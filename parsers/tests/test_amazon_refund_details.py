"""Amazon's refund details export (csv_institutions/amazon_refund_details.py),
against a wholly invented export with the real one's columns."""

import pytest

from conftest import approx
from csv_institutions import amazon_refund_details

FIXTURE = "amazon-refund-details-synthetic-sample.csv"
ORDERS = "amazon-order-history-synthetic-sample.csv"


def _refunds(run_statement):
    stmt = run_statement(FIXTURE, "--expected-parser", "amazon_refund_details.py")
    assert stmt.institution == "Amazon" and stmt.statement_date == ""
    assert stmt.transactions == [] and stmt.brokerage_transactions == []
    return stmt.retail_items


def test_a_refund_is_money_back(run_statement):
    refund = _refunds(run_statement)[0]
    assert refund["date"] == "2026-03-22" and approx(refund["amount"], 136.78)
    assert refund["description"] == "Refund: Customer return"
    assert refund["order_id"] == "111-0000002-0000002" and refund["status"] == "Refunded"
    assert refund["charge_group"] == "111-0000002-0000002/refund/2026-03-22"
    assert all(r["line_type"] == "refund" and r["amount"] > 0 for r in _refunds(run_statement))


def test_the_exports_repeats_of_a_refund_are_one_refund(run_statement):
    twice = [r for r in _refunds(run_statement) if r["order_id"] == "111-0000003-0000003"]
    assert [(r["date"], r["amount"]) for r in twice] == [("2026-04-12", 9.80), ("2026-04-18", 4.5)]
    assert twice[1]["description"] == "Refund: Item shipped late"


def test_a_refund_not_yet_paid_is_left_out(run_statement):
    refunds = _refunds(run_statement)
    assert len(refunds) == 5
    assert all(r["order_id"] != "111-0000006-0000006" for r in refunds)


def test_another_countrys_store_is_named(run_statement):
    abroad = _refunds(run_statement)[-1]
    assert abroad["institution"] == "Amazon.in" and abroad["currency_code"] == "INR"
    assert approx(abroad["amount"], 1899.00)


def test_every_refund_names_an_order_that_was_bought(run_statement):
    bought = {i["order_id"] for i in run_statement(ORDERS, "--expected-parser", "amazon_order_history.py").retail_items}
    assert {r["order_id"] for r in _refunds(run_statement)} <= bought


def test_no_order_gets_back_more_than_it_cost(run_statement):
    spent, back = {}, {}
    for item in run_statement(ORDERS, "--expected-parser", "amazon_order_history.py").retail_items:
        spent[item["order_id"]] = spent.get(item["order_id"], 0.0) - item["amount"]
    for refund in _refunds(run_statement):
        back[refund["order_id"]] = back.get(refund["order_id"], 0.0) + refund["amount"]
    assert back and set(back) <= set(spent)
    for order_id, amount in back.items():
        assert amount <= spent[order_id] + 0.005, order_id


def test_a_refund_with_no_refund_date_is_dated_when_it_was_created(run_statement):
    undated = [r for r in _refunds(run_statement) if r["order_id"] == "111-0000001-0000001"]
    assert [(r["date"], r["amount"]) for r in undated] == [("2026-03-10", 19.49)]
    assert undated[0]["charge_group"] == "111-0000001-0000001/refund/2026-03-10"


def test_a_date_in_another_format_fails_the_file():
    row = {"Order ID": "111-0000001-0000001", "Payment Status": "Completed", "Refund Amount": "5.00",
           "Refund Date": "03/10/2026", "Creation Date": "03/10/2026"}
    with pytest.raises(ValueError, match="date format has changed"):
        amazon_refund_details.parse([row], "Refund Details.csv")
