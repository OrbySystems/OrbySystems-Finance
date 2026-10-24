"""OrbySystems' import CSV: reading a file in it (import_csv_schema.json,
IMPORT-CSV.md).

A file in the import CSV is somebody's own records, converted - by a script
their own AI model wrote from OrbySystems' Records Converter, or by hand.
It is read exactly: a value that isn't in the form the schema gives stops
the read, naming the row and the column, rather than being guessed at. Not
a parser itself; orbysystems_transactions_csv.py and
orbysystems_investments_csv.py read through it.
"""
from __future__ import annotations

import csv
import json
import os
import re

import parser_common

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(parser_common.__file__)), "import_csv_schema.json")

with open(_SCHEMA_PATH, encoding="utf-8") as _f:
    SCHEMA = json.load(_f)

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMBER = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)$")
_LAST4 = re.compile(r"^\d{4}$")
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


def columns(kind: str) -> list[dict]:
    return SCHEMA["files"][kind]["columns"]


def matches(kind: str, header: list[str]) -> tuple[bool, str]:
    """Whether header is the import CSV's for kind: every required column,
    any optional ones, nothing else, named exactly."""
    names = [h.strip() for h in header]
    allowed = {c["name"] for c in columns(kind)}
    required = {c["name"] for c in columns(kind) if c["required"]}
    missing = sorted(required - set(names))
    if missing:
        return False, f"not OrbySystems' {kind} import CSV: missing column(s) {missing}"
    extra = sorted(set(names) - allowed)
    if extra:
        return False, f"not OrbySystems' {kind} import CSV: unknown column(s) {extra}"
    if len(set(names)) != len(names):
        return False, f"not OrbySystems' {kind} import CSV: a column is named twice"
    return True, f"OrbySystems' {kind} import CSV"


class _Row:
    """One row's values, read by the schema's formats. The row number in
    errors counts the header as row 1, as a spreadsheet shows it."""

    def __init__(self, kind: str, row: dict[str, str], line: int):
        self.values = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        self.formats = {c["name"]: c for c in columns(kind)}
        self.line = line

    def _fail(self, name: str, what: str):
        raise ValueError(f"row {self.line}, column {name}: {what}")

    def text(self, name: str) -> str:
        v = self.values.get(name, "")
        if not v and self.formats[name]["required"]:
            self._fail(name, "is empty")
        return v

    def date(self, name: str) -> str:
        v = self.text(name)
        if v and not _DATE.match(v):
            self._fail(name, f"{v!r} is not a date as YYYY-MM-DD")
        return v

    def number(self, name: str) -> float | None:
        v = self.text(name)
        if not v:
            return None
        if not _NUMBER.match(v):
            self._fail(name, f"{v!r} is not a plain number (a dot for decimals, no symbols or separators)")
        return float(v)

    def choice(self, name: str) -> str:
        v = self.text(name)
        values = self.formats[name]["values"]
        if v not in values:
            self._fail(name, f"{v!r} is not one of {', '.join(values)}")
        return v

    def last4(self, name: str) -> str:
        v = self.text(name)
        if not _LAST4.match(v):
            self._fail(name, f"{v!r} is not four digits")
        return v

    def currency(self, name: str) -> str:
        v = self.text(name)
        if v and not _CURRENCY.match(v):
            self._fail(name, f"{v!r} is not a three-letter currency code")
        return v.upper()


def rows(kind: str, raw_rows: list[dict[str, str]]):
    """Each row of a file in the import CSV for kind, ready to read."""
    for i, raw in enumerate(raw_rows, start=2):
        yield _Row(kind, raw, i)


def account_fields(r: _Row) -> dict:
    """The contract's account fields from an import CSV row: its last four
    digits, type and institution, with its own name and currency when the
    row gives them."""
    out = {
        "account": r.last4("account_last4"),
        "accountType": r.choice("account_type"),
        "institution": r.text("institution"),
    }
    if name := r.values.get("account_name", ""):
        out["account_name"] = name
    if currency := (r.currency("currency") if "currency" in r.values else ""):
        out["currency_code"] = currency
    return out


def statement_institution(rows: list[dict]) -> str:
    """The one institution every row names, which the result carries in
    its place, or "" when the rows name several (each row keeps its own)."""
    institutions = {r.get("institution", "") for r in rows}
    if len(institutions) != 1:
        return ""
    institution = institutions.pop()
    for r in rows:
        r.pop("institution", None)
    return institution


# --- checking a converted file ---------------------------------------------
#
#     python import_csv.py <path>
#
# prints what a file in the import CSV holds, for OrbySystems' Records
# Converter to show before anything is imported: which of the three files it
# is, its rows, each account with its dates and totals, and every value out
# of form, by row and column (the first 50). The file's own values appear
# only in the problems, shown on the person's own machine.

_MAX_PROBLEMS = 50


def check(path: str) -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        raw = [r for r in reader if any(cell.strip() for cell in r)]
    kind = next((k for k in SCHEMA["files"] if matches(k, header)[0]), "")
    if not kind:
        reasons = "; ".join(matches(k, header)[1] for k in SCHEMA["files"])
        return {"kind": "", "rows": len(raw), "accounts": [], "problems": [{"row": 1, "column": "", "problem": reasons}]}
    names = [h.strip() for h in header]
    accounts: dict[tuple, dict] = {}
    problems = []
    date_column = "as_of" if kind == "holdings" else "date"
    for line, values in enumerate(raw, start=2):
        if len(values) != len(names):
            problems.append({"row": line, "column": "", "problem": f"has {len(values)} cells where the header has {len(names)}"})
            continue
        r = _Row(kind, dict(zip(names, values)), line)
        for c in columns(kind):
            name = c["name"]
            if name not in names:
                continue
            reader_of = {"date": r.date, "number": r.number, "choice": r.choice, "last4": r.last4,
                         "currency": r.currency, "text": r.text}[c["format"]]
            try:
                reader_of(name)
            except ValueError as e:
                if len(problems) < _MAX_PROBLEMS:
                    problems.append({"row": line, "column": name, "problem": str(e).split(": ", 1)[-1]})
        key = (r.values.get("institution", ""), r.values.get("account_last4", ""), r.values.get("account_type", ""))
        a = accounts.setdefault(key, {"institution": key[0], "last4": key[1], "type": key[2],
                                      "name": r.values.get("account_name", ""), "rows": 0, "first": "", "last": "",
                                      "in": 0.0, "out": 0.0})
        a["rows"] += 1
        day = r.values.get(date_column, "")
        if _DATE.match(day):
            a["first"] = min(a["first"] or day, day)
            a["last"] = max(a["last"], day)
        if kind != "holdings" and _NUMBER.match(r.values.get("amount", "")):
            amount = float(r.values["amount"])
            if amount >= 0:
                a["in"] += amount
            else:
                a["out"] += amount
    for a in accounts.values():
        a["in"], a["out"] = round(a["in"], 2), round(a["out"], 2)
    return {"kind": kind, "rows": len(raw), "accounts": list(accounts.values()), "problems": problems}


if __name__ == "__main__":
    import sys

    try:
        print(json.dumps(check(sys.argv[1])))
    except (OSError, UnicodeDecodeError, csv.Error, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
