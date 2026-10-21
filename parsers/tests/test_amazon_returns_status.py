"""Amazon's returns status export (csv_institutions/amazon_returns_status.py),
against a wholly invented export with the real one's columns."""

from conftest import approx

FIXTURE = "amazon-returns-status-synthetic-sample.csv"
ORDERS = "amazon-order-history-synthetic-sample.csv"


def _returns(run_statement):
    stmt = run_statement(FIXTURE, "--expected-parser", "amazon_returns_status.py")
    assert stmt.institution == "Amazon" and stmt.statement_date == ""
    assert stmt.retail_items == [] and stmt.transactions == []
    return {r["return_id"]: r for r in stmt.raw["tables"]["retail_returns"]}


def test_one_row_per_return(run_statement):
    assert sorted(_returns(run_statement)) == ["RSAMPLE0002", "RSAMPLE0003", "RSAMPLE0006", "RSAMPLE0007", "RSAMPLE0008"]


def test_a_return_names_its_order_and_when_it_started(run_statement):
    r = _returns(run_statement)["RSAMPLE0006"]
    assert r["order_id"] == "111-0000006-0000006" and r["date"] == "2026-05-02" and r["returned_on"] == "2026-05-03"
    assert r["resolution"] == "refund" and r["state"] == "open" and r["charged_back"] is False
    assert r["reason"] == "Wrong item was sent" and r["currency_code"] == "USD" and approx(r["amount"], 13.08)


def test_a_units_repeated_rows_count_once_at_their_largest(run_statement):
    returns = _returns(run_statement)
    assert approx(returns["RSAMPLE0002"]["amount"], 136.78)
    assert approx(returns["RSAMPLE0003"]["amount"], 14.30) and returns["RSAMPLE0003"]["state"] == "closed"


def test_an_item_never_sent_back_after_an_advance_refund_was_charged_again(run_statement):
    r = _returns(run_statement)["RSAMPLE0007"]
    assert r["state"] == "expired" and r["charged_back"] is True and r["amount"] is None


def test_an_exchange_without_a_creation_date_is_dated_when_it_was_sent(run_statement):
    r = _returns(run_statement)["RSAMPLE0008"]
    assert r["resolution"] == "exchange" and r["date"] == "2026-06-15"


def test_every_return_names_an_order_that_was_bought(run_statement):
    bought = {i["order_id"] for i in run_statement(ORDERS, "--expected-parser", "amazon_order_history.py").retail_items}
    assert {r["order_id"] for r in _returns(run_statement).values()} <= bought
