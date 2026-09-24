"""Edward Jones retail investment account statement parser.

This provisional parser targets the current statement family documented in
Edward Jones's first-party ``Understanding my statement`` guide.  It handles
the Value Summary, Asset Details, chronological Investment and Other Activity
by Date, Summary of Activity cash controls, and realized gain/loss detail.

The guide documents several user-selectable layouts.  This module deliberately
claims only statements carrying the chronological activity layout and the
cost-basis Asset Details columns it knows how to reconcile.  It must be
validated against a safely redacted production statement before the coverage
is considered final.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import parser_common

from . import common
from . import diagnostic_helpers


KIND = parser_common.KIND_BROKERAGE
INSTITUTION = "Edward Jones"
SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
DIAGNOSTIC_MARKERS = {
    "account_summary": "Value Summary",
    "holdings": "Asset Details",
    "activity_summary": "Summary of Activity",
    "activity": "Investment and Other Activity by Date",
    "realized_gains": "Realized Gain/Loss",
}
DIAGNOSTIC_FIELDS = {
    "beginningValue": "Beginning Value",
    "assetsAdded": "Assets Added to Account",
    "assetsWithdrawn": "Assets Withdrawn from Account",
    "fees": "Fees and Charges",
    "changeInValue": "Change in Value",
    "endingValue": "Ending Value",
    "totalAccountValue": "Total Account Value",
    "beginningCash": "Beginning Balance of Cash",
    "additions": "Additions to Cash",
    "subtractions": "Subtractions from Cash",
    "endingCash": "Ending Balance of Cash",
    "realizedGainTotal": "Summary",
}
DIAGNOSTIC_SIGNALS = diagnostic_helpers.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = diagnostic_helpers.DIAGNOSTIC_COUNTS
DIAGNOSTIC_TERMS = diagnostic_helpers.DIAGNOSTIC_TERMS
PARSER_REVISION = 1

_MONTHS = (
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December"
)
_PERIOD_RE = re.compile(
    rf"Statement Period\s*:?[ \t]*(?P<start>(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})\s*"
    rf"[-–]\s*(?P<end>(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})",
    re.I,
)
_ACCOUNT_RE = re.compile(r"Account (?:Number|#)\s*:?[ \t]*([*Xx\d][*Xx\d -]{3,24})", re.I)
_ACCOUNT_TYPE_RE = re.compile(r"Account Type\s*:?[ \t]*(.+)$", re.I | re.M)
_MONEY = r"(?:\(\s*\$?[\d,]+\.\d{2}\s*\)|-?\$?-?[\d,]+\.\d{2})"
_MONEY_RE = re.compile(_MONEY)
_MD_RE = re.compile(r"^\d{2}/\d{2}$")

_PAGE_FURNITURE = (
    "SYNTHETIC TEST DATA",
    "NOT AN OFFICIAL",
    "EDWARD JONES",
    "ACCOUNT STATEMENT",
    "Statement Period",
    "Account Number",
    "Account Type",
    "Member SIPC",
    "Page ",
)


def detect(head_text: str) -> tuple[bool, str]:
    """Recognize a statement, not the educational guide or a sibling form."""
    lower = head_text.lower()
    missing = []
    if "edward jones" not in lower:
        missing.append("Edward Jones")
    if "member sipc" not in lower:
        missing.append("Member SIPC")
    if not _PERIOD_RE.search(head_text):
        missing.append("Statement Period")
    if not _ACCOUNT_RE.search(head_text):
        missing.append("account identifier")
    if "value summary" not in lower:
        missing.append("Value Summary")
    if "asset details" not in lower:
        missing.append("Asset Details")
    if missing:
        return False, "missing Edward Jones statement marker(s): " + ", ".join(missing)
    if "understanding my statement" in lower and "account statement" not in lower:
        return False, "Edward Jones educational guide is not an account statement"
    return True, "found Edward Jones statement period, account identifier, Value Summary, and Asset Details"


def _amount(raw: str) -> float:
    value = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    if value in {"-", "--", "—"}:
        return 0.0
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    parsed = float(value)
    return -parsed if negative else parsed


def _optional_amount(raw: str) -> float | None:
    return None if raw.strip() in {"-", "--", "—"} else _amount(raw)


def _close(a: float, b: float, tolerance: float = 0.02) -> bool:
    return abs(a - b) <= tolerance


def _require_close(label: str, parsed: float, printed: float) -> None:
    if not _close(parsed, printed):
        lower = label.casefold()
        if "holding" in lower or "asset details" in lower:
            stage = "holdings"
        elif "realized" in lower:
            stage = "realized_gains"
        elif "activity" in lower or "cash" in lower:
            stage = "activity"
        else:
            stage = "summary"
        raise diagnostic_helpers.reconciliation_error(
            f"{label} does not reconcile: parsed {parsed:.2f}, printed {printed:.2f}",
            parsed,
            printed,
            stage,
        )


def _period(text: str) -> tuple[date, date]:
    match = _PERIOD_RE.search(text)
    if not match:
        raise ValueError("Edward Jones statement period not found")
    return tuple(
        datetime.strptime(match.group(name), "%B %d, %Y").date()
        for name in ("start", "end")
    )  # type: ignore[return-value]


def _resolve_date(month_day: str, start: date, end: date) -> str:
    month, day = (int(piece) for piece in month_day.split("/"))
    candidates = []
    for year in {start.year - 1, start.year, end.year, end.year + 1}:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = 0 if start <= candidate <= end else min(
            abs((candidate - start).days), abs((candidate - end).days)
        )
        candidates.append((distance, candidate))
    if not candidates:
        raise ValueError(f"invalid Edward Jones activity date {month_day!r}")
    return min(candidates)[1].isoformat()


def _account_metadata(text: str) -> tuple[str, str, str]:
    match = _ACCOUNT_RE.search(text)
    if not match:
        raise ValueError("Edward Jones account number not found")
    provider_id = match.group(1).strip()
    account = common.last4_digits(provider_id)
    title_match = _ACCOUNT_TYPE_RE.search(text)
    title = title_match.group(1).strip() if title_match else "Brokerage"
    account_type = common.classify_account_type(title, "Brokerage")
    return account, account_type, provider_id


_SUMMARY_LABELS = (
    "Beginning Value",
    "Assets Added to Account",
    "Assets Withdrawn from Account",
    "Fees and Charges",
    "Change in Value",
    "Ending Value",
)


def _value_summary(lines: list[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    active = False
    for raw in lines:
        line = raw.strip()
        if line == "Value Summary":
            active = True
            continue
        if active and line.startswith(("Summary of Assets", "Asset Details")):
            break
        if not active:
            continue
        for label in _SUMMARY_LABELS:
            if not line.startswith(label):
                continue
            amounts = _MONEY_RE.findall(line[len(label) :])
            if amounts:
                value = _amount(amounts[0])
                # Some layouts print withdrawals/fees as unsigned magnitudes;
                # their labels still define the direction unambiguously.
                if label in {"Assets Withdrawn from Account", "Fees and Charges"} and value > 0:
                    value = -value
                values[label] = value
            break
    missing = set(_SUMMARY_LABELS) - set(values)
    if missing:
        raise ValueError(f"missing Edward Jones Value Summary total(s): {sorted(missing)}")
    _require_close(
        "Value Summary",
        values["Beginning Value"]
        + values["Assets Added to Account"]
        + values["Assets Withdrawn from Account"]
        + values["Fees and Charges"]
        + values["Change in Value"],
        values["Ending Value"],
    )
    return values


def _ignored(line: str) -> bool:
    return not line or any(line.startswith(prefix) for prefix in _PAGE_FURNITURE)


_ASSET_CATEGORIES = {
    "Stocks": "Stock",
    "Mutual Funds": "Mutual Fund",
    "Exchange Traded Funds": "ETF",
    "Bonds": "Fixed Income",
    "Options": "Option",
}


def _parse_holdings(
    lines: list[str], account: str, account_type: str, provider_id: str
) -> tuple[list[dict], float]:
    holdings: list[dict] = []
    active = False
    category = ""
    printed_total: float | None = None
    printed_cash: float | None = None
    last_holding: dict | None = None
    row_re = re.compile(
        rf"^(?P<description>.+?)\s+(?P<symbol>[A-Z0-9./-]{{1,16}})\s+"
        rf"(?P<price>{_MONEY})\s+(?P<quantity>-?[\d,]+(?:\.\d+)?)\s+"
        rf"(?P<cost>{_MONEY}|--|—)\s+(?P<gain>{_MONEY}|--|—)\s+(?P<value>{_MONEY})$"
    )
    cash_re = re.compile(rf"^Cash\s+({_MONEY})$", re.I)

    for raw in lines:
        line = raw.strip()
        if line.startswith("Asset Details"):
            active, last_holding = True, None
            continue
        if not active:
            continue
        if line.startswith("Investment and Other Activity") or line == "Summary of Activity":
            break
        if line in _ASSET_CATEGORIES:
            category, last_holding = line, None
            continue
        if line.startswith("Cash, money market funds and insured bank deposit"):
            category, last_holding = "Cash", None
            continue
        if line.startswith("Total cash, money market"):
            amounts = _MONEY_RE.findall(line)
            if amounts:
                printed_cash = _amount(amounts[-1])
            last_holding = None
            continue
        total_match = re.match(rf"^Total Account Value\s+({_MONEY})$", line, re.I)
        if total_match:
            printed_total = _amount(total_match.group(1))
            last_holding = None
            continue
        if _ignored(line) or line.startswith(("Assets held at", "Description ", "Price ", "Unrealized ")):
            continue

        cash_match = cash_re.match(line)
        if cash_match and category == "Cash":
            row = {
                "symbol": "CASH",
                "description": "Cash",
                "current_value": _amount(cash_match.group(1)),
                "type": "Cash",
                "is_cash_equivalent": True,
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            holdings.append(row)
            last_holding = row
            continue

        match = row_re.match(line)
        if match:
            symbol = match.group("symbol")
            row = {
                "symbol": symbol,
                "description": match.group("description"),
                "price": _amount(match.group("price")),
                "quantity": _amount(match.group("quantity")),
                "cost_basis_total": _optional_amount(match.group("cost")),
                "current_value": _amount(match.group("value")),
                "type": _ASSET_CATEGORIES.get(category, category or "Security"),
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            if re.fullmatch(r"[A-Z0-9]{9}", symbol):
                row.update({"security_id": symbol, "security_id_type": "CUSIP", "cusip": symbol})
            holdings.append(row)
            last_holding = row
            continue

        # A prose-only physical line immediately below a holding is the
        # wrapped remainder of its name/additional details.
        if last_holding and not re.search(r"\d", line) and "Total" not in line:
            last_holding["description"] = f"{last_holding['description']} {line}".strip()

    if printed_total is None:
        raise parser_common.ParserDiagnosticError(
            "Edward Jones Total Account Value not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("totalAccountValue",),
        )
    if printed_cash is not None:
        cash_value = sum(h.get("current_value") or 0.0 for h in holdings if h["symbol"] == "CASH")
        _require_close("cash holdings", cash_value, printed_cash)
    _require_close("Asset Details", sum(h.get("current_value") or 0.0 for h in holdings), printed_total)
    return holdings, printed_total


_ACTIONS = (
    ("Transfer Out", "Transfer Out", "transfer_out"),
    ("Transfer In", "Transfer In", "transfer_in"),
    ("Advisory Fee", "Fee", "fee"),
    ("Reinvestment", "Reinvestment", "buy"),
    ("Withdrawal", "Withdrawal", "withdrawal"),
    ("Deposit", "Deposit", "deposit"),
    ("Dividend", "Dividend", "dividend"),
    ("Interest", "Interest", "interest"),
    ("Buy", "Buy", "buy"),
    ("Sell", "Sell", "sell"),
)
_SECURITY_ACTIONS = {"Dividend", "Reinvestment", "Buy", "Sell"}


def _activity_controls(lines: list[str]) -> dict[str, float]:
    labels = {
        "Beginning Balance of Cash, Money Market Funds and Insured Bank Deposit": "beginning",
        "Total Additions": "additions",
        "Total Subtractions": "subtractions",
        "Ending Balance of Cash, Money Market Funds and Insured Bank Deposit": "ending",
    }
    values: dict[str, float] = {}
    active = False
    for raw in lines:
        line = raw.strip()
        if line == "Summary of Activity":
            active = True
            continue
        if active and line.startswith("Investment and Other Activity"):
            break
        if not active:
            continue
        for label, key in labels.items():
            if line.startswith(label):
                amounts = _MONEY_RE.findall(line[len(label) :])
                if amounts:
                    value = _amount(amounts[-1])
                    if key == "subtractions" and value > 0:
                        value = -value
                    values[key] = value
                break
    missing = set(labels.values()) - set(values)
    if missing:
        raise ValueError(f"missing Edward Jones Summary of Activity total(s): {sorted(missing)}")
    _require_close("Summary of Activity", values["beginning"] + values["additions"] + values["subtractions"], values["ending"])
    return values


def _parse_transactions(
    lines: list[str], start: date, end: date, account: str, account_type: str, provider_id: str
) -> list[dict]:
    transactions: list[dict] = []
    active = False
    last_transaction: dict | None = None
    row_re = re.compile(rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<body>.+?)\s+(?P<amount>{_MONEY})$")

    for raw in lines:
        line = raw.strip()
        if line.startswith("Investment and Other Activity by Date"):
            active, last_transaction = True, None
            continue
        if active and line.startswith(("Detail of Realized Gain/Loss", "Summary of Realized Gain/Loss")):
            active, last_transaction = False, None
            continue
        if not active:
            continue
        if _ignored(line) or line.startswith(("Date ", "Total Activity")):
            continue
        match = row_re.match(line)
        if match:
            body = match.group("body").strip()
            issuer_action = display_action = transaction_type = ""
            for prefix, display, kind in _ACTIONS:
                if body == prefix or body.startswith(prefix + " "):
                    issuer_action, display_action, transaction_type = prefix, display, kind
                    break
            if not issuer_action:
                raise ValueError(f"unclassified Edward Jones activity row: {line}")

            remainder = body[len(issuer_action) :].strip()
            quantity = None
            if issuer_action in {"Buy", "Sell", "Reinvestment"}:
                quantity_match = re.search(r"\s+(-?[\d,]+(?:\.\d+)?)$", remainder)
                if not quantity_match:
                    raise ValueError(f"missing quantity in Edward Jones trade row: {line}")
                quantity = _amount(quantity_match.group(1))
                remainder = remainder[: quantity_match.start()].strip()
            price_match = re.search(r"@\s*\$?([\d,]+\.\d+)", remainder)
            price = _amount(price_match.group(1)) if price_match else None
            symbol = ""
            if issuer_action in _SECURITY_ACTIONS and remainder:
                symbol = remainder.split()[0]

            row = {
                "date": _resolve_date(match.group("date"), start, end),
                "description": body,
                "amount": _amount(match.group("amount")),
                "action": display_action,
                "transaction_type": transaction_type,
                "symbol": symbol,
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            if quantity is not None:
                row["quantity"] = quantity
            if price is not None:
                row["price"] = price
            transactions.append(row)
            last_transaction = row
            continue

        if last_transaction and not _MONEY_RE.search(line) and not _MD_RE.match(line):
            last_transaction["description"] = f"{last_transaction['description']} {line}".strip()

    if not transactions:
        raise ValueError("no Edward Jones chronological activity rows found")
    return transactions


def _attach_realized_gains(lines: list[str], transactions: list[dict], start: date, end: date) -> None:
    active = False
    detail_total = 0.0
    detail_count = 0
    printed_total: float | None = None
    row_re = re.compile(
        rf"^(?P<symbol>[A-Z0-9./-]+)\s+(?P<purchase>\d{{2}}/\d{{2}}/\d{{4}}|-+)\s+"
        rf"(?P<sale>\d{{2}}/\d{{2}})\s+(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
        rf"(?P<cost>{_MONEY})\s+(?P<proceeds>{_MONEY})\s+(?P<gain>{_MONEY})\s+"
        rf"(?P<term>ST|LT)$",
        re.I,
    )
    summary = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("Detail of Realized Gain/Loss From Sale of Securities"):
            active, summary = True, False
            continue
        if line.startswith("Summary of Realized Gain/Loss"):
            active, summary = False, True
            continue
        if active:
            match = row_re.match(line)
            if not match:
                continue
            sale_date = _resolve_date(match.group("sale"), start, end)
            proceeds = _amount(match.group("proceeds"))
            gain = _amount(match.group("gain"))
            candidates = [
                row
                for row in transactions
                if row.get("transaction_type") == "sell"
                and row.get("symbol") == match.group("symbol")
                and row["date"] == sale_date
                and _close(row["amount"], proceeds)
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"Edward Jones realized gain row did not match exactly one sale: {line}"
                )
            candidates[0]["realized_gain"] = gain
            candidates[0]["realized_gain_term"] = (
                "Short-term" if match.group("term").upper() == "ST" else "Long-term"
            )
            detail_total += gain
            detail_count += 1
        elif summary:
            total_match = re.match(rf"^Total\s+({_MONEY})$", line, re.I)
            if total_match:
                printed_total = _amount(total_match.group(1))
                summary = False

    if detail_count and printed_total is None:
        raise ValueError("Edward Jones realized gain detail has no Summary total")
    if printed_total is not None:
        _require_close("realized gains", detail_total, printed_total)


def _reconcile_activity(controls: dict[str, float], transactions: list[dict], summary: dict[str, float]) -> None:
    additions = sum(row["amount"] for row in transactions if row["amount"] > 0)
    subtractions = sum(row["amount"] for row in transactions if row["amount"] < 0)
    _require_close("activity additions", additions, controls["additions"])
    _require_close("activity subtractions", subtractions, controls["subtractions"])
    _require_close("activity ending cash", controls["beginning"] + additions + subtractions, controls["ending"])

    added_types = {"deposit", "contribution", "rollover_in", "transfer_in"}
    withdrawn_types = {"withdrawal", "distribution", "rollover_out", "transfer_out"}
    added = sum(row["amount"] for row in transactions if row.get("transaction_type") in added_types)
    withdrawn = sum(row["amount"] for row in transactions if row.get("transaction_type") in withdrawn_types)
    fees = sum(row["amount"] for row in transactions if row.get("transaction_type") == "fee")
    _require_close("Value Summary assets added", added, summary["Assets Added to Account"])
    _require_close("Value Summary assets withdrawn", withdrawn, summary["Assets Withdrawn from Account"])
    _require_close("Value Summary fees", fees, summary["Fees and Charges"])


@diagnostic_helpers.repair_grade(
    section_markers=tuple(DIAGNOSTIC_MARKERS.values()),
    known_labels=tuple(DIAGNOSTIC_FIELDS.values()),
)
def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    lines = [line.strip() for line in text.splitlines()]
    start, end = _period(text)
    account, account_type, provider_id = _account_metadata(text)
    summary = _value_summary(lines)
    holdings, ending_value = _parse_holdings(lines, account, account_type, provider_id)
    controls = _activity_controls(lines)
    transactions = _parse_transactions(lines, start, end, account, account_type, provider_id)
    _attach_realized_gains(lines, transactions, start, end)
    _reconcile_activity(controls, transactions, summary)
    _require_close("ending holdings", ending_value, summary["Ending Value"])

    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": transactions,
        },
    }
