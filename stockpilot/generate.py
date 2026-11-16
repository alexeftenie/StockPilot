import argparse
import random
from datetime import date, timedelta
from pathlib import Path

from . import config
from .db import connect, create_schema, set_meta, set_reference_date

SUPPLIERS = [
    ("Carpathia Metals", "Romania", 0.90),
    ("Danube Plastics", "Bulgaria", 0.75),
    ("Nordic Fasteners", "Sweden", 0.95),
    ("Iberia Packaging", "Spain", 0.80),
    ("Baltic Chemicals", "Lithuania", 0.65),
    ("Alpine Electronics", "Austria", 0.85),
    ("Pannonia Steel", "Hungary", 0.70),
    ("Adria Components", "Croatia", 0.88),
]

MATERIALS = [
    ("Steel sheet 2mm", "Raw material", "kg", (1.5, 3.0)),
    ("Steel sheet 4mm", "Raw material", "kg", (1.6, 3.2)),
    ("Aluminium bar 20mm", "Raw material", "kg", (3.0, 5.5)),
    ("Aluminium profile 40x40", "Raw material", "m", (4.0, 8.0)),
    ("Copper wire 1.5mm", "Raw material", "m", (0.4, 0.9)),
    ("ABS granulate", "Raw material", "kg", (2.0, 3.5)),
    ("Polypropylene granulate", "Raw material", "kg", (1.2, 2.4)),
    ("Stainless tube 25mm", "Raw material", "m", (6.0, 11.0)),
    ("Plywood board 18mm", "Raw material", "pcs", (18.0, 30.0)),
    ("Rubber seal strip", "Raw material", "m", (0.8, 1.6)),
    ("M6 bolt", "Component", "pcs", (0.05, 0.12)),
    ("M8 bolt", "Component", "pcs", (0.08, 0.18)),
    ("M6 nut", "Component", "pcs", (0.02, 0.05)),
    ("Hinge 90mm", "Component", "pcs", (1.2, 2.8)),
    ("Door handle", "Component", "pcs", (3.0, 7.0)),
    ("Ball bearing 6204", "Component", "pcs", (2.0, 4.5)),
    ("DC motor 24V", "Component", "pcs", (25.0, 45.0)),
    ("Control board v2", "Component", "pcs", (38.0, 70.0)),
    ("Power supply 24V", "Component", "pcs", (18.0, 32.0)),
    ("LED indicator", "Component", "pcs", (0.3, 0.8)),
    ("Cable gland M20", "Component", "pcs", (0.5, 1.2)),
    ("Caster wheel 75mm", "Component", "pcs", (2.5, 5.0)),
    ("Gas spring 300N", "Component", "pcs", (6.0, 11.0)),
    ("Touch display 7in", "Component", "pcs", (55.0, 90.0)),
    ("Cardboard box L", "Packaging", "pcs", (0.9, 1.8)),
    ("Cardboard box XL", "Packaging", "pcs", (1.4, 2.6)),
    ("Bubble wrap roll", "Packaging", "m", (0.2, 0.5)),
    ("Wooden pallet", "Packaging", "pcs", (8.0, 14.0)),
    ("Stretch film", "Packaging", "m", (0.05, 0.12)),
    ("Foam insert", "Packaging", "pcs", (0.6, 1.4)),
    ("Industrial glue", "Consumable", "l", (6.0, 12.0)),
    ("Powder paint RAL7035", "Consumable", "kg", (7.0, 13.0)),
    ("Welding wire", "Consumable", "kg", (3.0, 6.0)),
    ("Cutting disc 125mm", "Consumable", "pcs", (0.8, 1.6)),
    ("Lubricant spray", "Consumable", "pcs", (3.5, 6.5)),
    ("Cleaning solvent", "Consumable", "l", (2.5, 5.0)),
]

PRODUCTS = [
    "Industrial Shelf IS-100",
    "Control Cabinet CC-200",
    "Tool Trolley TT-50",
    "Workbench WB-180",
    "Motorized Gate Unit MG-1",
    "Electrical Enclosure EE-40",
    "Storage Locker SL-6",
    "Conveyor Module CM-300",
    "Smart Panel SP-7",
    "Lift Table LT-500",
]


def generate(db_path: Path | str = config.DB_PATH, seed: int = 42, today: date | None = None) -> Path:
    rng = random.Random(seed)
    today = today or date.today()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = connect(db_path)
    create_schema(conn)
    set_reference_date(conn, today)
    set_meta(conn, dataset="Synthetic demo data", currency="EUR")

    suppliers = [(f"S{i + 1:02d}", n, c) for i, (n, c, _) in enumerate(SUPPLIERS)]
    reliability = {f"S{i + 1:02d}": r for i, (_, _, r) in enumerate(SUPPLIERS)}
    conn.executemany("INSERT INTO suppliers VALUES (?, ?, ?)", suppliers)

    materials = []
    for i, (name, category, unit, (lo, hi)) in enumerate(MATERIALS):
        min_stock = rng.choice([50, 100, 150, 200, 300, 500, 800, 1000])
        if rng.random() < 0.25:
            stock = round(min_stock * rng.uniform(0.0, 0.95))
        else:
            stock = round(min_stock * rng.uniform(1.05, 3.0))
        materials.append((
            f"M{i + 1:03d}", name, category, unit, stock, min_stock,
            round(rng.uniform(lo, hi), 2), rng.randint(5, 45), rng.choice(suppliers)[0],
        ))
    conn.executemany("INSERT INTO materials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", materials)

    products = [(f"P{i + 1:02d}", n) for i, n in enumerate(PRODUCTS)]
    conn.executemany("INSERT INTO products VALUES (?, ?)", products)
    buildable = [m for m in materials if m[2] in ("Raw material", "Component")]
    packaging = [m for m in materials if m[2] == "Packaging"]
    bom = []
    for pid, _ in products:
        for m in rng.sample(buildable, rng.randint(4, 7)) + rng.sample(packaging, 1):
            bom.append((pid, m[0], rng.choice([0.5, 1, 1, 2, 4])))
    conn.executemany("INSERT INTO bom VALUES (?, ?, ?)", bom)

    orders = []
    for i in range(120):
        start = today + timedelta(days=rng.randint(-90, 45))
        due = start + timedelta(days=rng.randint(3, 20))
        completed = None
        if start > today:
            status = "Planned"
        elif due >= today:
            status = "In progress"
        elif rng.random() < 0.8:
            status = "Completed"
            completed = min(due + timedelta(days=rng.randint(-3, 6)), today)
        else:
            status = "In progress"
        orders.append((
            f"PO-{1001 + i}", rng.choice(products)[0], rng.randint(1, 12) * 5,
            start.isoformat(), due.isoformat(), status,
            completed.isoformat() if completed else None,
        ))
    conn.executemany("INSERT INTO production_orders VALUES (?, ?, ?, ?, ?, ?, ?)", orders)

    pos = []
    for i in range(150):
        m = rng.choice(materials)
        sid, lead = m[8], m[7]
        ordered = today - timedelta(days=rng.randint(0, 120))
        expected = ordered + timedelta(days=lead)
        received = None
        status = "Open"
        if expected <= today:
            if rng.random() < reliability[sid]:
                received = expected + timedelta(days=rng.randint(-3, 0))
            else:
                received = expected + timedelta(days=rng.randint(1, 15))
            if received > today:
                received = None
            else:
                status = "Received"
        qty = round(m[5] * rng.uniform(0.5, 2.0))
        received_qty = rejected_qty = 0
        if status == "Received":
            received_qty = qty if rng.random() < 0.9 else round(qty * rng.uniform(0.7, 0.98))
            if rng.random() < 1.2 - reliability[sid]:
                rejected_qty = round(received_qty * rng.uniform(0.01, 0.1))
        pos.append((
            f"PUR-{5001 + i}", m[0], sid, qty,
            ordered.isoformat(), expected.isoformat(),
            received.isoformat() if received else None, status,
            received_qty, rejected_qty,
        ))
    conn.executemany("INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", pos)

    conn.commit()
    conn.close()
    return db_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate StockPilot synthetic data")
    parser.add_argument("--db", default=str(config.DB_PATH))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="reference date, YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    path = generate(args.db, args.seed, args.today)
    print(f"Synthetic database written to {path}")


if __name__ == "__main__":
    main()
