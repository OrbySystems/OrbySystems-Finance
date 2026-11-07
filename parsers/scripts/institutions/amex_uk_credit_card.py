"""American Express UK card statement parser.

Format: the monthly PDF "Statement of Account" of an American Express card
issued in the United Kingdom by American Express Services Europe Ltd., in
pounds. Page 1 prints the Membership Number (masked to its last five
digits, "xxxx-xxxxxx-12345"), then the account summary:

    Previous Closing Balance New Credits New Debits Closing Balance
    £1,480.00 - £1,480.00 + £967.25 = £967.25

and "Statement Period From 21 September to 20 October 2026". The
transactions follow, on as many pages as they take, each page repeating
the header above them:

    Transaction Process
    Date Date Transaction Details Foreign Spending Amount £
    Sep 21 Sep 21 PAYMENT RECEIVED - THANK YOU 1,480.00
    CR
    Sep 20 Sep 22 TESCO STORES LONDON 38.40

Each row has its transaction date and the date it was processed, without
their year; the year is the one that puts the transaction on or before
the end of the statement period. A credit is marked CR after its amount,
on the row's line or on the line below it, where the text layer may run it
into the row's carried-on line. The lines between two rows
carry on the one above (a merchant's address, a foreign amount). A
cardholder's rows end with "Total new ... transactions for <NAME>". The
transaction date is the row's date.

Amounts are read in the statement's own sign (debits raise the balance
owed), checked, then negated to this codebase's convention (CONTRACT.md,
"Amount sign convention"), in pounds: every row carries currency_code when
the app accepts it. The statement's own arithmetic is reported as checks:
the previous closing balance plus every row is the closing balance, the CR
rows add up to New Credits and the others to New Debits, each
cardholder's rows (repayments left out) add up to their "Total new"
figure, and every line that starts like a row but was not read is listed.
A balance in credit printed without its sign takes the one the summary's
own equation gives it. A statement without the account summary is refused:
no check would hold its rows to anything.

Built from a scrambled sample of a real statement (README_addparser.md):
detect() is anchored on words the scrambler keeps.
"""

import re
from datetime import date

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1

INSTITUTION = "American Express"

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_POUNDS = r"\d{1,3}(?:,\d{3})*\.\d{2}"

_MEMBERSHIP_RE = re.compile(r"\b[xX*]{4}[- ]?[xX*]{6}[- ]?(\d{4,5})\b")
# "Statement Period From 21 September to 20 October 2026": its end is the
# statement's date, and gives the rows their year.
_PERIOD_END_RE = re.compile(r"Statement Period\b.*?\bto\s+(\d{1,2})\s+(" + _MONTH + r")\s+(\d{4})", re.I)
# The credit summary's "At 20 October 2026", when the period isn't printed.
_AT_RE = re.compile(r"^At\s+(\d{1,2})\s+(" + _MONTH + r")\s+(\d{4})\b", re.I | re.M)
_SUMMARY_HEADER_RE = re.compile(r"^Previous Closing Balance\s+New Credits\s+New Debits\s+Closing Balance$", re.I)
# A summary figure, a balance in credit with its minus against it ("-£26.70",
# "£-26.70") or CR after it. A minus with a space after it is the
# operator between two figures.
_SUMMARY_FIGURE_RE = re.compile(r"([-–−])?£\s?([-–−])?(" + _POUNDS + r")(\s?CR\b)?", re.I)
_TABLE_HEADER_RE = re.compile(r"^Date\s+Date\s+Transaction Details\b", re.I)
# A row: "Sep 21 Sep 22 TESCO STORES LONDON 38.40", "... 1,480.00 CR".
_ROW_RE = re.compile(r"^(" + _MONTH + r")\s+(\d{1,2})\s+(" + _MONTH + r")\s+(\d{1,2})\s+(.*?)\s*(" + _POUNDS + r")(?:\s?(CR))?$")
# A line that starts like a row: two dates. One not read is reported.
_ROWLIKE_RE = re.compile(r"^" + _MONTH + r"\s+\d{1,2}\s+" + _MONTH + r"\s+\d{1,2}\b")
# A row's CR on the line below it, alone or run into the row's carried-on
# line there ("1 Example Road London CR"), which the text layer may merge.
_CREDIT_MARK_RE = re.compile(r"^(?:(.*\S)\s+)?CR$")
_TOTAL_RE = re.compile(r"^Total new\b.*\btransactions for\b", re.I)
_TOTAL_FIGURE_RE = re.compile(r"\s(" + _POUNDS + r")(\s?CR)?$")
# A repayment of the card, which a cardholder's total leaves out.
_PAYMENT_RE = re.compile(r"^PAYMENT\b|\bTHANK YOU\b", re.I)


def _currency_accepted() -> bool:
    """Whether the app running this accepts currency_code on a row: from
    the release after 1.0.2 on (orby-core docs/currency-on-cash-rows.md)."""
    return hasattr(parser_common, "normalize_currency_codes")


def detect(head_text: str) -> tuple[bool, str]:
    missing = [name for name, found in (
        ("American Express", re.search(r"American\s+Express", head_text)),
        ("Statement of Account", re.search(r"Statement of Account", head_text)),
        ("Membership Number", re.search(r"Membership Number", head_text)),
        ("Previous Closing Balance", re.search(r"Previous Closing Balance", head_text)),
        ("£ amounts", "£" in head_text),
    ) if not found]
    if missing:
        return False, "American Express UK statement marker(s) not found: " + ", ".join(missing)
    return True, "matched American Express UK Statement of Account (American Express, Membership Number, Previous Closing Balance, £)"


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def _month(name: str) -> int:
    return _MONTHS[name[:3].lower()]


def _period_end(combined: str) -> date | None:
    for regex in (_PERIOD_END_RE, _AT_RE):
        m = regex.search(combined)
        if m:
            try:
                return date(int(m.group(3)), _month(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
    return None


def _row_date(month: str, day: str, end: date) -> date:
    """A row's "Sep 21" as a date: the year that puts it on or before the
    period's end (a January statement lists December's rows); a few days
    after the end are allowed, for a row processed late. ValueError if it
    is no day."""
    m, d = _month(month), int(day)
    for year in (end.year, end.year - 1):
        try:
            when = date(year, m, d)
        except ValueError:
            if year == end.year - 1:
                raise
            continue
        if (when - end).days <= 7:
            return when
    raise ValueError(f"{month} {day} is not in the year before {end}")


def _summary(pages: list[list[str]]):
    """The account summary, in the statement's sign: ((previous closing
    balance, new credits, new debits, closing balance), None), or (None,
    the line below its header) when that line doesn't hold its four
    figures. A balance in credit is negative; one printed without its sign
    (its CR on the line below) takes the sign that makes the statement's
    own equation hold, previous - credits + debits = closing.
    ParserDiagnosticError when there is no account summary at all."""
    for p, lines in enumerate(pages, 1):
        for n, s in enumerate(lines, 1):
            if not _SUMMARY_HEADER_RE.match(s):
                continue
            below = lines[n] if n < len(lines) else ""
            figures = [-common.parse_amount(f) if (before or after or cr) else common.parse_amount(f)
                       for before, after, f, cr in _SUMMARY_FIGURE_RE.findall(below)]
            if len(figures) != 4:
                return None, {"page": p, "line": n + 1, "text": below}
            previous, credits, debits, closing = figures
            holds = [(o, c) for o in (previous, -previous) for c in (closing, -closing)
                     if abs(o - credits + debits - c) < 0.005]
            if holds and (previous, closing) not in holds and len(set(holds)) == 1:
                previous, closing = holds[0]
            return (previous, credits, debits, closing), None
    raise parser_common.ParserDiagnosticError(
        "no 'Previous Closing Balance New Credits New Debits Closing Balance' account summary found",
        code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("openingBalance", "closingBalance"))


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [_lines(t) for t in pages_text]
    combined = "\n".join(pages_text)

    end = _period_end(combined)
    if end is None:
        raise parser_common.ParserDiagnosticError(
            "no 'Statement Period From ... to DD Month YYYY' line found to date the rows by",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("statementDate",))
    m = _MEMBERSHIP_RE.search(combined)
    account = common.last4_digits(m.group(1)) if m else ""
    summary, unread_summary = _summary(pages)

    transactions: list[dict] = []
    credits: list[int] = []
    payments: set[int] = set()
    unread: list[dict] = [unread_summary] if unread_summary else []
    # Each cardholder's rows end with their total: (rows, total, as printed).
    totals: list[tuple[list[int], float]] = []
    section_start = 0
    for p, lines in enumerate(pages, 1):
        in_table = False
        row = None  # the index of the row whose carried-on lines follow
        pending: list[str] = []  # lines after it, until the next row shows they carry it on
        for n, s in enumerate(lines, 1):
            if not s:
                continue
            if _TABLE_HEADER_RE.match(s):
                in_table, row, pending = True, None, []
                continue
            looks_like_row = _ROWLIKE_RE.match(s)
            if not in_table:
                if looks_like_row:
                    # A row outside the table: in a part of the statement this
                    # parser doesn't know. Reported, not dropped.
                    unread.append({"page": p, "line": n, "text": s})
                continue
            if _TOTAL_RE.match(s):
                t = _TOTAL_FIGURE_RE.search(s)
                if t:
                    value = common.parse_amount(t.group(1))
                    totals.append((list(range(section_start, len(transactions))), -value if t.group(2) else value))
                else:
                    unread.append({"page": p, "line": n, "text": s})
                section_start = len(transactions)
                in_table, row, pending = False, None, []
                continue
            r = _ROW_RE.match(s) if looks_like_row else None
            when = None
            if r:
                try:
                    when = _row_date(r.group(1), r.group(2), end)
                except ValueError:
                    when = None
            if when:
                if row is not None and pending:
                    transactions[row]["description"] += " " + " ".join(pending)
                value = common.parse_amount(r.group(6))
                credit = bool(r.group(7))
                transactions.append({"date": when.isoformat(), "description": r.group(5) or "Transaction",
                                     "amount": -value if credit else value, "balance": None})
                row, pending = len(transactions) - 1, []
                if credit:
                    credits.append(row)
                if _PAYMENT_RE.search(r.group(5)):
                    payments.add(row)
            elif looks_like_row:
                unread.append({"page": p, "line": n, "text": s})
                row, pending = None, []
            elif row is not None and not pending and (mark := _CREDIT_MARK_RE.match(s)):
                # The row's CR, on the line below its amount.
                if row not in credits:
                    transactions[row]["amount"] = -transactions[row]["amount"]
                    credits.append(row)
                if mark.group(1):
                    pending.append(mark.group(1))
            elif row is not None:
                pending.append(s)
    unread = sorted({(u["page"], u["line"]): u for u in unread}.values(), key=lambda u: (u["page"], u["line"]))

    opening = summary[0] if summary else None
    common.apply_running_balance(transactions, opening)
    common.negate_amounts_and_balances(transactions)
    common.tag_account(transactions, account, "Credit Card")
    keys = ["date", "description", "amount", "balance", "account", "accountType"]
    if _currency_accepted():
        for t in transactions:
            t["currency_code"] = "GBP"
        keys.append("currency_code")

    # The statement's own figures, negated like the rows.
    checks: list[dict] = []
    if summary:
        previous, new_credits, new_debits, closing = summary
        checks.append({"kind": "balance", "label": "Account Summary", "table": "cash_transactions",
                       "rows": list(range(len(transactions))), "opening": -previous, "closing": -closing})
        checks.append({"kind": "sum", "label": "New Credits", "table": "cash_transactions",
                       "rows": sorted(credits), "expected": new_credits})
        checks.append({"kind": "sum", "label": "New Debits", "table": "cash_transactions",
                       "rows": [i for i in range(len(transactions)) if i not in credits], "expected": -new_debits})
    # A cardholder's total: their rows net of refunds, repayments left out.
    for rows, total in totals:
        checks.append({"kind": "sum", "label": "Cardholder total", "table": "cash_transactions",
                       "rows": [i for i in rows if not (i in credits and i in payments)], "expected": -total})
    if unread:
        checks.append({"kind": "unread", "label": "Transactions", "lines": unread})

    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "transactions": [{k: t[k] for k in keys} for t in transactions],
        "checks": checks,
    }
