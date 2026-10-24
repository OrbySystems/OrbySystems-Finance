"""Bank of America credit card activity, downloaded as CSV: Posted Date,
Reference Number, Payee, Address, Amount.

How the download signs Amount is not documented, so the rows say: a payment
to the card is positive when they are signed as the contract wants, negative
when they follow the card's balance (app_export.card_sign), and the rows are
negated in that case. Dates are month first (03/05/2024). Bank of America
names the download for the month and the card ("May2024_1234.csv"): its
four digits file the rows. Renamed, the import asks which account it is.
"""

import os
import re

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Bank of America"

_HEADER = {"Posted Date", "Reference Number", "Payee", "Address", "Amount"}

_FILE_NAME = re.compile(r"(?i)^[a-z]+\d{4}_(\d{4})\.csv$")


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Bank of America card activity export header matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    named = _FILE_NAME.match(os.path.basename(csv_path or ""))
    account = named.group(1) if named else ""
    read = []
    for n, row in enumerate(rows, start=2):
        raw = (row.get("Amount") or "").strip()
        if not raw:
            raise ValueError(f"row {n}: no amount")
        description = " ".join((row.get("Payee") or "").split())
        if not description:
            raise ValueError(f"row {n}: no payee")
        read.append((row, app_export.money(raw), description))
    sign = app_export.card_sign([(a, d) for _, a, d in read])
    transactions = []
    for row, amount, description in read:
        txn = {
            "date": app_export.date(row["Posted Date"], "mdy"),
            "description": description,
            "amount": sign * amount,
            "balance": None,
            "account": account,
            "accountType": "Credit Card",
        }
        reference = (row.get("Reference Number") or "").strip()
        if reference:
            txn["reference"] = reference
        transactions.append(txn)
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
