#!/usr/bin/env python3
"""Generates the synthetic fixtures for the big banks' CSV export parsers -
chase_card_csv.py, citi_card_csv.py, bofa_checking_csv.py, bofa_card_csv.py,
wells_fargo_csv.py - behind tests/test_bank_csv_exports.py.

Every merchant, amount and account here is invented. Each file follows its
bank's export layout: its header (or none), how it signs amounts, how it
writes dates and money, and, where the bank names the download for the
account, its file name.

Regenerate with:  python3 tests/generators/gen-bank-csv-samples.py
"""

import csv
import os

FIXTURES = {
    "Chase9921_Activity20240301_20240331_20240401.CSV": [
        ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"],
        ["03/02/2024", "03/03/2024", "LAKESHORE GROCER", "Groceries", "Sale", "-84.20", ""],
        ["03/05/2024", "03/06/2024", "NORTHSIDE FUEL", "Gas", "Sale", "-38.12", ""],
        ["03/09/2024", "03/10/2024", "BOOKSHOP RETURN", "Shopping", "Return", "19.99", ""],
        ["03/20/2024", "03/20/2024", "AUTOMATIC PAYMENT - THANK", "", "Payment", "102.33", ""],
    ],
    "citi-card-synthetic-sample.csv": [
        ["Status", "Date", "Description", "Debit", "Credit", "Member Name"],
        ["Cleared", "04/02/2024", "LAKESHORE GROCER", "126.44", "", "PAT EXAMPLE"],
        ["Cleared", "04/04/2024", "NORTHSIDE FUEL", "38.12", "", "SAM EXAMPLE"],
        ["Cleared", "04/15/2024", "ONLINE PAYMENT, THANK YOU", "", "-164.56", "PAT EXAMPLE"],
        ["Pending", "04/30/2024", "CORNER COFFEE", "5.75", "", "PAT EXAMPLE"],
    ],
    "bofa-checking-synthetic-sample.csv": [
        ["Description", "", "Summary Amt."],
        ["Beginning balance as of 05/01/2024", "", "1,000.00"],
        ["Total credits", "", "3,200.00"],
        ["Total debits", "", "-1,911.30"],
        ["Ending balance as of 05/31/2024", "", "2,288.70"],
        [],
        ["Date", "Description", "Amount", "Running Bal."],
        ["05/01/2024", "Beginning balance as of 05/01/2024", "", "1,000.00"],
        ["05/02/2024", "ACME WIDGETS DES:PAYROLL", "3,200.00", "4,200.00"],
        ["05/03/2024", "LAKESHORE GROCER", "-61.30", "4,138.70"],
        ["05/15/2024", "RENT PAYMENT", "-1,850.00", "2,288.70"],
    ],
    "May2024_9921.csv": [
        ["Posted Date", "Reference Number", "Payee", "Address", "Amount"],
        ["05/03/2024", "24692164123000012345678", "LAKESHORE GROCER", "SPRINGFIELD IL", "-61.30"],
        ["05/04/2024", "24692164123000012345679", "NORTHSIDE FUEL", "SPRINGFIELD IL", "-45.00"],
        ["05/20/2024", "24692164123000012345680", "PAYMENT - THANK YOU", "", "106.30"],
    ],
    "Checking1.csv": [
        ["06/03/2024", "3200.00", "*", "", "ACME WIDGETS PAYROLL"],
        ["06/04/2024", "-61.30", "*", "", "PURCHASE AUTHORIZED ON 06/03 LAKESHORE GROCER"],
        ["06/10/2024", "-1850.00", "*", "", "CHECK # 1043"],
    ],
    "CreditCard1.csv": [
        ["07/01/2024", "84.23", "*", "", "LAKESHORE GROCER"],
        ["07/04/2024", "38.12", "*", "", "NORTHSIDE FUEL"],
        ["07/20/2024", "-122.35", "*", "", "ONLINE PAYMENT THANK YOU"],
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
