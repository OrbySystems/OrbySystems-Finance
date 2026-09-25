"""Morgan Stanley Global Stock Plan Services quarterly statements.

This layout is distinct from Morgan Stanley Wealth Management client statements.
It reports one issuer, a share balance, releases, sales, and disbursements.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

import parser_common
from institutions import common


KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
INSTITUTION = "Morgan Stanley Global Stock Plan Services"
PARSER_REVISION = 1

DIAGNOSTIC_MARKERS = {
    "statement_title": "STATEMENT For the Period",
    "holdings_summary": "Share Purchase and Holdings Summary",
    "activity": "SHARE PURCHASE AND HOLDINGS",
}
DIAGNOSTIC_FIELDS = {
    "openingShares": "Number of Shares",
    "sharePrice": "Share Price",
    "shareValue": "Share Value",
    "cashValue": "Cash Value",
    "unsettledCash": "Net Unsettled Cash",
    "endingValue": "Total Account Value",
}

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)
_PERIOD_RE = re.compile(
    rf"STATEMENT\s+For the Period\s+(?P<start_month>{_MONTHS})\s+"
    rf"(?P<start_day>\d{{1,2}})\s+(?:\(cid:\d+\)|[-–—])\s+"
    rf"(?P<end_month>{_MONTHS})\s+(?P<end_day>\d{{1,2}}),?\s+"
    rf"(?P<end_year>\d{{4}})",
    re.I,
)
_ACCOUNT_RE = re.compile(r"\bAccount Number:\s*(MS[A-Z0-9-]+)\b", re.I)
_ISSUER_RE = re.compile(r"^Issuer Description:\s*(.+?)\s+P\.O\. Box\b", re.I | re.M)
_NUMBER = r"\$?\(?-?[\d,]+(?:\.\d+)?\)?"
_DATE_ROW_RE = re.compile(r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<body>.+)$")
_RELEASE_RE = re.compile(rf"^Release\s+(?P<quantity>{_NUMBER})\s+(?P<price>{_NUMBER})$", re.I)
_SALE_RE = re.compile(
    rf"^Sale\s+(?P<quantity>{_NUMBER})\s+(?P<price>{_NUMBER})\s+"
    rf"(?P<gross>{_NUMBER})\s+(?P<fees>{_NUMBER})\s+(?P<net>{_NUMBER})$",
    re.I,
)
_DISBURSEMENT_RE = re.compile(rf"^Proceeds Disbursement\s+(?P<amount>{_NUMBER})$", re.I)
_SUMMARY_LABELS = (
    "Number of Shares",
    "Share Price",
    "Share Value",
    "Cash Value",
    "Net Unsettled Cash",
    "Total Account Value",
)


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.casefold()
    required = (
        "morgan stanley smith barney llc",
        "global stock plan services",
        "share purchase and holdings summary",
        "share purchase and holdings",
        "number of shares",
        "total account value",
    )
    if not all(marker in lower for marker in required):
        return False, "missing Morgan Stanley stock plan section markers"
    if not _PERIOD_RE.search(head_text) or not _ACCOUNT_RE.search(head_text):
        return False, "missing Morgan Stanley stock plan period or account number"
    return True, "found Morgan Stanley stock plan statement, summary, and activity"


def _decimal(raw: str) -> Decimal:
    value = raw.replace("$", "").replace(",", "").strip()
    if value.startswith("(") and value.endswith(")"):
        return -Decimal(value[1:-1])
    return Decimal(value)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _require_close(label: str, calculated: Decimal, printed: Decimal, tolerance: Decimal = Decimal("0.02")) -> None:
    if abs(calculated - printed) > tolerance:
        raise ValueError(f"Morgan Stanley stock plan {label} does not reconcile")


def _period(text: str) -> tuple[date, date]:
    match = _PERIOD_RE.search(text)
    if not match:
        raise ValueError("Morgan Stanley stock plan statement period missing")
    end = date(
        int(match["end_year"]),
        datetime.strptime(match["end_month"], "%B").month,
        int(match["end_day"]),
    )
    start_month = datetime.strptime(match["start_month"], "%B").month
    start_year = end.year - (start_month > end.month)
    start = date(start_year, start_month, int(match["start_day"]))
    if start > end:
        raise ValueError("Morgan Stanley stock plan period is reversed")
    return start, end


def _summary(lines: list[str]) -> dict[str, tuple[Decimal, Decimal]]:
    try:
        start = next(i for i, line in enumerate(lines) if line.lower() == "share purchase and holdings summary")
    except StopIteration as exc:
        raise ValueError("Morgan Stanley stock plan holdings summary missing") from exc
    values: dict[str, tuple[Decimal, Decimal]] = {}
    for line in lines[start + 1 :]:
        if line.startswith("The quarter-end market closing price"):
            break
        for label in _SUMMARY_LABELS:
            match = re.fullmatch(rf"{re.escape(label)}\s+({_NUMBER})\s+({_NUMBER})", line, re.I)
            if match:
                if label in values:
                    raise ValueError("duplicate Morgan Stanley stock plan summary row")
                values[label] = (_decimal(match[1]), _decimal(match[2]))
                break
    if set(values) != set(_SUMMARY_LABELS):
        raise ValueError("Morgan Stanley stock plan summary is incomplete")
    for column in (0, 1):
        _require_close(
            "share value",
            _money(values["Number of Shares"][column] * values["Share Price"][column]),
            values["Share Value"][column],
        )
        _require_close(
            "account value",
            values["Share Value"][column] + values["Cash Value"][column] + values["Net Unsettled Cash"][column],
            values["Total Account Value"][column],
        )
    return values


def _activity(lines: list[str], start: date, end: date, issuer: str, account: str, provider_id: str) -> tuple[list[dict], Decimal, Decimal, Decimal, Decimal]:
    try:
        section = next(i for i, line in enumerate(lines) if line.upper() == "SHARE PURCHASE AND HOLDINGS")
    except StopIteration as exc:
        raise ValueError("Morgan Stanley stock plan activity section missing") from exc
    rows: list[dict] = []
    releases = sales = sale_proceeds = disbursements = Decimal("0")
    for line in lines[section + 1 :]:
        if line.startswith("Sell Transactions are provided"):
            break
        match = _DATE_ROW_RE.match(line)
        if not match:
            continue
        raw_date = match["date"]
        fmt = "%m/%d/%y" if len(raw_date.split("/")[-1]) == 2 else "%m/%d/%Y"
        when = datetime.strptime(raw_date, fmt).date()
        if not start <= when <= end:
            raise ValueError("Morgan Stanley stock plan activity date outside statement period")
        body = match["body"]
        common_row = {
            "date": when.isoformat(),
            "account": account,
            "accountType": "Brokerage",
            "provider_account_id": provider_id,
            "currency_code": "USD",
        }
        if release := _RELEASE_RE.fullmatch(body):
            quantity, price = _decimal(release["quantity"]), _decimal(release["price"])
            if quantity <= 0 or price <= 0:
                raise ValueError("invalid Morgan Stanley stock plan release")
            releases += quantity
            rows.append({
                **common_row,
                "description": f"Release of {issuer} shares",
                "action": "Release",
                "transaction_type": "transfer_in",
                "symbol": issuer,
                "quantity": float(quantity),
                "price": float(price),
                "amount": float(_money(quantity * price)),
            })
        elif sale := _SALE_RE.fullmatch(body):
            quantity, price, gross, fees, net = (_decimal(sale[key]) for key in ("quantity", "price", "gross", "fees", "net"))
            if quantity <= 0 or price <= 0 or gross <= 0 or fees < 0 or net < 0:
                raise ValueError("invalid Morgan Stanley stock plan sale")
            _require_close("sale gross", _money(quantity * price), gross)
            _require_close("sale net", gross - fees, net)
            sales += quantity
            sale_proceeds += net
            rows.append({
                **common_row,
                "description": f"Sale of {issuer} shares",
                "action": "Sale",
                "transaction_type": "sell",
                "symbol": issuer,
                "quantity": float(quantity),
                "price": float(price),
                "commission_and_fees": float(fees),
                "amount": float(net),
            })
        elif disbursement := _DISBURSEMENT_RE.fullmatch(body):
            amount = _decimal(disbursement["amount"])
            if amount >= 0:
                raise ValueError("invalid Morgan Stanley stock plan disbursement")
            disbursements += amount
            rows.append({
                **common_row,
                "description": "Proceeds disbursement",
                "action": "Proceeds Disbursement",
                "transaction_type": "withdrawal",
                "amount": float(amount),
            })
        else:
            raise ValueError("unsupported Morgan Stanley stock plan activity row")
    return rows, releases, sales, sale_proceeds, disbursements


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    lines = [line.strip() for line in text.splitlines()]
    start, end = _period(text)
    accounts = set(_ACCOUNT_RE.findall(text))
    if len(accounts) != 1:
        raise ValueError("Morgan Stanley stock plan account number missing or inconsistent")
    provider_id = accounts.pop()
    account = common.last4_digits(provider_id)
    issuer_match = _ISSUER_RE.search(text)
    if not issuer_match:
        raise ValueError("Morgan Stanley stock plan issuer description missing")
    issuer = issuer_match[1].strip()
    summary = _summary(lines)
    rows, releases, sales, sale_proceeds, disbursements = _activity(
        lines, start, end, issuer, account, provider_id
    )
    _require_close(
        "share movement",
        summary["Number of Shares"][0] + releases - sales,
        summary["Number of Shares"][1],
        Decimal("0.0005"),
    )
    _require_close(
        "cash movement",
        summary["Cash Value"][0] + summary["Net Unsettled Cash"][0]
        + sale_proceeds + disbursements,
        summary["Cash Value"][1] + summary["Net Unsettled Cash"][1],
    )
    holding = {
        "symbol": issuer,
        "description": issuer,
        "type": "Stock",
        "quantity": float(summary["Number of Shares"][1]),
        "price": float(summary["Share Price"][1]),
        "current_value": float(summary["Share Value"][1]),
        "account": account,
        "accountType": "Brokerage",
        "provider_account_id": provider_id,
        "currency_code": "USD",
    }
    holdings = [holding]
    closing_cash = summary["Cash Value"][1] + summary["Net Unsettled Cash"][1]
    if closing_cash:
        holdings.append({
            "symbol": "CASH",
            "description": "Cash and unsettled cash",
            "type": "Cash",
            "current_value": float(closing_cash),
            "is_cash_equivalent": True,
            "account": account,
            "accountType": "Brokerage",
            "provider_account_id": provider_id,
            "currency_code": "USD",
        })
    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "tables": {"brokerage_holdings": holdings, "brokerage_transactions": rows},
    }
