import json
from types import SimpleNamespace as NS

from stockpilot.assistant import OllamaAssistant, StockPilotAssistant


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def text(t):
    return NS(type="text", text=t)


def test_tool_call_then_answer(db_path):
    client = FakeClient([
        NS(stop_reason="tool_use", content=[tool_use("t1", "materials_below_min_stock", {"category": None})]),
        NS(stop_reason="end_turn", content=[text("Two materials are below minimum stock.")]),
    ])
    reply = StockPilotAssistant(db_path, client=client).ask("Which materials are below minimum stock?")

    assert reply.text == "Two materials are below minimum stock."
    assert len(reply.tool_calls) == 1
    assert list(reply.tool_calls[0].table["material_id"]) == ["M001", "M002"]

    result_msg = client.requests[1]["messages"][-1]
    assert result_msg["role"] == "user"
    result = result_msg["content"][0]
    assert result["tool_use_id"] == "t1"
    assert json.loads(result["content"])["rows_total"] == 2
    assert "2026-01-15" in client.requests[0]["system"]


def test_parallel_tool_calls_returned_in_one_message(db_path):
    client = FakeClient([
        NS(stop_reason="tool_use", content=[
            tool_use("a", "delayed_production_orders", {"min_days_late": None, "include_completed": None}),
            tool_use("b", "late_purchase_orders", {"supplier": None, "include_received": None}),
        ]),
        NS(stop_reason="end_turn", content=[text("done")]),
    ])
    reply = StockPilotAssistant(db_path, client=client).ask("What is late?")
    assert [c.name for c in reply.tool_calls] == ["delayed_production_orders", "late_purchase_orders"]
    results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_invalid_tool_input_reported_as_error(db_path):
    client = FakeClient([
        NS(stop_reason="tool_use", content=[tool_use("t1", "materials_below_min_stock", {"category": "Food"})]),
        NS(stop_reason="end_turn", content=[text("No such category.")]),
    ])
    reply = StockPilotAssistant(db_path, client=client).ask("Food stock?")
    assert reply.tool_calls[0].error
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


def test_answer_without_tools(db_path):
    client = FakeClient([NS(stop_reason="end_turn", content=[text("Hello! Ask me about stock.")])])
    reply = StockPilotAssistant(db_path, client=client).ask("Hi")
    assert reply.tool_calls == []
    assert len(client.requests) == 1


def test_refusal(db_path):
    client = FakeClient([NS(stop_reason="refusal", content=[])])
    reply = StockPilotAssistant(db_path, client=client).ask("...")
    assert "can't help" in reply.text


class FakeOllama:
    def __init__(self, messages):
        self.messages = list(messages)
        self.requests = []

    def chat(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return NS(message=self.messages.pop(0))


def ollama_call(name, args):
    return NS(function=NS(name=name, arguments=args))


def test_ollama_tool_call_with_loose_types(db_path):
    client = FakeOllama([
        NS(role="assistant", content="", tool_calls=[
            ollama_call("delayed_production_orders", {"min_days_late": "1", "include_completed": "true"}),
        ]),
        NS(role="assistant", content="Two orders are late.", tool_calls=None),
    ])
    reply = OllamaAssistant(db_path, client=client).ask("Late orders?")

    assert reply.text == "Two orders are late."
    call = reply.tool_calls[0]
    assert call.error is None
    assert call.args == {"min_days_late": 1, "include_completed": True}
    assert list(call.table["order_id"]) == ["PO-1", "PO-3"]

    first = client.requests[0]["messages"]
    assert first[0]["role"] == "system" and "2026-01-15" in first[0]["content"]
    tool_msg = client.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "delayed_production_orders"
    assert json.loads(tool_msg["content"])["rows_total"] == 2


def test_ollama_definitions_shape():
    from stockpilot.tools import ollama_tool_definitions
    for d in ollama_tool_definitions(["Component"]):
        assert d["type"] == "function"
        assert d["function"]["parameters"]["type"] == "object"


def test_history_is_sent(db_path):
    client = FakeClient([NS(stop_reason="end_turn", content=[text("ok")])])
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    StockPilotAssistant(db_path, client=client).ask("q2", history)
    assert [m["content"] for m in client.requests[0]["messages"]] == ["q1", "a1", "q2"]
