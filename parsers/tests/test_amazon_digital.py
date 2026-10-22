"""Amazon's digital orders and digital returns exports
(csv_institutions/amazon_digital_orders.py, amazon_digital_returns.py),
against wholly invented exports with the real ones' columns."""

from conftest import approx

ORDERS = "amazon-digital-orders-synthetic-sample.csv"
RETURNS = "amazon-digital-returns-synthetic-sample.csv"


def _orders(run_statement):
    stmt = run_statement(ORDERS, "--expected-parser", "amazon_digital_orders.py")
    assert stmt.institution == "Amazon" and stmt.statement_date == ""
    return {i["item_id"]: i for i in stmt.retail_items}


def test_each_paid_item_is_one_digital_purchase(run_statement):
    items = _orders(run_statement)
    assert sorted(items) == ["B0DIGI0001", "B0DIGI0002", "B0DIGI0003", "B0DIGI0007"]
    assert all(i["line_type"] == "purchase" and i["digital"] is True and i["amount"] < 0 for i in items.values())
    book = items["B0DIGI0001"]
    assert book["date"] == "2026-03-04" and approx(book["amount"], -9.99)
    assert book["description"] == "The Quiet Orchard (Kindle Edition)" and book["order_id"] == "D01-0000001-0000001"
    assert "payment_method" not in book


def test_a_coupon_comes_off_the_price(run_statement):
    item = _orders(run_statement)["B0DIGI0002"]
    assert approx(item["amount"], -11.99) and approx(item["unit_price"], 14.99) and approx(item["discount"], -3.0)


def test_tax_is_counted_and_audible_is_named(run_statement):
    item = _orders(run_statement)["B0DIGI0003"]
    assert approx(item["amount"], -21.40) and approx(item["tax"], 1.45)
    assert item["retailer_category"] == "Audible"


def test_free_unreleased_and_paid_by_someone_else_are_left_out(run_statement):
    items = _orders(run_statement)
    assert not {"B0DIGI0004", "B0DIGI0005", "B0DIGI0006"} & set(items)


def test_a_digital_return_is_money_back_for_its_order(run_statement):
    stmt = run_statement(RETURNS, "--expected-parser", "amazon_digital_returns.py")
    assert len(stmt.retail_items) == 1
    refund = stmt.retail_items[0]
    assert refund["line_type"] == "refund" and refund["digital"] is True
    assert refund["date"] == "2026-05-22" and approx(refund["amount"], 6.42)
    assert refund["order_id"] == "D01-0000007-0000007"
    bought = _orders(run_statement)["B0DIGI0007"]
    assert approx(refund["amount"], -bought["amount"])
