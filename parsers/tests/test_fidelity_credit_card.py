"""Fidelity Rewards Visa credit card statement (fidelity_credit_card).

The demo statement is generated from invented data by
tests/generators/gen-fidelity-credit-card-sample.py. The page texts in
the unit tests below are invented too: their shapes follow the
statement's layout, their names and figures come from no statement.
"""

from __future__ import annotations

import parser_common
import statement_checks
from conftest import approx
from institutions import fidelity_credit_card

DEMO = "fidelity-credit-card-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "Fidelity Rewards Visa"
    assert stmt.statement_date == "2026-01-19"
    assert stmt.raw["parser"] == {"id": "fidelity_credit_card", "tier": "verified", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 11
    # Both cards' rows are the one account's.
    assert {(r["account"], r["accountType"]) for r in rows} == {("4417", "Credit Card")}

    # Every check holds, and nothing was left unread.
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    assert "unread" not in {r["kind"] for r in results}

    # Date order across the year boundary; the earliest is a transaction
    # dated before the period opened.
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert rows[0]["date"] == "2025-12-18"
    assert rows[-1]["date"] == "2026-01-14"
    assert not any(r["date"].startswith("2026-12") or r["date"].startswith("2025-01") for r in rows)

    by_desc = {r["description"]: r for r in rows}
    payment = by_desc["PAYMENT THANK YOU"]
    assert approx(payment["amount"], 1850.00) and payment["reference"] == "EP"
    credit = by_desc["PINE HARDWARE 800-555-0111 IL MERCHANDISE RETURN"]
    assert approx(credit["amount"], 22.50)
    grocer = by_desc["MAPLE STREET GROCERS SPRINGFIELD IL"]
    assert approx(grocer["amount"], -84.12) and grocer["reference"] == "0412"
    # Detail lines fold into the row above them, across none of the page
    # furniture.
    assert "FAKEAIR 0016789012345 FAKEAIR.COM TX TICKET 0016789012345 PASSENGER SAMPLE/PAT" in by_desc
    assert "CAFE ABROAD PARIS FR 45.00 EURO" in by_desc
    assert "BOOKSHOP ON MAIN SPRINGFIELD IL" in by_desc  # the second card's

    # The running balance ends on the statement's New Balance, negated.
    assert approx(rows[-1]["balance"], -971.47)


# --- invented page texts -----------------------------------------------------

def _pages(sections: list[str], summary: dict | None = None, close: str = "03/11/2027") -> list[str]:
    s = {"Previous Balance": "$500.00", "Payments": "$500.00CR", "Other Credits": "$0.00",
         "Purchases": "$120.00", "Balance Transfers": "$0.00", "Advances": "$0.00", "Other Debits": "$0.00",
         "Fees Charged": "$0.00", "Interest Charged": "$0.00", "New Balance": "$120.00"}
    s.update(summary or {})
    first = "\n".join([
        "March 2027 Statement Page 1 of 2",
        f"Open Date:02/10/2027 Closing Date:{close} Account ending in:7300",
        "Fidelity® Rewards Visa Signature® Card Example Financial Services 1-800-555-0100",
        f"New Balance {s['New Balance']} Activity Summary",
        f"Minimum Payment Due $25.00 Previous Balance + {s['Previous Balance']}",
        f"Payment Due Date 04/05/2027 Payments - {s['Payments']}",
        f"Other Credits - {s['Other Credits']}",
        f"Purchases + {s['Purchases']}",
        f"Balance Transfers {s['Balance Transfers']}",
        f"Advances {s['Advances']}",
        f"Other Debits {s['Other Debits']}",
        f"Fees Charged {s['Fees Charged']}",
        f"Interest Charged {s['Interest Charged']}",
        f"New Balance = {s['New Balance']}",
    ])
    second = "\n".join(["March 2027 Statement 02/10/2027 -03/11/2027 Page 2 of 2", "Transactions", *sections,
                        "2027 Totals Year-to-Date", "Interest Charge Calculation", "End of Statement"])
    return [first, second]


_HEADER = "Post Trans\nDate Date Ref # Transaction Description Amount"
_PAYMENTS = f"Account Payments and Credits\n{_HEADER}\n02/20 02/20 EP PAYMENT THANK YOU $500.00CR\nTOTAL THIS PERIOD $500.00CR"
_PURCHASES = (f"TEST H - 7300: Purchases and Other Debits\n{_HEADER}\n"
              "02/10 02/09 1001 FIRST STORE TOWN ST $70.00\n02/15 02/14 1002 SECOND STORE TOWN ST $50.00\n"
              "TOTAL THIS PERIOD $120.00")


def _parse(pages: list[str]):
    out = fidelity_credit_card.parse(pages, "statement.pdf", None)
    parser_common.validate_parse_result(out, "fidelity_credit_card")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return out, results


def _failed(results) -> set[tuple[str, str]]:
    return {(r["kind"], r["label"]) for r in results if not r["ok"]}


def test_a_clean_statement_passes_every_check():
    out, results = _parse(_pages([_PAYMENTS, _PURCHASES]))
    assert len(out["transactions"]) == 3
    assert _failed(results) == set()
    assert approx(out["transactions"][-1]["balance"], -120.00)


def test_fee_and_interest_rows_without_a_reference_keep_their_description():
    fees = f"Account Fees\n{_HEADER}\n03/11 03/11 LATE FEE $29.00\nTOTAL FEES THIS PERIOD $29.00"
    interest = f"Interest Charged\n{_HEADER}\n03/11 03/11 INTEREST CHARGE ON PURCHASES $1.25\nTOTAL INTEREST THIS PERIOD $1.25"
    out, results = _parse(_pages([_PAYMENTS, fees, _PURCHASES, interest],
                                 {"Fees Charged": "$29.00", "Interest Charged": "$1.25", "New Balance": "$150.25"}))
    assert _failed(results) == set()
    by_desc = {t["description"]: t for t in out["transactions"]}
    assert by_desc["LATE FEE"]["reference"] == "" and approx(by_desc["LATE FEE"]["amount"], -29.00)
    assert by_desc["INTEREST CHARGE ON PURCHASES"]["reference"] == ""


def test_a_row_that_cannot_be_read_is_reported_not_read():
    broken = _PURCHASES.replace("SECOND STORE TOWN ST $50.00", "SECOND STORE TOWN ST 50.00-")
    out, results = _parse(_pages([_PAYMENTS, broken]))
    assert len(out["transactions"]) == 2
    section = "Purchases and Other Debits (card ending 7300)"
    assert ("unread", section) in _failed(results)
    assert ("sum", section) in _failed(results)
    assert ("balance", "Activity Summary") in _failed(results)
    # The cardholder's name is not in any label.
    assert not any("TEST H" in c["label"] for c in out["checks"])


def test_a_row_under_a_heading_this_parser_does_not_know_is_reported_not_read():
    unknown = f"Cash Advances Detail\n{_HEADER}\n02/18 02/18 1003 CASH ADVANCE $40.00\nTOTAL THIS PERIOD $40.00"
    out, results = _parse(_pages([_PAYMENTS, _PURCHASES, unknown]))
    assert ("unread", "Transactions") in _failed(results)
    assert len(out["transactions"]) == 3


def test_a_previous_balance_that_does_not_add_up_fails_only_the_balance_check():
    _, results = _parse(_pages([_PAYMENTS, _PURCHASES], {"Previous Balance": "$600.00"}))
    assert _failed(results) == {("balance", "Activity Summary")}


def test_a_year_boundary_gives_december_rows_the_year_before():
    purchases = (f"TEST H - 7300: Purchases and Other Debits\n{_HEADER}\n"
                 "12/29 12/28 1001 FIRST STORE TOWN ST $70.00\n01/03 01/02 1002 SECOND STORE TOWN ST $50.00\n"
                 "TOTAL THIS PERIOD $120.00")
    payments = _PAYMENTS.replace("02/20 02/20", "01/04 01/04")
    out, results = _parse(_pages([payments, purchases], close="01/18/2028"))
    assert [t["date"] for t in out["transactions"]] == ["2027-12-28", "2028-01-02", "2028-01-04"]
    assert _failed(results) == set()


def test_detect():
    pages = _pages([_PAYMENTS, _PURCHASES])
    assert fidelity_credit_card.detect("\n".join(pages))[0]
    # A brokerage statement advertising the card is not a card statement.
    advert = "INVESTMENT REPORT\nEarn more with the Fidelity® Rewards Visa Signature® Card.\nAccount Summary"
    matched, reason = fidelity_credit_card.detect(advert)
    assert not matched and "Account ending in" in reason
