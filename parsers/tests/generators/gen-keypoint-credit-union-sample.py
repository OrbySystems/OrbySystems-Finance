#!/usr/bin/env python3
"""Generate a wholly invented KeyPoint Credit Union statement of account: a
checking account with cleared checks and a service charge, a savings account
carried on to the next page, and a club account, each under its summary of
labels over figures, opening on a balance line. Every figure adds up.

A second copy has its labels' words run together ("StartDate:",
"AccountNo.12345678", "PostDate TransactionDescription"), as the scrambled
sample's text, and maybe the statement's own, has them.

A third statement is a trust's, in the layout of a second scrambled sample:
KeyPoint named only by its web address, the trust's address block run into
the lines of an IMPORTANT MESSAGES block beside it, a checking account fed
by transfers from a money market savings account that is paid interest, that
account's column header carried on to the next page with no rows under it
before its dividend lines, and a savings account with no activity."""

from pathlib import Path

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 9
LINE_H = 13
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "keypoint-credit-union-synthetic-sample.pdf"
RUN_TOGETHER_OUT = Path(__file__).resolve().parent.parent / "fixtures" / "keypoint-credit-union-run-together-synthetic-sample.pdf"
TRUST_OUT = Path(__file__).resolve().parent.parent / "fixtures" / "keypoint-credit-union-trust-synthetic-sample.pdf"

SUMMARY_LABELS = [
    "Beginning Dividend Service Ending",
    "Balance + Deposits + Paid - Withdrawals - Charges = Balance",
]
COLUMNS = "Post Date Transaction Description Withdrawal Deposit Balance"


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
        "1 of 2",
        "Statement of Account",
        "PAT EXAMPLE",
        "100 SAMPLE STREET",
        "SAMPLE CITY CA 95000",
        "Start Date: 12/01/2026",
        "End Date: 12/31/2026",
        "Questions? Visit any KeyPoint branch or call (800) 555-0100.",
        "FREE CHECKING Account No. 12345678",
        *SUMMARY_LABELS,
        "$1,200.00 $2,500.00 $0.00 $1,946.30 $5.00 $1,748.70",
        COLUMNS,
        "12/01 Beginning Balance 1,200.00",
        "12/02 Check 1001 150.00 1,050.00",
        "12/05 ACH Deposit SAMPLE EMPLOYER PAYROLL 2,500.00 3,550.00",
        "12/09 Transfer To Share *0001 1,000.00 2,550.00",
        "12/15 POS Purchase SAMPLE GROCERY 96.30 2,453.70",
        "12/20 Check 1002 700.00 1,753.70",
        "12/31 Monthly Service Charge 5.00 1,748.70",
        "Summary of Overdraft and Returned Item Fees",
        "Total For This Period Total Year-To-Date",
        "Total Overdraft Fees $0.00 $0.00",
        "Total Returned Item Fees $0.00 $0.00",
        "CHECKS CLEARED",
        "Check# Date Amount Check# Date Amount",
        "1001 12/02 150.00 1002 12/20 700.00",
        "REGULAR SAVINGS Account No. 12340001",
        "Dividend Rate 0.250% Dividends Year-To-Date: $3.10",
        *SUMMARY_LABELS,
        "$5,000.00 $1,000.00 $1.05 $250.00 $0.00 $5,751.05",
        COLUMNS,
        "12/01 Beginning Balance 5,000.00",
        "12/09 Transfer From Share *5678 1,000.00 6,000.00",
    ],
    [
        "12/01/2026",
        "12/31/2026",
        "2 of 2",
        COLUMNS,
        "12/18 Withdrawal Transfer To SAMPLE BANK 250.00 5,750.00",
        "12/31 Credit Dividend 1.05 5,751.05",
        "The Annual Percentage Yield Earned for this account is 0.25%.",
        "HOLIDAY CLUB Account No. 12340009",
        "Dividend Rate 0.100% Dividends Year-To-Date: $0.20",
        *SUMMARY_LABELS,
        "$300.00 $50.00 $0.03 $0.00 $0.00 $350.03",
        COLUMNS,
        "12/01 Beginning Balance 300.00",
        "12/15 ACH Deposit SAMPLE BANK 50.00 350.00",
        "12/31 Credit Dividend 0.03 350.03",
        "The Annual Percentage Yield Earned for this account is 0.10%.",
        "Federally insured by NCUA",
    ],
]

OUT.write_bytes(build_pdf(pages))
print(OUT)

RUN_TOGETHER = [("Start Date:", "StartDate:"), ("End Date:", "EndDate:"), ("Account No. ", "AccountNo."),
                ("Post Date", "PostDate"), ("Transaction Description", "TransactionDescription"),
                ("Beginning Balance", "BeginningBalance"), ("Credit Dividend", "CreditDividend")]


def run_together(line: str) -> str:
    for spaced, joined in RUN_TOGETHER:
        line = line.replace(spaced, joined)
    return line


RUN_TOGETHER_OUT.write_bytes(build_pdf([[run_together(line) for line in page] for page in pages]))
print(RUN_TOGETHER_OUT)


def dividend_lines(earned: str, average: str, minimum: str, apy: str) -> list[str]:
    return [
        f"The amount of Dividend earned between 12-01-2026 and 12-31-2026 is ${earned}.",
        f"The average daily balance during this period was ${average}.",
        f"The minimum balance during this period was ${minimum}.",
        f"The Annual Percentage Yield Earned for this account is {apy}%.",
    ]


trust_pages = [
    [
        "1 of 2",
        "Statement of Account",
        "100 Sample Plaza, Suite 200",
        "Sample City, CA 95000",
        "Start Date: 12/01/2026",
        "End Date: 12/31/2026",
        "kpcu.com | (800) 555-0100",
        "IMPORTANT MESSAGES",
        "Holiday Hours: Sample branches",
        "PAT EXAMPLE TRUSTEE close at 2 p.m. on December 24 and stay closed",
        "SAM EXAMPLE TRUSTEE on December 25 and January 1. Online banking",
        "EXAMPLE FAMILY TRUST DTD 03/15/99 stays open, apart from upkeep (2 a.m. to",
        "200 SAMPLE LANE 4 a.m. on January 2). Questions? Write to",
        "SAMPLE CITY CA 95000 sample-notices@kpcu.com.",
        "PREFERRED CHECKING Account No. 12345670",
        *SUMMARY_LABELS,
        "$210.00 $900.00 $0.00 $650.00 $0.00 $460.00",
        COLUMNS,
        "12/01 Beginning Balance 210.00",
        "12/01 Deposit Transfer From *0002; REF # 1000001 200.00 410.00",
        "12/12 Check 2001 325.00 85.00",
        "12/15 Deposit Transfer From *0002; REF # 1000002 400.00 485.00",
        "12/26 Check 2002 325.00 160.00",
        "12/29 Deposit Transfer From *0002; REF # 1000003 300.00 460.00",
        "Summary of Overdraft and Returned Item Fees",
        "Total For This Period Total Year-To-Date",
        "Total Overdraft Fees $0.00 $0.00",
        "Total Returned Item Fees $0.00 $0.00",
        "CLEARED CHECKS",
        "Check# Date Amount Check# Date Amount",
        "2001 12/12 325.00 2002 12/26 325.00",
        "MONEY MARKET SAVINGS Account No. 12340002",
        "Dividend Rate 0.050% Dividend Paid YTD: $20.40",
        *SUMMARY_LABELS,
        "$5,000.00 $0.00 $1.95 $900.00 $0.00 $4,101.95",
        COLUMNS,
        "12/01 Beginning Balance 5,000.00",
        "12/01 Withdrawal Transfer To *5670; REF # 1000001 200.00 4,800.00",
        "12/15 Withdrawal Transfer To *5670; REF # 1000002 400.00 4,400.00",
        "12/29 Withdrawal Transfer To *5670; REF # 1000003 300.00 4,100.00",
        "12/31 Credit Interest 1.95 4,101.95",
    ],
    [
        "12/01/2026",
        "12/31/2026",
        "2 of 2",
        COLUMNS,
        *dividend_lines("1.95", "4,452.03", "4,100.00", "0.050"),
        "REGULAR SAVINGS Account No. 12340003",
        "Dividend Rate 0.050% Dividend Paid YTD: $0.00",
        *SUMMARY_LABELS,
        "$300.00 $0.00 $0.00 $0.00 $0.00 $300.00",
        COLUMNS,
        "12/01 Beginning Balance 300.00",
        *dividend_lines("0.00", "300.00", "300.00", "0.000"),
        "Federally insured by NCUA",
    ],
]

TRUST_OUT.write_bytes(build_pdf(trust_pages))
print(TRUST_OUT)
