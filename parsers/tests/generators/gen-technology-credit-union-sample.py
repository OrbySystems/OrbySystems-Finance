#!/usr/bin/env python3
"""Generate a wholly invented Technology Credit Union member statement: a
savings account and a checking account, each opening on its Starting
Balance and closing on its Ending Balance and Summary line, with deposits,
withdrawals printed negative, and a description continued on the line below.
Every figure adds up."""

from pathlib import Path

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 9
LINE_H = 13
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "technology-credit-union-synthetic-sample.pdf"


def escape(value: str) -> bytes:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def build_pdf(pages: list[list[str]]) -> bytes:
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
            stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 40 {y} Tm (".encode())
            stream.extend(escape(line))
            stream.extend(b") Tj ET\n")
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
        "Member Number: 123456",
        "Statement Date: 09/30/2026",
        "Page: 1 of 1",
        "PAT EXAMPLE",
        "100 SAMPLE STREET",
        "SAMPLE CITY CA 95000-0000",
        "When receiving direct deposits, ACH payments, and incoming wire transfers, use our Routing Number (RTN): 000000000",
        "Savings",
        "Date Transaction Description Amount Balance",
        "SHARE SAVINGS 1234567890123",
        "09/01 Starting Balance $1,529.17",
        "09/15 Withdrawal Transfer to Checking -200.00 1,329.17",
        "09/30 Deposit Dividend 0.150% 2.44 1,331.61",
        "Annual % Yield Earned Ending 09/30/2026 : 0.15%",
        "09/30 Ending Balance for SHARE SAVINGS $1,331.61",
        "Summary: 1 Deposit : $2.44 1 Withdrawal : $200.00 YTD Dividends Paid : $6.80",
        "Checking",
        "Date Transaction Description Amount Balance",
        "INTEREST CHECKING 9876543210987",
        "09/01 Starting Balance $3,072.66",
        "09/03 Withdrawal POS SAMPLE GROCERY -61.20 3,011.46",
        "SAMPLE CITY CA",
        "09/15 Deposit Transfer from Savings 200.00 3,211.46",
        "09/20 Withdrawal ACH SAMPLE UTILITY -88.35 3,123.11",
        "09/30 Deposit Dividend 0.050% 0.13 3,123.24",
        "Annual % Yield Earned Ending 09/30/2026 : 0.05%",
        "09/30 Ending Balance for INTEREST CHECKING $3,123.24",
        "Summary: 2 Deposits : $200.13 2 Withdrawals : $149.55 YTD Dividends Paid : $1.12",
        "Total Dividends Paid : $7.92",
        "www.techcu.com",
    ],
]

OUT.write_bytes(build_pdf(pages))
print(OUT)
