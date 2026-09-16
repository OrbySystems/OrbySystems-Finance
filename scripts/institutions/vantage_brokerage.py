"""Vantage Brokerage - the bundled example household's custodian.

Vantage Brokerage does not exist. It is invented, like the household whose
statements this reads, and it has its own format for a deliberate reason:
generating a fabricated household's records in a REAL custodian's layout
would be a bad thing to ship with the product, however synthetic the
numbers. The fixtures live in demo/ and are produced by
tests/generators/gen-demo-household.py.

The layout is one statement covering several accounts, each with a
holdings table and an activity table:

    VANTAGE BROKERAGE SERVICES
    Statement Period: March 1, 2026 - March 31, 2026

    Account Number: VB-2041
    Account Type: Individual

    HOLDINGS
    Symbol Description Quantity Price Market Value Cost Basis Est Annual Income
    BND VANGUARD TOTAL BOND MARKET ETF 4,200.000 73.40 308,280.00 315,000.00 11,837.95

    ACTIVITY
    Date Type Symbol Description Quantity Price Amount
    03/12/2026 Buy VTI VANGUARD TOTAL STOCK MARKET ETF 9.000 302.10 -2,718.90
    03/22/2026 Dividend BND VANGUARD TOTAL BOND MARKET ETF 2,959.49
    03/27/2026 Withdrawal ACH WITHDRAWAL - TRANSFER TO BANK -1,518.51

Every activity row sets `transaction_type` from the closed vocabulary in
scripts/transaction_vocabulary.json rather than relying on `action` alone.
That is the point of the vocabulary: money entering or leaving has to be
recognisable as such, because every growth figure Orby reports is computed
net of it, and a contribution nothing recognises is reported as investment
gain. A parser written today has no excuse for leaving that to convention.
"""

import re

from . import common

KIND = "brokerage"

_HEADER_MARKER = "VANTAGE BROKERAGE SERVICES"
_INSTITUTION = "Vantage Brokerage"

_PERIOD_RE = re.compile(
    r"Statement Period:\s+\w+\s+\d{1,2},\s+\d{4}\s*-\s*(\w+)\s+(\d{1,2}),\s+(\d{4})")
_ACCOUNT_RE = re.compile(r"Account Number:\s*VB-(\d+)")
_TYPE_RE = re.compile(r"Account Type:\s*(.+?)\s*$")

_NUM = r"-?[\d,]+\.\d{2}"
_QTY = r"-?[\d,]+\.\d{3}"

# Symbol, description, then exactly five figures.
_HOLDING_RE = re.compile(
    r"^(?P<symbol>[A-Z][A-Z0-9.]{0,9})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<quantity>" + _QTY + r")\s+"
    r"(?P<price>" + _NUM + r")\s+"
    r"(?P<value>" + _NUM + r")\s+"
    r"(?P<basis>" + _NUM + r")\s+"
    r"(?P<income>" + _NUM + r")\s*$")

# A trade carries a symbol, a quantity and a price; a cash movement
# carries none of them. Two patterns rather than one forgiving one,
# because a single pattern that tolerated missing columns would happily
# read a deposit's amount as a quantity.
_TRADE_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<action>Buy|Sell)\s+"
    r"(?P<symbol>[A-Z][A-Z0-9.]{0,9})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<quantity>" + _QTY + r")\s+"
    r"(?P<price>" + _NUM + r")\s+"
    r"(?P<amount>" + _NUM + r")\s*$")

_INCOME_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<action>Dividend|Interest)\s+"
    r"(?P<symbol>[A-Z][A-Z0-9.]{0,9})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<amount>" + _NUM + r")\s*$")

_CASH_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<action>Deposit|Withdrawal)\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<amount>" + _NUM + r")\s*$")

# The classification each action means, from the shared vocabulary.
_TRANSACTION_TYPES = {
    "Buy": "buy",
    "Sell": "sell",
    "Dividend": "dividend",
    "Interest": "interest",
    "Deposit": "deposit",
    "Withdrawal": "withdrawal",
}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def detect(head_text: str) -> tuple[bool, str]:
    if _HEADER_MARKER not in head_text:
        return False, f"{_HEADER_MARKER!r} not found"
    return True, f"found {_HEADER_MARKER!r}"


def _statement_date(text: str) -> str:
    m = _PERIOD_RE.search(text)
    if not m:
        return ""
    month = _MONTHS.get(m.group(1))
    if not month:
        return ""
    return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"


def _iso(date_str: str) -> str:
    mm, dd, yyyy = date_str.split("/")
    return f"{yyyy}-{mm}-{dd}"


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    statement_date = _statement_date(text)

    holdings: list[dict] = []
    transactions: list[dict] = []

    account = ""
    account_type = ""
    section = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = _ACCOUNT_RE.search(line)
        if m:
            account = m.group(1)
            section = ""
            continue
        if line.startswith("Account Type:"):
            m = _TYPE_RE.search(line)
            if m:
                # Normalized through the shared table, so "Rollover IRA"
                # means the same thing here as it does in every other
                # parser - and so its tax treatment is not this file's
                # opinion.
                account_type = common.classify_account_type(m.group(1), m.group(1))
            continue
        if line == "HOLDINGS":
            section = "holdings"
            continue
        if line == "ACTIVITY":
            section = "activity"
            continue
        if line.startswith(("Symbol ", "Date ", "Total Account Value", "-", "No activity")):
            continue

        if section == "holdings":
            m = _HOLDING_RE.match(line)
            if not m:
                continue
            holdings.append({
                "symbol": m.group("symbol"),
                "description": m.group("desc").strip(),
                "quantity": common.parse_amount(m.group("quantity")),
                "price": common.parse_amount(m.group("price")),
                "current_value": common.parse_amount(m.group("value")),
                "cost_basis_total": common.parse_amount(m.group("basis")),
                "estimated_annual_income": common.parse_amount(m.group("income")),
                "account": account,
                "accountType": account_type,
                "institution": _INSTITUTION,
            })
            continue

        if section == "activity":
            row = _activity_row(line, account, account_type)
            if row:
                transactions.append(row)

    return {
        "institution": _INSTITUTION,
        "statementDate": statement_date,
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": transactions,
        },
    }


def _activity_row(line: str, account: str, account_type: str) -> dict | None:
    """One activity line, or None when nothing recognises it.

    Order matters: the trade pattern is tried first because it is the most
    specific, and a cash pattern tried first would match a trade's line and
    read its price as the amount.
    """
    m = _TRADE_RE.match(line)
    if m:
        action = m.group("action")
        return _row(m, action, symbol=m.group("symbol"),
                    quantity=common.parse_amount(m.group("quantity")),
                    price=common.parse_amount(m.group("price")),
                    account=account, account_type=account_type)

    m = _INCOME_RE.match(line)
    if m:
        return _row(m, m.group("action"), symbol=m.group("symbol"),
                    account=account, account_type=account_type)

    m = _CASH_RE.match(line)
    if m:
        return _row(m, m.group("action"), symbol="",
                    account=account, account_type=account_type)
    return None


def _row(m, action: str, *, symbol: str, account: str, account_type: str,
         quantity: float | None = None, price: float | None = None) -> dict:
    row = {
        "date": _iso(m.group("date")),
        "description": m.group("desc").strip(),
        "amount": common.parse_amount(m.group("amount")),
        "account": account,
        "accountType": account_type,
        "action": action,
        # Set, never omitted. An unclassified row falls back to being
        # matched on its action alone, and a word nobody has classified
        # counts as investment gain rather than as money moving.
        "transaction_type": _TRANSACTION_TYPES[action],
        "institution": _INSTITUTION,
        "currency_code": "USD",
    }
    if symbol:
        row["symbol"] = symbol
    if quantity is not None:
        row["quantity"] = quantity
    if price is not None:
        row["price"] = price
    return row
