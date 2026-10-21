#!/usr/bin/env python3
"""Generates tests/fixtures/amazon-order-history-synthetic-sample.csv, the
fixture behind tests/test_amazon_order_history.py.

It has the columns of the "Order History.csv" in an Amazon Request Your
Data export, in the export's own order. Every order number, product,
address, card and amount is invented, so it can live in git.

Regenerate with:  python3 tests/generators/gen-amazon-order-history-sample.py
"""

import csv
import os

HEADER = [
    "ASIN", "Billing Address", "Carrier Name & Tracking Number", "Currency", "Gift Message",
    "Gift Recipient Contact", "Gift Sender Name", "Item Serial Number", "Order Date", "Order ID",
    "Order Status", "Original Quantity", "Payment Method Type", "Product Condition", "Product Name",
    "Purchase Order Number", "Ship Date", "Shipment Item Subtotal", "Shipment Item Subtotal Tax",
    "Shipment Status", "Shipping Address", "Shipping Charge", "Shipping Option", "Total Amount",
    "Total Discounts", "Unit Price", "Unit Price Tax", "Website",
]

NA = "Not Available"
ADDRESS = "Pat Example 100 Sample Street Springfield ZZ 00000 United States"
VISA = "Visa - 0000"

# (asin, currency, order date, order id, status, quantity, payment, product,
#  ship date, shipment subtotal, shipment tax, shipping, total, discounts,
#  unit price, unit tax, website)
ITEMS = [
    # One shipment, two items: the shipment figures repeat on both rows.
    ("B0EXAMPLE01", "USD", "2026-03-02T18:04:11Z", "111-0000001-0000001", "Closed", "1", VISA,
     "Sample Brand Dry Dog Food, Chicken, 30 lb", "2026-03-03T09:15:00Z", "74.48", "6.71", "0", "59.94", "0",
     "54.99", "4.95", "Amazon.com"),
    ("B0EXAMPLE02", "USD", "2026-03-02T18:04:11Z", "111-0000001-0000001", "Closed", "1", VISA,
     "Sample Brand Whole Bean Coffee, Medium Roast, 2 lb", "2026-03-03T09:15:00Z", "74.48", "6.71", "0", "21.25",
     "0", "19.49", "1.76", "Amazon.com"),
    # One order, two shipments (two card charges), a quantity above one and
    # a discount.
    ("B0EXAMPLE03", "USD", "2026-03-10T07:30:00Z", "111-0000002-0000002", "Closed", "2", VISA,
     "Sample Brand Men's Crew Socks, 6 Pack", "2026-03-11T12:00:00Z", "28.00", "2.52", "0", "28.52", "-2.00",
     "14.00", "1.26", "Amazon.com"),
    ("B0EXAMPLE04", "USD", "2026-03-10T07:30:00Z", "111-0000002-0000002", "Closed", "1", VISA,
     "Sample Brand 1.1 cu ft Countertop Microwave Oven", "2026-03-14T16:45:00Z", "119.99", "10.80", "5.99",
     "136.78", "0", "119.99", "10.80", "Amazon.com"),
    # The same item twice in one shipment, as two rows.
    ("B0EXAMPLE05", "USD", "2026-04-01T20:00:00Z", "111-0000003-0000003", "Closed", "1",
     "Gift Certificate/Card and Visa - 0000", "Sample Brand Moisturizing Shampoo, 12 oz",
     "2026-04-02T10:00:00Z", "17.98", "1.62", "0", "9.80", "0", "8.99", "0.81", "Amazon.com"),
    ("B0EXAMPLE05", "USD", "2026-04-01T20:00:00Z", "111-0000003-0000003", "Closed", "1",
     "Gift Certificate/Card and Visa - 0000", "Sample Brand Moisturizing Shampoo, 12 oz",
     "2026-04-02T10:00:00Z", "17.98", "1.62", "0", "9.80", "0", "8.99", "0.81", "Amazon.com"),
    # Cancelled: nothing shipped, nothing charged.
    ("B0EXAMPLE06", "USD", "2026-04-05T11:11:11Z", "111-0000004-0000004", "Cancelled", "0", NA,
     "Sample Brand Allergy Relief Tablets, 90 Count", NA, NA, NA, "0", "0", "0", "0", "0", "Amazon.com"),
    # Another country's store, in its own currency; the older date format.
    ("B0EXAMPLE07", "INR", "2026-04-20T05:00:00.000Z", "404-0000005-0000005", "Closed", "1", VISA,
     "Sample Brand Stainless Steel Pressure Cooker, 5 Litre", "2026-04-21T05:00:00.000Z", "1,899.00", "0", "0",
     "1899.00", "0", "1899.00", "0", "Amazon.in"),
    # No product name on record.
    ("B0EXAMPLE08", "USD", "2026-05-01T00:00:00Z", "111-0000006-0000006", "Closed", "1", "MasterCard - 0000",
     NA, "2026-05-02T00:00:00Z", "12.00", "1.08", "0", "13.08", "0", "12.00", "1.08", "Amazon.com"),
    # Subscribe & Save deliveries (SUBSCRIBE_AND_SAVE_ORDERS), with its
    # discount: the coffee bought normally in March, now by subscription.
    ("B0EXAMPLE02", "USD", "2026-05-10T06:00:00Z", "111-0000007-0000007", "Closed", "1", VISA,
     "Sample Brand Whole Bean Coffee, Medium Roast, 2 lb", "2026-05-11T06:00:00Z", "19.49", "1.67", "0",
     "20.19", "-0.97", "19.49", "1.67", "Amazon.com"),
    ("B0EXAMPLE09", "USD", "2026-06-10T06:00:00Z", "111-0000008-0000008", "Closed", "1", VISA,
     "Sample Brand Paper Towels, 12 Rolls", "2026-06-11T06:00:00Z", "24.99", "2.25", "0",
     "25.99", "-1.25", "24.99", "2.25", "Amazon.com"),
]

# Orders delivered by Subscribe & Save, and the invented Shipping Option code
# they carry; every other order ships "standard". A real export's code is
# Amazon's own; what matters is "sns" as a word of its own.
SUBSCRIBE_AND_SAVE_ORDERS = {"111-0000007-0000007", "111-0000008-0000008"}
SUBSCRIBE_AND_SAVE_OPTION = "sns-standard-us"


def build() -> list[list[str]]:
    rows = [HEADER]
    for (asin, currency, order_date, order_id, status, quantity, payment, product, ship_date, subtotal,
         subtotal_tax, shipping, total, discounts, unit_price, unit_tax, website) in ITEMS:
        shipped = ship_date != NA
        rows.append([
            asin, ADDRESS, "SAMPLE(TBA000000000000)" if shipped else NA, currency, NA, NA, NA, NA,
            order_date, order_id, status, quantity, payment, "New", product, NA, ship_date, subtotal,
            subtotal_tax, "Shipped" if shipped else NA, ADDRESS, shipping,
            SUBSCRIBE_AND_SAVE_OPTION if order_id in SUBSCRIBE_AND_SAVE_ORDERS else "standard", total, discounts,
            unit_price, unit_tax, website,
        ])
    return rows


def main():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")
    path = os.path.join(here, "amazon-order-history-synthetic-sample.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(build())
    print(f"wrote {path}")
    print(f"  {len(ITEMS)} rows")


if __name__ == "__main__":
    main()
