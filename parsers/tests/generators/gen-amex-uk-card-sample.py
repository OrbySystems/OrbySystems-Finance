#!/usr/bin/env python3
"""Generates tests/fixtures/amex-uk-card-synthetic-sample.pdf, the demo
statement behind tests/test_amex_uk_credit_card.py.

Every name, figure and date here is invented, so the fixture can live in git.
The layout follows a real American Express UK "Statement of Account", as a
scrambled sample of one showed it (7 Nov 2026), with the transactions at the
vertical offsets measured on that sample, so pdfplumber groups their lines
as it does a real statement's:
  - page 1: the masked Membership Number, the account summary ("Previous
    Closing Balance New Credits New Debits Closing Balance" over "£A - £B +
    £C = £D") and "Statement Period From ... to ...";
  - the transactions under the two-line header ("Transaction Process" /
    "Date Date Transaction Details Foreign Spending Amount £"), each row
    "Mon DD Mon DD DETAILS AMOUNT", a credit marked CR 12pt below its row;
  - a refund whose merchant prints an address line 10.7pt below it, which
    pdfplumber runs into its CR ("1 Example Road London CR");
  - a foreign purchase with its "Euro 41.00" line;
  - the transactions carrying on to the next page under the repeated
    header, then "Total new spend transactions for <NAME>", and a
    supplementary cardholder's rows with their own total;
  - payment instructions after the table, and a summary box page.
"""

import os
from decimal import Decimal as D

H = 842.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "amex-uk-card-synthetic-sample.pdf")

PREVIOUS = D("1480.00")
# (date, processed, details, amount, credit?, the line below it)
MAIN_PAGE_2 = [
    ("Sep 21", "Sep 21", "PAYMENT RECEIVED - THANK YOU", PREVIOUS, True, None),
    ("Sep 22", "Sep 23", "TESCO STORES 2041 LONDON", D("38.40"), False, None),
    ("Sep 23", "Sep 24", "JOHN LEWIS OXFORD ST LONDON", D("120.00"), True, "1 Example Road London"),
    ("Sep 24", "Sep 25", "AMAZON.CO.UK*AB12C34D5 AMAZON.CO.UK", D("23.99"), False, None),
    ("Sep 26", "Sep 28", "HOTEL LE MARAIS PARIS", D("35.50"), False, "Euro 41.00"),
    ("Sep 30", "Oct 1", "PRET A MANGER LONDON", D("6.45"), False, None),
]
MAIN_PAGE_3 = [
    ("Oct 2", "Oct 3", "TFL TRAVEL CH TFL.GOV.UK/CP", D("2.80"), False, None),
    ("Oct 5", "Oct 6", "WAITROSE 123 LONDON", D("88.10"), False, None),
    ("Oct 9", "Oct 10", "DELIVEROO LONDON", D("24.60"), False, None),
]
SUPPLEMENTARY = [
    ("Sep 23", "Sep 24", "BOOTS 1180 LONDON", D("12.49"), False, None),
    ("Oct 4", "Oct 5", "SHELL WANDSWORTH LONDON", D("61.70"), False, None),
]
MAIN = MAIN_PAGE_2 + MAIN_PAGE_3
ROWS = MAIN + SUPPLEMENTARY


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


def plain(x: D) -> str:
    return f"{x:,.2f}"


def gbp(x: D) -> str:
    return f"£{x:,.2f}"


def grid(lines, start=40.0, lead=12.0, size=8.0, x=40.0):
    return [(x, start + i * lead, size, s) for i, s in enumerate(lines) if s]


def credits() -> D:
    return sum(r[3] for r in ROWS if r[4])


def debits() -> D:
    return sum(r[3] for r in ROWS if not r[4])


def closing() -> D:
    return PREVIOUS - credits() + debits()


def total(rows) -> D:
    """A cardholder's "Total new spend": their rows net of refunds, the repayment left out."""
    return sum(-r[3] if r[4] else r[3] for r in rows if "THANK YOU" not in r[2])


def page_head(number: int):
    return grid(["Statement of Account", f"Page {number} of 5", "Prepared for Membership Number Date",
                 "ALEX MORGAN xxxx-xxxxxx-31007 20/10/26"]) + [
        (14.4, 233.84, 6, "Transaction"), (57.6, 233.84, 6, "Process"),
        (14.4, 242.0, 6, "Date"), (57.6, 242.0, 6, "Date"), (100.8, 242.0, 6, "Transaction Details"),
        (377.0, 242.0, 6, "Foreign Spending"), (504.2, 243.68, 6, "Amount £")]


def rows_at(rows, top):
    """Rows at the sample's offsets: the row 9pt at top, its amount 10pt
    0.07pt higher, a line below it 7pt at +10.69, a CR 10pt at +12.17."""
    items = []
    for day, processed, details, amount, credit, below in rows:
        items += [(14.4, top, 9, day), (57.6, top, 9, processed), (100.8, top, 9, details),
                  (532.6 - 5.0 * len(plain(amount)), top - 0.07, 10, plain(amount))]
        if below:
            items.append((377.0 if below.startswith("Euro") else 100.8, top + 10.69, 7, below))
        if credit:
            items.append((518.9, top + 12.17, 10, "CR"))
        top += 31.2 if (credit or below) else 19.2
    return items, top


def build_pages():
    page1 = grid([
        "americanexpress.co.uk", "Customer Service", "0800 000 0000",
        "American Express", "Services Europe Ltd.",
        "Statement of Account", "Page 1 of 5",
        "Prepared for Membership Number Date", "ALEX MORGAN xxxx-xxxxxx-31007 20/10/26",
        "Account Summary",
        "Statement includes payments and charges received by 20 October 2026",
        "Previous Closing Balance New Credits New Debits Closing Balance",
        f"{gbp(PREVIOUS)} - {gbp(credits())} + {gbp(debits())} = {gbp(closing())}",
        "Direct Debit Amount Direct Debit Date Minimum Repayment Payment Due Date",
        f"{gbp(closing())} 5 November 2026 £25.00 10 November 2026",
        "Statement Period From 21 September to 20 October 2026",
        "Credit Summary Credit Limit £ Available Credit Limit £",
        f"At 20 October 2026 6,000.00 {plain(D('6000') - closing())}",
        "ALEX MORGAN", "1 EXAMPLE STREET", "LONDON", "AB1 2CD",
    ])
    rows, top = rows_at(MAIN_PAGE_2, 258.36)
    page2 = page_head(2) + rows + grid([
        "How you can pay your statement",
        "You must pay from a bank account in your own name.",
        "Direct Debit - Payment will be collected from your bank account on the Direct Debit due date shown.",
        "Bank Transfer - Please use sort code 00-00-00 and account number 00000000.",
    ], start=top + 30)
    rows, top = rows_at(MAIN_PAGE_3, 258.36)
    page3 = page_head(3) + rows + [(100.8, top, 9, f"Total new spend transactions for ALEX MORGAN {plain(total(MAIN))}")]
    top += 30
    page3 += [(14.4, top, 9, "Supplementary Card Member SAM MORGAN xxxx-xxxxxx-31015"),
              (14.4, top + 16, 6, "Transaction"), (57.6, top + 16, 6, "Process"),
              (14.4, top + 24, 6, "Date"), (57.6, top + 24, 6, "Date"), (100.8, top + 24, 6, "Transaction Details"),
              (377.0, top + 24, 6, "Foreign Spending"), (504.2, top + 25.68, 6, "Amount £")]
    rows, top = rows_at(SUPPLEMENTARY, top + 40)
    page3 += rows + [(100.8, top, 9, f"Total new spend transactions for SAM MORGAN {plain(total(SUPPLEMENTARY))}")]
    page4 = grid(["Statement of Account", "Page 4 of 5", "Your Cashback Statement",
                  "Cashback earned as of 20/10/2026", "£12.30", "Total Cashback Earned 4.15"])
    page5 = grid(["Statement of Account", "Page 5 of 5", "Summary Box",
                  "Interest Free Period Up to 56 days on purchases if you pay the full amount you owe each month.",
                  "Fees Late Payment Fee £12", "Online at americanexpress.co.uk"])
    return [page1, page2, page3, page4, page5]


def main():
    build(build_pages(), OUT)
    print(f"wrote {OUT}")
    print(f"  {len(ROWS)} transactions, previous {PREVIOUS}, credits {credits()}, debits {debits()}, closing {closing()}")


if __name__ == "__main__":
    main()
