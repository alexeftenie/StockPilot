from datetime import date

import pandas as pd

from stockpilot.db import connect
from stockpilot.generate import generate


def test_generate_is_reproducible_and_consistent(tmp_path):
    a = generate(tmp_path / "a.db", seed=1, today=date(2026, 11, 16))
    b = generate(tmp_path / "b.db", seed=1, today=date(2026, 11, 16))
    with connect(a) as ca, connect(b) as cb:
        for table in ["materials", "production_orders", "purchase_orders", "bom"]:
            pd.testing.assert_frame_equal(
                pd.read_sql(f"SELECT * FROM {table}", ca), pd.read_sql(f"SELECT * FROM {table}", cb)
            )
        orders = pd.read_sql("SELECT * FROM production_orders", ca)
        assert set(orders["status"]) <= {"Planned", "In progress", "Completed"}
        assert orders.loc[orders["status"] == "Completed", "completed_date"].notna().all()
        assert (orders["completed_date"].dropna() <= "2026-11-16").all()
        below = ca.execute("SELECT COUNT(*) FROM materials WHERE stock_qty < min_stock").fetchone()[0]
        assert below > 0
