"""ICICI Bank account statement (icici_bank_statement).

The demo statement is generated from invented data by
tests/generators/gen-icici-bank-sample.py. The page texts in the unit tests
below are invented too: their shapes follow the statement's layout, their
names and figures come from no statement.
"""

from __future__ import annotations

import pytest

import statement_checks
from conftest import approx
from institutions import icici_bank_statement as icici

DEMO = "icici-bank-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "ICICI Bank"
    assert stmt.statement_date == "2026-11-07"
    assert stmt.raw["parser"] == {"id": "icici_bank_statement", "tier": "provisional", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 9
    assert {(r["account"], r["accountType"], r["currency_code"]) for r in rows} == {
        ("4567", "Savings", "INR"), ("6677", "Savings", "INR")}

    # Every check holds, for each account.
    assert [(r["kind"], r["ok"]) for r in stmt.raw["checkResults"]] == [
        ("running", True), ("sum", True), ("sum", True), ("balance", True), ("balance", True)] * 2

    # Each amount signed by the balance it leaves; Indian digit grouping read.
    nre = [r for r in rows if r["account"] == "4567"]
    assert [round(r["amount"], 2) for r in nre] == [-1250.00, 85000.00, -10000.00, -25000.00, -3412.50, 1410.25, -35000.00]
    assert approx(nre[-1]["balance"], 151747.75)
    # Particulars that run on to the next line.
    assert nre[1]["description"] == "NEFT-HDFCN52026082011223344-ACME SOFTWARE PVT LTD-SALARY AUGUST 2026"
    # The account carries on to page 2 under the repeated column header.
    assert nre[4]["description"] == "BIL/ONL/000987654321/ELECTRICITY BOARD/MSEDCL"
    # The account's own number, wherever the particulars repeat it, down to its last four digits.
    assert nre[5]["description"] == "********4567:Int.Pd:30-06-2026 to 29-09-2026"
    assert not any("000101234567" in r["description"] or "000105556677" in r["description"] for r in rows)


def _statement(rows: list[str], currency: str = "INR", total: str = "TOTAL 100.00 50.00 1,050.00") -> list[str]:
    return [
        "ICICI BANK LTD.\nSummary of Accounts held under Cust ID: 900000001 as on November 07, 2026\n"
        "Savings - NRE A/c 000101234567 1,050.00 0.00 1,050.00 Registered\n"
        f"Statement of Transactions in Savings Account Number: 000101234567 in {currency} for the period "
        "August 07, 2026 - November 07, 2026\nDATE MODE** PARTICULARS DEPOSITS WITHDRAWALS BALANCE\n"
        "07-08-2026 B/F 1,000.00\n" + "\n".join(rows) + "\n" + total,
    ]


def _checks(out: dict) -> list[tuple[str, bool]]:
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return [(r["kind"], r["ok"]) for r in results]


def test_a_balance_that_does_not_follow_is_said_so():
    # The second row's balance follows neither a deposit nor a withdrawal.
    out = icici.parse(_statement(["12-08-2026 UPI/Grocery 50.00 950.00", "20-08-2026 NEFT/Salary 100.00 1,070.00"]),
                      "statement.pdf")
    assert ("running", False) in _checks(out)


def test_a_row_it_cannot_read_is_listed():
    out = icici.parse(_statement(["12-08-2026 UPI/Grocery 50.00 950.00", "20-08-2026 NEFT/Salary pending",
                                  "21-08-2026 NEFT/Salary 100.00 1,050.00"]), "statement.pdf")
    unread = next(c for c in out["checks"] if c["kind"] == "unread")
    assert [u["text"] for u in unread["lines"]] == ["20-08-2026 NEFT/Salary pending"]
    assert all(ok for kind, ok in _checks(out) if kind != "unread")


@pytest.mark.parametrize("printed, kept", [("INR", "INR"), ("USD", "USD"), ("XYZ", "INR")])
def test_the_currency_is_the_accounts_own(printed, kept):
    out = icici.parse(_statement(["12-08-2026 UPI/Grocery 50.00 950.00", "21-08-2026 NEFT/Salary 100.00 1,050.00"],
                                 printed), "statement.pdf")
    assert {t["currency_code"] for t in out["transactions"]} == {kept}


def test_detect():
    assert icici.detect("\n".join(_statement([])))[0]
    assert not icici.detect("HDFC BANK\nStatement of account\nDate Narration Withdrawal Amt. Deposit Amt. Closing Balance")[0]
