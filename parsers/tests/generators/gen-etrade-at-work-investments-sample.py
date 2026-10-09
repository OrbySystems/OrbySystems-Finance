#!/usr/bin/env python3
"""Generate a fictional E*TRADE at Work holdings/activity statement.

The CASH FLOW ACTIVITY BY DATE amounts and NET CREDITS/(DEBITS) are drawn
right-aligned in one Credits/(Debits) column, as a real statement prints
them: the Statement Scrambler finds a total's rows by that column, and
keeps NET = the rows only when they line up. The page text pdfplumber
reads is the same either way.
"""

import re
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "etrade-at-work-investments-synthetic-202608.pdf"
PAGE_W, PAGE_H = 792, 612
# The right edge of the Credits/(Debits) column.
AMOUNT_RIGHT = 520.0
# A cash-flow row ("8/05 Deposit ... $500.00") or the NET line: the label,
# then the amount that goes in the column.
_COLUMN_AMOUNT_RE = re.compile(
    r"^(?P<label>\d{1,2}/\d{2} .*?|NET CREDITS/\(DEBITS\)) (?P<amount>\$\(?[\d,]+\.\d{2}\)?)$"
)


def _escape(value: str) -> bytes:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def _text(x: str, y: int, value: str) -> bytes:
    return f"BT /F1 8 Tf 1 0 0 1 {x} {y} Tm (".encode() + _escape(value) + b") Tj ET\n"


def _pdf(pages: list[list[str]]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}

    def add(number: int, body: bytes) -> None:
        offsets[number] = len(out)
        out.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")

    page_objects = [4 + 2 * i for i in range(len(pages))]
    add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add(2, f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_objects)}] /Count {len(pages)} >>".encode())
    add(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, lines in enumerate(pages):
        page_no = page_objects[index]
        content_no = page_no + 1
        add(page_no, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_no} 0 R >>".encode())
        stream = bytearray()
        y = PAGE_H - 35
        for line in lines:
            column = _COLUMN_AMOUNT_RE.match(line)
            if column:
                amount = column.group("amount")
                stream.extend(_text("30", y, column.group("label")))
                x = AMOUNT_RIGHT - stringWidth(amount, "Helvetica", 8)
                stream.extend(_text(f"{x:.2f}", y, amount))
            else:
                stream.extend(_text("30", y, line))
            y -= 13
        add(content_no, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")
    xref = len(out)
    out.extend(f"xref\n0 {max(offsets) + 1}\n0000000000 65535 f \n".encode())
    for number in range(1, max(offsets) + 1):
        out.extend(f"{offsets[number]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {max(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


PAGES = [
    [
        "CLIENT STATEMENT For the Period August 1- August 31, 2026",
        "Morgan Stanley Smith Barney LLC. Member SIPC.",
        "Access Your Account Online At www.etrade.com",
        "E*TRADE is a business of Morgan Stanley.",
    ],
    [
        "CLIENT STATEMENT For the Period August 1- August 31, 2026",
        "Account Summary 999-111111-2468 TEST ACCOUNT",
        "CHANGE IN VALUE OF YOUR ACCOUNT",
        "TOTAL BEGINNING VALUE $10,000.00 $9,000.00",
        "Credits $500.00 $1,500.00",
        "Debits $(200.00) $(500.00)",
        "Security Transfers -- --",
        "Net Credits/Debits/Transfers $300.00 $1,000.00",
        "Change in Value $700.00 $1,000.00",
        "TOTAL ENDING VALUE $11,000.00 $11,000.00",
    ],
    [
        "CLIENT STATEMENT For the Period August 1- August 31, 2026",
        "Account Detail 999-111111-2468 TEST ACCOUNT",
        "HOLDINGS",
        "MORGAN STANLEY PRIVATE BANK NA $1,000.00 -- -- 0.010",
        "STOCKS",
        "ACME CORPORATION ACM 10.000 $500.00 $4,000.00 $5,000.00 $1,000.00",
        "EXCHANGE-TRADED & CLOSED-END FUNDS",
        "SAMPLE INDEX FUND SIF 20.000 $250.00 $4,500.00 $5,000.00 $500.00",
        "TOTAL VALUE 100.00% $9,500.00 $11,000.00 $1,500.00",
        "ACTIVITY",
        "CASH FLOW ACTIVITY BY DATE",
        "Activity Settlement",
        "Date Date Activity Type Description Comments Quantity Price Credits/(Debits)",
        "8/05 Deposit EXTERNAL CASH CONTRIBUTION $500.00",
        "8/10 Withdrawal CASH DISTRIBUTION $(200.00)",
        "8/28 Qualified Dividend ACM ACME CORPORATION $100.00",
        "NET CREDITS/(DEBITS) $400.00",
        "MONEY MARKET FUND (MMF) AND BANK DEPOSIT PROGRAM ACTIVITY",
    ],
]

OUT.write_bytes(_pdf(PAGES))
print(OUT)
