"""Capital One 360 checking and savings activity, downloaded as CSV: Account
Number, Transaction Description, Transaction Date, Transaction Type,
Transaction Amount, Balance.

Transaction Type says which way each row went ("Debit" out, "Credit" in);
the amount is read unsigned and signed by it, so a file that signs its
amounts too reads the same. Dates are month first (03/05/24). Account
Number's last four digits file the row. The file doesn't say checking or
savings, so the type is left for the import to ask.
"""

from institutions import common

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Capital One"

_HEADER = {"Account Number", "Transaction Description", "Transaction Date", "Transaction Type", "Transaction Amount", "Balance"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "Capital One 360 account activity export header matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    order = app_export.date_order([r.get("Transaction Date", "") for r in rows])
    transactions = []
    for n, row in enumerate(rows, start=2):
        way = (row.get("Transaction Type") or "").strip().lower()
        if way not in ("debit", "credit"):
            raise ValueError(f"row {n}: Transaction Type {row.get('Transaction Type')!r} is neither Debit nor Credit")
        raw = (row.get("Transaction Amount") or "").strip()
        if not raw:
            raise ValueError(f"row {n}: no amount")
        amount = abs(app_export.money(raw))
        balance_raw = (row.get("Balance") or "").strip()
        description = " ".join((row.get("Transaction Description") or "").split())
        if not description:
            raise ValueError(f"row {n}: no description")
        transactions.append({
            "date": app_export.date(row["Transaction Date"], order),
            "description": description,
            "amount": -amount if way == "debit" else amount,
            "balance": app_export.money(balance_raw) if balance_raw else None,
            "account": common.last4_digits(row.get("Account Number") or ""),
            "accountType": "",
        })
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
