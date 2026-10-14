"""Apple Card statement parser.

Format: the monthly statement Apple Card (issued by Goldman Sachs Bank
USA) offers as a PDF. Every page opens with the same header,

    Statement
    Apple Card Customer
    <holder>, <email> Sep 1 — Sep 30, 2029

which carries the statement period: a calendar month, with full years only
on its closing date. Page 1 is the summary (Total Balance, Minimum Payment,
Previous Total Balance); the activity follows in tables with full
MM/DD/YYYY dates:

    Payments
    Date Description Amount
    09/01/2029 ACH Deposit Internet transfer from account ending in 1234 -$183.20
    Total payments for this period -$183.20
    Transactions
    Date Description Daily Cash Amount
    09/05/2029 COFFEE SHOP 123 MAIN ST ANYTOWN 12345 CA USA 2% $0.13 $6.36
    Total Daily Cash this month $9.99
    Total charges, credits and returns $800.56

The statement prints no card or account number - the only number near the
activity is the paying bank account's, in the payment's description - so
every row carries an empty account and the app asks which account the
statement is for when it is imported. Daily Cash is not a row: it is paid
to Apple Cash, not to the card.

Amounts are printed in the card's own sign (charges positive, payments
and returns negative) and checked that way against the statement's own
figures: each table against its total, and the Previous Total Balance
plus every row against the Total Balance. They are then negated, with the
running balance derived from the Previous Total Balance, into this
codebase's sign convention (common.negate_amounts_and_balances).

Built from a scrambled sample of a real statement (README_addparser.md),
then confirmed by a clean import of a real one (13 Oct 2026): detect()
anchors only on words a scrambled sample keeps - the card's name, "Daily
Cash", "Minimum Payment" - and amounts are read by their shape, never
their value.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
PARSER_REVISION = 1

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MONTH = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"

# The header's period: "Sep 1 — Sep 30, 2029". The opening date may carry
# its own year when the period crosses one.
_PERIOD_RE = re.compile(
    _MONTH + r"\s+(\d{1,2})(?:,\s*(\d{4}))?\s*[—–-]\s*" + _MONTH + r"\s+(\d{1,2}),\s*(\d{4})"
)

_AMOUNT = r"(-?\$[\d,]+\.\d{2})"

# Page 1's summary. "Previous Total Balance" is the balance the Total
# Balance follows from; "Previous Monthly Balance" leaves out what is owed
# on installments, so it is only a fallback.
_PREVIOUS_TOTAL_RE = re.compile(r"^Previous Total Balance\s+" + _AMOUNT, re.MULTILINE)
_PREVIOUS_MONTHLY_RE = re.compile(r"^Previous Monthly Balance\s+" + _AMOUNT, re.MULTILINE)
_TOTAL_BALANCE_RE = re.compile(r"^Total Balance\s+" + _AMOUNT, re.MULTILINE)
_TOTAL_INTEREST_RE = re.compile(r"^Total interest for this month\s+" + _AMOUNT, re.MULTILINE)

# A table's column header. The line above it names the table ("Payments",
# "Transactions").
_TABLE_HEADER_RE = re.compile(r"^Date\s+Description\s+(?:Daily Cash\s+)?Amount$")

# The interest table prints no column header of its own.
_INTEREST_HEADING_RE = re.compile(r"^Interest Charged$")

# A table's own total: "Total payments for this period -$183.20",
# "Total charges, credits and returns $800.56", "Total interest for this
# month $0.00". A label's last word may be one a scrambled sample fakes. "Total Daily Cash this month" is Daily Cash, not
# money on the card, and ends the rows without being their total.
_TABLE_TOTAL_RE = re.compile(r"^Total\s+(?:payments|charges|interest)\b.*?\s" + _AMOUNT + r"$", re.IGNORECASE)
_ENDS_ROWS_RE = re.compile(r"^Total\b", re.IGNORECASE)

# A row: "MM/DD/YYYY <description> [<n>% <Daily Cash>] <amount>".
_ROW_RE = re.compile(
    r"^(\d{2})/(\d{2})/(\d{4})\s+(.+?)\s+(?:(-?\d+(?:\.\d+)?%)\s+" + _AMOUNT + r"\s+)?" + _AMOUNT + r"$"
)
# Anything else that starts with a date: a row this parser could not read.
_DATED_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")


def detect(head_text: str) -> tuple[bool, str]:
    low = head_text.lower()
    if "apple card" not in low:
        return False, "'Apple Card' not found"
    if "minimum payment" not in low:
        return False, "'Apple Card' found, but no 'Minimum Payment' (not a card statement)"
    if "daily cash" not in low and "card.apple.com" not in low:
        return False, "'Apple Card' found, but neither 'Daily Cash' nor 'card.apple.com'"
    if not _PERIOD_RE.search(head_text):
        return False, "'Apple Card' found, but no statement period ('Sep 1 — Sep 30, 2029')"
    return True, "matched Apple Card statement"


def _period(text: str) -> tuple[datetime | None, datetime | None]:
    """The statement's (opening, closing) dates from the page header."""
    m = _PERIOD_RE.search(text)
    if not m:
        return None, None
    om, od, oy, cm, cd, cy = m.groups()
    close_year = int(cy)
    open_month, close_month = _MONTHS[om.lower()[:3]], _MONTHS[cm.lower()[:3]]
    open_year = int(oy) if oy else (close_year - 1 if open_month > close_month else close_year)
    try:
        return datetime(open_year, open_month, int(od)), datetime(close_year, close_month, int(cd))
    except ValueError:
        return None, None


def _figure(regex: re.Pattern, text: str) -> float | None:
    m = regex.search(text)
    return common.parse_amount(m.group(1)) if m else None


class _Table:
    """One activity table: its name, the rows read from it, the statement's
    own total for it, and the lines in it that could not be read."""

    def __init__(self, label: str):
        self.label = label
        self.rows: list[dict] = []
        self.total: float | None = None
        self.unread: list[dict] = []


def _tables(pages_text: list[str]) -> tuple[list[_Table], list[dict]]:
    """The activity tables, and dated lines outside any table - rows under a
    heading this parser doesn't know, reported rather than dropped."""
    tables: list[_Table] = []
    stray: list[dict] = []
    current: _Table | None = None
    reading = False
    previous_line = ""

    for page_no, text in enumerate(pages_text, 1):
        for line_no, line in enumerate(text.split("\n"), 1):
            s = line.strip()
            if not s:
                continue

            if _TABLE_HEADER_RE.match(s):
                label = previous_line if _is_heading(previous_line) else ""
                # A table broken across a page reprints its column header
                # under the page header, or under its own heading again:
                # the same table goes on.
                if not (current is not None and reading and label in ("", current.label)):
                    current = _Table(label or "Transactions")
                    tables.append(current)
                reading = True
                previous_line = s
                continue
            if _INTEREST_HEADING_RE.match(s):
                current = _Table(s)
                tables.append(current)
                reading = True
                previous_line = s
                continue

            total = _TABLE_TOTAL_RE.match(s)
            if total and current is not None:
                current.total = common.parse_amount(total.group(1))
                reading = False
            elif _ENDS_ROWS_RE.match(s):
                reading = False

            m = _ROW_RE.match(s)
            if m and reading and current is not None:
                month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                current.rows.append({
                    "date": f"{year:04d}-{month:02d}-{day:02d}",
                    "description": re.sub(r"\s+", " ", m.group(4)).strip(),
                    # As printed: charges positive, payments and returns
                    # negative. Negated in parse().
                    "amount": common.parse_amount(m.group(7)),
                    "balance": None,
                })
            elif _DATED_RE.match(s):
                where = current.unread if (reading and current is not None) else stray
                where.append({"page": page_no, "line": line_no, "text": s})
            previous_line = s
    return tables, stray


def _is_heading(line: str) -> bool:
    """Whether a line can name a table: a short title, not page furniture
    (the page header's holder and period line, a page number)."""
    return bool(line) and len(line) <= 40 and not _PERIOD_RE.search(line) and not re.match(r"^Page\s", line)


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    combined = "\n".join(pages_text)
    _, closing = _period(combined)
    previous = _figure(_PREVIOUS_TOTAL_RE, combined)
    if previous is None:
        previous = _figure(_PREVIOUS_MONTHLY_RE, combined)
    total_balance = _figure(_TOTAL_BALANCE_RE, combined)
    interest = _figure(_TOTAL_INTEREST_RE, combined)

    tables, stray = _tables(pages_text)

    # Interest the statement charged but printed in no row of its own is
    # added, dated on the closing date - only when the statement's own
    # figures say it is missing: the rows fall short of the Total Balance by
    # exactly the month's interest.
    if interest and closing and previous is not None and total_balance is not None:
        read = round(previous + sum(r["amount"] for t in tables for r in t.rows), 2)
        if read != round(total_balance, 2) and round(read + interest, 2) == round(total_balance, 2):
            table = next((t for t in tables if t.label == "Interest Charged"), None)
            if table is None:
                table = _Table("Interest Charged")
                tables.append(table)
            table.rows.append({"date": closing.strftime("%Y-%m-%d"), "description": "Interest Charged",
                               "amount": interest, "balance": None})

    # Date order, statement order within a day; the running balance is
    # derived from the Previous Total Balance in that order.
    transactions = sorted((r for t in tables for r in t.rows), key=lambda r: r["date"])
    common.apply_running_balance(transactions, previous)
    common.negate_amounts_and_balances(transactions)
    for t in transactions:
        if t["balance"] == 0:
            t["balance"] = 0.0  # not -0.0, which negating a zero balance gives
    common.tag_account(transactions, "", "Credit Card")

    # The statement's own arithmetic, negated like the rows (statement_checks):
    # each table against its printed total, and Previous Total Balance plus
    # every row against the Total Balance.
    checks: list[dict] = []
    index = {id(r): i for i, r in enumerate(transactions)}
    for t in tables:
        if t.total is not None:
            checks.append({"kind": "sum", "label": t.label, "table": "cash_transactions",
                           "rows": [index[id(r)] for r in t.rows], "expected": -t.total})
        if t.unread:
            checks.append({"kind": "unread", "label": t.label, "lines": t.unread})
    if stray:
        checks.append({"kind": "unread", "label": "Transactions", "lines": stray})
    if previous is not None and total_balance is not None:
        checks.append({"kind": "balance", "label": "Total Balance", "table": "cash_transactions",
                       "rows": list(range(len(transactions))), "opening": -previous, "closing": -total_balance})

    return {
        "institution": "Apple Card",
        "statementDate": closing.strftime("%Y-%m-%d") if closing else "",
        "transactions": transactions,
        "checks": checks,
    }
