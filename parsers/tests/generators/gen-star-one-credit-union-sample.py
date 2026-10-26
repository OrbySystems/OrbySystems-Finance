#!/usr/bin/env python3
"""Generate a wholly invented Star One Credit Union member statement: a
savings account and a checking account, the checking account carried on to
a second page under its repeated page header, with deposits, withdrawals and
a description continued on the line below. Every figure adds up."""

from pathlib import Path

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 9
LINE_H = 13
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "star-one-credit-union-synthetic-sample.pdf"


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
        "Star One Credit Union",
        "Member No. Period Ending Page",
        "123456789 09/30/26 1 of 2",
        "ACCOUNT SUMMARY",
        "service@starone.org - www.starone.org 1 REGULAR SAVINGS ACCOUNT $ 1,206.68",
        "P.O. Box 3643 - Sample City, CA 94088-3643 7 CHECKING ACCOUNT $ 2,468.13",
        "PAT EXAMPLE",
        "100 SAMPLE STREET",
        "SAMPLE CITY CA 95000-0000",
        "REGULAR SAVINGS ACCOUNT ACCT# 1",
        "Beginning Balance Deposits/Credits Withdrawals/Debits Ending Balance YTD Dividends",
        "$ 1,204.17 $ 2.51 $ 0.00 $ 1,206.68 $ 18.40",
        "Date Transaction Description Deposit Withdrawal Balance",
        "SEP30 DIVIDEND 2.51 1,206.68",
        "ANNUAL PERCENTAGE YIELD EARNED FROM 09/01/26 THRU 09/30/26",
        "WAS 2.50%",
        "CHECKING ACCOUNT ACCT# 7",
        "Beginning Balance Deposits/Credits Withdrawals/Debits Ending Balance YTD Dividends",
        "$ 1,530.00 $ 2,600.15 $ 1,662.02 $ 2,468.13 $ 0.41",
        "Date Transaction Description Deposit Withdrawal Balance",
        "SEP02 POS DEBIT SAMPLE GROCERY 42.18 1,487.82",
        "SAMPLE CITY CA",
        "SEP05 ACH CREDIT SAMPLE EMPLOYER PAYROLL 1,300.00 2,787.82",
    ],
    [
        "Member No. Period Ending Page",
        "123456789 09/30/26 2 of 2",
        "CHECKING ACCOUNT ACCT# 7",
        "Date Transaction Description Deposit Withdrawal Balance",
        "SEP15 WITHDRAWAL TRANSFER TO SAMPLE BANK 500.00 2,287.82",
        "SEP19 CHECK 1042 119.84 2,167.98",
        "SEP30 ACH CREDIT SAMPLE EMPLOYER PAYROLL 1,300.00 3,467.98",
        "SEP30 ACH DEBIT SAMPLE CARD PAYMENT 1,000.00 2,467.98",
        "SEP30 DIVIDEND 0.15 2,468.13",
        "ANNUAL PERCENTAGE YIELD EARNED FROM 09/01/26 THRU 09/30/26",
        "WAS 0.05%",
        "YTD ACCOUNT SUMMARY",
        "Deposit Account Totals",
        "YTD Total Dividends: $ 18.81",
        "September 2026 October 2026",
        "Account Type Rate APY Rate APY",
        "Regular Savings 2.47% 2.50% 2.47% 2.50%",
        "Free Checking 0.05% 0.05% 0.05% 0.05%",
    ],
]

OUT.write_bytes(build_pdf(pages))
print(OUT)
