#!/usr/bin/env python3
"""Generates tests/fixtures/icici-bank-synthetic-sample.pdf, the demo
statement behind tests/test_icici_bank_statement.py.

Every name, number and figure here is invented, so the fixture can live in
git. The layout follows a real ICICI Bank statement's, as a scrambled sample
of one showed it (7 Nov 2026). The real statement comes password-protected;
this one doesn't, and tests/test_password_protected.py covers locked PDFs.
  - page 1:
    - "Summary of Accounts held under Cust ID: ... as on <date>";
    - a line per account ("Savings - NRE A/c <number> <balance> 0.00
      <balance> Registered") and their TOTAL;
    - the first account's transactions under "Statement of Transactions in
      Savings Account Number: <number> in INR for the period <date> -
      <date>" and the column header "DATE MODE** PARTICULARS DEPOSITS
      WITHDRAWALS BALANCE";
  - the balance brought forward ("DD-MM-YYYY B/F <balance>"), then one line
    a transaction (date, particulars, amount, balance after it), its
    particulars running on to the next line when long;
  - amounts in Indian digit grouping ("1,52,410.25");
  - the first account's transactions carrying on to page 2 under the
    repeated column header, then its TOTAL, and the second account's;
  - the particulars of an interest credit naming the account's own number;
  - the TDS and interest summary, the account information table, and a
    page of definitions.
"""

import os
from decimal import Decimal as D

PAGE_W, PAGE_H, FONT, LEAD = 595, 842, 7, 11
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "icici-bank-synthetic-sample.pdf")

NRE, NRO = "000101234567", "000105556677"
PERIOD = "August 07, 2026 - November 07, 2026"
# Each account: (type, number, brought forward, rows on page 1, rows on page 2).
# A row: (date, particulars lines, amount (+ deposit, - withdrawal)).
ACCOUNTS = [
    ("NRE", NRE, D("140000.00"), [
        ("12-08-2026", ["UPI/622512345678/Grocery/rahul.k@okaxis/UPI"], D("-1250.00")),
        ("20-08-2026", ["NEFT-HDFCN52026082011223344-ACME SOFTWARE", "PVT LTD-SALARY AUGUST 2026"], D("85000.00")),
        ("05-09-2026", ["ATM/CASH WDL/05-09-26/MUMBAI ANDHERI W"], D("-10000.00")),
        ("11-09-2026", ["IMPS/P2A/625411223344/PRIYA S/HDFC0001234"], D("-25000.00")),
    ], [
        ("18-09-2026", ["BIL/ONL/000987654321/ELECTRICITY BOARD/MSEDCL"], D("-3412.50")),
        ("30-09-2026", [f"{NRE}:Int.Pd:30-06-2026 to 29-09-2026"], D("1410.25")),
        ("02-10-2026", ["UPI/627512349876/Rent October/landlord@icici/UPI"], D("-35000.00")),
    ]),
    ("NRO", NRO, D("18282.63"), [
        ("30-09-2026", [f"{NRO}:TDS.Pd:30-06-2026 to 29-09-2026"], D("-38.13")),
        ("30-09-2026", [f"{NRO}:Int.Pd:30-06-2026 to 29-09-2026"], D("718.67")),
    ], []),
]


def inr(x: D) -> str:
    """Indian digit grouping: 1,52,410.25."""
    sign = "-" if x < 0 else ""
    whole, cents = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{cents}"


def closing(account) -> D:
    _, _, opening, first, second = account
    return opening + sum(r[2] for r in first + second)


def deposits(account) -> D:
    return sum(r[2] for r in account[3] + account[4] if r[2] > 0)


def withdrawals(account) -> D:
    return -sum(r[2] for r in account[3] + account[4] if r[2] < 0)


def esc(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("cp1252")


def build_pdf(pages, path):
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
    for i, lines in enumerate(pages):
        stream = bytearray()
        y = PAGE_H - 36
        for s in lines:
            if s:
                stream.extend(f"BT /F1 {FONT} Tf 1 0 0 1 30 {y} Tm (".encode())
                stream.extend(esc(s))
                stream.extend(b") Tj ET\n")
            y -= LEAD
        obj(nums[i], (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
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


HEADER = "DATE MODE** PARTICULARS DEPOSITS WITHDRAWALS BALANCE"


def rows(balance: D, rows_):
    lines = []
    for day, particulars, amount in rows_:
        balance += amount
        lines.append(f"{day} {particulars[0]} {inr(abs(amount))} {inr(balance)}")
        lines += particulars[1:]
    return lines, balance


def section(account):
    """An account's heading, the column header, and its balance brought forward."""
    return [f"Statement of Transactions in Savings Account Number: {account[1]} in INR for the period {PERIOD}",
            HEADER, f"07-08-2026 B/F {inr(account[2])}"]


def build_pages():
    nre, nro = ACCOUNTS
    page1 = [
        "Page 1 of 3",
        "MR.ALEX MORGAN Your Base Branch: ICICI BANK LTD., 2/1, EXAMPLE ROAD",
        "ANDHERI WEST, MUMBAI, 400058",
        "Visit www.icicibank.com",
        "Summary of Accounts held under Cust ID: 900000001 as on November 07, 2026",
        "ACCOUNT DETAILS - INR",
        "ACCOUNT TYPE A/c BALANCE(A) FIXED DEPOSITS (LINKED) BAL.(B) TOTAL BALANCE(A+B) NOMINATION",
        f"Savings - NRE A/c {NRE} {inr(closing(nre))} 0.00 {inr(closing(nre))} Registered",
        f"Savings - NRO A/c {NRO} {inr(closing(nro))} 0.00 {inr(closing(nro))} Registered",
        f"TOTAL {inr(closing(nre) + closing(nro))} 0.00 {inr(closing(nre) + closing(nro))}",
    ]
    page1 += section(nre)
    lines, balance = rows(nre[2], nre[3])
    page1 += lines
    page2 = ["Page 2 of 3", HEADER]
    lines, balance = rows(balance, nre[4])
    page2 += lines + [f"TOTAL {inr(deposits(nre))} {inr(withdrawals(nre))} {inr(balance)}"]
    page2 += section(nro)
    lines, balance = rows(nro[2], nro[3])
    page2 += lines + [f"TOTAL {inr(deposits(nro))} {inr(withdrawals(nro))} {inr(balance)}"]
    page2 += [
        "Summary of TDS/Interest on Fixed Deposits during the Period " + PERIOD,
        "Opening Balance 167.11 82.03",
        f"{NRE} 30-09-2026 1,410.25 0.00",
        f"{NRO} 30-09-2026 718.67 38.13",
        "Closing Balance 2,296.03 120.16",
        "Account Related Other Information",
        "ACCOUNT TYPE ACCOUNT NUMBER MICR CODE IFSC CODE NAME OF NOMINEE NAME OF JOINT HOLDER",
        f"Savings - NRE {NRE} 400229001 ICIC0000001 - -",
        f"Savings - NRO {NRO} 400229001 ICIC0000001 - -",
    ]
    page3 = [
        "Page 3 of 3",
        "Dear Customer,",
        "Thank you for banking with ICICI Bank.",
        "Legends for transactions in your account statement",
        "VAT/MAT/NFS - Cash Withdrawal at other bank's ATM INF - Internet funds transfer in linked accounts",
        "UPI - Unified Payments Interface IMPS - Immediate Payment Service",
        "This is a system-generated statement. Hence, it does not require any signature.",
    ]
    return [page1, page2, page3]


def main():
    build_pdf(build_pages(), OUT)
    print(f"wrote {OUT}")
    for account in ACCOUNTS:
        n = len(account[3]) + len(account[4])
        print(f"  {account[0]} {account[1][-4:]}: {n} rows, closing {closing(account)}")


if __name__ == "__main__":
    main()
