#!/usr/bin/env python3
"""Generates tests/fixtures/apple-card-synthetic-sample.pdf, the demo
statement behind tests/test_apple_card.py.

Every name, merchant, amount and address here is invented, so the fixture
can live in git and give the Apple Card parser regression coverage that
runs for everyone. The layout follows a real statement's, as a scrambled
sample of one showed it:

  - the same three-line header on every page, the statement period at the
    end of the holder's line ("Sep 1 — Sep 30, 2026")
  - the summary on page 1: Total Balance, Minimum Payment, and the
    Previous Monthly and Previous Total Balances
  - a Payments table, then a Transactions table with a Daily Cash column
    ("2% $1.68") before each amount
  - the Transactions table breaking across a page, its column header
    reprinted under the next page's header
  - a return, printed negative with negative Daily Cash
  - the Interest Charged table, empty ("— $0.00")

Regenerate with:  python3 tests/generators/gen-apple-card-sample.py
"""

import os

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 8
LINE_H = 11
X_LEFT = 40

HOLDER = "Pat Q Sample, pat.sample@example.com"
PERIOD = "Sep 1 — Sep 30, 2026"
ISSUER = "Apple Card is issued by Goldman Sachs Bank USA, Salt Lake City Branch."
PREVIOUS_BALANCE = 412.37
MINIMUM_PAYMENT = 25.00

# (date, description, amount) as printed: a payment negative.
PAYMENTS = [
    ("09/01/2026", "ACH Deposit Internet transfer from account ending in 5521", -412.37),
]
# (date, description, Daily Cash %, Daily Cash, amount) as printed: a
# purchase positive, a return negative.
TRANSACTIONS = [
    ("09/02/2026", "MAPLE STREET GROCERS 12 MAIN ST SPRINGFIELD 62701 IL USA", "2%", 1.68, 84.12),
    ("09/03/2026", "RIVERTOWN FUEL 0021 400 RIVER RD SPRINGFIELD 62702 IL USA", "2%", 0.83, 41.30),
    ("09/05/2026", "STREAMING CO 888-555-0177 LOS ANGELES 90001 CA USA", "3%", 0.54, 17.99),
    ("09/08/2026", "CORNER BAKERY #12 9 ELM ST SPRINGFIELD 62701 IL USA", "2%", 0.20, 9.75),
    ("09/12/2026", "PINE HARDWARE 800-555-0111 SPRINGFIELD 62704 IL USA", "1%", 1.33, 133.08),
    ("09/15/2026", "BOOKSHOP ON MAIN 21 MAIN ST SPRINGFIELD 62701 IL USA", "2%", 0.55, 27.48),
    # A page break falls here (PAGE_BREAK_AFTER).
    ("09/18/2026", "PINE HARDWARE 800-555-0111 SPRINGFIELD 62704 IL USA", "1%", -0.23, -22.50),
    ("09/22/2026", "TOWN PHARMACY 5 OAK AVE SPRINGFIELD 62701 IL USA", "2%", 0.36, 18.20),
    ("09/28/2026", "CAFE ABROAD 3 RUE EXEMPLE PARIS 75001 FRA", "2%", 0.99, 49.65),
]
PAGE_BREAK_AFTER = 6


def money(value: float) -> str:
    return ("-" if value < 0 else "") + f"${abs(value):,.2f}"


def totals():
    payments = round(sum(r[-1] for r in PAYMENTS), 2)
    charges = round(sum(r[-1] for r in TRANSACTIONS), 2)
    daily_cash = round(sum(r[3] for r in TRANSACTIONS), 2)
    total_balance = round(PREVIOUS_BALANCE + payments + charges, 2)
    return payments, charges, daily_cash, total_balance


def build_pages():
    payments, charges, daily_cash, total_balance = totals()
    pages = []

    def page(lines, number, of):
        y, items = PAGE_H - 50, []
        for line in ["Statement", "Apple Card Customer", f"{HOLDER} {PERIOD}", *lines, ISSUER, f"Page {number} /{of}"]:
            items.append((X_LEFT, y, line))
            y -= LINE_H
        pages.append(items)

    page([
        "Your September Balance Minimum Payment",
        "as of Sep 30, 2026 Payment Due Due By",
        f"{money(total_balance)} {money(MINIMUM_PAYMENT)} Oct 31, 2026",
        "Account Information",
        "If you pay your monthly balance in full each month, you will not be charged interest.",
        "Please go to Wallet or card.apple.com to schedule new payments.",
        f"Previous Monthly Balance {money(PREVIOUS_BALANCE)}",
        "as of Aug 31, 2026",
        f"Previous Total Balance {money(PREVIOUS_BALANCE)}",
        "as of Aug 31, 2026",
        f"Total Balance {money(total_balance)}",
        "as of Sep 30, 2026",
        "Minimum Payment Warning If you make only the minimum payment each period, you will pay more in interest.",
    ], 1, 4)

    first, rest = TRANSACTIONS[:PAGE_BREAK_AFTER], TRANSACTIONS[PAGE_BREAK_AFTER:]
    row = lambda r: f"{r[0]} {r[1]} {r[2]} {money(r[3])} {money(r[4])}"  # noqa: E731
    page([
        "Payments",
        "Date Description Amount",
        *(f"{d} {desc} {money(a)}" for d, desc, a in PAYMENTS),
        f"Total payments for this period {money(payments)}",
        "Transactions",
        "Date Description Daily Cash Amount",
        *(row(r) for r in first),
    ], 2, 4)
    page([
        "Date Description Daily Cash Amount",
        *(row(r) for r in rest),
        f"Total Daily Cash this month {money(daily_cash)}",
        f"Total charges, credits and returns {money(charges)}",
    ], 3, 4)
    page([
        "Daily Cash",
        f"Daily Cash from Apple Card {money(daily_cash)}",
        f"Total Daily Cash {money(daily_cash)}",
        "Interest Charged",
        "— $0.00",
        "Total interest for this month $0.00",
        "Interest Charges Interest Charge Calculation",
        "2026 Total Year-to-Date: Annual Percentage Rate (APR) 24.99 % (variable)",
        "– Total interest charged in 2026 $0.00 Balance subject to interest rate $0.00",
    ], 4, 4)
    return pages, total_balance


def escape(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("cp1252")


def build_pdf(pages, path):
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}

    def add_obj(num: int, body: bytes):
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    page_obj_nums = [4 + 2 * i for i in range(len(pages))]
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    # WinAnsiEncoding, so the period's em dash extracts as it prints.
    add_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    for i, items in enumerate(pages):
        page_num, content_num = page_obj_nums[i], page_obj_nums[i] + 1
        add_obj(page_num, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode())
        stream = bytearray()
        for x, y, s in items:
            stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm (".encode())
            stream.extend(escape(s))
            stream.extend(b") Tj ET\n")
        add_obj(content_num, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream")

    xref_pos = len(out)
    count = max(offsets) + 1
    out.extend(f"xref\n0 {count}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for num in range(1, count):
        out.extend(f"{offsets[num]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())

    with open(path, "wb") as f:
        f.write(bytes(out))


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "apple-card-synthetic-sample.pdf")


def main():
    pages, total_balance = build_pages()
    build_pdf(pages, OUT)
    print(f"wrote {OUT}")
    print(f"  {len(PAYMENTS) + len(TRANSACTIONS)} transactions, previous {money(PREVIOUS_BALANCE)}, "
          f"total balance {money(total_balance)}")


if __name__ == "__main__":
    main()
