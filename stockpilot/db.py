import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    country     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    material_id    TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    unit           TEXT NOT NULL,
    stock_qty      REAL NOT NULL,
    min_stock      REAL NOT NULL,
    unit_cost      REAL NOT NULL,
    lead_time_days INTEGER NOT NULL,
    supplier_id    TEXT REFERENCES suppliers(supplier_id)
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bom (
    product_id   TEXT NOT NULL REFERENCES products(product_id),
    material_id  TEXT NOT NULL REFERENCES materials(material_id),
    qty_per_unit REAL NOT NULL,
    PRIMARY KEY (product_id, material_id)
);

CREATE TABLE IF NOT EXISTS production_orders (
    order_id       TEXT PRIMARY KEY,
    product_id     TEXT NOT NULL REFERENCES products(product_id),
    quantity       INTEGER NOT NULL,
    start_date     TEXT NOT NULL,
    due_date       TEXT NOT NULL,
    status         TEXT NOT NULL,
    completed_date TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id         TEXT PRIMARY KEY,
    material_id   TEXT NOT NULL REFERENCES materials(material_id),
    supplier_id   TEXT NOT NULL REFERENCES suppliers(supplier_id),
    quantity      REAL NOT NULL,
    order_date    TEXT NOT NULL,
    expected_date TEXT NOT NULL,
    received_date TEXT,
    status        TEXT NOT NULL,
    received_qty  REAL NOT NULL DEFAULT 0,
    rejected_qty  REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_production_orders_due ON production_orders(due_date);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_material ON purchase_orders(material_id);
"""

DEFAULT_META = {"dataset": "Synthetic demo data", "currency": "EUR"}


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def set_meta(conn: sqlite3.Connection, **values: str) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        [(k, str(v)) for k, v in values.items()],
    )
    conn.commit()


def set_reference_date(conn: sqlite3.Connection, ref: date) -> None:
    set_meta(conn, reference_date=ref.isoformat())


def reference_date(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT value FROM meta WHERE key = 'reference_date'").fetchone()
    return date.fromisoformat(row[0]) if row else date.today()


def dataset_info(conn: sqlite3.Connection) -> dict:
    info = dict(DEFAULT_META)
    info.update(dict(conn.execute("SELECT key, value FROM meta").fetchall()))
    info["reference_date"] = reference_date(conn).isoformat()
    return info
