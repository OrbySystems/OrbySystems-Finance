#!/usr/bin/env python3
"""Generates the synthetic fixtures for the card issuers' and banks' CSV
export parsers - amex_csv.py, capital_one_card_csv.py,
capital_one_360_csv.py, discover_card_csv.py - behind
tests/test_card_csv_exports.py.

Every merchant, amount and card number here is invented. Each file follows
its issuer's export layout: its header, how it signs amounts, how it writes
dates and money.

Regenerate with:  python3 tests/generators/gen-card-csv-samples.py
"""

import csv
import os

FIXTURES = {
    "amex-detailed-synthetic-sample.csv": [
        ["Date", "Description", "Card Member", "Account #", "Amount", "Extended Details", "Appears On Your Statement As",
         "Address", "City/State", "Zip Code", "Country", "Reference", "Category"],
        ["03/02/2024", "LAKESHORE GROCER", "PAT EXAMPLE", "-21004", "84.20", "GROCERY", "LAKESHORE GROCER",
         "1 MAIN ST", "SPRINGFIELD\nIL", "62701", "UNITED STATES", "'320240620123456789'", "Merchandise & Supplies-Groceries"],
        ["03/05/2024", "NORTHSIDE FUEL", "SAM EXAMPLE", "-21012", "38.12", "FUEL", "NORTHSIDE FUEL 5741",
         "", "", "", "", "'320240650123456790'", "Transportation-Fuel"],
        ["03/15/2024", "ONLINE PAYMENT - THANK YOU", "PAT EXAMPLE", "-21004", "-122.32", "", "ONLINE PAYMENT - THANK YOU",
         "", "", "", "", "'320240750123456791'", ""],
    ],
    "amex-synthetic-sample.csv": [
        ["Date", "Description", "Amount", "Extended Details", "Appears On Your Statement As", "Address", "City/State",
         "Zip Code", "Country", "Reference", "Category"],
        ["04/01/2024", "CORNER COFFEE", "5.75", "", "CORNER COFFEE #12", "", "", "", "", "'320240920123456792'", "Restaurant-Bar & Café"],
        ["04/03/2024", "RETURN CREDIT", "-19.99", "", "BOOKSHOP RETURN", "", "", "", "", "'320240940123456793'", ""],
    ],
    "capital-one-card-synthetic-sample.csv": [
        ["Transaction Date", "Posted Date", "Card No.", "Description", "Category", "Debit", "Credit"],
        ["2024-05-01", "2024-05-02", "9921", "LAKESHORE GROCER", "Grocery", "61.30", ""],
        ["2024-05-03", "2024-05-04", "9921", "NORTHSIDE FUEL", "Gas/Automotive", "45.00", ""],
        ["2024-05-20", "2024-05-20", "9921", "CAPITAL ONE AUTOPAY PYMT", "Payment/Credit", "", "106.30"],
    ],
    "capital-one-360-synthetic-sample.csv": [
        ["Account Number", "Transaction Description", "Transaction Date", "Transaction Type", "Transaction Amount", "Balance"],
        ["36000004417", "Deposit from ACME WIDGETS PAYROLL", "06/03/24", "Credit", "3200.00", "4115.80"],
        ["36000004417", "Debit Card Purchase - LAKESHORE GROCER", "06/04/24", "Debit", "61.30", "4054.50"],
        ["36000004417", "Withdrawal to 360 Performance Savings", "06/10/24", "Debit", "500.00", "3554.50"],
    ],
    "discover-card-synthetic-sample.csv": [
        ["Trans. Date", "Post Date", "Description", "Amount", "Category"],
        ["07/01/2024", "07/02/2024", "LAKESHORE GROCER", "84.23", "Supermarkets"],
        ["07/04/2024", "07/05/2024", "NORTHSIDE FUEL", "38.12", "Gasoline"],
        ["07/20/2024", "07/20/2024", "INTERNET PAYMENT - THANK YOU", "-1502.74", "Payments and Credits"],
    ],
}


def main():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")
    for name, rows in FIXTURES.items():
        path = os.path.join(here, name)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
