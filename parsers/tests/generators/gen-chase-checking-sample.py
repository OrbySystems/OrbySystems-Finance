#!/usr/bin/env python3
"""Generate a wholly invented Chase checking and savings statement: a balance
summary of both accounts, a checking account whose heading prints no number
(the balance summary has it), its transaction detail carried on to the next
page with a description continued on the line below, and a savings account
paying interest. Every figure adds up.

Also the same statement as a later layout prints it (MARKER_RUN_IN_OUT):
the marker that closes the first page's part of the checking detail is read
run into that page's last row, the row's first digit among the marker's
letters, and the detail goes on under "(continued)" on a line of its own."""

from pathlib import Path

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 9
LINE_H = 13
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "chase-checking-synthetic-sample.pdf"
MARKER_RUN_IN_OUT = Path(__file__).resolve().parent.parent / "fixtures" / "chase-checking-marker-run-in-synthetic-sample.pdf"

PERIOD = "October 01, 2026 through October 31, 2026"
COLUMNS = "DATE DESCRIPTION AMOUNT BALANCE"
# Chase prints its markers ("*end*transaction detail") so small that the
# text can read one beside a row run into it, the row's first digit among
# the marker's letters: "*end*transact1iondetail 0/15 ATM ...". A (marker,
# split, line) entry draws the marker that way: at MARKER_SCALE percent of
# its letters' width, its first split letters just left of the line and the
# rest over the line's first digit.
MARKER_SCALE = 5
MARKER_X = (36.5, 40.2)


def escape(value: str) -> bytes:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def build_pdf(pages: list[list[str | tuple[str, int, str]]]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    def add(number: int, body: bytes):
        offsets[number] = len(out)
        out.extend(f"{number} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    page_objects = [4 + 2 * index for index in range(len(pages))]
    add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add(2, f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_objects)}] /Count {len(pages)} >>".encode())
    add(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, lines in enumerate(pages):
        page_number = page_objects[index]
        content_number = page_number + 1
        add(page_number, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>"
        ).encode())
        stream = bytearray()
        y = PAGE_H - 45
        for line in lines:
            marker = None
            if isinstance(line, tuple):
                marker, split, line = line
            stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 40 {y} Tm (".encode())
            stream.extend(escape(line))
            stream.extend(b") Tj ET\n")
            if marker:
                for x, part in zip(MARKER_X, (marker[:split], marker[split:])):
                    # q/Q: the narrow letters' scale must not reach the next line.
                    stream.extend(f"q BT /F1 {FONT_SIZE} Tf {MARKER_SCALE} Tz 1 0 0 1 {x} {y} Tm (".encode())
                    stream.extend(escape(part))
                    stream.extend(b") Tj ET Q\n")
            y -= LINE_H
        add(content_number, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")

    xref = len(out)
    out.extend(f"xref\n0 {max(offsets) + 1}\n0000000000 65535 f \n".encode())
    for number in range(1, max(offsets) + 1):
        out.extend(f"{offsets[number]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {max(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


pages = [
    [
        PERIOD,
        "JPMorgan Chase Bank, N.A.",
        "P O Box 100000",
        "Sample City, OH 43000 - 0000",
        "Web site: Chase.com",
        "PAT EXAMPLE",
        "100 SAMPLE STREET",
        "SAMPLE CITY CA 95000",
        "*start*summary",
        "CONSOLIDATED BALANCE SUMMARY",
        "Checking & Savings ACCOUNT BEGINNING BALANCE ENDING BALANCE",
        "THIS PERIOD THIS PERIOD",
        "Chase Total Checking 000000001234567 $1,200.00 $2,045.10",
        "Chase Savings 000000007654321 5,000.00 5,401.25",
        "Total $6,200.00 $7,446.35",
        "*end*summary",
        "*start*summary",
        "CHASE TOTAL CHECKING",
        "PAT EXAMPLE Account Number:",
        "CHECKING SUMMARY",
        "AMOUNT",
        "Beginning Balance $1,200.00",
        "Deposits and Additions 2,500.00",
        "ATM & Debit Card Withdrawals -154.90",
        "Electronic Withdrawals -1,500.00",
        "Ending Balance $2,045.10",
        "*end*summary",
        "*start*transaction detail",
        "TRANSACTION DETAIL",
        COLUMNS,
        "Beginning Balance $1,200.00",
        "10/03 Card Purchase 10/02 Sample Grocery Sample City CA Card 1234 -54.90 1,145.10",
        "10/05 Payroll Deposit SAMPLE EMPLOYER PPD ID: 0000000000 2,500.00 3,645.10",
        "10/09 10/08 Online Transfer To Sav ...4321 Transaction#: 1111111111 -1,000.00 2,645.10",
        "10/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10",
        "Page 1 of 2",
    ],
    [
        PERIOD,
        "Primary Account: 000000001234567",
        "TRANSACTION DETAIL (continued)",
        COLUMNS,
        "10/20 10/20 Online Payment 2222222222 To Sample Utility -500.00 2,045.10",
        "Transaction#: 3333333333 Reference#: 4444444444",
        "Ending Balance $2,045.10",
        "*end*transaction detail",
        "*start*summary",
        "CHASE SAVINGS",
        "PAT EXAMPLE Account Number: 000000007654321",
        "SAVINGS SUMMARY",
        "AMOUNT",
        "Beginning Balance $5,000.00",
        "Deposits and Additions 1,001.25",
        "Electronic Withdrawals -600.00",
        "Ending Balance $5,401.25",
        "Annual Percentage Yield Earned This Period 0.01%",
        "Interest Paid This Period $1.25",
        "Interest Paid Year-to-Date $9.80",
        "*end*summary",
        "*start*transaction detail",
        "TRANSACTION DETAIL",
        COLUMNS,
        "Beginning Balance $5,000.00",
        "10/09 Online Transfer From Chk ...4567 Transaction#: 1111111111 1,000.00 6,000.00",
        "10/25 10/24 Online Transfer To Sample Bank Transfer 5555 -600.00 5,400.00",
        "10/31 Interest Payment 1.25 5,401.25",
        "Ending Balance $5,401.25",
        "*end*transaction detail",
        "JPMorgan Chase Bank, N.A. Member FDIC",
        "Page 2 of 2",
    ],
]

OUT.write_bytes(build_pdf(pages))
print(OUT)

marker_run_in = [list(page) for page in pages]
last_row = marker_run_in[0].index("10/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10")
marker_run_in[0][last_row] = ("*end*transactiondetail", len("*end*transact"), marker_run_in[0][last_row])
continued = marker_run_in[1].index("TRANSACTION DETAIL (continued)")
marker_run_in[1][continued:continued + 1] = ["*start*transaction detail", "(continued)", "TRANSACTION DETAIL"]
MARKER_RUN_IN_OUT.write_bytes(build_pdf(marker_run_in))
print(MARKER_RUN_IN_OUT)
