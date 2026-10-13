"""Amazon - the "Order History.csv" of a Request Your Data export (Your
Amazon Orders/Order History.csv): physical orders, one row per item.

Real export header: "ASIN,Billing Address,Carrier Name & Tracking
Number,Currency,Gift Message,...,Order Date,Order ID,Order Status,Original
Quantity,Payment Method Type,...,Product Name,...,Ship Date,Shipment Item
Subtotal,Shipment Item Subtotal Tax,...,Shipping Charge,...,Total
Amount,Total Discounts,Unit Price,Unit Price Tax,Website". A field the
export has nothing for reads "Not Available".

What the columns mean, checked against a real export by counting rows:
  * Total Amount is the line in full: (Unit Price + Unit Price Tax) x
    Original Quantity + Shipping Charge + Total Discounts. Total Discounts
    is printed negative.
  * Shipment Item Subtotal and its tax are the shipment's, repeated on
    every row of it, so they are not read as a row's own.
  * Amazon charges a card per shipment, and an order can ship in several.
    Order ID plus the ship date is the charge group.
  * A cancelled item has quantity 0 and cost nothing; it is left out.

The digital orders, the refunds and the returns of the same export are
other files with other columns, and are not read here. No check is
reported: the file prints no total that the rows could be held against.
"""

import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL

KIND = parser_common.KIND_RETAIL

_REQUIRED_HEADER = {
    "ASIN", "Order ID", "Order Date", "Order Status", "Original Quantity",
    "Product Name", "Ship Date", "Shipment Item Subtotal", "Total Amount",
    "Total Discounts", "Unit Price", "Unit Price Tax", "Website",
}

_NOT_AVAILABLE = "not available"


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    missing = _REQUIRED_HEADER - {h.strip().lstrip("﻿") for h in header}
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Amazon order history export header matched"


def _text(row: dict, key: str) -> str:
    value = (row.get(key) or "").strip()
    return "" if value.lower() == _NOT_AVAILABLE else value


def _number(row: dict, key: str) -> float | None:
    value = _text(row, key).replace(",", "").replace("$", "").strip("'\"")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip().lstrip("﻿"): v for k, v in row.items()} for row in rows]
    items = []
    for row in rows:
        quantity = _number(row, "Original Quantity")
        total = _number(row, "Total Amount")
        if _text(row, "Order Status").lower() == "cancelled" or (not quantity and not total):
            continue
        order_date = _text(row, "Order Date")[:10]
        order_id = _text(row, "Order ID")
        if not order_date or not order_id:
            continue
        asin = _text(row, "ASIN")
        item = {
            "date": order_date,
            "description": _text(row, "Product Name") or (f"Amazon item {asin}" if asin else "Amazon item"),
            # Money spent is negative (CONTRACT.md, sign convention).
            "amount": -round(abs(total or 0.0), 2),
            "order_id": order_id,
            "line_type": parser_common.RETAIL_LINE_PURCHASE,
            "quantity": quantity,
            "unit_price": _number(row, "Unit Price"),
            "shipping": _number(row, "Shipping Charge"),
            "discount": _number(row, "Total Discounts"),
        }
        unit_tax = _number(row, "Unit Price Tax")
        item["tax"] = None if unit_tax is None else round(unit_tax * (quantity or 1), 2)
        ship_date = _text(row, "Ship Date")[:10]
        item["charge_group"] = f"{order_id}/{ship_date}" if ship_date else order_id
        for key, column in (("payment_method", "Payment Method Type"), ("item_id", "ASIN"),
                            ("currency_code", "Currency"), ("status", "Order Status")):
            value = _text(row, column)
            if value:
                item[key] = value
        # Another country's store is named, since its amounts are in
        # another currency and must not be added to the rest unseen.
        website = _text(row, "Website")
        if website.lower().startswith("amazon.") and website.lower() != "amazon.com":
            item["institution"] = website
        items.append(item)
    return {"institution": "Amazon", "statementDate": "", "tables": {"retail_items": items}}
