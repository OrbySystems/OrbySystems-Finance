"""Fidelity Rewards Visa credit card statement parser.

The card is issued by Elan Financial Services, and its monthly statement
uses Elan's layout:

  * page 1: the period ("... Closing Date:MM/DD/YYYY Account ending
    in:NNNN"), the payment block, and the Activity Summary -
    Previous Balance, Payments, Other Credits, Purchases, Balance
    Transfers, Advances, Other Debits, Fees Charged, Interest Charged and
    New Balance. The summary is printed in a column of its own, so its
    lines interleave with the payment block's in the extracted text
    ("Minimum Payment Due $25.00 Previous Balance + $1,234.56").
  * the Transactions pages: account-level sections ("Account Payments and
    Credits", "Account Fees"), then a group of sections per card on the
    account, headed with the cardholder's name and the card's last four
    digits ("JANE Q - 1234: Purchases and Other Debits", "... Other
    Credits", "... Fees"). Every section ends in a "TOTAL THIS PERIOD" or
    "TOTAL FEES THIS PERIOD" line, and an empty one prints "$0.00" in
    place of rows.

A row is

    Post Date  Trans Date  Ref #  Transaction Description  Amount
    01/06      01/04       0000   SOME MERCHANT CITY ST    $12.34

with credits marked CR ("$500.00CR"). Detail lines below a row - a
foreign-currency amount, an order or ticket number, a passenger name -
carry no date and are folded into the row's description. Dates are MM/DD
with no year; the year comes from the closing date, which also resolves a
period that straddles a year boundary.

Every card's rows belong to the one account: a second card on the account
(an authorized user, a replacement) shares its balance, so every row is
tagged with the statement's "Account ending in" digits. Giving a second
card's rows its own last four would make it a second account with a
balance of its own, counted twice in every total.

Amounts are read in the statement's printed sign (charges positive,
credits negative) and checked against the statement's own figures:

  * each section's rows against its TOTAL line;
  * the payment and credit sections against the summary's Payments plus
    Other Credits, and every other section against Purchases plus Balance
    Transfers, Advances, Other Debits, Fees Charged and Interest Charged -
    a section this parser does not know still has to add up there;
  * Previous Balance + every row = New Balance;
  * every line that looks like a row but could not be read, reported as
    not read rather than dropped.

These are reported as checks (statement_checks) rather than raised, so a
statement that does not add up is held for the user's review. Amounts and
the derived running balance are then negated to this codebase's
convention - see common.negate_amounts_and_balances.

Rows are put in date order before the running balance is derived, so the
latest row carries the New Balance - the figure anything reading an
account's latest balance takes as its current one.
"""

import re
from datetime import date

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
PARSER_REVISION = 1

INSTITUTION = "Fidelity Rewards Visa"
_ACCOUNT_TYPE = "Credit Card"

# --- detection ---------------------------------------------------------------

# "Fidelity(R) Rewards Visa Signature(R) Card", whatever mark the PDF puts
# after the name.
_BRAND_RE = re.compile(r"Fidelity\W{0,3}\s*Rewards\s+Visa", re.IGNORECASE)
# Card-statement vocabulary that a brokerage statement mentioning the card
# in an advertisement does not carry.
_CARD_MARKERS = ("Account ending in", "Closing Date", "Activity Summary", "Minimum Payment Due")

# --- statement facts ---------------------------------------------------------

_ACCOUNT_RE = re.compile(r"Account ending in:?\s*(\d{4})", re.IGNORECASE)
_CLOSING_RE = re.compile(r"Closing Date:?\s*(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)
# The page header's "MM/DD/YYYY -MM/DD/YYYY": the period, should the
# closing date not be found where it is expected.
_PERIOD_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")

_AMOUNT = r"\$?(?P<amt>\d[\d,]*\.\d{2})(?P<cr>\s?CR)?"

# The Activity Summary. Each figure's direction comes from what it is,
# not from the "+" or "-" printed beside it: some lines print the sign
# only when the figure is not zero.
_PREVIOUS_RE = re.compile(r"Previous Balance\s*[+\-]?\s*" + _AMOUNT, re.IGNORECASE)
_NEW_RE = re.compile(r"New Balance\s*=\s*" + _AMOUNT, re.IGNORECASE)
_NEW_FIRST_RE = re.compile(r"New Balance\s+" + _AMOUNT, re.IGNORECASE)
_SUMMARY_CREDITS = ("Payments", "Other Credits")
_SUMMARY_DEBITS = ("Purchases", "Balance Transfers", "Advances", "Other Debits", "Fees Charged", "Interest Charged")


def _summary_re(label: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z])" + re.escape(label) + r"\s*[+\-]?\s*\$(?P<amt>\d[\d,]*\.\d{2})(?P<cr>\s?CR)?",
                      re.IGNORECASE)


_SUMMARY_RES = {label: _summary_re(label) for label in _SUMMARY_CREDITS + _SUMMARY_DEBITS}

# --- the transaction pages ---------------------------------------------------

# "Account Payments and Credits", "Account Fees": the account's own
# sections, ahead of the per-card ones. Interest may be headed without
# the "Account".
_ACCOUNT_SECTION_RE = re.compile(
    r"^(?:Account\s+(?P<name>Payments and (?:Other )?Credits|Fees|Interest(?: Charged| Charges)?|"
    r"Other Credits|Credits|Advances|Balance Transfers|Other Debits)"
    r"|(?P<interest>Interest Charged|Interest Charges))\s*$",
    re.IGNORECASE,
)
# "<cardholder> - NNNN: <section>", one group of sections per card.
_CARD_SECTION_RE = re.compile(r"^(?P<holder>.+?)\s+-\s+(?P<card>\d{4}):\s*(?P<name>[A-Za-z][A-Za-z ,&/'-]*?)\s*$")
# A section's closing figure: "TOTAL THIS PERIOD $1,234.56", "TOTAL FEES
# THIS PERIOD $0.00", "TOTAL THIS PERIOD $500.00CR".
_TOTAL_RE = re.compile(r"^TOTAL\b.*?\bTHIS PERIOD\s+(?P<neg>-)?" + _AMOUNT + r"\s*$", re.IGNORECASE)
# A row; see the module docstring.
_ROW_RE = re.compile(
    r"^(?P<pm>\d{2})/(?P<pd>\d{2})\s+(?P<tm>\d{2})/(?P<td>\d{2})\s+(?P<rest>.+?)\s+"
    r"(?P<neg>-)?" + _AMOUNT + r"\s*$"
)
# The Ref # column: digits on a purchase, a short code in capitals on a
# payment. A row the issuer writes itself - a fee, an interest charge -
# can have none, and its first word is then the description's own, so a
# first word is the reference only when it is shaped like one.
_REF_RE = re.compile(r"^(?P<ref>(?=\S*\d)[A-Za-z0-9*#-]+|[A-Z]{1,3})\s+(?P<desc>\S.*)$")
# Starts like a row; reported as not read when _ROW_RE cannot take it.
_TWO_DATES_RE = re.compile(r"^\d{2}/\d{2}\s+\d{2}/\d{2}\b")
# Anything that starts with a date and ends with an amount, anywhere in
# the statement - outside a section, it is a row nothing claimed.
_ROWLIKE_RE = re.compile(r"^\d{2}/\d{2}\s.*\d\.\d{2}\)?\s*(?:CR|DR|-)?\s*$", re.IGNORECASE)
# Where the sections end: the year-to-date totals, the interest table, the
# statement's last line.
_END_RE = re.compile(r"^(?:\d{4}\s+Totals Year-to-Date|Interest Charge Calculation|End of Statement)\b",
                     re.IGNORECASE)
# The column header and page furniture inside the sections.
_FURNITURE_RE = re.compile(r"^(?:Post\s+Trans|Date\s+Date\s+Ref\b|Transactions|Continued on Next Page)\b",
                           re.IGNORECASE)
# What an empty section prints in place of rows.
_EMPTY_RE = re.compile(r"^-?\$?\d[\d,]*\.\d{2}(?:\s?CR)?$", re.IGNORECASE)

_OUTSIDE = "Transactions"


def detect(head_text: str) -> tuple[bool, str]:
    if not _BRAND_RE.search(head_text):
        return False, "'Fidelity Rewards Visa' not found"
    lower = head_text.lower()
    missing = [m for m in _CARD_MARKERS if m.lower() not in lower]
    if missing:
        return False, "'Fidelity Rewards Visa' found, but not the card statement's " + ", ".join(missing)
    return True, "matched Fidelity Rewards Visa credit card statement"


def _amount(m: re.Match) -> float:
    """A figure as printed, signed: CR (or a leading minus) is a credit."""
    value = common.parse_amount(m.group("amt"))
    credit = bool(m.group("cr")) or bool(m.groupdict().get("neg"))
    return -value if credit else value


def _closing_date(combined: str) -> date | None:
    m = _CLOSING_RE.search(combined)
    if m:
        month, day, year = (int(g) for g in m.groups())
    else:
        m = _PERIOD_RE.search(combined)
        if not m:
            return None
        month, day, year = (int(g) for g in m.groups()[3:])
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _row_date(month: int, day: int, closing: date) -> date | None:
    """An MM/DD date's year: the closing date's, unless that puts it after
    the closing date - nothing on a statement happens after it closes - in
    which case the year before (a December row on a January statement)."""
    for year in (closing.year, closing.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d <= closing:
            return d
    return None


def _section_label(account_name: str | None, card_name: str | None, card: str | None) -> str:
    if account_name:
        return "Account " + account_name
    # The cardholder's name is left out on purpose: the card's digits say
    # which group it is, and a label is shown wherever the check is.
    return f"{card_name} (card ending {card})"


def _is_credit_section(label: str) -> bool:
    lower = label.lower()
    return "credit" in lower or "payment" in lower


def _read_sections(pages_text: list[str], closing: date):
    """The rows, in statement order, with the label of the section each
    came from; each section's TOTAL figure, as printed; and the lines that
    looked like rows but were not read, by section label."""
    rows: list[dict] = []
    row_sections: list[str] = []
    totals: dict[str, float] = {}
    order: list[str] = []
    unread: dict[str, list[dict]] = {}

    def not_read(label: str, page: int, line: int, text: str) -> None:
        unread.setdefault(label, []).append({"page": page, "line": line, "text": text})

    section = None
    for page_no, text in enumerate(pages_text, 1):
        # A detail line belongs to the row above it on the same page; a
        # page starts with its header, never with another row's detail.
        last_row = None
        for line_no, raw in enumerate(text.split("\n"), 1):
            s = raw.strip()
            if not s:
                continue
            if _END_RE.match(s):
                section, last_row = None, None
                continue
            m = _ACCOUNT_SECTION_RE.match(s)
            c = None if m else _CARD_SECTION_RE.match(s)
            if m or c:
                section = (_section_label(m.group("name") or m.group("interest"), None, None) if m
                           else _section_label(None, c.group("name"), c.group("card")))
                if section not in order:
                    order.append(section)
                last_row = None
                continue
            if section is None:
                if _ROWLIKE_RE.match(s):
                    not_read(_OUTSIDE, page_no, line_no, s)
                continue
            t = _TOTAL_RE.match(s)
            if t:
                totals[section] = round(totals.get(section, 0.0) + _amount(t), 2)
                section, last_row = None, None
                continue
            r = _ROW_RE.match(s)
            if r:
                posted = _row_date(int(r.group("pm")), int(r.group("pd")), closing)
                traded = _row_date(int(r.group("tm")), int(r.group("td")), closing)
                if posted is None or traded is None:
                    not_read(section, page_no, line_no, s)
                    last_row = None
                    continue
                rest = r.group("rest").strip()
                ref = _REF_RE.match(rest)
                last_row = {
                    "date": traded.isoformat(),
                    "description": ref.group("desc") if ref else rest,
                    "amount": _amount(r),
                    "balance": None,
                    "reference": ref.group("ref") if ref else "",
                }
                rows.append(last_row)
                row_sections.append(section)
                continue
            if _TWO_DATES_RE.match(s) or _ROWLIKE_RE.match(s):
                not_read(section, page_no, line_no, s)
                last_row = None
                continue
            if _FURNITURE_RE.match(s) or _EMPTY_RE.match(s):
                if s.lower().startswith("continued on next page"):
                    last_row = None
                continue
            if last_row is not None:
                last_row["description"] += " " + s
    for row in rows:
        row["description"] = re.sub(r"\s+", " ", row["description"]).strip()
    return rows, row_sections, totals, order, unread


def _summary(pages_text: list[str]) -> dict:
    """The Activity Summary's figures as printed (credits negative), from
    the page that carries it; a figure that is not found is left out."""
    page = next((p for p in pages_text if "activity summary" in p.lower()), "")
    out = {}
    m = _PREVIOUS_RE.search(page)
    if m:
        out["Previous Balance"] = _amount(m)
    m = _NEW_RE.search(page) or _NEW_FIRST_RE.search(page)
    if m:
        out["New Balance"] = _amount(m)
    for label, pattern in _SUMMARY_RES.items():
        m = pattern.search(page)
        if m:
            value = common.parse_amount(m.group("amt"))
            out[label] = -value if label in _SUMMARY_CREDITS else value
    return out


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    combined = "\n".join(pages_text)
    closing = _closing_date(combined)
    m = _ACCOUNT_RE.search(combined)
    account = m.group(1) if m else ""

    if closing is None:
        rows, row_sections, totals, order, unread = [], [], {}, [], {}
    else:
        rows, row_sections, totals, order, unread = _read_sections(pages_text, closing)

    # Date order, statement order within a day - see the module docstring.
    ordered = sorted(range(len(rows)), key=lambda i: (rows[i]["date"], i))
    transactions = [rows[i] for i in ordered]
    sections = [row_sections[i] for i in ordered]

    summary = _summary(pages_text)
    common.apply_running_balance(transactions, summary.get("Previous Balance"))
    common.negate_amounts_and_balances(transactions)
    common.tag_account(transactions, account, _ACCOUNT_TYPE)

    # Every figure below is negated like the rows: this codebase's sign
    # convention, not the statement's.
    checks = []
    for label in order:
        indices = [i for i, s in enumerate(sections) if s == label]
        if label in totals and (indices or totals[label]):
            checks.append({"kind": "sum", "label": label, "table": "cash_transactions",
                           "rows": indices, "expected": round(-totals[label], 2)})
    if all(k in summary for k in _SUMMARY_CREDITS):
        checks.append({"kind": "sum", "label": "Activity Summary: payments and credits",
                       "table": "cash_transactions",
                       "rows": [i for i, s in enumerate(sections) if _is_credit_section(s)],
                       "expected": round(-sum(summary[k] for k in _SUMMARY_CREDITS), 2)})
    if all(k in summary for k in _SUMMARY_DEBITS):
        checks.append({"kind": "sum", "label": "Activity Summary: purchases, fees and interest",
                       "table": "cash_transactions",
                       "rows": [i for i, s in enumerate(sections) if not _is_credit_section(s)],
                       "expected": round(-sum(summary[k] for k in _SUMMARY_DEBITS), 2)})
    if "Previous Balance" in summary and "New Balance" in summary:
        checks.append({"kind": "balance", "label": "Activity Summary", "table": "cash_transactions",
                       "rows": list(range(len(transactions))),
                       "opening": round(-summary["Previous Balance"], 2),
                       "closing": round(-summary["New Balance"], 2)})
    for label, lines in unread.items():
        checks.append({"kind": "unread", "label": label, "lines": lines})

    return {
        "institution": INSTITUTION,
        "statementDate": closing.isoformat() if closing else "",
        "transactions": transactions,
        "checks": checks,
    }
