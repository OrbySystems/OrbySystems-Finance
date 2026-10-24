"""Discover card activity, downloaded as CSV (Activity > Download): Trans.
Date, Post Date, Description, Amount, Category.

Amounts are written as the card's balance moves - a purchase positive, a
payment or a credit negative - read in that sign, then negated as the last
step (common.negate_amounts_and_balances). Dates are month first
(03/05/2024). The file names no card number, so the import asks which
account it is.
"""

from institutions import common

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Discover"

_HEADER = {"Trans. Date", "Post Date", "Description", "Amount", "Category"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Discover card activity export header matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    transactions = []
    for n, row in enumerate(rows, start=2):
        raw = (row.get("Amount") or "").strip()
        if not raw:
            raise ValueError(f"row {n}: no amount")
        description = " ".join((row.get("Description") or "").split())
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append({
            "date": app_export.date(row["Trans. Date"], "mdy"),
            "description": description,
            "amount": app_export.money(raw),
            "balance": None,
            "account": "",
            "accountType": "Credit Card",
        })
    common.negate_amounts_and_balances(transactions)
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
