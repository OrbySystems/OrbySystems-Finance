#!/usr/bin/env python3
"""Generates tests/fixtures/amazon-digital-orders-synthetic-sample.csv and
amazon-digital-returns-synthetic-sample.csv, the fixtures behind
tests/test_amazon_digital.py.

They have the columns of the "Digital Content Orders.csv" and "Digital
Returns.csv" in an Amazon Request Your Data export, in the export's own
order. Every title, order and amount is invented.

Regenerate with:  python3 tests/generators/gen-amazon-digital-sample.py
"""

import csv
import os

ORDERS_HEADER = [
    "ASIN", "Affected Item Quantity", "Alternative Order Providing Payment", "Base Currency", "Base Currency Code",
    "Billing Address", "Claim Code", "Component Type", "Country Code", "Customer Declared Address",
    "Declared Country Code", "Delivery Date", "Delivery Packet ID", "Delivery Status",
    "Digital Order Item Attributes", "Digital Order Item ID", "Does Order Depend on Another Order",
    "FX Currency Code", "FX Transaction Amount", "Fulfilled Date", "Fulfillment Mobile Number",
    "Fullfilment Status", "Gift Claim Date", "Gift Customer Nickname", "Gift Email", "Gift Item", "Gift Message",
    "Gift Redemption", "Installment Our Price", "Installment Our Price Plus Tax", "Installment Price Currency Code",
    "Installment Price Plus Tax Currency Code", "Is Order Eligible for Prime Benefit", "Is Order Free Replacement",
    "Is Order a Preorder", "Item Fulfilled", "Item Merged from Another Order", "List Price Amount",
    "List Price Currency Code", "List Price Tax Amount", "List Price Tax Currency Code", "Marketplace",
    "Multifactor Authentication Status (depreciated)", "Offer Type Code", "Offering SKU", "Order Date", "Order ID",
    "Order Status", "Ordering Customer Nickname", "Original Quantity", "Paid by Other Customer",
    "Payment Information", "Previously Paid Digital Order Item ID", "PreviouslyPaidOrderId", "Price",
    "Price Currency Code", "Price Tax", "Price Tax Currency Code", "Product Name", "Publisher", "Quantity Ordered",
    "Recharge Amount", "Recharge Amount Currency Code", "Recipient Email", "Related Physical Order ID",
    "Seller of Record", "Session ID", "Ship From", "Ship To", "Shipping Address", "Shopping Marketplace ID",
    "Subscription Order Info List", "Subscription Order Type", "Third Party Display Currency Code",
    "Third Party Display Price", "Transaction Amount", "Unique Browser ID",
]

RETURNS_HEADER = [
    "ASIN", "Affected Item Quantity", "Amount Refunded", "Base Currency", "Claim Code", "Condition Code",
    "Delivery Packet ID", "Digital Order Item ID", "FX Currency Code", "FX Transaction Amount",
    "Monetary Component Type", "Offer Type Code", "Order ID", "Payment Information", "Processing Successful",
    "Product Name", "Quantity", "Reason Code", "Refund to Gift Certificate", "Return Date", "Return Status",
    "Returned By", "Settle Type", "Status", "Transaction Amount",
]

NA = "Not Applicable"

# (item id, asin, order id, date, title, marketplace, status, paid by other,
#  price, [(component, transaction amount, offer type)])
ITEMS = [
    # An ebook, its tax row zero.
    ("ITEM1", "B0DIGI0001", "D01-0000001-0000001", "2026-03-04T10:00:00Z", "The Quiet Orchard (Kindle Edition)",
     "www.amazon.com", "SUCCESS", NA, "9.99", [("Price Amount", "9.99", NA), ("Tax", "0.0", NA)]),
    # An ebook with a coupon: 14.99 less 3.00 = 11.99.
    ("ITEM2", "B0DIGI0002", "D01-0000002-0000002", "2026-03-15T12:00:00Z", "Weekend Bread Baking (Kindle Edition)",
     "www.amazon.com", "SUCCESS", NA, "14.99",
     [("Price Amount", "14.99", NA), ("Tax", "0.0", NA), ("Price Amount", "-3.0", "Coupon"), ("Tax", "0.0", "Coupon")]),
    # An audiobook from Audible, with tax.
    ("ITEM3", "B0DIGI0003", "D01-0000003-0000003", "2026-04-02T09:00:00Z", "Harbor Lights (Audiobook)",
     "www.audible.com", "SUCCESS", NA, "19.95", [("Price Amount", "19.95", NA), ("Tax", "1.45", NA)]),
    # A free ebook: nothing paid, left out.
    ("ITEM4", "B0DIGI0004", "D01-0000004-0000004", "2026-04-10T09:00:00Z", "A Free Sample Story (Kindle Edition)",
     "www.amazon.com", "SUCCESS", NA, "0.0", [("Price Amount", "0.0", NA), ("Tax", "0.0", NA)]),
    # A preorder not released yet: not charged, left out.
    ("ITEM5", "B0DIGI0005", "D01-0000005-0000005", "2026-05-01T09:00:00Z", "Next Year's Novel (Kindle Edition)",
     "www.amazon.com", "PENDING_PREORDER_RELEASE", NA, "12.99", [("Price Amount", "12.99", NA), ("Tax", "0.0", NA)]),
    # Paid for by someone else: left out.
    ("ITEM6", "B0DIGI0006", "D01-0000006-0000006", "2026-05-03T09:00:00Z", "A Gift Received (Kindle Edition)",
     "www.amazon.com", "SUCCESS", "Yes", "7.99", [("Price Amount", "7.99", NA), ("Tax", "0.0", NA)]),
    # A video rented, then returned (see RETURNS).
    ("ITEM7", "B0DIGI0007", "D01-0000007-0000007", "2026-05-20T20:00:00Z", "Mountain Weekend (HD Rental)",
     "www.amazon.com", "SUCCESS", NA, "5.99", [("Price Amount", "5.99", NA), ("Tax", "0.43", NA)]),
]

# (item id, order id, return date, status, [(component, transaction amount)])
RETURNS = [
    ("ITEM7", "D01-0000007-0000007", "2026-05-22T10:00:00Z", "Customer Return Complete",
     [("Price Amount", "5.99"), ("Tax", "0.43")]),
]


def build_orders() -> list[list[str]]:
    rows = [ORDERS_HEADER]
    for item_id, asin, order_id, day, title, market, status, other, price, components in ITEMS:
        for component, amount, offer in components:
            row = dict.fromkeys(ORDERS_HEADER, NA)
            row.update({
                "ASIN": asin, "Base Currency Code": "USD", "Component Type": component,
                "Digital Order Item ID": item_id, "Marketplace": market, "Offer Type Code": offer,
                "Order Date": day, "Order ID": order_id, "Order Status": status, "Paid by Other Customer": other,
                "Payment Information": "Payment Instrument Details Not Available", "Price": price,
                "Price Currency Code": "USD", "Product Name": title, "Quantity Ordered": "1",
                "Transaction Amount": amount,
            })
            rows.append([row[h] for h in ORDERS_HEADER])
    return rows


def build_returns() -> list[list[str]]:
    rows = [RETURNS_HEADER]
    for item_id, order_id, day, status, components in RETURNS:
        for component, amount in components:
            row = dict.fromkeys(RETURNS_HEADER, "Not Available")
            row.update({
                "Digital Order Item ID": item_id, "Monetary Component Type": component, "Order ID": order_id,
                "Quantity": "1", "Reason Code": "Other", "Return Date": day, "Return Status": status,
                "Transaction Amount": amount, "Base Currency": "USD",
            })
            rows.append([row[h] for h in RETURNS_HEADER])
    return rows


def main():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")
    for name, rows in (("amazon-digital-orders-synthetic-sample.csv", build_orders()),
                       ("amazon-digital-returns-synthetic-sample.csv", build_returns())):
        path = os.path.join(here, name)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        print(f"wrote {path}")
        print(f"  {len(rows) - 1} rows")


if __name__ == "__main__":
    main()
