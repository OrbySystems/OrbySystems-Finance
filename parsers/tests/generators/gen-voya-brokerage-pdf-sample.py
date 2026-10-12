#!/usr/bin/env python3
"""Generate a fictional Voya-style 401(k) plan activity statement.

Invented plan, participant, funds and figures; labels and table layout match
the real format. Output: voya-brokerage-pdf-synthetic-sample.pdf next to this file.
"""
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent / "voya-brokerage-pdf-synthetic-sample.pdf"

FUNDS = [  # name, begin, gain, end, shares, price
    ("Synthetic Index Fund A", "$10,000.00", "$250.00", "$10,500.00", "100.0000", "$105.0000"),
    ("Synthetic Bond Fund B", "$20,000.00", "-$40.00", "$20,460.00", "1,023.0000", "$20.0000"),
]
TOTAL = ("$30,000.00", "$0.00", "$210.00", "$30,960.00")
PERIOD = "January 01, 2030 - March 31, 2030"


def page(c, lines):
    y = 740
    for text in lines:
        c.setFont("Helvetica", 9)
        c.drawString(36, y, text)
        y -= 14
    c.showPage()


def build():
    c = canvas.Canvas(str(OUT), pagesize=letter, invariant=1)
    c.setTitle("Synthetic Voya Plan Statement")
    page(c, [
        "Voya Financial At Your Service",
        "SYNTHETIC TEST DATA - NOT AN OFFICIAL STATEMENT",
        PERIOD,
        "Your Account Balance as of",
        "March 31, 2030",
        "$30,960.00",
        "Account Balance on 01/01/2030 $30,000.00",
        "Account Balance on 03/31/2030 $30,960.00",
    ])
    page(c, [
        PERIOD,
        "Voya Financial TEST PARTICIPANT",
        "Activity Statement for Your 401(K) Plan 99A123",
        "Your Current Investment Portfolio for Plan 99A123",
        "Investment Balance on Total Activity Balance on Shares Price",
        *[f"{n} {b} $0.00 {g} {e} {s} {p}" for n, b, g, e, s, p in FUNDS],
        "Total " + " ".join(TOTAL),
    ])
    c.save()


if __name__ == "__main__":
    build()
