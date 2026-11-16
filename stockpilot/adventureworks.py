import argparse
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .db import connect, create_schema, set_meta, set_reference_date

BASE_URL = (
    "https://raw.githubusercontent.com/microsoft/sql-server-samples/master/"
    "samples/databases/adventure-works/oltp-install-script"
)
DEFAULT_REFERENCE_DATE = date(2025, 5, 20)

COLUMNS = {
    "Product": "ProductID Name ProductNumber MakeFlag FinishedGoodsFlag Color SafetyStockLevel "
               "ReorderPoint StandardCost ListPrice Size SizeUnitMeasureCode WeightUnitMeasureCode "
               "Weight DaysToManufacture ProductLine Class Style ProductSubcategoryID ProductModelID "
               "SellStartDate SellEndDate DiscontinuedDate rowguid ModifiedDate",
    "ProductInventory": "ProductID LocationID Shelf Bin Quantity rowguid ModifiedDate",
    "BillOfMaterials": "BillOfMaterialsID ProductAssemblyID ComponentID StartDate EndDate "
                       "UnitMeasureCode BOMLevel PerAssemblyQty ModifiedDate",
    "WorkOrder": "WorkOrderID ProductID OrderQty StockedQty ScrappedQty StartDate EndDate DueDate "
                 "ScrapReasonID ModifiedDate",
    "PurchaseOrderHeader": "PurchaseOrderID RevisionNumber Status EmployeeID VendorID ShipMethodID "
                           "OrderDate ShipDate SubTotal TaxAmt Freight TotalDue ModifiedDate",
    "PurchaseOrderDetail": "PurchaseOrderID PurchaseOrderDetailID DueDate OrderQty ProductID UnitPrice "
                           "LineTotal ReceivedQty RejectedQty StockedQty ModifiedDate",
    "Vendor": "BusinessEntityID AccountNumber Name CreditRating PreferredVendorStatus ActiveFlag "
              "PurchasingWebServiceURL ModifiedDate",
    "ProductVendor": "ProductID BusinessEntityID AverageLeadTime StandardPrice LastReceiptCost "
                     "LastReceiptDate MinOrderQty MaxOrderQty OnOrderQty UnitMeasureCode ModifiedDate",
    "BusinessEntityAddress": "BusinessEntityID AddressID AddressTypeID rowguid ModifiedDate",
    "Address": "AddressID AddressLine1 AddressLine2 City StateProvinceID PostalCode SpatialLocation "
               "rowguid ModifiedDate",
    "StateProvince": "StateProvinceID StateProvinceCode CountryRegionCode IsOnlyStateProvinceFlag Name "
                     "TerritoryID rowguid ModifiedDate",
    "CountryRegion": "CountryRegionCode Name ModifiedDate",
}
PLUS_PIPE_FILES = {"BusinessEntityAddress"}


def download(source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    for name in COLUMNS:
        target = source_dir / f"{name}.csv"
        if not target.exists():
            print(f"Downloading {name}.csv")
            urllib.request.urlretrieve(f"{BASE_URL}/{name}.csv", target)


def read_table(source_dir: Path, name: str) -> pd.DataFrame:
    path = source_dir / f"{name}.csv"
    cols = COLUMNS[name].split()
    if name in PLUS_PIPE_FILES:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        rows = [r.split("+|") for r in text.split("&|\n") if r.strip()]
        rows = [[c.removesuffix("&|") for c in r] for r in rows]
        return pd.DataFrame(rows, columns=cols)
    return pd.read_csv(path, sep="\t", header=None, names=cols, dtype=str,
                       keep_default_na=False, quoting=3, encoding="utf-8")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace("", np.nan))


def _date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.replace("", np.nan))


def _iso(s: pd.Series) -> pd.Series:
    return s.dt.strftime("%Y-%m-%d").where(s.notna(), None)


def build(source_dir: Path, ref: date) -> dict[str, pd.DataFrame]:
    t = {name: read_table(source_dir, name) for name in COLUMNS}
    ref_ts = pd.Timestamp(ref)

    product = t["Product"].set_index("ProductID")
    number = product["ProductNumber"]

    vendor = t["Vendor"]
    country = (
        t["BusinessEntityAddress"][["BusinessEntityID", "AddressID"]]
        .merge(t["Address"][["AddressID", "StateProvinceID"]], on="AddressID")
        .merge(t["StateProvince"][["StateProvinceID", "CountryRegionCode"]], on="StateProvinceID")
        .merge(t["CountryRegion"][["CountryRegionCode", "Name"]], on="CountryRegionCode")
        .drop_duplicates("BusinessEntityID")
        .set_index("BusinessEntityID")["Name"]
    )
    suppliers = pd.DataFrame({
        "supplier_id": "V" + vendor["BusinessEntityID"],
        "name": vendor["Name"],
        "country": vendor["BusinessEntityID"].map(country).fillna("Unknown"),
    })

    bom = t["BillOfMaterials"]
    bom = bom[(bom["EndDate"] == "") & (bom["ProductAssemblyID"] != "")].copy()
    bom["PerAssemblyQty"] = _num(bom["PerAssemblyQty"])
    bom["UnitMeasureCode"] = bom["UnitMeasureCode"].str.strip()

    headers = t["PurchaseOrderHeader"]
    details = t["PurchaseOrderDetail"].merge(
        headers[["PurchaseOrderID", "VendorID", "Status", "OrderDate"]], on="PurchaseOrderID"
    )

    pv = t["ProductVendor"].copy()
    pv["AverageLeadTime"] = _num(pv["AverageLeadTime"])
    pv["StandardPrice"] = _num(pv["StandardPrice"])
    lines = details.groupby(["ProductID", "VendorID"]).size().rename("lines").reset_index()
    pv = pv.merge(lines, left_on=["ProductID", "BusinessEntityID"],
                  right_on=["ProductID", "VendorID"], how="left")
    pv["lines"] = pv["lines"].fillna(0)
    main_vendor = (pv.sort_values(["lines", "AverageLeadTime"], ascending=[False, True])
                   .drop_duplicates("ProductID").set_index("ProductID"))

    components = set(bom["ComponentID"])
    material_ids = sorted(components | set(pv["ProductID"]), key=int)
    m = product.loc[material_ids].copy()
    make = m["MakeFlag"] == "1"
    m["category"] = np.select(
        [make, m.index.isin(list(components))], ["Subassembly", "Purchased part"], "Resale item"
    )
    inv = t["ProductInventory"]
    stock = _num(inv["Quantity"]).groupby(inv["ProductID"]).sum()
    unit = bom.groupby("ComponentID")["UnitMeasureCode"].agg(lambda s: s.mode().iat[0])
    vend = main_vendor.reindex(m.index)
    std_cost = _num(m["StandardCost"]).fillna(0)
    materials = pd.DataFrame({
        "material_id": m["ProductNumber"],
        "name": m["Name"],
        "category": m["category"],
        "unit": unit.reindex(m.index).fillna("EA"),
        "stock_qty": stock.reindex(m.index).fillna(0),
        "min_stock": _num(m["SafetyStockLevel"]),
        "unit_cost": std_cost.where(std_cost > 0, vend["StandardPrice"]).fillna(0).round(2),
        "lead_time_days": vend["AverageLeadTime"].where(~make, _num(m["DaysToManufacture"]))
                          .fillna(0).astype(int),
        "supplier_id": ("V" + vend["BusinessEntityID"]).where(~make & vend["BusinessEntityID"].notna()),
    }).reset_index(drop=True)

    wo = t["WorkOrder"].copy()
    assembly_ids = sorted(set(bom["ProductAssemblyID"]) | set(wo["ProductID"]), key=int)
    products = pd.DataFrame({
        "product_id": number.loc[assembly_ids].values,
        "name": product.loc[assembly_ids, "Name"].values,
    })

    bom_rows = (bom.assign(product_id=bom["ProductAssemblyID"].map(number),
                           material_id=bom["ComponentID"].map(number))
                .groupby(["product_id", "material_id"], as_index=False)["PerAssemblyQty"].sum()
                .rename(columns={"PerAssemblyQty": "qty_per_unit"}))

    start, end, due = _date(wo["StartDate"]), _date(wo["EndDate"]), _date(wo["DueDate"])
    planned = start > ref_ts
    done = ~planned & end.notna() & (end <= ref_ts)
    production_orders = pd.DataFrame({
        "order_id": "WO-" + wo["WorkOrderID"],
        "product_id": wo["ProductID"].map(number),
        "quantity": _num(wo["OrderQty"]).astype(int),
        "start_date": _iso(start),
        "due_date": _iso(due),
        "status": np.select([planned, done], ["Planned", "Completed"], "In progress"),
        "completed_date": _iso(end.where(done)),
    })

    d = details[details["ProductID"].isin(material_ids)].copy()
    order_date, due_date = _date(d["OrderDate"]), _date(d["DueDate"])
    d = d[order_date <= ref_ts]
    order_date, due_date = order_date[d.index], due_date[d.index]
    rejected = d["Status"] == "3"
    still_open = d["Status"].isin(["1", "2"]) | ((d["Status"] == "4") & (due_date > ref_ts))
    status = pd.Series(np.select([rejected, still_open], ["Rejected", "Open"], "Received"), index=d.index)
    received = status == "Received"
    purchase_orders = pd.DataFrame({
        "po_id": "PUR-" + d["PurchaseOrderID"] + "-" + d["PurchaseOrderDetailID"],
        "material_id": d["ProductID"].map(number),
        "supplier_id": "V" + d["VendorID"],
        "quantity": _num(d["OrderQty"]),
        "order_date": _iso(order_date),
        "expected_date": _iso(due_date),
        "received_date": None,
        "status": status,
        "received_qty": _num(d["ReceivedQty"]).where(received, 0),
        "rejected_qty": _num(d["RejectedQty"]).where(received, 0),
    })

    return {
        "suppliers": suppliers,
        "materials": materials,
        "products": products,
        "bom": bom_rows,
        "production_orders": production_orders,
        "purchase_orders": purchase_orders,
    }


def import_adventureworks(
    db_path: Path | str = config.DB_PATH,
    source_dir: Path | str = config.AW_SOURCE_DIR,
    ref: date = DEFAULT_REFERENCE_DATE,
    download_missing: bool = True,
) -> Path:
    source_dir, db_path = Path(source_dir), Path(db_path)
    if download_missing:
        download(source_dir)
    tables = build(source_dir, ref)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    try:
        create_schema(conn)
        set_reference_date(conn, ref)
        set_meta(conn, dataset=f"AdventureWorks (Microsoft sample data), snapshot as of {ref.isoformat()}",
                 currency="USD")
        for name in ["suppliers", "materials", "products", "bom", "production_orders", "purchase_orders"]:
            tables[name].to_sql(name, conn, if_exists="append", index=False)
        conn.commit()
    finally:
        conn.close()
    return db_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Microsoft AdventureWorks into StockPilot")
    parser.add_argument("--db", default=str(config.AW_DB_PATH))
    parser.add_argument("--source", default=str(config.AW_SOURCE_DIR))
    parser.add_argument("--today", type=date.fromisoformat, default=DEFAULT_REFERENCE_DATE,
                        help=f"snapshot date, YYYY-MM-DD (default: {DEFAULT_REFERENCE_DATE})")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()
    path = import_adventureworks(args.db, args.source, args.today, not args.no_download)
    print(f"AdventureWorks database written to {path}")


if __name__ == "__main__":
    main()
