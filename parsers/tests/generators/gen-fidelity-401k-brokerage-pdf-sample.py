#!/usr/bin/env python3
"""Generate a wholly synthetic Fidelity NetBenefits 401(k) statement.

The parser is line-oriented, so this PDF keeps the same extracted labels,
section names, and table shapes as the real NetBenefits statement while
using invented names, dates, account numbers, and amounts.
"""

from __future__ import annotations

import argparse
import os

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 8
LINE_H = 12
X = 36
OUT_NAME = "fidelity-401k-brokerage-pdf-synthetic-sample.pdf"
ZERO_OMITTED_OUT_NAME = "fidelity-401k-zero-omitted-synthetic-sample.pdf"
GENERIC_EXCHANGE_OUT_NAME = "fidelity-401k-generic-exchange-synthetic-sample.pdf"


LINES = [
    "Fidelity NetBenefits",
    "Retirement Savings Statement",
    "Statement Period: 04/01/2026 to 06/30/2026",
    "Account Number: XQ-0000-2468",
    "",
    "Account Activity",
    "Beginning Balance $10,000.00",
    "Exchange In $500.00",
    "Exchange Out -$250.00",
    "Revenue Credit $12.34",
    "Change In Market Value $125.66",
    "Ending Balance $10,388.00",
    "Dividends & Interest $42.50",
    "",
    "Your Account Activity",
    "Statement Period: 04/01/2026 to 06/30/2026",
    "Use this section as a summary of transactions that occurred in your account during the statement period.",
    [(248, "Synthetic"), (332, "Blue"), (420, "Total")],
    [(144, "Activity")],
    [(248, "Growth"), (332, "Horizon")],
    [(248, "Index"), (332, "Bond")],
    [(144, "Beginning Balance"), (248, "$5,000.00"), (332, "$5,000.00"), (420, "$10,000.00")],
    [(146, "Exchange In"), (248, "$500.00"), (332, "$0.00"), (420, "$500.00")],
    [(146, "Exchange Out"), (248, "$0.00"), (332, "-$250.00"), (420, "-$250.00")],
    [(146, "Revenue Credit"), (248, "$10.00"), (332, "$2.34"), (420, "$12.34")],
    [(146, "Change In Market Value"), (248, "$100.00"), (332, "$25.66"), (420, "$125.66")],
    [(144, "Ending Balance"), (248, "$5,610.00"), (332, "$4,778.00"), (420, "$10,388.00")],
    [(146, "Dividends & Interest"), (248, "$30.00"), (332, "$12.50"), (420, "$42.50")],
    "Revenue Credit represents your share of a pricing credit from Fidelity Investments.",
    "",
    "Market Value of Your Account",
    "Investment as of 04/01/2026 Investment as of 06/30/2026",
    "Shares/Units Beginning Ending Price as of 04/01/2026 Price as of 06/30/2026 Market Value Beginning Market Value Ending",
    "INDEX FUNDS (PASSIVELY MANAGED)",
    "Synthetic Growth Index Fund 50.000 60.000 $100.00 $101.25 $5,000.00 $6,075.00",
    "Bond",
    "Blue Horizon Bond Pool 20.000 20.000 $120.00 $124.40 $2,400.00 $2,488.00",
    "Income",
    "Stable Value Income Fd 2,500.000 1,825.000 $1.00 $1.00 $2,500.00 $1,825.00",
    "Account Totals $9,900.00 $10,388.00",
    "",
    "Detailed Transaction History",
    "This synthetic statement intentionally prints only statement-period activity summaries.",
]


# NetBenefits suppresses activity rows when their value is zero. This variant
# mirrors that documented shape with Exchange In and Exchange Out absent while
# retaining fictional names, dates, and amounts throughout.
ZERO_OMITTED_LINES = [
    "Fidelity NetBenefits",
    "Retirement Savings Statement",
    "Statement Period: 01/01/2026 to 09/17/2026",
    "",
    "Your Account Summary",
    "Beginning Balance $10,000.00",
    "Revenue Credit $60.84",
    "Change In Market Value $939.16",
    "Ending Balance $11,000.00",
    "Dividends & Interest $100.00",
    "",
    "Market Value of Your Account",
    "Investment as of 12/31/2025 Investment as of 09/17/2026",
    "Shares/Units Beginning Ending Price as of 12/31/2025 Price as of 09/17/2026 Market Value Beginning Market Value Ending",
    "INDEX FUNDS (PASSIVELY MANAGED)",
    "Synthetic Growth Index Fund 60.000 60.000 $100.00 $110.00 $6,000.00 $6,600.00",
    "Bond",
    "Blue Horizon Bond Pool 40.000 40.000 $100.00 $110.00 $4,000.00 $4,400.00",
    "Account Totals $10,000.00 $11,000.00",
    "",
    "Your Contribution Summary",
    "Pre-Tax Contributions $0.00 100% $7,000.00 $7,000.00",
    "",
    "Your Account Activity",
    "Statement Period: 01/01/2026 to 09/17/2026",
    "Use this section as a summary of transactions that occurred in your account during the statement period.",
    [(248, "Synthetic"), (332, "Blue"), (420, "Total")],
    [(144, "Activity")],
    [(248, "Growth"), (332, "Horizon")],
    [(248, "Index"), (332, "Bond")],
    [(144, "Beginning Balance"), (248, "$6,000.00"), (332, "$4,000.00"), (420, "$10,000.00")],
    [(146, "Revenue Credit"), (248, "$40.00"), (332, "$20.84"), (420, "$60.84")],
    [(146, "Change In Market Value"), (248, "$560.00"), (332, "$379.16"), (420, "$939.16")],
    [(144, "Ending Balance"), (248, "$6,600.00"), (332, "$4,400.00"), (420, "$11,000.00")],
    [(146, "Dividends & Interest"), (248, "$60.00"), (332, "$40.00"), (420, "$100.00")],
    "Revenue Credit represents your share of a pricing credit from Fidelity Investments.",
    "",
    "Your Account Information",
    "This synthetic fixture intentionally omits zero-valued exchange rows.",
]


# Some NetBenefits plans combine fund-to-fund movements into one signed
# "Exchanges" row whose account-level total is zero. In this layout dividends
# are also a separate reconciliation component rather than being included in
# Change In Market Value.
GENERIC_EXCHANGE_LINES = [
    "Fidelity NetBenefits",
    "Retirement Savings Statement",
    "Statement Period: 07/01/2026 to 09/30/2026",
    "Account Number: SYN-0000-9753",
    "",
    "Your Account Summary",
    "Beginning Balance $10,000.00",
    "Exchanges $0.00",
    "Change In Market Value $200.00",
    "Ending Balance $10,250.00",
    "Dividend & Interest $50.00",
    "",
    "Market Value of Your Account",
    "Investment as of 06/30/2026 Investment as of 09/30/2026",
    "Shares/Units Beginning Ending Price as of 06/30/2026 Price as of 09/30/2026 Market Value Beginning Market Value Ending",
    "INDEX FUNDS (PASSIVELY MANAGED)",
    "Synthetic Growth Index Fund 40.000 36.000 $100.00 $100.00 $4,000.00 $3,600.00",
    "Bond",
    "Blue Horizon Bond Pool 35.000 37.850 $100.00 $100.00 $3,500.00 $3,785.00",
    "Income",
    "Stable Value Income Fd 25.000 28.650 $100.00 $100.00 $2,500.00 $2,865.00",
    "Account Totals $10,000.00 $10,250.00",
    "",
    "Your Contribution Summary",
    "Pre-Tax Contributions $0.00 100% $10,250.00 $10,250.00",
    "",
    "Your Account Activity",
    "Statement Period: 07/01/2026 to 09/30/2026",
    "Use this section as a summary of transactions that occurred in your account during the statement period.",
    [(220, "Synthetic"), (300, "Blue"), (380, "Stable"), (470, "Total")],
    [(120, "Activity")],
    [(220, "Growth"), (300, "Horizon"), (380, "Value")],
    [(220, "Index"), (300, "Bond")],
    [(120, "Beginning Balance"), (220, "$4,000.00"), (300, "$3,500.00"), (380, "$2,500.00"), (470, "$10,000.00")],
    [(120, "Exchanges"), (220, "-$500.00"), (300, "$200.00"), (380, "$300.00"), (470, "$0.00")],
    [(120, "Change In Market Value"), (220, "$80.00"), (300, "$70.00"), (380, "$50.00"), (470, "$200.00")],
    [(120, "Ending Balance"), (220, "$3,600.00"), (300, "$3,785.00"), (380, "$2,865.00"), (470, "$10,250.00")],
    [(120, "Dividend & Interest"), (220, "$20.00"), (300, "$15.00"), (380, "$15.00"), (470, "$50.00")],
    "Your Account Information",
    "This synthetic fixture uses a signed, zero-net Exchanges row.",
]


def escape(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1", "replace")


def draw_text(stream: bytearray, text: str, x: float, y: float) -> None:
    stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {x} {y:.2f} Tm (".encode())
    stream.extend(escape(text))
    stream.extend(b") Tj ET\n")


def build_pdf(lines: list, path: str) -> None:
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    def add_obj(num: int, body: bytes) -> None:
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add_obj(2, b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>")
    add_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    add_obj(
        4,
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            "/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>" % (PAGE_W, PAGE_H)
        ).encode(),
    )

    stream = bytearray()
    y = PAGE_H - 45
    for line in lines:
        if isinstance(line, list):
            for x, text in line:
                draw_text(stream, text, x, y)
        elif line:
            draw_text(stream, line, X, y)
        y -= LINE_H
    add_obj(5, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream")

    xref_pos = len(out)
    count = max(offsets) + 1
    out.extend(f"xref\n0 {count}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for num in range(1, count):
        out.extend(f"{offsets[num]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())

    with open(path, "wb") as f:
        f.write(bytes(out))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=("all", "baseline", "zero-omitted", "generic-exchange"),
        default="all",
    )
    args = parser.parse_args()
    out_dir = os.path.dirname(os.path.abspath(__file__))
    variants = {
        "baseline": (OUT_NAME, LINES),
        "zero-omitted": (ZERO_OMITTED_OUT_NAME, ZERO_OMITTED_LINES),
        "generic-exchange": (GENERIC_EXCHANGE_OUT_NAME, GENERIC_EXCHANGE_LINES),
    }
    selected = variants.values() if args.variant == "all" else (variants[args.variant],)
    for name, lines in selected:
        path = os.path.join(out_dir, name)
        build_pdf(lines, path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
