"""American Express card activity, downloaded as CSV (Statements & Activity
> Download), with "Include all additional transaction details" ticked:
Date, Description, Card Member, Account #, Amount, Extended Details,
Appears On Your Statement As, Address, City/State, Zip Code, Country,
Reference, Category. An older download has the same less Card Member and
Account #. The plain download (Date, Description, Amount alone) is not
claimed: any file can have that header. Ticking the box gives the detailed
one.

This is the US download: its address columns are City/State and Zip
Code, and its amounts dollars. Another country's (Town/City, Postcode, day
first dates, another currency) is not claimed, rather than read as dollars
on the wrong days.

Amounts are written as the card's balance moves - a charge positive, a
payment or a credit negative - read in that sign, then negated as the last
step (common.negate_amounts_and_balances). Dates are month first
(03/05/2024). Account # is a card's last five digits ("-21004"). An
additional card's charges are billed to the account its payments are made
to, so every row of the file files under the card the payments arrive on
(or the card most rows are, in a file with no payment): one account, as its
statement is. A download without Account # names no account, and the
import asks which one it is.
"""

from institutions import common

import app_export
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED

INSTITUTION = "American Express"

_HEADER = {"Date", "Description", "Amount", "Extended Details", "Appears On Your Statement As", "City/State", "Zip Code"}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    cols = {h.strip() for h in header}
    missing = _HEADER - cols
    if missing:
        return False, f"missing column(s) {sorted(missing)}"
    return True, "American Express activity export header matched"


def _billing_card(rows: list[dict[str, str]]) -> str:
    """The card a file's rows are billed to: the one its payments arrive on,
    else the one most rows are."""
    def card(r):
        return common.last4_digits(r.get("Account #") or "")
    paid = [card(r) for r in rows if "PAYMENT" in (r.get("Description") or "").upper()
            and (r.get("Amount") or "").strip().startswith("-") and card(r)]
    cards = paid or [card(r) for r in rows if card(r)]
    return max(set(cards), key=cards.count) if cards else ""


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
    account = _billing_card(rows)
    transactions = []
    for n, row in enumerate(rows, start=2):
        raw = (row.get("Amount") or "").strip()
        if not raw:
            raise ValueError(f"row {n}: no amount")
        description = " ".join((row.get("Description") or "").split()) or " ".join((row.get("Appears On Your Statement As") or "").split())
        if not description:
            raise ValueError(f"row {n}: no description")
        txn = {
            "date": app_export.date(row["Date"], "mdy"),
            "description": description,
            "amount": app_export.money(raw),
            "balance": None,
            "account": account,
            "accountType": "Credit Card",
        }
        reference = (row.get("Reference") or "").strip().strip("'\"")
        if reference:
            txn["reference"] = reference
        transactions.append(txn)
    common.negate_amounts_and_balances(transactions)
    return {"institution": INSTITUTION, "statementDate": "", "transactions": transactions}
