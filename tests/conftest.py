from datetime import date

import pytest

from stockpilot.db import connect, create_schema, set_reference_date


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    conn = connect(path)
    create_schema(conn)
    set_reference_date(conn, date(2026, 1, 15))
    conn.executemany("INSERT INTO suppliers VALUES (?, ?, ?)", [
        ("S01", "Good Supplier", "Romania"),
        ("S02", "Slow Supplier", "Bulgaria"),
    ])
    conn.executemany("INSERT INTO materials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("M001", "Steel sheet", "Raw material", "kg", 50, 100, 2.0, 10, "S01"),
        ("M002", "M6 bolt", "Component", "pcs", 900, 1000, 0.1, 5, "S02"),
        ("M003", "Cardboard box", "Packaging", "pcs", 500, 100, 1.0, 7, "S01"),
    ])
    conn.executemany("INSERT INTO products VALUES (?, ?)", [("P01", "Shelf")])
    conn.executemany("INSERT INTO bom VALUES (?, ?, ?)", [
        ("P01", "M001", 2), ("P01", "M002", 10), ("P01", "M003", 1),
    ])
    conn.executemany("INSERT INTO production_orders VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ("PO-1", "P01", 10, "2026-01-01", "2026-01-10", "In progress", None),
        ("PO-2", "P01", 20, "2026-01-05", "2026-01-20", "In progress", None),
        ("PO-3", "P01", 5, "2025-12-01", "2025-12-10", "Completed", "2025-12-13"),
        ("PO-4", "P01", 50, "2026-03-01", "2026-03-10", "Planned", None),
    ])
    conn.executemany("INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("PUR-1", "M001", "S01", 40, "2026-01-01", "2026-01-11", "2026-01-11", "Received", 40, 0),
        ("PUR-2", "M002", "S02", 200, "2026-01-01", "2026-01-06", None, "Open", 0, 0),
        ("PUR-3", "M002", "S02", 100, "2025-12-01", "2025-12-06", "2025-12-10", "Received", 90, 9),
        ("PUR-4", "M001", "S01", 30, "2026-01-10", "2026-01-20", None, "Open", 0, 0),
        ("PUR-5", "M003", "S01", 10, "2026-01-01", "2026-01-05", None, "Rejected", 0, 0),
    ])
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()
