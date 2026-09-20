"""E*TRADE investment-statement parser.

The documented provisional layout is still handled by the shared profile
core. Morgan Stanley at Work statements use a materially different Client
Statement family: the cover is followed by disclosure pages, with account
summary and holdings sections later in the document. That format is handled
here so detection never depends on those later pages.
"""

from __future__ import annotations

from datetime import date
import re

import parser_common

from . import common
from . import diagnostic_helpers
from . import provisional_brokerage_common as core


KIND = core.KIND
SUPPORT_TIER = core.SUPPORT_TIER
PROFILE_KEY = "etrade"
INSTITUTION = core.PROFILES[PROFILE_KEY]["institution"]
DIAGNOSTIC_MARKERS = {
    **core.diagnostic_markers(PROFILE_KEY),
    "client_statement": "CLIENT STATEMENT",
    "cash_flow": "CASH FLOW",
    "account_detail": "Account Detail",
}
DIAGNOSTIC_FIELDS = {
    **core.diagnostic_fields(PROFILE_KEY),
    "statementPeriod": "For the Period",
    "accountIdentifier": "Account Summary",
    "totalBeginningValue": "TOTAL BEGINNING VALUE",
    "securityTransfers": "Security Transfers",
    "netCreditsDebitsTransfers": "Net Credits/Debits/Transfers",
    "changeInValue": "Change in Value",
    "totalEndingValue": "TOTAL ENDING VALUE",
    "cashHolding": "MORGAN STANLEY BANK N.A.",
    "totalValue": "TOTAL VALUE",
}
DIAGNOSTIC_SIGNALS = core.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = core.DIAGNOSTIC_COUNTS
DIAGNOSTIC_TERMS = core.DIAGNOSTIC_TERMS
PARSER_REVISION = 2

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTHS = "|".join(_MONTH_NAMES)
_MONTH_NUMBERS = {name.casefold(): number for number, name in enumerate(_MONTH_NAMES, 1)}
_AT_WORK_PERIOD_RE = re.compile(
    rf"For\s+the\s+Period\s+(?P<start_month>{_MONTHS})\s*(?P<start_day>\d{{1,2}})\s*"
    rf"-\s*(?P<end_month>{_MONTHS})\s*(?P<end_day>\d{{1,2}}),\s*(?P<end_year>\d{{4}})",
    re.I,
)
_AT_WORK_ACCOUNT_RE = re.compile(
    r"^(?:Account Summary|Account Detail)\s+(?P<account>\d[\d-]{4,})\b",
    re.I | re.M,
)
_MONEY = r"(?:\$?\(\s*[\d,]+\.\d{2}\s*\)|\(\s*\$?[\d,]+\.\d{2}\s*\)|-?\$?-?[\d,]+\.\d{2})"
_DOLLAR_MONEY_RE = re.compile(r"\$\(?\s*[\d,]+\.\d{2}\s*\)?")
_ZERO_CELL = {"--", "—", "-"}

_AT_WORK_SUMMARY_LABELS = {
    "beginning": ("TOTAL BEGINNING VALUE", "totalBeginningValue"),
    "credits": ("Credits", "credits"),
    "debits": ("Debits", "debits"),
    "security_transfers": ("Security Transfers", "securityTransfers"),
    "net_transfers": ("Net Credits/Debits/Transfers", "netCreditsDebitsTransfers"),
    "market_change": ("Change in Value", "changeInValue"),
    "ending": ("TOTAL ENDING VALUE", "totalEndingValue"),
}


def _looks_like_at_work(text: str) -> bool:
    lower = text.casefold()
    return (
        "client statement" in lower
        and "e*trade is a business of morgan stanley" in lower
        and "morgan stanley smith barney llc" in lower
        and _AT_WORK_PERIOD_RE.search(text) is not None
    )


def _detect_at_work(head_text: str) -> tuple[bool, str]:
    lower = head_text.casefold()
    required = {
        "CLIENT STATEMENT": "client statement" in lower,
        "E*TRADE/Morgan Stanley legal marker": "e*trade is a business of morgan stanley" in lower,
        "Morgan Stanley Smith Barney LLC": "morgan stanley smith barney llc" in lower,
        "For the Period": _AT_WORK_PERIOD_RE.search(head_text) is not None,
    }
    missing = [label for label, found in required.items() if not found]
    if missing:
        return False, "missing E*TRADE at Work marker(s): " + ", ".join(missing)
    return True, "found E*TRADE Morgan Stanley at Work Client Statement and statement period"


def detect(head_text: str) -> tuple[bool, str]:
    matched, reason = _detect_at_work(head_text)
    if matched:
        return matched, reason
    legacy_matched, legacy_reason = core.detect_profile(head_text, PROFILE_KEY)
    if legacy_matched:
        return legacy_matched, legacy_reason
    return False, f"{reason}; {legacy_reason}"


def _amount(raw: str) -> float:
    value = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    parsed = float(value)
    return -parsed if negative else parsed


def _period(text: str) -> tuple[date, date]:
    match = _AT_WORK_PERIOD_RE.search(text)
    if not match:
        raise parser_common.ParserDiagnosticError(
            "E*TRADE at Work statement period not found",
            code="PARSER_STATEMENT_DATE_INVALID",
            stage="metadata",
            missing_fields=("statementPeriod",),
        )
    end_year = int(match.group("end_year"))
    start_month = _MONTH_NUMBERS[match.group("start_month").casefold()]
    end_month = _MONTH_NUMBERS[match.group("end_month").casefold()]
    start_year = end_year - 1 if start_month > end_month else end_year
    return (
        date(start_year, start_month, int(match.group("start_day"))),
        date(end_year, end_month, int(match.group("end_day"))),
    )


def _metadata(text: str) -> tuple[str, str, str]:
    match = _AT_WORK_ACCOUNT_RE.search(text)
    if not match:
        raise parser_common.ParserDiagnosticError(
            "E*TRADE at Work account identifier not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="metadata",
            missing_fields=("accountIdentifier",),
        )
    provider_id = match.group("account")
    return common.last4_digits(provider_id), "Brokerage", provider_id


def _first_period_cell(line: str, label: str) -> float | None:
    match = re.match(
        rf"^{re.escape(label)}\s+(?P<value>{_MONEY}|—|--|-)(?:\s|$)",
        line,
        re.I,
    )
    if not match:
        return None
    raw = match.group("value")
    return 0.0 if raw in _ZERO_CELL else _amount(raw)


def _summary(lines: list[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in lines:
        for key, (label, _) in _AT_WORK_SUMMARY_LABELS.items():
            if key in values:
                continue
            value = _first_period_cell(line, label)
            if value is not None:
                values[key] = value

    missing = [
        field_id
        for key, (_, field_id) in _AT_WORK_SUMMARY_LABELS.items()
        if key not in values
    ]
    if missing:
        raise parser_common.ParserDiagnosticError(
            "missing E*TRADE at Work account-summary controls",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="summary",
            missing_fields=missing,
        )

    core._require_close(
        "E*TRADE at Work net credits/debits/transfers",
        values["credits"] + values["debits"] + values["security_transfers"],
        values["net_transfers"],
        "summary",
    )
    core._require_close(
        "E*TRADE at Work account summary",
        values["beginning"] + values["net_transfers"] + values["market_change"],
        values["ending"],
        "summary",
    )
    return values


def _holdings(
    lines: list[str], account: str, account_type: str, provider_id: str, statement_date: str
) -> tuple[list[dict], float]:
    active = False
    rows: list[dict] = []
    printed_total: float | None = None
    for line in lines:
        if line == "HOLDINGS":
            active = True
            continue
        if not active:
            continue
        if line.startswith("MORGAN STANLEY BANK N.A."):
            match = _DOLLAR_MONEY_RE.search(line)
            if match:
                rows.append(
                    {
                        "symbol": "CASH",
                        "description": "Morgan Stanley Bank N.A.",
                        "current_value": _amount(match.group()),
                        "type": "Cash",
                        "is_cash_equivalent": True,
                        "currency_code": "USD",
                        "price_as_of": statement_date,
                        "account": account,
                        "accountType": account_type,
                        "provider_account_id": provider_id,
                    }
                )
            continue
        if line.startswith("TOTAL VALUE"):
            matches = _DOLLAR_MONEY_RE.findall(line)
            if matches:
                printed_total = _amount(matches[-1])
                break

    if printed_total is None:
        raise parser_common.ParserDiagnosticError(
            "E*TRADE at Work holdings total not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("totalValue",),
        )
    if not rows:
        raise parser_common.ParserDiagnosticError(
            "E*TRADE at Work cash holding not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("cashHolding",),
        )
    core._require_close(
        "E*TRADE at Work holdings",
        sum(row["current_value"] for row in rows),
        printed_total,
        "holdings",
    )
    return rows, printed_total


def _parse_at_work(pages_text: list[str]) -> dict:
    text = "\n".join(pages_text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    context = diagnostic_helpers.diagnostic_context(
        pages_text,
        section_markers=("CLIENT STATEMENT", "Account Summary", "CASH FLOW", "HOLDINGS"),
        known_labels=tuple(label for label, _ in _AT_WORK_SUMMARY_LABELS.values())
        + ("MORGAN STANLEY BANK N.A.", "TOTAL VALUE"),
        extra_counts={
            "summaryComponents": sum(
                1
                for label, _ in _AT_WORK_SUMMARY_LABELS.values()
                if any(_first_period_cell(line, label) is not None for line in lines)
            ),
        },
    )
    try:
        _, end = _period(text)
        account, account_type, provider_id = _metadata(text)
        summary = _summary(lines)
        holdings, holdings_total = _holdings(
            lines, account, account_type, provider_id, end.isoformat()
        )
        context["counts"]["holdingsParsed"] = len(holdings)
        context["counts"]["transactionsParsed"] = 0
        core._require_close(
            "E*TRADE at Work ending holdings",
            holdings_total,
            summary["ending"],
            "holdings",
        )
        if not core._close(summary["net_transfers"], 0.0):
            raise parser_common.ParserDiagnosticError(
                "E*TRADE at Work statement has nonzero period activity without itemized rows",
                code="PARSER_ACTIVITY_ROWS_NOT_FOUND",
                stage="activity",
            )
    except ValueError as error:
        raise parser_common.enrich_parser_error(error, **context) from error

    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": [],
        },
    }


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    if _looks_like_at_work(text):
        return _parse_at_work(pages_text)
    return core.parse_profile(pages_text, pdf_path, PROFILE_KEY)
