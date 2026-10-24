"""Bank of America checking and savings activity, downloaded as "Microsoft
Excel format (CSV)": a summary block (Description, Summary Amt.: the
beginning balance, total credits and debits, the ending balance), then the
transactions under Date, Description, Amount, Running Bal. The summary's
own row of labels is what the dispatcher takes for the header, so this
parser reads the file itself from the transactions' header on; a file whose
summary was deleted reads the same.

Amount is signed already - a withdrawal negative, a deposit positive - and
Running Bal. is the balance after the row. The first row is the beginning
balance, with no amount: it is not a transaction. Dates are month first
(03/05/2024). The file names neither the account nor whether it is
checking or savings, so the import asks.
"""

import csv

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Bank of America"

_HEADER = {"Date", "Description", "Amount", "Running Bal."}
_SUMMARY = {"Description", "Summary Amt."}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    if _HEADER <= cols:
        return True, "Bank of America account activity export header matched"
    if _SUMMARY <= cols and len([c for c in cols if c]) == 2:
        return True, "Bank of America account activity export summary matched"
    return False, f"missing column(s) {sorted(_HEADER - cols)}"


def _rows(csv_path: str) -> list[dict[str, str]]:
    """The transactions, under their own header, whatever stands above it."""
    if csv_path.lower().endswith(".xlsx"):
        raise ValueError("Bank of America's export is a CSV file; this is a workbook")
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        grid = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    at = next((i for i, r in enumerate(grid) if _HEADER <= {c.strip() for c in r}), None)
    if at is None:
        raise ValueError("no Date, Description, Amount, Running Bal. header under the summary")
    header = [c.strip() for c in grid[at]]
    return [{header[i]: (r[i] if i < len(r) else "") for i in range(len(header))} for r in grid[at + 1:]]


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = _rows(csv_path)
    transactions = []
    for n, row in enumerate(rows, start=1):
        raw = (row.get("Amount") or "").strip()
        description = " ".join((row.get("Description") or "").split())
        if not raw:
            if description.lower().startswith("beginning balance"):
                continue  # the beginning balance, which is not a transaction
            raise ValueError(f"row {n}: no amount")
        if not description:
            raise ValueError(f"row {n}: no description")
        balance = (row.get("Running Bal.") or "").strip()
        transactions.append({
            "date": app_export.date(row["Date"], "mdy"),
            "description": description,
            "amount": app_export.money(raw),
            "balance": app_export.money(balance) if balance else None,
            "account": "",
            "accountType": "",
        })
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
