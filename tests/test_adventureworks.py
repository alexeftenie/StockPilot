from datetime import date

import pytest

from stockpilot import analysis, config
from stockpilot.adventureworks import COLUMNS, import_adventureworks, read_table
from stockpilot.db import connect, dataset_info

HAS_SOURCE = all((config.AW_SOURCE_DIR / f"{name}.csv").exists() for name in COLUMNS)


def test_read_plus_pipe_format(tmp_path):
    (tmp_path / "BusinessEntityAddress.csv").write_text(
        "1+|249+|2+|guid-a+|2025-09-11 11:15:06.967&|\n"
        "2+|293+|2+|guid-b+|2025-09-11 11:15:06.967&|\n",
        encoding="utf-8",
    )
    df = read_table(tmp_path, "BusinessEntityAddress")
    assert list(df["AddressID"]) == ["249", "293"]
    assert df.loc[1, "ModifiedDate"] == "2025-09-11 11:15:06.967"


@pytest.fixture(scope="module")
def aw_conn(tmp_path_factory):
    if not HAS_SOURCE:
        pytest.skip("AdventureWorks CSV files not downloaded")
    path = import_adventureworks(tmp_path_factory.mktemp("aw") / "aw.db", ref=date(2025, 5, 20),
                                 download_missing=False)
    conn = connect(path)
    yield conn
    conn.close()


def test_import_counts_and_statuses(aw_conn):
    count = lambda t: aw_conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    assert count("production_orders") == 72591
    assert count("products") == 238
    assert count("suppliers") == 104
    assert count("materials") > 300
    statuses = dict(aw_conn.execute("SELECT status, COUNT(*) FROM production_orders GROUP BY status").fetchall())
    assert set(statuses) == {"Planned", "In progress", "Completed"}
    assert dataset_info(aw_conn)["currency"] == "USD"


def test_import_is_consistent(aw_conn):
    assert aw_conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert aw_conn.execute(
        "SELECT COUNT(*) FROM production_orders WHERE status = 'Completed' AND completed_date > '2025-05-20'"
    ).fetchone()[0] == 0
    assert aw_conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE order_date > '2025-05-20'"
    ).fetchone()[0] == 0


def test_analyses_run_on_adventureworks(aw_conn):
    assert analysis.material_categories(aw_conn) == ["Purchased part", "Resale item", "Subassembly"]
    assert not analysis.materials_below_min_stock(aw_conn).empty
    assert not analysis.delayed_production_orders(aw_conn).empty
    assert not analysis.supplier_performance(aw_conn).empty
    assert not analysis.material_requirements(aw_conn, horizon_days=14, only_shortages=False).empty
    assert len(analysis.find_material(aw_conn, "chain")) >= 1
