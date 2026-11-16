import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATASET = (os.getenv("STOCKPILOT_DATASET") or "synthetic").strip().lower()

SYNTHETIC_DB_PATH = ROOT / "data" / "stockpilot.db"
AW_DB_PATH = ROOT / "data" / "adventureworks.db"
AW_SOURCE_DIR = ROOT / "data" / "adventureworks"

DB_PATH = Path(os.getenv("STOCKPILOT_DB") or (AW_DB_PATH if DATASET == "adventureworks" else SYNTHETIC_DB_PATH))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH

PROVIDER = os.getenv("STOCKPILOT_PROVIDER", "anthropic").strip().lower()

MODEL = os.getenv("STOCKPILOT_MODEL") or "claude-opus-5-5"
EFFORT = os.getenv("STOCKPILOT_EFFORT") or "medium"

OLLAMA_MODEL = os.getenv("STOCKPILOT_OLLAMA_MODEL") or "qwen2.5:7b"
OLLAMA_NUM_CTX = int(os.getenv("STOCKPILOT_OLLAMA_NUM_CTX") or 8192)
OLLAMA_MAX_ROWS = 25

MAX_ROWS_TO_MODEL = 50
MAX_TOOL_ROUNDS = 6
