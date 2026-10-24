"""OrbySystems' import CSV for transactions: somebody's own records of bank,
credit-card and similar accounts, converted to OrbySystems' format
(IMPORT-CSV.md, import_csv_schema.json's "transactions").

The file is the person's records, not an institution's statement, so it
says so (RECORDS): where an account's statements or its institution's
exports cover the same days, theirs are the rows that count, and these fill
the rest (CONTRACT.md, "Where files overlap"). Every value is read exactly
as the schema gives it; one that isn't stops the read, naming the row.
"""

import import_csv
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED

RECORDS = True

# Recognised by its exact header, before any parser that might take a
# date/description/amount file for its own.
PRIORITY = 10

_KIND = "transactions"


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    return import_csv.matches(_KIND, header)


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    transactions = []
    for r in import_csv.rows(_KIND, rows):
        row = {
            "date": r.date("date"),
            "description": r.text("description"),
            "amount": r.number("amount"),
            "balance": r.number("balance") if "balance" in r.values else None,
        }
        row.update(import_csv.account_fields(r))
        transactions.append(row)
    return {
        "institution": import_csv.statement_institution(transactions),
        "statementDate": "",
        "transactions": transactions,
    }
