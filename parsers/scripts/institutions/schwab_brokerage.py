"""Charles Schwab retail brokerage statement parser.

This first version targets the post-2022 retail Account Statement layout
documented by Schwab.  It is intentionally conservative: it will not claim an
Advisor Services statement, pending/open activity is not emitted, duplicated
Bank Sweep activity is reconciled but not emitted, and every printed control
total we understand must foot before data is returned.

The module follows Orby's bundled brokerage PDF-parser contract and is
auto-discovered by ``bank_statement.py``.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

import parser_common

from . import common
from . import diagnostic_helpers


KIND = parser_common.KIND_BROKERAGE
INSTITUTION = "Charles Schwab"
SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
DIAGNOSTIC_MARKERS = {
    "account_summary": "Account Summary",
    "holdings": "Positions",
    "activity_summary": "Transaction Summary",
    "activity": "Transactions",
    "cash_sweep": "Bank Sweep",
}
DIAGNOSTIC_FIELDS = {
    "beginningValue": "Beginning Value",
    "endingValue": "Ending Value",
    "totalPositions": "Total Positions",
    "beginningCash": "Beginning Cash",
    "endingCash": "Ending Cash",
    "bankSweepBeginning": "Beginning Balance",
    "bankSweepEnding": "Ending Balance",
}
DIAGNOSTIC_SIGNALS = diagnostic_helpers.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = diagnostic_helpers.DIAGNOSTIC_COUNTS
DIAGNOSTIC_TERMS = diagnostic_helpers.DIAGNOSTIC_TERMS
PARSER_REVISION = 1

_MONEY = r"(?:\(?-?\$?[\d,]+\.\d{2}\)?)"
_NUMBER = r"(?:-?[\d,]+(?:\.\d+)?)"
_MONEY_RE = re.compile(rf"^{_MONEY}$")
_WORD_NUMBER_RE = re.compile(r"^\(?-?\$?[\d,]+(?:\.\d+)?\)?$")
_REALIZED_GAIN_WORD_RE = re.compile(
    r"^(?P<amount>\(?-?\$?[\d,]+\.\d{2}\)?),?\((?P<term>ST|LT)\)$",
    re.I,
)
_DATE_WORD_RE = re.compile(r"^\d{2}/\d{2}$")
_MONTH = (
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December"
)
_COMPACT_PERIOD = re.compile(
    rf"(?P<month>{_MONTH})\s*(?P<first>\d{{1,2}})\s*[-–]\s*"
    r"(?P<last>\d{1,2}),\s*(?P<year>\d{4})",
    re.I,
)
_RETAIL_ACCOUNT_OF = re.compile(r"Schwab\s+One\s*®?\s+Account\s+of", re.I)
_UNLABELED_ACCOUNT_PERIOD = re.compile(
    rf"(?P<account>[*Xx\d]{{2,8}}-[*Xx\d]{{2,8}})\s+(?={_MONTH}\s*\d{{1,2}}\s*[-–])",
    re.I,
)

_IGNORED_PREFIXES = (
    "SYNTHETIC TEST DATA",
    "NOT AN OFFICIAL",
    "CHARLES SCHWAB",
    "Schwab One Brokerage Account",
    "Account Number:",
    "Statement Period:",
    "Page ",
    "Member SIPC",
    "Fictional values for parser validation only.",
    "ACCOUNT OVERVIEW",
    "POSITIONS",
    "TRANSACTIONS",
    "Date  Category",
    "Date  Description",
    "Symbol  Description",
    "CUSIP  Description",
    "Date Category",
    "Date Description",
    "Symbol Description",
    "CUSIP Description",
)


def detect(head_text: str) -> tuple[bool, str]:
    """Recognize only Schwab's current retail statement family."""
    lower = head_text.lower()
    missing = []
    if "schwab" not in lower:
        missing.append("Schwab")
    if "statement period" not in lower and not _COMPACT_PERIOD.search(head_text):
        missing.append("statement date range")
    if "account summary" not in lower:
        missing.append("Account Summary")
    labeled_account = re.search(r"Account (?:Number|#)\s*:?[ \t]*[*Xx\d]", head_text, re.I)
    if not labeled_account and not _UNLABELED_ACCOUNT_PERIOD.search(head_text):
        missing.append("account identifier")
    if not re.search(r"Schwab One|Brokerage Account|Rollover IRA|Roth IRA|Contributory IRA|Trust Account", head_text, re.I):
        missing.append("retail account title")
    if "Schwab One" in head_text and not _RETAIL_ACCOUNT_OF.search(head_text) and not labeled_account:
        missing.append("Schwab One Account of")
    if missing:
        return False, "missing retail Schwab marker(s): " + ", ".join(missing)
    if "advisor services statement format" in lower:
        return False, "Advisor Services guide/format is not the supported retail layout"
    return True, "found Schwab retail account title, account identifier, statement date range, and Account Summary"


def _amount(raw: str) -> float:
    value = raw.strip().replace("$", "").replace(",", "")
    if value in {"-", "--", "—"}:
        return 0.0
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    parsed = float(value)
    return -parsed if negative else parsed


def _close(a: float, b: float, tolerance: float = 0.02) -> bool:
    return abs(a - b) <= tolerance


def _require_close(label: str, parsed: float, printed: float) -> None:
    if not _close(parsed, printed):
        lower = label.casefold()
        if "position" in lower:
            stage = "holdings"
        elif "cash" in lower or "transaction" in lower or "sweep" in lower:
            stage = "activity"
        else:
            stage = "summary"
        raise diagnostic_helpers.reconciliation_error(
            f"{label} does not reconcile: parsed {parsed:.2f}, printed {printed:.2f}",
            parsed,
            printed,
            stage,
        )


def _statement_period(text: str) -> tuple[date, date]:
    full = re.search(
        r"Statement Period\s*:?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})\s*[-–]\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
        text,
        re.I,
    )
    if full:
        return tuple(datetime.strptime(full.group(i), "%B %d, %Y").date() for i in (1, 2))  # type: ignore[return-value]

    compact = re.search(
        r"Statement Period\s*:?\s*([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),\s*(\d{4})",
        text,
        re.I,
    )
    if not compact:
        compact = _COMPACT_PERIOD.search(text)
        if not compact:
            raise ValueError("Schwab statement period not found")
        month = compact.group("month")
        first_day = compact.group("first")
        last_day = compact.group("last")
        year = compact.group("year")
        start = datetime.strptime(f"{month} {first_day}, {year}", "%B %d, %Y").date()
        end = datetime.strptime(f"{month} {last_day}, {year}", "%B %d, %Y").date()
        return start, end
    month, first_day, last_day, year = compact.groups()
    start = datetime.strptime(f"{month} {first_day}, {year}", "%B %d, %Y").date()
    end = datetime.strptime(f"{month} {last_day}, {year}", "%B %d, %Y").date()
    return start, end


def _resolve_date(month_day: str, start: date, end: date) -> str:
    month, day = (int(part) for part in month_day.split("/"))
    candidates = []
    for year in {start.year - 1, start.year, end.year, end.year + 1}:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = 0 if start <= candidate <= end else min(abs((candidate - start).days), abs((candidate - end).days))
        candidates.append((distance, candidate))
    if not candidates:
        raise ValueError(f"invalid Schwab transaction date {month_day!r}")
    return min(candidates)[1].isoformat()


def _account_metadata(text: str) -> tuple[str, str, str]:
    match = re.search(
        r"Account (?:Number|#)\s*:?\s*([*Xx\d][*Xx\d -]{2,20})",
        text,
        re.I,
    )
    if match:
        provider_id = match.group(1).strip()
    else:
        unlabeled = _UNLABELED_ACCOUNT_PERIOD.search(text)
        if not unlabeled:
            raise ValueError("Schwab account number not found")
        provider_id = unlabeled.group("account")
    account = common.last4_digits(provider_id)
    title_match = re.search(
        r"^(.*?(?:Schwab One|Brokerage Account|Rollover IRA|Roth IRA|Contributory IRA|Trust Account).*?)$",
        text,
        re.I | re.M,
    )
    title = title_match.group(1).strip() if title_match else "Brokerage"
    account_type = common.classify_account_type(title, "Brokerage")
    return account, account_type, provider_id


def _summary(lines: list[str], start_label: str, end_labels: tuple[str, ...]) -> dict[str, float]:
    active = False
    values: dict[str, float] = {}
    for raw in lines:
        line = raw.strip()
        if line.lower() == start_label.lower():
            active = True
            continue
        if active and any(line.lower().startswith(label.lower()) for label in end_labels):
            break
        if not active:
            continue
        match = re.match(rf"^(.*?)\s+({_MONEY})$", line)
        if match:
            values[match.group(1).strip()] = _amount(match.group(2))
    return values


def _value(values: dict[str, float], *labels: str) -> float:
    for label in labels:
        if label in values:
            return values[label]
    raise ValueError(f"missing Schwab control total: {' / '.join(labels)}")


def _current_account_summary(lines: list[str]) -> dict[str, float]:
    """Read the current-period column from Schwab's compact real layout.

    Current retail PDFs commonly collapse all spaces inside labels and print
    ``This Statement`` and ``YTD`` amounts on the same physical line. Sidebar
    help text may also precede the label on that line. The first currency
    amount after the recognized label is the current-period value; the second,
    when present, is YTD and is deliberately ignored here.
    """
    labels = (
        ("BeginningAccountValue", "Beginning Value"),
        ("Deposits", "Deposits"),
        ("Withdrawals", "Withdrawals"),
        ("DividendsandInterest", "Dividends and Interest"),
        ("TransferofSecurities", "Transfer of Securities (In/Out)"),
        ("MarketAppreciation/(Depreciation)", "Market Value Change"),
        ("Expenses", "Fees"),
        ("EndingAccountValue", "Ending Value"),
    )
    values: dict[str, float] = {}
    for raw in lines:
        compact = re.sub(r"\s+", "", raw)
        for printed, canonical in labels:
            position = compact.find(printed)
            if position < 0:
                continue
            amounts = re.findall(_MONEY, compact[position + len(printed) :])
            if amounts:
                values[canonical] = _amount(amounts[0])
            break
    return values


def _reconcile_account_summary(values: dict[str, float]) -> None:
    beginning = _value(values, "Beginning Value")
    ending = _value(values, "Ending Value", "Ending Account Value")
    components = sum(
        _value(values, label)
        for label in (
            "Deposits",
            "Withdrawals",
            "Dividends and Interest",
            "Transfer of Securities (In/Out)",
            "Market Value Change",
            "Fees",
        )
    )
    _require_close("Account Summary", beginning + components, ending)


def _is_ignored(line: str) -> bool:
    return not line or any(line.startswith(prefix) for prefix in _IGNORED_PREFIXES)


def _parse_holdings(
    lines: list[str], account: str, account_type: str, provider_id: str
) -> tuple[list[dict], float]:
    holdings: list[dict] = []
    in_holdings = False
    subtype = ""
    printed_total: float | None = None
    last_holding: dict | None = None

    regular = re.compile(
        rf"^(?P<symbol>[A-Z0-9./-]+)\s+(?P<description>.+?)\s+"
        rf"(?P<quantity>{_NUMBER})\s+(?P<price>{_NUMBER})\s+"
        rf"(?P<value>{_MONEY})\s+(?P<cost>{_MONEY}|--|—)$"
    )
    fixed = re.compile(
        rf"^(?P<cusip>[A-Z0-9]{{9}})\s+(?P<description>.+?)\s+"
        rf"(?P<coupon>\d+\.\d+%)\s+(?P<maturity>\d{{2}}/\d{{2}}/\d{{4}})\s+"
        rf"(?P<quantity>{_NUMBER})\s+(?P<price>{_NUMBER})\s+(?P<value>{_MONEY})$"
    )
    cash = re.compile(rf"^CASH\s+(?P<description>.+?)\s+(?P<value>{_MONEY})$")

    for raw in lines:
        line = raw.strip()
        if line == "Cash and Cash Investments":
            in_holdings, subtype, last_holding = True, "Cash", None
            continue
        if line in {"Equities", "Mutual Funds", "Options", "Fixed Income"}:
            in_holdings, subtype, last_holding = True, line, None
            continue
        if line.startswith("Transactions - Summary"):
            break
        if not in_holdings:
            continue
        total_match = re.match(rf"^Total Positions\s+({_MONEY})$", line)
        if total_match:
            printed_total = _amount(total_match.group(1))
            last_holding = None
            continue
        if re.sub(r"\s+", "", line).startswith("TotalCashandCashInvestments"):
            amounts = re.findall(_MONEY, line)
            if len(amounts) >= 2:
                # Real statements print beginning, ending, and change; the
                # ending balance is the holding value as of statement close.
                printed_total = _amount(amounts[1])
            last_holding = None
            continue
        if _is_ignored(line) or line.startswith("Quantity  Price"):
            continue

        match = fixed.match(line)
        if match:
            row = {
                "symbol": match.group("cusip"),
                "security_id": match.group("cusip"),
                "security_id_type": "CUSIP",
                "cusip": match.group("cusip"),
                "description": match.group("description"),
                "quantity": _amount(match.group("quantity")),
                "price": _amount(match.group("price")),
                "current_value": _amount(match.group("value")),
                "type": "Fixed Income",
                "subtype": f"Coupon {match.group('coupon')}; matures {match.group('maturity')}",
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            holdings.append(row)
            last_holding = row
            continue

        match = cash.match(line)
        if match:
            row = {
                "symbol": "CASH",
                "description": match.group("description"),
                "current_value": _amount(match.group("value")),
                "type": "Cash and Cash Investments",
                "is_cash_equivalent": True,
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            holdings.append(row)
            last_holding = row
            continue

        if subtype == "Cash" and line.startswith("Cash "):
            amounts = re.findall(_MONEY, line)
            if len(amounts) >= 2:
                row = {
                    "symbol": "CASH",
                    "description": "Cash",
                    "current_value": _amount(amounts[1]),
                    "type": "Cash and Cash Investments",
                    "is_cash_equivalent": True,
                    "currency_code": "USD",
                    "account": account,
                    "accountType": account_type,
                    "provider_account_id": provider_id,
                }
                holdings.append(row)
                last_holding = row
                continue

        match = regular.match(line)
        if match:
            row = {
                "symbol": match.group("symbol"),
                "description": match.group("description"),
                "quantity": _amount(match.group("quantity")),
                "price": _amount(match.group("price")),
                "current_value": _amount(match.group("value")),
                "cost_basis_total": None if match.group("cost") in {"--", "—"} else _amount(match.group("cost")),
                "type": subtype or "Security",
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            if subtype == "Options":
                row["subtype"] = "Option"
            holdings.append(row)
            last_holding = row
            continue

        # Schwab descriptions commonly wrap under the first physical row.
        # Only attach prose-only lines while a real holding is open.
        if last_holding and not re.search(r"\d", line) and line not in {"Positions", "Positions (Continued)"}:
            last_holding["description"] = f"{last_holding['description']} {line}".strip()

    if printed_total is None:
        raise parser_common.ParserDiagnosticError(
            "Total Positions control total not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("totalPositions",),
        )
    _require_close("Positions", sum(h.get("current_value") or 0.0 for h in holdings), printed_total)
    return holdings, printed_total


_ACTION_TYPES = {
    "Buy": "buy",
    "Reinvest": "buy",
    "Sell": "sell",
    "Qualified Dividend": "dividend",
    "Cash Dividend": "dividend",
    "Bank Interest": "interest",
    "Deposit": "deposit",
    "Withdrawal": "withdrawal",
    "Advisory Fee": "fee",
}

_DISPLAY_ACTIONS = {
    "Reinvest": "Reinvestment",
    "Qualified Dividend": "Dividend",
    "Cash Dividend": "Dividend",
    "Bank Interest": "Interest",
    "Advisory Fee": "Fee",
}


def _parse_transactions(
    lines: list[str], start: date, end: date, account: str, account_type: str, provider_id: str
) -> list[dict]:
    transactions: list[dict] = []
    active = False
    pending = False
    last_transaction: dict | None = None
    row_re = re.compile(r"^\d{2}/\d{2}\s+")
    actions = "|".join(sorted((re.escape(a) for a in _ACTION_TYPES), key=len, reverse=True))
    categories = "Deposit|Withdrawal|Purchase|Sale|Dividend|Interest|Fee"
    detail_re = re.compile(
        rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<category>{categories})\s+"
        rf"(?P<action>{actions})\s+(?P<symbol>\S+)\s+(?P<description>.+?)\s+"
        rf"(?P<quantity>{_NUMBER}|-|--|—)\s+(?P<price>{_NUMBER}|-|--|—)\s+"
        rf"(?P<charges>{_MONEY}|-|--|—)\s+(?P<amount>{_MONEY})$"
    )

    for raw in lines:
        line = raw.strip()
        if line in {"Transaction Details", "Transaction Details (Continued)"}:
            active, pending, last_transaction = True, False, None
            continue
        if line.startswith("Bank Sweep Activity") or line.startswith("Money Market Fund (Sweep) Activity"):
            active, last_transaction = False, None
            continue
        if line.startswith("Pending/Open Activities"):
            pending, active, last_transaction = True, False, None
            continue
        if pending or not active or _is_ignored(line):
            continue
        if line.startswith("Total Transaction Details"):
            last_transaction = None
            continue

        if row_re.match(line):
            match = detail_re.match(line)
            if not match:
                raise ValueError(f"unrecognized Schwab transaction row: {line}")
            month_day = match.group("date")
            category = match.group("category")
            issuer_action = match.group("action")
            symbol = match.group("symbol")
            description = match.group("description")
            quantity = match.group("quantity")
            price = match.group("price")
            charges = match.group("charges")
            raw_amount = match.group("amount")
            transaction_type = _ACTION_TYPES.get(issuer_action)
            if not transaction_type:
                raise ValueError(f"unclassified Schwab action {issuer_action!r}")
            row = {
                "date": _resolve_date(month_day, start, end),
                "description": description,
                "amount": _amount(raw_amount),
                "action": _DISPLAY_ACTIONS.get(issuer_action, issuer_action),
                "transaction_type": transaction_type,
                "symbol": "" if symbol in {"-", "--"} else symbol,
                "commission_and_fees": None if charges in {"-", "--", "—"} else _amount(charges),
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            if quantity not in {"-", "--", "—"}:
                row["quantity"] = _amount(quantity)
            if price not in {"-", "--", "—"}:
                row["price"] = _amount(price)
            transactions.append(row)
            last_transaction = row
            continue

        # Description continuations are prose-only physical lines under a
        # dated row. Repeated page furniture is filtered above.
        if last_transaction and not re.search(r"\d{2}/\d{2}", line):
            last_transaction["description"] = f"{last_transaction['description']} {line}".strip()

    return transactions


_POSITIONED_CATEGORIES = {
    "Deposit",
    "Dividend",
    "Expense",
    "Fee",
    "Interest",
    "Other",
    "Purchase",
    "Redemption",
    "Sale",
    "Transfer",
    "Withdrawal",
}


def _word_rows(page) -> list[tuple[float, list[dict]]]:
    """Group pdfplumber words into physical rows without losing x positions."""
    grouped: list[tuple[float, list[dict]]] = []
    for word in page.extract_words(x_tolerance=2, y_tolerance=2):
        top = float(word["top"])
        for index, (row_top, words) in enumerate(grouped):
            if abs(row_top - top) <= 2:
                words.append(word)
                grouped[index] = (row_top, sorted(words, key=lambda item: item["x0"]))
                break
        else:
            grouped.append((top, [word]))
    return sorted(grouped, key=lambda item: item[0])


def _positioned_header(rows: list[tuple[float, list[dict]]]) -> tuple[int, dict[str, float]] | None:
    """Find a Transaction Details column header and its x coordinates."""
    for index, (_, words) in enumerate(rows):
        by_text = {word["text"]: float(word["x0"]) for word in words}
        if not {"Date", "Category", "Action"}.issubset(by_text):
            continue
        description = next((word for word in words if word["text"] == "Description"), None)
        if not description:
            continue

        # The current Schwab header is split vertically: ``Symbol/``,
        # ``Price/Rate``, ``Charges/``, and ``Realized`` are printed on the
        # physical line *above* Date/Category/Action, while CUSIP and the
        # units are on the anchor line. Include both preceding and following
        # header rows, stopping before the first dated/category data row.
        header_words = [word for _, row in rows[max(0, index - 2) : index + 1] for word in row]
        for _, following in rows[index + 1 : index + 3]:
            if any(_DATE_WORD_RE.fullmatch(word["text"]) for word in following):
                break
            if any(
                abs(float(word["x0"]) - by_text["Category"]) <= 5
                and word["text"] in _POSITIONED_CATEGORIES
                for word in following
            ):
                break
            header_words.extend(following)

        symbol = next(
            (
                word
                for word in header_words
                if word["text"].startswith("Symbol") or word["text"] == "CUSIP"
            ),
            None,
        )
        if not symbol:
            continue

        def x_for(*prefixes: str) -> float | None:
            candidates = [
                float(word["x0"])
                for word in header_words
                if any(word["text"].startswith(prefix) for prefix in prefixes)
            ]
            return min(candidates) if candidates else None

        columns = {
            "date": by_text["Date"],
            "category": by_text["Category"],
            "action": by_text["Action"],
            "symbol": float(symbol["x0"]),
            "description": float(description["x0"]),
            "quantity": x_for("Quantity"),
            "price": x_for("Price", "Rate"),
            "charges": x_for("Charges", "Interest"),
            "amount": x_for("Amount"),
            "gain": x_for("Realized", "Gain/Loss"),
        }
        if any(columns[name] is None for name in ("quantity", "price", "charges", "amount")):
            continue
        numeric_positions = [columns[name] for name in ("quantity", "price", "charges", "amount")]
        if numeric_positions != sorted(numeric_positions):
            continue
        return index, {name: float(value) for name, value in columns.items() if value is not None}
    return None


def _column_boundaries(columns: dict[str, float]) -> dict[str, tuple[float, float]]:
    # Text cells are left-aligned, so the next heading's x position is
    # their natural boundary. Numeric cells are right-aligned and can begin
    # slightly left of their heading; give each a modest left gutter.
    quantity_left = columns["quantity"] - 30
    price_left = columns["price"] - 20
    charges_left = columns["charges"] - 20
    amount_left = columns["amount"] - 20
    gain_left = columns.get("gain", float("inf")) - 20
    return {
        "date": (float("-inf"), columns["category"] - 3),
        "category": (columns["category"] - 3, columns["action"] - 3),
        "action": (columns["action"] - 3, columns["symbol"] - 3),
        "symbol": (columns["symbol"] - 3, columns["description"] - 3),
        "description": (columns["description"] - 3, quantity_left),
        "quantity": (quantity_left, price_left),
        "price": (price_left, charges_left),
        "charges": (charges_left, amount_left),
        "amount": (amount_left, gain_left),
        **({"gain": (gain_left, float("inf"))} if "gain" in columns else {}),
    }


def _column_words(block: list[tuple[float, list[dict]]], bounds: tuple[float, float]) -> list[dict]:
    left, right = bounds
    return sorted(
        [word for _, words in block for word in words if left <= float(word["x0"]) < right],
        key=lambda word: (float(word["top"]), float(word["x0"])),
    )


def _cell_text(block: list[tuple[float, list[dict]]], bounds: tuple[float, float]) -> str:
    return " ".join(word["text"] for word in _column_words(block, bounds)).strip()


def _cell_number(block: list[tuple[float, list[dict]]], bounds: tuple[float, float]) -> float | None:
    for word in _column_words(block, bounds):
        text = word["text"].strip()
        if _WORD_NUMBER_RE.fullmatch(text):
            return _amount(text)
    return None


def _cell_realized_gain(
    block: list[tuple[float, list[dict]]], bounds: tuple[float, float]
) -> tuple[float | None, str]:
    for word in _column_words(block, bounds):
        text = word["text"].strip()
        annotated = _REALIZED_GAIN_WORD_RE.fullmatch(text)
        if annotated:
            term = "Short-term" if annotated.group("term").upper() == "ST" else "Long-term"
            return _amount(annotated.group("amount")), term
        if _WORD_NUMBER_RE.fullmatch(text):
            return _amount(text), ""
    return None, ""


def _humanize_action(value: str) -> str:
    known = {
        "JournaledFunds": "Journaled Funds",
        "MoneyLinkTxn": "MoneyLink Transaction",
        "StockPlanActivity": "Stock Plan Activity",
    }
    if value in known:
        return known[value]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value).strip()


def _positioned_transaction(
    block: list[tuple[float, list[dict]]],
    columns: dict[str, float],
    month_day: str,
    start: date,
    end: date,
    account: str,
    account_type: str,
    provider_id: str,
) -> dict:
    bounds = _column_boundaries(columns)
    category = re.sub(r"\s+", " ", _cell_text(block, bounds["category"])).strip()
    category_key = re.sub(r"[^a-z]", "", category.lower())
    raw_action = re.sub(r"\s+", "", _cell_text(block, bounds["action"]))

    if category_key.startswith("otheractivity"):
        transaction_type, action = "corporate_action", _humanize_action(raw_action or "Other Activity")
    elif category_key.startswith(("sale", "redemption")):
        transaction_type, action = "sell", _humanize_action(raw_action or "Sell")
    elif category_key.startswith("purchase"):
        transaction_type, action = "buy", _humanize_action(raw_action or "Buy")
    elif category_key.startswith("withdrawal"):
        transaction_type, action = "withdrawal", _humanize_action(raw_action or "Withdrawal")
    elif category_key.startswith("deposit"):
        transaction_type, action = "deposit", _humanize_action(raw_action or "Deposit")
    elif category_key.startswith("dividend"):
        transaction_type, action = "dividend", _humanize_action(raw_action or "Dividend")
    elif category_key.startswith("interest"):
        transaction_type, action = "interest", _humanize_action(raw_action or "Interest")
    elif category_key.startswith(("expense", "fee")):
        transaction_type, action = "fee", _humanize_action(raw_action or "Fee")
    elif category_key.startswith("transfer"):
        transaction_type, action = "transfer", _humanize_action(raw_action or "Transfer")
    else:
        raise ValueError(f"unclassified positioned Schwab category {category!r}")

    printed_amount = _cell_number(block, bounds["amount"])
    if transaction_type == "corporate_action":
        # Schwab prints a market value for stock-plan/share movements in
        # the Amount column, but explicitly excludes Other Activity from
        # its cash equation. Orby's amount is cash movement, so it is zero.
        amount = 0.0
    elif printed_amount is None:
        raise ValueError(f"missing amount for positioned Schwab {category!r} row")
    else:
        amount = printed_amount

    description = _cell_text(block, bounds["description"])
    symbol = _cell_text(block, bounds["symbol"])
    row = {
        "date": _resolve_date(month_day, start, end),
        "description": description or action,
        "amount": amount,
        "action": action,
        "transaction_type": transaction_type,
        "symbol": "" if symbol in {"-", "--", "—"} else symbol,
        "currency_code": "USD",
        "account": account,
        "accountType": account_type,
        "provider_account_id": provider_id,
    }
    quantity = _cell_number(block, bounds["quantity"])
    price = _cell_number(block, bounds["price"])
    charges = _cell_number(block, bounds["charges"])
    if quantity is not None:
        row["quantity"] = quantity
    if price is not None:
        row["price"] = price
    if charges is not None:
        row["commission_and_fees"] = charges
    if "gain" in bounds:
        realized_gain, realized_gain_term = _cell_realized_gain(block, bounds["gain"])
        if realized_gain is not None:
            row["realized_gain"] = realized_gain
            row["realized_gain_term"] = realized_gain_term
    return row


def _parse_positioned_transactions(
    pdf_path: str, start: date, end: date, account: str, account_type: str, provider_id: str
) -> list[dict]:
    """Parse current Schwab transaction tables from their PDF geometry.

    Production statements suppress repeated dates and wrap category/action
    labels across physical rows. ``extract_text()`` consequently cannot
    preserve the table's cells, while ``extract_words()`` retains enough x
    position to reconstruct them deterministically.
    """
    transactions: list[dict] = []
    last_date = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            rows = _word_rows(page)
            header = _positioned_header(rows)
            if not header:
                continue
            header_index, columns = header
            data_rows: list[tuple[float, list[dict]]] = []
            for row_top, words in rows[header_index + 1 :]:
                compact = re.sub(r"\s+", "", "".join(word["text"] for word in words)).lower()
                if compact.startswith(
                    ("totaltransaction", "banksweepactivity", "moneymarketfund", "pending/openactivities")
                ):
                    break
                data_rows.append((row_top, words))

            starter_indexes: list[int] = []
            for index, (_, words) in enumerate(data_rows):
                starters = [
                    word
                    for word in words
                    if abs(float(word["x0"]) - columns["category"]) <= 5
                    and word["text"] in _POSITIONED_CATEGORIES
                ]
                if starters:
                    starter_indexes.append(index)

            for position, block_start in enumerate(starter_indexes):
                block_end = starter_indexes[position + 1] if position + 1 < len(starter_indexes) else len(data_rows)
                block = data_rows[block_start:block_end]
                # On a page that continues the table, the final transaction
                # has no printed total after it. Do not let a distant page
                # footer become part of that row's action or description.
                contiguous = [block[0]]
                for candidate in block[1:]:
                    if candidate[0] - contiguous[-1][0] > 18:
                        break
                    contiguous.append(candidate)
                block = contiguous
                dates = [
                    word["text"]
                    for _, words in block
                    for word in words
                    if float(word["x0"]) < columns["category"] and _DATE_WORD_RE.fullmatch(word["text"])
                ]
                if dates:
                    last_date = dates[0]
                if not last_date:
                    raise ValueError("positioned Schwab transaction appeared before its first printed date")
                transactions.append(
                    _positioned_transaction(
                        block, columns, last_date, start, end, account, account_type, provider_id
                    )
                )
    if not transactions:
        raise ValueError("no positioned Schwab transaction rows found")
    return transactions


def _current_transaction_summary(lines: list[str]) -> dict[str, float]:
    """Read the compact eight-column cash equation in current statements."""
    labels = (
        "Beginning Cash",
        "Deposits",
        "Withdrawals",
        "Purchases",
        "Sales/Redemptions",
        "Dividends/Interest",
        "Fees",
        "Ending Cash",
    )
    for index, raw in enumerate(lines):
        compact = re.sub(r"\s+", "", raw)
        if not compact.startswith("BeginningCash*asof") or "EndingCash*asof" not in compact:
            continue
        for values_line in lines[index + 1 : index + 4]:
            amounts = re.findall(_MONEY, values_line)
            if len(amounts) >= len(labels):
                return {label: _amount(value) for label, value in zip(labels, amounts)}
    return {}


def _reconcile_transaction_summary(values: dict[str, float], transactions: list[dict]) -> None:
    expected = {
        "Deposits": sum(t["amount"] for t in transactions if t["transaction_type"] == "deposit"),
        "Withdrawals": sum(t["amount"] for t in transactions if t["transaction_type"] == "withdrawal"),
        "Purchases": sum(t["amount"] for t in transactions if t["transaction_type"] == "buy"),
        "Sales/Redemptions": sum(t["amount"] for t in transactions if t["transaction_type"] in {"sell", "redemption"}),
        "Dividends/Interest": sum(t["amount"] for t in transactions if t["transaction_type"] in {"dividend", "interest"}),
        "Fees": sum(t["amount"] for t in transactions if t["transaction_type"] == "fee"),
    }
    for label, parsed in expected.items():
        _require_close(f"Transactions - Summary {label}", parsed, _value(values, label))
    calculated_ending = _value(values, "Beginning Cash") + sum(expected.values())
    _require_close("Transactions - Summary Ending Cash", calculated_ending, _value(values, "Ending Cash"))


def _reconcile_sweep(lines: list[str], start: date, end: date) -> None:
    active = False
    beginning: float | None = None
    ending: float | None = None
    running: float | None = None
    saw_row = False
    for raw in lines:
        line = raw.strip()
        if line == "Bank Sweep Activity":
            active = True
            continue
        if active and (line.startswith("Pending/Open Activities") or line.startswith("Money Market Fund (Sweep) Activity")):
            break
        if not active or _is_ignored(line):
            continue
        match = re.match(rf"^Beginning Balance\s+({_MONEY})$", line)
        if match:
            beginning = running = _amount(match.group(1))
            continue
        match = re.match(rf"^Ending Balance\s+({_MONEY})$", line)
        if match:
            ending = _amount(match.group(1))
            continue
        row = re.match(
            rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<description>.+?)\s+"
            rf"(?P<amount>{_MONEY})\s+(?P<balance>{_MONEY})$",
            line,
        )
        if row:
            _resolve_date(row.group("date"), start, end)
            if running is None:
                raise ValueError("Bank Sweep activity row appeared before Beginning Balance")
            amount, printed_balance = _amount(row.group("amount")), _amount(row.group("balance"))
            running = round(running + amount, 2)
            _require_close(f"Bank Sweep running balance on {row.group('date')}", running, printed_balance)
            saw_row = True
    if active and (beginning is None or ending is None):
        raise ValueError("Bank Sweep section is missing its beginning or ending balance")
    if saw_row and running is not None and ending is not None:
        _require_close("Bank Sweep Ending Balance", running, ending)


@diagnostic_helpers.repair_grade(
    section_markers=tuple(DIAGNOSTIC_MARKERS.values()),
    known_labels=tuple(DIAGNOSTIC_FIELDS.values()),
)
def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    lines = [line.rstrip() for page in pages_text for line in page.splitlines()]
    start, end = _statement_period(text)
    account, account_type, provider_id = _account_metadata(text)

    account_summary = _summary(lines, "Account Summary", ("Positions - Summary",))
    if "Beginning Value" not in account_summary:
        account_summary = _current_account_summary(lines)
    _reconcile_account_summary(account_summary)

    holdings, total_positions = _parse_holdings(lines, account, account_type, provider_id)
    ending_value = _value(account_summary, "Ending Value", "Ending Account Value")
    _require_close("Ending Account Value versus Total Positions", total_positions, ending_value)

    try:
        transactions = _parse_transactions(lines, start, end, account, account_type, provider_id)
        if not transactions and any("Transaction Details" in line for line in lines):
            transactions = _parse_positioned_transactions(
                pdf_path, start, end, account, account_type, provider_id
            )
    except ValueError:
        # Current retail PDFs preserve transaction columns only as word
        # positions and suppress repeated dates. Keep the simpler text path
        # for older layouts and synthetic fixtures, then use geometry when
        # the flattened row cannot be classified safely.
        transactions = _parse_positioned_transactions(
            pdf_path, start, end, account, account_type, provider_id
        )
    transaction_summary = _summary(lines, "Transactions - Summary", ("Transaction Details",))
    if "Beginning Cash" not in transaction_summary:
        transaction_summary = _current_transaction_summary(lines)
    _reconcile_transaction_summary(transaction_summary, transactions)
    _reconcile_sweep(lines, start, end)

    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": transactions,
        },
    }
