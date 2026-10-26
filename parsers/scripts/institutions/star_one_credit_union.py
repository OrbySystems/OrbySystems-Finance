"""Star One Credit Union member statement parser.

Format: the monthly statement Star One sends its members, every share and
checking account of a membership in one PDF. Page 1 opens with the member
number and the period, then an account summary; each account follows under
a heading that names it and its suffix:

    Member No. Period Ending Page
    123456789 09/30/26 1 of 1
    REGULAR SAVINGS ACCOUNT ACCT# 1
    Beginning Balance Deposits/Credits Withdrawals/Debits Ending Balance YTD Dividends
    $ 1,204.17 $ 2.51 $ 0.00 $ 1,206.68 $ 18.40
    Date Transaction Description Deposit Withdrawal Balance
    SEP30 DIVIDEND 2.51 1,206.68
    ANNUAL PERCENTAGE YIELD EARNED FROM 09/01/26 THRU 09/30/26
    WAS 2.50%

A row is its date (month and day, "SEP30"), its description, one amount and
the balance after it; the lines under it, up to the next row, describe it
further. Whether the amount was printed under Deposit or under Withdrawal is
lost in the text, so it is recovered from the balances: each row's balance
is the one before it plus or minus its amount, the first row's the account's
Beginning Balance. A row the balances can't place is placed by the
account's Deposits/Credits and Withdrawals/Debits totals.

The statement's own arithmetic is reported as checks (CONTRACT.md,
"Checks"), per account: its deposits against Deposits/Credits, its
withdrawals against Withdrawals/Debits, Beginning Balance plus every row
against Ending Balance, and every dated line that was not read. An account
this parser doesn't read (a loan, a card) has its dated lines reported as
not read, so the rest of the statement still imports.

An account's number is the member number with the account's suffix after
it; its last four digits are kept.

Built from a scrambled sample of a real statement (README_addparser.md),
whose words but the layout's own were faked: detect() and the account
headings rest only on those ("ACCT#", "Period Ending", the statement's
starone domain).
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1

INSTITUTION = "Star One Credit Union"

DIAGNOSTIC_FIELDS = {
    "periodEnding": "Period Ending",
    "beginningBalance": "Beginning Balance",
    "endingBalance": "Ending Balance",
}

_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_MONEY = r"-?\$?\s*-?[\d,]+\.\d{2}-?"
# "123456789 09/30/26 1 of 2", under "Member No. Period Ending Page".
_MEMBER_RE = re.compile(r"^(\d{4,})\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+\d+\s+of\s+\d+$")
_HEADING_RE = re.compile(r"^(?P<name>.+?)\s+ACCT#\s*(?P<suffix>[0-9A-Za-z]+)$")
_SUMMARY_LABELS_RE = re.compile(r"^Beginning Balance\s+Deposits/Credits\s+Withdrawals/Debits\s+Ending Balance\b",
                                re.IGNORECASE)
_TABLE_HEADER_RE = re.compile(r"^Date\s+Transaction Description\s+Deposit\s+Withdrawal\s+Balance$", re.IGNORECASE)
_ROW_RE = re.compile(r"^(?P<mon>[A-Z]{3})(?P<day>\d{2})\s+(?P<desc>.+?)\s+(?P<amount>" + _MONEY + r")\s+(?P<balance>"
                     + _MONEY + r")$")
_DATED_RE = re.compile(r"^(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b")
_ENDS_WITH_AMOUNT_RE = re.compile(r"\d\.\d{2}-?$")
# Lines in an account that are neither rows nor what describes them.
_NOTE_RE = re.compile(r"^(?:ANNUAL PERCENTAGE YIELD EARNED\b|WAS\s+[\d.]+%$|Member No\.|\d{4,}\s+\d{1,2}/\d{1,2}/\d{2,4}\s+\d+\s+of\s+\d+$)",
                      re.IGNORECASE)
# Where the accounts end: the year-to-date totals and the rates table after them.
_END_RE = re.compile(r"^(?:YTD ACCOUNT\b|Deposit Account Totals\b|YTD Total Dividends\b)", re.IGNORECASE)

_EPS = 0.005

# An account that is a debt, whatever else its name says ("SHARE SECURED
# LOAN" is a loan): its rows are reported, not read as a deposit account's.
_DEBT_RE = re.compile(r"\b(?:LOAN|CREDIT|VISA|MASTERCARD|MORTGAGE|HELOC|LINE)\b")
# A page's footer, never part of a row's description.
_FOOTER_RE = re.compile(r"\b(?:continued|federally insured|NCUA|equal housing)\b|^Page\s*:?\s*\d+\s+of\s+\d+$",
                        re.IGNORECASE)


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    if "starone" in lower and "acct#" in lower and "period ending" in lower and "member no" in lower:
        return True, "matched Star One Credit Union member statement"
    return False, "Star One Credit Union markers (starone, Member No., Period Ending, ACCT#) not found"


def _money(raw: str) -> float:
    negative = raw.strip().startswith("-") or raw.strip().endswith("-") or "$-" in raw.replace(" ", "")
    value = float(re.sub(r"[^\d.]", "", raw))
    return -value if negative else value


def _year(raw: str) -> int:
    value = int(raw)
    return 2000 + value if value < 100 else value


def _account_type(name: str) -> str | None:
    """The account type a heading names, or None for an account this parser
    doesn't read (a loan, a card)."""
    upper = name.upper()
    if _DEBT_RE.search(upper):
        return None
    if "CHECKING" in upper:
        return "Checking"
    if any(word in upper for word in ("SAVINGS", "MONEY MARKET", "CERTIFICATE", "SHARE", "CLUB")):
        return "Savings"
    return None


class _Account:
    def __init__(self, name: str, suffix: str, page: int):
        self.name, self.suffix, self.page = name, suffix, page
        self.summary: list[float] | None = None
        self.rows: list[dict] = []


def _place_signs(account: _Account) -> None:
    """Gives each row's amount the sign its balances show: the change from
    the balance before it (the Beginning Balance for the first row). A row
    the balances can't place takes the sign the account's totals leave for
    it."""
    beginning, deposits, withdrawals = account.summary[0], account.summary[1], account.summary[2]
    unplaced = []
    previous = beginning
    for row in account.rows:
        change = row["balance"] - previous
        if abs(change - row["printed"]) < _EPS:
            row["amount"] = row["printed"]
        elif abs(change + row["printed"]) < _EPS:
            row["amount"] = -row["printed"]
        else:
            unplaced.append(row)
        previous = row["balance"]
    if not unplaced:
        return
    left_in = deposits - sum(r["amount"] for r in account.rows if r.get("amount", 0) > 0)
    left_out = abs(withdrawals) + sum(r["amount"] for r in account.rows if r.get("amount", 0) < 0)
    for row in unplaced:
        # The total whose remainder it comes closer to using up takes it.
        if abs(left_in - row["printed"]) <= abs(left_out - row["printed"]):
            row["amount"] = row["printed"]
            left_in -= row["printed"]
        else:
            row["amount"] = -row["printed"]
            left_out -= row["printed"]


def _date(mon: str, day: str, ending: datetime) -> str:
    month = _MONTHS[mon]
    # A statement ending in January can carry December's last days.
    year = ending.year if month <= ending.month else ending.year - 1
    return datetime(year, month, int(day)).strftime("%Y-%m-%d")


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [[line.strip() for line in text.splitlines()] for text in pages_text]
    member = ending = None
    for lines in pages:
        for line in lines:
            m = _MEMBER_RE.match(line)
            if m:
                member = m.group(1)
                month, day, year = m.group(2).split("/")
                ending = datetime(_year(year), int(month), int(day))
                break
        if ending:
            break
    if ending is None:
        raise parser_common.ParserDiagnosticError(
            "no member number and Period Ending line ('123456789 09/30/26 1 of 1') found",
            code="PARSER_STATEMENT_DATE_INVALID", stage="metadata", missing_fields=("periodEnding",))

    accounts: list[_Account] = []
    unread: list[dict] = []
    account: _Account | None = None
    reading: dict | None = None  # the row whose description lines follow
    expect_summary = False
    ended = False
    for p, lines in enumerate(pages):
        reading = None
        for n, line in enumerate(lines):
            if not line or ended:
                continue
            heading = _HEADING_RE.match(line)
            # A heading is followed by its summary or its column header; a
            # description line can end in "ACCT# 1" too ("TO REGULAR
            # SAVINGS ACCT# 1").
            following = next((x for x in lines[n + 1:] if x), "")
            if heading and following and not (_SUMMARY_LABELS_RE.match(following) or _TABLE_HEADER_RE.match(following)):
                heading = None
            if heading:
                # An account carried on to the next page may be headed again.
                name, suffix = heading.group("name").strip(), heading.group("suffix")
                account = next((a for a in accounts if (a.name, a.suffix) == (name, suffix)), None)
                if account is None:
                    account = _Account(name, suffix, p)
                    accounts.append(account)
                reading, expect_summary = None, False
                continue
            if account is None:
                continue
            if _END_RE.match(line):
                account, ended = None, True
                continue
            if _SUMMARY_LABELS_RE.match(line):
                expect_summary = True
                continue
            if expect_summary:
                expect_summary = False
                values = [_money(v) for v in re.findall(r"-?\$\s*-?[\d,]+\.\d{2}-?", line)]
                if len(values) >= 4:
                    account.summary = values
                    continue
            if _TABLE_HEADER_RE.match(line) or _NOTE_RE.match(line):
                reading = None
                continue
            row = _ROW_RE.match(line)
            date = None
            if row and row.group("mon") in _MONTHS:
                try:
                    date = _date(row.group("mon"), row.group("day"), ending)
                except ValueError:
                    date = None
            if date:
                reading = {"date": date, "description": row.group("desc"), "printed": abs(_money(row.group("amount"))),
                           "balance": _money(row.group("balance")), "page": p + 1, "line": n + 1, "text": line}
                account.rows.append(reading)
            elif _DATED_RE.match(line):
                unread.append({"page": p + 1, "line": n + 1, "text": line})
                reading = None
            elif reading is not None and not _ENDS_WITH_AMOUNT_RE.search(line) and not _FOOTER_RE.search(line):
                reading["description"] += " " + line
            else:
                reading = None

    if not accounts:
        raise parser_common.ParserDiagnosticError(
            "no account heading ('<NAME> ACCOUNT ACCT# <suffix>') found",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND", stage="activity")

    transactions: list[dict] = []
    checks: list[dict] = []
    for account in accounts:
        account_type = _account_type(account.name)
        if account_type is None or account.summary is None:
            # Not a deposit account, or one whose summary didn't read: its
            # rows are reported, not guessed at.
            unread.extend({"page": r["page"], "line": r["line"], "text": r["text"]} for r in account.rows)
            continue
        _place_signs(account)
        label = f"{account.name} ACCT# {account.suffix}"
        number = common.last4_digits((member or "") + account.suffix)
        first = len(transactions)
        for row in account.rows:
            transactions.append({"date": row["date"], "description": row["description"], "amount": round(row["amount"], 2),
                                 "balance": row["balance"], "account": number, "accountType": account_type})
        indices = list(range(first, len(transactions)))
        beginning, deposits, withdrawals, closing = account.summary[:4]
        checks.append({"kind": "sum", "label": f"{label}: Deposits/Credits", "table": "cash_transactions",
                       "rows": [i for i in indices if transactions[i]["amount"] > 0], "expected": round(deposits, 2)})
        checks.append({"kind": "sum", "label": f"{label}: Withdrawals/Debits", "table": "cash_transactions",
                       "rows": [i for i in indices if transactions[i]["amount"] < 0], "expected": round(-abs(withdrawals), 2)})
        checks.append({"kind": "balance", "label": label, "table": "cash_transactions", "rows": indices,
                       "opening": round(beginning, 2), "closing": round(closing, 2)})

    # A dated line that ends in an amount anywhere outside the accounts is a
    # row in a part of the statement this parser doesn't know.
    seen = {(r["page"], r["line"]) for a in accounts for r in a.rows} | {(u["page"], u["line"]) for u in unread}
    for p, lines in enumerate(pages):
        for n, line in enumerate(lines):
            if (p + 1, n + 1) not in seen and _DATED_RE.match(line) and _ENDS_WITH_AMOUNT_RE.search(line):
                unread.append({"page": p + 1, "line": n + 1, "text": line})
    if unread:
        unread.sort(key=lambda u: (u["page"], u["line"]))
        checks.append({"kind": "unread", "label": "Statement", "lines": unread})

    return {
        "institution": INSTITUTION,
        "statementDate": ending.strftime("%Y-%m-%d"),
        "transactions": transactions,
        "checks": checks,
    }
