#!/usr/bin/env python3
"""Generates tests/fixtures/citi-card-synthetic-sample.pdf, the demo
statement for the layout Citi's own cards print (citi_credit_card).

Every name, merchant, amount and account number here is invented, so the
fixture can live in git and run everywhere.

It reproduces the layout details the parser has to survive:
  - the Account Summary printed in a column beside the late-payment
    warning, its labels left-aligned and its figures right-aligned, so
    its lines interleave with the warning's when the text is extracted
  - signed summary figures ("-$500.00", "+$612.34")
  - a transaction table headed "Trans. / Post" over "date date
    Description Amount", continuing onto the next page with the page
    header and the table header printed again
  - Payments, Credits and Adjustments with a payment that has only one
    date, then each cardholder's Standard Purchases under their name
  - Fees Charged and Interest Charged closing on their printed totals, and
    a year-to-date block whose own totals are not the period's
  - a period straddling a year boundary (12/11/2026 - 01/10/2027),
    including a November transaction posted in December

Regenerate with:  python3 tests/generators/gen-citi-card-sample.py
"""

import os

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 8
LINE_H = 11

X_LEFT = 40
X_SUMMARY = 330
X_AMOUNT_R = 560
X_TRANS, X_POST, X_DESC = 40, 80, 120

CARD = "Citi Example Cash® Card"
ACCOUNT = "7731"
OPENING, CLOSING = "12/11/26", "01/10/27"
PREVIOUS_BALANCE = 1284.37

# (trans date or "", post date, description, amount as printed).
PAYMENTS = [
    ("", "12/15", "ONLINE PAYMENT, THANK YOU", -500.00),
    ("12/18", "12/18", "SAMPLE OUTFITTERS RETURN SPRINGFIELD IL", -18.25),
]
PURCHASES = {
    "PAT SAMPLE": [
        ("11/29", "12/11", "LATE POSTING HOTEL SPRINGFIELD IL", 211.40),
        ("12/12", "12/12", "MAPLE GROCERS SPRINGFIELD IL", 63.18),
        ("12/20", "12/21", "CORNER PHARMACY SPRINGFIELD IL", 24.95),
        ("12/28", "12/28", "TRAIN TICKETS ONLINE 800-555-0161 NY", 148.00),
    ],
    "SAM SAMPLE": [
        ("01/03", "01/03", "BOOKSHOP ON MAIN SPRINGFIELD IL", 37.42),
        ("01/06", "01/07", "STREAMING SERVICE 888-555-0144 CA", 15.99),
    ],
}
# The table breaks onto the next page after this many purchase rows.
PAGE_BREAK_AFTER = 3


def money(value: float) -> str:
    return ("-" if value < 0 else "") + f"${abs(value):,.2f}"


def text_width(s: str) -> float:
    return len(s) * FONT_SIZE * 0.55


def totals(previous_balance: float = PREVIOUS_BALANCE):
    payments = round(sum(r[3] for r in PAYMENTS if "PAYMENT" in r[2]), 2)
    credits = round(sum(r[3] for r in PAYMENTS if "PAYMENT" not in r[2]), 2)
    purchases = round(sum(a for rows in PURCHASES.values() for *_, a in rows), 2)
    new_balance = round(previous_balance + payments + credits + purchases, 2)
    return payments, credits, purchases, new_balance


def build_pages(previous_balance: float = PREVIOUS_BALANCE):
    """The statement's pages, and its New balance."""
    payments, credits, purchases, new_balance = totals(previous_balance)
    pages, items = [], []

    def emit(x, y, s):
        items.append((x, y, s))

    def right(y, s):
        emit(X_AMOUNT_R - text_width(s), y, s)

    def header(y, number):
        emit(X_LEFT, y, f"Page {number} of 4"); y -= LINE_H
        emit(X_LEFT, y, CARD); y -= LINE_H
        emit(X_LEFT, y, f"www.citicards.com Member Since 2011. Account number ending in: {ACCOUNT}"); y -= LINE_H
        emit(X_LEFT, y, "PAT SAMPLE"); y -= LINE_H
        return y

    def table_header(y):
        emit(X_TRANS, y, "Trans."); emit(X_POST, y, "Post"); y -= LINE_H
        emit(X_TRANS, y, "date"); emit(X_POST, y, "date"); emit(X_DESC, y, "Description"); right(y, "Amount")
        return y - LINE_H

    def row(y, trans, post, desc, amount):
        if trans:
            emit(X_TRANS, y, trans)
        emit(X_POST, y, post)
        emit(X_DESC, y, desc)
        right(y, money(amount))
        return y - LINE_H

    # --- page 1: the summary beside the late-payment warning ---
    y = PAGE_H - 50
    emit(X_LEFT, y, "Billing Inquiries and Customer Service"); y -= LINE_H
    emit(X_LEFT, y, f"1-800-555-0123 {CARD}"); y -= LINE_H
    emit(X_LEFT, y, f"www.citicards.com Member Since 2011. Account number ending in: {ACCOUNT}"); y -= LINE_H
    emit(X_LEFT, y, "JANUARY STATEMENT"); y -= LINE_H
    emit(X_LEFT, y, f"Billing Period: {OPENING}-{CLOSING}"); y -= LINE_H
    emit(X_LEFT, y, f"New balance as of {CLOSING}: {money(new_balance)}"); y -= LINE_H
    emit(X_LEFT, y, "Minimum payment due: $35.00"); y -= LINE_H
    emit(X_LEFT, y, "Payment due date: 02/05/27"); y -= LINE_H * 2
    emit(X_SUMMARY, y, "Account Summary"); y -= LINE_H
    left = [
        "",
        "Late Payment Warning: If we do not receive your Minimum Payment",
        "by the date listed above, you may have to pay a late fee of up to $41",
        "and your APRs may be increased up to the Penalty APR of 29.99%.",
        "",
        "For information about credit counseling services, call 1-800-555-0177.",
        "",
        "",
        "",
        "",
    ]
    summary = [
        ("Previous balance", money(previous_balance)),
        ("Payments", money(payments)),
        ("Credits", money(credits)),
        None,
        ("Purchases", "+" + money(purchases)),
        None,
        ("Cash advances", "+$0.00"),
        ("Fees", "+$0.00"),
        ("Interest", "+$0.00"),
        ("New balance", money(new_balance)),
    ]
    for text, line in zip(left, summary):
        if text:
            emit(X_LEFT, y, text)
        if line:
            emit(X_SUMMARY, y, line[0])
            right(y, line[1])
        y -= LINE_H
    y -= LINE_H
    emit(X_LEFT, y, "Credit Limit"); y -= LINE_H
    emit(X_LEFT, y, "Credit limit $6,500"); y -= LINE_H
    emit(X_LEFT, y, "Includes $1,300 cash advance limit"); y -= LINE_H
    emit(X_LEFT, y, f"Available credit ${6500 - new_balance:,.0f}"); y -= LINE_H * 3
    # The payment coupon, which prints the New balance again.
    emit(X_SUMMARY - 30, y, "Minimum payment due"); emit(X_SUMMARY + 70, y, "New balance")
    emit(X_SUMMARY + 140, y, "Payment due date"); y -= LINE_H
    emit(X_LEFT, y, "Box 6500 Springfield, IL 62701-6500")
    emit(X_SUMMARY + 30 - text_width("$35.00"), y, "$35.00")
    emit(X_SUMMARY + 120 - text_width(money(new_balance)), y, money(new_balance))
    emit(X_SUMMARY + 160, y, "02/05/27")
    pages.append(items)

    # --- page 2: terms (no amounts the parser reads) ---
    items = []
    y = header(PAGE_H - 50, 2)
    emit(X_LEFT, y, "Information About Your Account"); y -= LINE_H
    emit(X_LEFT, y, "How We Calculate Interest. We calculate it separately for each balance shown in the table.")
    pages.append(items)

    # --- page 3: the table, which continues onto page 4 ---
    first = PURCHASES["PAT SAMPLE"]
    items = []
    y = header(PAGE_H - 50, 3)
    emit(X_LEFT, y, "Account Summary"); y -= LINE_H
    y = table_header(y)
    emit(X_LEFT, y, "Payments, Credits and Adjustments"); y -= LINE_H
    for r in PAYMENTS:
        y = row(y, *r)
    emit(X_LEFT, y, "PAT SAMPLE"); y -= LINE_H
    emit(X_LEFT, y, "Standard Purchases"); y -= LINE_H
    for r in first[:PAGE_BREAK_AFTER]:
        y = row(y, *r)
    pages.append(items)

    items = []
    y = header(PAGE_H - 50, 4)
    y = table_header(y)
    for r in first[PAGE_BREAK_AFTER:]:
        y = row(y, *r)
    emit(X_LEFT, y, "SAM SAMPLE"); y -= LINE_H
    emit(X_LEFT, y, "Standard Purchases"); y -= LINE_H
    for r in PURCHASES["SAM SAMPLE"]:
        y = row(y, *r)
    emit(X_LEFT, y, "Fees Charged"); y -= LINE_H
    emit(X_LEFT, y, "Total fees charged in this billing period"); right(y, "$0.00"); y -= LINE_H
    emit(X_LEFT, y, "Interest Charged"); y -= LINE_H
    emit(X_LEFT, y, "Total interest charged in this billing period"); right(y, "$0.00"); y -= LINE_H * 2
    emit(X_LEFT, y, "2027 totals year-to-date"); y -= LINE_H
    emit(X_LEFT, y, "Total fees charged in 2027"); right(y, "$41.00"); y -= LINE_H
    emit(X_LEFT, y, "Total interest charged in 2027"); right(y, "$18.62"); y -= LINE_H * 2
    emit(X_LEFT, y, "Interest charge calculation"); y -= LINE_H
    emit(X_LEFT, y, "Days in billing cycle: 31"); y -= LINE_H
    emit(X_LEFT, y, "Standard Purch 21.24% (D) $0.00 (S) $0.00"); y -= LINE_H
    emit(X_LEFT, y, "Standard Adv 29.99% (D) $0.00 (S) $0.00")
    pages.append(items)
    return pages, new_balance


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
    # WinAnsiEncoding, so the registered-trademark sign extracts as it prints.
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


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "citi-card-synthetic-sample.pdf")


def main():
    pages, new_balance = build_pages()
    build_pdf(pages, OUT)
    rows = len(PAYMENTS) + sum(map(len, PURCHASES.values()))
    print(f"wrote {OUT}")
    print(f"  {rows} transactions, previous {money(PREVIOUS_BALANCE)}, new balance {money(new_balance)}")


if __name__ == "__main__":
    main()
