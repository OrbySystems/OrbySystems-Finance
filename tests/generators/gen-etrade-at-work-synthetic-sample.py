#!/usr/bin/env python3
"""Generate a fictional E*TRADE Morgan Stanley at Work Client Statement."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "etrade-at-work-synthetic-202406.pdf"
EXPECT = ROOT / "fixtures" / "etrade-at-work-synthetic-202406.expectations.json"
PAGE_W, PAGE_H = landscape(letter)
PERIOD = "April 1- June30, 2024"
ACCOUNT_ID = "999-111111-2468"


def _header(c: canvas.Canvas, page: int, section: str = "") -> None:
    c.setFont("Helvetica-Bold", 10)
    c.drawString(36, PAGE_H - 36, "CLIENT STATEMENT")
    c.setFont("Helvetica", 9)
    c.drawString(160, PAGE_H - 36, f"For the Period {PERIOD}")
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(PAGE_W - 36, PAGE_H - 34, "E*TRADE")
    c.setFont("Helvetica", 8)
    c.drawRightString(PAGE_W - 36, PAGE_H - 47, "from Morgan Stanley")
    c.drawRightString(PAGE_W - 36, PAGE_H - 62, f"Page {page} of 6")
    if section:
        c.setFillColorRGB(0.78, 0.84, 0.94)
        c.rect(30, PAGE_H - 105, PAGE_W - 60, 32, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 16)
        c.drawString(38, PAGE_H - 95, section)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(36, 22, "SYNTHETIC TEST DATA - NOT AN OFFICIAL STATEMENT")


def _summary_row(c: canvas.Canvas, y: float, label: str, current: str, year: str) -> None:
    c.setFont("Helvetica-Bold" if label.startswith(("TOTAL", "Net")) else "Helvetica", 8.5)
    c.drawString(38, y, label)
    c.drawRightString(300, y, current)
    c.drawRightString(405, y, year)


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=landscape(letter), invariant=1)
    c.setTitle("Synthetic ETRADE at Work Client Statement")
    c.setAuthor("Orby parser test fixture")

    _header(c, 1)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(38, 460, "STATEMENT FOR:")
    c.setFont("Helvetica", 9)
    c.drawString(46, 442, "TEST PARTICIPANT")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(430, 460, "Beginning Total Value")
    c.drawRightString(735, 460, "$2,500.00")
    c.drawString(430, 442, "Ending Total Value")
    c.drawRightString(735, 442, "$2,500.00")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(38, 310, "Morgan Stanley Smith Barney LLC. Member SIPC.")
    c.drawString(38, 296, "E*TRADE is a business of Morgan Stanley.")
    c.setFont("Helvetica-Bold", 19)
    c.drawRightString(PAGE_W - 36, 70, "SYNTHETIC")
    c.showPage()

    for page in (2, 3):
        _header(c, page, "Expanded Disclosures" if page == 2 else "Expanded Disclosures (CONTINUED)")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(38, 450, "Synthetic disclosure page")
        c.setFont("Helvetica", 8)
        c.drawString(38, 430, "This fictional page preserves statement ordering for parser validation.")
        c.showPage()

    _header(c, 4, "Account Summary")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(430, PAGE_H - 120, "Morgan Stanley at Work Self-Directed Account")
    c.setFont("Helvetica", 8)
    c.drawString(38, PAGE_H - 120, f"Account Summary {ACCOUNT_ID} SUBJECT TO TEST RULES")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(38, 450, "CHANGE IN VALUE OF YOUR ACCOUNT")
    c.setFont("Helvetica", 8)
    c.drawRightString(300, 432, "This Period")
    c.drawRightString(405, 432, "This Year")
    _summary_row(c, 412, "TOTAL BEGINNING VALUE", "$2,500.00", "$2,400.00")
    _summary_row(c, 394, "Credits", "—", "$100.00")
    _summary_row(c, 376, "Debits", "—", "—")
    _summary_row(c, 358, "Security Transfers", "—", "—")
    _summary_row(c, 340, "Net Credits/Debits/Transfers", "—", "$100.00")
    _summary_row(c, 322, "Change in Value", "—", "—")
    _summary_row(c, 304, "TOTAL ENDING VALUE", "$2,500.00", "$2,500.00")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(38, 248, "ASSET ALLOCATION")
    c.setFont("Helvetica", 8.5)
    c.drawString(48, 225, "Cash")
    c.drawRightString(300, 225, "$2,500.00")
    c.drawRightString(405, 225, "100.00%")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(38, 207, "TOTAL VALUE")
    c.drawRightString(300, 207, "$2,500.00")
    c.drawRightString(405, 207, "100.00%")
    c.showPage()

    _header(c, 5, "Account Summary")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(38, 450, "BALANCE SHEET")
    c.drawString(430, 450, "CASH FLOW")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(430, 420, "OPENING CASH, BDP, MMFs")
    c.drawRightString(735, 420, "$2,500.00")
    c.drawString(430, 396, "Total Investment Related Activity")
    c.drawRightString(735, 396, "—")
    c.drawString(430, 372, "CLOSING CASH, BDP, MMFs")
    c.drawRightString(735, 372, "$2,500.00")
    c.drawString(430, 320, "GAIN/(LOSS) SUMMARY")
    c.drawString(430, 294, "TOTAL GAIN/(LOSS)")
    c.drawRightString(735, 294, "—")
    c.showPage()

    _header(c, 6, "Account Detail")
    c.setFont("Helvetica", 8)
    c.drawString(38, PAGE_H - 120, f"Account Detail {ACCOUNT_ID} SUBJECT TO TEST RULES")
    c.setFont("Helvetica", 8.5)
    c.drawRightString(PAGE_W - 38, 476, "Brokerage Account")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(38, 458, "HOLDINGS")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(38, 410, "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS")
    c.setFont("Helvetica", 8.5)
    c.drawString(38, 376, "MORGAN STANLEY BANK N.A.")
    c.drawRightString(570, 376, "$2,500.00")
    c.drawRightString(735, 376, "0.010")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(38, 342, "CASH, BDP, AND MMFs")
    c.drawRightString(250, 342, "100.00%")
    c.drawRightString(570, 342, "$2,500.00")
    c.drawString(38, 306, "TOTAL VALUE")
    c.drawRightString(250, 306, "100.00%")
    c.drawRightString(330, 306, "—")
    c.drawRightString(570, 306, "$2,500.00")
    c.drawRightString(630, 306, "N/A")
    c.save()

    EXPECT.write_text(
        json.dumps(
            {
                "file": OUT.name,
                "institution": "E*TRADE from Morgan Stanley",
                "statementDate": "2024-06-30",
                "account": "2468",
                "accountType": "Brokerage",
                "providerAccountId": ACCOUNT_ID,
                "holdingCount": 1,
                "endingValue": 2500.0,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build()
