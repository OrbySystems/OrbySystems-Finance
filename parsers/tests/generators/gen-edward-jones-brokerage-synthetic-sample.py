#!/usr/bin/env python3
"""Generate a fictional Edward Jones-style brokerage statement fixture.

The layout reproduces documented section names and column relationships, not
Edward Jones artwork.  Every identity, account, security, and amount is
invented.  The output is visibly marked as synthetic test data.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "edward-jones-synthetic-202608.pdf"
EXPECT = ROOT / "fixtures" / "edward-jones-synthetic-202608.expectations.json"

PAGE_W, PAGE_H = letter
DARK = HexColor("#333333")
GOLD = HexColor("#F2C94C")
LIGHT = HexColor("#F7F7F7")

PERIOD = "July 25, 2026 - August 28, 2026"
ACCOUNT_ID = "123-45678-9-0"


class Statement:
    def __init__(self, path: Path):
        self.c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
        self.page = 0
        self.y = 0.0

    def new_page(self, title: str) -> None:
        if self.page:
            self.c.showPage()
        self.page += 1
        self.c.setFillColor(GOLD)
        self.c.rect(0, PAGE_H - 18, PAGE_W, 18, stroke=0, fill=1)
        self.c.setFillColor(DARK)
        self.c.setFont("Helvetica-Bold", 17)
        self.c.drawString(38, PAGE_H - 48, "EDWARD JONES")
        self.c.setFont("Helvetica", 8)
        self.c.drawRightString(PAGE_W - 38, PAGE_H - 45, "Member SIPC")
        self.c.setFont("Helvetica-Bold", 13)
        self.c.drawString(38, PAGE_H - 76, title)
        self.c.setFont("Helvetica", 8)
        self.c.drawString(38, PAGE_H - 94, f"Statement Period: {PERIOD}")
        self.c.drawString(305, PAGE_H - 94, f"Account Number: {ACCOUNT_ID}")
        self.c.drawString(38, PAGE_H - 108, "Account Type: Individual Brokerage Account")
        self.c.setFillColor(HexColor("#A00000"))
        self.c.setFont("Helvetica-Bold", 8)
        self.c.drawRightString(
            PAGE_W - 38,
            PAGE_H - 108,
            "SYNTHETIC TEST DATA - NOT AN OFFICIAL EDWARD JONES STATEMENT",
        )
        self.c.setFillColor(black)
        self.y = PAGE_H - 138

    def footer(self) -> None:
        self.c.setFillColor(DARK)
        self.c.setFont("Helvetica", 7)
        self.c.drawString(38, 24, "Fictional values for parser validation only.")
        self.c.drawRightString(PAGE_W - 38, 24, f"Page {self.page} of 6")

    def section(self, title: str) -> None:
        self.c.setFillColor(DARK)
        self.c.roundRect(38, self.y - 3, PAGE_W - 76, 18, 4, stroke=0, fill=1)
        self.c.setFillColor(white)
        self.c.setFont("Helvetica-Bold", 9)
        self.c.drawString(45, self.y + 2, title)
        self.c.setFillColor(black)
        self.y -= 22

    def label_value(self, label: str, value: str, bold: bool = False) -> None:
        self.c.setFillColor(LIGHT if not bold else HexColor("#FFF2B2"))
        self.c.rect(42, self.y - 3, PAGE_W - 84, 15, stroke=1, fill=1)
        self.c.setFillColor(black)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", 8)
        self.c.drawString(48, self.y + 1, label)
        self.c.drawRightString(PAGE_W - 48, self.y + 1, value)
        self.y -= 15

    def finish(self) -> None:
        self.footer()
        self.c.save()


def holding_header(s: Statement) -> None:
    s.c.setFont("Helvetica-Bold", 6.5)
    for x, label in [
        (45, "Description"),
        (185, "Symbol"),
        (263, "Price"),
        (326, "Quantity"),
        (396, "Cost Basis"),
        (468, "Unrealized Gain/Loss"),
        (552, "Value"),
    ]:
        if label in {"Price", "Quantity", "Cost Basis", "Unrealized Gain/Loss", "Value"}:
            s.c.drawRightString(x, s.y, label)
        else:
            s.c.drawString(x, s.y, label)
    s.y -= 13


def holding_row(
    s: Statement,
    description: str,
    symbol: str,
    price: str,
    quantity: str,
    cost: str,
    gain: str,
    value: str,
) -> None:
    s.c.setFont("Helvetica", 7)
    s.c.drawString(45, s.y, description)
    s.c.drawString(185, s.y, symbol)
    s.c.drawRightString(263, s.y, price)
    s.c.drawRightString(326, s.y, quantity)
    s.c.drawRightString(396, s.y, cost)
    s.c.drawRightString(468, s.y, gain)
    s.c.drawRightString(552, s.y, value)
    s.y -= 14


def activity_header(s: Statement) -> None:
    s.c.setFont("Helvetica-Bold", 7)
    s.c.drawString(45, s.y, "Date")
    s.c.drawString(90, s.y, "Description")
    s.c.drawRightString(485, s.y, "Quantity")
    s.c.drawRightString(560, s.y, "Amount")
    s.y -= 14


def activity_row(s: Statement, md: str, description: str, quantity: str, amount: str, continuation: str = "") -> None:
    s.c.setFont("Helvetica", 7.2)
    s.c.drawString(45, s.y, md)
    s.c.drawString(90, s.y, description)
    if quantity:
        s.c.drawRightString(485, s.y, quantity)
    s.c.drawRightString(560, s.y, amount)
    s.y -= 14
    if continuation:
        s.c.drawString(90, s.y, continuation)
        s.y -= 14


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    s = Statement(OUT)

    s.new_page("ACCOUNT STATEMENT")
    s.section("Value Summary")
    s.c.setFont("Helvetica-Bold", 7)
    s.c.drawRightString(PAGE_W - 48, s.y, "This Period")
    s.y -= 13
    for label, value, bold in [
        ("Beginning Value", "$100,000.00", False),
        ("Assets Added to Account", "$12,000.00", False),
        ("Assets Withdrawn from Account", "-$7,000.00", False),
        ("Fees and Charges", "-$50.00", False),
        ("Change in Value", "$3,050.00", False),
        ("Ending Value", "$108,000.00", True),
    ]:
        s.label_value(label, value, bold)
    s.y -= 18
    s.section("Summary of Assets (as of August 28, 2026)")
    for label, value, bold in [
        ("Cash, money market funds and insured bank deposit", "$8,000.00", False),
        ("Stocks", "$25,000.00", False),
        ("Mutual Funds", "$50,000.00", False),
        ("Bonds", "$25,000.00", False),
        ("Total at Edward Jones", "$108,000.00", True),
        ("Account Value", "$108,000.00", True),
    ]:
        s.label_value(label, value, bold)
    s.y -= 18
    s.section("Asset Details (as of August 28, 2026)")
    s.c.setFont("Helvetica", 8)
    s.c.drawString(45, s.y, "Assets held at Edward Jones")
    s.y -= 14
    s.c.drawString(45, s.y, "Cash, money market funds and insured bank deposit")
    s.y -= 14
    s.c.drawString(45, s.y, "Cash")
    s.c.drawRightString(552, s.y, "$8,000.00")
    s.y -= 14
    s.c.drawString(45, s.y, "Total cash, money market funds and insured bank deposit")
    s.c.drawRightString(552, s.y, "$8,000.00")
    s.footer()

    s.new_page("Asset Details")
    s.section("Asset Details (as of August 28, 2026) (continued)")
    s.c.setFont("Helvetica", 8)
    s.c.drawString(45, s.y, "Assets held at Edward Jones")
    s.y -= 16
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Stocks")
    s.y -= 13
    holding_header(s)
    holding_row(s, "Alpha Synthetic Industries", "ALPH", "$200.00", "100.000", "$15,000.00", "$5,000.00", "$20,000.00")
    s.c.setFont("Helvetica", 7)
    s.c.drawString(45, s.y, "Global Innovation Holding")
    s.y -= 15
    holding_row(s, "Beta Fictional Utilities", "BETA", "$100.00", "50.000", "$4,500.00", "$500.00", "$5,000.00")
    s.y -= 10
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Mutual Funds")
    s.y -= 13
    holding_header(s)
    holding_row(s, "Fictional Balanced Fund", "FUNDX", "$50.00", "1,000.000", "$45,000.00", "$5,000.00", "$50,000.00")
    s.footer()

    s.new_page("Asset Details")
    s.section("Asset Details (as of August 28, 2026) (continued)")
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Bonds")
    s.y -= 13
    holding_header(s)
    holding_row(s, "Fictional Municipal Bond 4.25% 08/28/2036", "123456AB7", "$100.00", "25,000", "$25,000.00", "$0.00", "$25,000.00")
    s.y -= 18
    s.label_value("Total Account Value", "$108,000.00", True)
    s.footer()

    s.new_page("Activity")
    s.section("Summary of Activity")
    for label, value, bold in [
        ("Beginning Balance of Cash, Money Market Funds and Insured Bank Deposit", "$2,000.00", False),
        ("Total Additions", "$18,250.00", False),
        ("Total Subtractions", "-$12,250.00", False),
        ("Ending Balance of Cash, Money Market Funds and Insured Bank Deposit", "$8,000.00", True),
    ]:
        s.label_value(label, value, bold)
    s.y -= 18
    s.section("Investment and Other Activity by Date")
    activity_header(s)
    activity_row(s, "08/03", "Deposit ACH CONTRIBUTION", "", "$10,000.00", "Continuation: reference SYNTHETIC-EDJ-001")
    activity_row(s, "08/05", "Transfer In Cash FROM FICTIONAL CUSTODIAN", "", "$2,000.00")
    activity_row(s, "08/07", "Dividend ALPH QUALIFIED DIVIDEND", "", "$200.00")
    activity_row(s, "08/08", "Interest CASH CREDIT INTEREST", "", "$50.00")
    activity_row(s, "08/10", "Buy FUNDX FICTIONAL BALANCED FUND @ $50.00", "100.000", "-$5,000.00")
    activity_row(s, "08/12", "Reinvestment FUNDX DIVIDEND REINVEST @ $50.00", "4.000", "-$200.00")
    s.footer()

    s.new_page("Activity")
    s.section("Investment and Other Activity by Date (continued)")
    activity_header(s)
    activity_row(s, "08/17", "Sell ALPH ALPHA SYNTHETIC INDUSTRIES @ $200.00", "30.000", "$6,000.00")
    activity_row(s, "08/20", "Withdrawal ACH DISTRIBUTION", "", "-$5,000.00")
    activity_row(s, "08/21", "Transfer Out Cash TO FICTIONAL CUSTODIAN", "", "-$2,000.00")
    activity_row(s, "08/28", "Advisory Fee MONTHLY PROGRAM FEE", "", "-$50.00")
    s.y -= 15
    s.label_value("Total Activity", "$6,000.00", True)
    s.footer()

    s.new_page("Realized Gain/Loss")
    s.section("Detail of Realized Gain/Loss From Sale of Securities")
    s.c.setFont("Helvetica-Bold", 6.5)
    for x, label in [
        (45, "Security"),
        (225, "Purchase date"),
        (285, "Sale date"),
        (345, "Quantity"),
        (410, "Cost basis"),
        (475, "Proceeds"),
        (548, "Realized gain/loss"),
    ]:
        if x > 300:
            s.c.drawRightString(x, s.y, label)
        else:
            s.c.drawString(x, s.y, label)
    s.y -= 15
    s.c.setFont("Helvetica", 7)
    s.c.drawString(45, s.y, "ALPH")
    s.c.drawString(225, s.y, "01/15/2022")
    s.c.drawString(285, s.y, "08/17")
    s.c.drawRightString(345, s.y, "30.000")
    s.c.drawRightString(410, s.y, "$4,500.00")
    s.c.drawRightString(475, s.y, "$6,000.00")
    s.c.drawRightString(548, s.y, "$1,500.00")
    s.c.drawString(560, s.y, "LT")
    s.y -= 34
    s.section("Summary of Realized Gain/Loss")
    s.label_value("Short-term (assets held 1 year or less)", "$0.00")
    s.label_value("Long-term (held over 1 year)", "$1,500.00")
    s.label_value("Total", "$1,500.00", True)
    s.finish()

    expectations = {
        "file": OUT.name,
        "institution": "Edward Jones",
        "statementDate": "2026-08-28",
        "account": "7890",
        "accountType": "Brokerage",
        "providerAccountId": ACCOUNT_ID,
        "endingValue": 108000.0,
        "positions": {
            "CASH": 8000.0,
            "ALPH": 20000.0,
            "BETA": 5000.0,
            "FUNDX": 50000.0,
            "123456AB7": 25000.0,
        },
        "transactionCount": 10,
        "transactionTotals": {
            "deposit": 10000.0,
            "transfer_in": 2000.0,
            "dividend": 200.0,
            "interest": 50.0,
            "buy": -5200.0,
            "sell": 6000.0,
            "withdrawal": -5000.0,
            "transfer_out": -2000.0,
            "fee": -50.0,
        },
        "realizedGain": 1500.0,
    }
    EXPECT.write_text(json.dumps(expectations, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    generate()
