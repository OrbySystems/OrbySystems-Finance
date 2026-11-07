#!/usr/bin/env python3
"""Generates tests/fixtures/chase-uk-card-synthetic-sample.pdf, the demo
statement behind tests/test_chase_uk_credit_card.py.

Every name, figure and date here is invented, so the fixture can live in git.
The layout follows a real Chase UK credit card statement's, as a scrambled
sample of one showed it (7 Nov 2026), with the text at the vertical offsets
measured on that sample. pdfplumber groups lines by position, so the text it
reads here is grouped as a real statement's would be:
  - page 1: "Your credit card statement", the statement date and period,
    "...section of the Chase app";
  - page 2: the period's summary ("Opening balance Money out Money in
    Interest & fees Closing balance" over "£A + £B - £C + £D = £E"), then
    the transactions, each on three lines (date and merchant, the amount 6pt
    below, money in marked "+", then what it was);
  - a merchant's name wrapped onto a second line, 8pt down, which pdfplumber
    runs into the amount ("London WC2 £57.12");
  - foreign purchases, with "| EUR 25.00 | FX rate £1 = EUR 1.1550";
  - the transactions carrying on to page 3 under the repeated statement date
    and period, an interest charge, and the "Closing balance" line;
  - a page of small print.
"""

import os
from decimal import Decimal as D

H = 842.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "chase-uk-card-synthetic-sample.pdf")

OPENING = D("1250.00")
STATEMENT_DATE, PERIOD = "03 Oct 2026", "03 Sep 2026 - 02 Oct 2026"
# (date, merchant lines, amount, money in?, what it was)
PAGE_2_ROWS = [
    ("04 Sep 2026", ["Tesco Stores 2041"], D("41.30"), False, "Purchase"),
    ("05 Sep 2026", ["Sainsbury's Supermarkets Ltd Holborn Circus Kingsway Branch", "London WC2"], D("57.12"), False, "Purchase"),
    ("06 Sep 2026", ["Pret A Manger Paris Gare du Nord"], D("21.65"), False, "Purchase | EUR 25.00 | FX rate £1 = EUR 1.1550"),
    ("08 Sep 2026", ["Transport for London"], D("2.80"), False, "Purchase"),
    ("12 Sep 2026", ["Amazon.co.uk"], D("18.00"), True, "Refund"),
    ("14 Sep 2026", ["Deliveroo"], D("24.60"), False, "Purchase"),
    ("15 Sep 2026", ["Hotel Le Marais"], D("312.40"), False, "Purchase | EUR 360.82 | FX rate £1 = EUR 1.1550"),
    ("17 Sep 2026", ["Uber"], D("14.25"), False, "Purchase"),
]
PAGE_3_ROWS = [
    ("20 Sep 2026", ["Waitrose"], D("88.10"), False, "Purchase"),
    ("27 Sep 2026", ["From Alex Morgan"], OPENING, True, "Repayment"),
    ("28 Sep 2026", ["Boots"], D("12.49"), False, "Purchase"),
    ("01 Oct 2026", ["Netflix.com"], D("10.99"), False, "Purchase | USD 14.80 | FX rate £1 = USD 1.3467"),
    ("02 Oct 2026", ["Interest charged"], D("2.15"), False, "Interest"),
]
ROWS = PAGE_2_ROWS + PAGE_3_ROWS


def esc(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("cp1252")


def build(pages, path):
    """pages: [[(x, top, size, text), ...], ...], top as pdfplumber reports it."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}

    def obj(n, body):
        offsets[n] = len(out)
        out.extend(f"{n} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    nums = [4 + 2 * i for i in range(len(pages))]
    obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in nums)}] /Count {len(pages)} >>".encode())
    obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, items in enumerate(pages):
        stream = bytearray()
        for x, top, size, text in items:
            base = H - top - 0.793 * size
            stream.extend(f"BT /F1 {size} Tf 1 0 0 1 {x:.2f} {base:.2f} Tm (".encode())
            stream.extend(esc(text))
            stream.extend(b") Tj ET\n")
        obj(nums[i], (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 {H:.0f}] "
                      f"/Resources << /Font << /F1 3 0 R >> >> /Contents {nums[i] + 1} 0 R >>").encode())
        obj(nums[i] + 1, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream")
    xref = len(out)
    count = max(offsets) + 1
    out.extend(f"xref\n0 {count}\n0000000000 65535 f \n".encode())
    for n in range(1, count):
        out.extend(f"{offsets[n]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    with open(path, "wb") as f:
        f.write(bytes(out))


def gbp(x: D) -> str:
    return f"£{x:,.2f}"


def grid(lines, start=40.0, lead=12.0, size=8.0, x=40.0):
    return [(x, start + i * lead, size, s) for i, s in enumerate(lines) if s]


def money_out() -> D:
    return sum(a for _, _, a, money_in, kind in ROWS if not money_in and kind != "Interest")


def interest() -> D:
    return sum(a for _, _, a, _, kind in ROWS if kind == "Interest")


def money_in() -> D:
    return sum(a for _, _, a, money_in, _ in ROWS if money_in)


def closing() -> D:
    return OPENING + money_out() - money_in() + interest()


def rows_at(rows, top):
    """A page's transactions from top: three lines each, at the sample's offsets."""
    items = []
    for day, merchant, amount, into, kind in rows:
        items += [(40, top, 7.5, day), (100, top, 7.5, merchant[0])]
        extra = 0
        for k, more in enumerate(merchant[1:], 1):
            items.append((100, top + 8 * k, 7.5, more))
            extra = 8 * k
        shown = ("+" if into else "") + gbp(amount)
        items += [(555 - 4.2 * len(shown), top + 6.0, 7.5, shown), (100, top + 10.21 + extra, 7.5, kind)]
        top += 32 + extra
    return items, top


def build_pages():
    page1 = grid([
        "The best way to call or chat with us is via the",
        "'Support' section of the Chase app.",
        "Alex Morgan", "Flat 2", "1 Example Street", "London", "AB1 2CD",
        "Your credit card statement",
        f"Statement date: {STATEMENT_DATE} Available credit: {gbp(D('5000') - closing())}",
        f"Statement period: {PERIOD} Credit limit: £5,000.00",
        "Your balances", "Minimum payment", "£25.00", "Due 27 Oct 2026",
        f"Statement balance: {gbp(closing())}",
        "Description Interest Balance Annual Rate",
        f"Standard purchases {gbp(interest())} {gbp(closing())} 24.90%",
    ]) + [(524.3, 802.16, 6, "Page 1 of 4")]
    page2 = [(40, 108.05, 14, "Transactions"),
             (40, 140.71, 7.5, "Opening balance"), (175, 140.71, 7.5, "Money out"), (288, 140.71, 7.5, "Money in"),
             (395, 140.71, 7.5, "Interest & fees"), (494.9, 140.71, 7.5, "Closing balance"),
             (40, 154.71, 7.5, gbp(OPENING)), (135, 153.33, 12, "+"), (175, 154.71, 7.5, gbp(money_out())),
             (240, 153.33, 12, "-"), (288, 154.71, 7.5, gbp(money_in())), (355, 153.33, 12, "+"),
             (395, 154.71, 7.5, gbp(interest())), (484, 153.33, 12, "="), (519.1, 154.71, 7.5, gbp(closing())),
             (40, 181.71, 7.5, "Date"), (100, 181.71, 7.5, "Transaction details"), (524, 181.71, 7.5, "Amount")]
    rows, _ = rows_at(PAGE_2_ROWS, 211.71)
    page2 += rows + [(524.3, 802.16, 6, "Page 2 of 4")]
    page3 = [(40, 108.05, 14, "Transactions"),
             (40, 130.0, 7.5, f"Statement date: {STATEMENT_DATE}"), (40, 142.0, 7.5, f"Statement period: {PERIOD}"),
             (40, 181.71, 7.5, "Date"), (100, 181.71, 7.5, "Transaction details"), (524, 181.71, 7.5, "Amount")]
    rows, top = rows_at(PAGE_3_ROWS, 211.71)
    shown = gbp(closing())
    page3 += rows + [(40, top, 7.5, STATEMENT_DATE), (100, top, 7.5, "Closing balance"),
                     (555 - 4.2 * len(shown), top + 6.0, 7.5, shown),
                     (40, top + 40, 7.5, "* If you don't pay off the full amount owed, we'll allocate your payment as set out overleaf."),
                     (524.3, 802.16, 6, "Page 3 of 4")]
    page4 = grid([
        "Interest-free period",
        "Up to 56 interest-free days for purchases when you pay off your statement balance in full and on time.",
        "Allocation of payments",
        "If you pay less than the full amount you owe, we use your payment to reduce the balances charged the highest rate first.",
        "Fees",
        "Late payment fee £12.00 for each late payment",
        "Chase is a registered trading name of an example bank, registered in England.",
    ]) + [(524.3, 802.16, 6, "Page 4 of 4")]
    return [page1, page2, page3, page4]


def main():
    build(build_pages(), OUT)
    print(f"wrote {OUT}")
    print(f"  {len(ROWS)} transactions, opening {OPENING}, closing {closing()}")


if __name__ == "__main__":
    main()
