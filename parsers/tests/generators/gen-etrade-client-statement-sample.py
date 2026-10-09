#!/usr/bin/env python3
"""Generate a fictional E*TRADE from Morgan Stanley CLIENT STATEMENT.

The demo statement for etrade_brokerage.py's Client Statement layout: a
cover, a disclosures page, two Account Summary pages (CHANGE IN VALUE,
ASSET ALLOCATION, BALANCE SHEET | CASH FLOW, INCOME AND DISTRIBUTION |
GAIN/(LOSS) SUMMARY) and three Account Detail pages (HOLDINGS with cash,
common stocks, short calls and exchange-traded funds; ACTIVITY with the
cash flow by date, the bank deposit sweep and an option expiration).

Every name, ticker, figure, date and the account number is invented; the
words are the layout's own. The figures are computed from the positions
and the month's activity below, so every total the statement prints adds
up, and amounts are drawn right-aligned in their columns, so the Statement
Scrambler finds and keeps those relations.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "etrade-client-statement-synthetic-202607.pdf"
EXPECT = ROOT / "fixtures" / "etrade-client-statement-synthetic-202607.expectations.json"
PAGE_W, PAGE_H = landscape(letter)
PAGES = 7

PERIOD = "July 1-31, 2026"
STATEMENT_DATE = "2026-07-31"
ACCOUNT_ID = "731-406259-318"
HOLDER = "TAYLOR EXAMPLE"
TITLE = "Morgan Stanley at Work Self-Directed Account"
BANK = "MORGAN STANLEY BANK N.A."

# The month's cash flow, in cents. Opening cash, then the rows of CASH FLOW
# ACTIVITY BY DATE.
#
# One row per CASH FLOW summary line (one Sold, one Bought, one row per
# income line): the Statement Scrambler fakes the same printed figure the
# same way everywhere, which is what ties these rows to Purchases, Sales
# and Redemptions and the income lines, and so to NET CREDITS/(DEBITS).
# It finds NET as Purchases + Sales + Income (the shortest run of a column
# that adds up to it), never as the rows themselves, so a second Sold row
# would leave the rows free to stop adding up in a scrambled copy. No money
# moves in or out this month either: with Credits and Net printed in CHANGE
# IN VALUE's This Period column, the Scrambler no longer finds beginning +
# change = ending there, and a scrambled copy fails the parser's summary
# identity.
OPENING_CASH = 184717
# (trade, settle, activity, description, comments, quantity, price, amount,
#  continuation, symbol, transaction_type, signed quantity)
CASH_ROWS = [
    ("7/14", "7/15", "Sold", "CALL HBVS 08/21/26 150.000", "ACTED AS AGENT", "2.000", "3.1500", 62866,
     "UNSOLICITED TRADE; OPENING", "HBVS260821C150", "sell", -2.0),
    ("7/15", "", "Qualified Dividend", "LAKESIDE MATERIALS CORP", "", "", "", 14400, "",
     "LKMC", "dividend", None),
    ("7/22", "7/23", "Bought", "EXAMPLE QUALITY GROWTH ETF", "ACTED AS AGENT", "25.000", "49.8200", -124550,
     "UNSOLICITED TRADE", "EXQG", "buy", 25.0),
    ("7/30", "", "Dividend", "EXAMPLE QUALITY GROWTH ETF", "", "", "", 775, "",
     "EXQG", "dividend", None),
    ("7/31", "", "Interest Income", f"{BANK} (Period 07/01-07/31)", "", "", "", 42, "",
     "", "interest", None),
]
# The bank deposit program sweep: the same cash, by settlement date.
SWEEP_ROWS = [
    ("7/15", "Automatic Investment", 62866),
    ("7/15", "Automatic Investment", 14400),
    ("7/23", "Automatic Redemption", -124550),
    ("7/30", "Automatic Investment", 775),
    ("7/31", "Automatic Investment", 42),
]
# A covered call written in June that expired worthless this month.
EXPIRED = ("7/17", "Option Expired", "CALL QFEC 07/17/26 45.000", "EXPIRED OPTIONS", "1.000", "QFEC260717C45")

# Positions at month end: (description, ticker, quantity, price, total cost
# in cents, estimated annual income in cents, continuation line).
COMMON_STOCKS = [
    ("HARBORVIEW SYSTEMS INC", "HBVS", "200.000", "142.350", 2146000, 16000,
     "Rating: Morgan Stanley: 2, Morningstar: 3; Asset Class: Equities"),
    ("LAKESIDE MATERIALS CORP", "LKMC", "300.000", "58.120", 1591200, 57600,
     "Next Dividend Payable 10/2026; Asset Class: Equities"),
    ("QUILLFIELD ENERGY CO", "QFEC", "100.000", "41.640", 370000, 14000,
     "Asset Class: Equities"),
    ("NORTHGATE FOODS INC", "NGFD", "80.000", "33.900", 248000, 9600,
     "Next Dividend Payable 11/2026; Asset Class: Equities"),
]
# Short calls: (underlying, root, strike, expiry, contracts, contract price,
# total cost in cents (the premium received, negative), OSI date+strike).
# The HBVS calls were sold this month, the LKMC ones in June.
OPTIONS = [
    ("HARBORVIEW SYSTEMS INC", "HBVS", "150.000", "08/21/2026", 2, "1.425", -62866, "260821C00150000"),
    ("LAKESIDE MATERIALS CORP", "LKMC", "62.500", "08/21/2026", 3, "0.840", -32799, "260821C00062500"),
]
ETFS = [
    ("EXAMPLE TOTAL MARKET ETF", "EXTM", "150.000", "96.480", 1215000, 20100,
     "Next Dividend Payable 09/2026; Asset Class: Equities"),
    ("EXAMPLE QUALITY GROWTH ETF", "EXQG", "75.000", "49.860", 370050, 13950,
     "Asset Class: Equities"),
]
CASH_INCOME = 69  # the bank deposit program's estimated annual income

# Last month's balance sheet and this year's figures (cents).
LAST_STOCKS, LAST_ETFS = 4967135, 1689420
YEAR_BEGINNING = 5938014
YEAR_CREDITS, YEAR_DEBITS = 950000, -200000
YEAR_PURCHASES, YEAR_SALES = -1638020, 794137
YEAR_INCOME = {"Qualified Dividends": 98040, "Other Dividends": 27618, "Interest": 348}
# Realized gain this period: the expired QFEC call's premium (short-term).
REALIZED_PERIOD = {"st_gain": 8435, "st_loss": 0, "lt_gain": 0}
REALIZED_YEAR = {"st_gain": 111820, "st_loss": -9640, "lt_gain": 51233}
UNREALIZED_ST = {"st_gain": 42065, "st_loss": -1230}


def money(cents: int | None, dollar: bool = False) -> str:
    """A statement cell: "1,234.56", "(1,234.56)", "$1,234.56", "$(1,234.56)",
    or "—" for zero/none."""
    if not cents:
        return "—"
    text = f"{abs(cents) / 100:,.2f}"
    if cents < 0:
        text = f"({text})"
    return f"${text}" if dollar else text


def percent(part: int, whole: int) -> str:
    return f"{part * 100 / whole:.2f}"


def _price_cents(quantity: str, price: str, multiplier: int = 1) -> int:
    return round(float(quantity) * float(price) * multiplier * 100)


# --- the figures, derived ------------------------------------------------------

def figures() -> dict:
    stocks = []
    for name, ticker, qty, price, cost, income, note in COMMON_STOCKS:
        value = _price_cents(qty, price)
        stocks.append({"name": name, "ticker": ticker, "qty": qty, "price": price, "cost": cost,
                       "value": value, "gain": value - cost, "income": income, "note": note})
    options = []
    for name, root, strike, expiry, contracts, price, cost, osi in OPTIONS:
        value = -_price_cents(str(contracts), price, 100)
        options.append({"name": name, "root": root, "strike": strike, "expiry": expiry,
                        "contracts": contracts, "price": price, "cost": cost, "value": value,
                        "gain": value - cost, "osi": osi})
    etfs = []
    for name, ticker, qty, price, cost, income, note in ETFS:
        value = _price_cents(qty, price)
        etfs.append({"name": name, "ticker": ticker, "qty": qty, "price": price, "cost": cost,
                     "value": value, "gain": value - cost, "income": income, "note": note})

    def total(rows, key):
        return sum(row[key] for row in rows)

    net = sum(row[7] for row in CASH_ROWS)
    assert net == sum(row[2] for row in SWEEP_ROWS)
    cash = OPENING_CASH + net
    common = {k: total(stocks, k) for k in ("cost", "value", "gain", "income")}
    opts = {k: total(options, k) for k in ("cost", "value", "gain")}
    stock_section = {k: common[k] + opts.get(k, 0) for k in ("cost", "value", "gain", "income")}
    etf_section = {k: total(etfs, k) for k in ("cost", "value", "gain", "income")}
    ending = cash + stock_section["value"] + etf_section["value"]
    credits = sum(row[7] for row in CASH_ROWS if row[10] == "deposit")
    debits = sum(row[7] for row in CASH_ROWS if row[10] == "withdrawal")
    purchases = sum(row[7] for row in CASH_ROWS if row[10] == "buy")
    sales = sum(row[7] for row in CASH_ROWS if row[10] == "sell")
    income = sum(row[7] for row in CASH_ROWS if row[10] in ("dividend", "interest"))
    beginning = OPENING_CASH + LAST_STOCKS + LAST_ETFS
    pcts = {
        "cash": percent(cash, ending),
        "stocks": percent(stock_section["value"], ending),
        "etfs": percent(etf_section["value"], ending),
    }
    assert round(sum(float(v) for v in pcts.values()), 2) == 100.00, pcts
    unrealized = stock_section["gain"] + etf_section["gain"]
    unrealized_lt = unrealized - UNREALIZED_ST["st_gain"] - UNREALIZED_ST["st_loss"]
    year_net = YEAR_CREDITS + YEAR_DEBITS
    year_tira = YEAR_PURCHASES + YEAR_SALES + sum(YEAR_INCOME.values())
    # January's opening cash: what this year's flows leave at the close.
    year_opening = cash - year_tira - year_net
    assert year_opening > 0
    return {
        "stocks": stocks, "options": options, "etfs": etfs, "common": common, "opts": opts,
        "stock_section": stock_section, "etf_section": etf_section, "cash": cash, "net": net,
        "ending": ending, "beginning": beginning, "credits": credits, "debits": debits,
        "purchases": purchases, "sales": sales, "income": income, "pcts": pcts,
        "unrealized": unrealized, "unrealized_lt": unrealized_lt, "year_net": year_net,
        "year_tira": year_tira, "year_opening": year_opening,
        "income_period": {
            "Qualified Dividends": sum(r[7] for r in CASH_ROWS if r[2] == "Qualified Dividend"),
            "Other Dividends": sum(r[7] for r in CASH_ROWS if r[2] == "Dividend"),
            "Interest": sum(r[7] for r in CASH_ROWS if r[10] == "interest"),
        },
    }


# --- drawing -------------------------------------------------------------------

class Statement:
    """Lines of cells on landscape pages. A cell is (x, text) drawn from x,
    or (x, text, "r") ending at x. Cells of a line share one baseline, so
    the PDF's text reads back one line per row."""

    def __init__(self, path: Path) -> None:
        self.c = canvas.Canvas(str(path), pagesize=landscape(letter), invariant=1)
        self.c.setTitle("Synthetic E*TRADE Client Statement")
        self.c.setAuthor("OrbySystems parser test fixture")
        self.y = 0.0
        self.page = 0

    def line(self, *cells, bold: bool = False, size: float = 8, step: float = 13) -> None:
        font = "Helvetica-Bold" if bold else "Helvetica"
        spans = []
        for cell in cells:
            x, text = cell[0], cell[1]
            width = stringWidth(text, font, size)
            left = x - width if len(cell) > 2 else x
            spans.append((left, left + width, text))
        spans.sort()
        for (_, end, text), (start, _, nxt) in zip(spans, spans[1:]):
            assert start - end >= 5, f"cells overlap on page {self.page}: {text!r} / {nxt!r}"
        self.c.setFont(font, size)
        for left, _, text in spans:
            self.c.drawString(left, self.y, text)
        self.y -= step

    def gap(self, points: float = 8) -> None:
        self.y -= points

    def new_page(self, banner: str | None = None) -> None:
        if self.page:
            self.c.setFont("Helvetica-Bold", 7)
            self.c.drawString(36, 22, "SYNTHETIC TEST DATA - NOT AN OFFICIAL STATEMENT")
            self.c.showPage()
        self.page += 1
        self.y = PAGE_H - 36
        if self.page == 1:
            self.line((36, "CLIENT STATEMENT"), (150, f"For the Period {PERIOD}"), bold=True, size=10, step=24)
            return
        self.line((36, "CLIENT STATEMENT"), (150, f"For the Period {PERIOD}"),
                  (PAGE_W - 36, f"Page {self.page} of {PAGES}", "r"))
        if banner:
            self.line((36, TITLE), (PAGE_W - 36, HOLDER, "r"))
            self.line((36, f"Account {banner} {ACCOUNT_ID}"), (PAGE_W - 36, HOLDER, "r"), step=22)
        else:
            self.gap(10)

    def save(self) -> None:
        self.c.setFont("Helvetica-Bold", 7)
        self.c.drawString(36, 22, "SYNTHETIC TEST DATA - NOT AN OFFICIAL STATEMENT")
        self.c.save()


# Column right edges.
SUMMARY_COLS = (300, 400)            # This Period, This Year
LEFT_COLS = (250, 330)               # balance sheet: Last Period, This Period
RIGHT_COLS = (650, 740)              # cash flow / income: This Period, This Year
GAIN_COLS = (590, 665, 745)          # realized period, realized year, unrealized
HOLDING_COLS = (330, 395, 470, 545, 620, 690, 745)  # qty, price, cost, value, gain, income, yield
SUBTOTAL_COLS = (330, 470, 545, 620, 690, 745)      # pct, cost, value, gain, income, yield
OPTION_COLS = (420, 480, 560, 640, 720)             # contracts, price, cost, value, gain
ACTIVITY = {"settle": 62, "type": 96, "desc": 180, "comments": 345, "qty": 520, "price": 590, "amount": 705,
            "sweep": 610}


def _cover(s: Statement, f: dict) -> None:
    s.new_page()
    s.line((38, "STATEMENT FOR:"), (430, "Beginning Total Value (as of 7/1/26)"),
           (735, money(f["beginning"], True), "r"), bold=True, size=9, step=16)
    s.line((46, HOLDER), (430, "Ending Total Value (as of 7/31/26)"),
           (735, money(f["ending"], True), "r"), bold=True, size=9, step=16)
    s.line((46, "100 EXAMPLE AVENUE"))
    s.line((46, "SPRINGFIELD ZZ 00000"))
    s.gap(140)
    s.line((38, "Morgan Stanley Smith Barney LLC. Member SIPC."))
    s.line((38, "E*TRADE is a business of Morgan Stanley."))


def _disclosures(s: Statement) -> None:
    s.new_page()
    s.line((38, "Standard Disclosures"), bold=True, size=10, step=18)
    for text in (
        "This synthetic page stands where a statement prints its standard disclosures.",
        "Its sentences are invented for a parser test and describe no real account or policy.",
        "Questions about a real account belong with the firm that holds it.",
    ):
        s.line((38, text))


def _change_in_value(s: Statement, f: dict) -> None:
    s.new_page("Summary")
    s.line((38, "CHANGE IN VALUE OF YOUR ACCOUNT (includes accrued interest)"), bold=True, size=9, step=16)
    s.line((SUMMARY_COLS[0], "This Period", "r"), (SUMMARY_COLS[1], "This Year", "r"))
    s.line((SUMMARY_COLS[0], "(7/1/26-7/31/26)", "r"), (SUMMARY_COLS[1], "(1/1/26-7/31/26)", "r"))
    year_change = f["ending"] - YEAR_BEGINNING - f["year_net"]
    rows = [
        ("TOTAL BEGINNING VALUE", f["beginning"], YEAR_BEGINNING, True),
        ("Credits", f["credits"], YEAR_CREDITS, False),
        ("Debits", f["debits"], YEAR_DEBITS, False),
        ("Security Transfers", 0, 0, False),
        ("Net Credits/Debits/Transfers", f["credits"] + f["debits"], f["year_net"], True),
        ("Change in Value", f["ending"] - f["beginning"] - f["credits"] - f["debits"], year_change, False),
        ("TOTAL ENDING VALUE", f["ending"], f["ending"], True),
    ]
    for label, period, year, dollar in rows:
        s.line((38, label), (SUMMARY_COLS[0], money(period, dollar), "r"), (SUMMARY_COLS[1], money(year, dollar), "r"))
    s.gap(12)
    s.line((38, "ASSET ALLOCATION (includes accrued interest)"), bold=True, size=9, step=16)
    s.line((SUMMARY_COLS[0], "Market Value", "r"), (SUMMARY_COLS[1], "Percentage", "r"))
    equities = f["stock_section"]["value"] + f["etf_section"]["value"]
    s.line((38, "Cash"), (SUMMARY_COLS[0], money(f["cash"], True), "r"),
           (SUMMARY_COLS[1], f["pcts"]["cash"], "r"))
    s.line((38, "Equities"), (SUMMARY_COLS[0], money(equities), "r"),
           (SUMMARY_COLS[1], f"{100 - float(f['pcts']['cash']):.2f}", "r"))
    s.line((38, "TOTAL VALUE"), (SUMMARY_COLS[0], money(f["ending"], True), "r"),
           (SUMMARY_COLS[1], "100.00%", "r"))


def _balance_sheet_and_cash_flow(s: Statement, f: dict) -> None:
    s.new_page("Summary")
    s.line((38, "BALANCE SHEET (^ includes accrued interest)"), (430, "CASH FLOW"), bold=True, size=9, step=16)
    s.line((LEFT_COLS[0], "Last Period", "r"), (LEFT_COLS[1], "This Period", "r"),
           (RIGHT_COLS[0], "This Period", "r"), (RIGHT_COLS[1], "This Year", "r"))
    s.line((LEFT_COLS[0], "(as of 6/30/26)", "r"), (LEFT_COLS[1], "(as of 7/31/26)", "r"),
           (RIGHT_COLS[0], "(7/1/26-7/31/26)", "r"), (RIGHT_COLS[1], "(1/1/26-7/31/26)", "r"))
    tira = f["purchases"] + f["sales"] + f["income"]
    left = [
        ("Cash, BDP, MMFs", OPENING_CASH, f["cash"], True),
        ("Stocks", LAST_STOCKS, f["stock_section"]["value"], False),
        ("ETFs & CEFs", LAST_ETFS, f["etf_section"]["value"], False),
        ("Total Assets", f["beginning"], f["ending"], True),
        ("Cash, BDP, MMFs (Debit)", 0, 0, False),
        ("Total Liabilities (outstanding balance)", 0, 0, False),
        ("TOTAL VALUE", f["beginning"], f["ending"], True),
    ]
    right = [
        ("OPENING CASH, BDP, MMFs", OPENING_CASH, f["year_opening"], True),
        ("Purchases", f["purchases"], YEAR_PURCHASES, False),
        ("Sales and Redemptions", f["sales"], YEAR_SALES, False),
        ("Income and Distributions", f["income"], sum(YEAR_INCOME.values()), False),
        ("Total Investment Related Activity", tira, f["year_tira"], True),
        ("Electronic Transfers-Credits", f["credits"], YEAR_CREDITS, False),
        ("Electronic Transfers-Debits", f["debits"], YEAR_DEBITS, False),
        ("Total Cash Related Activity", f["credits"] + f["debits"], f["year_net"], True),
        ("Total Card/Check Activity", 0, 0, False),
        ("CLOSING CASH, BDP, MMFs", f["cash"], f["cash"], True),
    ]
    for index in range(max(len(left), len(right))):
        cells = []
        if index < len(left):
            label, last, this, dollar = left[index]
            cells += [(38, label), (LEFT_COLS[0], money(last, dollar), "r"), (LEFT_COLS[1], money(this, dollar), "r")]
        label, period, year, dollar = right[index]
        cells += [(430, label), (RIGHT_COLS[0], money(period, dollar), "r"), (RIGHT_COLS[1], money(year, dollar), "r")]
        s.line(*cells)
    s.gap(12)

    s.line((38, "INCOME AND DISTRIBUTION SUMMARY"), (430, "GAIN/(LOSS) SUMMARY"), bold=True, size=9, step=16)
    s.line((LEFT_COLS[0], "This Period", "r"), (LEFT_COLS[1], "This Year", "r"),
           (GAIN_COLS[0], "Realized", "r"), (GAIN_COLS[1], "Realized", "r"), (GAIN_COLS[2], "Unrealized", "r"))
    s.line((GAIN_COLS[0], "This Period", "r"), (GAIN_COLS[1], "This Year", "r"),
           (GAIN_COLS[2], "(as of 7/31/26)", "r"))
    period_income = f["income_period"]
    income_total = sum(period_income.values())
    year_income_total = sum(YEAR_INCOME.values())
    rp, ry, us = REALIZED_PERIOD, REALIZED_YEAR, UNREALIZED_ST
    income_lines = [
        ("Qualified Dividends", period_income["Qualified Dividends"], YEAR_INCOME["Qualified Dividends"], False),
        ("Other Dividends", period_income["Other Dividends"], YEAR_INCOME["Other Dividends"], False),
        ("Interest", period_income["Interest"], YEAR_INCOME["Interest"], False),
        ("Income And Distributions", income_total, year_income_total, True),
        ("Tax-Exempt Income", 0, 0, False),
    ]
    gain_lines = [
        ("Short-Term Gain", rp["st_gain"], ry["st_gain"], us["st_gain"], True),
        ("Short-Term (Loss)", rp["st_loss"], ry["st_loss"], us["st_loss"], False),
        ("Total Short-Term", rp["st_gain"] + rp["st_loss"], ry["st_gain"] + ry["st_loss"],
         us["st_gain"] + us["st_loss"], True),
        ("Long-Term Gain", rp["lt_gain"], ry["lt_gain"], f["unrealized_lt"], False),
    ]
    for (label, period, year, dollar), gain in zip(income_lines, gain_lines + [None]):
        cells = [(38, label), (LEFT_COLS[0], money(period, dollar), "r"), (LEFT_COLS[1], money(year, dollar), "r")]
        if gain:
            g_label, g_period, g_year, g_unrealized, g_dollar = gain
            cells += [(430, g_label), (GAIN_COLS[0], money(g_period, g_dollar), "r"),
                      (GAIN_COLS[1], money(g_year, g_dollar), "r"), (GAIN_COLS[2], money(g_unrealized, g_dollar), "r")]
        s.line(*cells)
    realized_period = rp["st_gain"] + rp["st_loss"] + rp["lt_gain"]
    realized_year = ry["st_gain"] + ry["st_loss"] + ry["lt_gain"]
    s.line((38, "TOTAL INCOME AND DISTRIBUTIONS"), (LEFT_COLS[0], money(income_total, True), "r"),
           (LEFT_COLS[1], money(year_income_total, True), "r"),
           (430, "TOTAL GAIN/(LOSS)"), (GAIN_COLS[0], money(realized_period, True), "r"),
           (GAIN_COLS[1], money(realized_year, True), "r"), (GAIN_COLS[2], money(f["unrealized"], True), "r"),
           bold=True)


def _holding_row(s: Statement, row: dict, first: bool) -> None:
    cols = HOLDING_COLS
    s.line((38, f"{row['name']} ({row['ticker']})"), (cols[0], row["qty"], "r"),
           (cols[1], ("$" if first else "") + row["price"], "r"), (cols[2], money(row["cost"], first), "r"),
           (cols[3], money(row["value"], first), "r"), (cols[4], money(row["gain"], first), "r"),
           (cols[5], money(row["income"], first), "r"),
           (cols[6], percent(row["income"], row["value"]) if row["income"] else "—", "r"))
    s.line((46, row["note"]))


def _subtotal(s: Statement, label: str, pct: str | None, section: dict, yield_pct: str) -> None:
    cols = SUBTOTAL_COLS
    cells = [(38, label)]
    if pct is not None:
        cells.append((cols[0], f"{pct}%", "r"))
    cells += [(cols[1], money(section["cost"], True), "r"), (cols[2], money(section["value"], True), "r"),
              (cols[3], money(section["gain"], True), "r"), (cols[4], money(section["income"], True), "r"),
              (cols[5], yield_pct, "r")]
    s.line(*cells, bold=True)


def _holding_headers(s: Statement) -> None:
    s.line((HOLDING_COLS[4], "Unrealized", "r"), (HOLDING_COLS[6], "Current", "r"))
    s.line((38, "Security Description"), (HOLDING_COLS[0], "Quantity", "r"), (HOLDING_COLS[1], "Share Price", "r"),
           (HOLDING_COLS[2], "Total Cost", "r"), (HOLDING_COLS[3], "Market Value", "r"),
           (HOLDING_COLS[4], "Gain/(Loss)", "r"), (HOLDING_COLS[5], "Est Ann Income", "r"),
           (HOLDING_COLS[6], "Yield %", "r"))


def _subtotal_headers(s: Statement, accrued: bool = False) -> None:
    s.line((SUBTOTAL_COLS[0], "Percentage", "r"), (SUBTOTAL_COLS[3], "Unrealized", "r"),
           *([(SUBTOTAL_COLS[4], "Est Ann Income", "r")] if accrued else []), (SUBTOTAL_COLS[5], "Current", "r"))
    s.line((SUBTOTAL_COLS[0], "of Holdings", "r"), (SUBTOTAL_COLS[1], "Total Cost", "r"),
           (SUBTOTAL_COLS[2], "Market Value", "r"), (SUBTOTAL_COLS[3], "Gain/(Loss)", "r"),
           (SUBTOTAL_COLS[4], "Accrued Interest" if accrued else "Est Ann Income", "r"),
           (SUBTOTAL_COLS[5], "Yield %", "r"))


def _yield(section: dict) -> str:
    return f"{percent(section['income'], section['value'])}%"


def _holdings_cash_and_stocks(s: Statement, f: dict) -> None:
    s.new_page("Detail")
    s.line((38, "Investment Objectives (in order of priority): Growth"),
           (PAGE_W - 38, "Brokerage Account", "r"))
    s.line((38, "HOLDINGS"), bold=True, size=11, step=16)
    s.line((38, "Positions are shown as of the trade date of each purchase or sale."))
    s.gap(4)
    s.line((38, "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS"), bold=True, size=9, step=15)
    s.line((470, "7-Day", "r"))
    s.line((38, "Description"), (330, "Market Value", "r"), (400, "Current Yield %", "r"),
           (470, "Est Ann Income", "r"), (530, "APY %", "r"))
    s.line((38, BANK), (330, money(f["cash"], True), "r"), (400, "—", "r"),
           (470, money(CASH_INCOME, True), "r"), (530, "0.050", "r"))
    s.line((250, "Percentage", "r"))
    s.line((250, "of Holdings", "r"), (330, "Market Value", "r"), (470, "Est Ann Income", "r"))
    s.line((38, "CASH, BDP, AND MMFs"), (250, f"{f['pcts']['cash']}%", "r"), (330, money(f["cash"], True), "r"),
           (470, money(CASH_INCOME, True), "r"), bold=True)
    s.gap(4)
    s.line((38, "STOCKS"), bold=True, size=9, step=15)
    s.line((38, "COMMON STOCKS"), bold=True)
    _holding_headers(s)
    for index, row in enumerate(f["stocks"]):
        _holding_row(s, row, index == 0)
    _subtotal(s, "COMMON STOCKS", None, f["common"], _yield(f["common"]))
    s.gap(4)
    s.line((38, "OPTIONS (Contract prices are shown to three decimal places)"), bold=True)
    s.line((OPTION_COLS[0], "Number of", "r"), (OPTION_COLS[4], "Unrealized", "r"))
    s.line((38, "Security Description"), (OPTION_COLS[0], "Contracts", "r"), (OPTION_COLS[1], "Contract Price", "r"),
           (OPTION_COLS[2], "Total Cost", "r"), (OPTION_COLS[3], "Market Value", "r"),
           (OPTION_COLS[4], "Gain/(Loss)", "r"))
    for index, row in enumerate(f["options"]):
        first = index == 0
        s.line((38, f"CALL {row['name']} AT {row['strike']} EXPIRES {row['expiry']}"),
               (OPTION_COLS[0], f"({row['contracts']:.3f})", "r"),
               (OPTION_COLS[1], ("$" if first else "") + row["price"], "r"),
               (OPTION_COLS[2], money(row["cost"], first), "r"), (OPTION_COLS[3], money(row["value"], first), "r"),
               (OPTION_COLS[4], money(row["gain"], first), "r"))
        s.line((46, f"({row['root']} {row['osi']})"))
        s.line((46, "Short Position; Asset Class: Equities"))
    s.line((38, "OPTIONS"), (OPTION_COLS[2], money(f["opts"]["cost"], True), "r"),
           (OPTION_COLS[3], money(f["opts"]["value"], True), "r"),
           (OPTION_COLS[4], money(f["opts"]["gain"], True), "r"), bold=True)
    s.gap(4)
    _subtotal_headers(s)
    _subtotal(s, "STOCKS", f["pcts"]["stocks"], f["stock_section"], _yield(f["stock_section"]))
    s.line((38, "Total Stocks (Long)"), (SUBTOTAL_COLS[2], money(f["common"]["value"], True), "r"))
    s.line((38, "Total Stocks (Short)"), (SUBTOTAL_COLS[2], money(f["opts"]["value"], True), "r"))


def _holdings_funds_and_total(s: Statement, f: dict) -> None:
    s.new_page("Detail")
    s.line((38, "EXCHANGE-TRADED & CLOSED-END FUNDS"), bold=True, size=9, step=15)
    _holding_headers(s)
    for index, row in enumerate(f["etfs"]):
        _holding_row(s, row, index == 0)
    _subtotal_headers(s)
    _subtotal(s, "EXCHANGE-TRADED & CLOSED-END FUNDS", f["pcts"]["etfs"], f["etf_section"], _yield(f["etf_section"]))
    s.gap(6)
    total = {
        "cost": f["stock_section"]["cost"] + f["etf_section"]["cost"],
        "value": f["ending"],
        "gain": f["unrealized"],
        "income": CASH_INCOME + f["stock_section"]["income"] + f["etf_section"]["income"],
    }
    _subtotal_headers(s, accrued=True)
    _subtotal(s, "TOTAL VALUE", "100.00", total, _yield(total))
    s.line((SUBTOTAL_COLS[4], "—", "r"))
    s.gap(10)
    s.line((38, "ALLOCATION OF ASSETS"), bold=True, size=9, step=15)
    cols = (290, 380, 470, 550, 640, 720)
    s.line((470, "Fixed Income &", "r"), (640, "Structured", "r"))
    s.line((cols[0], "Cash", "r"), (cols[1], "Equities", "r"), (cols[2], "Preferred Securities", "r"),
           (cols[3], "Alternatives", "r"), (cols[4], "Investments", "r"), (cols[5], "Other", "r"))
    equities = f["stock_section"]["value"] + f["etf_section"]["value"]
    for label, cash, equity, dollar in (
        ("Cash, BDP, MMFs", f["cash"], 0, True),
        ("Stocks", 0, f["stock_section"]["value"], True),
        ("ETFs & CEFs", 0, f["etf_section"]["value"], False),
        ("TOTAL ALLOCATION OF ASSETS", f["cash"], equities, True),
    ):
        s.line((38, label), (cols[0], money(cash, dollar), "r"), (cols[1], money(equity, dollar), "r"),
               *[(x, "—", "r") for x in cols[2:]], bold=label.startswith("TOTAL"))


def _activity(s: Statement, f: dict) -> None:
    s.new_page("Detail")
    s.line((38, "ACTIVITY"), bold=True, size=11, step=16)
    s.line((38, "CASH FLOW ACTIVITY BY DATE"), bold=True, size=9, step=15)
    a = ACTIVITY
    s.line((38, "Activity"), (a["settle"] + 10, "Settlement"))
    s.line((38, "Date"), (a["settle"] + 6, "Date"), (a["type"], "Activity Type"), (a["desc"], "Description"),
           (a["comments"], "Comments"), (a["qty"], "Quantity", "r"), (a["price"], "Price", "r"),
           (a["amount"], "Credits/(Debits)", "r"))
    first_price = next(index for index, row in enumerate(CASH_ROWS) if row[6])
    for index, row in enumerate(CASH_ROWS):
        trade, settle, activity, desc, comments, qty, price, amount, cont = row[:9]
        first = index == 0
        cells = [(38, trade), (a["type"], activity), (a["desc"], desc), (a["amount"], money(amount, first), "r")]
        if settle:
            cells.append((a["settle"], settle))
        if comments:
            cells.append((a["comments"], comments))
        if qty:
            cells += [(a["qty"], qty, "r"), (a["price"], ("$" if index == first_price else "") + price, "r")]
        s.line(*cells)
        if cont:
            s.line((a["comments"], cont))
    s.line((38, "NET CREDITS/(DEBITS)"), (a["amount"], money(f["net"], True), "r"), bold=True)
    s.line((38, "Purchase and sale prices above may be averaged across several executions."), size=7)
    s.gap(6)
    s.line((38, "MONEY MARKET FUND (MMF) AND BANK DEPOSIT PROGRAM ACTIVITY"), bold=True, size=9, step=15)
    s.line((38, "Activity"))
    # Its own Credits/(Debits) column, narrower than the table above: the
    # Scrambler matches a total to a run of its column, and these rows add
    # up to NET CREDITS/(DEBITS) too.
    s.line((38, "Date"), (a["type"], "Activity Type"), (a["desc"] + 40, "Description"),
           (a["sweep"], "Credits/(Debits)", "r"))
    for index, (when, activity, amount) in enumerate(SWEEP_ROWS):
        s.line((38, when), (a["type"], activity), (a["desc"] + 40, "BANK DEPOSIT PROGRAM"),
               (a["sweep"], money(amount, index == 0), "r"))
    s.line((38, "NET ACTIVITY FOR PERIOD"), (a["sweep"], money(f["net"], True), "r"), bold=True)
    s.gap(6)
    s.line((38, "TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY"), bold=True, size=9, step=15)
    s.line((38, "OPTIONS EXPIRATIONS, EXERCISES AND ASSIGNMENTS"), bold=True)
    s.line((38, "Activity"))
    s.line((38, "Date"), (a["type"], "Activity Type"), (a["desc"], "Description"), (a["comments"], "Comments"),
           (a["qty"], "Contracts", "r"))
    when, activity, desc, comments, contracts, _ = EXPIRED
    s.line((38, when), (a["type"], activity), (a["desc"], desc), (a["comments"], comments), (a["qty"], contracts, "r"))
    s.gap(10)
    s.line((38, "MESSAGES"), bold=True, size=9, step=15)
    s.line((38, "This synthetic message closes the account's pages; it carries no figures."))


def build() -> None:
    f = figures()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    s = Statement(OUT)
    _cover(s, f)
    _disclosures(s)
    _change_in_value(s, f)
    _balance_sheet_and_cash_flow(s, f)
    _holdings_cash_and_stocks(s, f)
    _holdings_funds_and_total(s, f)
    _activity(s, f)
    assert s.page == PAGES
    s.save()

    def dollars(cents: int) -> float:
        return round(cents / 100, 2)

    holdings = [{"symbol": "CASH", "type": "Cash", "current_value": dollars(f["cash"])}]
    for row in f["stocks"]:
        holdings.append({"symbol": row["ticker"], "type": "Stock", "quantity": float(row["qty"]),
                         "current_value": dollars(row["value"]), "cost_basis_total": dollars(row["cost"])})
    for row in f["options"]:
        strike = row["strike"].rstrip("0").rstrip(".")
        expiry = row["expiry"]
        symbol = f"{row['root']}{expiry[8:10]}{expiry[0:2]}{expiry[3:5]}C{strike}"
        holdings.append({"symbol": symbol, "type": "Options", "quantity": -float(row["contracts"]),
                         "current_value": dollars(row["value"]), "cost_basis_total": dollars(row["cost"])})
    for row in f["etfs"]:
        holdings.append({"symbol": row["ticker"], "type": "ETF", "quantity": float(row["qty"]),
                         "current_value": dollars(row["value"]), "cost_basis_total": dollars(row["cost"])})

    def iso(month_day: str) -> str:
        month, day = month_day.split("/")
        return f"2026-{int(month):02d}-{int(day):02d}"

    transactions = []
    for trade, _, activity, *_, amount, _, symbol, ttype, quantity in CASH_ROWS:
        row = {"date": iso(trade), "action": activity, "transaction_type": ttype, "symbol": symbol,
               "amount": dollars(amount)}
        if quantity is not None:
            row["quantity"] = quantity
        transactions.append(row)
    when, activity, _, _, contracts, symbol = EXPIRED
    transactions.append({"date": iso(when), "action": activity, "transaction_type": "corporate_action",
                         "subtype": "Out", "symbol": symbol, "quantity": float(contracts), "amount": 0.0})

    EXPECT.write_text(
        json.dumps(
            {
                "file": OUT.name,
                "institution": "E*TRADE from Morgan Stanley",
                "statementDate": STATEMENT_DATE,
                "account": "".join(ch for ch in ACCOUNT_ID if ch.isdigit())[-4:],
                "accountType": "Brokerage",
                "providerAccountId": ACCOUNT_ID,
                "endingValue": dollars(f["ending"]),
                "holdings": holdings,
                "transactions": transactions,
                "checks": [
                    {"kind": "sum", "label": "Credits/Debits", "expected": dollars(f["credits"] + f["debits"])},
                    {"kind": "sum", "label": "CASH FLOW ACTIVITY BY DATE", "expected": dollars(f["net"])},
                    {"kind": "unread", "label": "CASH FLOW ACTIVITY BY DATE"},
                    {"kind": "unread", "label": "TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build()
