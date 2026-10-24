"""Tiller's Transactions sheet, downloaded as CSV (or the workbook as
.xlsx): Date, Description, Category, Amount, Account, Account #,
Institution, and the other columns a Tiller template has.

Amount is signed: income, refunds and credits positive, expenses negative.
Account # is the account's last four digits, written "xxxx1102", and
Institution its bank, so each row files under its account with no
question asked; Account is the account's name. Somebody's records rather
than a statement (RECORDS; app_export.py).
"""

from institutions import common

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

RECORDS = True

_HEADER = {"Date", "Description", "Amount", "Account", "Account #", "Institution"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    return app_export.has_columns(header, _HEADER, "Tiller")


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    order = app_export.date_order([r.get("Date", "") for r in rows])
    transactions = []
    for n, r in enumerate(rows, start=2):
        if not (r.get("Date") or "").strip() and not (r.get("Amount") or "").strip():
            continue  # a blank line at the foot of the sheet
        description = (r.get("Description") or "").strip() or (r.get("Full Description") or "").strip()
        if not description:
            raise ValueError(f"row {n}: no description")
        name = (r.get("Account") or "").strip()
        row = app_export.row(app_export.date(r["Date"], order), description, app_export.money(r["Amount"]), name)
        number = common.last4_digits(r.get("Account #") or "")
        institution = (r.get("Institution") or "").strip()
        if len(number) == 4 and institution:
            row["account"] = number
            row["institution"] = institution
        transactions.append(row)
    return {"institution": "", "statementDate": "", "transactions": transactions}
