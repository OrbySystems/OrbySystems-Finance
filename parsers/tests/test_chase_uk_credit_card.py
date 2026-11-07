"""Chase UK credit card statement (chase_uk_credit_card).

The demo statement is generated from invented data by
tests/generators/gen-chase-uk-card-sample.py. The page texts in the unit
tests below are invented too: their shapes follow the statement's layout,
their names and figures come from no statement.
"""

from __future__ import annotations

import pytest

import parser_common
import statement_checks
from conftest import approx
from institutions import chase_uk_credit_card as chase_uk

DEMO = "chase-uk-card-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "Chase UK"
    assert stmt.statement_date == "2026-10-03"
    assert stmt.raw["parser"] == {"id": "chase_uk_credit_card", "tier": "provisional", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 13
    # The statement prints no card number: the app asks for one on import.
    assert {(r["account"], r["accountType"], r["currency_code"]) for r in rows} == {("", "Credit Card", "GBP")}

    # Every check holds, and nothing was left unread.
    assert [(r["kind"], r["label"], r["ok"]) for r in stmt.raw["checkResults"]] == [
        ("balance", "Transactions", True), ("sum", "Money in", True), ("sum", "Money out, interest & fees", True)]

    by_day = {r["date"]: r for r in rows}
    # Money out negative, money in ("+") positive, interest a charge.
    assert approx(by_day["2026-09-04"]["amount"], -41.30)
    assert by_day["2026-09-12"]["description"] == "Amazon.co.uk - Refund"
    assert approx(by_day["2026-09-12"]["amount"], 18.00)
    assert approx(by_day["2026-09-27"]["amount"], 1250.00)
    assert approx(by_day["2026-10-02"]["amount"], -2.15)
    # A merchant's name wrapped onto a second line, which the text layer
    # runs into the amount below it.
    assert by_day["2026-09-05"]["description"] == "Sainsbury's Supermarkets Ltd Holborn Circus Kingsway Branch London WC2"
    assert approx(by_day["2026-09-05"]["amount"], -57.12)
    # A foreign purchase keeps its amount abroad and the rate.
    assert by_day["2026-09-15"]["description"] == "Hotel Le Marais - Purchase | EUR 360.82 | FX rate £1 = EUR 1.1550"
    # The rows carry on to the next page; the closing balance is no row.
    assert [r["date"] for r in rows][-2:] == ["2026-10-01", "2026-10-02"]
    assert approx(rows[-1]["balance"], -569.85)


def _statement(summary: str, rows: list[str], closing: str) -> list[str]:
    """Invented page texts in the statement's shape."""
    return [
        "'Support' section of the Chase app.\nYour credit card statement\n"
        "Statement date: 03 Oct 2026 Available credit: £5,000.00\nStatement period: 03 Sep 2026 - 02 Oct 2026",
        "Transactions\n" + summary + "\nDate Transaction details Amount\n" + "\n".join(rows)
        + "\n03 Oct 2026 Closing balance\n" + closing + "\nPage 2 of 2",
    ]


def _checks(out: dict) -> list[tuple[str, bool]]:
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return [(r["kind"], r["ok"]) for r in results]


SUMMARY_HEADER = "Opening balance Money out Money in Interest & fees Closing balance"
ROWS = ["04 Sep 2026 Tesco Stores", "£41.30", "Purchase",
        "12 Sep 2026 Amazon.co.uk", "+£18.00", "Refund",
        "27 Sep 2026 From Alex Morgan", "+£100.00", "Repayment"]


@pytest.mark.parametrize("closing", ["-£26.70", "£-26.70", "£26.70"])
def test_a_balance_in_credit_takes_the_sign_its_summary_gives(closing):
    # £50.00 owed, £41.30 spent, £118.00 paid in: £26.70 in credit, however
    # the closing figure is printed - with its minus, or none at all.
    out = chase_uk.parse(_statement(f"{SUMMARY_HEADER}\n£50.00 + £41.30 - £118.00 + £0.00 = {closing}", ROWS, closing),
                         "statement.pdf")
    balance = next(c for c in out["checks"] if c["kind"] == "balance")
    assert approx(balance["opening"], -50.00) and approx(balance["closing"], 26.70)
    assert _checks(out) == [("balance", True), ("sum", True), ("sum", True)]


def test_a_summary_it_cannot_read_is_said_so():
    # Figures it can't read: the line is unread, so the import isn't clean.
    out = chase_uk.parse(_statement(f"{SUMMARY_HEADER}\nsee overleaf", ROWS, "£26.70"), "statement.pdf")
    assert [c["kind"] for c in out["checks"]] == ["unread"]
    assert out["checks"][0]["lines"][0]["text"] == "see overleaf"
    # No summary at all: no check would hold the rows to anything.
    with pytest.raises(parser_common.ParserDiagnosticError):
        chase_uk.parse(_statement("", ROWS, "£26.70"), "statement.pdf")


def test_a_row_without_its_amount_is_listed_once():
    rows = ["04 Sep 2026 Tesco Stores", "Purchase"] + ROWS[3:]
    out = chase_uk.parse(_statement(f"{SUMMARY_HEADER}\n£50.00 + £41.30 - £118.00 + £0.00 = £26.70", rows, "£26.70"),
                         "statement.pdf")
    unread = next(c for c in out["checks"] if c["kind"] == "unread")
    assert [u["text"] for u in unread["lines"]] == ["04 Sep 2026 Tesco Stores"]


def test_detect_takes_a_chase_uk_statement_and_no_us_one():
    head = "\n".join(_statement(f"{SUMMARY_HEADER}\n£50.00 + £0.00 - £0.00 + £0.00 = £50.00", [], "£50.00"))
    assert chase_uk.detect(head)[0]
    us = "Manage your account online at chase.com\nOpening/Closing Date 06/22/26 - 07/21/26\nPrevious Balance $1,000.00"
    matched, reason = chase_uk.detect(us)
    assert not matched and "Your credit card statement" in reason
