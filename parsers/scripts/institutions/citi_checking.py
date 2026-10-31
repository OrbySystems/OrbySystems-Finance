"""Citi checking monthly statement parser.

Citi's deposit-account activity table prints one unsigned transaction amount
and the resulting balance on every row. PDF text loses whether that amount was
in the subtracted or added column, so the balance change supplies its sign. A
row is accepted only when its printed amount reconciles to that change.
"""

import re
from datetime import datetime

import parser_common

from institutions import common


SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
INSTITUTION = "Citi"
PARSER_REVISION = 1
DIAGNOSTIC_FIELDS = {
    "statementDate": "statement period",
    "openingBalance": "opening balance",
    "closingBalance": "closing balance",
    "statementTotals": "total subtracted and added",
}
# Try the narrower credit-card parser and its fallback first. Their layouts
# are mutually exclusive with this deposit-account activity table, and this
# keeps credit-card failure diagnostics focused on the card parsers.
PRIORITY = 120

_EPS = 0.005
_AMOUNT = r"-?\$?[\d,]+\.\d{2}"
_ACCOUNT_ENDING_RE = re.compile(
    r"\bCiti\b[^\n]{0,80}\bAccount ending in\s*:?[ \t]*(\d{3,4})\b",
    re.IGNORECASE,
)
_PRODUCT_ACCOUNT_RE = re.compile(
    r"^.+?\b(?P<type>Checking)\s+(?P<number>\d{4,})\s*$",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"^([A-Z][a-z]+)\s+(\d{1,2})\s*[-\u2010-\u2015]\s*"
    r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\b",
    re.MULTILINE,
)
_ACTIVITY_HEADER_RE = re.compile(
    r"^(?:Continued\s+)?Date\s+Description\b.*\bBalance\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_OPENING_RE = re.compile(r"^(\d{2}/\d{2}/(?:\d{2}|\d{4}))\s+Opening Balance\s+(" + _AMOUNT + r")\s*$", re.I)
_CLOSING_RE = re.compile(r"^(\d{2}/\d{2}/(?:\d{2}|\d{4}))\s+Closing Balance\s+(" + _AMOUNT + r")\s*$", re.I)
_TRANSACTION_RE = re.compile(
    r"^(\d{2}/\d{2}/(?:\d{2}|\d{4}))\s+(.+?)\s+(" + _AMOUNT + r")\s+(" + _AMOUNT + r")\s*$"
)
_TOTALS_RE = re.compile(r"^Total\s+.+?\s+(" + _AMOUNT + r")\s+(" + _AMOUNT + r")\s*$", re.I)
_DATED_LINE_RE = re.compile(r"^\d{2}/\d{2}/(?:\d{2}|\d{4})\b")
_CONTINUATION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .,&'()/#:+-]{1,100}$")
_TABLE_BOUNDARY_RE = re.compile(
    r"^(?:Checking|Savings|Continued|Page\b|Member FDIC\b|Questions\b|Fees\b|Total\b|Closing\b)",
    re.IGNORECASE,
)


def detect(head_text: str) -> tuple[bool, str]:
    if not _ACCOUNT_ENDING_RE.search(head_text):
        return False, "Citi deposit-account header not found"
    if not re.search(r"^Checking\s*$", head_text, re.I | re.M):
        return False, "Citi account header found, but no checking section"
    if not _ACTIVITY_HEADER_RE.search(head_text):
        return False, "Citi deposit account found, but no activity table header"
    return True, "matched Citi checking activity table"


def _statement_date(combined_text: str) -> str:
    match = _PERIOD_RE.search(combined_text)
    if not match:
        return ""
    closing_month, closing_day, year = match.group(3), match.group(4), match.group(5)
    try:
        return datetime.strptime(f"{closing_month} {closing_day}, {year}", "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _transaction_date(raw: str) -> str:
    for pattern in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, pattern).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError("Citi checking transaction date is invalid")


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001
    combined = "\n".join(pages_text)
    statement_date = _statement_date(combined)
    if not statement_date:
        raise parser_common.ParserDiagnosticError(
            "Citi checking statement period is missing or invalid",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="metadata",
            missing_fields=("statementDate",),
        )

    header_account = ""
    header_match = _ACCOUNT_ENDING_RE.search(combined)
    if header_match:
        header_account = header_match.group(1)

    transactions: list[dict] = []
    row_indices: dict[str, list[int]] = {}
    openings: dict[str, float] = {}
    closings: dict[str, float] = {}
    totals: dict[str, tuple[float, float]] = {}
    previous: dict[str, float] = {}

    current_account = header_account
    current_type = "Checking"
    in_activity = False
    pending_index: int | None = None

    for text in pages_text:
        in_activity = False
        pending_index = None
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue

            product = _PRODUCT_ACCOUNT_RE.match(line)
            if product:
                current_account = common.last4_digits(product.group("number")) or header_account
                current_type = product.group("type").title()
                pending_index = None
                continue

            if _ACTIVITY_HEADER_RE.match(line):
                in_activity = True
                pending_index = None
                continue
            if not in_activity:
                continue

            account = current_account or header_account
            opening = _OPENING_RE.match(line)
            if opening:
                value = common.parse_amount(opening.group(2))
                openings[account] = value
                previous[account] = value
                pending_index = None
                continue

            closing = _CLOSING_RE.match(line)
            if closing:
                closings[account] = common.parse_amount(closing.group(2))
                in_activity = False
                pending_index = None
                continue

            stated_totals = _TOTALS_RE.match(line)
            if stated_totals:
                totals[account] = (
                    common.parse_amount(stated_totals.group(1)),
                    common.parse_amount(stated_totals.group(2)),
                )
                pending_index = None
                continue

            row = _TRANSACTION_RE.match(line)
            if row:
                if account not in previous:
                    raise parser_common.ParserDiagnosticError(
                        "Citi checking opening balance is missing",
                        code="PARSER_REQUIRED_DATA_MISSING",
                        stage="activity",
                        missing_fields=("openingBalance",),
                    )
                printed_amount = abs(common.parse_amount(row.group(3)))
                balance = common.parse_amount(row.group(4))
                amount = round(balance - previous[account], 2)
                if abs(abs(amount) - printed_amount) > _EPS:
                    raise ValueError("Citi checking transaction does not reconcile with its running balance")
                previous[account] = balance
                index = len(transactions)
                transactions.append({
                    "date": _transaction_date(row.group(1)),
                    "description": row.group(2).strip(),
                    "amount": amount,
                    "balance": balance,
                    "account": account,
                    "accountType": current_type,
                    "reference": "",
                })
                row_indices.setdefault(account, []).append(index)
                pending_index = index
                continue

            if _DATED_LINE_RE.match(line):
                raise parser_common.ParserDiagnosticError(
                    "Citi checking transaction row has an unsupported shape",
                    code="PARSER_UNCLASSIFIED_ROW",
                    stage="activity",
                )

            if (
                pending_index is not None
                and _CONTINUATION_RE.fullmatch(line)
                and not _TABLE_BOUNDARY_RE.match(line)
                and not re.search(_AMOUNT, line)
            ):
                transactions[pending_index]["description"] += " " + line

    if not transactions:
        raise parser_common.ParserDiagnosticError(
            "Citi checking activity table contained no transactions",
            code="PARSER_ACTIVITY_ROWS_NOT_FOUND",
            stage="activity",
        )

    for account in row_indices:
        missing_fields = []
        if account not in openings:
            missing_fields.append("openingBalance")
        if account not in closings:
            missing_fields.append("closingBalance")
        if account not in totals:
            missing_fields.append("statementTotals")
        if missing_fields:
            raise parser_common.ParserDiagnosticError(
                "Citi checking statement is missing required reconciliation values",
                code="PARSER_REQUIRED_DATA_MISSING",
                stage="summary",
                missing_fields=tuple(missing_fields),
            )

    checks = []
    for account, indices in row_indices.items():
        label = f"Checking activity ending {account}" if account else "Checking activity"
        if account in openings and account in closings:
            checks.append({
                "kind": "balance",
                "label": label,
                "table": "cash_transactions",
                "rows": indices,
                "opening": openings[account],
                "closing": closings[account],
            })
        if account in totals:
            withdrawn, added = totals[account]
            checks.extend([
                {
                    "kind": "sum",
                    "label": f"{label}: amount subtracted",
                    "table": "cash_transactions",
                    "rows": [i for i in indices if transactions[i]["amount"] < 0],
                    "expected": -withdrawn,
                },
                {
                    "kind": "sum",
                    "label": f"{label}: amount added",
                    "table": "cash_transactions",
                    "rows": [i for i in indices if transactions[i]["amount"] > 0],
                    "expected": added,
                },
            ])

    return {
        "institution": INSTITUTION,
        "statementDate": statement_date,
        "transactions": transactions,
        "checks": checks,
    }
