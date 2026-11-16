from stockpilot import analysis


def test_materials_below_min_stock(conn):
    df = analysis.materials_below_min_stock(conn)
    assert list(df["material_id"]) == ["M001", "M002"]
    assert list(df["shortfall"]) == [50, 100]
    assert list(df["coverage_pct"]) == [50.0, 90.0]


def test_materials_below_min_stock_by_category(conn):
    df = analysis.materials_below_min_stock(conn, category="component")
    assert list(df["material_id"]) == ["M002"]


def test_delayed_production_orders(conn):
    df = analysis.delayed_production_orders(conn)
    assert list(df["order_id"]) == ["PO-1"]
    assert df.loc[0, "days_late"] == 5


def test_delayed_production_orders_include_completed(conn):
    df = analysis.delayed_production_orders(conn, include_completed=True)
    assert list(df["order_id"]) == ["PO-1", "PO-3"]
    assert list(df["days_late"]) == [5, 3]


def test_delayed_production_orders_min_days(conn):
    assert analysis.delayed_production_orders(conn, min_days_late=6).empty


def test_late_purchase_orders(conn):
    df = analysis.late_purchase_orders(conn)
    assert list(df["po_id"]) == ["PUR-2"]
    assert df.loc[0, "days_late"] == 9


def test_late_purchase_orders_filters(conn):
    df = analysis.late_purchase_orders(conn, include_received=True)
    assert list(df["po_id"]) == ["PUR-2", "PUR-3"]
    assert analysis.late_purchase_orders(conn, supplier="good").empty


def test_supplier_performance(conn):
    df = analysis.supplier_performance(conn).set_index("supplier")
    assert df.loc["Slow Supplier", "on_time_rate_pct"] == 0.0
    assert df.loc["Slow Supplier", "avg_delay_days"] == 4.0
    assert df.loc["Slow Supplier", "open_late_orders"] == 1
    assert df.loc["Slow Supplier", "short_deliveries"] == 1
    assert df.loc["Slow Supplier", "rejected_pct"] == 10.0
    assert df.loc["Good Supplier", "on_time_rate_pct"] == 100.0
    assert df.loc["Good Supplier", "open_late_orders"] == 0
    assert df.loc["Good Supplier", "rejected_pct"] == 0.0
    assert df.loc["Good Supplier", "total_orders"] == 3


def test_supplier_performance_without_receipt_dates(conn):
    conn.execute("UPDATE purchase_orders SET received_date = NULL")
    df = analysis.supplier_performance(conn).set_index("supplier")
    assert df["on_time_rate_pct"].isna().all()
    assert list(df.index) == ["Slow Supplier", "Good Supplier"]


def test_material_requirements(conn):
    assert analysis.material_requirements(conn, horizon_days=30, only_shortages=False).empty

    df = analysis.material_requirements(conn, horizon_days=60)
    assert list(df["material_id"]) == ["M001"]
    row = df.iloc[0]
    assert row["orders"] == 1
    assert row["required_qty"] == 100
    assert row["available_qty"] == 80
    assert row["shortage_qty"] == 20
    assert len(analysis.material_requirements(conn, horizon_days=60, only_shortages=False)) == 3


def test_stock_value_by_category(conn):
    df = analysis.stock_value_by_category(conn)
    assert list(df["category"]) == ["Packaging", "Raw material", "Component"]
    assert list(df["stock_value"]) == [500.0, 100.0, 90.0]
    assert list(df["below_min"]) == [0, 1, 1]


def test_material_categories(conn):
    assert analysis.material_categories(conn) == ["Component", "Packaging", "Raw material"]


def test_find_material(conn):
    df = analysis.find_material(conn, "bolt")
    assert list(df["material_id"]) == ["M002"]
    assert df.loc[0, "open_po_qty"] == 200
    assert list(analysis.find_material(conn, "m003")["material_id"]) == ["M003"]
