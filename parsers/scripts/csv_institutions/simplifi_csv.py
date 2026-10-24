"""Quicken Simplifi's transaction export (the web app's Transactions >
Export): Date, Account, Status, Payee, Category, Tags, Notes, Amount.

Amount is signed: negative is money out. Dates are month first (1/1/2022).
Every account is in the file, named but with no number or bank: each row
carries its Account for OrbySystems to ask which account it is. Somebody's
records rather than a statement (RECORDS; app_export.py). Simplifi's older
export (account, state, postedOn, payee, ...) is not this one.
"""

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

RECORDS = True

_HEADER = {"Date", "Account", "Status", "Payee", "Category", "Tags", "Notes", "Amount"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    return app_export.has_columns(header, _HEADER, "Simplifi")


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    order = app_export.date_order([r.get("Date", "") for r in rows])
    transactions = []
    for n, r in enumerate(rows, start=2):
        description = (r.get("Payee") or "").strip() or (r.get("Notes") or "").strip() or (r.get("Category") or "").strip()
        if not description:
            raise ValueError(f"row {n}: no payee")
        transactions.append(app_export.row(
            app_export.date(r["Date"], order), description, app_export.money(r["Amount"]), (r.get("Account") or "").strip(),
        ))
    return {"institution": "", "statementDate": "", "transactions": transactions}
