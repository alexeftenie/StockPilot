import sqlite3

import pandas as pd

from .db import reference_date


def _ref(conn: sqlite3.Connection) -> pd.Timestamp:
    return pd.Timestamp(reference_date(conn))


def _as_date_str(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = df[c].dt.strftime("%Y-%m-%d")
    return df


def materials_below_min_stock(conn: sqlite3.Connection, category: str | None = None) -> pd.DataFrame:
    sql = """
        SELECT m.material_id, m.name, m.category, m.unit,
               m.stock_qty, m.min_stock,
               ROUND(m.min_stock - m.stock_qty, 2)          AS shortfall,
               ROUND(100.0 * m.stock_qty / m.min_stock, 1)   AS coverage_pct,
               m.lead_time_days, s.name AS supplier
        FROM materials m
        LEFT JOIN suppliers s ON s.supplier_id = m.supplier_id
        WHERE m.stock_qty < m.min_stock
          AND (:category IS NULL OR LOWER(m.category) = LOWER(:category))
        ORDER BY coverage_pct ASC, m.material_id
    """
    return pd.read_sql(sql, conn, params={"category": category})


def delayed_production_orders(
    conn: sqlite3.Connection, min_days_late: int = 1, include_completed: bool = False
) -> pd.DataFrame:
    df = pd.read_sql(
        """SELECT o.order_id, p.name AS product, o.quantity, o.status,
                  o.start_date, o.due_date, o.completed_date
           FROM production_orders o JOIN products p ON p.product_id = o.product_id""",
        conn,
        parse_dates=["start_date", "due_date", "completed_date"],
    )
    is_open = df["status"] != "Completed"
    end = df["completed_date"].where(~is_open, _ref(conn))
    df["days_late"] = (end - df["due_date"]).dt.days
    mask = df["days_late"] >= min_days_late
    if not include_completed:
        mask &= is_open
    df = df[mask].sort_values(["days_late", "order_id"], ascending=[False, True])
    df = _as_date_str(df, ["start_date", "due_date", "completed_date"])
    return df.reset_index(drop=True)


def late_purchase_orders(
    conn: sqlite3.Connection, supplier: str | None = None, include_received: bool = False
) -> pd.DataFrame:
    df = pd.read_sql(
        """SELECT po.po_id, m.name AS material, s.name AS supplier, po.quantity, m.unit,
                  po.order_date, po.expected_date, po.received_date, po.status,
                  po.received_qty, po.rejected_qty
           FROM purchase_orders po
           JOIN materials m ON m.material_id = po.material_id
           JOIN suppliers s ON s.supplier_id = po.supplier_id""",
        conn,
        parse_dates=["order_date", "expected_date", "received_date"],
    )
    if supplier:
        df = df[df["supplier"].str.contains(supplier, case=False, regex=False)]
    is_open = df["status"] == "Open"
    end = df["received_date"].where(~is_open, _ref(conn))
    df = df.assign(days_late=(end - df["expected_date"]).dt.days)
    mask = df["days_late"] >= 1
    if not include_received:
        mask &= is_open
    df = df[mask].sort_values(["days_late", "po_id"], ascending=[False, True])
    df = _as_date_str(df, ["order_date", "expected_date", "received_date"])
    return df.reset_index(drop=True)


def supplier_performance(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        """SELECT s.name AS supplier, s.country, po.status, po.quantity,
                  po.received_qty, po.rejected_qty, po.expected_date, po.received_date
           FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id""",
        conn,
        parse_dates=["expected_date", "received_date"],
    )
    ref = _ref(conn)
    received = df["status"] == "Received"
    dated = received & df["received_date"].notna()
    delay = (df["received_date"] - df["expected_date"]).dt.days.clip(lower=0)
    df = df.assign(
        received=received,
        dated=dated,
        delay=delay,
        on_time=dated & (delay == 0),
        short=received & (df["received_qty"] < df["quantity"]),
        open_late=(df["status"] == "Open") & (df["expected_date"] < ref),
        recv_qty=df["received_qty"].where(received, 0),
        rej_qty=df["rejected_qty"].where(received, 0),
    )

    out = df.groupby(["supplier", "country"]).agg(
        total_orders=("status", "size"),
        received_orders=("received", "sum"),
        dated_orders=("dated", "sum"),
        on_time_orders=("on_time", "sum"),
        avg_delay_days=("delay", "mean"),
        short_deliveries=("short", "sum"),
        received_qty=("recv_qty", "sum"),
        rejected_qty=("rej_qty", "sum"),
        open_late_orders=("open_late", "sum"),
    ).reset_index()
    out["on_time_rate_pct"] = (100 * out["on_time_orders"] / out["dated_orders"].where(out["dated_orders"] > 0)).round(1)
    out["rejected_pct"] = (100 * out["rejected_qty"] / out["received_qty"].where(out["received_qty"] > 0)).round(2)
    out["avg_delay_days"] = out["avg_delay_days"].round(1)
    cols = ["supplier", "country", "total_orders", "received_orders", "on_time_rate_pct",
            "avg_delay_days", "short_deliveries", "rejected_pct", "open_late_orders"]
    out = out[cols].sort_values(["on_time_rate_pct", "rejected_pct"], ascending=[True, False],
                                na_position="last")
    return out.reset_index(drop=True)


def material_requirements(
    conn: sqlite3.Connection, horizon_days: int = 30, only_shortages: bool = True
) -> pd.DataFrame:
    ref = _ref(conn)
    horizon_end = (ref + pd.Timedelta(days=horizon_days)).strftime("%Y-%m-%d")

    req = pd.read_sql(
        """SELECT b.material_id, SUM(o.quantity * b.qty_per_unit) AS required_qty,
                   COUNT(DISTINCT o.order_id) AS orders
            FROM production_orders o JOIN bom b ON b.product_id = o.product_id
            WHERE o.status = 'Planned' AND o.start_date <= :end
            GROUP BY b.material_id""",
        conn, params={"end": horizon_end},
    )
    incoming = pd.read_sql(
        """SELECT material_id, SUM(quantity) AS incoming_qty
           FROM purchase_orders WHERE status = 'Open' AND expected_date <= :end
           GROUP BY material_id""",
        conn, params={"end": horizon_end},
    )
    mats = pd.read_sql("SELECT material_id, name, unit, stock_qty FROM materials", conn)

    df = req.merge(mats, on="material_id").merge(incoming, on="material_id", how="left")
    df["incoming_qty"] = df["incoming_qty"].fillna(0)
    df["available_qty"] = df["stock_qty"] + df["incoming_qty"]
    df["shortage_qty"] = (df["required_qty"] - df["available_qty"]).clip(lower=0).round(2)
    if only_shortages:
        df = df[df["shortage_qty"] > 0]
    cols = ["material_id", "name", "unit", "orders", "required_qty", "stock_qty",
            "incoming_qty", "available_qty", "shortage_qty"]
    return df[cols].sort_values(["shortage_qty", "material_id"], ascending=[False, True]).reset_index(drop=True)


def stock_value_by_category(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT category,
               COUNT(*)                              AS materials,
               SUM(stock_qty < min_stock)            AS below_min,
               ROUND(SUM(stock_qty * unit_cost), 2)  AS stock_value
        FROM materials
        GROUP BY category
        ORDER BY stock_value DESC
    """
    return pd.read_sql(sql, conn)


def material_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT category FROM materials ORDER BY category").fetchall()
    return [r[0] for r in rows]


def find_material(conn: sqlite3.Connection, query: str) -> pd.DataFrame:
    sql = """
        SELECT m.material_id, m.name, m.category, m.unit, m.stock_qty, m.min_stock,
               m.unit_cost, m.lead_time_days, s.name AS supplier,
               COALESCE((SELECT SUM(quantity) FROM purchase_orders po
                         WHERE po.material_id = m.material_id AND po.status = 'Open'), 0)
                   AS open_po_qty
        FROM materials m LEFT JOIN suppliers s ON s.supplier_id = m.supplier_id
        WHERE LOWER(m.name) LIKE '%' || LOWER(:q) || '%' OR UPPER(m.material_id) = UPPER(:q)
        ORDER BY m.material_id
    """
    return pd.read_sql(sql, conn, params={"q": query})
