# SPDX-License-Identifier: Apache-2.0
"""Schwab Retirement Plan Services 401(k) quarterly statement parser.

This is a different document family from Schwab's retail brokerage account
statement.  It prints a period-level account-value bridge and an ending fund
snapshot, but no itemized transaction ledger or account number.  The parser
therefore emits contribution/fee summary rows and holdings; OrbySystems' shared
missing-account resolver asks the user for an identifier before insertion.
"""

from __future__ import annotations

from datetime import datetime
import re

import pdfplumber

import parser_common

from . import common
from . import diagnostic_helpers


KIND = parser_common.KIND_BROKERAGE
INSTITUTION = "Charles Schwab"
SUPPORT_TIER = parser_common.SUPPORT_TIER_PARTIAL
PARSER_REVISION = 1

# OpenText's text layer frequently removes spaces between adjacent words even
# though the rendered statement is perfectly spaced.  These are the stable
# public labels as they appear in that compact extraction.
DIAGNOSTIC_MARKERS = {
    "plan_value": "Changein PlanAccountValue",
    "positions": "YourPositions",
    "holdings": "Asset AllocationandAccountValue",
}
DIAGNOSTIC_FIELDS = {
    "statementPeriod": "Periodcovered",
    "beginningValue": "BeginningValue",
    "employeeContributions": "YourContributions",
    "employerContributions": "EmployerContributions",
    "transactionFees": "IndividualTransactionFees",
    "planAdministrationFees": "PlanAdministrationandOther",
    "investmentGainLoss": "Gain/Loss/NetIncome",
    "endingValue": "EndingValue",
    "holdingsTotal": "TOTALACCOUNTVALUE",
}
DIAGNOSTIC_SIGNALS = diagnostic_helpers.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = diagnostic_helpers.DIAGNOSTIC_COUNTS
DIAGNOSTIC_TERMS = diagnostic_helpers.DIAGNOSTIC_TERMS

_ACCOUNT_TYPE = "401(k)"
_EPS = 0.02
_MONTHS = (
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December"
)
_PERIOD_RE = re.compile(
    rf"Periodcovered:?(?P<start_month>{_MONTHS})(?P<start_day>\d{{1,2}}),?"
    rf"(?P<start_year>\d{{4}})TO(?P<end_month>{_MONTHS})(?P<end_day>\d{{1,2}}),?"
    r"(?P<end_year>\d{4})",
    re.I,
)
_ACCOUNT_RE = re.compile(
    r"Account\s*(?:Number|#)\s*:?\s*([*XxA-Za-z0-9-]{4,})",
    re.I,
)
_MONEY = r"(?:\(\$?[\d,]+\.\d{2}\)|-?\$?[\d,]+\.\d{2})"
_MONEY_RE = re.compile(_MONEY)
_MONEY_WORD_RE = re.compile(rf"^{_MONEY}$")
_NUMBER_WORD_RE = re.compile(r"^[\d,]+(?:\.\d+)?$")
_PERCENT_WORD_RE = re.compile(r"^(\d+(?:\.\d+)?)%$")

_SUMMARY_LABELS = {
    "beginning": (r"BeginningValue", "Beginning Value", "beginningValue"),
    "employee": (r"YourContributions", "Your Contributions", "employeeContributions"),
    "employer": (r"EmployerContributions", "Employer Contributions", "employerContributions"),
    "transaction_fees": (r"IndividualTransactionFees\*", "Individual Transaction Fees", "transactionFees"),
    # In the real PDF, the two monetary columns precede the wrapped "Fees*"
    # suffix in extraction order, so this prefix is the stable control.
    "plan_fees": (r"PlanAdministrationandOther(?:Fees\*)?", "Plan Administration and Other Fees", "planAdministrationFees"),
    "gain_loss": (r"Gain/Loss/NetIncome", "Gain/Loss/Net Income", "investmentGainLoss"),
    "ending": (r"EndingValue", "Ending Value", "endingValue"),
}

_DIAGNOSTIC_REPLACEMENTS = {
    "Changein PlanAccountValue": "Change in Plan Account Value",
    "Asset AllocationandAccountValue": "Asset Allocation and Account Value",
    "BeginningValue": "Beginning Value",
    "YourContributions": "Your Contributions",
    "EmployerContributions": "Employer Contributions",
    "IndividualTransactionFees": "Individual Transaction Fees",
    "PlanAdministrationandOther": "Plan Administration and Other Fees",
    "Gain/Loss/NetIncome": "Investment Gain/Loss and Net Income",
    "EndingValue": "Ending Value",
    "TOTALACCOUNTVALUE": "TOTAL ACCOUNT VALUE",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def detect(head_text: str) -> tuple[bool, str]:
    compact = _compact(head_text).casefold()
    required = {
        "Schwab Retirement Plan Services": "schwabretirementplanservices",
        "401(k) plan statement": "401(k)planstatement",
        "Period covered": "periodcovered:",
        "Change in Plan Account Value": "changeinplanaccountvalue",
        "Asset Allocation and Account Value": "assetallocationandaccountvalue",
    }
    missing = [label for label, marker in required.items() if marker not in compact]
    if missing:
        return False, "missing Schwab retirement-plan marker(s): " + ", ".join(missing)
    if not _PERIOD_RE.search(_compact(head_text)):
        return False, "Schwab retirement-plan period not found"
    return True, "found Schwab Retirement Plan Services 401(k) statement, value bridge, and fund holdings"


def _amount(raw: str) -> float:
    value = raw.strip().replace("$", "").replace(",", "")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    parsed = float(value)
    return -parsed if negative else parsed


def _statement_date(text: str) -> str:
    match = _PERIOD_RE.search(_compact(text))
    if not match:
        return ""
    raw = f"{match.group('end_month')} {match.group('end_day')}, {match.group('end_year')}"
    try:
        return datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _account(text: str) -> str:
    for line in text.splitlines():
        match = _ACCOUNT_RE.search(line)
        if match:
            return common.last4_digits(match.group(1))
    return ""


def _summary(pages_text: list[str]) -> dict[str, float]:
    compact = _compact("\n".join(pages_text[:2]))
    values: dict[str, float] = {}
    missing: list[str] = []
    for key, (label_pattern, _, field_id) in _SUMMARY_LABELS.items():
        match = re.search(label_pattern + rf"(?P<period>{_MONEY})", compact, re.I)
        if not match:
            missing.append(field_id)
            continue
        value = _amount(match.group("period"))
        if key in {"transaction_fees", "plan_fees"} and value > 0:
            value = -value
        values[key] = value
    if missing:
        raise parser_common.ParserDiagnosticError(
            f"missing Schwab retirement-plan summary controls: {missing}",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="summary",
            missing_fields=missing,
        )
    return values


def _word_rows(page) -> list[list[dict]]:
    grouped: list[tuple[float, list[dict]]] = []
    for word in page.extract_words(x_tolerance=1, y_tolerance=2):
        top = float(word["top"])
        for i, (row_top, words) in enumerate(grouped):
            if abs(row_top - top) <= 2:
                words.append(word)
                grouped[i] = (row_top, sorted(words, key=lambda item: item["x0"]))
                break
        else:
            grouped.append((top, [word]))
    return [words for _, words in sorted(grouped, key=lambda item: item[0])]


def _symbol(description: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", description.upper())).strip()


def _parse_holdings(pdf_path: str, statement_date: str) -> tuple[list[dict], float | None]:
    holdings: list[dict] = []
    printed_total: float | None = None
    active = False
    pending_category_percent: float | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for words in _word_rows(page):
                texts = [word["text"] for word in words]
                joined = " ".join(texts)
                compact = _compact(joined).casefold()
                if "assetallocationandaccountvalue" in compact:
                    active = True
                    continue
                if not active:
                    continue

                if compact.startswith("totalaccountvalue"):
                    money_words = [word for word in words if _MONEY_WORD_RE.fullmatch(word["text"])]
                    if money_words:
                        printed_total = _amount(money_words[-1]["text"])
                    active = False
                    continue

                percent_index = next(
                    (i for i, word in enumerate(words) if _PERCENT_WORD_RE.fullmatch(word["text"])),
                    None,
                )
                percent_match = (
                    _PERCENT_WORD_RE.fullmatch(words[percent_index]["text"])
                    if percent_index is not None
                    else None
                )
                money_words = [word for word in words if _MONEY_WORD_RE.fullmatch(word["text"])]
                if not money_words:
                    if percent_match:
                        pending_category_percent = float(percent_match.group(1))
                    continue

                if percent_index is not None:
                    description_words = words[:percent_index]
                    percent = float(percent_match.group(1)) if percent_match else None
                elif pending_category_percent is not None and "--" in texts:
                    first_dash = texts.index("--")
                    description_words = words[:first_dash]
                    percent = pending_category_percent
                else:
                    continue
                description = " ".join(word["text"] for word in description_words).strip()
                if not description or percent is None:
                    continue

                holding = {
                    "symbol": _symbol(description),
                    "description": description,
                    "current_value": _amount(money_words[-1]["text"]),
                    "percent_of_account": percent,
                    "currency_code": "USD",
                    "price_as_of": statement_date,
                }
                if len(money_words) >= 2:
                    holding["price"] = _amount(money_words[-2]["text"])
                    price_x = float(money_words[-2]["x0"])
                    quantity_words = [
                        word
                        for word in words[percent_index + 1 :]
                        if float(word["x1"]) < price_x and _NUMBER_WORD_RE.fullmatch(word["text"])
                    ]
                    if quantity_words:
                        holding["quantity"] = common.parse_amount(quantity_words[-1]["text"])
                if re.search(r"\b(?:money market|treasury|stable value)\b|\bMM\b", description, re.I):
                    holding["is_cash_equivalent"] = True
                holdings.append(holding)

    return holdings, printed_total


def _transactions(summary: dict[str, float], statement_date: str) -> list[dict]:
    rows = (
        ("employee", "Statement-period employee contributions", "Employee Contribution", "contribution", "employee"),
        ("employer", "Statement-period employer contributions", "Employer Contribution", "contribution", "employer"),
        ("transaction_fees", "Statement-period individual transaction fees", "Individual Transaction Fee", "fee", "transaction_fee"),
        ("plan_fees", "Statement-period plan administration and other fees", "Plan Administration Fee", "fee", "plan_administration"),
    )
    transactions = []
    for key, description, action, transaction_type, subtype in rows:
        amount = summary[key]
        if abs(amount) <= _EPS:
            continue
        transactions.append(
            {
                "date": statement_date,
                "description": description,
                "amount": amount,
                "action": action,
                "transaction_type": transaction_type,
                "subtype": subtype,
                "currency_code": "USD",
            }
        )
    return transactions


def _require_close(label: str, parsed: float, printed: float, stage: str) -> None:
    if abs(parsed - printed) <= _EPS:
        return
    raise diagnostic_helpers.reconciliation_error(
        f"{label} does not reconcile: parsed {parsed:.2f}, printed {printed:.2f}",
        parsed,
        printed,
        stage,
    )


def _diagnostic_pages(pages_text: list[str]) -> list[str]:
    normalized = []
    for page in pages_text:
        for compact, expanded in _DIAGNOSTIC_REPLACEMENTS.items():
            page = page.replace(compact, expanded)
        normalized.append(page)
    return normalized


def parse(pages_text: list[str], pdf_path: str) -> dict:
    context = diagnostic_helpers.diagnostic_context(
        _diagnostic_pages(pages_text),
        section_markers=(
            "Change in Plan Account Value",
            "Asset Allocation and Account Value",
        ),
        known_labels=tuple(label for _, label, _ in _SUMMARY_LABELS.values()) + ("TOTAL ACCOUNT VALUE",),
    )
    try:
        text = "\n".join(pages_text)
        statement_date = _statement_date(text)
        if not statement_date:
            raise parser_common.ParserDiagnosticError(
                "Schwab retirement-plan statement date not found",
                code="PARSER_STATEMENT_DATE_INVALID",
                stage="metadata",
                missing_fields=("statementPeriod",),
            )

        summary = _summary(pages_text)
        context["counts"]["summaryComponents"] = len(summary)
        context["counts"]["activityControlComponents"] = len(summary)

        holdings, holdings_total = _parse_holdings(pdf_path, statement_date)
        context["counts"]["holdingsParsed"] = len(holdings)
        if holdings_total is None:
            raise parser_common.ParserDiagnosticError(
                "Schwab retirement-plan holdings total not found",
                code="PARSER_REQUIRED_DATA_MISSING",
                stage="holdings",
                missing_fields=("holdingsTotal",),
            )
        if not holdings:
            raise parser_common.ParserDiagnosticError(
                "no Schwab retirement-plan holdings found",
                code="PARSER_REQUIRED_DATA_MISSING",
                stage="holdings",
            )

        _require_close(
            "Schwab retirement-plan account-value bridge",
            summary["beginning"]
            + summary["employee"]
            + summary["employer"]
            + summary["transaction_fees"]
            + summary["plan_fees"]
            + summary["gain_loss"],
            summary["ending"],
            "summary",
        )
        _require_close(
            "Schwab retirement-plan holdings total",
            sum(holding["current_value"] for holding in holdings),
            holdings_total,
            "holdings",
        )
        _require_close(
            "Schwab retirement-plan ending value",
            holdings_total,
            summary["ending"],
            "holdings",
        )

        transactions = _transactions(summary, statement_date)
        context["counts"]["transactionsParsed"] = len(transactions)
        account = _account(text)
        common.tag_account(holdings, account, _ACCOUNT_TYPE)
        common.tag_account(transactions, account, _ACCOUNT_TYPE)
        return {
            "institution": INSTITUTION,
            "statementDate": statement_date,
            "tables": {
                "brokerage_holdings": holdings,
                "brokerage_transactions": transactions,
            },
        }
    except ValueError as error:
        raise parser_common.enrich_parser_error(error, **context) from error
