#!/usr/bin/env python3
"""Generates the bundled example household: six brokerage statements and
two credit-card statements for a household that does not exist.

WHY THIS EXISTS. Someone evaluating OrbySystems who will not go and find their
own statement is a normal person, not a lost cause - but a demo that
loads rows straight into the database skips the parse, and the parse is
both the step users doubt and the step that convinces them. So these are
real PDFs the user ingests, and they see the parser recognise an
institution, extract positions, and produce the same answers their own
statements would.

WHOLLY INVENTED, AND DELIBERATELY NOT ANY REAL INSTITUTION. Vantage
Brokerage and Meridian Card do not exist; the names come from the
benchmark dataset, which invented them for the same reason. Generating a
fabricated household's records in a REAL custodian's format would be a
bad thing to ship, however synthetic the numbers - so this format is its
own, and `vantage_brokerage.py` / `meridian_card.py` parse it.

BUILT SO THE LESSONS LAND. The numbers are not arbitrary. The household
sits just under an IRMAA tier, holds one position at ~30% of its taxable
account with a large embedded gain, and has its bonds in exactly the
wrong places. Each is checked by assertions at the bottom of this file
rather than left to drift, because a demo whose teaching examples stop
being true is worse than no demo - it teaches the wrong thing
confidently.

Regenerate with:  python3 tests/generators/gen-demo-household.py
"""

import json
import os
import random
from datetime import date

# Page geometry, matching the other generators.
PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 7
LINE_H = 10
X = 24

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "demo")

# --- the household -----------------------------------------------------
#
# Married filing jointly, both born 1963, so both reach 65 in 2028 - which
# is what makes the IRMAA lookback bite: 2026 income sets 2028 premiums.
# Prior-year taxable income 180,000.
#
#   MAGI = taxable income + the standard deduction = 180,000 + 32,200
#        = 212,200, against a 2026 married-joint IRMAA tier 1 of 218,000.
#   Headroom: 5,800. The 24% bracket is 31,400 away and NIIT 37,800 away,
#   so the NEAREST line is a cliff rather than a slope - which is the
#   single most useful thing this product teaches.
# Read from demo/household.json rather than restated here: OrbySystems seeds the
# project's profile from that same file, and two copies of a household's
# income would drift silently - the statements would still look plausible
# while the headroom the onboarding copy quotes stopped being true.
with open(os.path.join(OUT, "household.json"), encoding="utf-8") as _f:
    HOUSEHOLD = json.load(_f)

PRIOR_YEAR_TAXABLE_INCOME = HOUSEHOLD["prior_year_taxable_income"]
STD_DEDUCTION_MFJ_2026 = HOUSEHOLD["_derived"]["standard_deduction_mfj_2026"]
IRMAA_TIER1_MFJ_2026 = HOUSEHOLD["_derived"]["irmaa_tier1_mfj_2026"]
EXPECTED_HEADROOM = HOUSEHOLD["_derived"]["expected_irmaa_headroom"]

INSTITUTION = "Vantage Brokerage"

# symbol, name, asset kind, annual income yield used for est. income
SECURITIES = {
    "NVDA": ("NVIDIA CORP", "equity", 0.0002),
    "VTI":  ("VANGUARD TOTAL STOCK MARKET ETF", "equity", 0.0121),
    "SCHD": ("SCHWAB US DIVIDEND EQUITY ETF", "equity", 0.0372),
    "BND":  ("VANGUARD TOTAL BOND MARKET ETF", "bond", 0.0384),
    "SGOV": ("ISHARES 0-3 MONTH TREASURY BOND ETF", "bond", 0.0498),
}

PRICES = {"NVDA": 191.50, "VTI": 302.10, "SCHD": 27.35, "BND": 73.40, "SGOV": 100.45}

# account number, type as the statement prints it, holdings as
# symbol -> (quantity, cost basis total)
ACCOUNTS = [
    ("2041", "Individual", {
        # The concentrated position: ~30% of this account, bought at 33.
        # A study-sized problem, which is the product we sell first.
        "NVDA": (1950.0, 64_350.00),
        # Bonds in the TAXABLE account, throwing off ordinary income that
        # is taxed every year at the household's marginal rate. Half of
        # the asset-location mistake.
        "BND":  (4200.0, 315_000.00),
        "VTI":  (1150.0, 213_900.00),
        "SCHD": (4800.0, 118_000.00),
    }),
    ("6683", "Roth IRA", {
        # And the other half: the account that would never be taxed on
        # anything is holding the lowest-growth assets in the portfolio.
        "BND":  (2400.0, 170_000.00),
        "SGOV": (920.0, 92_000.00),
    }),
    # The pre-tax 401(k) the household still pays into from every paycheck:
    # its monthly purchases are funded by contributions, not by the bank.
    ("3390", "401(k)", {
        "VTI":  (900.0, 180_000.00),
        "SCHD": (3200.0, 79_000.00),
    }),
]

# Accounts funded from payroll rather than from the bank: what their
# purchases need arrives as the employee's pre-tax deferral and the
# employer's match, on payday.
PAYROLL_FUNDED = {"3390"}
EMPLOYEE_SHARE = 0.75

MONTHS = [
    (date(2025, 10, 1), date(2025, 10, 31)),
    (date(2025, 11, 1), date(2025, 11, 30)),
    (date(2025, 12, 1), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 1, 31)),
    (date(2026, 2, 1), date(2026, 2, 28)),
    (date(2026, 3, 1), date(2026, 3, 31)),
]

# Each month's price as a fraction of the final price, so the series has a
# real shape (a dip in December, a strong March) rather than a straight
# line - a portfolio that only ever goes up teaches nothing about return.
# Together with the dividends it is about 8.5% a year, money-weighted: the
# return check() asserts, and the one a planner would start from.
PRICE_PATH = [0.9775, 0.9830, 0.9718, 0.9855, 0.9912, 1.0000]


def money(x: float) -> str:
    return f"{x:,.2f}"


def qty(x: float) -> str:
    return f"{x:,.3f}"


# --- activity ----------------------------------------------------------
#
# A monthly purchase plan per account. Quantities are walked BACKWARDS from
# the final holdings above, so the two halves of every statement agree:
# what the account held at the end of March, minus what it bought since,
# is what it held in October. Inventing the snapshots independently is how
# a demo ends up with a portfolio whose history does not add up.
#
# NVDA is deliberately absent: the concentrated position was bought years
# before this window and is not being added to, which is exactly the
# situation that makes it a problem nobody has dealt with.
MONTHLY_BUYS = {
    "2041": {"VTI": 9.0, "SCHD": 42.0},
    "6683": {"BND": 18.0, "SGOV": 6.0},
    "3390": {"VTI": 7.0, "SCHD": 30.0},
}

# Dividends land in the month after each quarter end, which is when funds
# actually distribute.
DIVIDEND_MONTHS = {2, 5}  # index into MONTHS: December and March


def price_at(symbol: str, i: int) -> float:
    return round(PRICES[symbol] * PRICE_PATH[i], 2)


def quantities_at(acct: str, holdings: dict, i: int) -> dict:
    """Shares held at the END of month i, walked back from the final."""
    out = {}
    months_after = len(MONTHS) - 1 - i
    for sym, (final_qty, _basis) in holdings.items():
        bought_per_month = MONTHLY_BUYS.get(acct, {}).get(sym, 0.0)
        out[sym] = round(final_qty - bought_per_month * months_after, 3)
    return out


def basis_at(acct: str, holdings: dict, i: int) -> dict:
    """Cost basis at the end of month i, reduced by what later purchases
    added - so basis and quantity move together and the unrealised gain
    is consistent in every statement."""
    out = {}
    months_after = len(MONTHS) - 1 - i
    for sym, (_final_qty, final_basis) in holdings.items():
        per_month = MONTHLY_BUYS.get(acct, {}).get(sym, 0.0)
        spent_after = 0.0
        for j in range(i + 1, len(MONTHS)):
            spent_after += per_month * price_at(sym, j)
        out[sym] = round(final_basis - spent_after, 2)
    return out


def activity_for(acct: str, holdings: dict, i: int):
    """Returns (rows, deposit) for month i.

    Deposits fund purchases NET OF DIVIDENDS, never gross. A dividend is
    investment return, and a purchase made with one is income being
    reinvested rather than money paid in - funding those too would make
    every growth figure understate the return by exactly what the
    portfolio earned. The benchmark dataset had this wrong for months.
    """
    start, end = MONTHS[i]
    rows = []
    spent = 0.0
    for sym, n in sorted(MONTHLY_BUYS.get(acct, {}).items()):
        px = price_at(sym, i)
        amount = round(-n * px, 2)
        spent += amount
        rows.append((end.replace(day=min(12, end.day)), "Buy", sym,
                     SECURITIES[sym][0], n, px, amount))

    income = 0.0
    if i in DIVIDEND_MONTHS:
        for sym, (_qty, _basis) in sorted(holdings.items()):
            held = quantities_at(acct, holdings, i)[sym]
            annual = SECURITIES[sym][2] * held * price_at(sym, i)
            div = round(annual / 4.0, 2)
            if div < 1.0:
                continue
            income += div
            rows.append((end.replace(day=min(22, end.day)), "Dividend", sym,
                         SECURITIES[sym][0], None, None, div))

    # What outside money has to cover - or, in a quarter where the
    # dividends more than pay for the month's purchases, what is swept
    # back out to the bank.
    #
    # The surplus has to go SOMEWHERE. Leaving it implicit would mean the
    # account received money that appears in no holding and in no
    # withdrawal, which is the same defect the benchmark dataset had:
    # value arriving from nowhere, and every growth figure quietly wrong
    # because of it. A household living partly off its dividends moving
    # the excess to its current account is also just what happens.
    need = round(-(spent + income), 2)
    flow = 0.0
    if need > 0.005 and acct in PAYROLL_FUNDED:
        flow = need
        employee = round(need * EMPLOYEE_SHARE, 2)
        payday = start.replace(day=min(15, end.day))
        rows.insert(0, (payday, "Contribution", "", "EMPLOYER MATCHING CONTRIBUTION",
                        None, None, round(need - employee, 2)))
        rows.insert(0, (payday, "Contribution", "", "EMPLOYEE PRE-TAX CONTRIBUTION",
                        None, None, employee))
    elif need > 0.005:
        flow = need
        rows.insert(0, (start.replace(day=min(3, end.day)), "Deposit", "",
                        "ACH DEPOSIT - TRANSFER FROM BANK", None, None, flow))
    elif need < -0.005:
        flow = need
        rows.append((end.replace(day=min(27, end.day)), "Withdrawal", "",
                     "ACH WITHDRAWAL - TRANSFER TO BANK", None, None, flow))
    rows.sort(key=lambda r: r[0])
    return rows, flow


# --- the statement layout ----------------------------------------------

def brokerage_lines(i: int) -> list:
    start, end = MONTHS[i]
    period = f"{start.strftime('%B %-d, %Y')} - {end.strftime('%B %-d, %Y')}"
    lines = [
        "VANTAGE BROKERAGE SERVICES",
        "Member FINRA/SIPC",
        "",
        f"Statement Period: {period}",
        "Prepared for: A. WHITFIELD & M. WHITFIELD",
        "",
    ]
    for acct, acct_type, holdings in ACCOUNTS:
        q = quantities_at(acct, holdings, i)
        b = basis_at(acct, holdings, i)
        total = sum(q[s] * price_at(s, i) for s in holdings)
        lines += [
            f"Account Number: VB-{acct}",
            f"Account Type: {acct_type}",
            "",
            "HOLDINGS",
            "Symbol   Description                              Quantity"
            "         Price    Market Value      Cost Basis   Est Annual Income",
        ]
        for sym in sorted(holdings):
            px = price_at(sym, i)
            value = round(q[sym] * px, 2)
            est = round(SECURITIES[sym][2] * value, 2)
            lines.append(
                f"{sym:<8} {SECURITIES[sym][0]:<40} {qty(q[sym]):>12} "
                f"{money(px):>10} {money(value):>15} {money(b[sym]):>15} {money(est):>19}"
            )
        lines += ["", f"Total Account Value {money(round(total, 2)):>60}", "", "ACTIVITY"]
        rows, _ = activity_for(acct, holdings, i)
        if not rows:
            lines.append("No activity this period.")
        else:
            lines.append(
                "Date         Type        Symbol   Description"
                "                                  Quantity      Price           Amount")
            for d, kind, sym, desc, n, px, amount in rows:
                lines.append(
                    f"{d.strftime('%m/%d/%Y')}   {kind:<11} {sym:<8} {desc:<40} "
                    f"{(qty(n) if n is not None else ''):>10} "
                    f"{(money(px) if px is not None else ''):>10} {money(amount):>16}"
                )
        lines += ["", "-" * 100, ""]
    return lines


# --- the credit card ---------------------------------------------------
#
# The everyday spending is ordinary and unremarkable on purpose: a grocer,
# fuel, the pharmacy, a cafe. Around it are the two things a household
# most often pays for without noticing, because finding them is the first
# thing the spending analyses are asked to do:
#
#   - subscriptions that overlap: five video services, two that both
#     include music, two gyms. Netflix's price rises in March, and
#     Paramount+ starts in March, when a free trial nobody cancelled runs
#     out;
#   - habits that add up: coffee most days, two delivery apps, fast food,
#     the corner store, short rides, a bar tab, many small online orders.
#
# Real merchant names, like the ticker symbols above, are public facts,
# and the categorizer's own rules place them, so every reader of the demo
# sees the same subscriptions and habits. The household, the card and
# every amount are invented. Each statement reconciles: the autopay pays
# the previous statement's balance.
CARD_ACCOUNT = "8814"
CARD_MONTHS = [(date(2026, 2, 1), date(2026, 2, 28)), (date(2026, 3, 1), date(2026, 3, 31))]
CARD_OPENING_BALANCE = 1284.55

CARD_EVERYDAY = [
    [("02/03", "WHOLE EARTH MARKET", 184.22), ("02/05", "NORTHSIDE FUEL", 61.40),
     ("02/07", "ALDERTON PHARMACY", 42.15), ("02/09", "THE COPPER KETTLE", 88.60),
     ("02/14", "WHOLE EARTH MARKET", 210.08), ("02/17", "CITY TRANSIT AUTHORITY", 96.00),
     ("02/19", "HARBOUR POINT DENTAL", 320.00), ("02/24", "WHOLE EARTH MARKET", 165.73),
     ("02/26", "NORTHSIDE FUEL", 58.90), ("02/27", "THE COPPER KETTLE", 74.25)],
    [("03/02", "WHOLE EARTH MARKET", 197.41), ("03/04", "NORTHSIDE FUEL", 63.75),
     ("03/08", "BRIGHTWATER UTILITIES", 212.44), ("03/13", "WHOLE EARTH MARKET", 178.65),
     ("03/15", "ALDERTON PHARMACY", 29.40), ("03/18", "CITY TRANSIT AUTHORITY", 96.00),
     ("03/20", "THE COPPER KETTLE", 102.10), ("03/23", "WHOLE EARTH MARKET", 221.37),
     ("03/25", "NORTHSIDE FUEL", 55.20), ("03/28", "GRANVILLE HARDWARE", 143.86)],
]

# Day of the month, description, price; a second price takes over from
# the month index given, and a first month delays the start.
CARD_SUBSCRIPTIONS = [
    (5, "PLANET FITNESS #88", 49.00),
    (9, "24 HOUR FITNESS CLUB #417", 54.99),
    (17, "NETFLIX.COM", 22.99),
    (17, "SPOTIFY USA", 16.99),
    (19, "HULU", 18.99),
    (20, "HBO MAX", 16.99),
    (21, "DISNEY+ SUBSCRIPTION", 15.99),
    (23, "YOUTUBE PREMIUM", 13.99),
    (24, "PARAMOUNT+ SUBSCRIPTION", 12.99),
    (26, "MICROSOFT 365 FAMILY", 12.99),
]
CARD_PRICE_RISES = {"NETFLIX.COM": (1, 24.99)}
CARD_STARTS = {"PARAMOUNT+ SUBSCRIPTION": 1}

# Merchant, visits a month, lowest and highest charge.
CARD_HABITS = [
    ("STARBUCKS #1204", 10, 5.50, 9.50),
    ("COSTA COFFEE #218", 5, 5.00, 16.00),
    ("DOORDASH", 3, 28.00, 75.00),
    ("UBER EATS", 3, 28.00, 58.00),
    ("CHIPOTLE 2650", 3, 13.00, 26.00),
    ("MCDONALD'S F21543", 3, 8.00, 17.00),
    ("7-ELEVEN #33104", 4, 6.00, 22.00),
    ("UBER TRIP", 2, 14.00, 45.00),
    ("LYFT RIDE", 2, 11.00, 32.00),
    ("ANCHOR BREWING CO", 2, 32.00, 85.00),
    ("AMAZON MKTPL", 5, 12.00, 110.00),
    ("STEAM GAMES", 2, 5.00, 25.00),
]

AUTOPAY = "MERIDIAN CARD AUTOPAY - THANK YOU"


def card_charges(i: int) -> list:
    """Month i's purchases, in the statement's own signs (charges positive)."""
    start, end = CARD_MONTHS[i]
    rows = list(CARD_EVERYDAY[i])
    for day, desc, price in CARD_SUBSCRIPTIONS:
        if CARD_STARTS.get(desc, 0) > i:
            continue
        rise = CARD_PRICE_RISES.get(desc)
        if rise and i >= rise[0]:
            price = rise[1]
        rows.append((f"{start.month:02d}/{min(day, end.day):02d}", desc, price))
    # A stream of its own per merchant and month, so changing one habit
    # leaves every other one's charges exactly as they were.
    for desc, visits, low, high in CARD_HABITS:
        rng = random.Random(f"{desc}|{start.isoformat()}")
        for _ in range(visits):
            day = rng.randint(1, end.day)
            amount = round(low + rng.random() * (high - low), 2)
            rows.append((f"{start.month:02d}/{day:02d}", desc, amount))
    return rows


def card_previous_balance(i: int) -> float:
    """The balance month i opens with. Each autopay clears the balance the
    month opened with, so what carries over is last month's charges."""
    if i == 0:
        return CARD_OPENING_BALANCE
    return round(sum(a for _, _, a in card_charges(i - 1)), 2)


def card_transactions(i: int) -> list:
    """Month i's rows as the statement prints them: the purchases and the
    autopay of the previous balance, in date order."""
    start, _end = CARD_MONTHS[i]
    autopay_day = 12 if i == 0 else 11
    rows = card_charges(i) + [(f"{start.month:02d}/{autopay_day:02d}", AUTOPAY, -card_previous_balance(i))]
    return sorted(rows, key=lambda r: (r[0], r[1]))


def card_lines(i: int) -> list:
    start, end = CARD_MONTHS[i]
    txns = card_transactions(i)
    purchases = round(sum(a for _, _, a in txns if a > 0), 2)
    credits = round(sum(a for _, _, a in txns if a < 0), 2)
    previous = card_previous_balance(i)
    new_balance = round(previous + purchases + credits, 2)
    lines = [
        "MERIDIAN CARD",
        "",
        f"Statement Closing Date: {end.strftime('%B %-d, %Y')}",
        f"Account Number: ****{CARD_ACCOUNT}",
        f"Billing Period: {start.strftime('%m/%d/%Y')} - {end.strftime('%m/%d/%Y')}",
        "",
        "ACCOUNT SUMMARY",
        f"Previous Balance {money(previous):>40}",
        f"Payments and Credits {money(credits):>36}",
        f"Purchases {money(purchases):>47}",
        f"New Balance {money(new_balance):>45}",
        "",
        "TRANSACTIONS",
        "Date     Description                                        Amount",
    ]
    for d, desc, amount in txns:
        lines.append(f"{d}    {desc:<48} {money(amount):>12}")
    return lines


# --- PDF output --------------------------------------------------------
#
# The same hand-rolled writer the other generators use. Copied rather than
# imported because these scripts are run standalone from anywhere, and a
# shared module would make each one depend on being run from the repo.

def escape(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1", "replace")


# Lines on one page: from 50pt below the top to about 30pt above the
# bottom, which keeps every brokerage statement on a single page.
LINES_PER_PAGE = 72


def build_pdf(lines, path):
    """One page per LINES_PER_PAGE lines. A document that fits on one page
    comes out byte for byte as it did before pages were supported."""
    pages = [lines[k:k + LINES_PER_PAGE] for k in range(0, len(lines), LINES_PER_PAGE)] or [[]]
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}

    def add_obj(num: int, body: bytes):
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    kids = " ".join(f"{4 + 2 * k} 0 R" for k in range(len(pages)))
    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    add_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for k, page in enumerate(pages):
        add_obj(
            4 + 2 * k,
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (PAGE_W, PAGE_H, 5 + 2 * k)
            ).encode(),
        )
        stream = bytearray()
        y = PAGE_H - 50
        for line in page:
            stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {X} {y:.2f} Tm (".encode())
            stream.extend(escape(line))
            stream.extend(b") Tj ET\n")
            y -= LINE_H
        add_obj(5 + 2 * k, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream")

    xref_pos = len(out)
    count = max(offsets) + 1
    out.extend(f"xref\n0 {count}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for num in range(1, count):
        out.extend(f"{offsets[num]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())

    with open(path, "wb") as f:
        f.write(bytes(out))


def main():
    os.makedirs(OUT, exist_ok=True)
    written = []

    for i, (_start, end) in enumerate(MONTHS):
        name = f"vantage-brokerage-{end.strftime('%Y%m')}.pdf"
        build_pdf(brokerage_lines(i), os.path.join(OUT, name))
        written.append(name)

    for i, (_start, end) in enumerate(CARD_MONTHS):
        name = f"meridian-card-{end.strftime('%Y%m')}.pdf"
        build_pdf(card_lines(i), os.path.join(OUT, name))
        written.append(name)

    check()
    for n in written:
        print("wrote", os.path.join(OUT, n))


def money_weighted_return() -> float:
    """The portfolio's annual money-weighted return from the first
    month-end to the last: the rate at which the opening value plus every
    deposit and contribution, less every withdrawal, grows into the closing
    value. Dividends stay inside and are not flows."""
    first, last = MONTHS[0][1], MONTHS[-1][1]

    def value(i):
        return sum(quantities_at(a, h, i)[s] * price_at(s, i) for a, _t, h in ACCOUNTS for s in h)

    flows = []
    for acct, _type, holdings in ACCOUNTS:
        for i in range(1, len(MONTHS)):
            rows, _ = activity_for(acct, holdings, i)
            flows += [(d, amount) for d, kind, _s, _d, _n, _p, amount in rows
                      if kind in ("Deposit", "Contribution", "Withdrawal")]

    def years(d):
        return (d - first).days / 365.25

    def surplus(rate):
        grown = value(0) * (1 + rate) ** years(last)
        for d, amount in flows:
            grown += amount * (1 + rate) ** (years(last) - years(d))
        return grown - value(len(MONTHS) - 1)

    lo, hi = -0.5, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if surplus(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def check():
    """The teaching examples, asserted.

    A demo whose lessons quietly stop being true is worse than no demo: it
    teaches the wrong thing with the product's full confidence behind it.
    So every claim the onboarding copy makes about this household is
    checked here, and changing a holding fails loudly rather than
    silently making the copy wrong.
    """
    final = len(MONTHS) - 1

    # 1. The nearest tax line is a cliff, not a bracket.
    magi = PRIOR_YEAR_TAXABLE_INCOME + STD_DEDUCTION_MFJ_2026
    headroom = IRMAA_TIER1_MFJ_2026 - magi
    assert abs(headroom - EXPECTED_HEADROOM) < 0.01, (
        f"IRMAA headroom is {headroom:,.2f} but household.json says {EXPECTED_HEADROOM:,.2f} - "
        f"the profile OrbySystems seeds and the lesson the copy quotes have come apart")

    # 2. One position dominates the taxable account, with a large gain.
    acct, _type, holdings = ACCOUNTS[0]
    q = quantities_at(acct, holdings, final)
    values = {s: q[s] * price_at(s, final) for s in holdings}
    total = sum(values.values())
    biggest = max(values, key=values.get)
    assert biggest == "NVDA", (
        f"{biggest} is the largest taxable position, not NVDA - a broad-market fund at a "
        f"third of an account is diversification, not the concentration problem the "
        f"Concentrated Position Study exists to solve")
    share = values["NVDA"] / total
    assert 0.28 <= share <= 0.36, f"NVDA is {share:.1%} of the taxable account, want ~32%"
    gain = values["NVDA"] - holdings["NVDA"][1]
    assert gain > 250_000, f"the concentrated position's gain is {gain:,.0f}, want a study-sized one"

    # 3. Bonds are in exactly the wrong places: throwing ordinary income
    #    in the taxable account, and using up tax-free space in the Roth.
    taxable_bonds = values["BND"]
    assert taxable_bonds > 250_000, "the taxable account should hold enough bonds to matter"
    roth = dict(zip(("acct", "type", "holdings"), ACCOUNTS[1]))["holdings"]
    rq = quantities_at("6683", roth, final)
    roth_total = sum(rq[s] * price_at(s, final) for s in roth)
    roth_bondish = sum(rq[s] * price_at(s, final)
                       for s in roth if SECURITIES[s][1] == "bond")
    assert roth_bondish / roth_total > 0.9, "the Roth should be almost entirely bonds"

    # 4. The ledger balances: nothing is bought with money that appears
    #    from nowhere. Same rule the benchmark dataset had to learn.
    for acct, _type, holdings in ACCOUNTS:
        net = 0.0
        for i in range(len(MONTHS)):
            rows, _dep = activity_for(acct, holdings, i)
            net += sum(r[6] for r in rows)
        assert abs(net) < 0.05, f"account {acct} nets to {net:,.2f}, not 0.00"

    # 5. Quantities never go negative walking backwards.
    for acct, _type, holdings in ACCOUNTS:
        for i in range(len(MONTHS)):
            for sym, n in quantities_at(acct, holdings, i).items():
                assert n > 0, f"{acct}/{sym} is {n} in month {i}"

    # 6. It returns what a well-run portfolio of these funds plausibly
    #    does - not a bull market's 20%, which would make every plan look
    #    safe, nor so little that every plan fails.
    rate = money_weighted_return()
    assert 0.08 <= rate <= 0.09, f"the portfolio returns {rate:.2%} a year, want 8-9%"

    print(f"checks passed: return {rate:.2%} a year, IRMAA headroom {headroom:,.0f}, "
          f"NVDA {share:.1%} of taxable with {gain:,.0f} gain, "
          f"portfolio {sum(sum(quantities_at(a, h, final)[s] * price_at(s, final) for s in h) for a, _t, h in ACCOUNTS):,.0f}")


if __name__ == "__main__":
    main()
