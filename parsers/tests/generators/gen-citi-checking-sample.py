#!/usr/bin/env python3
"""Generate a wholly invented Citi checking-statement fixture."""

from pathlib import Path


PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 9
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "citi-checking-synthetic-sample.pdf"
LINES = [
    "September 1 - September 30, 2026",
    "Citi Test Account ending in 4321",
    "Value of Accounts Summary",
    "Checking",
    "Everyday Checking 0000004321",
    "Activity",
    "Date Description Amount Subtracted Amount Added Balance",
    "09/01/26 Opening Balance 1,000.00",
    "09/02/26 SAMPLE PAYROLL 500.00 1,500.00",
    "09/03/26 SAMPLE RENT 600.00 900.00",
    "09/04/26 SAMPLE MARKET 40.00 860.00",
    "09/05/26 SAMPLE REFUND 10.00 870.00",
    "09/06/26 SAMPLE TRANSFER 70.00 800.00",
    "REFERENCE TEXT",
    "Total Subtracted/Added 710.00 510.00",
    "09/30/26 Closing Balance 800.00",
]


def escape(value: str) -> bytes:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def build_pdf(lines: list[str]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    def add(number: int, body: bytes) -> None:
        offsets[number] = len(out)
        out.extend(f"{number} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add(2, b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>")
    add(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    add(4, (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
        f"/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>"
    ).encode())
    stream = bytearray()
    y = PAGE_H - 45
    for line in lines:
        stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 40 {y} Tm (".encode())
        stream.extend(escape(line))
        stream.extend(b") Tj ET\n")
        y -= 13
    add(5, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")

    xref = len(out)
    out.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for number in range(1, 6):
        out.extend(f"{offsets[number]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


OUT.write_bytes(build_pdf(LINES))
print(OUT)
