"""Technology Credit Union member statement parser.

Format: the monthly statement Tech CU sends its members, every savings and
checking account of a membership in one PDF. Page 1 opens with the member
number and the statement date; each account follows under its kind
("Savings", "Checking"), its own column header, and a line that names it
and gives its number:

    Member Number: 123456
    Statement Date: 09/30/2026
    Savings
    Date Transaction Description Amount Balance
    SHARE SAVINGS 1234567890123
    09/01 Starting Balance $1,529.17
    09/30 Deposit Dividend 0.150% 2.44 1,531.61
    Annual % Yield Earned Ending 09/30/2026 : 0.15%
    09/30 Ending Balance for SHARE SAVINGS $1,531.61
    Summary: 1 Deposit : $2.44 YTD Dividends Paid : $6.80

A row is its date (month and day), its description, its amount and the
balance after it; the lines under it, up to the next row, describe it
further. The amount's sign is the one its balance shows: the change from
the balance before it, the account's Starting Balance for the first row,
whatever sign is printed.

The statement's own arithmetic is reported as checks (CONTRACT.md,
"Checks"), per account: Starting Balance plus every row against the
Ending Balance, its deposits and its withdrawals against the totals its
Summary line gives, and every dated line that was not read. An account
this parser doesn't read (a loan, a card) has its dated lines reported as
not read, so the rest of the statement still imports.

Built from a scrambled sample of a real statement (README_addparser.md),
which kept no word naming the credit union: detect() rests on the layout -
its words ("Member Number:", "Starting Balance", "Ending Balance for",
"Summary:") and an account named under the column header by a number of
ten digits or more - and takes the techcu domain when the statement prints
it. Another credit union printing the same template would be read as this
one.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1

INSTITUTION = "Technology Credit Union"

DIAGNOSTIC_FIELDS = {
    "statementDate": "Statement Date",
    "startingBalance": "Starting Balance",
    "endingBalance": "Ending Balance for",
}

_MONEY = r"-?\$?-?[\d,]+\.\d{2}-?"
_STATEMENT_DATE_RE = re.compile(r"Statement Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE)
_TABLE_HEADER_RE = re.compile(r"^Date\s+Transaction Description\s+Amount\s+Balance$", re.IGNORECASE)
# The line under the column header naming the account: "SHARE SAVINGS 1234567890123".
_ACCOUNT_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9 &'/+.-]*?)\s+(?P<number>\d{4,})$")
_STARTING_RE = re.compile(r"^(?P<date>\d{2}/\d{2})\s+Starting Balance\s+(?P<amount>" + _MONEY + r")$", re.IGNORECASE)
_ENDING_RE = re.compile(r"^(?P<date>\d{2}/\d{2})\s+Ending Balance for\b.*?\s(?P<amount>" + _MONEY + r")$", re.IGNORECASE)
_ROW_RE = re.compile(r"^(?P<date>\d{2}/\d{2})\s+(?P<desc>.+?)\s+(?P<amount>" + _MONEY + r")\s+(?P<balance>" + _MONEY + r")$")
_SUMMARY_RE = re.compile(r"^Summary:", re.IGNORECASE)
_SUMMARY_DEPOSITS_RE = re.compile(r"\d+\s+Deposits?\s*:\s*(" + _MONEY + r")", re.IGNORECASE)
_SUMMARY_WITHDRAWALS_RE = re.compile(r"\d+\s+Withdrawals?\s*:\s*(" + _MONEY + r")", re.IGNORECASE)
_DATED_RE = re.compile(r"^\d{2}/\d{2}\b")
_ENDS_WITH_AMOUNT_RE = re.compile(r"\d\.\d{2}-?$")
_NOTE_RE = re.compile(r"^(?:Annual % Yield Earned\b|Member Number:|Statement Date:|Page:)", re.IGNORECASE)

_EPS = 0.005

# An account that is a debt, whatever else its name says ("SHARE SECURED
# LOAN" is a loan): its rows are reported, not read as a deposit account's.
_DEBT_RE = re.compile(r"\b(?:LOAN|CREDIT|VISA|MASTERCARD|MORTGAGE|HELOC|LINE)\b")
# A page's footer, never part of a row's description.
_FOOTER_RE = re.compile(r"\b(?:continued|federally insured|NCUA|equal housing)\b|^Page\s*:?\s*\d+\s+of\s+\d+$",
                        re.IGNORECASE)
# The column header and, under it, an account's name and number: the layout
# detect() knows this statement by.
_ACCOUNT_UNDER_HEADER_RE = re.compile(
    r"^Date\s+Transaction Description\s+Amount\s+Balance\s*\n\s*[A-Za-z][A-Za-z0-9 &'/+.-]*?\s+\d{10,}\s*$",
    re.IGNORECASE | re.MULTILINE)


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    layout = all(marker in lower for marker in (
        "member number:", "statement date:", "starting balance", "ending balance for", "summary:")) and bool(
        _ACCOUNT_UNDER_HEADER_RE.search(head_text))
    named = "techcu" in lower and "starting balance" in lower and "ending balance for" in lower
    if layout or named:
        return True, "matched Technology Credit Union member statement"
    return False, "Technology Credit Union markers (Member Number:, Starting Balance, Ending Balance for) not found"


def _money(raw: str) -> float:
    text = raw.strip()
    negative = text.startswith("-") or text.endswith("-") or "$-" in text
    value = float(re.sub(r"[^\d.]", "", text))
    return -value if negative else value


def _account_type(name: str) -> str | None:
    """The account type an account's name gives, or None for one this
    parser doesn't read (a loan, a card)."""
    upper = name.upper()
    if _DEBT_RE.search(upper):
        return None
    if "CHECKING" in upper:
        return "Checking"
    if any(word in upper for word in ("SAVINGS", "SHARE", "MONEY MARKET", "CERTIFICATE", "CLUB")):
        return "Savings"
    return None


class _Account:
    def __init__(self, name: str, number: str):
        self.name, self.number = name, number
        self.starting: float | None = None
        self.ending: float | None = None
        self.deposits: float | None = None
        self.withdrawals: float | None = None
        self.rows: list[dict] = []


def _date(md: str, statement: datetime) -> str:
    month, day = (int(v) for v in md.split("/"))
    # A statement dated in January can carry December's last days.
    year = statement.year if month <= statement.month else statement.year - 1
    return datetime(year, month, day).strftime("%Y-%m-%d")


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    combined = "\n".join(pages_text)
    m = _STATEMENT_DATE_RE.search(combined)
    statement = None
    if m:
        try:
            statement = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            statement = None
    if statement is None:
        raise parser_common.ParserDiagnosticError(
            "no 'Statement Date: MM/DD/YYYY' line found",
            code="PARSER_STATEMENT_DATE_INVALID", stage="metadata", missing_fields=("statementDate",))

    pages = [[line.strip() for line in text.splitlines()] for text in pages_text]
    accounts: list[_Account] = []
    unread: list[dict] = []
    account: _Account | None = None
    reading: dict | None = None  # the row whose description lines follow
    expect_account = False
    seen: set[tuple[int, int]] = set()
    for p, lines in enumerate(pages):
        reading = None
        for n, line in enumerate(lines):
            if not line:
                continue
            if _TABLE_HEADER_RE.match(line):
                expect_account, reading = True, None
                continue
            if expect_account:
                expect_account = False
                named = _ACCOUNT_RE.match(line)
                if named:
                    # An account carried on to the next page is named again
                    # under the header there.
                    name, number = named.group("name").strip(), named.group("number")
                    account = next((a for a in accounts if (a.name, a.number) == (name, number)), None)
                    if account is None:
                        account = _Account(name, number)
                        accounts.append(account)
                    continue
            if account is None:
                continue
            starting = _STARTING_RE.match(line)
            if starting:
                account.starting = _money(starting.group("amount"))
                seen.add((p + 1, n + 1))
                reading = None
                continue
            ending = _ENDING_RE.match(line)
            if ending:
                account.ending = _money(ending.group("amount"))
                seen.add((p + 1, n + 1))
                reading = None
                continue
            if _SUMMARY_RE.match(line):
                # A Summary line names only the kinds the month had ("1
                # Deposit : $2.44"): a kind it doesn't name had none, or is
                # counted under a name this parser doesn't know - so it is
                # checked only when named, the balance check holding either way.
                d, w = _SUMMARY_DEPOSITS_RE.search(line), _SUMMARY_WITHDRAWALS_RE.search(line)
                account.deposits = _money(d.group(1)) if d else None
                account.withdrawals = abs(_money(w.group(1))) if w else None
                account, reading = None, None
                continue
            if _NOTE_RE.match(line):
                reading = None
                continue
            row = _ROW_RE.match(line)
            date = None
            if row:
                try:
                    date = _date(row.group("date"), statement)
                except ValueError:
                    date = None
            if date:
                reading = {"date": date, "description": row.group("desc"), "printed": _money(row.group("amount")),
                           "balance": _money(row.group("balance")), "page": p + 1, "line": n + 1, "text": line}
                account.rows.append(reading)
                seen.add((p + 1, n + 1))
            elif _DATED_RE.match(line):
                unread.append({"page": p + 1, "line": n + 1, "text": line})
                seen.add((p + 1, n + 1))
                reading = None
            elif reading is not None and not _ENDS_WITH_AMOUNT_RE.search(line) and not _FOOTER_RE.search(line):
                reading["description"] += " " + line
            else:
                reading = None

    if not accounts:
        raise parser_common.ParserDiagnosticError(
            "no account under a 'Date Transaction Description Amount Balance' header found",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND", stage="activity")

    transactions: list[dict] = []
    checks: list[dict] = []
    for account in accounts:
        account_type = _account_type(account.name)
        if account_type is None or account.starting is None or account.ending is None:
            # Not a deposit account, or one whose balances didn't read: its
            # rows are reported, not guessed at.
            unread.extend({"page": r["page"], "line": r["line"], "text": r["text"]} for r in account.rows)
            continue
        number = common.last4_digits(account.number)
        first = len(transactions)
        previous = account.starting
        for row in account.rows:
            # The sign the balance shows; as printed when it shows none.
            change = row["balance"] - previous
            amount = abs(row["printed"]) if abs(change - abs(row["printed"])) < _EPS else (
                -abs(row["printed"]) if abs(change + abs(row["printed"])) < _EPS else row["printed"])
            previous = row["balance"]
            transactions.append({"date": row["date"], "description": row["description"], "amount": round(amount, 2),
                                 "balance": row["balance"], "account": number, "accountType": account_type})
        indices = list(range(first, len(transactions)))
        label = account.name
        checks.append({"kind": "balance", "label": label, "table": "cash_transactions", "rows": indices,
                       "opening": round(account.starting, 2), "closing": round(account.ending, 2)})
        if account.deposits is not None:
            checks.append({"kind": "sum", "label": f"{label}: deposits", "table": "cash_transactions",
                           "rows": [i for i in indices if transactions[i]["amount"] > 0],
                           "expected": round(account.deposits, 2)})
        if account.withdrawals is not None:
            checks.append({"kind": "sum", "label": f"{label}: withdrawals", "table": "cash_transactions",
                           "rows": [i for i in indices if transactions[i]["amount"] < 0],
                           "expected": round(-account.withdrawals, 2)})

    # A dated line that ends in an amount anywhere this parser didn't read.
    for p, lines in enumerate(pages):
        for n, line in enumerate(lines):
            if (p + 1, n + 1) not in seen and _DATED_RE.match(line) and _ENDS_WITH_AMOUNT_RE.search(line):
                unread.append({"page": p + 1, "line": n + 1, "text": line})
    if unread:
        unread.sort(key=lambda u: (u["page"], u["line"]))
        checks.append({"kind": "unread", "label": "Statement", "lines": unread})

    return {
        "institution": INSTITUTION,
        "statementDate": statement.strftime("%Y-%m-%d"),
        "transactions": transactions,
        "checks": checks,
    }
