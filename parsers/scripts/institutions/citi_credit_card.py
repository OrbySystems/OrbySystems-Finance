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
blank on some payments, so a row can start with one date or two. On a
Costco card the rewards summary prints in a column beside the table, so a
row, a section's heading or total, or the table's header can run on into
one of its lines: words and figures that are not money ("Your 2026 reward
will follow"), or a line of its ledger ("... $15.00 and EV charging ......
+$0.60", "certificate amount ...... -$12.40"). A row's amount is never
taken from that text. A row level with any other figure ("$45.00 Year to
Date : $31.40") is read by its own amount, the first on its line, and a
charge printed in capitals with no date in Fees Charged or Interest
Charged by its own, dated the closing date. Such tentative readings are
kept only when each is in at least one of the statement's checks and every
check over any of them holds; else all are held for review, as lines not
read. A statement can cover two cards, the primary cardholder's and an
authorized user's, each heading its own sections; they are one account.

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

import os
import re
from datetime import datetime

import parser_common
import statement_checks

from institutions import common


SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
INSTITUTION = "Citi"
PARSER_REVISION = 8
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

# True when the billing period's pattern matched but its dates are not a
# billing cycle's; False when it did not match at all.
DIAGNOSTIC_SIGNALS = ("billingPeriodDatesInvalid",)

# The billing period, "Billing Period: 10/15/25-11/14/25", and the ways a
# statement's text can give the same line: any space between the words or
# none (a no-break space, words glued in small type), no colon, one-digit
# months and days, a four-digit year, any dash or "to".
_PERIOD_RE = re.compile(
    r"Billing\s*Period\s*:?\s*"
    r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4}|\d{2})(?!\d)"
    r"\s*(?:[-\u2010-\u2015\u2212]|to)\s*"
    r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE,
)
# The longest a billing cycle runs, in days. A closing date further out is
# a misread - "09/14/2630 days", a year glued to the next word.
_LONGEST_CYCLE = 62
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

# Where the table ends: the year-to-date totals some cards print after it,
# or the interest table.
_TABLE_END_RE = re.compile(r"^(?:Interest charge calculation|\d{4}\s+totals\s+year-to-date)\b", re.IGNORECASE)
# The column beside the table (the rewards summary on a Costco card's later
# page) can run on into the line a row, a heading or a total is on. What
# runs on is text with nothing shaped like money - words, and figures that
# are not money, a year, a count, a percentage ("Your 2026 reward will
# follow", "4% on eligible gas") - or a line of the summary's ledger, its
# figure after a dot leader and signed before the dollar ("4% on eligible
# gas ...... +$1.80"). A row's own amount is never printed with a "+", so
# that figure is never taken for it; a ledger line can print one signed
# "-" too ("certificate amount ...... -$12.40"), after its dot leader. A
# column line with any other figure ("Year to Date : $31.40") makes the row
# a tentative reading (_TENTATIVE_ROW_RE). Through revision 5 the row's
# amount was taken from that figure instead, and a tester's purchases check
# failed with nothing to show why (27 Oct 2026).
_BESIDE_TEXT = r"\s+(?!\d\.\d)[A-Za-z0-9](?:(?!\d\.\d|\$)[^\n])*?"
_BESIDE = r"(?:" + _BESIDE_TEXT + r"(?:\.{3,}\s*[+-]\$[\d,]+\.\d{2})?)?"
# The transaction table's header: "Sale / Post" over the Costco card's
# dates, "Trans. / Post" over other cards'. What the column beside it runs
# on into it, a "$" figure included, is left aside: the header holds none.
_TABLE_START_RE = re.compile(r"^(?:Sale|Trans\.?)\s+Post\b", re.IGNORECASE)
# Its sections. Purchases can be headed with their kind ("Standard
# Purchases"), and run on into the column beside the table like a row. A
# heading printed as Citi prints it, in title case, takes anything after
# it, a column line's "$" figure included; any other casing takes only what
# holds no money, so a charge that starts with a heading's words, printed
# in capitals ("INTEREST CHARGED TO STANDARD PURCH $4.20"), is never a
# heading. The ledger's own line "purchases ...... +$5.70" (the end of "2%
# on Costco and Costco.com purchases") is none either.
_SECTION_NAMES = (r"Payments, Credits and Adjustments|(?:[A-Za-z]+\s+)?Purchases|Balance Transfers|"
                  r"Cash Advances|Fees Charged|Interest Charged")
_SECTION_RE = re.compile(r"^(?P<name>" + _SECTION_NAMES + r")" + _BESIDE + r"\s*$", re.IGNORECASE)
_TITLE_SECTION_RE = re.compile(
    r"^(?P<name>Payments, Credits and Adjustments|(?:[A-Z][a-z]+\s+)?Purchases|Balance Transfers|"
    r"Cash Advances|Fees Charged|Interest Charged)\s+\S")
# A section's printed total: "TOTAL FEES FOR THIS PERIOD $0.00", "Total
# interest charged in this billing period $1.23". Not the year-to-date
# block's "Total fees charged in 2026", which ends the table. Its own figure
# comes first; what the column beside it runs on into it is left aside, a
# total misread there only failing its check.
_SECTION_TOTAL_RE = re.compile(
    r"^Total\s+(?P<what>fees|interest)\b(?:\s+charged)?\s+(?:for|in)\s+this\s+(?:billing\s+)?period\s+"
    r"(?P<sign>-)?\$?(?P<num>[\d,]+\.\d{2})(?:\s+\S.*)?$",
    re.IGNORECASE,
)
# A row's description holds no "$" amount: the row's own amount is the first
# one on its line, never one further along in the column's text. Nor does it
# end in a column label's colon or a dot leader: a dated line whose only
# figure is the column's ("... CITY CA Year to Date : $31.40") is no row.
_DESCRIPTION = r"((?:(?!-?\$[\d,]+\.\d{2}).)+?)(?<!:)(?<!\.\.)"
_TWO_DATE_ROW_RE = re.compile(
    r"^(\d{2}/\d{2})\s+\d{2}/\d{2}\s+" + _DESCRIPTION + r"\s+(-?\$?[\d,]+\.\d{2})" + _BESIDE + r"\s*$"
)
# Citi leaves Sale Date blank for some payments, so pdfplumber emits only
# the Post Date at the start of the row.
_ONE_DATE_ROW_RE = re.compile(r"^(\d{2}/\d{2})\s+" + _DESCRIPTION + r"\s+(-?\$?[\d,]+\.\d{2})" + _BESIDE
                              + r"\s*$")
# A row level with a column line that has a "$" figure of its own ("08/21
# 08/21 STORE $45.00 Year to Date : $31.40"): its own amount is the first
# on the line, Citi printing every row's with "$". Read only tentatively.
_TENTATIVE_ROW_RE = re.compile(r"^(\d{2}/\d{2})\s+(?:\d{2}/\d{2}\s+)?" + _DESCRIPTION
                               + r"\s+(-?\$[\d,]+\.\d{2})\s+\S.*$")
# A charge printed with no date in the Fees Charged or Interest Charged
# section ("INTEREST CHARGED TO STANDARD PURCH $4.20"), in capitals as Citi
# prints its charges: no row form takes it, so it is read only tentatively,
# a line of the rewards ledger beside it left aside ("LATE FEE $41.00 4% on
# eligible gas ...... +$1.80"). Never a total, nor a line of the column
# beside the section, in mixed case or ending in a colon: "certificate
# amount ...... -$12.40", which revision 6 took for one, or "Year to Date :
# $31.40", which revision 7 did.
_UNDATED_CHARGE_RE = re.compile(r"^(?!TOTAL\b)(?P<desc>[A-Z](?:(?!\.\.)[A-Z0-9 &'/#*.,-])*?)\s"
                                r"(?P<amount>-?\$[\d,]+\.\d{2})" + _BESIDE + r"\s*$")
# Starts like a row; reported as not read when no row form, tentative or
# not, takes it.
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
        if _PERIOD_RE.search(head_text):
            return True, "matched Citi Costco Anywhere Visa monthly statement"
        # An app that reads the label apart from its dates (_read_again):
        # parse() reads the statement again.
        if re.search(r"billing\s*period", lower):
            return True, "matched Citi Costco Anywhere Visa monthly statement, its billing period to be read again"
        return False, "Citi Costco markers found, but no Billing Period"
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
        opening, closing = datetime(_year(oy), int(om), int(od)), datetime(_year(cy), int(cm), int(cd))
    except ValueError:
        return None, None
    if not 0 < (closing - opening).days <= _LONGEST_CYCLE:
        return None, None
    return opening, closing


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
    line numbers 1-based). found says whether the table was there at all.
    A tentative reading's row carries its line as "held"; _parse_monthly
    keeps it or reports the line."""
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
                # A row the column beside it ran on into ends in words.
                if (_ROWLIKE_RE.match(line) or _TWO_DATE_ROW_RE.match(line) or _ONE_DATE_ROW_RE.match(line)
                        or _TENTATIVE_ROW_RE.match(line)):
                    not_read(page_no, line_no, line)
                continue
            heading = _SECTION_RE.match(line) or _TITLE_SECTION_RE.match(line)
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
            held = None
            match = _TWO_DATE_ROW_RE.match(line) or _ONE_DATE_ROW_RE.match(line)
            if not match and _DATED_RE.match(line):
                match = _TENTATIVE_ROW_RE.match(line)
                held = {"page": page_no, "line": line_no, "text": line}
            date = _transaction_date(match.group(1), closing) if match else None
            charge = None
            if not match and section in ("Fees Charged", "Interest Charged"):
                charge = _UNDATED_CHARGE_RE.match(line)
            if date:
                # Summary and year-to-date total rows have an amount but no
                # leading MM/DD date, so only actual activity reaches here.
                rows.append({
                    "date": date,
                    "description": re.sub(r"\s+", " ", match.group(2)).strip(),
                    "amount": common.parse_amount(match.group(3)),
                    "held": held,
                })
                sections.append(section)
            elif charge:
                rows.append({
                    "date": closing.strftime("%Y-%m-%d"),
                    "description": re.sub(r"\s+", " ", charge.group("desc")).strip(),
                    "amount": common.parse_amount(charge.group("amount")),
                    "held": {"page": page_no, "line": line_no, "text": line},
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
            signals={"billingPeriodDatesInvalid": bool(_PERIOD_RE.search(combined))},
        )

    found, rows, row_sections, totals, order, unread = _read_table(pages_text, closing)
    if not found or not (rows or unread):
        raise parser_common.ParserDiagnosticError(
            "Citi account activity table contained no transactions",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND",
            stage="activity",
        )

    summary = _summary(pages_text)
    account_match = _ACCOUNT_RE.search(combined)
    account = account_match.group(1) if account_match else ""
    statement_date = closing.strftime("%Y-%m-%d")
    transactions, checks = _assemble(rows, row_sections, totals, order, unread, summary, account)
    if any(row["held"] for row in rows):
        # The tentative readings stay only when each is in at least one sum or
        # balance check and every check over any of them holds; else they are
        # all held for review, as lines not read. A reading no check covers is
        # confirmed by nothing (a summary that didn't read).
        results = statement_checks.evaluate(checks, {"cash_transactions": transactions}, statement_date)
        held = {i for i, t in enumerate(transactions) if t["held"]}
        covering = [(set(c["rows"]), r["ok"]) for r, c in zip(results, checks) if c["kind"] in ("sum", "balance")]
        covered = set().union(*(rows_ for rows_, _ in covering)) if covering else set()
        if held - covered or any(not ok and held & rows_ for rows_, ok in covering):
            for row, section in zip(rows, row_sections):
                if row["held"]:
                    unread.setdefault(section or _OUTSIDE, []).append(row["held"])
            for lines in unread.values():
                lines.sort(key=lambda line: (line["page"], line["line"]))
            kept = [i for i, row in enumerate(rows) if not row["held"]]
            transactions, checks = _assemble([rows[i] for i in kept], [row_sections[i] for i in kept],
                                             totals, order, unread, summary, account)
    for t in transactions:
        del t["held"]

    return {
        "institution": INSTITUTION,
        "statementDate": statement_date,
        "transactions": transactions,
        "checks": checks,
    }


def _assemble(rows: list[dict], row_sections: list[str | None], totals: dict[str, float], order: list[str],
              unread: dict[str, list[dict]], summary: dict[str, float], account: str) -> tuple[list[dict], list[dict]]:
    """The output rows, fresh copies of rows, and the checks over them."""
    # Date order, statement order within a day: the latest row carries the
    # New balance, which is what reading an account's latest balance takes
    # as its current one.
    credit = [_is_credit(section, row["amount"]) for section, row in zip(row_sections, rows)]
    ordered = sorted(range(len(rows)), key=lambda i: (rows[i]["date"], i))
    transactions = [{**rows[i], "balance": None, "reference": ""} for i in ordered]
    sections = [row_sections[i] for i in ordered]
    credit = [credit[i] for i in ordered]

    common.apply_running_balance(transactions, summary.get("Previous balance"))
    common.negate_amounts_and_balances(transactions)
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
    return transactions, checks


# Characters pdfminer measures as smaller than a point but that are wider
# than one and a half times that: a font whose height it could not read, as
# Citi's November 2025 statements draw their labels in. parser_common.page_text
# reads them at their line's size; an app older than that (OrbySystems 1.0.3)
# reads such a label's dates into the line above, so this parser, delivered
# to it, reads the statement again itself. The same rules as
# parser_common._resize_unmeasured, which a test holds equal.
def _own_resize_unmeasured(chars: list[dict]) -> list[dict] | None:
    def unmeasured(c):
        return c["size"] < 1.0 and c.get("upright", True) and c["x1"] - c["x0"] > 1.5 * c["size"]

    measured = [c for c in chars if c["size"] >= 1.0]
    if not measured or not any(unmeasured(c) for c in chars):
        return None
    sizes = sorted(c["size"] for c in measured)
    usual = sizes[len(sizes) // 2]
    by_bottom: dict[int, list[dict]] = {}
    for c in measured:
        by_bottom.setdefault(int(c["bottom"]), []).append(c)
    out = []
    for c in chars:
        if not unmeasured(c):
            out.append(c)
            continue
        near = sorted(m["size"] for key in range(int(c["bottom"]) - 5, int(c["bottom"]) + 6)
                      for m in by_bottom.get(key, ()) if abs(m["bottom"] - c["bottom"]) <= 0.3 * m["size"] + 0.5)
        size = near[len(near) // 2] if near else usual
        grown = size - (c["bottom"] - c["top"])
        out.append({**c, "size": size, "height": c["height"] + grown, "top": c["top"] - grown,
                    "doctop": c["doctop"] - grown, "y1": c["y1"] + grown})
    return out


def _read_again(pdf_path: str) -> list[str] | None:
    """The statement's pages, read as parser_common.page_text reads them,
    when any has a character too small to have been measured; else None,
    the app's own reading being that already."""
    import pdfplumber
    from pdfplumber.utils.text import chars_to_textmap

    resize = getattr(parser_common, "_resize_unmeasured", None) or _own_resize_unmeasured
    gap = getattr(parser_common, "SPACE_GAP_EM", 0.18)
    pages, resized = [], False
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            chars = resize(page.chars)
            if chars is None:
                pages.append(page.extract_text(x_tolerance_ratio=gap) or "")
                continue
            resized = True
            pages.append(chars_to_textmap(chars, x_tolerance_ratio=gap).as_string)
    return [text for text in pages if text] if resized else None


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001
    combined = "\n".join(pages_text)
    if _ANNUAL_TITLE_RE.search(combined):
        return _parse_annual(pages_text)
    if not _PERIOD_RE.search(combined) and pdf_path and os.path.exists(pdf_path):
        pages_text = _read_again(pdf_path) or pages_text
    return _parse_monthly(pages_text)
