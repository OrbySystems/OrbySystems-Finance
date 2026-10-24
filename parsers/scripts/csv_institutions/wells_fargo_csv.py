"""Wells Fargo account activity, downloaded as "Comma Delimited": no header
row, five columns - the date, the amount, an asterisk (posted), an empty
column, the description.

There is no header, so the dispatcher hands this parser the first row as
one; it reads the file itself, every row. The fourth column is empty, or a
check's number. A checking or savings download is signed already - a
withdrawal negative, a deposit positive. A credit card's sign is not
documented, so its rows say (app_export.card_sign). Wells Fargo names the
download for the account's kind ("Checking1.csv", "CreditCard1.csv"), which
gives the account type. A renamed download's kind is unknown, and its rows
are kept as written: reading a sign from a checking account's rows would
misread its card payments. The file names no account number, so the import
asks which account it is. Dates are month first.
"""

import csv
import os
import re

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "Wells Fargo"

_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")

_KINDS = [(re.compile(r"(?i)^credit\s*card"), "Credit Card"), (re.compile(r"(?i)^checking"), "Checking"),
          (re.compile(r"(?i)^savings"), "Savings")]


def _is_row(cells: list[str]) -> bool:
    cells = [c.strip() for c in cells]
    if len(cells) != 5 or not _DATE.match(cells[0]) or cells[2] not in ("*", "") or not (cells[3] == "" or cells[3].isdigit()) or not cells[4]:
        return False
    try:
        app_export.money(cells[1])
    except ValueError:
        return False
    return True


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    if not _is_row(header):
        return False, "not Wells Fargo's headerless five-column export"
    return True, "Wells Fargo comma-delimited activity export matched"


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    if csv_path.lower().endswith(".xlsx"):
        raise ValueError("Wells Fargo's export is a CSV file; this is a workbook")
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        grid = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    kind = next((t for pattern, t in _KINDS if pattern.match(os.path.basename(csv_path))), "")
    read = []
    for n, cells in enumerate(grid, start=1):
        if not _is_row(cells):
            raise ValueError(f"row {n}: not a row of the export (date, amount, *, blank, description)")
        read.append((app_export.date(cells[0].strip(), "mdy"), app_export.money(cells[1]), " ".join(cells[4].split())))
    sign = app_export.card_sign([(a, d) for _, a, d in read]) if kind == "Credit Card" else 1
    transactions = [{
        "date": day, "description": description, "amount": sign * amount, "balance": None,
        "account": "", "accountType": kind,
    } for day, amount, description in read]
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
