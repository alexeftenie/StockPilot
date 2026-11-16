import json

import pandas as pd
import pytest

from stockpilot.tools import ToolError, build_tools, run_tool, table_for_model, tool_definitions

CATEGORIES = ["Component", "Packaging", "Raw material"]


def test_definitions_are_strict_and_complete():
    for d in tool_definitions(CATEGORIES):
        schema = d["input_schema"]
        assert d["strict"] is True
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert d["description"]


def test_category_list_comes_from_data():
    d = next(d for d in tool_definitions(CATEGORIES) if d["name"] == "materials_below_min_stock")
    assert "Raw material" in d["input_schema"]["properties"]["category"]["description"]


def test_tool_names_unique():
    names = [t.name for t in build_tools(CATEGORIES)]
    assert len(names) == len(set(names))


def test_run_tool_applies_defaults(conn):
    args, df = run_tool(conn, "delayed_production_orders", {"min_days_late": None, "include_completed": None})
    assert args == {"min_days_late": 1, "include_completed": False}
    assert list(df["order_id"]) == ["PO-1"]


def test_run_tool_normalizes_enum(conn):
    args, df = run_tool(conn, "materials_below_min_stock", {"category": "raw MATERIAL"})
    assert args["category"] == "Raw material"
    assert list(df["material_id"]) == ["M001"]


@pytest.mark.parametrize("name,args", [
    ("no_such_tool", {}),
    ("materials_below_min_stock", {"category": "Food"}),
    ("delayed_production_orders", {"min_days_late": 0}),
    ("delayed_production_orders", {"min_days_late": "5"}),
    ("delayed_production_orders", {"include_completed": "yes"}),
    ("material_requirements", {"horizon_days": 1000}),
    ("find_material", {"query": None}),
    ("find_material", {"query": "bolt", "sql": "DROP TABLE materials"}),
])
def test_run_tool_rejects_bad_input(conn, name, args):
    with pytest.raises(ToolError):
        run_tool(conn, name, args)


def test_table_for_model_truncates():
    df = pd.DataFrame({"a": range(10)})
    payload = json.loads(table_for_model(df, max_rows=3))
    assert payload["rows_total"] == 10
    assert payload["rows_shown"] == 3
    assert payload["rows"] == [{"a": 0}, {"a": 1}, {"a": 2}]
    assert "note" in payload
