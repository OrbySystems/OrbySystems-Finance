"""Chase UK credit card statement parser.

Format: the monthly PDF statement of a Chase credit card in the United
Kingdom, in pounds. Page 1 says "Your credit card statement" and prints:

    Statement date: 03 Oct 2026            Available credit: £4,157.83
    Statement period: 03 Sep 2026 - 02 Oct 2026   Credit limit: £5,000.00

The transactions start on page 2, under a summary of the period:

    Opening balance Money out Money in Interest & fees Closing balance
    £1,250.00 + £842.17 - £1,250.00 + £0.00 = £842.17
    Date Transaction details Amount
    04 Sep 2026 Tesco Stores
    £41.30
    Purchase
    13 Sep 2026 Amazon.co.uk
    +£18.00
    Refund | EUR 20.79 | FX rate £1 = EUR 1.1550

Each transaction takes three lines or more: its date and the merchant, the
amount on a line of its own (money in marked "+", money out unmarked), then
what it was ("Purchase", "Refund", a repayment), with the foreign amount
and rate when it was in another currency. Pages after the first repeat the
statement date and period above the "Date Transaction details Amount"
header. The table ends with a "Closing balance" line on the last day.

The statement prints no card number in its text, so the account is left
for the user to name when the file is imported. Amounts are read in the
statement's own sign (money out raises the balance owed), checked, then
negated to this codebase's convention (CONTRACT.md, "Amount sign
convention"), in pounds: every row carries currency_code when the app
accepts it. The statement's own arithmetic is reported as checks: opening
balance plus every row is the closing balance; the rows marked "+" add up
to Money in; the others to Money out plus Interest & fees; and every line
that starts with a date like a transaction but was not read is listed. A
balance in credit printed without its sign takes the one the summary's own
equation gives it. A statement without the summary is refused: no check
would hold its rows to anything.

Built from a scrambled sample of a real statement (README_addparser.md):
detect() is anchored on words the scrambler keeps.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1

INSTITUTION = "Chase UK"

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_DATE = r"\d{1,2} " + _MONTH + r" \d{4}"
_POUNDS = r"\d{1,3}(?:,\d{3})*\.\d{2}"
# The minus between the summary's figures may print as "-", "–", "−" or a
# glyph the text layer can't name.
_DASH = r"\s*[-–—−?]?\s*"

_STATEMENT_DATE_RE = re.compile(r"Statement date:\s*(" + _DATE + r")")
_PERIOD_RE = re.compile(r"Statement period:\s*(" + _DATE + r")" + _DASH + r"(" + _DATE + r")")
_SUMMARY_HEADER_RE = re.compile(
    r"^Opening balance\s+Money out\s+Money in\s+Interest (?:&|and) fees\s+Closing balance$", re.I)
# A summary figure, a balance in credit with its minus against it ("-£26.70",
# "£-26.70") or CR after it. A minus with a space after it is the
# operator between two figures.
_SUMMARY_FIGURE_RE = re.compile(r"([-–−])?£\s?([-–−])?(" + _POUNDS + r")(\s?CR\b)?")
_TABLE_HEADER_RE = re.compile(r"^Date\s+Transaction details\s+Amount$", re.I)
# A transaction's first line: "04 Sep 2026 Tesco Stores".
_ROW_RE = re.compile(r"^(" + _DATE + r")\s+(.+)$")
# Its amount, on a line of its own: "£41.30", "+£18.00"; money in is the
# "+" alone (a minus, before or after the "£", is a balance in credit on the
# Closing balance line, whose figure the summary gives).
_AMOUNT_RE = re.compile(r"^([+\-–−])?\s?£\s?[-–−]?(" + _POUNDS + r")$")
# The end of a merchant's name wrapped onto a second line, run into the
# amount below it: "London WC2 £57.12".
_WRAPPED_AMOUNT_RE = re.compile(r"^(.*\S)\s+([+\-–−])?£\s?[-–−]?(" + _POUNDS + r")$")
_PAGE_FOOT_RE = re.compile(r"^Page \d+ of \d+$", re.I)
_BALANCE_LINE_RE = re.compile(r"^(Opening|Closing) balance$", re.I)


def _currency_accepted() -> bool:
    """Whether the app running this accepts currency_code on a row: from
    the release after 1.0.2 on (orby-core docs/currency-on-cash-rows.md)."""
    return hasattr(parser_common, "normalize_currency_codes")


def detect(head_text: str) -> tuple[bool, str]:
    missing = [name for name, found in (
        ("Chase", re.search(r"\bChase\b", head_text)),
        ("Your credit card statement", re.search(r"Your credit card statement", head_text, re.I)),
        ("Statement period", _PERIOD_RE.search(head_text)),
        ("Opening balance Money out Money in Interest & fees Closing balance",
         any(_SUMMARY_HEADER_RE.match(re.sub(r"\s+", " ", line).strip()) for line in head_text.split("\n"))),
        ("£ amounts", "£" in head_text),
    ) if not found]
    if missing:
        return False, "Chase UK credit card marker(s) not found: " + ", ".join(missing)
    return True, "matched Chase UK credit card statement (Chase, Your credit card statement, Statement period, summary, £)"


def _iso(raw: str) -> str:
    """"03 Oct 2026" (or "03 October 2026") as 2026-10-03; ValueError if it is no day."""
    day, month, year = raw.split()
    return datetime.strptime(f"{day} {month[:3]} {year}", "%d %b %Y").strftime("%Y-%m-%d")


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def _summary(pages: list[list[str]]):
    """The period's summary: ((opening, money out, money in, interest &
    fees, closing), None), or (None, the line below its header) when that
    line doesn't hold its five figures. A balance in credit is negative.
    A balance printed without its sign takes the sign that makes the
    statement's own equation hold, opening + out - in + fees = closing.
    ParserDiagnosticError when there is no summary at all."""
    for p, lines in enumerate(pages, 1):
        for n, s in enumerate(lines, 1):
            if not _SUMMARY_HEADER_RE.match(s):
                continue
            below = lines[n] if n < len(lines) else ""
            figures = [-common.parse_amount(f) if (before or after or cr) else common.parse_amount(f)
                       for before, after, f, cr in _SUMMARY_FIGURE_RE.findall(below)]
            if len(figures) != 5:
                return None, {"page": p, "line": n + 1, "text": below}
            opening, out, money_in, fees, closing = figures
            holds = [(o, c) for o in (opening, -opening) for c in (closing, -closing)
                     if abs(o + out - money_in + fees - c) < 0.005]
            if holds and (opening, closing) not in holds and len(set(holds)) == 1:
                opening, closing = holds[0]
            return (opening, out, money_in, fees, closing), None
    raise parser_common.ParserDiagnosticError(
        "no 'Opening balance Money out Money in Interest & fees Closing balance' summary found",
        code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("openingBalance", "closingBalance"))


class _Row:
    def __init__(self, page: int, line: int, text: str, day: str, details: str):
        self.page, self.line, self.text = page, line, text
        self.day, self.details = day, [details]
        self.amount = None  # in the statement's own sign
        self.money_in = False
        self.kind: list[str] = []  # what it was: the lines below its amount


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [_lines(t) for t in pages_text]
    combined = "\n".join(pages_text)

    m = _STATEMENT_DATE_RE.search(combined)
    period = _PERIOD_RE.search(combined)
    try:
        statement_date = _iso(m.group(1)) if m else _iso(period.group(2)) if period else ""
    except ValueError:
        statement_date = ""
    if not statement_date:
        raise parser_common.ParserDiagnosticError(
            "no 'Statement date: DD Mon YYYY' or 'Statement period: ... - DD Mon YYYY' line found",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("statementDate",))
    summary, unread_summary = _summary(pages)

    rows: list[_Row] = []
    unread: list[dict] = [unread_summary] if unread_summary else []
    closing_row = None
    done = False  # past the table's "Closing balance" line
    for p, lines in enumerate(pages, 1):
        in_table = False
        row = None  # the row read last, while the lines below it belong to it
        for n, s in enumerate(lines, 1):
            if not s:
                continue
            if _TABLE_HEADER_RE.match(s):
                in_table, row = not done, None
                continue
            dated = _ROW_RE.match(s)
            if not in_table:
                # Outside the table, a dated line with an amount below it is
                # a transaction in a part of the statement this parser
                # doesn't know: reported, not dropped.
                if dated and n < len(lines) and _AMOUNT_RE.match(lines[n]):
                    unread.append({"page": p, "line": n, "text": s})
                continue
            if _PAGE_FOOT_RE.match(s):
                in_table = False
                continue
            if dated:
                try:
                    day = _iso(dated.group(1))
                except ValueError:
                    unread.append({"page": p, "line": n, "text": s})
                    row = None
                    continue
                row = _Row(p, n, s, day, dated.group(2))
                if _BALANCE_LINE_RE.match(dated.group(2)):
                    if dated.group(2).lower().startswith("closing"):
                        closing_row = row
                    continue
                rows.append(row)
                continue
            if row is None:
                continue
            if row.amount is not None:
                row.kind.append(s)
                continue
            a = _AMOUNT_RE.match(s)
            wrapped = None if a else _WRAPPED_AMOUNT_RE.match(s)
            if a:
                sign, figure = a.group(1), a.group(2)
            elif wrapped:
                row.details.append(wrapped.group(1))
                sign, figure = wrapped.group(2), wrapped.group(3)
            else:
                row.details.append(s)  # a merchant's name wrapped onto a second line
                continue
            value = common.parse_amount(figure)
            row.money_in = sign == "+"
            row.amount = -value if row.money_in else value
            if row is closing_row:
                in_table, done, row = False, True, None

    if closing_row is not None and closing_row.amount is None:
        unread.append({"page": closing_row.page, "line": closing_row.line, "text": closing_row.text})
    for row in rows:
        if row.amount is None:
            unread.append({"page": row.page, "line": row.line, "text": row.text})
    read = [row for row in rows if row.amount is not None]
    unread = sorted({(u["page"], u["line"]): u for u in unread}.values(), key=lambda u: (u["page"], u["line"]))

    transactions = []
    for row in read:
        kind = " ".join(row.kind)
        description = " ".join(row.details)
        if kind and kind.lower() != "purchase":
            description += " - " + kind
        transactions.append({"date": row.day, "description": description, "amount": row.amount, "balance": None})

    opening = summary[0] if summary else None
    closing = summary[4] if summary else closing_row.amount if closing_row and closing_row.amount is not None else None
    common.apply_running_balance(transactions, opening)
    common.negate_amounts_and_balances(transactions)
    common.tag_account(transactions, "", "Credit Card")
    keys = ["date", "description", "amount", "balance", "account", "accountType"]
    if _currency_accepted():
        for t in transactions:
            t["currency_code"] = "GBP"
        keys.append("currency_code")

    # The statement's own figures, negated like the rows.
    checks: list[dict] = []
    if opening is not None and closing is not None:
        checks.append({"kind": "balance", "label": "Transactions", "table": "cash_transactions",
                       "rows": list(range(len(transactions))), "opening": -opening, "closing": -closing})
    if summary:
        _, money_out, money_in, fees, _ = summary
        checks.append({"kind": "sum", "label": "Money in", "table": "cash_transactions",
                       "rows": [i for i, row in enumerate(read) if row.money_in], "expected": money_in})
        checks.append({"kind": "sum", "label": "Money out, interest & fees", "table": "cash_transactions",
                       "rows": [i for i, row in enumerate(read) if not row.money_in],
                       "expected": -round(money_out + fees, 2)})
    if unread:
        checks.append({"kind": "unread", "label": "Transactions", "lines": unread})

    return {
        "institution": INSTITUTION,
        "statementDate": statement_date,
        "transactions": [{k: t[k] for k in keys} for t in transactions],
        "checks": checks,
    }
