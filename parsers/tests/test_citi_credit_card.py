"""Citi monthly card statement in the layout Citi's own cards print
(citi_credit_card); the Costco Anywhere Visa and annual-summary cases are in
test_bank_pdf.py.

The demo statement is generated from invented data by
tests/generators/gen-citi-card-sample.py. The page texts in the unit tests
below are invented too: their shapes follow the statement's layout, their
names and figures come from no statement.
"""

from __future__ import annotations

import parser_common
import statement_checks
from conftest import approx
from institutions import citi_credit_card, citi_credit_card_family

DEMO = "citi-card-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "Citi"
    assert stmt.statement_date == "2027-01-10"
    assert stmt.raw["parser"] == {"id": "citi_credit_card", "tier": "verified", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 8
    assert {(r["account"], r["accountType"]) for r in rows} == {("7731", "Credit Card")}
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    assert "unread" not in {r["kind"] for r in results}

    # Date order across the year boundary; the November transaction was
    # posted in December.
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert rows[0]["date"] == "2026-11-29"
    assert rows[-1]["date"] == "2027-01-06"
    by_desc = {r["description"]: r for r in rows}
    assert approx(by_desc["ONLINE PAYMENT, THANK YOU"]["amount"], 500.00)
    assert by_desc["ONLINE PAYMENT, THANK YOU"]["date"] == "2026-12-15"  # its only date, the post date
    assert approx(by_desc["SAMPLE OUTFITTERS RETURN SPRINGFIELD IL"]["amount"], 18.25)
    assert approx(by_desc["TRAIN TICKETS ONLINE 800-555-0161 NY"]["amount"], -148.00)  # after the page break
    assert "BOOKSHOP ON MAIN SPRINGFIELD IL" in by_desc  # the second cardholder's
    assert approx(rows[-1]["balance"], -1267.06)


# --- invented page texts -----------------------------------------------------

def _pages(rows: list[str], summary: dict | None = None, period: str = "03/11/27-04/10/27",
           extra: list[str] | None = None) -> list[str]:
    s = {"Previous balance": "$400.00", "Payments": "-$400.00", "Credits": "-$0.00", "Purchases": "+$75.00",
         "Cash advances": "+$0.00", "Fees": "+$0.00", "Interest": "+$0.00", "New balance": "$75.00"}
    s.update(summary or {})
    first = "\n".join([
        "Billing Inquiries and Customer Service",
        "www.citicards.com Member Since 2019. Account number ending in: 4120",
        "APRIL STATEMENT",
        f"Billing Period: {period}",
        "Account Summary",
        f"Previous balance {s['Previous balance']}",
        f"Late Payment Warning: If we do not receive your Minimum Payment Payments {s['Payments']}",
        f"by the date listed above, you may have to pay a late fee of up to $41 Credits {s['Credits']}",
        f"Purchases {s['Purchases']}",
        f"Cash advances {s['Cash advances']}",
        f"Fees {s['Fees']}",
        f"Interest {s['Interest']}",
        f"New balance {s['New balance']}",
    ])
    table = "\n".join([
        "Page 3 of 3", "www.citicards.com Member Since 2019. Account number ending in: 4120", "TEST HOLDER",
        "Account Summary", "Trans. Post", "date date Description Amount", *rows,
        "Fees Charged", "Total fees charged in this billing period $0.00",
        "Interest Charged", "Total interest charged in this billing period $0.00",
        "2027 totals year-to-date", "Total fees charged in 2027 $35.00", "Total interest charged in 2027 $9.10",
        *(extra or []), "Interest charge calculation",
    ])
    return [first, table]


_ROWS = ["Payments, Credits and Adjustments", "03/20 ONLINE PAYMENT, THANK YOU -$400.00",
         "Standard Purchases", "03/14 03/15 FIRST STORE TOWN ST $50.00", "04/01 04/02 SECOND STORE TOWN ST $25.00"]


def _parse(pages: list[str]):
    out = citi_credit_card.parse(pages, "statement.pdf", None)
    parser_common.validate_parse_result(out, "citi_credit_card")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return out, results


def _failed(results) -> set[tuple[str, str]]:
    return {(r["kind"], r["label"]) for r in results if not r["ok"]}


def test_a_clean_statement_passes_every_check():
    out, results = _parse(_pages(_ROWS))
    assert len(out["transactions"]) == 3
    assert _failed(results) == set()
    # The year-to-date block's totals are not read as the period's.
    assert not any(c["kind"] == "sum" and c["label"] == "Fees Charged" for c in out["checks"])
    assert approx(out["transactions"][-1]["balance"], -75.00)


def test_a_credit_balance_and_no_payments():
    rows = ["Standard Purchases", "03/14 03/15 FIRST STORE TOWN ST $50.00", "04/01 04/02 SECOND STORE TOWN ST $25.00"]
    out, results = _parse(_pages(rows, {"Previous balance": "-$300.00", "Payments": "-$0.00",
                                        "New balance": "-$225.00"}))
    assert _failed(results) == set()
    # Citi owes the cardholder: a positive balance, money they have.
    assert approx(out["transactions"][-1]["balance"], 225.00)


def test_a_year_boundary_gives_late_posted_rows_the_year_before():
    rows = ["Payments, Credits and Adjustments", "12/20 ONLINE PAYMENT, THANK YOU -$400.00",
            "Standard Purchases", "11/30 12/09 FIRST STORE TOWN ST $50.00", "01/04 01/04 SECOND STORE TOWN ST $25.00"]
    out, results = _parse(_pages(rows, period="12/08/27-01/07/28"))
    assert [t["date"] for t in out["transactions"]] == ["2027-11-30", "2027-12-20", "2028-01-04"]
    assert _failed(results) == set()


def test_a_row_that_cannot_be_read_is_reported_not_read():
    rows = [r.replace("SECOND STORE TOWN ST $25.00", "SECOND STORE TOWN ST 25.00-") for r in _ROWS]
    out, results = _parse(_pages(rows))
    assert len(out["transactions"]) == 2
    assert ("unread", "Standard Purchases") in _failed(results)
    assert ("balance", "Account Summary") in _failed(results)
    # And a dated row after the table ends.
    _, results = _parse(_pages(_ROWS, extra=["04/05 04/05 STRAY ROW TOWN ST $1.00"]))
    assert _failed(results) == {("unread", "Transactions")}


def test_a_previous_balance_that_does_not_add_up_fails_only_the_balance_check():
    _, results = _parse(_pages(_ROWS, {"Previous balance": "$410.00"}))
    assert _failed(results) == {("balance", "Account Summary")}


def test_detect():
    pages = _pages(_ROWS)
    matched, reason = citi_credit_card.detect("\n".join(pages))
    assert matched and "monthly statement" in reason
    # The family module claims it too, but is tried after (PRIORITY).
    assert citi_credit_card_family.PRIORITY > 100
