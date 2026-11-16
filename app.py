from contextlib import closing

import anthropic
import streamlit as st

from stockpilot import config
from stockpilot.adventureworks import import_adventureworks
from stockpilot.assistant import make_assistant
from stockpilot.db import connect, dataset_info
from stockpilot.generate import generate

EXAMPLES = [
    "Which materials are below minimum stock?",
    "Which production orders are delayed?",
    "Do we have enough material for the orders starting in the next 2 weeks?",
    "Which suppliers have the highest rejection rate?",
    "What is our stock value per category?",
    "Which purchase orders are overdue?",
]

st.set_page_config(page_title="StockPilot", page_icon="📦", layout="wide")


def ensure_database() -> None:
    if config.DB_PATH.exists():
        return
    if config.DATASET == "adventureworks":
        with st.spinner("Building the AdventureWorks database (first run downloads about 15 MB)..."):
            import_adventureworks(config.DB_PATH)
    else:
        generate(config.DB_PATH)


ensure_database()

if "history" not in st.session_state:
    st.session_state.history = []


@st.cache_resource
def get_assistant():
    return make_assistant()


def show_tool_calls(tool_calls) -> None:
    for call in tool_calls:
        args = ", ".join(f"{k}={v!r}" for k, v in call.args.items())
        label = f"Data used: `{call.name}({args})`"
        if call.error:
            st.caption(f"{label} - error: {call.error}")
            continue
        with st.expander(f"{label} - {len(call.table)} rows", expanded=True):
            st.dataframe(call.table, hide_index=True)


with closing(connect(config.DB_PATH)) as _conn:
    info = dataset_info(_conn)

with st.sidebar:
    st.title("📦 StockPilot")
    st.caption("AI assistant for stock and production planning.")
    st.caption(f"Dataset: {info['dataset']}")
    st.caption(f"Today in the dataset: {info['reference_date']} · Currency: {info['currency']}")
    st.caption(f"Model: `{get_assistant().label}`")
    st.subheader("Try a question")
    clicked = None
    for q in EXAMPLES:
        if st.button(q, use_container_width=True):
            clicked = q
    st.divider()
    if config.DATASET != "adventureworks" and st.button("Regenerate synthetic data"):
        generate(config.DB_PATH)
        st.success("New dataset generated.")
    if st.button("Clear chat"):
        st.session_state.history = []
        st.rerun()

st.header("Ask about stock, production and suppliers")

for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        show_tool_calls(msg.get("tool_calls", []))

question = st.chat_input("e.g. Which materials are below minimum stock?") or clicked
if question:
    with st.chat_message("user"):
        st.markdown(question)

    prior = [{"role": m["role"], "content": m["content"]} for m in st.session_state.history]
    st.session_state.history.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        try:
            with st.spinner("Analyzing..."):
                reply = get_assistant().ask(question, prior)
        except anthropic.AuthenticationError:
            st.error("Missing or invalid API key. Put ANTHROPIC_API_KEY in the .env file.")
            st.session_state.history.pop()
            st.stop()
        except anthropic.APIConnectionError:
            st.error("Could not reach the Claude API. Check your internet connection.")
            st.session_state.history.pop()
            st.stop()
        except anthropic.APIStatusError as e:
            st.error(f"API error ({e.status_code}): {e.message}")
            st.session_state.history.pop()
            st.stop()
        except ConnectionError:
            st.error("Could not reach Ollama. Is it running? Start the Ollama app or run `ollama serve`.")
            st.session_state.history.pop()
            st.stop()
        except Exception as e:
            st.error(f"Error: {e}")
            st.session_state.history.pop()
            st.stop()

        st.markdown(reply.text)
        show_tool_calls(reply.tool_calls)

    st.session_state.history.append(
        {"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls}
    )
