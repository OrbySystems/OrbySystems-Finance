"""Merrill Lynch CMA brokerage statement parser.

Merrill's CMA statement is a brokerage statement with a linked cash
management ledger.  The public sample PDFs this parser was developed
from are heavily anonymized and their text extraction is uneven: some
pages interleave columns, some words are split into letters, and dates
use masked years ("20xx").  The parser therefore keys off stable section
headers and ordinary one-line rows, and returns only rows whose required
fields can be read without guessing.

The related "WEALTH MANAGEMENT REPORT" and "TRUST MANAGEMENT ACCOUNT"
documents are deliberately not matched here.  They are summary/report
documents, not the account-level CMA statement this module parses.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import parser_common

from . import common

KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_PARTIAL

_INSTITUTION = "Merrill Lynch"
_ACCOUNT_TYPE = "Brokerage"
_CURRENCY = "USD"

_PERIOD_RE = re.compile(
    r"([A-Z][a-z]+ \d{1,2}, (?P<sy>\d{4}|20xx))\s*-\s*"
    r"([A-Z][a-z]+ \d{1,2}, (?P<ey>\d{4}|20xx))",
    re.I,
)
_ACCOUNT_RE = re.compile(r"Account Number:\s*([A-Za-z0-9Xx*#-]+)", re.I)
_DATE_START_RE = re.compile(r"^(?P<md>\d{1,2}/\d{1,2})\s+(?P<rest>.+)$")
_NUM = r"\(?-?\$?[\d,]+\.\d+\)?"
_NUM_RE = re.compile(_NUM)
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_CUSIP_RE = re.compile(r"CUSIP (?:NUM|NO)[: ]+\s*([A-Z0-9]{6,})", re.I)
_VALID_AMOUNT_RE = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$")

_HOLDING_STOP_RE = re.compile(
    r"^(?:TOTAL|Subtotal|RESEARCH RATINGS|PLEASE REFER|Equity Cost Basis|"
    r"Other Money Market|Total Client Investment|Notes\b|Market Timing)",
    re.I,
)
_ASSET_SECTION_RE = re.compile(
    r"^(?:"
    r"CASH\b|ML BANK DEPOSIT PROGRAM|PREFERRED DEPOSIT|CASH RESERVE FUND|"
    r".*\b[A-Z][A-Z0-9.]{0,9}\s+\d[\d,]*\.\d{4}\s+|"
    r".*\b(?:SYMBOL|SYMBO L)\s*:|"
    r".*\bC U S I P\b|.*\bCUSIP\b"
    r")",
    re.I,
)

_CASH_ACTIONS = {
    "Funds Received": "deposit",
    "Direct Deposit": "deposit",
    "Withdrawal": "withdrawal",
    "Pre-Authorized Withdrawal": "withdrawal",
    "Wire Transfer Out": "withdrawal",
    "Cash In Lieu of Shares": "corporate_action",
    "Foreign Tax Withholding": "tax",
    "Visa Access Debit": "withdrawal",
    "Margin Interest Charged": "interest",
    "Advisory Program Fee": "fee",
    "Metals Servicing Fee": "fee",
    "Visa Cash Advance": "withdrawal",
}
_INCOME_ACTIONS = {
    "Interest": ("Interest", "interest", "interest"),
    "Bank Interest": ("Interest", "interest", "bank_interest"),
    "Dividend": ("Dividend", "dividend", "dividend"),
    "Long Term Capital Gain": ("Capital Gain", "capital_gain", "long_term"),
    "Income Total": ("Income", "income", "other_income"),
}
_SECURITY_ACTIONS = {
    "Purchase": ("Buy", "buy"),
    "Sale": ("Sell", "sell"),
    "Redemption": ("Redemption", "sell"),
    "Transfer/Adjustment": ("Transfer/Adjustment", "internal_transfer"),
    "When Issue Purchase": ("Buy", "buy"),
}


def detect(head_text: str) -> tuple[bool, str]:
    low = head_text.lower()
    if "wealth management report" in low:
        return False, "wealth management report is not a CMA statement"
    if "trust management account" in low:
        return False, "trust management account is not a CMA statement"
    if "merrill" not in low and "mlpf&s" not in low:
        return False, "'Merrill' not found"
    if "cma" not in low:
        return False, "'CMA' not found"
    if "account number:" not in low:
        return False, "'Account Number:' not found"
    if not _PERIOD_RE.search(head_text):
        return False, "no Merrill CMA statement period found"
    return True, "matched Merrill Lynch CMA account statement"


def _amount(token: str | None) -> float | None:
    if not token:
        return None
    if not _VALID_AMOUNT_RE.match(token):
        return None
    return common.parse_amount(token.replace("$", ""))


def _statement_date(text: str) -> tuple[str, date | None]:
    match = _PERIOD_RE.search(text)
    if not match or "x" in match.group(0).lower():
        return "", None
    end = match.group(3)
    try:
        d = datetime.strptime(end, "%B %d, %Y").date()
    except ValueError:
        return "", None
    return d.isoformat(), d


def _resolve_date(month_day: str, anchor: date | None) -> str | None:
    if anchor is None:
        return None
    month, day = (int(part) for part in month_day.split("/"))
    year = anchor.year
    if month == 12 and anchor.month == 1:
        year -= 1
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _account(text: str) -> str:
    match = _ACCOUNT_RE.search(text)
    return common.last4_digits(match.group(1)) if match else ""


def _clean_description(value: str) -> str:
    value = re.sub(r"[\u2722\u2727\u2729\u272a\u271a\u2749\u25a0\u00b3\u00a7#*]+", " ", value)
    value = re.sub(r"\bPAY DATE\b.*", "", value, flags=re.I)
    value = re.sub(r"\bCUSIP (?:NUM|NO)[: ].*", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -")
    return value


def _infer_symbol(description: str) -> str:
    symbol_match = re.search(r"SYMBOL\s*:?\s*([A-Z][A-Z0-9.]{1,9})", description, re.I)
    if symbol_match:
        return symbol_match.group(1).upper()
    words = re.findall(r"\b[A-Z][A-Z0-9.]{1,9}\b", description)
    for word in reversed(words):
        if word not in {"CURRENT", "YIELD", "CUSIP", "PAY", "DATE", "TOTAL"}:
            return word
    return re.sub(r"[^A-Z0-9]", "", description.upper())[:12] or "UNKNOWN"


def _holding_type(section: str, description: str) -> tuple[str, str, bool]:
    s = section.lower()
    d = description.lower()
    if description.upper() == "CASH" or "deposit" in d or "cash reserve" in d:
        return "Cash", "cash", True
    if "money market" in s:
        return "Mutual Fund", "money_market", True
    if "cds/equivalents" in s or "commercial paper" in d:
        return "Fixed Income", "cd_or_equivalent", False
    if "government" in s or "treasury" in d or "bond" in d:
        return "Fixed Income", "bond", False
    if "equities" in s:
        return "Equity", "stock", False
    if "mutual funds" in s:
        return "Mutual Fund", "fund", False
    if "options" in s or description.upper().startswith(("CALL ", "PUT ")):
        return "Option", "option", False
    if "alternative" in s:
        return "Alternative Investment", "alternative", False
    if re.search(r"\b[A-Z][A-Z0-9.]{0,9}\b", description) and _SYMBOL_RE.match(description.split()[-1]):
        return "Equity", "stock", False
    return "Security", "", False


def _parse_holding_line(line: str, section: str, account: str, statement_date: str) -> dict | None:
    if _HOLDING_STOP_RE.match(line) or "TRANSACTIONS" in line:
        return None
    if not _ASSET_SECTION_RE.match(line):
        return None

    nums = _NUM_RE.findall(line)
    if not nums:
        return None

    before = line[: line.find(nums[0])].strip()
    if not before:
        return None

    tokens = before.split()
    symbol = ""
    if len(tokens) >= 2 and _SYMBOL_RE.match(tokens[-1]):
        symbol = tokens[-1]
        description = " ".join(tokens[:-1])
    else:
        description = before
        symbol = _infer_symbol(description)

    values = [_amount(n) for n in nums]
    if any(v is None for v in values):
        return None
    if not values:
        return None

    quantity = values[0]
    price = None
    current_value = None
    cost_basis = None

    if len(values) > 8:
        return None
    if len(values) == 1:
        current_value = quantity
        quantity = None
    elif len(values) == 2:
        cost_basis, current_value = values
        quantity = values[0]
    elif len(values) >= 4:
        quantity = values[0]
        cost_basis = values[1]
        price = values[2]
        current_value = values[3]
    elif len(values) == 3:
        quantity, price, current_value = values

    if description.upper() == "CASH" and len(values) >= 3 and values[0] == values[1] == values[2]:
        quantity = None
        price = None
        cost_basis = None
        current_value = values[0]

    description = _clean_description(description)
    if not description:
        return None
    row = {
        "symbol": symbol,
        "description": description,
        "account": account,
        "accountType": _ACCOUNT_TYPE,
        "currency_code": _CURRENCY,
    }
    if quantity is not None:
        row["quantity"] = quantity
    if price is not None:
        row["price"] = price
    if current_value is not None:
        row["current_value"] = current_value
    if cost_basis is not None:
        row["cost_basis_total"] = cost_basis
    if statement_date:
        row["price_as_of"] = statement_date
    htype, subtype, is_cash = _holding_type(section, description)
    row["type"] = htype
    if subtype:
        row["subtype"] = subtype
    if is_cash:
        row["is_cash_equivalent"] = True
    cusip = _CUSIP_RE.search(line)
    if cusip:
        row["cusip"] = cusip.group(1)
        row["security_id"] = cusip.group(1)
        row["security_id_type"] = "CUSIP"
    return row


def _parse_holdings(lines: list[str], account: str, statement_date: str) -> list[dict]:
    holdings = []
    section = ""
    in_assets = False
    seen = set()
    for raw in lines:
        line = re.sub(r"\s+", " ", raw.strip())
        if not line:
            continue
        upper = line.upper()
        if "YOUR CMA ASSETS" in upper:
            in_assets = True
            continue
        if "YOUR CMA TRANSACTIONS" in upper or "YOUR CMA LIABILITIES" in upper:
            in_assets = False
        if not in_assets:
            continue
        for marker in (
            "CASH/MONEY ACCOUNTS", "OTHER MONEY MARKET MUTUAL FUNDS",
            "CDS/EQUIVALENTS", "GOVERNMENT AND AGENCY SECURITIES",
            "EQUITIES", "MUTUAL FUNDS/CLOSED END FUNDS/UITs/ETPs",
            "OTHER", "OPTIONS", "ALTERNATIVE INVESTMENTS",
        ):
            compact_marker = re.sub(r"[^A-Z]", "", marker.upper())
            compact_line = re.sub(r"[^A-Z]", "", upper)
            if compact_marker in compact_line:
                section = marker
                break
        row = _parse_holding_line(line, section, account, statement_date)
        if not row:
            continue
        key = (row["symbol"], row.get("quantity"), row.get("current_value"))
        if key in seen:
            continue
        seen.add(key)
        holdings.append(row)
    return holdings


def _make_brokerage_txn(
    row_date: str,
    description: str,
    amount: float,
    action: str,
    transaction_type: str,
    account: str,
    quantity: float | None = None,
    symbol: str = "",
    subtype: str = "",
) -> dict:
    row = {
        "date": row_date,
        "description": _clean_description(description),
        "amount": amount,
        "account": account,
        "accountType": _ACCOUNT_TYPE,
        "action": action,
        "transaction_type": transaction_type,
        "currency_code": _CURRENCY,
    }
    if subtype:
        row["subtype"] = subtype
    if symbol:
        row["symbol"] = symbol
    if quantity is not None:
        row["quantity"] = quantity
    return row


def _parse_income_txn(line: str, account: str, anchor: date | None) -> dict | None:
    match = _DATE_START_RE.match(line)
    if not match:
        return None
    row_date = _resolve_date(match.group("md"), anchor)
    if not row_date:
        return None
    rest = match.group("rest")
    for label, classification in _INCOME_ACTIONS.items():
        if label not in rest:
            continue
        amount_tokens = _NUM_RE.findall(rest)
        if not amount_tokens:
            return None
        amount = _amount(amount_tokens[-1])
        if amount is None:
            return None
        action, txn_type, subtype = classification
        description = rest.split(label, 1)[0] or rest
        return _make_brokerage_txn(
            row_date, description, amount, action, txn_type, account,
            symbol=_infer_symbol(description), subtype=subtype,
        )
    return None


def _parse_security_txn(line: str, account: str, anchor: date | None) -> dict | None:
    match = _DATE_START_RE.match(line)
    if not match:
        return None
    row_date = _resolve_date(match.group("md"), anchor)
    if not row_date:
        return None
    rest = match.group("rest")
    for label, (action, txn_type) in _SECURITY_ACTIONS.items():
        if label not in rest:
            continue
        amount_tokens = _NUM_RE.findall(rest)
        if not amount_tokens:
            return None
        amount = _amount(amount_tokens[-1])
        if amount is None:
            return None
        if txn_type == "buy" and amount > 0:
            amount = -amount
        qty = None
        prefix = rest.split(label, 1)[0]
        nums = _NUM_RE.findall(prefix)
        if nums:
            qty = _amount(nums[-1])
        description = prefix or rest
        return _make_brokerage_txn(
            row_date, description, amount, action, txn_type, account,
            quantity=qty, symbol=_infer_symbol(description),
        )
    return None


def _parse_cash_txn(line: str, account: str, anchor: date | None) -> dict | None:
    match = _DATE_START_RE.match(line)
    if not match:
        return None
    row_date = _resolve_date(match.group("md"), anchor)
    if not row_date:
        return None
    rest = match.group("rest")
    for label, subtype in _CASH_ACTIONS.items():
        if label not in rest:
            continue
        amount_tokens = _NUM_RE.findall(rest)
        if not amount_tokens:
            return None
        amount = _amount(amount_tokens[-1])
        if amount is None:
            return None
        if subtype in {"withdrawal", "fee", "tax", "interest"} and amount > 0:
            amount = -amount
        description = rest.split(label, 1)[0] or rest
        return {
            "date": row_date,
            "description": _clean_description(description or label),
            "amount": amount,
            "balance": None,
            "account": account,
            "accountType": "Cash Management",
        }
    return None


def _parse_money_account_txns(line: str, account: str, anchor: date | None) -> list[dict]:
    # Merrill prints these two-up on one line:
    # 12/03 ML BANK DEPOSIT PROGRAM 25,000.00 12/18 PREFERRED DEPOSIT 1,761.00
    rows = []
    pieces = re.split(r"(?=\b\d{1,2}/\d{1,2}\s+)", line)
    for piece in pieces:
        match = _DATE_START_RE.match(piece.strip())
        if not match:
            continue
        row_date = _resolve_date(match.group("md"), anchor)
        if not row_date:
            continue
        rest = match.group("rest")
        amount_tokens = _NUM_RE.findall(rest)
        if not amount_tokens:
            continue
        amount = _amount(amount_tokens[-1])
        if amount is None:
            continue
        description = rest[: rest.rfind(amount_tokens[-1])]
        rows.append({
            "date": row_date,
            "description": _clean_description(description),
            "amount": amount,
            "account": account,
            "accountType": _ACCOUNT_TYPE,
            "action": "Money Account Sweep",
            "transaction_type": "internal_transfer",
            "subtype": "cash_sweep",
            "currency_code": _CURRENCY,
        })
    return rows


def _parse_transactions(lines: list[str], account: str, anchor: date | None) -> tuple[list[dict], list[dict]]:
    brokerage_transactions: list[dict] = []
    cash_transactions: list[dict] = []
    section = ""
    seen = set()

    for raw in lines:
        line = re.sub(r"\s+", " ", raw.strip())
        if not line:
            continue
        upper = line.upper()
        if "DIVIDENDS" in upper and "INCOME TRANSACTIONS" in upper:
            section = "income"
            continue
        if "SECURITY TRANSACTIONS" in upper or "UNSETTLED TRADES" in upper or "WHEN ISSUE" in upper:
            section = "security"
            continue
        if "CASH" in upper and "OTHER" in upper and "TRANSACTIONS" in upper:
            section = "cash"
            continue
        if "ADVISORY" in upper and "FEES" in upper:
            section = "cash"
            continue
        if "VISA ACCESS CARD ACTIVITY" in upper or "CHECKS WRITTEN" in upper:
            section = "cash"
            continue
        if "YOUR CMA MONEY ACCOUNT TRANSACTIONS" in upper or "YOUR CMA MONEY FUND TRANSACTIONS" in upper:
            section = "money"
            continue
        if line.startswith(("Subtotal", "TOTAL", "NET TOTAL", "OPENING BALANCE", "CLOSING BALANCE")):
            continue

        produced: list[dict] = []
        cash = None
        if section == "income":
            txn = _parse_income_txn(line, account, anchor)
            if txn:
                produced.append(txn)
        elif section == "security":
            txn = _parse_security_txn(line, account, anchor)
            if txn:
                produced.append(txn)
        elif section == "cash":
            cash = _parse_cash_txn(line, account, anchor)
        elif section == "money":
            produced.extend(_parse_money_account_txns(line, account, anchor))

        if cash:
            key = ("cash", cash["date"], cash["description"], cash["amount"])
            if key not in seen:
                seen.add(key)
                cash_transactions.append(cash)
        for txn in produced:
            if not txn.get("description"):
                continue
            key = ("brokerage", txn["date"], txn["description"], txn["amount"], txn.get("action", ""))
            if key in seen:
                continue
            seen.add(key)
            brokerage_transactions.append(txn)

    return brokerage_transactions, cash_transactions


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    lines = text.splitlines()
    statement_date, anchor = _statement_date(text)
    account = _account(text)

    holdings = _parse_holdings(lines, account, statement_date)
    brokerage_transactions, cash_transactions = _parse_transactions(lines, account, anchor)

    return {
        "institution": _INSTITUTION,
        "statementDate": statement_date,
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": brokerage_transactions,
            "cash_transactions": cash_transactions,
        },
    }
