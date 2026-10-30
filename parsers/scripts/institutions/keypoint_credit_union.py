"""KeyPoint Credit Union statement of account parser.

Format: the monthly "Statement of Account" KeyPoint sends its members, every
share and checking account of a membership in one PDF. Page 1 gives the
period ("Start Date: 12/01/2026", "End Date: 12/31/2026"); each account
follows under a heading that names it and its number, a summary printed as
a row of labels over a row of figures, and its own column header:

    FREE CHECKING Account No. 12345678
    Beginning Dividend Service Ending
    Balance + Deposits + Paid - Withdrawals - Charges = Balance
    $1,200.00 $2,500.00 $0.00 $1,946.30 $5.00 $1,748.70
    Post Date Transaction Description Withdrawal Deposit Balance
    12/01 Beginning Balance 1,200.00
    12/02 Check 1001 150.00 1,050.00

A row is its date (month and day), its description, one amount and the
balance after it. Whether the amount was printed under Withdrawal or under
Deposit is lost in the text, so it is recovered from the balances: each
row's balance is the one before it plus or minus its amount, the first
row's the account's Beginning Balance. A line with a balance and no amount
that leaves the balance where it was (the account's opening line) moves no
money and is not a row; one that moves it is reported as not read.

The statement's own arithmetic is reported as checks (CONTRACT.md,
"Checks"), per account: its deposits against Deposits plus Dividend Paid,
its withdrawals against Withdrawals plus Service Charges, Beginning Balance
plus every row against Ending Balance, and every dated line that was not
read, a row dated outside the statement's period among them. An account
this parser doesn't read (a loan, a card, one whose heading did not read)
has its dated lines reported as not read, so the rest of the statement
still imports.

An account's type is read from its name ("CHECKING", "SAVINGS", "MONEY
MARKET", a share draft); a name that says none of these is passed on as
printed, which the app reports as unclassified rather than guessed at
(common.classify_account_type).

Built from a scrambled sample of a real statement (orby-core's
README/addparser.md). detect() rests on the layout's own words - "Statement
of Account", the summary's labels and the column header - and on KeyPoint's
name or its web address. A second sample, a trust's statement, printed only
the address: "kpcu.com" in its page header and in an email address. The
first sample's text ran some labels' words together ("StartDate:",
"AccountNo.", "PostDate TransactionDescription"), as the statement's own
text layer may (the scrambler draws a word's boundaries where the
original's text had them), so every label is matched with or without the
spaces between its words.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
PARSER_REVISION = 2

INSTITUTION = "KeyPoint Credit Union"
# KeyPoint's web address, which can be all a statement prints of its name.
# Counted outside the rows only, since another credit union's statement can
# have a member paying KeyPoint; the name counts anywhere, as it did when the
# parser was verified.
_WEB_ADDRESS = "kpcu.com"

DIAGNOSTIC_FIELDS = {
    "endDate": "End Date",
    "accountNumber": "Account No.",
    "beginningBalance": "Beginning",
}

_MONEY = r"-?\$?\s*-?[\d,]+\.\d{2}-?"
_START_DATE_RE = re.compile(r"Start\s*Date\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE)
_END_DATE_RE = re.compile(r"End\s*Date\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE)
# A month and day starting a line, not a full date ("12/01/2026", the period
# printed at a page's top).
_MONTH_DAY = r"\d{1,2}/\d{1,2}(?![/\d])"
# "FREE CHECKING Account No. 12345678": the name can be empty, the number
# masked but for its last digits. Never a row's line ("12/10 Transfer to
# Account No. 0001"), and followed by the account's summary or column
# header (see parse()).
_HEADING_RE = re.compile(r"^(?!" + _MONTH_DAY + r")(?P<name>.*?)\s*Account\s*No\.?\s*:?\s*(?P<number>[X*\d-]*\d{3,})$",
                         re.IGNORECASE)
_SUMMARY_HEAD_RE = re.compile(r"^Beginning\s*Dividend\s*Service\s*Ending$", re.IGNORECASE)
_SUMMARY_LABELS_RE = re.compile(
    r"^Balance\s*\+\s*Deposits\s*\+\s*Paid\s*-\s*Withdrawals\s*-\s*Charges\s*=\s*Balance$", re.IGNORECASE)
_SUMMARY_FIGURE_RE = re.compile(r"-?\$\s*-?[\d,]+\.\d{2}-?")
_TABLE_HEADER_RE = re.compile(
    r"^Post\s*Date\s*Transaction\s*Description\s*Withdrawal\s*Deposit\s*Balance$", re.IGNORECASE)
_ROW_RE = re.compile(r"^(?P<date>" + _MONTH_DAY + r")\s+(?P<desc>\S.*?)\s+(?P<amount>" + _MONEY
                     + r")\s+(?P<balance>" + _MONEY + r")$")
_BALANCE_LINE_RE = re.compile(r"^(?P<date>" + _MONTH_DAY + r")\s+(?P<desc>\S.*?)\s+(?P<balance>" + _MONEY + r")$")
# A row's line, read or not: one whose date runs into its text
# ("12/02Check") is reported, never passed over.
_DATED_RE = re.compile(r"^" + _MONTH_DAY)
_ENDS_WITH_AMOUNT_RE = re.compile(r"\d\.\d{2}-?$")

# Credit union names for a share account that common.classify_account_type
# doesn't know: a share draft is a checking account, a share a savings one.
_SHARE_DRAFT_RE = re.compile(r"\bSHARE\s*DRAFT\b", re.IGNORECASE)
_SHARE_RE = re.compile(r"\bSHARES?\b|\bCLUB\b|\bCERTIFICATE\b", re.IGNORECASE)
_DEBT_TYPES = {"Credit Card", "Mortgage", "Loan"}

_EPS = 0.005


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    lines = [line.strip() for line in head_text.splitlines()]
    layout = (re.search(r"statement\s*of\s*account", lower)
              and any(_SUMMARY_LABELS_RE.match(line) for line in lines)
              and any(_TABLE_HEADER_RE.match(line) for line in lines))
    named = "keypoint" in lower or any(_WEB_ADDRESS in line.lower() for line in lines if not _DATED_RE.match(line))
    if layout and named:
        return True, "matched KeyPoint Credit Union statement of account"
    return False, ("KeyPoint Credit Union markers (KeyPoint or kpcu.com, Statement of Account, Post Date ... Balance)"
                   " not found")


def _money(raw: str) -> float:
    text = raw.replace(" ", "")
    negative = text.startswith("-") or text.endswith("-") or "$-" in text
    value = float(re.sub(r"[^\d.]", "", text))
    return -value if negative else value


def _period_date(pattern: re.Pattern, text: str) -> datetime | None:
    m = pattern.search(text)
    try:
        return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def _date(md: str, start: datetime | None, end: datetime) -> datetime:
    """A month and day's date: in the end date's year, unless that puts it
    after the end date, in which case the year before (December on a
    statement ending in January). ValueError for a day that doesn't exist or
    one outside the statement's period."""
    month, day = (int(v) for v in md.split("/"))
    date = datetime(end.year, month, day)
    if date > end:
        date = datetime(end.year - 1, month, day)
    if start is not None and date < start:
        raise ValueError(f"{md} is before the statement's start")
    return date


def _account_type(name: str) -> str:
    """The account type the name gives; the name as printed when it gives
    none."""
    if _SHARE_DRAFT_RE.search(name):
        return "Checking"
    kind = common.classify_account_type(name)
    if kind:
        return kind
    if _SHARE_RE.search(name):
        return "Savings"
    return name


class _Account:
    def __init__(self, name: str | None, number: str):
        # name is None for an account whose heading did not read: its lines
        # are reported, never read.
        self.name, self.number = name, number
        self.summary: list[float] | None = None
        # Its rows and balance lines, in statement order.
        self.lines: list[dict] = []


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    combined = "\n".join(pages_text)
    end = _period_date(_END_DATE_RE, combined)
    if end is None:
        raise parser_common.ParserDiagnosticError(
            "no 'End Date: MM/DD/YYYY' line found",
            code="PARSER_STATEMENT_DATE_INVALID", stage="metadata", missing_fields=("endDate",))
    start = _period_date(_START_DATE_RE, combined)
    if start is not None and start > end:
        start = None

    pages = [[line.strip() for line in text.splitlines()] for text in pages_text]
    # Every line, in order across pages, so a heading can be told by what
    # follows it even over a page break.
    flat = [(p, n, line) for p, lines in enumerate(pages) for n, line in enumerate(lines) if line]
    accounts: list[_Account] = []
    unread: list[dict] = []
    seen: set[tuple[int, int]] = set()
    account: _Account | None = None
    reading = expect_figures = False
    for i, (p, n, line) in enumerate(flat):
        where = {"page": p + 1, "line": n + 1, "text": line}
        heading = _HEADING_RE.match(line)
        if heading:
            name, number = heading.group("name").strip(), heading.group("number")
            known = next((a for a in accounts if (a.name, a.number) == (name, number)), None)
            following = [x for _, _, x in flat[i + 1:i + 4]]
            # A heading is followed by its summary (a share account's
            # dividend rate line coming first); an account carried on to the
            # next page can be headed again over its column header alone. A
            # sentence that ends in an account number is neither.
            if any(_SUMMARY_HEAD_RE.match(x) or _SUMMARY_LABELS_RE.match(x) for x in following):
                account = known or _Account(name, number)
            elif known and any(_TABLE_HEADER_RE.match(x) for x in following):
                account = known
            else:
                heading = None
            if heading:
                if account not in accounts:
                    accounts.append(account)
                reading = expect_figures = False
                continue
        if account is None:
            continue
        if _SUMMARY_LABELS_RE.match(line):
            if account.summary is not None:
                # A second summary under one heading: the next account's,
                # under a heading that did not read. Its rows must not join
                # this account's.
                account = _Account(None, "")
                accounts.append(account)
                reading = False
            expect_figures = True
            continue
        if expect_figures:
            expect_figures = False
            figures = _SUMMARY_FIGURE_RE.findall(line)
            if len(figures) == 6:
                account.summary = [_money(f) for f in figures]
                continue
        if _TABLE_HEADER_RE.match(line):
            reading = True
            continue
        if not reading or not _DATED_RE.match(line):
            continue
        seen.add((p + 1, n + 1))
        row = _ROW_RE.match(line)
        balance_line = None if row else _BALANCE_LINE_RE.match(line)
        try:
            date = _date(row.group("date"), start, end) if row else None
        except ValueError:
            date = None
        if date:
            account.lines.append({"kind": "row", "date": date.strftime("%Y-%m-%d"),
                                  "description": re.sub(r"\s+", " ", row.group("desc")),
                                  "printed": _money(row.group("amount")), "balance": _money(row.group("balance")),
                                  **where})
        elif row:
            # Dated outside the period: reported, its balance kept for the
            # rows after it.
            account.lines.append({"kind": "unread", "balance": _money(row.group("balance")), **where})
        elif balance_line:
            # Its date is not a row's: an opening line can carry the day
            # before the period.
            account.lines.append({"kind": "balance", "balance": _money(balance_line.group("balance")), **where})
        else:
            unread.append(where)

    if not any(a.lines for a in accounts):
        raise parser_common.ParserDiagnosticError(
            "no account under a 'Post Date Transaction Description Withdrawal Deposit Balance' header found",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND", stage="activity")

    transactions: list[dict] = []
    checks: list[dict] = []
    for account in accounts:
        account_type = None if account.name is None else _account_type(account.name)
        if account_type is None or account_type in _DEBT_TYPES or account.summary is None:
            # A heading that did not read, not a deposit account, or a
            # summary that did not read: its lines are reported, not guessed
            # at.
            unread.extend({k: line[k] for k in ("page", "line", "text")} for line in account.lines)
            continue
        beginning, deposits, dividends, withdrawals, charges, ending = account.summary
        number = common.last4_digits(account.number)
        first = len(transactions)
        previous = beginning
        for line in account.lines:
            if line["kind"] != "row":
                # A balance line that moves the balance is a row whose amount
                # did not read: reported, like a row dated outside the
                # period. The rows after either go on from its balance.
                if line["kind"] == "unread" or abs(line["balance"] - previous) >= _EPS:
                    unread.append({k: line[k] for k in ("page", "line", "text")})
                previous = line["balance"]
                continue
            # The sign the balance shows; as printed when it shows none.
            change = line["balance"] - previous
            printed = abs(line["printed"])
            amount = printed if abs(change - printed) < _EPS else -printed if abs(change + printed) < _EPS else line["printed"]
            previous = line["balance"]
            transactions.append({"date": line["date"], "description": line["description"], "amount": round(amount, 2),
                                 "balance": line["balance"], "account": number, "accountType": account_type})
        indices = list(range(first, len(transactions)))
        label = f"{account.name} Account No. {number}".strip()
        checks.append({"kind": "sum", "label": f"{label}: deposits and dividends", "table": "cash_transactions",
                       "rows": [i for i in indices if transactions[i]["amount"] > 0],
                       "expected": round(deposits + dividends, 2)})
        checks.append({"kind": "sum", "label": f"{label}: withdrawals and service charges", "table": "cash_transactions",
                       "rows": [i for i in indices if transactions[i]["amount"] < 0],
                       "expected": round(-(abs(withdrawals) + abs(charges)), 2)})
        checks.append({"kind": "balance", "label": label, "table": "cash_transactions", "rows": indices,
                       "opening": round(beginning, 2), "closing": round(ending, 2)})

    # A dated line that ends in an amount anywhere outside an account's
    # table is a row in a part of the statement this parser doesn't know.
    for p, lines in enumerate(pages):
        for n, line in enumerate(lines):
            if (p + 1, n + 1) not in seen and _DATED_RE.match(line) and _ENDS_WITH_AMOUNT_RE.search(line):
                unread.append({"page": p + 1, "line": n + 1, "text": line})
    if unread:
        unread.sort(key=lambda u: (u["page"], u["line"]))
        checks.append({"kind": "unread", "label": "Statement", "lines": unread})

    return {
        "institution": INSTITUTION,
        "statementDate": end.strftime("%Y-%m-%d"),
        "transactions": transactions,
        "checks": checks,
    }
