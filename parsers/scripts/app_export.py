"""Reading a money app's transaction export: Mint, YNAB, Monarch, Tiller,
Quicken Simplifi, Empower. Not a parser itself; the csv_institutions/
parsers for those apps read through it, and so do card issuers' CSV
parsers (amex_csv, capital_one_*, discover_card_csv) for its amounts and
dates.

An app's export is somebody's records across all their accounts, so its
parsers say so (RECORDS): where an account's statements or its bank's own
export cover the same days, theirs are the rows that count (CONTRACT.md,
"Where files overlap"). Most name an account but give no number or bank
for it: the rows carry the name (account_name), and OrbySystems asks the
user which account each name is.
"""
from __future__ import annotations

import datetime
import re

_SYMBOLS = re.compile(r"[$€£¥\s ]|[A-Z]{1,3}\$|USD|EUR|GBP|CAD")


def money(raw: str) -> float:
    """An app's amount: "$1,234.56", "-$45.00", "$-45.00", "(45.00)",
    "1.234,56 €", "84,23€". Raises ValueError on anything else."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty amount")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = s.replace("−", "-")
    s = _SYMBOLS.sub("", s)
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    elif s.endswith("-"):
        negative, s = not negative, s[:-1]
    s = s.lstrip("+")
    # A decimal comma: "1.234,56" or "84,23" (two digits after the last comma).
    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}|\d+,\d{2}", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", s):
        raise ValueError(f"not an amount: {raw!r}")
    value = float(s)
    return -value if negative else value


_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_SLASHED = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{2}|\d{4})$")


def date_order(values: list[str]) -> str:
    """"dmy" when the file writes its dates day first - dots, or a first
    part over 12 - else "mdy", the US apps' default."""
    for v in values:
        m = _SLASHED.match((v or "").strip())
        if not m:
            continue
        if "." in v or int(m.group(1)) > 12:
            return "dmy"
    return "mdy"


def date(raw: str, order: str = "mdy") -> str:
    """An app's date as YYYY-MM-DD: "2024-03-05", "3/5/2024", "03/05/24",
    "05.03.2024". Raises ValueError on anything else."""
    s = (raw or "").strip()
    if m := _ISO.match(s):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif m := _SLASHED.match(s):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000 if y < 70 else 1900
        mo, d = (b, a) if order == "dmy" else (a, b)
    else:
        raise ValueError(f"not a date: {raw!r}")
    return datetime.date(y, mo, d).isoformat()


_TYPES = [
    (re.compile(r"(?i)\bchecking\b|\bcurrent account\b"), "Checking"),
    (re.compile(r"(?i)\bsavings?\b"), "Savings"),
    (re.compile(r"(?i)\bmoney market\b"), "Money Market"),
    (re.compile(r"(?i)\bcredit\b|\bcard\b|\bvisa\b|\bmastercard\b|\bamex\b|\bamerican express\b|\bdiscover\b"), "Credit Card"),
]


def account_type(name: str) -> str:
    """The account's type when its name says it ("Chase Checking", "Amex
    Gold Card"), else "" for OrbySystems to ask."""
    for pattern, kind in _TYPES:
        if pattern.search(name or ""):
            return kind
    return ""


def has_columns(header: list[str], required: set[str], app: str) -> tuple[bool, str]:
    names = {h.strip() for h in header}
    missing = sorted(required - names)
    if missing:
        return False, f"not {app}'s export: missing column(s) {missing}"
    return True, f"{app} transactions export"


def row(date_iso: str, description: str, amount: float, account_name: str, **extra) -> dict:
    """A cash row for an account the export names but gives no number for."""
    out = {
        "date": date_iso,
        "description": description,
        "amount": amount,
        "balance": None,
        "account": "",
        "accountType": account_type(account_name),
    }
    if account_name:
        out["account_name"] = account_name
    out.update(extra)
    return out


# Money back to the card holder, in an issuer's words: a payment to the card
# ("PAYMENT - THANK YOU", "AUTOPAY", "ONLINE PAYMENT") or a refund. Not a
# merchant's "BILL PAYMENT" charged to the card, nor a "LATE PAYMENT FEE".
_MONEY_BACK = re.compile(r"(?i)thank\s*you|\bautopay\b|\bauto(matic)?\s+payment|\b(online|mobile|internet|electronic|e-?)\s*payment|"
                         r"\bpayment\s+(received|posted)|\bpymt\b|\brefund\b|\breturn(ed)?\b")
_NOT_MONEY_BACK = re.compile(r"(?i)\bfee\b|\bbill\s*pay|\binterest\b|\bcharge\b")


def card_sign(amounts_and_descriptions: list[tuple[float, str]]) -> int:
    """How a card export signs its rows, from the rows themselves, for an
    issuer whose convention isn't documented: 1 when they are already as the
    contract wants (a purchase negative), -1 when they are as the card's
    balance moves (a purchase positive) and need negating.

    Money back - a payment to the card, a refund - says it best: positive in
    the first, negative in the second. Where none does, or they disagree
    evenly, purchases outnumber everything else on a card: most rows
    negative means the first."""
    back = [a for a, d in amounts_and_descriptions
            if a and _MONEY_BACK.search(d or "") and not _NOT_MONEY_BACK.search(d or "")]
    positive = sum(1 for a in back if a > 0)
    if back and positive * 2 != len(back):
        return 1 if positive * 2 > len(back) else -1
    rows = [a for a, _ in amounts_and_descriptions if a]
    negative = sum(1 for a in rows if a < 0)
    return 1 if negative * 2 >= len(rows) else -1
