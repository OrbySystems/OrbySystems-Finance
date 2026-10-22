"""Amazon - the "Digital Returns.csv" of a Request Your Data export (Your
Amazon Orders/Digital Returns.csv): money given back for digital items,
one retail_items refund per item returned, marked digital. Read beside
amazon_digital_orders.py.

Real export header: "ASIN,Affected Item Quantity,Amount Refunded,Base
Currency,Claim Code,Condition Code,Delivery Packet ID,Digital Order Item
ID,FX Currency Code,FX Transaction Amount,Monetary Component Type,Offer
Type Code,Order ID,Payment Information,Processing Successful,Product
Name,Quantity,Reason Code,Refund to Gift Certificate,Return Date,Return
Status,Returned By,Settle Type,Status,Transaction Amount".

What the file is like, checked against a real export by counting rows:
  * A returned item (Digital Order Item ID) has rows like its order's: a
    price row, a tax row, and a negative price row for a coupon. The
    money back is its rows' Transaction Amounts added up, which matched
    what the item cost for every item returned.
  * Amount Refunded is often "Not Available", so it is not relied on.
  * A return whose Return Status is not complete has given nothing back
    yet, and is left out.
"""

from collections import OrderedDict

import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL

KIND = parser_common.KIND_RETAIL

_REQUIRED_HEADER = {
    "Digital Order Item ID", "Monetary Component Type", "Transaction Amount", "Order ID",
    "Return Date", "Return Status",
}

_NOT_AVAILABLE = ("not available", "not applicable")


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    missing = _REQUIRED_HEADER - {h.strip().lstrip("﻿") for h in header}
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Amazon digital returns export header matched"


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

    refunds = []
    for group in items.values():
        first = group[0]
        if "complete" not in _text(first, "Return Status").lower():
            continue
        day = _text(first, "Return Date")[:10]
        order_id = _text(first, "Order ID")
        back = abs(sum(_number(r, "Transaction Amount") or 0.0 for r in group))
        if len(day) != 10 or not order_id or back < 0.005:
            continue
        reason = _text(first, "Reason Code")
        refund = {
            "date": day,
            "description": f"Refund: digital return ({reason})" if reason else "Refund: digital return",
            # Money back is positive (CONTRACT.md, sign convention).
            "amount": round(back, 2),
            "order_id": order_id,
            "line_type": parser_common.RETAIL_LINE_REFUND,
            "quantity": _number(first, "Quantity") or 1.0,
            "charge_group": f"{order_id}/refund/{day}",
            "status": "Refunded",
            "digital": True,
        }
        currency = _text(first, "Base Currency")
        if currency and len(currency) == 3:
            refund["currency_code"] = currency
        refunds.append(refund)
    return {"institution": "Amazon", "statementDate": "", "tables": {"retail_items": refunds}}
