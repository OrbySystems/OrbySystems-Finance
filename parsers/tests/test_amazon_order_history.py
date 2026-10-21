"""Amazon's order history export (csv_institutions/amazon_order_history.py),
against a wholly invented export with the real one's columns."""

from conftest import approx

FIXTURE = "amazon-order-history-synthetic-sample.csv"


def _items(run_statement):
    stmt = run_statement(FIXTURE, "--expected-parser", "amazon_order_history.py")
    assert stmt.institution == "Amazon" and stmt.statement_date == ""
    assert stmt.transactions == [] and stmt.brokerage_transactions == []
    return stmt.retail_items


def test_one_row_per_item_and_cancelled_items_left_out(run_statement):
    items = _items(run_statement)
    assert len(items) == 10
    assert all(i["order_id"] != "111-0000004-0000004" for i in items)
    assert all(i.get("status") != "Cancelled" for i in items)
    assert all(i["line_type"] == "purchase" and i["amount"] <= 0 for i in items)


def test_a_line_is_spending_in_full(run_statement):
    food = _items(run_statement)[0]
    assert food["date"] == "2026-03-02"
    assert food["description"] == "Sample Brand Dry Dog Food, Chicken, 30 lb"
    assert approx(food["amount"], -59.94)
    assert approx(food["unit_price"], 54.99) and approx(food["tax"], 4.95)
    assert food["item_id"] == "B0EXAMPLE01" and food["currency_code"] == "USD"
    assert food["payment_method"] == "Visa - 0000"


def test_quantity_discount_and_shipping(run_statement):
    items = _items(run_statement)
    socks, oven = items[2], items[3]
    assert approx(socks["quantity"], 2) and approx(socks["tax"], 2.52)
    assert approx(socks["discount"], -2.00) and approx(socks["amount"], -28.52)
    assert approx(oven["shipping"], 5.99) and approx(oven["amount"], -136.78)


def test_each_shipment_of_an_order_is_its_own_charge_group(run_statement):
    items = _items(run_statement)
    assert items[0]["charge_group"] == items[1]["charge_group"] == "111-0000001-0000001/2026-03-03"
    assert items[2]["order_id"] == items[3]["order_id"]
    assert items[2]["charge_group"] == "111-0000002-0000002/2026-03-11"
    assert items[3]["charge_group"] == "111-0000002-0000002/2026-03-14"


def test_the_same_item_twice_stays_two_rows(run_statement):
    items = _items(run_statement)
    assert items[4] == items[5]
    assert items[4]["payment_method"] == "Gift Certificate/Card and Visa - 0000"


def test_another_countrys_store_is_named(run_statement):
    items = _items(run_statement)
    abroad = items[6]
    assert abroad["institution"] == "Amazon.in" and abroad["currency_code"] == "INR"
    assert abroad["date"] == "2026-04-20" and approx(abroad["amount"], -1899.00)
    assert all("institution" not in i for i in items if i is not abroad)


def test_an_item_with_no_name_is_still_a_row(run_statement):
    unnamed = _items(run_statement)[7]
    assert unnamed["description"] == "Amazon item B0EXAMPLE08"
    assert unnamed["payment_method"] == "MasterCard - 0000"


def test_a_subscribe_and_save_delivery_is_marked_by_line(run_statement):
    items = _items(run_statement)
    subscribed = [i for i in items if i["subscribe_and_save"]]
    assert [i["order_id"] for i in subscribed] == ["111-0000007-0000007", "111-0000008-0000008"]
    assert all(i["subscribe_and_save"] is False for i in items if i not in subscribed)
    # The same coffee, bought normally in March and by subscription in May:
    # the mark is the line's, not the item's.
    coffee = [i for i in items if i["item_id"] == "B0EXAMPLE02"]
    assert [(i["date"], i["subscribe_and_save"]) for i in coffee] == [("2026-03-02", False), ("2026-05-10", True)]
    assert approx(coffee[1]["discount"], -0.97) and approx(coffee[1]["amount"], -20.19)
