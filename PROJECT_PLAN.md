# StockPilot

## Project Idea

An AI assistant for stock and production planning. Users ask questions in natural language, such as "Which materials are below minimum stock?" or "Which production orders are delayed?", and get an answer together with the data table it is based on.

The project uses synthetic data only and combines AI with supply chain processes.

## Architecture

```
User (Streamlit chat)
        │ question
        ▼
   LLM (tool calling)
        │ picks the right function + parameters
        ▼
   Analysis functions (Python + pandas)
        │ query
        ▼
   Synthetic data (SQLite)
        │ result (table)
        ▼
   LLM → answer written only from the result
        ▼
   Chat: answer + the table used
```

Design decision: the model does not generate SQL. It chooses from functions written by me and supplies their parameters. The answer is based only on the data those functions return, which makes the system safer, easier to test and easier to explain.

## Tech Stack

| Component | Technology |
| --- | --- |
| Language | Python 3.11+ |
| Data processing | pandas |
| Database | SQLite |
| Model | LLM API with tool calling support |
| Interface | Streamlit (chat) |
| Testing | pytest |
| Configuration | python-dotenv |
| Version control | Git / GitHub |
