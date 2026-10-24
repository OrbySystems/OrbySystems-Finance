"""Mint's transaction export (transactions.csv, from Mint's website before
it closed in March 2024): Date, Description, Original Description, Amount,
Transaction Type, Category, Account Name, Labels, Notes.

Amount is always positive; Transaction Type says which way it went
("debit" out, "credit" in). Dates are month first (3/5/2024). Every account
is in the one file, named but with no number or bank: each row carries its
Account Name for OrbySystems to ask which account it is. Somebody's records
rather than a statement (RECORDS; app_export.py).
"""

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

RECORDS = True

_HEADER = {"Date", "Description", "Original Description", "Amount", "Transaction Type", "Category", "Account Name"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    return app_export.has_columns(header, _HEADER, "Mint")


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    transactions = []
    for n, r in enumerate(rows, start=2):
        way = (r.get("Transaction Type") or "").strip().lower()
        if way not in ("debit", "credit"):
            raise ValueError(f"row {n}: Transaction Type {r.get('Transaction Type')!r} is neither debit nor credit")
        amount = abs(app_export.money(r["Amount"]))
        description = (r.get("Description") or "").strip() or (r.get("Original Description") or "").strip() or (r.get("Category") or "").strip()
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append(app_export.row(
            app_export.date(r["Date"], "mdy"), description, -amount if way == "debit" else amount,
            (r.get("Account Name") or "").strip(),
        ))
    return {"institution": "", "statementDate": "", "transactions": transactions}
