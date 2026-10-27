"""Amazon - the "Refund Details.csv" of a Request Your Data export (Your
Returns & Refunds/Refund Details.csv): money Amazon gave back, one row per
refund. Read beside amazon_order_history.py, whose rows are what was
spent; without this file a returned item still counts as spending.

Real export header: "Creation Date,Currency,Direct Debit Refund
Amount,Disbursement Type,Order ID,Payment Status,Quantity,Refund
Amount,Refund Date,Reversal Amount State,Reversal Reason,Reversal
Status,Website".

What the file is like, checked against a real export by counting rows:
  * A refund names its order and nothing else: no item, no product. Which
    item of the order it was for is worked out after the import, from the
    order's own rows.
  * An order refunded n times has n x n rows, not n: every refund is
    repeated once for each of the order's Creation Dates. A refund's
    amount goes with its Refund Date, so one row is kept for each Refund
    Date and amount of an order. Added up as printed, such an order's
    refunds come to more than it cost.
  * Every row of that export was a completed refund. A row whose Payment
    Status says anything else is left out: the money has not come back.
  * A completed refund can say "Not Applicable" for its Refund Date (seen
    in a scrambled real export). Its Creation Date is when the refund was
    made - the same day as the Refund Date, or the day before, wherever
    both are given - so it is dated by that instead. Its repeats differ
    only in Creation Date, so they are told apart without it, and the
    earliest one dates it.
  * A date that is still not YYYY-MM-DD fails the file by name: the
    export's format has changed, and leaving those rows out would quietly
    lose refunds.
"""

import re

import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL

KIND = parser_common.KIND_RETAIL

_REQUIRED_HEADER = {
    "Creation Date", "Direct Debit Refund Amount", "Disbursement Type", "Order ID",
    "Payment Status", "Refund Amount", "Refund Date", "Reversal Reason", "Reversal Status",
}

# What the export prints in a cell with nothing in it.
_NOT_AVAILABLE = "not available"
_EMPTY = {_NOT_AVAILABLE, "not applicable"}


# A date as the export writes it: YYYY-MM-DD, then the time.
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    missing = _REQUIRED_HEADER - {h.strip().lstrip("﻿") for h in header}
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Amazon refund details export header matched"


def _text(row: dict, key: str) -> str:
    value = (row.get(key) or "").strip()
    return "" if value.lower() in _EMPTY else value


def _number(row: dict, key: str) -> float | None:
    value = _text(row, key).replace(",", "").replace("$", "").strip("'\"")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip().lstrip("﻿"): v for k, v in row.items()} for row in rows]
    # A refund's own rows, once the export's repeats (see the module
    # docstring) are one: keyed by order, Refund Date as printed and amount.
    refunds_by_key = {}
    for row in rows:
        order_id = _text(row, "Order ID")
        amount = _number(row, "Refund Amount")
        if not order_id or not amount:
            continue
        # Read as printed: "Not Applicable" here is not a completed refund.
        status = (row.get("Payment Status") or "").strip().lower()
        if status not in ("", "completed", _NOT_AVAILABLE):
            continue
        refund_date = _text(row, "Refund Date")
        key = (order_id, refund_date, round(amount, 2))
        refunds_by_key.setdefault(key, []).append(row)

    refunds = []
    for (order_id, refund_date, amount), same in refunds_by_key.items():
        refunded_at = refund_date or min((d for r in same if (d := _text(r, "Creation Date"))), default="")
        if not _DATE.match(refunded_at):
            raise ValueError("amazon_refund_details: a completed refund's date is not YYYY-MM-DD; "
                             "the export's date format has changed")
        row = same[0]
        reason = _text(row, "Reversal Reason")
        refund = {
            "date": refunded_at[:10],
            "description": f"Refund: {reason}" if reason else "Refund",
            # Money back is positive (CONTRACT.md, sign convention).
            "amount": round(abs(amount), 2),
            # The order whose items this gives money back for.
            "order_id": order_id,
            "line_type": parser_common.RETAIL_LINE_REFUND,
            "quantity": _number(row, "Quantity"),
            # A refund is a credit of its own on the card.
            "charge_group": f"{order_id}/refund/{refunded_at[:10]}",
            "status": "Refunded",
        }
        currency = _text(row, "Currency")
        if currency:
            refund["currency_code"] = currency
        website = _text(row, "Website")
        if website.lower().startswith("amazon.") and website.lower() != "amazon.com":
            refund["institution"] = website
        refunds.append(refund)
    return {"institution": "Amazon", "statementDate": "", "tables": {"retail_items": refunds}}
