#!/usr/bin/env python3
"""Generate wholly invented Citi Costco Anywhere Visa statements for two
cards, the primary cardholder's and an authorized user's, paid by one
payment. Their transaction table is on page 3 with the rewards summary in a
column beside it, a line of that column level with each of some rows and
headings.

The base statement has the autopay row at page 3, line 17, beside a column
line that holds a year ("Your 2026 reward will follow"); every figure adds
up. Each variant adds one way a statement in this layout can fail to add up
for a reason that is not the arithmetic:

  amount-beside       the authorized user's row level with a column line
                      holding its own "$" figure ("Year to Date : $31.40");
  first-row-beside    the primary cardholder's first row level with that
                      line, the ledger's "certificate amount ...... -$12.40"
                      under the autopay - a tester's statement's layout;
  credits-beside      the authorized user's own Payments, Credits and
                      Adjustments, its heading level with that column line,
                      over a return;
  undated-interest    an interest charge printed without a date, its total
                      level with a column line ("1% on all other purchases").
"""

from pathlib import Path

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 9
LINE_H = 13
COLUMN_X = 330
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def escape(value: str) -> bytes:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def pdf_of(streams: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    def add(number: int, body: bytes):
        offsets[number] = len(out)
        out.extend(f"{number} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    page_objects = [4 + 2 * index for index in range(len(streams))]
    add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add(2, f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_objects)}] /Count {len(streams)} >>".encode())
    add(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, stream in enumerate(streams):
        page_number = page_objects[index]
        content_number = page_number + 1
        add(page_number, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>"
        ).encode())
        add(content_number, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")

    xref = len(out)
    out.extend(f"xref\n0 {max(offsets) + 1}\n0000000000 65535 f \n".encode())
    for number in range(1, max(offsets) + 1):
        out.extend(f"{offsets[number]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {max(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


def page_stream(slots: list[tuple[str | None, str | None]]) -> bytes:
    """One line a slot: the table's text at the left margin, the column's
    beside it on the same baseline."""
    stream = bytearray()
    for n, (left, right) in enumerate(slots):
        y = PAGE_H - 45 - LINE_H * n
        for x, text in ((40, left), (COLUMN_X, right)):
            if text:
                stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {x} {y} Tm (".encode())
                stream.extend(escape(text))
                stream.extend(b") Tj ET\n")
    return bytes(stream)


def summary_page(payments: str, credits: str, purchases: str, interest: str,
                 new_balance: str) -> list[tuple[str | None, str | None]]:
    return [(line, None) for line in [
        "www.citicards.com Costco Anywhere Visa Card by Citi",
        "Account number ending in: 4455",
        "SEPTEMBER STATEMENT",
        "Billing Period: 08/15/26-09/14/26",
        "Account Summary",
        "Previous balance $300.00",
        f"Payments {payments}",
        f"Credits {credits}",
        f"Purchases {purchases}",
        "Cash advances +$0.00",
        "Fees +$0.00",
        f"Interest {interest}",
        f"New balance {new_balance}",
    ]]


TERMS_PAGE = [(line, None) for line in [
    "Page 2 of 3",
    "How We Calculate Interest. We use the daily balance method.",
    "Your Rights If You Are Dissatisfied With Your Credit Card Purchases.",
    "Balance Transfers. Balance Transfer amounts are included in the Purchases line.",
]]

AUTOPAY = "09/10 AUTOPAY 260807000000000RAUTOPAY AUTO-PMT -$300.00"


def table_page(variant: str) -> list[tuple[str | None, str | None]]:
    pat = ["08/21 08/21 SAMPLE FERRY TERMINAL WA $45.00", "08/24 08/24 SAMPLE EV CHARGING CA $15.00",
           "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $165.00"]
    sam = ["08/30 08/30 WWW COSTCO COM WA $60.00"]
    if variant != "credits-beside":
        sam.append("09/06 09/06 COSTCO GAS #0100 SAMPLE CITY CA $25.00")
    sam_total = "$ 60.00" if variant == "credits-beside" else "$ 85.00"
    slots = [
        ("Page 3 of 3", None),
        ("www.citicards.com Customer Service 1-888-555-0100", None),
        ("PAT EXAMPLE", None),
        ("CARDHOLDER SUMMARY", "Costco Cash Back"),
        (None, "Rewards Summary"),
        ("PAT EXAMPLE Card ending in 4455", None),
        ("New Charges $ 225.00", None),
        ("SAM EXAMPLE Card ending in 4466", "Total Costco"),
        (f"New Charges {sam_total}", "Cash Back Rewards Balance:"),
        (None, "$31.40"),
        ("ACCOUNT SUMMARY", None),
        ("Sale Post", None),
        ("Date Date Description Amount", "Costco Cash Back Rewards Summary"),
        (None, "Costco Cash Back Rewards balance as of"),
        ("Payments, Credits and Adjustments", "last statement ............ +$12.40"),
        (None, "Earned this period ........ +$19.00"),
        # Page 3, line 17.
        (AUTOPAY, "Your 2026 reward will follow"),
    ]
    if variant == "first-row-beside":
        slots += [(None, "certificate amount ............ -$12.40"), ("PAT EXAMPLE", None),
                  ("Standard Purchases", None), (None, "Total Costco Cash Back Rewards Balance"),
                  (pat[0], "Year to Date : $31.40")] + [(row, None) for row in pat[1:]]
    else:
        slots.append((None, "Total Costco Cash Back Rewards Balance"))
        if variant not in ("amount-beside", "credits-beside"):
            slots.append((None, "Year to Date : $31.40"))
        slots += [("PAT EXAMPLE", None), ("Standard Purchases", None)] + [(row, None) for row in pat]
    slots.append(("SAM EXAMPLE Card ending in 4466", None))
    if variant == "credits-beside":
        slots += [("Payments, Credits and Adjustments", "Year to Date : $31.40"),
                  ("09/08 09/08 COSTCO WHSE #0100 SAMPLE CITY CA -$20.00", None)]
    slots.append(("Standard Purchases", None))
    for n, row in enumerate(sam):
        slots.append((row, "Year to Date : $31.40" if variant == "amount-beside" and n == len(sam) - 1 else None))
    slots += [("Fees Charged", None), ("TOTAL FEES FOR THIS PERIOD $0.00", None), ("Interest Charged", None)]
    if variant == "undated-interest":
        slots += [("INTEREST CHARGED TO STANDARD PURCH $4.20", None),
                  ("TOTAL INTEREST FOR THIS PERIOD $4.20", "1% on all other purchases")]
    else:
        slots.append(("TOTAL INTEREST FOR THIS PERIOD $0.00", None))
    slots += [("2026 totals year-to-date", None), ("Total fees charged in 2026 $0.00", None),
              ("Total interest charged in 2026 $0.00", None), ("Interest charge calculation", None)]
    return slots


VARIANTS = {
    # name: (Payments, Credits, Purchases, Interest, New balance) as the summary prints them
    "": ("-$300.00", "-$0.00", "+$310.00", "+$0.00", "$310.00"),
    "amount-beside": ("-$300.00", "-$0.00", "+$310.00", "+$0.00", "$310.00"),
    "first-row-beside": ("-$300.00", "-$0.00", "+$310.00", "+$0.00", "$310.00"),
    "credits-beside": ("-$300.00", "-$20.00", "+$285.00", "+$0.00", "$265.00"),
    "undated-interest": ("-$300.00", "-$0.00", "+$310.00", "+$4.20", "$314.20"),
}

for variant, figures in VARIANTS.items():
    name = "citi-costco-three-page" + (f"-{variant}" if variant else "") + "-synthetic-sample.pdf"
    out = FIXTURES / name
    out.write_bytes(pdf_of([page_stream(summary_page(*figures)), page_stream(TERMS_PAGE),
                            page_stream(table_page(variant))]))
    print(out)
