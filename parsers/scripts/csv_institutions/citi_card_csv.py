"""Citi credit card activity, downloaded as CSV: Status, Date, Description,
Debit, Credit, and Member Name on a card with named cardmembers.

There is no signed amount: a charge fills Debit, written positive, and a
payment or a credit fills Credit, written negative. A row's amount is the
Debit negated, or the Credit made positive - negative when the person is
poorer. A pending row is left out: it posts later, perhaps for another
amount, and would then count twice. Dates are month first (03/05/2024). The
file names no card number, so the import asks which account it is.
"""

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Citi"

_HEADER = {"Status", "Date", "Description", "Debit", "Credit"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Citi card activity export header matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    transactions = []
    for n, row in enumerate(rows, start=2):
        if (row.get("Status") or "").strip().lower() == "pending":
            continue
        debit = (row.get("Debit") or "").strip()
        credit = (row.get("Credit") or "").strip()
        if not debit and not credit:
            raise ValueError(f"row {n}: neither Debit nor Credit")
        amount = (-app_export.money(debit) if debit else 0.0) + (abs(app_export.money(credit)) if credit else 0.0)
        description = " ".join((row.get("Description") or "").split())
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append({
            "date": app_export.date(row["Date"], "mdy"),
            "description": description,
            "amount": round(amount, 2),
            "balance": None,
            "account": "",
            "accountType": "Credit Card",
        })
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
