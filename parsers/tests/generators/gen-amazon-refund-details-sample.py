#!/usr/bin/env python3
"""Generates tests/fixtures/amazon-refund-details-synthetic-sample.csv, the
fixture behind tests/test_amazon_refund_details.py.

It has the columns of the "Refund Details.csv" in an Amazon Request Your
Data export, in the export's own order, and its order numbers are those of
gen-amazon-order-history-sample.py's fixture. Every one is invented.

Regenerate with:  python3 tests/generators/gen-amazon-refund-details-sample.py
"""

import csv
import os

HEADER = [
    "Creation Date", "Currency", "Direct Debit Refund Amount", "Disbursement Type", "Order ID",
    "Payment Status", "Quantity", "Refund Amount", "Refund Date", "Reversal Amount State",
    "Reversal Reason", "Reversal Status", "Website",
]

# (creation date, currency, order id, payment status, quantity, amount,
#  refund date, reason, website)
REFUNDS = [
    # One refund, for the whole of a one-item shipment.
    ("2026-03-20T10:00:00.000Z", "USD", "111-0000002-0000002", "Completed", "1", "136.78",
     "2026-03-22T08:30:00.000Z", "Customer return", "Amazon.com"),
    # An order refunded twice. The export repeats each refund once for each
    # of the order's two creation dates: four rows for two refunds.
    ("2026-04-10T09:00:00Z", "USD", "111-0000003-0000003", "Completed", "1", "9.80",
     "2026-04-12T11:00:00Z", "Customer return", "Amazon.com"),
    ("2026-04-15T09:00:00Z", "USD", "111-0000003-0000003", "Completed", "1", "9.80",
     "2026-04-12T11:00:00Z", "Customer return", "Amazon.com"),
    ("2026-04-10T09:00:00Z", "USD", "111-0000003-0000003", "Completed", "1", "4.5",
     "2026-04-18T14:00:00Z", "Item shipped late", "Amazon.com"),
    ("2026-04-15T09:00:00Z", "USD", "111-0000003-0000003", "Completed", "1", "4.5",
     "2026-04-18T14:00:00Z", "Item shipped late", "Amazon.com"),
    # Not paid yet: not money back.
    ("2026-05-03T09:00:00Z", "USD", "111-0000006-0000006", "Pending", "1", "13.08",
     "2026-05-04T09:00:00Z", "Customer return", "Amazon.com"),
    # A completed refund the export gives no Refund Date, repeated for its
    # order's two creation dates: one refund, dated by the earlier.
    ("2026-03-11T12:00:00Z", "USD", "111-0000001-0000001", "Completed", "1", "19.49",
     "Not Applicable", "Customer return", "Amazon.com"),
    ("2026-03-10T12:00:00Z", "USD", "111-0000001-0000001", "Completed", "1", "19.49",
     "Not Applicable", "Customer return", "Amazon.com"),
    # A Payment Status of "Not Applicable" is not a completed refund.
    ("2026-03-12T12:00:00Z", "USD", "111-0000001-0000001", "Not Applicable", "1", "6.71",
     "2026-03-12T12:00:00Z", "Customer return", "Amazon.com"),
    # Another country's store.
    ("2026-04-25T05:00:00.000Z", "INR", "404-0000005-0000005", "Completed", "1", "1,899.00",
     "2026-04-27T05:00:00.000Z", "Item not received", "Amazon.in"),
]


def build() -> list[list[str]]:
    rows = [HEADER]
    for created, currency, order_id, paid, quantity, amount, refunded, reason, website in REFUNDS:
        rows.append([created, currency, "0", "Refund", order_id, paid, quantity, amount, refunded, "Final",
                     reason, "Completed", website])
    return rows


def main():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")
    path = os.path.join(here, "amazon-refund-details-synthetic-sample.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(build())
    print(f"wrote {path}")
    print(f"  {len(REFUNDS)} rows")


if __name__ == "__main__":
    main()
