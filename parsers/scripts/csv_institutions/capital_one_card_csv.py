"""Capital One credit card activity, downloaded as CSV (View Statements >
Download Transactions): Transaction Date, Posted Date, Card No., Description,
Category, Debit, Credit.

There is no signed amount: a charge fills Debit and a payment or credit
fills Credit, the other left blank, so a row's amount is Credit less Debit -
negative when the person is poorer, as the contract wants, with nothing to
negate. Each is taken as written, so a reversal written negative in Debit
is money back. Dates are YYYY-MM-DD. Card No. is the card's last four
digits.
"""

from institutions import common

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Capital One"

_HEADER = {"Transaction Date", "Posted Date", "Card No.", "Description", "Debit", "Credit"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Capital One card activity export header matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    order = app_export.date_order([r.get("Transaction Date", "") for r in rows])
    transactions = []
    for n, row in enumerate(rows, start=2):
        debit = (row.get("Debit") or "").strip()
        credit = (row.get("Credit") or "").strip()
        if not debit and not credit:
            raise ValueError(f"row {n}: neither Debit nor Credit")
        amount = (app_export.money(credit) if credit else 0.0) - (app_export.money(debit) if debit else 0.0)
        description = " ".join((row.get("Description") or "").split())
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append({
            "date": app_export.date(row["Transaction Date"], order),
            "description": description,
            "amount": round(amount, 2),
            "balance": None,
            "account": common.last4_digits(row.get("Card No.") or ""),
            "accountType": "Credit Card",
        })
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
