"""Chase checking and savings statement parser.

Format: the monthly statement JPMorgan Chase Bank, N.A. sends for a
customer's deposit accounts, every checking and savings account in one PDF.
Page 1 gives the period ("October 01, 2026 through October 31, 2026") and a
balance summary of every account; each account follows with its own summary
and its transaction detail:

    CHASE TOTAL CHECKING
    PAT EXAMPLE Account Number: 000000001234567
    CHECKING SUMMARY
    AMOUNT
    Beginning Balance $1,200.00
    Deposits and Additions 2,500.00
    Electronic Withdrawals -1,000.00
    Ending Balance $2,700.00
    TRANSACTION DETAIL
    DATE DESCRIPTION AMOUNT BALANCE
    Beginning Balance $1,200.00
    10/05 Payroll Deposit SAMPLE EMPLOYER 2,500.00 3,700.00
    10/09 10/08 Online Transfer To Sav ...4321 -1,000.00 2,700.00
    Transaction#: 1234567890
    Ending Balance $2,700.00

A row is its posting date, its description (an outgoing transfer's own
date first, dropped here), its amount signed as printed and the balance
after it; a line under it that is neither a row nor the end of the detail
continues its description. Rows are read only inside TRANSACTION DETAIL.

Chase's markers ("*start*summary", "*end*transaction detail") are printed
so small that the text can read one run into the line beside it:
"*end*summaryInterest Paid Year-to-Date", or a row whose date's first
digit falls among the marker's letters, its words run together or not
("*end*transact1iondetail 0/15 ATM Withdrawal ... -100.00 2,545.10"). A
line is read without the marker run into it, the digit put back before
its date. A dated line or one ending in a row's two figures that still
doesn't read as a row, or whose date then isn't the statement period's, is
reported as printed, marker and all; any other line a marker ran into ends
the row above it, never continuing its description.

The statement's own arithmetic is reported as checks (CONTRACT.md,
"Checks"), per account: its money in against the summary's positive lines
(Deposits and Additions), its money out against its negative ones (Checks
Paid, ATM & Debit Card Withdrawals, Electronic Withdrawals, Fees...),
Beginning Balance plus every row against Ending Balance, each row's printed
balance against the one before it, the transaction detail's own Beginning
and Ending Balance when they differ from the summary's, and every dated
line that was not read, a row dated outside the statement's period among
them, and every line in a detail that ends in an amount and a balance but
was not read as a row. An account whose summary heading or summary did not
read has its rows reported as not read, never joined to another account's.

An account's type is the summary's own heading (CHECKING SUMMARY, SAVINGS
SUMMARY, MONEY MARKET SUMMARY). Its number is printed after "Account
Number:" on its holder line, or, where that line holds none, it is the
balance summary's row whose beginning and ending balances are the account's
and whose number no other account printed; with neither, it is left for
the app to ask (CONTRACT.md).

Built from a scrambled sample of a real statement (README_addparser.md):
detect() rests on the bank's name ("JPMorgan Chase Bank") or its web site
("Chase.com") and the layout's own words ("CHECKING SUMMARY", "TRANSACTION
DETAIL", "DATE DESCRIPTION AMOUNT BALANCE"), each label matched with or
without the spaces between its words. A sample made under the name "Chase"
fakes "JPMorgan" but keeps the web site, which the card parser matches on
too. Chase's own markers in the text ("*start*transaction detail") are not
relied on.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
PARSER_REVISION = 3

INSTITUTION = "Chase"

DIAGNOSTIC_FIELDS = {
    "statementPeriod": "through",
    "beginningBalance": "Beginning Balance",
    "endingBalance": "Ending Balance",
    "accountNumber": "Account Number",
}

_MONEY = r"-?\$?-?[\d,]+\.\d{2}"
_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                        "september", "october", "november", "december"), 1)}
_MONTH = "(" + "|".join(_MONTHS) + ")"
# "October 01, 2026 through October 31, 2026", its months named so a word run
# into one ("periodOctober") doesn't hide it.
_PERIOD = _MONTH + r"\s*(\d{1,2}),\s*(\d{4})\s*through\s*" + _MONTH + r"\s*(\d{1,2}),\s*(\d{4})"
_PERIOD_RE = re.compile(_PERIOD, re.IGNORECASE)
_PERIOD_LINE_RE = re.compile(r"^" + _PERIOD + r"$", re.IGNORECASE)
_BANK_RE = re.compile(r"JPMorgan\s*Chase\s*Bank|\bChase\.com\b", re.IGNORECASE)
# An account's summary heading: "CHECKING SUMMARY", "SAVINGS SUMMARY". Not
# page 1's balance summary of every account.
_SUMMARY_HEAD_RE = re.compile(r"^(?P<kind>CHECKING|SAVINGS|MONEY\s*MARKET)\s*SUMMARY$", re.IGNORECASE)
_KINDS = {"CHECKING": "Checking", "SAVINGS": "Savings", "MONEYMARKET": "Money Market"}
_NUMBER_RE = re.compile(r"Account\s*Number\s*:\s*(?P<number>[\dXx*][\dXx* -]{2,}\d)\s*$", re.IGNORECASE)
# Beginning and Ending Balance, a summary that counts instances printing the
# total count before the amount ("Ending Balance 8 $2,045.10").
_BEGINNING_RE = re.compile(r"^Beginning\s*Balance\s+(?:\d+\s+)?(?P<amount>" + _MONEY + r")$", re.IGNORECASE)
_ENDING_RE = re.compile(r"^Ending\s*Balance\s+(?:\d+\s+)?(?P<amount>" + _MONEY + r")$", re.IGNORECASE)
# A summary line between Beginning and Ending Balance: its label, maybe a
# count of instances, its amount ("Electronic Withdrawals 4 -1,000.00").
_SUMMARY_LINE_RE = re.compile(r"^(?P<label>[A-Za-z].*?[A-Za-z)])\s+(?:\d+\s+)?(?P<amount>" + _MONEY + r")$")
# "TRANSACTION DETAIL", "(continued)" after it on the next page.
_DETAIL_HEAD_RE = re.compile(r"^TRANSACTION\s*DETAIL(?:\s*\(continued\))?$", re.IGNORECASE)
_COLUMNS_RE = re.compile(r"^DATE\s*DESCRIPTION\s*AMOUNT\s*BALANCE$", re.IGNORECASE)
_MONTH_DAY = r"\d{1,2}/\d{1,2}(?![/\d])"
_ROW_RE = re.compile(r"^(?P<date>" + _MONTH_DAY + r")\s+(?:" + _MONTH_DAY + r"\s+)?(?P<desc>\S.*?)\s+(?P<amount>" + _MONEY
                     + r")\s+(?P<balance>" + _MONEY + r")$")
_DATED_RE = re.compile(r"^" + _MONTH_DAY)
_ENDS_WITH_AMOUNT_RE = re.compile(r"\d\.\d{2}$")
# A row's two figures, its amount and the balance after it, at a line's end.
_ENDS_WITH_ROW_FIGURES_RE = re.compile(_MONEY + r"\s+" + _MONEY + r"$")
# A Chase marker run into the text after it on its line: the marker's
# lowercase words, with or without their spaces, then the line's own text
# from its first capital or its date ("*end*summaryInterest Paid",
# "*end*transact1iondetail 0/15 ATM Withdrawal"). A digit among the
# marker's letters is the first of that date's.
_MARKER_RUN_IN_RE = re.compile(r"^\*(?:start|end)\*(?P<marker>[a-z\d ]*?)\s*(?=[A-Z]|" + _MONTH_DAY + r"\s)")
_ONE_DIGIT_MONTH_RE = re.compile(r"^\d/")
# Page 1's balance summary, a row per account: its name, number, beginning
# and ending balance.
_BALANCE_ROW_RE = re.compile(r"^(?P<name>[A-Za-z].*?)\s+(?P<number>\d{4,})\s+(?P<begin>" + _MONEY + r")\s+(?P<end>"
                             + _MONEY + r")$")
# Never part of a row's description: Chase's markers, a page's furniture
# (and the period printed at its top, _PERIOD_LINE_RE).
_NOT_DESCRIPTION_RE = re.compile(r"^\*(?:start|end)\*|^Page\s*\d+\s*of\s*\d+$|^\(continued\)$", re.IGNORECASE)

_EPS = 0.005


def detect(head_text: str) -> tuple[bool, str]:
    lines = [line.strip() for line in head_text.splitlines()]
    if (_BANK_RE.search(head_text) and _PERIOD_RE.search(head_text)
            and any(_SUMMARY_HEAD_RE.match(line) for line in lines)
            and any(_DETAIL_HEAD_RE.match(line) for line in lines)
            and any(_COLUMNS_RE.match(line) for line in lines)):
        return True, "matched Chase checking and savings statement"
    return False, ("Chase deposit-statement markers (JPMorgan Chase Bank or Chase.com, CHECKING SUMMARY, "
                   "TRANSACTION DETAIL) not found")


def _unmarked(line: str) -> str:
    """line without a Chase marker run into it (_MARKER_RUN_IN_RE), the
    one digit the marker's letters took put back before the date that
    lost it. A line with no marker run into it is returned as it is."""
    m = _MARKER_RUN_IN_RE.match(line)
    if not m:
        return line
    rest = line[m.end():]
    digits = re.sub(r"\D", "", m.group("marker"))
    if len(digits) == 1 and _ONE_DIGIT_MONTH_RE.match(rest):
        rest = digits + rest
    return rest


def _money(raw: str) -> float:
    negative = raw.count("-") % 2 == 1
    value = float(re.sub(r"[^\d.]", "", raw))
    return -value if negative else value


def _period(text: str) -> tuple[datetime, datetime] | None:
    m = _PERIOD_RE.search(text)
    if not m:
        return None
    try:
        start = datetime(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        end = datetime(int(m.group(6)), _MONTHS[m.group(4).lower()], int(m.group(5)))
    except (KeyError, ValueError):
        return None
    return (start, end) if start <= end else None


def _date(md: str, start: datetime, end: datetime) -> datetime:
    """A month and day's date: in the end date's year, unless that puts it
    after the end date, in which case the year before (December on a
    statement ending in January). ValueError for a day that doesn't exist or
    one outside the statement's period."""
    month, day = (int(v) for v in md.split("/"))
    date = datetime(end.year, month, day)
    if date > end:
        date = datetime(end.year - 1, month, day)
    if date < start:
        raise ValueError(f"{md} is before the statement's start")
    return date


class _Account:
    def __init__(self, kind: str | None, number: str):
        # kind is None for the account of a transaction detail whose summary
        # heading did not read: its rows are reported, never read.
        self.kind, self.number = kind, number
        self.beginning: float | None = None
        self.ending: float | None = None
        self.summary_lines: list[float] = []
        self.detail_beginning: float | None = None
        self.detail_ending: float | None = None
        self.rows: list[dict] = []


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    combined = "\n".join(pages_text)
    period = _period(combined)
    if period is None:
        raise parser_common.ParserDiagnosticError(
            "no 'Month DD, YYYY through Month DD, YYYY' statement period found",
            code="PARSER_STATEMENT_DATE_INVALID", stage="metadata", missing_fields=("statementPeriod",))
    start, end = period

    printed = [[line.strip() for line in text.splitlines()] for text in pages_text]
    # Each line as it is read: without a marker run into it. A line not read
    # is reported as printed.
    pages = [[_unmarked(line) for line in lines] for lines in printed]
    balance_rows: list[tuple[str, float, float]] = []
    accounts: list[_Account] = []
    unread: list[dict] = []
    seen: set[tuple[int, int]] = set()
    account: _Account | None = None
    # Where the account's lines are: "summary", "detail" (after its column
    # header) or None.
    part = None
    # The number on the holder line over the next summary heading. Taken only
    # between accounts, never from a row's lines.
    number = ""
    for p, lines in enumerate(pages):
        reading = None  # the row a line under it continues
        for n, line in enumerate(lines):
            if not line:
                continue
            where = {"page": p + 1, "line": n + 1, "text": printed[p][n]}
            balance_row = _BALANCE_ROW_RE.match(line)
            if balance_row and part is None:
                balance_rows.append((balance_row.group("number"), _money(balance_row.group("begin")),
                                     _money(balance_row.group("end"))))
                continue
            numbered = _NUMBER_RE.search(line) if part is None else None
            if numbered:
                number = numbered.group("number")
                continue
            heading = _SUMMARY_HEAD_RE.match(line)
            if heading:
                kind = _KINDS[re.sub(r"\s+", "", heading.group("kind")).upper()]
                account = _Account(kind, number)
                accounts.append(account)
                part, number, reading = "summary", "", None
                continue
            if account is None:
                continue
            if part == "summary" and not _DETAIL_HEAD_RE.match(line):
                beginning, ending = _BEGINNING_RE.match(line), _ENDING_RE.match(line)
                if beginning:
                    account.beginning = _money(beginning.group("amount"))
                elif ending:
                    account.ending = _money(ending.group("amount"))
                    part = None
                else:
                    summary_line = _SUMMARY_LINE_RE.match(line)
                    if summary_line and account.beginning is not None:
                        account.summary_lines.append(_money(summary_line.group("amount")))
                continue
            if _DETAIL_HEAD_RE.match(line):
                if account.detail_ending is not None:
                    # A second detail under one summary: the next account's,
                    # under a summary heading that did not read. Its rows
                    # must not join this account's.
                    account = _Account(None, "")
                    accounts.append(account)
                part, reading, number = "detail", None, ""
                continue
            if part != "detail":
                continue
            if _COLUMNS_RE.match(line):
                reading = None
                continue
            beginning, ending = _BEGINNING_RE.match(line), _ENDING_RE.match(line)
            if beginning:
                account.detail_beginning, reading = _money(beginning.group("amount")), None
                continue
            if ending:
                account.detail_ending, part, reading, number = _money(ending.group("amount")), None, None, ""
                continue
            if _DATED_RE.match(line):
                seen.add((p + 1, n + 1))
                row = _ROW_RE.match(line)
                try:
                    date = _date(row.group("date"), start, end) if row else None
                except ValueError:
                    date = None
                if date is None:
                    unread.append(where)
                    reading = None
                    continue
                reading = {"date": date.strftime("%Y-%m-%d"), "description": row.group("desc"),
                           "amount": _money(row.group("amount")), "balance": _money(row.group("balance")), **where}
                account.rows.append(reading)
            elif _ENDS_WITH_ROW_FIGURES_RE.search(line):
                # A line ending in a row's amount and balance whose date did
                # not read (a marker run into it took more of the date than
                # one digit, say): reported, never passed over as the end of
                # the row above.
                seen.add((p + 1, n + 1))
                unread.append(where)
                reading = None
            elif (reading is not None and not _ENDS_WITH_AMOUNT_RE.search(line) and not _NOT_DESCRIPTION_RE.search(line)
                  and not _PERIOD_LINE_RE.match(line) and line == printed[p][n]):
                # A line a marker ran into ends the row, as the marker alone
                # does: what follows it is the statement's next block.
                reading["description"] += " " + line
            else:
                reading = None

    if not any(a.rows for a in accounts):
        raise parser_common.ParserDiagnosticError(
            "no row under a 'TRANSACTION DETAIL' header found",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND", stage="activity")

    transactions: list[dict] = []
    checks: list[dict] = []
    # A number one account's heading printed is never another's.
    used = {a.number for a in accounts if a.number}
    for position, account in enumerate(accounts, 1):
        if account.kind is None or account.beginning is None or account.ending is None:
            # A summary heading or summary that didn't read: the rows are
            # reported, not guessed at.
            unread.extend({k: r[k] for k in ("page", "line", "text")} for r in account.rows)
            continue
        number = account.number
        if not number:
            matches = {n for n, b, e in balance_rows
                       if n not in used and abs(b - account.beginning) < _EPS and abs(e - account.ending) < _EPS}
            number = matches.pop() if len(matches) == 1 else ""
            used.add(number)
        last4 = common.last4_digits(number) if number else ""
        first = len(transactions)
        for row in account.rows:
            transactions.append({"date": row["date"], "description": re.sub(r"\s+", " ", row["description"]).strip(),
                                 "amount": round(row["amount"], 2), "balance": row["balance"],
                                 "account": last4, "accountType": account.kind})
        indices = list(range(first, len(transactions)))
        # Two accounts without a number are told apart by their place.
        label = f"{account.kind} {last4}" if last4 else f"{account.kind} (account {position})"
        checks.append({"kind": "sum", "label": f"{label}: deposits and additions", "table": "cash_transactions",
                       "rows": [i for i in indices if transactions[i]["amount"] > 0],
                       "expected": round(sum(v for v in account.summary_lines if v > 0), 2)})
        checks.append({"kind": "sum", "label": f"{label}: withdrawals", "table": "cash_transactions",
                       "rows": [i for i in indices if transactions[i]["amount"] < 0],
                       "expected": round(sum(v for v in account.summary_lines if v < 0), 2)})
        checks.append({"kind": "balance", "label": label, "table": "cash_transactions", "rows": indices,
                       "opening": round(account.beginning, 2), "closing": round(account.ending, 2)})
        # Each row's printed balance is the one before it plus its amount: a
        # misread balance or amount shows, though the totals still hold.
        checks.append({"kind": "running", "label": label, "table": "cash_transactions", "rows": indices,
                       "opening": round(account.beginning, 2)})
        detail = (account.detail_beginning, account.detail_ending)
        if None not in detail and (abs(detail[0] - account.beginning) >= _EPS or abs(detail[1] - account.ending) >= _EPS):
            checks.append({"kind": "balance", "label": f"{label}: transaction detail", "table": "cash_transactions",
                           "rows": indices, "opening": round(detail[0], 2), "closing": round(detail[1], 2)})

    # A dated line that ends in an amount anywhere outside a transaction
    # detail, a marker run into it or not, is a row in a part of the
    # statement this parser doesn't know.
    for p, lines in enumerate(pages):
        for n, line in enumerate(lines):
            if (p + 1, n + 1) not in seen and _DATED_RE.match(line) and _ENDS_WITH_AMOUNT_RE.search(line):
                unread.append({"page": p + 1, "line": n + 1, "text": printed[p][n]})
    if unread:
        unread.sort(key=lambda u: (u["page"], u["line"]))
        checks.append({"kind": "unread", "label": "Statement", "lines": unread})

    return {
        "institution": INSTITUTION,
        "statementDate": end.strftime("%Y-%m-%d"),
        "transactions": transactions,
        "checks": checks,
    }
