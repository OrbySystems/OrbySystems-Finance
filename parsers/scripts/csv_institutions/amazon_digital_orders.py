"""Amazon - the "Digital Content Orders.csv" of a Request Your Data export
(Your Amazon Orders/Digital Content Orders.csv): ebooks, audiobooks,
videos, apps and digital subscriptions bought, one retail_items purchase
per item, marked digital. Read beside amazon_order_history.py, whose rows
are what was shipped.

Real export header (abridged): "ASIN,...,Component Type,...,Digital Order
Item ID,...,Marketplace,...,Order Date,Order ID,Order Status,...,Paid by
Other Customer,Payment Information,...,Price,Price Currency Code,...,
Product Name,Publisher,Quantity Ordered,...,Transaction Amount,...".

What the file is like, checked against a real export by counting rows:
  * An item (Digital Order Item ID) has a "Price Amount" row and a "Tax"
    row, and one more "Price Amount" row, negative, for each coupon or
    promotion. What it cost is its rows' Transaction Amounts added up.
  * Payment Information says "Payment Instrument Details Not Available":
    no payment method is recorded.
  * Free items (nothing paid), orders not completed (pending, a preorder
    not yet released, cancelled) and items another customer paid for are
    not money spent, and are left out.
  * Every order number starts "D01-"; Audible's are marked by the
    Marketplace "www.audible.com", kept as the item's retailer category.
"""

from collections import OrderedDict

import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL

KIND = parser_common.KIND_RETAIL

_REQUIRED_HEADER = {
    "Digital Order Item ID", "Component Type", "Transaction Amount", "Order ID", "Order Date",
    "Order Status", "Product Name", "Marketplace",
}

_NOT_AVAILABLE = ("not available", "not applicable")


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    missing = _REQUIRED_HEADER - {h.strip().lstrip("﻿") for h in header}
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Amazon digital content orders export header matched"


def _text(row: dict, key: str) -> str:
    value = (row.get(key) or "").strip()
    return "" if value.lower() in _NOT_AVAILABLE else value


def _number(row: dict, key: str) -> float | None:
    value = _text(row, key).replace(",", "").replace("$", "").strip("'\"")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip().lstrip("﻿"): v for k, v in row.items()} for row in rows]
    items: "OrderedDict[str, list[dict]]" = OrderedDict()
    for row in rows:
        item_id = _text(row, "Digital Order Item ID")
        if item_id:
            items.setdefault(item_id, []).append(row)

    purchases = []
    for group in items.values():
        first = group[0]
        if _text(first, "Order Status").upper() != "SUCCESS" or _text(first, "Paid by Other Customer").lower() == "yes":
            continue
        day = _text(first, "Order Date")[:10]
        order_id = _text(first, "Order ID")
        if len(day) != 10 or not order_id:
            continue
        price_rows = [r for r in group if _text(r, "Component Type").lower() == "price amount"]
        tax_rows = [r for r in group if _text(r, "Component Type").lower() == "tax"]
        paid = sum(_number(r, "Transaction Amount") or 0.0 for r in group)
        if paid < 0.005:
            continue  # free, or nothing paid
        coupons = sum(min(_number(r, "Transaction Amount") or 0.0, 0.0) for r in price_rows)
        tax = sum(_number(r, "Transaction Amount") or 0.0 for r in tax_rows)
        asin = _text(first, "ASIN")
        name = _text(first, "Product Name") or (f"Digital item {asin}" if asin else "Digital item")
        item = {
            "date": day,
            "description": name,
            "amount": -round(paid, 2),
            "order_id": order_id,
            "line_type": parser_common.RETAIL_LINE_PURCHASE,
            "quantity": _number(first, "Quantity Ordered") or 1.0,
            "unit_price": _number(first, "Price"),
            "discount": round(coupons, 2) if coupons else None,
            "tax": round(tax, 2),
            "charge_group": order_id,
            "status": "Delivered",
            "digital": True,
        }
        if asin:
            item["item_id"] = asin
        if "audible" in _text(first, "Marketplace").lower():
            item["retailer_category"] = "Audible"
        currency = _text(first, "Price Currency Code")
        if currency:
            item["currency_code"] = currency
        purchases.append(item)
    return {"institution": "Amazon", "statementDate": "", "tables": {"retail_items": purchases}}
