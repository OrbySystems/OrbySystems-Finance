#!/usr/bin/env python3
"""Generates tests/fixtures/fidelity-credit-card-synthetic-sample.pdf, the
demo statement behind tests/test_fidelity_credit_card.py.

Every name, merchant, amount and card number here is invented, so the
fixture can live in git and give the Fidelity Rewards Visa parser
regression coverage that runs for everyone.

It reproduces the layout details the parser has to survive:
  - the Activity Summary printed in a column beside the payment block,
    so their lines interleave when the text is extracted
    ("Minimum Payment Due $... Previous Balance + $...")
  - account-level sections, then a group of sections per card, the
    second card's rows belonging to the same account
  - a section breaking across a page, with the page header, the
    section heading and the column header reprinted
  - detail lines under a row (a ticket number, a passenger, a foreign
    amount) that carry no date and fold into the row's description
  - empty sections, which print "$0.00" in place of rows
  - a period straddling a year boundary (12/20/2025 - 01/19/2026), so a
    row's MM/DD date has to be given the right year, including one whose
    transaction date falls before the period opens

Regenerate with:  python3 tests/generators/gen-fidelity-credit-card-sample.py
"""

import os

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 8
LINE_H = 11

X_LEFT = 40
X_RIGHT = 330
X_POST, X_TRANS, X_REF, X_DESC = 40, 75, 110, 150
X_AMOUNT_R = 560

ACCOUNT = "4417"
SECOND_CARD = "9031"
HOLDER = "PAT Q SAMPLE"
CARD_HOLDERS = {ACCOUNT: "PAT Q", SECOND_CARD: "SAM R"}
OPEN, CLOSE = "12/20/2025", "01/19/2026"
STATEMENT_MONTH = "January 2026"
ISSUER_LINE = "Elan Financial Services 1-888-555-0123"
PREVIOUS_BALANCE = 1850.00
CREDIT_LINE = 10000.00

# (post date, trans date, ref, description, [detail lines], amount).
# Amounts are as the statement prints them: charges positive, credits
# negative (printed with CR).
PAYMENTS = [
    ("01/05", "01/05", "EP", "PAYMENT THANK YOU", [], -1850.00),
]
PURCHASES = {
    ACCOUNT: [
        ("12/20", "12/18", "0412", "MAPLE STREET GROCERS SPRINGFIELD IL", [], 84.12),
        ("12/22", "12/21", "1187", "RIVERTOWN FUEL 0021 SPRINGFIELD IL", [], 41.30),
        ("12/28", "12/26", "2290", "FAKEAIR 0016789012345 FAKEAIR.COM TX",
         ["TICKET 0016789012345", "PASSENGER SAMPLE/PAT"], 612.40),
        ("12/31", "12/30", "3305", "CORNER BAKERY #12 SPRINGFIELD IL", [], 9.75),
        # A page break falls here (PAGE_BREAK_AFTER).
        ("01/03", "01/02", "4486", "PINE HARDWARE 800-555-0111 IL", [], 133.08),
        ("01/09", "01/08", "5521", "CAFE ABROAD PARIS FR", ["45.00 EURO"], 49.65),
        ("01/15", "01/14", "6634", "STREAMING CO 888-555-0177 CA", [], 17.99),
    ],
    SECOND_CARD: [
        ("12/24", "12/23", "8856", "BOOKSHOP ON MAIN SPRINGFIELD IL", [], 27.48),
        ("01/12", "01/11", "9967", "TOWN PHARMACY SPRINGFIELD IL", [], 18.20),
    ],
}
OTHER_CREDITS = {
    ACCOUNT: [
        ("01/10", "01/09", "7745", "PINE HARDWARE 800-555-0111 IL", ["MERCHANDISE RETURN"], -22.50),
    ],
    SECOND_CARD: [],
}
# The first card's purchases break onto the next page after this many.
PAGE_BREAK_AFTER = 4


def money(value: float) -> str:
    return f"${abs(value):,.2f}" + ("CR" if value < 0 else "")


def text_width(s: str) -> float:
    return len(s) * FONT_SIZE * 0.55


def totals(previous_balance: float = PREVIOUS_BALANCE):
    payments = round(sum(r[-1] for r in PAYMENTS), 2)
    credits = round(sum(r[-1] for rows in OTHER_CREDITS.values() for r in rows), 2)
    purchases = round(sum(r[-1] for rows in PURCHASES.values() for r in rows), 2)
    new_balance = round(previous_balance + payments + credits + purchases, 2)
    return payments, credits, purchases, new_balance


def build_pages(previous_balance: float = PREVIOUS_BALANCE):
    """The statement's pages, and its New Balance. previous_balance other
    than the committed one makes a statement not paid in full, which
    orby-core's scrambler test uses (test/scramble_statement_test.py)."""
    payments, credits, purchases, new_balance = totals(previous_balance)
    minimum = 40.00
    pages, items = [], []

    def emit(x, y, s):
        items.append((x, y, s))

    def right(y, s):
        emit(X_AMOUNT_R - text_width(s), y, s)

    def page_header(y, number, of):
        emit(X_LEFT, y, f"{STATEMENT_MONTH} Statement {OPEN} - {CLOSE} Page {number} of {of}")
        y -= LINE_H
        emit(X_LEFT, y, HOLDER)
        emit(X_RIGHT, y, ISSUER_LINE)
        y -= LINE_H
        emit(X_LEFT, y, "Transactions")
        return y - LINE_H

    def section(y, heading):
        emit(X_LEFT, y, heading)
        y -= LINE_H
        emit(X_POST, y, "Post")
        emit(X_TRANS, y, "Trans")
        y -= LINE_H
        emit(X_POST, y, "Date")
        emit(X_TRANS, y, "Date")
        emit(X_REF, y, "Ref #")
        emit(X_DESC, y, "Transaction Description")
        right(y, "Amount")
        return y - LINE_H

    def row(y, post, trans, ref, desc, details, amount):
        emit(X_POST, y, post)
        emit(X_TRANS, y, trans)
        emit(X_REF, y, ref)
        emit(X_DESC, y, desc)
        right(y, money(amount))
        y -= LINE_H
        for d in details:
            emit(X_DESC, y, d)
            y -= LINE_H
        return y

    def empty(y):
        right(y, "$0.00")
        return y - LINE_H

    def total(y, label, amount):
        emit(X_LEFT, y, label)
        right(y, money(amount))
        return y - LINE_H * 2

    # --- page 1: the payment block beside the Activity Summary ---
    y = PAGE_H - 50
    emit(X_LEFT, y, f"{STATEMENT_MONTH} Statement Page 1 of 3"); y -= LINE_H
    emit(X_LEFT, y, f"Open Date:{OPEN} Closing Date:{CLOSE} Account ending in:{ACCOUNT}"); y -= LINE_H
    emit(X_LEFT, y, "Fidelity® Rewards Visa Signature® Card")
    emit(X_RIGHT, y, ISSUER_LINE); y -= LINE_H
    emit(X_LEFT, y, HOLDER); y -= LINE_H * 2
    left = [
        f"New Balance {money(new_balance)}",
        f"Minimum Payment Due {money(minimum)}",
        "Payment Due Date 02/15/2026",
        "",
        "Late Payment Warning: If we do not receive your",
        "minimum payment by the date listed above, you may have",
        "to pay up to a $40.00 Late Fee.",
        "Reward Points",
        "",
        "Earned This Statement 1,862",
        "For details, see your rewards summary.",
    ]
    right_col = [
        "Activity Summary",
        f"Previous Balance + {money(previous_balance)}",
        f"Payments - {money(payments)}",
        f"Other Credits - {money(credits)}",
        f"Purchases + {money(purchases)}",
        "Balance Transfers $0.00",
        "Advances $0.00",
        "Other Debits $0.00",
        "Fees Charged $0.00",
        "Interest Charged $0.00",
        f"New Balance = {money(new_balance)}",
        "Past Due $0.00",
        f"Minimum Payment Due {money(minimum)}",
        f"Revolving Line of Credit {money(CREDIT_LINE)}",
        f"Revolving Line Available {money(CREDIT_LINE - new_balance)}",
        "Days in Billing Period 31",
    ]
    for i in range(max(len(left), len(right_col))):
        if i < len(left) and left[i]:
            emit(X_LEFT, y, left[i])
        if i < len(right_col):
            emit(X_RIGHT, y, right_col[i])
        y -= LINE_H
    pages.append(items)

    # --- page 2: account sections, then the first card's purchases ---
    items = []
    y = page_header(PAGE_H - 50, 2, 3)
    y = section(y, "Account Payments and Credits")
    for r in PAYMENTS:
        y = row(y, *r)
    y = total(y, "TOTAL THIS PERIOD", payments)
    y = section(y, "Account Fees")
    y = empty(y)
    y = total(y, "TOTAL FEES THIS PERIOD", 0.0)
    first = PURCHASES[ACCOUNT]
    y = section(y, f"{CARD_HOLDERS[ACCOUNT]} - {ACCOUNT}: Purchases and Other Debits")
    for r in first[:PAGE_BREAK_AFTER]:
        y = row(y, *r)
    emit(X_LEFT, y - LINE_H, "Continued on Next Page")
    pages.append(items)

    # --- page 3: the rest of the first card, then the second card ---
    items = []
    y = page_header(PAGE_H - 50, 3, 3)
    y = section(y, f"{CARD_HOLDERS[ACCOUNT]} - {ACCOUNT}: Purchases and Other Debits")
    for r in first[PAGE_BREAK_AFTER:]:
        y = row(y, *r)
    y = total(y, "TOTAL THIS PERIOD", sum(r[-1] for r in first))
    for card in (ACCOUNT, SECOND_CARD):
        holder = CARD_HOLDERS[card]
        if card == SECOND_CARD:
            y = section(y, f"{holder} - {card}: Purchases and Other Debits")
            for r in PURCHASES[card]:
                y = row(y, *r)
            y = total(y, "TOTAL THIS PERIOD", sum(r[-1] for r in PURCHASES[card]))
        y = section(y, f"{holder} - {card}: Other Credits")
        for r in OTHER_CREDITS[card]:
            y = row(y, *r)
        if not OTHER_CREDITS[card]:
            y = empty(y)
        y = total(y, "TOTAL THIS PERIOD", sum(r[-1] for r in OTHER_CREDITS[card]))
        y = section(y, f"{holder} - {card}: Fees")
        y = empty(y)
        y = total(y, "TOTAL FEES THIS PERIOD", 0.0)
    emit(X_LEFT, y, "2026 Totals Year-to-Date"); y -= LINE_H
    emit(X_LEFT, y, "Total Fees Charged in 2026 $0.00"); y -= LINE_H
    emit(X_LEFT, y, "Total Interest Charged in 2026 $0.00"); y -= LINE_H * 2
    emit(X_LEFT, y, "Interest Charge Calculation"); y -= LINE_H
    emit(X_LEFT, y, "Balance Type Balance By Type Balance Subject to Interest Rate Interest Charge"); y -= LINE_H
    emit(X_LEFT, y, "PURCHASES $0.00 $0.00 YES $0.00 21.24%"); y -= LINE_H
    emit(X_LEFT, y, "ADVANCES $0.00 $0.00 YES $0.00 29.99%"); y -= LINE_H * 2
    emit(X_LEFT, y, "End of Statement")
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
    # WinAnsiEncoding, so the registered-trademark signs after the card's
    # name extract as they print.
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


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures",
                   "fidelity-credit-card-synthetic-sample.pdf")


def main():
    pages, new_balance = build_pages()
    build_pdf(pages, OUT)
    rows = len(PAYMENTS) + sum(map(len, PURCHASES.values())) + sum(map(len, OTHER_CREDITS.values()))
    print(f"wrote {OUT}")
    print(f"  {rows} transactions, previous {money(PREVIOUS_BALANCE)}, new balance {money(new_balance)}")


if __name__ == "__main__":
    main()
