"""Monarch Money's transaction export (Settings > Data, or an account's
Download transactions): Date, Merchant, Category, Account, Original
Statement, Notes, Amount, Tags, and Owner in a household's.

Amount is signed: negative is money out, positive money in, credit cards
included. Dates are YYYY-MM-DD. Every account may be in the file, named but
with no number or bank: each row carries its Account for OrbySystems to
ask which account it is. Somebody's records rather than a statement
(RECORDS; app_export.py).
"""

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

RECORDS = True

_HEADER = {"Date", "Merchant", "Category", "Account", "Original Statement", "Amount"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    return app_export.has_columns(header, _HEADER, "Monarch")


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    order = app_export.date_order([r.get("Date", "") for r in rows])
    transactions = []
    for n, r in enumerate(rows, start=2):
        description = (r.get("Merchant") or "").strip() or (r.get("Original Statement") or "").strip()
        if not description:
            raise ValueError(f"row {n}: no merchant or statement text")
        transactions.append(app_export.row(
            app_export.date(r["Date"], order), description, app_export.money(r["Amount"]), (r.get("Account") or "").strip(),
        ))
    return {"institution": "", "statementDate": "", "transactions": transactions}
