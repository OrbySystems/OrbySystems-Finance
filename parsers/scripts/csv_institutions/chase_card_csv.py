"""Chase credit card activity, downloaded as CSV: Transaction Date, Post
Date, Description, Category, Type, Amount, Memo. (Chase checking and
savings downloads have their own layout: chase_checking_csv.)

Amount is signed already as the contract wants - a purchase negative, a
payment or a return positive - so nothing is negated. Dates are month first
(03/05/2024). The file holds no card number, but Chase names the download
for the card ("Chase1234_Activity20240101_20240131_20240201.CSV"): its four
digits file the rows. Renamed, the import asks which account it is.
"""

import os
import re

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Chase"

_HEADER = {"Transaction Date", "Post Date", "Description", "Category", "Type", "Amount"}

_FILE_NAME = re.compile(r"(?i)^chase(\d{4})_activity")


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Chase card activity export header matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    named = _FILE_NAME.match(os.path.basename(csv_path or ""))
    account = named.group(1) if named else ""
    transactions = []
    for n, row in enumerate(rows, start=2):
        raw = (row.get("Amount") or "").strip()
        if not raw:
            raise ValueError(f"row {n}: no amount")
        description = " ".join((row.get("Description") or "").split())
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append({
            "date": app_export.date(row["Transaction Date"], "mdy"),
            "description": description,
            "amount": app_export.money(raw),
            "balance": None,
            "account": account,
            "accountType": "Credit Card",
        })
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
