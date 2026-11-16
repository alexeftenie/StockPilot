import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from . import analysis


class ToolError(Exception):
    pass


@dataclass
class Param:
    name: str
    type: str
    description: str
    default: Any = None
    enum: list[str] | None = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., pd.DataFrame]
    params: list[Param] = field(default_factory=list)

    def definition(self) -> dict:
        props = {}
        for p in self.params:
            schema: dict[str, Any] = {
                "type": [p.type, "null"],
                "description": f"{p.description} Use null for the default ({p.default!r}).",
            }
            if p.enum:
                schema["description"] += f" Allowed values: {', '.join(p.enum)}."
            props[p.name] = schema
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": [p.name for p in self.params],
                "additionalProperties": False,
            },
        }

    def ollama_definition(self) -> dict:
        props = {}
        for p in self.params:
            desc = f"{p.description} Optional, default {p.default!r}."
            if p.enum:
                desc += f" Allowed values: {', '.join(p.enum)}."
            props[p.name] = {"type": p.type, "description": desc}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": []},
            },
        }

    def loosen(self, args: dict) -> dict:
        types = {p.name: p.type for p in self.params}
        out = {}
        for k, v in args.items():
            if isinstance(v, str):
                s = v.strip()
                if s.lower() in ("", "null", "none"):
                    v = None
                elif types.get(k) == "integer" and s.lstrip("-").isdigit():
                    v = int(s)
                elif types.get(k) == "boolean" and s.lower() in ("true", "false"):
                    v = s.lower() == "true"
            out[k] = v
        return out

    def validate(self, args: dict | None) -> dict:
        args = dict(args or {})
        known = {p.name for p in self.params}
        unknown = set(args) - known
        if unknown:
            raise ToolError(f"Unknown parameter(s) for {self.name}: {sorted(unknown)}")
        clean = {}
        for p in self.params:
            value = args.get(p.name)
            if value is None:
                clean[p.name] = p.default
                continue
            if p.type == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ToolError(f"'{p.name}' must be an integer")
                if p.minimum is not None and value < p.minimum:
                    raise ToolError(f"'{p.name}' must be >= {p.minimum}")
                if p.maximum is not None and value > p.maximum:
                    raise ToolError(f"'{p.name}' must be <= {p.maximum}")
            elif p.type == "boolean":
                if not isinstance(value, bool):
                    raise ToolError(f"'{p.name}' must be true or false")
            elif p.type == "string":
                if not isinstance(value, str) or not value.strip():
                    raise ToolError(f"'{p.name}' must be a non-empty string")
                value = value.strip()
                if p.enum:
                    match = next((e for e in p.enum if e.lower() == value.lower()), None)
                    if match is None:
                        raise ToolError(f"'{p.name}' must be one of {p.enum}")
                    value = match
            clean[p.name] = value
        return clean


def build_tools(categories: list[str]) -> list[Tool]:
    return [
        Tool(
            "materials_below_min_stock",
            "List materials whose current stock is below their minimum stock level, "
            "with shortfall, coverage % and supplier. Optionally filter by category.",
            analysis.materials_below_min_stock,
            [Param("category", "string", "Material category to filter by.", None, enum=categories or None)],
        ),
        Tool(
            "delayed_production_orders",
            "List production orders that are late: open orders past their due date, "
            "with days late. Can also include orders that were completed after the due date.",
            analysis.delayed_production_orders,
            [
                Param("min_days_late", "integer", "Only orders at least this many days late.", 1,
                      minimum=1, maximum=365),
                Param("include_completed", "boolean", "Also include orders completed late.", False),
            ],
        ),
        Tool(
            "late_purchase_orders",
            "List purchase orders from suppliers that were not delivered by the expected date. "
            "Optionally filter by supplier name and include orders that were received late.",
            analysis.late_purchase_orders,
            [
                Param("supplier", "string", "Part of the supplier name to filter by.", None),
                Param("include_received", "boolean", "Also include orders received late.", False),
            ],
        ),
        Tool(
            "supplier_performance",
            "Per supplier: on-time delivery rate and average delay (null when receipt dates are not "
            "recorded), short deliveries, rejected quantity % (quality) and open late orders.",
            analysis.supplier_performance,
        ),
        Tool(
            "material_requirements",
            "Compare the material required by planned (not yet started) production orders that "
            "start within a time horizon against current stock plus incoming purchase orders. "
            "Shows material shortages.",
            analysis.material_requirements,
            [
                Param("horizon_days", "integer", "Look ahead this many days.", 30, minimum=1, maximum=365),
                Param("only_shortages", "boolean", "Return only materials with a shortage.", True),
            ],
        ),
        Tool(
            "stock_value_by_category",
            "Inventory value, number of materials and number below minimum stock, per category.",
            analysis.stock_value_by_category,
        ),
        Tool(
            "find_material",
            "Look up materials by partial name or exact material ID (e.g. 'bolt' or 'HN-1220'). "
            "Returns stock, minimum stock, cost, lead time, supplier and open purchase order quantity.",
            analysis.find_material,
            [Param("query", "string", "Material name fragment or material ID.", None)],
        ),
    ]


def tool_definitions(categories: list[str]) -> list[dict]:
    return [t.definition() for t in build_tools(categories)]


def ollama_tool_definitions(categories: list[str]) -> list[dict]:
    return [t.ollama_definition() for t in build_tools(categories)]


def run_tool(
    conn: sqlite3.Connection, name: str, args: dict | None, lenient: bool = False
) -> tuple[dict, pd.DataFrame]:
    tools = {t.name: t for t in build_tools(analysis.material_categories(conn))}
    tool = tools.get(name)
    if tool is None:
        raise ToolError(f"Unknown tool: {name}")
    if lenient:
        args = tool.loosen(dict(args or {}))
    clean = tool.validate(args)
    if name == "find_material" and not clean["query"]:
        raise ToolError("'query' is required")
    return clean, tool.func(conn, **clean)


def table_for_model(df: pd.DataFrame, max_rows: int) -> str:
    shown = df.head(max_rows)
    payload = {
        "rows_total": len(df),
        "rows_shown": len(shown),
        "columns": list(df.columns),
        "rows": json.loads(shown.to_json(orient="records")),
    }
    if len(df) > max_rows:
        payload["note"] = f"Only the first {max_rows} rows are shown; the user sees the full table."
    return json.dumps(payload, ensure_ascii=False)
