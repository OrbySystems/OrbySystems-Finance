#!/usr/bin/env python3
"""Generates tests/fixtures/amazon-returns-status-synthetic-sample.csv, the
fixture behind tests/test_amazon_returns_status.py.

It has the columns of the "Returns Status.csv" in an Amazon Request Your
Data export, in the export's own order, and its order numbers are those of
gen-amazon-order-history-sample.py's fixture. Every one is invented.

Regenerate with:  python3 tests/generators/gen-amazon-returns-status-sample.py
"""

import csv
import os

HEADER = [
    "Carrier Package ID", "Carrier Tracking ID", "Charge Status", "Contract Creation Date", "Contract ID",
    "Contract Unit ID", "Date of Return", "Gift Card", "Order ID", "Payment Method Service Type",
    "Replacement Order", "Retrocharge Resolution", "Return Amount", "Return Amount Currency",
    "Return Authorization ID", "Return Creation Date", "Return Reason", "Return Receivable Creation Reason",
    "Return Receivable Initiation Date", "Return Receivable State", "Return Receivable Tracking ID",
    "Return Resolution", "Return Ship Option",
]

NA = "Not Applicable"

# (return id, unit, order id, created, returned, amount, currency, reason,
#  resolution, receivable state, charged back)
ROWS = [
    # Returned and refunded (amazon_refund_details' 2026-03-22 refund). The
    # export repeats the unit, once with a smaller amount.
    ("RSAMPLE0002", "U1", "111-0000002-0000002", "2026-03-18T10:00:00Z", "2026-03-19T09:00:00Z", "136.78", "USD",
     "No longer needed", "Refund", "Closed", False),
    ("RSAMPLE0002", "U1", "111-0000002-0000002", "2026-03-18T10:00:00Z", "2026-03-19T09:00:00Z", "120.00", "USD",
     "No longer needed", "Refund", "Closed", False),
    # Two units of one return, refunded on 12 and 18 April.
    ("RSAMPLE0003", "U1", "111-0000003-0000003", "2026-04-11T08:00:00Z", "2026-04-11T12:00:00Z", "9.80", "USD",
     "Defective", "Refund", "Closed", False),
    ("RSAMPLE0003", "U2", "111-0000003-0000003", "2026-04-11T08:00:00Z", "2026-04-11T12:00:00Z", "4.50", "USD",
     "Defective", "Refund", "Closed", False),
    # Sent back, refund not paid yet (its refund row is Pending): to come.
    ("RSAMPLE0006", "U1", "111-0000006-0000006", "2026-05-02T09:00:00Z", "2026-05-03T09:00:00Z", "13.08", "USD",
     "Wrong item was sent", "Refund", NA, False),
    # Refunded ahead, never sent back, charged again.
    ("RSAMPLE0007", "U1", "111-0000007-0000007", "2026-05-12T09:00:00Z", "2026-06-12T09:00:00Z", "Not Available",
     "Not Available", "No longer needed", "Refund", "Expired", True),
    # An exchange: no money back to wait for. No creation date printed.
    ("RSAMPLE0008", "U1", "111-0000008-0000008", NA, "2026-06-15T09:00:00Z", "21.99", "USD",
     "Too small", "Exchange", NA, False),
]


def build() -> list[list[str]]:
    rows = [HEADER]
    for return_id, unit, order_id, created, returned, amount, currency, reason, resolution, state, charged in ROWS:
        rows.append([
            NA, NA, "ChargeSuccess" if charged else NA, NA, "C-" + return_id, unit, returned, NA, order_id,
            "IdentityService" if charged else NA, NA, "AdvancedRefund" if charged else NA, amount, currency,
            return_id, created, reason, "CustomerReturn", NA, state, NA, resolution, "SAMPLE_SHIP_OPTION",
        ])
    return rows


def main():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")
    path = os.path.join(here, "amazon-returns-status-synthetic-sample.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(build())
    print(f"wrote {path}")
    print(f"  {len(ROWS)} rows")


if __name__ == "__main__":
    main()
