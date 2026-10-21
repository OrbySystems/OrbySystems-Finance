"""Amazon - the "Returns Status.csv" of a Request Your Data export (Your
Returns & Refunds/Returns Status.csv): every return the customer started,
one row per return in retail_returns. Read beside amazon_refund_details.py:
a return with no refund for its order yet is a refund still to come.

Real export header: "Carrier Package ID,Carrier Tracking ID,Charge
Status,Contract Creation Date,Contract ID,Contract Unit ID,Date of
Return,Gift Card,Order ID,Payment Method Service Type,Replacement
Order,Retrocharge Resolution,Return Amount,Return Amount Currency,Return
Authorization ID,Return Creation Date,Return Reason,Return Receivable
Creation Reason,Return Receivable Initiation Date,Return Receivable
State,Return Receivable Tracking ID,Return Resolution,Return Ship Option".

What the file is like, checked against a real export by counting rows:
  * A return (its Return Authorization ID) has one row per unit sent back
    (Contract Unit ID), and often several rows per unit. The rows of one
    unit can print different amounts, so a return's amount is the largest
    each of its units printed, added up, and it is only a guide.
  * It names the order, never the item: no product name or item number.
  * Return Creation Date is "Not Applicable" on some returns; Date of
    Return, always a date, stands in for it then.
  * Return Receivable State is Closed (the item came back), Expired (it
    never did) or Not Applicable (nothing recorded yet).
  * Where Amazon refunded before the item came back and it never did, the
    row says Retrocharge Resolution "AdvancedRefund" and Charge Status
    "ChargeSuccess": the customer was charged again.
"""

from collections import Counter

import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL

KIND = parser_common.KIND_RETAIL

_REQUIRED_HEADER = {
    "Return Authorization ID", "Order ID", "Return Creation Date", "Return Resolution",
    "Return Receivable State", "Return Amount", "Contract Unit ID",
}

_NOT_AVAILABLE = ("not available", "not applicable")

_STATES = {"closed": "closed", "expired": "expired"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    missing = _REQUIRED_HEADER - {h.strip().lstrip("﻿") for h in header}
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Amazon returns status export header matched"


def _text(row: dict, key: str) -> str:
    value = (row.get(key) or "").strip()
    return "" if value.lower() in _NOT_AVAILABLE else value


def _number(row: dict, key: str) -> float | None:
    value = _text(row, key).replace(",", "").replace("$", "").strip("'\"")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _day(value: str) -> str:
    return value[:10] if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-" else ""


def _most_common(values: list[str]) -> str:
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0][0] if values else ""


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip().lstrip("﻿"): v for k, v in row.items()} for row in rows]
    by_return: dict[str, list[dict]] = {}
    for row in rows:
        return_id = _text(row, "Return Authorization ID")
        if return_id and _text(row, "Order ID"):
            by_return.setdefault(return_id, []).append(row)

    returns = []
    for return_id, group in by_return.items():
        created = sorted(d for d in (_day(_text(r, "Return Creation Date")) for r in group) if d)
        sent = sorted(d for d in (_day(_text(r, "Date of Return")) for r in group) if d)
        date = (created or sent or [""])[0]
        if not date:
            continue
        units: dict[str, float] = {}
        for r in group:
            amount = _number(r, "Return Amount")
            if amount is not None:
                unit = _text(r, "Contract Unit ID") or str(len(units))
                units[unit] = max(units.get(unit, 0.0), abs(amount))
        states = {_STATES.get(_text(r, "Return Receivable State").lower(), "open") for r in group}
        state = "closed" if "closed" in states else "expired" if "expired" in states else "open"
        out = {
            "date": date,
            "order_id": _most_common([_text(r, "Order ID") for r in group]),
            "return_id": return_id,
            "amount": round(sum(units.values()), 2) if units else None,
            "reason": _most_common([_text(r, "Return Reason") for r in group]),
            "resolution": {"refund": "refund", "exchange": "exchange"}.get(
                _most_common([_text(r, "Return Resolution") for r in group]).lower(), ""),
            "state": state,
            "charged_back": any(_text(r, "Charge Status").lower() == "chargesuccess" for r in group),
        }
        if sent:
            out["returned_on"] = sent[-1]
        currency = _most_common([_text(r, "Return Amount Currency") for r in group])
        if currency:
            out["currency_code"] = currency
        returns.append(out)
    returns.sort(key=lambda r: (r["date"], r["return_id"]))
    return {"institution": "Amazon", "statementDate": "", "tables": {"retail_returns": returns}}
