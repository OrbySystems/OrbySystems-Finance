"""YNAB's register export (the web app's "Export" of an account's or the
whole plan's transactions, and YNAB 4's): Account, Date, Payee, the
category columns, Memo, Outflow, Inflow, Cleared.

There is no signed amount: Outflow is money out and Inflow money in, the
unused one written as a zero, with the plan's currency symbol. Dates follow
the plan's own format, day first with dots (01.08.2026) in some. Every
account is in the file, named but with no number or bank: each row carries
its Account for OrbySystems to ask which account it is. A starting balance
is not a transaction, nor is a tracking account's balance adjustment (no
category): both are left out. Somebody's records rather than a statement
(RECORDS; app_export.py).
"""

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

RECORDS = True

_HEADER = {"Account", "Date", "Payee", "Memo", "Outflow", "Inflow"}

_ADJUSTMENTS = {"manual balance adjustment", "reconciliation balance adjustment"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    return app_export.has_columns(header, _HEADER, "YNAB")


def _category(r: dict) -> str:
    for column in ("Category Group/Category", "Category", "Sub Category"):
        if value := (r.get(column) or "").strip():
            return value
    return ""


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    order = app_export.date_order([r.get("Date", "") for r in rows])
    transactions = []
    for n, r in enumerate(rows, start=2):
        payee = (r.get("Payee") or "").strip()
        if payee.lower() == "starting balance":
            continue
        if payee.lower() in _ADJUSTMENTS and not _category(r):
            continue
        outflow = app_export.money(r["Outflow"]) if (r.get("Outflow") or "").strip() else 0.0
        inflow = app_export.money(r["Inflow"]) if (r.get("Inflow") or "").strip() else 0.0
        amount = round(abs(inflow) - abs(outflow), 2)
        if amount == 0:
            continue
        description = payee or (r.get("Memo") or "").strip() or _category(r)
        if not description:
            raise ValueError(f"row {n}: no payee, memo or category")
        transactions.append(app_export.row(app_export.date(r["Date"], order), description, amount, (r.get("Account") or "").strip()))
    return {"institution": "", "statementDate": "", "transactions": transactions}
