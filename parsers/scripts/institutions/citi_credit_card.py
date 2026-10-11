"""Citi credit-card statement and annual-summary parser.

This covers Citi's monthly card statement - the Costco Anywhere Visa
layout, and the layout Citi's other cards print (its transaction table
headed "Trans. date / Post date", a year-to-date block after it) - and
Citi's annual account summary, which may include multiple cardholders and
groups purchases by category rather than presenting a balance ledger.

A monthly statement's Account Summary prints Previous balance, Payments,
Credits, Purchases, Cash advances, Fees, Interest and New balance, each
signed, and either balance can be a credit balance ("-$55.10"). On a
card's first page the summary sits in a column beside the payment
warning, so a summary line can start with the warning's own words ("...
a late fee of up to $41 Credits -$25.00"). The transaction table groups rows into
sections - Payments, Credits and Adjustments; Standard Purchases (a
cardholder's name can head their own); Fees Charged; Interest Charged -
the last two closing on a printed total. Citi leaves the transaction date
blank on some payments, so a row can start with one date or two.

Citi prints charges as positive and payments/credits as negative. A
monthly statement is read in those printed signs and checked against its
own figures (statement_checks): each printed section total, the summary's
Payments and Credits against the payment and credit rows and its other
figures against the rest, Previous balance + every row = New balance, and
every line that looks like a row but could not be read. A statement that
does not add up is held for the user's review rather than refused. Rows
are then put in date order, so the latest carries the New balance, and
every amount and derived balance is flipped to OrbySystems' cash-impact
convention (purchases negative, payments and credits positive).
"""

import re
from datetime import datetime

import parser_common

from institutions import common


SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
INSTITUTION = "Citi"
PARSER_REVISION = 3
DIAGNOSTIC_MARKERS = {
    "account_summary": "Account Summary",
    "transaction_table": "date description amount",
    "payments_credits": "Payments, Credits and Adjustments",
    "interest_calculation": "Interest charge calculation",
    "annual_summary": "Annual account summary",
    "annual_categories": "Totals by Category",
}
DIAGNOSTIC_FIELDS = {
    "billingPeriod": "Billing Period",
    "previousBalance": "Previous balance",
    "newBalance": "New balance",
    "paymentDueDate": "Payment Due Date",
    "minimumPaymentDue": "Minimum Payment Due",
    "creditLimit": "Credit Limit",
}

_PERIOD_RE = re.compile(
    r"Billing Period:\s*(\d{2})/(\d{2})/(\d{2,4})\s*[-–—]\s*"
    r"(\d{2})/(\d{2})/(\d{2,4})",
    re.IGNORECASE,
)
_ACCOUNT_RE = re.compile(r"Account number ending in\s*:?\s*(\d{3,4})", re.IGNORECASE)

# A figure as the Account Summary prints it, its sign before or after the
# dollar sign: "-$55.10", "+$30.00", "$300.00".
_FIGURE = r"(?P<sign>[+-])?\s*\$?\s*(?P<sign2>-)?(?P<num>[\d,]+\.\d{2})"
# Searched anywhere on the summary's page rather than at a line's start:
# the column beside the summary can come first on its line.
_PREVIOUS_BALANCE_RE = re.compile(r"(?<![A-Za-z])Previous balance\s+" + _FIGURE, re.IGNORECASE)
_NEW_BALANCE_RE = re.compile(r"(?<![A-Za-z])New balance\s+" + _FIGURE, re.IGNORECASE)
_SUMMARY_CREDITS = ("Payments", "Credits")
_SUMMARY_DEBITS = ("Purchases", "Cash advances", "Fees", "Interest")
_SUMMARY_RES = {
    label: re.compile(r"(?<![A-Za-z])" + re.escape(label) + r"\s+(?P<sign>[+-])?\s*\$(?P<sign2>-)?"
                      r"(?P<num>[\d,]+\.\d{2})", re.IGNORECASE)
    for label in _SUMMARY_CREDITS + _SUMMARY_DEBITS
}

# The transaction table's header: "Sale / Post" over the Costco card's
# dates, "Trans. / Post" over other cards'.
_TABLE_START_RE = re.compile(r"^(?:Sale|Trans\.?)\s+Post\s*$", re.IGNORECASE)
# Where it ends: the year-to-date totals some cards print after it, or the
# interest table.
_TABLE_END_RE = re.compile(r"^(?:Interest charge calculation|\d{4}\s+totals\s+year-to-date)\b", re.IGNORECASE)
# Its sections. Purchases can be headed with their kind ("Standard
# Purchases").
_SECTION_RE = re.compile(
    r"^(?P<name>Payments, Credits and Adjustments|(?:[A-Za-z]+\s+)?Purchases|Balance Transfers|"
    r"Cash Advances|Fees Charged|Interest Charged)\s*$",
    re.IGNORECASE,
)
# A section's printed total: "TOTAL FEES FOR THIS PERIOD $0.00", "Total
# interest charged in this billing period $1.23". Not the year-to-date
# block's "Total fees charged in 2026", which ends the table.
_SECTION_TOTAL_RE = re.compile(
    r"^Total\s+(?P<what>fees|interest)\b(?:\s+charged)?\s+(?:for|in)\s+this\s+(?:billing\s+)?period\s+"
    r"(?P<sign>-)?\$?(?P<num>[\d,]+\.\d{2})\s*$",
    re.IGNORECASE,
)
_TWO_DATE_ROW_RE = re.compile(
    r"^(\d{2}/\d{2})\s+\d{2}/\d{2}\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$"
)
# Citi leaves Sale Date blank for some payments, so pdfplumber emits only
# the Post Date at the start of the row.
_ONE_DATE_ROW_RE = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$")
# Starts like a row; reported as not read when neither row form takes it.
_DATED_RE = re.compile(r"^\d{2}/\d{2}\b")
# Starts with a date and ends with an amount, anywhere in the statement:
# outside the table, a row nothing claimed.
_ROWLIKE_RE = re.compile(r"^\d{2}/\d{2}\s.*\d\.\d{2}\)?\s*(?:CR|DR|-)?\s*$", re.IGNORECASE)
_OUTSIDE = "Transactions"

_EPS = 0.005

_ANNUAL_TITLE_RE = re.compile(r"Annual\s+account\s+summary\s*\((\d{4})\)", re.I)
_ANNUAL_DATE_HEADER = "date description amount notes"
_ANNUAL_ROW_START_RE = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\b")
_ANNUAL_ROW_RE = re.compile(
    r"^([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s+(.+?)\s+(-?\$\s*[\d,]+\.\d{2})\s*$"
)
_ANNUAL_ACCOUNT_RE = re.compile(r"^(.+?)\s*\|\s*(.+?)\s*$")
_ANNUAL_SUBTOTAL_RE = re.compile(r"^Subtotal\s+(-?\$\s*[\d,]+\.\d{2})\s*$", re.I)


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    if "costco anywhere visa" in lower and "citicards.com" in lower:
        if not _PERIOD_RE.search(head_text):
            return False, "Citi Costco markers found, but no Billing Period"
        return True, "matched Citi Costco Anywhere Visa monthly statement"
    if (
        _ANNUAL_TITLE_RE.search(head_text)
        and "totals by category" in lower
        and "total by month" in lower
        and "if you earn rewards by category" in lower
    ):
        return True, "matched Citi credit-card annual account summary"
    if (
        "citicards.com" in lower
        and _PERIOD_RE.search(head_text)
        and all(marker in lower for marker in ("account summary", "previous balance", "new balance"))
    ):
        return True, "matched Citi credit-card monthly statement"
    # Any other Citi card layout is claimed by citi_credit_card_family, which
    # is untested, so that its failure offers the Statement Scrambler.
    return False, "Citi monthly-statement and annual-summary markers not found"


def _year(raw: str) -> int:
    value = int(raw)
    return 2000 + value if len(raw) == 2 and value < 70 else 1900 + value if len(raw) == 2 else value


def _period(combined_text: str) -> tuple[datetime | None, datetime | None]:
    match = _PERIOD_RE.search(combined_text)
    if not match:
        return None, None
    om, od, oy, cm, cd, cy = match.groups()
    try:
        return datetime(_year(oy), int(om), int(od)), datetime(_year(cy), int(cm), int(cd))
    except ValueError:
        return None, None


def _transaction_date(raw: str, closing: datetime) -> str | None:
    """An MM/DD date's year: the closing date's, unless that puts it after
    the closing date - nothing on a statement happens after it closes - in
    which case the year before (a December row on a January statement,
    including one dated before the period opened). None for a date that
    does not exist."""
    month, day = (int(part) for part in raw.split("/"))
    for year in (closing.year, closing.year - 1):
        try:
            date = datetime(year, month, day)
        except ValueError:
            return None
        if date <= closing:
            return date.strftime("%Y-%m-%d")
    return None


def _section_label(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    for canonical in ("Fees Charged", "Interest Charged"):
        if name.lower() == canonical.lower():
            return canonical
    return name


def _is_credit(section: str | None, printed_amount: float) -> bool:
    """Whether a row belongs with the summary's Payments and Credits: by its
    section, or by its printed sign when it came before any section."""
    if section is None:
        return printed_amount < 0
    lower = section.lower()
    return "payment" in lower or "credit" in lower


def _read_table(pages_text: list[str], closing: datetime):
    """The transaction table: its rows in statement order, each row's
    section, each section's printed total, the sections in order, and the
    lines that looked like rows but were not read, by section (page and
    line numbers 1-based). found says whether the table was there at all."""
    rows: list[dict] = []
    sections: list[str | None] = []
    totals: dict[str, float] = {}
    order: list[str] = []
    unread: dict[str, list[dict]] = {}
    found = in_table = False
    section = None

    def not_read(page: int, line_no: int, text: str) -> None:
        unread.setdefault(section if in_table and section else _OUTSIDE, []).append(
            {"page": page, "line": line_no, "text": text})

    for page_no, text in enumerate(pages_text, 1):
        for line_no, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            if _TABLE_START_RE.match(line):
                found = in_table = True
                continue
            if in_table and _TABLE_END_RE.match(line):
                in_table, section = False, None
                continue
            if not in_table:
                if _ROWLIKE_RE.match(line):
                    not_read(page_no, line_no, line)
                continue
            heading = _SECTION_RE.match(line)
            if heading:
                section = _section_label(heading.group("name"))
                if section not in order:
                    order.append(section)
                continue
            total = _SECTION_TOTAL_RE.match(line)
            if total:
                label = "Fees Charged" if total.group("what").lower() == "fees" else "Interest Charged"
                value = common.parse_amount(total.group("num"))
                totals[label] = round(totals.get(label, 0.0) + (-value if total.group("sign") else value), 2)
                if label not in order:
                    order.append(label)
                continue
            match = _TWO_DATE_ROW_RE.match(line) or _ONE_DATE_ROW_RE.match(line)
            date = _transaction_date(match.group(1), closing) if match else None
            if date:
                # Summary and year-to-date total rows have an amount but no
                # leading MM/DD date, so only actual activity reaches here.
                rows.append({
                    "date": date,
                    "description": re.sub(r"\s+", " ", match.group(2)).strip(),
                    "amount": common.parse_amount(match.group(3)),
                    "balance": None,
                    "reference": "",
                })
                sections.append(section)
            elif _DATED_RE.match(line):
                not_read(page_no, line_no, line)
    return found, rows, sections, totals, order, unread


def _summary(pages_text: list[str]) -> dict[str, float]:
    """The Account Summary's figures as printed, from the page that carries
    it; a figure that is not found is left out."""
    page = next((p for p in pages_text
                 if "account summary" in p.lower() and "previous balance" in p.lower()), "")

    def figure(match: re.Match) -> float:
        value = common.parse_amount(match.group("num"))
        return -value if match.group("sign") == "-" or match.group("sign2") else value

    out: dict[str, float] = {}
    for label, pattern in (("Previous balance", _PREVIOUS_BALANCE_RE), ("New balance", _NEW_BALANCE_RE),
                           *_SUMMARY_RES.items()):
        match = pattern.search(page)
        if match:
            out[label] = figure(match)
    return out


def _annual_accounts(first_page: str) -> dict[str, str]:
    """Map the annual report's cardholder headings to account suffixes."""
    accounts: dict[str, str] = {}
    for line in (raw.strip() for raw in first_page.splitlines()):
        if line.lower().startswith("totals by category"):
            break
        match = _ANNUAL_ACCOUNT_RE.match(line)
        if match:
            accounts[match.group(1).strip()] = common.last4_digits(match.group(2))
    return accounts


def _parse_annual(pages_text: list[str]) -> dict:
    combined = "\n".join(pages_text)
    title = _ANNUAL_TITLE_RE.search(combined)
    if not title:
        raise ValueError("Citi annual summary year is missing")
    year = int(title.group(1))
    accounts = _annual_accounts(pages_text[0] if pages_text else "")
    active_holder = next(iter(accounts), "")
    active_account = next(iter(accounts.values()), "")
    active_category = ""
    previous_line = ""
    category_amounts: dict[tuple[str, str], float] = {}
    incomplete_categories: set[tuple[str, str]] = set()
    transactions: list[dict] = []

    for text in pages_text:
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            if "|" not in line and line in accounts:
                active_holder = line
                active_account = accounts[line]
                previous_line = line
                continue
            if line.lower() == _ANNUAL_DATE_HEADER:
                active_category = previous_line
                previous_line = line
                continue

            row = _ANNUAL_ROW_RE.match(line)
            if row:
                raw_date, description, raw_amount = row.groups()
                date = datetime.strptime(raw_date, "%b %d, %Y")
                if date.year != year:
                    raise ValueError("Citi annual transaction year does not match summary year")
                printed_amount = common.parse_amount(raw_amount.replace(" ", ""))
                transactions.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "description": description.strip(),
                    "amount": -printed_amount,
                    "balance": None,
                    "reference": "",
                    "account": active_account,
                    "accountType": "Credit Card",
                })
                key = (active_holder, active_category)
                category_amounts[key] = round(category_amounts.get(key, 0.0) + printed_amount, 2)
                previous_line = line
                continue

            # A dated row whose amount was redacted is intentionally omitted;
            # remember that its category subtotal can no longer validate the
            # visible rows alone.
            if _ANNUAL_ROW_START_RE.match(line):
                incomplete_categories.add((active_holder, active_category))
                previous_line = line
                continue

            subtotal = _ANNUAL_SUBTOTAL_RE.match(line)
            if subtotal:
                key = (active_holder, active_category)
                if key not in incomplete_categories:
                    stated = common.parse_amount(subtotal.group(1).replace(" ", ""))
                    parsed = category_amounts.get(key, 0.0)
                    if abs(parsed - stated) > _EPS:
                        raise ValueError("Citi annual category subtotal does not reconcile")
                previous_line = line
                continue
            previous_line = line

    if not transactions:
        raise ValueError("Citi annual summary contained no readable transactions")
    return {
        "institution": INSTITUTION,
        "statementDate": f"{year}-12-31",
        "transactions": transactions,
    }


def _parse_monthly(pages_text: list[str]) -> dict:
    combined = "\n".join(pages_text)
    opening, closing = _period(combined)
    if not opening or not closing:
        raise parser_common.ParserDiagnosticError(
            "Citi billing period is missing or invalid",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="metadata",
            missing_fields=("billingPeriod",),
        )

    found, rows, row_sections, totals, order, unread = _read_table(pages_text, closing)
    if not found or not (rows or unread):
        raise parser_common.ParserDiagnosticError(
            "Citi account activity table contained no transactions",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND",
            stage="activity",
        )

    # Date order, statement order within a day: the latest row carries the
    # New balance, which is what reading an account's latest balance takes
    # as its current one.
    credit = [_is_credit(section, row["amount"]) for section, row in zip(row_sections, rows)]
    ordered = sorted(range(len(rows)), key=lambda i: (rows[i]["date"], i))
    transactions = [rows[i] for i in ordered]
    sections = [row_sections[i] for i in ordered]
    credit = [credit[i] for i in ordered]

    summary = _summary(pages_text)
    common.apply_running_balance(transactions, summary.get("Previous balance"))
    common.negate_amounts_and_balances(transactions)

    account_match = _ACCOUNT_RE.search(combined)
    account = account_match.group(1) if account_match else ""
    common.tag_account(transactions, account, "Credit Card")

    # The statement's own figures, negated like the rows (statement_checks).
    checks = []
    for label in order:
        indices = [i for i, section in enumerate(sections) if section == label]
        if label in totals and (indices or totals[label]):
            checks.append({"kind": "sum", "label": label, "table": "cash_transactions",
                           "rows": indices, "expected": round(-totals[label], 2)})
    if all(label in summary for label in _SUMMARY_CREDITS):
        checks.append({"kind": "sum", "label": "Account Summary: payments and credits",
                       "table": "cash_transactions", "rows": [i for i, c in enumerate(credit) if c],
                       "expected": round(-sum(summary[label] for label in _SUMMARY_CREDITS), 2)})
    if all(label in summary for label in _SUMMARY_DEBITS):
        checks.append({"kind": "sum", "label": "Account Summary: purchases, cash advances, fees and interest",
                       "table": "cash_transactions", "rows": [i for i, c in enumerate(credit) if not c],
                       "expected": round(-sum(summary[label] for label in _SUMMARY_DEBITS), 2)})
    if "Previous balance" in summary and "New balance" in summary:
        checks.append({"kind": "balance", "label": "Account Summary", "table": "cash_transactions",
                       "rows": list(range(len(transactions))),
                       "opening": round(-summary["Previous balance"], 2),
                       "closing": round(-summary["New balance"], 2)})
    for label, lines in unread.items():
        checks.append({"kind": "unread", "label": label, "lines": lines})

    return {
        "institution": INSTITUTION,
        "statementDate": closing.strftime("%Y-%m-%d"),
        "transactions": transactions,
        "checks": checks,
    }


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001
    combined = "\n".join(pages_text)
    if _ANNUAL_TITLE_RE.search(combined):
        return _parse_annual(pages_text)
    return _parse_monthly(pages_text)
