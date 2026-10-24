"""Empower's (formerly Personal Capital's) transaction export, from the web
app's Transactions page: Date, Account, Description, Category, Tags,
Amount.

Amount is the change to the account: a card charge is negative, a payment
positive. Every account on the tab is in the file, named but with no number
or bank: each row carries its Account for OrbySystems to ask which account
it is. Somebody's records rather than a statement (RECORDS;
app_export.py). Investment accounts' rows are cash only - a purchase is
cash leaving, with no shares - so they read as spending rows.
"""

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

RECORDS = True

_HEADER = {"Date", "Account", "Description", "Category", "Tags", "Amount"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    names = {h.strip() for h in header}
    if names != _HEADER:
        return False, f"not Empower's export: its header is exactly {sorted(_HEADER)}"
    return True, "Empower transactions export"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    order = app_export.date_order([r.get("Date", "") for r in rows])
    transactions = []
    for n, r in enumerate(rows, start=2):
        description = (r.get("Description") or "").strip() or (r.get("Category") or "").strip()
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append(app_export.row(
            app_export.date(r["Date"], order), description, app_export.money(r["Amount"]), (r.get("Account") or "").strip(),
        ))
    return {"institution": "", "statementDate": "", "transactions": transactions}
