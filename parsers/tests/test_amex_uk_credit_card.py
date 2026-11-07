"""American Express UK card statement (amex_uk_credit_card).

The demo statement is generated from invented data by
tests/generators/gen-amex-uk-card-sample.py. The page texts in the unit
tests below are invented too: their shapes follow the statement's layout,
their names and figures come from no statement.
"""

from __future__ import annotations

from datetime import date

import pytest

import parser_common
import statement_checks
from conftest import approx
from institutions import amex_uk_credit_card as amex_uk

DEMO = "amex-uk-card-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "American Express"
    assert stmt.statement_date == "2026-10-20"
    assert stmt.raw["parser"] == {"id": "amex_uk_credit_card", "tier": "provisional", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 11
    # The membership number's last four digits, the supplementary card's rows on the same account.
    assert {(r["account"], r["accountType"], r["currency_code"]) for r in rows} == {("1007", "Credit Card", "GBP")}

    # Every check holds, a cardholder total for each cardholder.
    assert [(r["kind"], r["label"], r["ok"]) for r in stmt.raw["checkResults"]] == [
        ("balance", "Account Summary", True), ("sum", "New Credits", True), ("sum", "New Debits", True),
        ("sum", "Cardholder total", True), ("sum", "Cardholder total", True)]

    by_text = {r["description"]: r for r in rows}
    # The repayment's CR alone on the line below it.
    assert approx(by_text["PAYMENT RECEIVED - THANK YOU"]["amount"], 1480.00)
    # A refund's CR run into the merchant's address line below it.
    assert approx(by_text["JOHN LEWIS OXFORD ST LONDON 1 Example Road London"]["amount"], 120.00)
    # A foreign purchase, its amount abroad carried on.
    assert approx(by_text["HOTEL LE MARAIS PARIS Euro 41.00"]["amount"], -35.50)
    # Payment instructions after the table are no description; the rows
    # carry on to the next page, then the supplementary cardholder's.
    assert by_text["PRET A MANGER LONDON"]["date"] == "2026-09-30"
    assert [r["description"] for r in rows][-2:] == ["BOOTS 1180 LONDON", "SHELL WANDSWORTH LONDON"]
    assert approx(rows[-1]["balance"], -174.03)


def test_a_row_takes_the_year_that_puts_it_in_the_period():
    end = date(2027, 1, 20)
    assert amex_uk._row_date("Dec", "22", end) == date(2026, 12, 22)
    assert amex_uk._row_date("Jan", "5", end) == date(2027, 1, 5)
    # Processed a few days after the period's end: still this year.
    assert amex_uk._row_date("Jan", "24", end) == date(2027, 1, 24)
    with pytest.raises(ValueError):
        amex_uk._row_date("Feb", "30", end)


def _statement(summary: str, rows: list[str], total: str = "0.00") -> list[str]:
    head = "Statement of Account\nPrepared for Membership Number Date\nALEX MORGAN xxxx-xxxxxx-31007 20/10/26\n"
    return [
        "American Express\nServices Europe Ltd.\n" + head
        + "Previous Closing Balance New Credits New Debits Closing Balance\n" + summary
        + "\nStatement Period From 21 September to 20 October 2026",
        head + "Transaction Process\nDate Date Transaction Details Foreign Spending Amount £\n" + "\n".join(rows)
        + "\nTotal new spend transactions for ALEX MORGAN " + total,
    ]


def _checks(out: dict) -> list[tuple[str, str, bool]]:
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return [(r["kind"], r["label"], r["ok"]) for r in results]


def test_a_credit_on_its_rows_own_line():
    out = amex_uk.parse(_statement("£214.00 - £214.00 + £0.00 = £0.00",
                                   ["Oct 7 Oct 8 BRITISH AIRWAYS LONDON 214.00 CR"], "214.00 CR"), "statement.pdf")
    assert approx(out["transactions"][0]["amount"], 214.00)
    assert all(ok for _, _, ok in _checks(out))


@pytest.mark.parametrize("summary", ["£40.00CR - £0.00 + £12.00 = £28.00CR", "£40.00 - £0.00 + £12.00 = £28.00"])
def test_a_balance_in_credit_takes_the_sign_its_summary_gives(summary):
    # £40.00 in credit, £12.00 spent: £28.00 in credit, CR printed beside the
    # figures or below them, where the line read here doesn't show it.
    out = amex_uk.parse(_statement(summary, ["Oct 7 Oct 8 TESCO STORES LONDON 12.00"], "12.00"), "statement.pdf")
    balance = next(c for c in out["checks"] if c["kind"] == "balance")
    assert approx(balance["opening"], 40.00) and approx(balance["closing"], 28.00)
    assert ("balance", "Account Summary", True) in _checks(out)


def test_an_account_summary_it_cannot_read_is_said_so():
    out = amex_uk.parse(_statement("see overleaf", ["Oct 7 Oct 8 TESCO STORES LONDON 12.00"]), "statement.pdf")
    assert next(c for c in out["checks"] if c["kind"] == "unread")["lines"][0]["text"] == "see overleaf"
    with pytest.raises(parser_common.ParserDiagnosticError):
        amex_uk.parse([p.replace("Previous Closing Balance New Credits New Debits Closing Balance\n", "")
                       for p in _statement("£0.00 - £0.00 + £0.00 = £0.00", [])], "statement.pdf")


def test_detect_takes_a_uk_statement_of_account_only():
    assert amex_uk.detect("\n".join(_statement("£0.00 - £0.00 + £0.00 = £0.00", [])))[0]
    us = "American Express\nAccount Ending 1-01007\nNew Balance $1,234.56\nPrevious Balance $1,000.00"
    assert not amex_uk.detect(us)[0]
