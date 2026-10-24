#!/usr/bin/env python3
"""Generates the synthetic fixtures for the parsers of somebody's records:
OrbySystems' import CSV (orbysystems_transactions_csv.py,
orbysystems_investments_csv.py) and the money apps' exports (mint_csv.py,
ynab_register_csv.py, monarch_csv.py, tiller_csv.py, simplifi_csv.py,
empower_csv.py), behind tests/test_records.py.

Every name, payee, amount and account here is invented. The app exports
follow each app's published layout: its header, how it signs amounts, how
it writes dates and money.

Regenerate with:  python3 tests/generators/gen-records-samples.py
"""

import csv
import os

FIXTURES = {
    "orbysystems-transactions-synthetic-sample.csv": [
        ["date", "description", "amount", "account_type", "institution", "account_last4", "account_name", "balance"],
        ["2019-01-05", "Lakeshore Grocer", "-84.20", "Checking", "Harbor Bank", "4417", "Joint checking", "915.80"],
        ["2019-01-07", "Northside Fuel", "-45.00", "Credit Card", "Meridian Card", "9921", "", ""],
        ["2019-01-15", "Payroll Acme Widgets", "3200.00", "Checking", "Harbor Bank", "4417", "Joint checking", "4115.80"],
        ["2019-01-20", "Card payment", "45.00", "Credit Card", "Meridian Card", "9921", "", ""],
    ],
    "orbysystems-investment-transactions-synthetic-sample.csv": [
        ["date", "description", "transaction_type", "amount", "symbol", "quantity", "price", "fees", "account_type", "institution", "account_last4"],
        ["2020-01-02", "Bought 10 VTI", "buy", "-1600.00", "VTI", "10", "160.00", "0", "Roth IRA", "Vantage Brokerage", "3301"],
        ["2020-01-02", "Contribution", "contribution", "6000.00", "", "", "", "", "Roth IRA", "Vantage Brokerage", "3301"],
        ["2020-03-31", "VTI dividend", "dividend", "12.30", "VTI", "", "", "", "Roth IRA", "Vantage Brokerage", "3301"],
        ["2020-04-01", "Shares moved in", "transfer_in", "0", "BND", "5", "", "", "Roth IRA", "Vantage Brokerage", "3301"],
        ["2020-06-01", "Sold 4 VTI", "sell", "700.00", "VTI", "4", "175.00", "0", "Roth IRA", "Vantage Brokerage", "3301"],
    ],
    "orbysystems-holdings-synthetic-sample.csv": [
        ["as_of", "symbol", "quantity", "description", "price", "market_value", "cost_basis", "account_type", "institution", "account_last4", "account_name"],
        ["2024-12-31", "VTI", "120", "Total Stock Market ETF", "210.50", "25260.00", "18000.00", "Brokerage", "Vantage Brokerage", "7788", "Taxable"],
        ["2024-12-31", "CASH", "1500.25", "", "", "", "", "Brokerage", "Vantage Brokerage", "7788", "Taxable"],
        ["2025-06-30", "VTI", "125", "Total Stock Market ETF", "230.00", "28750.00", "19100.00", "Brokerage", "Vantage Brokerage", "7788", "Taxable"],
    ],
    "mint-synthetic-sample.csv": [
        ["Date", "Description", "Original Description", "Amount", "Transaction Type", "Category", "Account Name", "Labels", "Notes"],
        ["3/02/2020", "Acme Widgets", "ACME WIDGETS PAYROLL", "3200.00", "credit", "Paycheck", "Harbor Checking", "", ""],
        ["3/03/2020", "Corner Coffee", "CORNER COFFEE #12", "5.75", "debit", "Coffee Shops", "Meridian Visa", "", ""],
        ["3/04/2020", "Lakeshore Grocer", "LAKESHORE GROCER 0042", "42.10", "debit", "Groceries", "Meridian Visa", "", ""],
        ["3/15/2020", "Meridian Card Payment", "PAYMENT THANK YOU", "47.85", "credit", "Credit Card Payment", "Meridian Visa", "", ""],
    ],
    "ynab-register-synthetic-sample.csv": [
        ["Account", "Flag", "Date", "Payee", "Category Group/Category", "Category Group", "Category", "Memo", "Outflow", "Inflow", "Cleared"],
        ["Harbor Checking", "", "01/02/2021", "Starting Balance", "Inflow: Ready to Assign", "Inflow", "Ready to Assign", "", "$0.00", "$1,500.00", "Cleared"],
        ["Harbor Checking", "", "01/03/2021", "Lakeshore Grocer", "Everyday: Groceries", "Everyday", "Groceries", "", "$84.23", "$0.00", "Cleared"],
        ["Harbor Checking", "", "01/15/2021", "Acme Widgets", "Inflow: Ready to Assign", "Inflow", "Ready to Assign", "Pay", "$0.00", "$3,200.00", "Cleared"],
        ["Meridian Card", "", "01/20/2021", "Corner Coffee", "Everyday: Dining", "Everyday", "Dining", "", "$5.75", "$0.00", "Uncleared"],
        ["Meridian Card", "", "01/25/2021", "Transfer : Harbor Checking", "", "", "", "", "$0.00", "$5.75", "Cleared"],
        ["Retirement 401k", "", "01/31/2021", "Reconciliation Balance Adjustment", "", "", "", "", "$0.00", "$2,000.00", "Reconciled"],
    ],
    "monarch-synthetic-sample.csv": [
        ["Date", "Merchant", "Category", "Account", "Original Statement", "Notes", "Amount", "Tags"],
        ["2022-05-01", "Acme Widgets", "Paychecks", "Harbor Checking (...4417)", "ACME WIDGETS DIR DEP", "", "3200.00", ""],
        ["2022-05-03", "Lakeshore Grocer", "Groceries", "Meridian Card", "LAKESHORE GROCER 0042", "", "-61.30", "household"],
        ["2022-05-04", "", "Restaurants", "Meridian Card", "CORNER COFFEE #12", "", "-4.50", ""],
    ],
    "tiller-synthetic-sample.csv": [
        ["Date", "Description", "Category", "Amount", "Account", "Account #", "Institution", "Month", "Week", "Transaction ID", "Account ID", "Check Number", "Full Description", "Date Added"],
        ["2/17/2023", "Northside Fuel", "Gas", "-$38.12", "Meridian Visa", "xxxx9921", "Meridian Card", "2/1/2023", "2/12/2023", "t1", "a1", "", "NORTHSIDE FUEL 5741", "2/18/2023"],
        ["2/20/2023", "Acme Widgets Payroll", "Paycheck", "$3,200.00", "Joint Checking", "xxxx4417", "Harbor Bank", "2/1/2023", "2/19/2023", "t2", "a2", "", "ACME WIDGETS PAYROLL", "2/21/2023"],
        ["2/21/2023", "Check", "Rent", "-$1,850.00", "Joint Checking", "xxxx4417", "Harbor Bank", "2/1/2023", "2/19/2023", "t3", "a2", "1043", "CHECK 1043", "2/22/2023"],
        ["2/22/2023", "Cash", "Spending", "-$20.00", "Wallet", "", "", "2/1/2023", "2/19/2023", "t4", "a3", "", "CASH", "2/22/2023"],
    ],
    "simplifi-synthetic-sample.csv": [
        ["Date", "Account", "Status", "Payee", "Category", "Tags", "Notes", "Amount"],
        ["6/01/2024", "Harbor Checking", "Cleared", "Acme Widgets", "Paychecks", "", "", "3200.00"],
        ["6/02/2024", "Meridian Visa", "Cleared", "Lakeshore Grocer", "Groceries", "", "", "-71.15"],
    ],
    "empower-synthetic-sample.csv": [
        ["Date", "Account", "Description", "Category", "Tags", "Amount"],
        ["2024-07-01", "Harbor Bank - Checking", "Acme Widgets Payroll", "Paychecks/Salary", "", "3200.0"],
        ["2024-07-02", "Meridian Card - Credit Card", "Lakeshore Grocer", "Groceries", "", "-61.3"],
        ["2024-07-05", "Meridian Card - Credit Card", "Payment", "Credit Card Payments", "", "61.3"],
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
