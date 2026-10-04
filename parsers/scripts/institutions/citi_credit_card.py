"""Citi credit-card statement and annual-summary parser.

This covers the current Costco Anywhere Visa monthly-statement layout and
Citi's annual account summary, which may include multiple cardholders and
groups purchases by category rather than presenting a balance ledger.

Citi prints charges as positive and payments/credits as negative.  The
parser first validates those printed signs against the statement summary,
then flips every amount and derived balance to OrbySystems' cash-impact
convention (purchases negative, payments and credits positive).
"""

import re
from datetime import datetime

import parser_common

from institutions import common


SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED
INSTITUTION = "Citi"
PARSER_REVISION = 2
DIAGNOSTIC_MARKERS = {
    "account_summary": "Account Summary",
    "transaction_table": "Sale Post",
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
_PREVIOUS_BALANCE_RE = re.compile(r"^Previous balance\s+\$?(-?[\d,]+\.\d{2})", re.I | re.M)
_NEW_BALANCE_RE = re.compile(r"^New balance\s+\$?(-?[\d,]+\.\d{2})", re.I | re.M)

_TABLE_START_RE = re.compile(r"^Sale\s+Post\s*$", re.IGNORECASE)
_TABLE_END_RE = re.compile(r"^Interest charge calculation\b", re.IGNORECASE)
_TWO_DATE_ROW_RE = re.compile(
    r"^(\d{2}/\d{2})\s+\d{2}/\d{2}\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$"
)
# Citi leaves Sale Date blank for some payments, so pdfplumber emits only
# the Post Date at the start of the row.
_ONE_DATE_ROW_RE = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$")

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
    citi_brand = "citicards.com" in lower or bool(re.search(r"\bciti(?:bank)?\b", lower))
    card_markers = sum(
        marker in lower
        for marker in (
            "payment due date",
            "minimum payment due",
            "credit limit",
            "cash advance limit",
            "payments, credits and adjustments",
            "interest charge calculation",
        )
    )
    if citi_brand and card_markers >= 2:
        return True, "matched untested Citi credit-card statement family"
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


def _transaction_date(raw: str, opening: datetime, closing: datetime) -> str:
    month, day = (int(part) for part in raw.split("/"))
    year = closing.year
    if opening.year != closing.year and month >= opening.month:
        year = opening.year
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"invalid transaction date {raw!r}") from error


def _transactions(pages_text: list[str], opening: datetime, closing: datetime) -> list[dict]:
    transactions: list[dict] = []
    in_table = False
    for text in pages_text:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if _TABLE_START_RE.match(line):
                in_table = True
                continue
            if not in_table:
                continue
            if _TABLE_END_RE.match(line):
                return transactions

            match = _TWO_DATE_ROW_RE.match(line)
            if match:
                date, description, amount = match.groups()
            else:
                match = _ONE_DATE_ROW_RE.match(line)
                if not match:
                    continue
                date, description, amount = match.groups()

            # Summary and year-to-date total rows have an amount but no
            # leading MM/DD date, so only actual activity reaches here.
            transactions.append({
                "date": _transaction_date(date, opening, closing),
                "description": re.sub(r"\s+", " ", description).strip(),
                "amount": common.parse_amount(amount),
                "balance": None,
                "reference": "",
            })
    return transactions


def _validate(combined_text: str, transactions: list[dict]) -> float:
    previous_match = _PREVIOUS_BALANCE_RE.search(combined_text)
    new_match = _NEW_BALANCE_RE.search(combined_text)
    if not previous_match or not new_match:
        raise ValueError("Citi account summary balances are missing")
    previous = common.parse_amount(previous_match.group(1))
    new = common.parse_amount(new_match.group(1))
    activity = round(sum(row["amount"] for row in transactions), 2)
    if abs(previous + activity - new) > _EPS:
        raise ValueError(
            f"transactions total {activity} does not reconcile previous balance "
            f"{previous} with new balance {new}"
        )
    return previous


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

    transactions = _transactions(pages_text, opening, closing)
    if not transactions:
        raise parser_common.ParserDiagnosticError(
            "Citi account activity table contained no transactions",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND",
            stage="activity",
        )

    previous = _validate(combined, transactions)
    common.apply_running_balance(transactions, previous)
    common.negate_amounts_and_balances(transactions)

    account_match = _ACCOUNT_RE.search(combined)
    account = account_match.group(1) if account_match else ""
    common.tag_account(transactions, account, "Credit Card")

    return {
        "institution": INSTITUTION,
        "statementDate": closing.strftime("%Y-%m-%d"),
        "transactions": transactions,
    }


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001
    combined = "\n".join(pages_text)
    if _ANNUAL_TITLE_RE.search(combined):
        return _parse_annual(pages_text)
    return _parse_monthly(pages_text)
