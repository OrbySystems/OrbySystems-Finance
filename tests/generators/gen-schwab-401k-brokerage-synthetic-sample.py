#!/usr/bin/env python3
"""Generate a fictional Schwab Retirement Plan Services-like statement.

The fixture preserves the public section labels and table geometry needed by
the parser while using invented plan, participant, dates, funds, and values.
It contains no Schwab or customer artwork and is visibly marked synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "schwab-401k-synthetic-202606.pdf"
EXPECT = ROOT / "fixtures" / "schwab-401k-synthetic-202606.expectations.json"
PAGE_W, PAGE_H = landscape(letter)


def _header(c: canvas.Canvas, page: int) -> None:
    c.setFont("Helvetica-Bold", 8)
    c.drawString(36, PAGE_H - 34, "SYNTHETIC TEST DATA - NOT AN OFFICIAL STATEMENT")
    c.drawRightString(PAGE_W - 36, PAGE_H - 34, f"PAGE {page} OF 2")
    c.setLineWidth(2)
    c.line(36, PAGE_H - 42, PAGE_W - 36, PAGE_H - 42)


def _summary_row(c: canvas.Canvas, y: float, label: str, period: str, year: str) -> None:
    c.setFont("Helvetica", 9)
    c.drawString(36, y, label)
    c.drawRightString(220, y, period)
    c.drawRightString(292, y, year)


def _holding_row(
    c: canvas.Canvas,
    y: float,
    description: str,
    percent: str,
    quantity: str,
    price: str,
    value: str,
) -> None:
    c.setFont("Helvetica", 9)
    c.drawString(36, y, description)
    c.drawRightString(284, y, percent)
    c.drawRightString(380, y, quantity)
    c.drawRightString(476, y, price)
    c.drawRightString(570, y, value)


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=landscape(letter))
    c.setTitle("Synthetic Retirement Plan Statement")
    c.setAuthor("Orby parser test fixture")

    _header(c, 1)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(36, 530, "YOUR SYNTHETIC INDUSTRIES U.S. 401(K) PLAN STATEMENT")
    c.setFont("Helvetica", 10)
    c.drawString(36, 506, "Period covered: APRIL 1, 2026 TO JUNE 30, 2026")
    c.drawString(420, 506, "Prepared for: TEST PARTICIPANT")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(36, 466, "Your Account Value")
    c.drawRightString(292, 466, "$110,000.00")
    c.line(36, 456, 292, 456)
    c.drawString(36, 438, "Change in Plan Account Value")
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(220, 418, "This Period")
    c.drawRightString(292, 418, "This Year")
    _summary_row(c, 400, "Beginning Value", "$100,000.00", "$95,000.00")
    _summary_row(c, 384, "Your Contributions", "3,000.00", "6,000.00")
    _summary_row(c, 368, "Employer Contributions", "1,500.00", "3,000.00")
    _summary_row(c, 352, "Individual Transaction Fees*", "0.00", "0.00")
    _summary_row(c, 336, "Plan Administration and Other Fees*", "(5.00)", "(10.00)")
    _summary_row(c, 320, "Gain/Loss/Net Income", "5,505.00", "6,010.00")
    c.line(36, 312, 292, 312)
    _summary_row(c, 296, "Ending Value", "$110,000.00", "$110,000.00")
    c.setFont("Helvetica", 8)
    c.drawString(36, 274, "* Fictional values for parser validation only.")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(420, 466, "Your Positions")
    c.setFont("Helvetica", 9)
    c.drawString(420, 444, "Stocks & stock funds 50%")
    c.drawString(420, 428, "Capital preservation funds 50%")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(594, 398, "Contact Us")
    c.setFont("Helvetica", 9)
    c.drawString(594, 382, "Schwab Retirement Plan Services, Inc.")
    c.drawString(594, 366, "workplace.schwab.com")
    c.saveState()
    c.setFillGray(0.35)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(PAGE_W - 36, 70, "SYNTHETIC")
    c.restoreState()
    c.showPage()

    _header(c, 2)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, 540, "SYNTHETIC INDUSTRIES U.S. 401(K) PLAN")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(36, 508, "Asset Allocation and Account Value")
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(284, 484, "Percent of Total")
    c.drawRightString(380, 484, "Number of Shares")
    c.drawRightString(476, 484, "Share Price")
    c.drawRightString(570, 484, "Value as of 6/30/2026")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, 458, "STOCKS & STOCK FUNDS")
    c.drawRightString(284, 458, "50%")
    _holding_row(c, 438, "Synthetic Growth Trust", "20%", "100.0000", "$220.00", "$22,000.00")
    _holding_row(c, 420, "Broad Market Index Fund", "30%", "200.0000", "$165.00", "$33,000.00")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, 392, "CAPITAL PRESERVATION FUNDS")
    c.drawRightString(284, 392, "50%")
    _holding_row(c, 372, "Synthetic Stable Value Fund", "50%", "--", "--", "$55,000.00")
    c.line(36, 358, 570, 358)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, 342, "TOTAL ACCOUNT VALUE")
    c.drawRightString(284, 342, "100%")
    c.drawRightString(570, 342, "$110,000.00")
    c.setFont("Helvetica", 8)
    c.drawString(36, 310, "All plan, participant, fund, date, and monetary data on this page is fictional.")
    c.saveState()
    c.setFillGray(0.35)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(PAGE_W - 36, 70, "SYNTHETIC")
    c.restoreState()
    c.save()

    EXPECT.write_text(
        json.dumps(
            {
                "institution": "Charles Schwab",
                "statementDate": "2026-06-30",
                "accountType": "401(k)",
                "holdingCount": 3,
                "transactionCount": 3,
                "endingValue": 110000.0,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build()
