from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import config
from .analysis import material_categories
from .db import connect, dataset_info
from .tools import ToolError, ollama_tool_definitions, run_tool, table_for_model, tool_definitions

FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"}

SYSTEM_PROMPT = """You are StockPilot, an assistant for stock and production planning.

You answer questions about materials, stock levels, production orders, purchase orders and \
suppliers of a manufacturing company. You have no direct database access: the only way to get \
data is through the provided tools.

Dataset: {dataset}. Monetary values are in {currency}. Today's date in the dataset is {today}.

Rules:
- For any question about the company's data, call the most suitable tool(s) first.
- Base your answer only on the tool results in this conversation. Never invent numbers, \
materials, orders or suppliers. If the results don't contain the answer, say so.
- If no tool can answer the question, say which kinds of questions you can answer instead.
- Keep the answer short: a direct answer first, then the key figures. The user sees the full \
result table under your answer, so don't repeat every row - highlight what matters.
- Always answer in English, whatever language the question is in."""


def _system_prompt(conn) -> str:
    info = dataset_info(conn)
    return SYSTEM_PROMPT.format(dataset=info["dataset"], currency=info["currency"],
                                today=info["reference_date"])

TOO_MANY_STEPS = ("I couldn't finish answering within the allowed number of steps. "
                  "Please try a more specific question.")


@dataclass
class ToolCall:
    name: str
    args: dict
    table: pd.DataFrame | None = None
    error: str | None = None


@dataclass
class AssistantReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


def _execute(conn, name: str, args, calls: list[ToolCall], max_rows: int,
             lenient: bool = False) -> tuple[str, bool]:
    args = args if isinstance(args, dict) else {}
    try:
        clean, df = run_tool(conn, name, args, lenient=lenient)
    except ToolError as e:
        calls.append(ToolCall(name, args, error=str(e)))
        return f"Error: {e}", True
    calls.append(ToolCall(name, clean, table=df))
    return table_for_model(df, max_rows), False


class StockPilotAssistant:
    def __init__(
        self,
        db_path: Path | str = config.DB_PATH,
        client=None,
        model: str = config.MODEL,
        effort: str = config.EFFORT,
    ):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.db_path = db_path
        self.client = client
        self.model = model
        self.effort = effort

    @property
    def label(self) -> str:
        return f"Claude · {self.model}"

    def ask(self, question: str, history: list[dict] | None = None) -> AssistantReply:
        calls: list[ToolCall] = []
        messages = [*(history or []), {"role": "user", "content": question}]

        with closing(connect(self.db_path)) as conn:
            system = _system_prompt(conn)
            tools = tool_definitions(material_categories(conn))

            for _ in range(config.MAX_TOOL_ROUNDS):
                extra = {}
                if self.model in FALLBACK_MODELS:
                    extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=system,
                    tools=tools,
                    messages=messages,
                    output_config={"effort": self.effort},
                    **extra,
                )

                if response.stop_reason == "refusal":
                    return AssistantReply("Sorry, I can't help with that request.", calls)

                if response.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": response.content})
                    continue

                if response.stop_reason != "tool_use":
                    return AssistantReply(_claude_text(response), calls)

                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    content, is_error = _execute(conn, block.name, block.input, calls,
                                                 config.MAX_ROWS_TO_MODEL)
                    result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
                    if is_error:
                        result["is_error"] = True
                    results.append(result)
                messages.append({"role": "user", "content": results})

        return AssistantReply(TOO_MANY_STEPS, calls)


def _claude_text(response) -> str:
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens":
        text += "\n\n(Answer truncated.)"
    return text or "(No answer was produced.)"


class OllamaAssistant:
    def __init__(
        self,
        db_path: Path | str = config.DB_PATH,
        client=None,
        model: str = config.OLLAMA_MODEL,
        num_ctx: int = config.OLLAMA_NUM_CTX,
    ):
        if client is None:
            import ollama
            client = ollama.Client()
        self.db_path = db_path
        self.client = client
        self.model = model
        self.num_ctx = num_ctx

    @property
    def label(self) -> str:
        return f"Ollama · {self.model}"

    def ask(self, question: str, history: list[dict] | None = None) -> AssistantReply:
        calls: list[ToolCall] = []
        with closing(connect(self.db_path)) as conn:
            system = _system_prompt(conn)
            tools = ollama_tool_definitions(material_categories(conn))
            messages = [{"role": "system", "content": system},
                        *(history or []),
                        {"role": "user", "content": question}]

            for _ in range(config.MAX_TOOL_ROUNDS):
                response = self.client.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options={"num_ctx": self.num_ctx, "temperature": 0},
                )
                msg = response.message
                tool_calls = msg.tool_calls or []
                if not tool_calls:
                    text = (msg.content or "").strip()
                    return AssistantReply(text or "(No answer was produced.)", calls)

                messages.append(msg)
                for tc in tool_calls:
                    name = tc.function.name
                    content, _ = _execute(conn, name, dict(tc.function.arguments or {}), calls,
                                          config.OLLAMA_MAX_ROWS, lenient=True)
                    messages.append({"role": "tool", "content": content, "tool_name": name})

        return AssistantReply(TOO_MANY_STEPS, calls)


def make_assistant(db_path: Path | str = config.DB_PATH):
    if config.PROVIDER == "ollama":
        return OllamaAssistant(db_path)
    if config.PROVIDER == "anthropic":
        return StockPilotAssistant(db_path)
    raise ValueError(f"Unknown STOCKPILOT_PROVIDER: {config.PROVIDER!r} (use 'anthropic' or 'ollama')")
