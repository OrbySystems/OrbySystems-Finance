"""Apple Card statement (apple_card).

The demo statement is generated from invented data by
tests/generators/gen-apple-card-sample.py. The page texts in the unit tests
below are invented too: their shapes follow the statement's layout, their
names and figures come from no statement.
"""

from __future__ import annotations

import parser_common
import statement_checks
from conftest import approx
from institutions import apple_card

DEMO = "apple-card-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "Apple Card"
    assert stmt.statement_date == "2026-09-30"
    assert stmt.raw["parser"] == {"id": "apple_card", "tier": "verified", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 10
    # The statement prints no card number: the app asks which account it is.
    assert {(r["account"], r["accountType"]) for r in rows} == {("", "Credit Card")}

    # Every check holds, and nothing was left unread.
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    assert "unread" not in {r["kind"] for r in results}
    assert {(r["kind"], r["label"]) for r in results} >= {("sum", "Payments"), ("sum", "Transactions"),
                                                          ("balance", "Total Balance")}

    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    by_desc = {r["description"]: r for r in rows}
    # Signed by what the holder has: the payment and the return add to it.
    assert approx(by_desc["ACH Deposit Internet transfer from account ending in 5521"]["amount"], 412.37)
    assert approx(by_desc["MAPLE STREET GROCERS 12 MAIN ST SPRINGFIELD 62701 IL USA"]["amount"], -84.12)
    returned = [r for r in rows if r["description"].startswith("PINE HARDWARE") and r["amount"] > 0]
    assert len(returned) == 1 and approx(returned[0]["amount"], 22.50)
    # The rows after the page break, under the reprinted column header.
    assert "CAFE ABROAD 3 RUE EXEMPLE PARIS 75001 FRA" in by_desc
    # Daily Cash is not a row, and its figures are not in any description.
    assert not any("%" in r["description"] or "Daily Cash" in r["description"] for r in rows)

    # The running balance starts from the Previous Total Balance and ends on
    # the Total Balance, negated.
    assert rows[0]["balance"] == 0.0 and str(rows[0]["balance"]) == "0.0"
    assert approx(rows[-1]["balance"], -359.07)


# --- invented page texts -----------------------------------------------------

_HEADER = "Statement\nApple Card Customer\nTest Holder, holder@example.com Mar 1 — Mar 31, 2027"


def _pages(payments: str, transactions: str, *, previous: str = "$200.00", total: str = "$80.00",
           interest: str = "$0.00", interest_rows: str = "— $0.00") -> list[str]:
    summary = "\n".join([
        _HEADER,
        "Your March Balance Minimum Payment",
        "as of Mar 31, 2027 Payment Due Due By",
        f"{total} $25.00 Apr 30, 2027",
        "Please go to Wallet or card.apple.com to schedule new payments.",
        f"Previous Monthly Balance {previous}",
        "as of Feb 28, 2027",
        f"Previous Total Balance {previous}",
        "as of Feb 28, 2027",
        f"Total Balance {total}",
        "as of Mar 31, 2027",
        "Apple Card is issued by Example Bank USA.",
        "Page 1 /3",
    ])
    activity = "\n".join([_HEADER, payments, transactions, "Page 2 /3"])
    cash = "\n".join([_HEADER, "Daily Cash", "Daily Cash from Apple Card $1.60", "Total Daily Cash $1.60",
                      "Interest Charged", interest_rows, f"Total interest for this month {interest}", "Page 3 /3"])
    return [summary, activity, cash]


_PAYMENTS = ("Payments\nDate Description Amount\n"
             "03/02/2027 ACH Deposit Internet transfer from account ending in 0001 -$200.00\n"
             "Total payments for this period -$200.00")
_TRANSACTIONS = ("Transactions\nDate Description Daily Cash Amount\n"
                 "03/05/2027 FIRST STORE 1 MAIN ST TOWN 00001 ST USA 2% $1.00 $50.00\n"
                 "03/09/2027 SECOND STORE 2 MAIN ST TOWN 00001 ST USA 2% $0.60 $30.00\n"
                 "Total Daily Cash this month $1.60\n"
                 "Total charges, credits and returns $80.00")


def _parse(pages: list[str]):
    out = apple_card.parse(pages, "statement.pdf", None)
    parser_common.validate_parse_result(out, "apple_card")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return out, results


def _failed(results) -> set[tuple[str, str]]:
    return {(r["kind"], r["label"]) for r in results if not r["ok"]}


def test_a_clean_statement_passes_every_check():
    out, results = _parse(_pages(_PAYMENTS, _TRANSACTIONS))
    assert out["statementDate"] == "2027-03-31"
    assert [t["amount"] for t in out["transactions"]] == [200.00, -50.00, -30.00]
    assert _failed(results) == set()
    assert approx(out["transactions"][-1]["balance"], -80.00)


def test_a_row_that_cannot_be_read_is_reported_not_read():
    broken = _TRANSACTIONS.replace("2% $0.60 $30.00", "2% $0.60 30.00-")
    out, results = _parse(_pages(_PAYMENTS, broken))
    assert len(out["transactions"]) == 2
    assert {("unread", "Transactions"), ("sum", "Transactions"), ("balance", "Total Balance")} <= _failed(results)


def test_a_dated_line_under_a_heading_this_parser_does_not_know_is_reported_not_read():
    unknown = _TRANSACTIONS + "\nSomething New\nWhen What How Much\n03/20/2027 SOMETHING NEW $10.00"
    out, results = _parse(_pages(_PAYMENTS, unknown, total="$90.00"))
    assert len(out["transactions"]) == 3
    assert ("unread", "Transactions") in _failed(results)
    assert ("balance", "Total Balance") in _failed(results)


def test_a_previous_balance_that_does_not_add_up_fails_only_the_balance_check():
    _, results = _parse(_pages(_PAYMENTS, _TRANSACTIONS, previous="$250.00"))
    assert _failed(results) == {("balance", "Total Balance")}


def test_a_table_broken_across_a_page_goes_on_without_its_header_reprinted():
    first, second = _TRANSACTIONS.split("\n03/09/2027")
    pages = _pages(_PAYMENTS, first)
    pages.insert(2, "\n".join([_HEADER, "03/09/2027" + second, "Page 3 /4"]))
    out, results = _parse(pages)
    assert len(out["transactions"]) == 3
    assert _failed(results) == set()


def test_interest_printed_in_no_row_of_its_own_is_added_from_the_months_total():
    out, results = _parse(_pages(_PAYMENTS, _TRANSACTIONS, total="$83.21", interest="$3.21", interest_rows="— $3.21"))
    interest = [t for t in out["transactions"] if t["description"] == "Interest Charged"]
    assert len(interest) == 1
    assert interest[0]["date"] == "2027-03-31" and approx(interest[0]["amount"], -3.21)
    assert _failed(results) == set()
    assert approx(out["transactions"][-1]["balance"], -83.21)


def test_interest_already_in_a_row_is_not_added_twice():
    row = "03/31/2027 Interest charged on purchases $3.21"
    out, results = _parse(_pages(_PAYMENTS, _TRANSACTIONS, total="$83.21", interest="$3.21", interest_rows=row))
    assert [t["description"] for t in out["transactions"]].count("Interest charged on purchases") == 1
    assert "Interest Charged" not in [t["description"] for t in out["transactions"]]
    assert _failed(results) == set()


def test_interest_that_does_not_close_the_balance_is_not_invented():
    # The rows fall short by more than the month's interest: nothing is
    # added, and the balance check says the statement doesn't add up.
    out, results = _parse(_pages(_PAYMENTS, _TRANSACTIONS, total="$90.00", interest="$3.21", interest_rows="— $3.21"))
    assert "Interest Charged" not in [t["description"] for t in out["transactions"]]
    assert ("balance", "Total Balance") in _failed(results)


def test_detect():
    pages = _pages(_PAYMENTS, _TRANSACTIONS)
    assert apple_card.detect("\n".join(pages))[0]
    # A page 1 alone still matches, by the card's own address.
    assert apple_card.detect(pages[0])[0]
    # Not a card statement: a savings statement mentioning the card.
    savings = "Savings Statement\nYour Daily Cash from Apple Card was deposited.\nMar 1 — Mar 31, 2027\nInterest Paid"
    matched, reason = apple_card.detect(savings)
    assert not matched and "Minimum Payment" in reason
    assert not apple_card.detect("Statement\nMinimum Payment Due\nPrevious Balance")[0]
