#!/usr/bin/env python3
"""Generate reconciled fictional statements for provisional institutions.

The documents reproduce first-party section names and information hierarchy,
not logos or artwork. Every identity, identifier, security, and amount is
invented, and every page is visibly marked as synthetic test data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from institutions import common  # noqa: E402
from institutions.provisional_brokerage_common import PERIOD, PROFILES, STATEMENT_DATE  # noqa: E402


OUT_DIR = REPO / "tests" / "fixtures"
PAGE_W, PAGE_H = letter
PAGE_COUNT = 6

THEMES = [
    ("#17365D", "#D9EAF7"),
    ("#7A1F2B", "#F7E6E8"),
    ("#174A3B", "#E1F1EB"),
    ("#4B286D", "#EEE5F5"),
    ("#164B77", "#E0EDF7"),
    ("#5B3A29", "#F1E9E4"),
    ("#1E5A43", "#E2F0EA"),
    ("#334155", "#E8EDF2"),
]


class Statement:
    def __init__(self, path: Path, profile: dict, theme: tuple[str, str]):
        self.profile = profile
        self.dark = HexColor(theme[0])
        self.light = HexColor(theme[1])
        self.c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
        self.page = 0
        self.y = 0.0

    def new_page(self, page_title: str) -> None:
        if self.page:
            self.c.showPage()
        self.page += 1
        self.c.setFillColor(self.dark)
        self.c.rect(0, PAGE_H - 20, PAGE_W, 20, stroke=0, fill=1)
        self.c.setFillColor(self.dark)
        self.c.setFont("Helvetica-Bold", 15)
        self.c.drawString(38, PAGE_H - 49, self.profile["brand"])
        self.c.setFont("Helvetica", 6.5)
        self.c.drawRightString(PAGE_W - 38, PAGE_H - 45, self.profile["legal"])
        self.c.setFont("Helvetica-Bold", 12)
        self.c.drawString(38, PAGE_H - 75, page_title)
        self.c.setFont("Helvetica", 8)
        self.c.drawString(38, PAGE_H - 94, f"Statement Period: {PERIOD}")
        self.c.drawString(315, PAGE_H - 94, f"Account Number: {self.profile['account_id']}")
        self.c.drawString(38, PAGE_H - 108, f"Account Type: {self.profile['account_title']}")
        self.c.setFillColor(HexColor("#9B111E"))
        self.c.setFont("Helvetica-Bold", 6.2)
        self.c.drawRightString(PAGE_W - 38, PAGE_H - 108, "SYNTHETIC TEST DATA - NOT AN OFFICIAL STATEMENT")
        self.c.setFillColor(black)
        self.y = PAGE_H - 140

    def footer(self) -> None:
        self.c.setFillColor(self.dark)
        self.c.setFont("Helvetica", 7)
        self.c.drawString(38, 24, "Fictional values for parser validation only.")
        self.c.drawRightString(PAGE_W - 38, 24, f"Page {self.page} of {PAGE_COUNT}")

    def section(self, title: str) -> None:
        self.c.setFillColor(self.dark)
        self.c.roundRect(38, self.y - 3, PAGE_W - 76, 18, 3, stroke=0, fill=1)
        self.c.setFillColor(white)
        self.c.setFont("Helvetica-Bold", 9)
        self.c.drawString(45, self.y + 2, title)
        self.c.setFillColor(black)
        self.y -= 23

    def label_value(self, label: str, value: str, bold: bool = False) -> None:
        self.c.setFillColor(self.light)
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
    s.c.drawString(45, s.y, "Symbol/CUSIP")
    s.c.drawString(115, s.y, "Description")
    s.c.drawRightString(355, s.y, "Quantity")
    s.c.drawRightString(415, s.y, "Price")
    s.c.drawRightString(485, s.y, "Cost Basis")
    s.c.drawRightString(560, s.y, "Market Value")
    s.y -= 13


def holding_row(s: Statement, symbol: str, description: str, quantity: str,
                price: str, cost: str, value: str, continuation: str = "") -> None:
    s.c.setFont("Helvetica", 7)
    s.c.drawString(45, s.y, symbol)
    s.c.drawString(115, s.y, description)
    s.c.drawRightString(355, s.y, quantity)
    s.c.drawRightString(415, s.y, price)
    s.c.drawRightString(485, s.y, cost)
    s.c.drawRightString(560, s.y, value)
    s.y -= 14
    if continuation:
        s.c.drawString(115, s.y, continuation)
        s.y -= 14


def activity_header(s: Statement) -> None:
    s.c.setFont("Helvetica-Bold", 7)
    s.c.drawString(45, s.y, "Date")
    s.c.drawString(85, s.y, "Action and Description")
    s.c.drawRightString(485, s.y, "Quantity")
    s.c.drawRightString(560, s.y, "Amount")
    s.y -= 14


def activity_row(s: Statement, md: str, body: str, amount: str,
                 quantity: str = "", continuation: str = "") -> None:
    s.c.setFont("Helvetica", 7.1)
    s.c.drawString(45, s.y, md)
    s.c.drawString(85, s.y, body)
    if quantity:
        s.c.drawRightString(485, s.y, quantity)
    s.c.drawRightString(560, s.y, amount)
    s.y -= 14
    if continuation:
        s.c.drawString(85, s.y, continuation)
        s.y -= 14


def generate_one(profile_key: str, profile: dict, index: int) -> None:
    filename = f"{profile['slug']}-synthetic-202608.pdf"
    output = OUT_DIR / filename
    expectations_path = output.with_suffix(".expectations.json")
    s = Statement(output, profile, THEMES[index % len(THEMES)])
    labels = profile["labels"]

    s.new_page(profile["title"])
    s.section(profile["summary"])
    for key, value, bold in [
        ("beginning", "$100,000.00", False),
        ("deposits", "$12,000.00", False),
        ("withdrawals", "-$7,000.00", False),
        ("income", "$250.00", False),
        ("fees", "-$50.00", False),
        ("market", "$2,800.00", False),
        ("ending", "$108,000.00", True),
    ]:
        s.label_value(labels[key], value, bold)
    s.y -= 16
    s.section(profile["holdings"])
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Cash and Cash Equivalents")
    s.y -= 14
    holding_header(s)
    holding_row(s, "CASH", "Cash and Sweep", "8,000.000", "$1.00", "$8,000.00", "$8,000.00")
    s.footer()

    s.new_page(profile["holdings"])
    s.section(f"{profile['holdings']} (continued)")
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Equities")
    s.y -= 14
    holding_header(s)
    holding_row(s, "ALPH", "Alpha Synthetic Industries", "100.000", "$200.00", "$15,000.00", "$20,000.00", "Global Innovation Holding")
    holding_row(s, "BETA", "Beta Fictional Utilities", "50.000", "$100.00", "$4,500.00", "$5,000.00")
    s.y -= 10
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Mutual Funds")
    s.y -= 14
    holding_header(s)
    holding_row(s, "FUNDX", "Fictional Balanced Fund", "1,000.000", "$50.00", "$45,000.00", "$50,000.00")
    s.footer()

    s.new_page(profile["holdings"])
    s.section(f"{profile['holdings']} (continued)")
    s.c.setFont("Helvetica-Bold", 8)
    s.c.drawString(45, s.y, "Fixed Income")
    s.y -= 14
    holding_header(s)
    holding_row(s, "123456AB7", "Fictional Municipal Bond 4.25% 08/28/2036", "25,000", "$100.00", "$25,000.00", "$25,000.00")
    s.y -= 20
    total_word = "Assets" if profile_key == "merrill_wealth" else "Holdings"
    s.label_value(f"Total {total_word}", "$108,000.00", True)
    s.y -= 18
    s.section(profile["activity_summary"])
    for label, value, bold in [
        ("Beginning Cash", "$2,000.00", False),
        ("Credits", "$18,250.00", False),
        ("Debits", "-$12,250.00", False),
        ("Ending Cash", "$8,000.00", True),
    ]:
        s.label_value(label, value, bold)
    s.footer()

    s.new_page(profile["activity"])
    s.section(profile["activity"])
    activity_header(s)
    activity_row(s, "08/03", "Deposit ACH CONTRIBUTION", "$10,000.00", continuation=f"Reference SYNTHETIC-{profile['slug'].upper()}-001")
    activity_row(s, "08/05", "Transfer In FROM FICTIONAL CUSTODIAN", "$2,000.00")
    activity_row(s, "08/07", "Dividend ALPH QUALIFIED DIVIDEND", "$200.00")
    activity_row(s, "08/08", "Interest CASH CREDIT INTEREST", "$50.00")
    activity_row(s, "08/10", "Buy FUNDX FICTIONAL BALANCED FUND @ $50.00", "-$5,000.00", "100.000")
    activity_row(s, "08/12", "Reinvestment FUNDX DIVIDEND REINVEST @ $50.00", "-$200.00", "4.000")
    s.footer()

    s.new_page(profile["activity"])
    s.section(f"{profile['activity']} (continued)")
    activity_header(s)
    activity_row(s, "08/17", "Sell ALPH ALPHA SYNTHETIC INDUSTRIES @ $200.00", "$6,000.00", "30.000")
    activity_row(s, "08/20", "Withdrawal ACH DISTRIBUTION", "-$5,000.00")
    activity_row(s, "08/21", "Transfer Out TO FICTIONAL CUSTODIAN", "-$2,000.00")
    activity_row(s, "08/28", "Advisory Fee MONTHLY PROGRAM FEE", "-$50.00")
    s.y -= 18
    s.label_value("Total Activity", "$6,000.00", True)
    s.footer()

    s.new_page(profile["realized"])
    s.section(profile["realized"])
    s.c.setFont("Helvetica-Bold", 6.5)
    for x, label in [
        (45, "Security"), (190, "Purchase Date"), (270, "Sale Date"),
        (350, "Quantity"), (420, "Cost Basis"), (485, "Proceeds"),
        (560, "Gain/Loss"),
    ]:
        if x >= 350:
            s.c.drawRightString(x, s.y, label)
        else:
            s.c.drawString(x, s.y, label)
    s.y -= 15
    s.c.setFont("Helvetica", 7)
    s.c.drawString(45, s.y, "ALPH")
    s.c.drawString(190, s.y, "01/15/2022")
    s.c.drawString(270, s.y, "08/17")
    s.c.drawRightString(350, s.y, "30.000")
    s.c.drawRightString(420, s.y, "$4,500.00")
    s.c.drawRightString(485, s.y, "$6,000.00")
    s.c.drawRightString(548, s.y, "$1,500.00")
    s.c.drawString(560, s.y, "LT")
    s.y -= 35
    s.label_value("Total Realized Gain/Loss", "$1,500.00", True)
    s.finish()

    expectations = {
        "profile": profile_key,
        "file": filename,
        "institution": profile["institution"],
        "statementDate": STATEMENT_DATE,
        "account": "".join(ch for ch in profile["account_id"] if ch.isdigit())[-4:],
        "accountType": common.classify_account_type(profile["account_title"], "Brokerage"),
        "providerAccountId": profile["account_id"],
        "endingValue": 108000.0,
        "positions": {"CASH": 8000.0, "ALPH": 20000.0, "BETA": 5000.0, "FUNDX": 50000.0, "123456AB7": 25000.0},
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
    expectations_path.write_text(json.dumps(expectations, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (key, profile) in enumerate(PROFILES.items()):
        generate_one(key, profile, index)


if __name__ == "__main__":
    main()
