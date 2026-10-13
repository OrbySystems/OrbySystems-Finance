#!/usr/bin/env python3
"""Generate a wholly synthetic Empower 401(k) quarterly statement fixture."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT_NAME = "empower-401k-pdf-synthetic-sample.pdf"
PAGE_H = letter[1]

PLAN_FUNDS = [
    # (category, name lines, beginning, deposits, change, withdrawals, ending, shares)
    ("Target Date", ["Sample Target 2045 Trust", "Class A"], "50,000.00", "300.00", "2,100.00", "-5.00", "52,395.00", "1,200.500"),
    ("Index Funds", ["Fictional Large Cap Index"], "30,000.00", "200.00", "900.00", "-3.00", "31,097.00", "410.250"),
    (None, ["Imaginary Bond Fund Admin", "Shares"], "20,000.00", "100.00", "400.00", "-2.00", "20,498.00", "880.125"),
]
PLAN_TOTALS = ("100,000.00", "600.00", "3,400.00", "-10.00", "103,990.00")
PLAN_BRIDGE = [
    ("Balance as of June 30, 2026", "$60,000.00", "$40,000.00", "$100,000.00"),
    ("Payroll Contributions", "400.00", "200.00", "600.00"),
    ("Change in Value", "1,982.00", "1,388.00", "3,370.00"),
    ("Dividends", "18.00", "12.00", "30.00"),
    ("Expenses", "-6.00", "-4.00", "-10.00"),
    ("Balance as of September 30, 2026", "$62,394.00", "$41,596.00", "$103,990.00"),
    ("Vested Balance as of September 30, 2026", "$62,394.00", "$41,596.00", "$103,990.00"),
]
PLAN_CONTRIBUTIONS = [("Jul 15, 2026", "Jul 17, 2026"), ("Jul 31, 2026", "Aug 04, 2026"), ("Aug 14, 2026", "Aug 18, 2026")]


def plan_text(c: canvas.Canvas, x: int, y: float, text: str, size: float = 10, bold: bool = False) -> float:
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, text)
    return y - size - 4


def plan_page(c: canvas.Canvas, number: int, lines: list[str], footer_page: int) -> None:
    y = PAGE_H - 40
    for text in ["JANE SAMPLE", "Plan: 112233-44"] if number > 1 else []:
        y = plan_text(c, 28, y, text)
    for text in lines:
        y = plan_text(c, 28, y, text, 13 if text.endswith("?") else 10)
    plan_text(c, 72, 30, f"SYNTHETIC TEST DATA Page {footer_page} of 9", 7)
    c.showPage()


def generate_plan(output: Path) -> None:
    c = canvas.Canvas(str(output), pagesize=letter, invariant=1)
    bridge = [f"{label} {a} {b} {t}" for label, a, b, t in PLAN_BRIDGE[:1]]
    bridge += [f"{label} {a} {b} {t}" for label, a, b, t in PLAN_BRIDGE[1:]]
    plan_page(c, 1, [
        "Empower", "PO Box 100000", "Sampletown, CO 80000-0000", "JANE SAMPLE",
        "Statement Period: 07/01/2026 - 09/30/2026", "Acct Nbr: 5678", "Plan: 112233-44",
        "What is my account balance?", "$103,990.00", "As of 09/30/2026",
        "How has my account changed?", "Employee Employer Total", *bridge,
    ], 8)
    fund_header = ["Dividends Ending", "Beginning /Change Withdrawals Ending Shares/",
                   "Balance Deposits inValue Transfers /Expenses Balance Shares"]
    plan_page(c, 2, [
        "How is my account invested?",
        "40.00% Target Date", "40.00% Index Funds", "20.00% Bond Funds",
        *fund_header,
        "TargetDate",
        f"{PLAN_FUNDS[0][1][0]} " + " ".join(PLAN_FUNDS[0][2:]),
        PLAN_FUNDS[0][1][1],
        "IndexFunds",
        f"{PLAN_FUNDS[1][1][0]} " + " ".join(PLAN_FUNDS[1][2:]),
    ], 9)
    plan_page(c, 3, [
        "How is my account invested? (continued)", *fund_header,
        "BondFunds",
        f"{PLAN_FUNDS[2][1][0]} " + " ".join(PLAN_FUNDS[2][2:]),
        PLAN_FUNDS[2][1][1],
        "Totals " + " ".join(PLAN_TOTALS),
        "How is my account broken down?",
        "Dividends Withdrawals", "Beginning /Change /Expenses Ending Percent Vested",
        "Balance Deposits inValue /Transfers Balance Vested Balance",
        "Employee Pre Tax 60,000.00 400.00 2,000.00 -6.00 62,394.00 100% 62,394.00",
        "Employer Match 40,000.00 200.00 1,400.00 -4.00 41,596.00 100% 41,596.00",
        "Totals 100,000.00 600.00 3,400.00 -10.00 103,990.00 103,990.00",
    ], 8)
    rows = ["What activity occurred this period?", "Payroll Posted", "Date Date Amount", "Deposits/Contributions"]
    rows += [f"Contribution {payroll} {posted} 200.00" for payroll, posted in PLAN_CONTRIBUTIONS]
    rows += ["Total Deposits/Contributions 600.00", "Expenses"]
    rows += ["Investment Option Service Fee Credit Jul 13, 2026 2.00"]
    rows += [f"Plan Administration Account Fee {d} -4.00" for d in ("Jul 20, 2026", "Aug 12, 2026")]
    rows += ["Plan Recordkeeping Account Fee Sep 12, 2026 -4.00", "Total Expenses -10.00"]
    rows += ["Activity Detail # Shares Price/Share", "Date Amount InvestmentOption /Shares Price"]
    rows += ["Dividends/Capital Gains",
             "Dividend Aug 05, 2026 12.00 Fictional Large Cap Index 0.250 48.000",
             "Long Term Capital Gain Sep 16, 2026 18.00 Sample Target 2045 Trust Class A 0.300 60.000",
             "Total Dividends/Capital Gains 30.00"]
    rows += ["What is the rate of return on my retirement account(s)?"]
    plan_page(c, 4, rows, 9)
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generate_plan(out / OUT_NAME)


if __name__ == "__main__":
    main()
