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
SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
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
PARSER_REVISION = 3

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
_AT_WORK_NUMERIC_PERIOD_RE = re.compile(
    r"\((?P<start_month>\d{1,2})/(?P<start_day>\d{1,2})/(?P<start_year>\d{2,4})\s*"
    r"-\s*(?P<end_month>\d{1,2})/(?P<end_day>\d{1,2})/(?P<end_year>\d{2,4})\)"
)
_AT_WORK_ACCOUNT_RE = re.compile(
    r"^(?:Account Summary|Account Detail)\s+(?P<account>\d[\d-]{4,})\b",
    re.I | re.M,
)
_MONEY = r"(?:\$?\(\s*[\d,]+\.\d{2}\s*\)|\(\s*\$?[\d,]+\.\d{2}\s*\)|-?\$?-?[\d,]+\.\d{2})"
_DOLLAR_MONEY_RE = re.compile(r"\$\(?\s*[\d,]+\.\d{2}\s*\)?")
_ZERO_CELL = {"--", "—", "-"}
_REDACTED_TOKEN_RE = re.compile(r"^(?:x+|\$?\(?0[0,]*0*\.00\)?)$", re.I)
_POSITION_RE = re.compile(
    rf"^(?P<description>.+?)\s+(?P<symbol>[A-Z][A-Z0-9.\-]{{0,9}})\s+"
    rf"(?P<quantity>[\d,]+(?:\.\d+)?)\s+(?P<price>{_MONEY})\s+"
    rf"(?P<cost>{_MONEY})\s+(?P<market>{_MONEY})(?:\s+.*)?$"
)
_ACTIVITY_RE = re.compile(
    rf"^(?P<activity_date>\d{{1,2}}/\d{{1,2}})(?:\s+(?P<settlement_date>\d{{1,2}}/\d{{1,2}}))?\s+"
    rf"(?P<body>.+?)\s+(?P<amount>{_MONEY})$"
)
_ACTIVITY_TYPES = (
    ("Qualified Dividend", "dividend"),
    ("Dividend", "dividend"),
    ("Interest", "interest"),
    ("Capital Gain", "capital_gain"),
    ("Buy", "buy"),
    ("Sell", "sell"),
    ("Purchase", "buy"),
    ("Sale", "sell"),
    ("Electronic Transfer", "internal_transfer"),
    ("Journal", "internal_transfer"),
    ("Deposit", "deposit"),
    ("Withdrawal", "withdrawal"),
    ("Fee", "fee"),
)

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
    )


def _detect_at_work(head_text: str) -> tuple[bool, str]:
    lower = head_text.casefold()
    required = {
        "CLIENT STATEMENT": "client statement" in lower,
        "E*TRADE/Morgan Stanley legal marker": "e*trade is a business of morgan stanley" in lower,
        "Morgan Stanley Smith Barney LLC": "morgan stanley smith barney llc" in lower,
    }
    missing = [label for label, found in required.items() if not found]
    if missing:
        return False, "missing E*TRADE at Work marker(s): " + ", ".join(missing)
    return True, "found E*TRADE Morgan Stanley at Work Client Statement"


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
    if match:
        end_year = int(match.group("end_year"))
        start_month = _MONTH_NUMBERS[match.group("start_month").casefold()]
        end_month = _MONTH_NUMBERS[match.group("end_month").casefold()]
        start_year = end_year - 1 if start_month > end_month else end_year
        return (
            date(start_year, start_month, int(match.group("start_day"))),
            date(end_year, end_month, int(match.group("end_day"))),
        )
    numeric = _AT_WORK_NUMERIC_PERIOD_RE.search(text)
    if numeric:
        year = lambda raw: 2000 + int(raw) if len(raw) == 2 else int(raw)
        return (
            date(year(numeric.group("start_year")), int(numeric.group("start_month")), int(numeric.group("start_day"))),
            date(year(numeric.group("end_year")), int(numeric.group("end_month")), int(numeric.group("end_day"))),
        )
    raise parser_common.ParserDiagnosticError(
        "E*TRADE at Work statement period not found",
        code="PARSER_STATEMENT_DATE_INVALID",
        stage="metadata",
        missing_fields=("statementPeriod",),
    )


def _metadata(text: str) -> tuple[str, str, str]:
    match = _AT_WORK_ACCOUNT_RE.search(text)
    if not match:
        # Redacted statements commonly mask this entire field. The row schema
        # permits an unknown account; retain the statement data and surface
        # field presence through diagnostics instead of inventing an ID.
        return "", "Brokerage", ""
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
        if line.startswith(("MORGAN STANLEY BANK N.A.", "MORGAN STANLEY PRIVATE BANK NA")):
            match = _DOLLAR_MONEY_RE.search(line)
            if match and not _REDACTED_TOKEN_RE.match(match.group().replace(" ", "")):
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
        position = _POSITION_RE.match(line)
        if position and not any(
            "x" in position.group(name).casefold()
            for name in ("quantity", "price", "cost", "market")
        ):
            rows.append({
                "symbol": position.group("symbol"),
                "description": position.group("description").strip(),
                "quantity": float(position.group("quantity").replace(",", "")),
                "price": _amount(position.group("price")),
                "cost_basis_total": _amount(position.group("cost")),
                "current_value": _amount(position.group("market")),
                "type": "Security",
                "currency_code": "USD",
                "price_as_of": statement_date,
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            })
            continue
        if line.startswith("TOTAL VALUE"):
            matches = _DOLLAR_MONEY_RE.findall(line)
            if matches:
                # Full holdings totals print Total Cost, Market Value,
                # Gain/(Loss), and sometimes Estimated Annual Income. Market
                # Value is the second money cell; cash-only layouts have one.
                printed_total = _amount(matches[1] if len(matches) >= 2 else matches[0])
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


def _activity_date(raw: str, period_start: date, period_end: date) -> str:
    month, day = (int(value) for value in raw.split("/"))
    year = period_end.year
    if period_start.year != period_end.year and month >= period_start.month:
        year = period_start.year
    parsed = date(year, month, day)
    if parsed < period_start or parsed > period_end:
        raise ValueError("E*TRADE activity date falls outside statement period")
    return parsed.isoformat()


def _transactions(
    lines: list[str], account: str, account_type: str, provider_id: str,
    period_start: date, period_end: date,
) -> list[dict]:
    """Parse the primary cash-flow activity table.

    The later MMF/Bank Deposit Program table is the cash-side reflection of
    these events and is deliberately not emitted again.
    """
    active = False
    rows: list[dict] = []
    for line in lines:
        if line == "CASH FLOW ACTIVITY BY DATE":
            active = True
            continue
        if not active:
            continue
        if line.startswith(("NET CREDITS/(DEBITS)", "MONEY MARKET FUND (MMF)")):
            break
        match = _ACTIVITY_RE.match(line)
        if not match:
            continue
        body = match.group("body").strip()
        classified = next(
            ((label, txn_type) for label, txn_type in _ACTIVITY_TYPES if body.casefold().startswith(label.casefold())),
            None,
        )
        if not classified:
            raise parser_common.ParserDiagnosticError(
                "unclassified E*TRADE activity row",
                code="PARSER_UNCLASSIFIED_ROW",
                stage="activity",
            )
        action, txn_type = classified
        description = body[len(action):].strip() or action
        amount_raw = match.group("amount")
        if _REDACTED_TOKEN_RE.match(amount_raw.replace(" ", "")):
            continue
        rows.append({
            "date": _activity_date(match.group("activity_date"), period_start, period_end),
            "description": description,
            "amount": _amount(amount_raw),
            "action": action,
            "transaction_type": txn_type,
            "account": account,
            "accountType": account_type,
            "provider_account_id": provider_id,
        })
    return rows


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
        start, end = _period(text)
        account, account_type, provider_id = _metadata(text)
        summary = _summary(lines)
        holdings, holdings_total = _holdings(
            lines, account, account_type, provider_id, end.isoformat()
        )
        transactions = _transactions(
            lines, account, account_type, provider_id, start, end
        )
        context["counts"]["holdingsParsed"] = len(holdings)
        context["counts"]["transactionsParsed"] = len(transactions)
        core._require_close(
            "E*TRADE at Work ending holdings",
            holdings_total,
            summary["ending"],
            "holdings",
        )
        flow_total = sum(
            row["amount"] for row in transactions
            if row.get("transaction_type") in parser_common.FLOW_TRANSACTION_TYPES
        )
        if not core._close(summary["net_transfers"], flow_total):
            raise parser_common.ParserDiagnosticError(
                "E*TRADE at Work net transfers do not reconcile itemized flow activity",
                code=(
                    "PARSER_ACTIVITY_ROWS_NOT_FOUND"
                    if not transactions else "PARSER_RECONCILIATION_FAILED"
                ),
                stage="activity" if not transactions else "validation",
            )
    except ValueError as error:
        raise parser_common.enrich_parser_error(error, **context) from error

    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": transactions,
        },
    }


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    if _looks_like_at_work(text):
        return _parse_at_work(pages_text)
    return core.parse_profile(pages_text, pdf_path, PROFILE_KEY)
