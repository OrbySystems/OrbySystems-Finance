"""Meridian Card - the bundled example household's credit card.

Meridian Card does not exist, for the same reason Vantage Brokerage does
not: a fabricated household's records should not be shipped in a real
issuer's format. See tests/generators/gen-demo-household.py.

    MERIDIAN CARD
    Statement Closing Date: March 31, 2026
    Account Number: ****8814

    ACCOUNT SUMMARY
    Previous Balance 1,319.32
    Payments and Credits -1,319.32
    Purchases 1,318.17
    New Balance 1,318.17

    TRANSACTIONS
    Date Description Amount
    03/02 WHOLE EARTH MARKET 197.41
    03/11 MERIDIAN CARD AUTOPAY - THANK YOU -1,319.32

# The sign convention, which is the whole of the work here

The statement prints a charge as POSITIVE, because that is how the card's
own balance moves - a purchase increases what is owed. Orby signs every
amount by how it affects the money the account holder actually has, the
same way across every account type, so a charge is NEGATIVE and a payment
is positive.

Getting that backwards does not produce an error. It produces a spending
total with the right magnitude and the wrong sign, and a household that
appears to have earned money by buying groceries. So the rows are parsed
and reconciled in the statement's OWN signs first - Previous Balance plus
the transactions must equal New Balance, which is a check the statement
itself makes possible - and negated as the last step, once the arithmetic
has already proved the rows were read correctly.
"""

import re

from . import common

_HEADER_MARKER = "MERIDIAN CARD"
_INSTITUTION = "Meridian Card"
_ACCOUNT_TYPE = "Credit Card"

_NUM = r"-?[\d,]+\.\d{2}"
_CLOSING_RE = re.compile(r"Statement Closing Date:\s+(\w+)\s+(\d{1,2}),\s+(\d{4})")
_ACCOUNT_RE = re.compile(r"Account Number:\s*\*+(\d{3,4})")
_PERIOD_RE = re.compile(r"Billing Period:\s*(\d{2})/(\d{2})/(\d{4})")
_TXN_RE = re.compile(r"^(?P<md>\d{2}/\d{2})\s+(?P<desc>.+?)\s+(?P<amount>" + _NUM + r")\s*$")
_SUMMARY_RE = re.compile(r"^(?P<label>Previous Balance|Payments and Credits|Purchases|New Balance)"
                         r"\s+(?P<amount>" + _NUM + r")\s*$")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def detect(head_text: str) -> tuple[bool, str]:
    if _HEADER_MARKER not in head_text:
        return False, f"{_HEADER_MARKER!r} not found"
    if "Statement Closing Date" not in head_text:
        return False, "'Statement Closing Date' not found"
    return True, f"found {_HEADER_MARKER!r}"


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:
    text = "\n".join(pages_text)

    closing = ""
    m = _CLOSING_RE.search(text)
    if m and m.group(1) in _MONTHS:
        closing = f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"

    account = ""
    m = _ACCOUNT_RE.search(text)
    if m:
        account = common.last4_digits(m.group(1))

    # The year the billing period starts in, so "03/02" becomes a date.
    year = closing[:4] if closing else ""
    m = _PERIOD_RE.search(text)
    if m:
        year = m.group(3)

    summary = {}
    transactions = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SUMMARY_RE.match(line)
        if m:
            summary[m.group("label")] = common.parse_amount(m.group("amount"))
            continue
        m = _TXN_RE.match(line)
        if not m or not year:
            continue
        mm, dd = m.group("md").split("/")
        transactions.append({
            "date": f"{year}-{mm}-{dd}",
            "description": m.group("desc").strip(),
            "amount": common.parse_amount(m.group("amount")),
            "balance": None,
            "account": account,
            "accountType": _ACCOUNT_TYPE,
        })

    _reconcile(summary, transactions)
    # Last, once the arithmetic above has confirmed the rows were read
    # correctly in the statement's own signs.
    common.negate_amounts_and_balances(transactions)

    return {
        "institution": _INSTITUTION,
        "statementDate": closing,
        "transactions": transactions,
    }


def _reconcile(summary: dict, transactions: list[dict]) -> None:
    """Previous Balance + this period's rows must equal New Balance.

    Raises rather than warning. A credit-card statement that does not
    reconcile means a row was missed or double-read, and the resulting
    spending total is wrong by exactly that row while looking entirely
    plausible - which is worse than a failed import, because nothing
    downstream can tell.
    """
    previous = summary.get("Previous Balance")
    new = summary.get("New Balance")
    if previous is None or new is None:
        return
    got = round(previous + sum(t["amount"] for t in transactions), 2)
    if abs(got - new) > 0.01:
        raise ValueError(
            f"meridian_card: the statement does not reconcile - previous balance "
            f"{previous:,.2f} plus {len(transactions)} transactions comes to {got:,.2f}, "
            f"but the statement says the new balance is {new:,.2f}. A row was missed "
            f"or read twice.")
