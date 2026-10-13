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
STATEMENT_DETAILS_OUT_NAME = "fidelity-401k-statement-details-synthetic-sample.pdf"

# A line entry can also be ("raw", [(x, dy, text), ...], advance): each text
# drawn dy points above the current line, then the line moved down by
# advance - for the wrapped fund names below, whose lines sit a fraction of
# a line above and below their row of figures. PAGE_BREAK starts a new page.
PAGE_BREAK = "\f"


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


# The NetBenefits "Statement Details" layout (Q3 2026 sample): fund names
# wrap over two lines of the Investment column, centred on the row of
# figures, so one line of a name can sit above the figures and one below;
# a category label sits a full line above the first fund in it; the table
# runs onto a second page with its headings repeated. The positions follow
# a scrambled real statement: name lines about 8pt apart, a label about
# 13.5pt above the figures. No account number is printed. Invented funds
# and figures throughout; they add up.
FIGURES = 330
_HEADINGS = [
    [(36, "Shares/Units"), (226, "Shares/Units")],
    [(36, "Price as of"), (226, "Price as of Market Value as Market Value as")],
    [(36, "Investment as of as of")],
    [(36, "06/30/2026 09/30/2026 of 06/30/2026 of 09/30/2026")],
]


def _fund(first: tuple[float, str], second: tuple[float, str], figures: str) -> tuple:
    return ("raw", [(72, first[0], first[1]), (72, second[0], second[1]), (FIGURES, 0, figures)], 22)


STATEMENT_DETAILS_LINES = [
    "10/3/26, 9:47 AM Fidelity NetBenefits - Statement Details",
    "Statement Details",
    "Synthetic Widget Company 401(k)",
    "Retirement Savings Statement",
    "Your Account Summary",
    "Statement Period: 07/01/2026 to 09/30/2026",
    "Beginning Balance $50,000.00",
    "Withdrawals -$5,000.00",
    "Fees $0.00",
    "Change In Market Value $1,650.00",
    "Ending Balance $46,650.00",
    "",
    "Market Value of Your Account",
    "Statement Period: 07/01/2026 to 09/30/2026",
    *_HEADINGS,
    [(120, "CORE OPTIONS AND SYNTHETIC CO STK")],
    [(72, "Stock"), (420, "$30,000.00 $31,500.00")],
    ("raw", [(72, 1.5, "Large Cap")], 13.5),
    # The first line of the name on the figures' line, the second below it.
    _fund((2.8, "Synthetic Total"), (-5.0, "Market Index K"),
          "200.000 200.000 $100.00 $105.00 $20,000.00 $21,000.00"),
    # The first line of the name above the figures, the second on their line.
    _fund((5.6, "Synthetic"), (-2.2, "Growth Pool K"),
          "100.000 100.000 $100.00 $105.00 $10,000.00 $10,500.00"),
    "https://example.invalid/statement 1/2",
    PAGE_BREAK,
    "10/3/26, 9:47 AM Fidelity NetBenefits - Statement Details",
    *_HEADINGS,
    [(72, "Bond"), (420, "$15,000.00 $15,150.00")],
    ("raw", [(72, 1.5, "Stable Value")], 13.5),
    # A stable-value fund carried at its value: no shares, no price.
    _fund((2.8, "Synthetic Stable"), (-5.0, "Value Fund"), "N/A N/A N/A N/A $15,000.00 $15,150.00"),
    [(72, "Blended Fund Investments*"), (420, "$5,000.00 $0.00")],
    # Sold out during the quarter: it prints, at $0.00, and is not held.
    _fund((2.8, "Synthetic Target"), (-5.0, "Date 2030 K"), "50.000 0.000 $100.00 $102.00 $5,000.00 $0.00"),
    [(72, "Account Totals"), (420, "$50,000.00 $46,650.00")],
    "",
    "Your Current Investment Elections as of 10/03/2026",
    "SYNTHETIC TOTAL MARKET INDEX K 60%",
    "SYNTHETIC GROWTH POOL K 40%",
    "",
    "Your Account Activity",
    "Statement Period: 07/01/2026 to 09/30/2026",
    "Detailed Transaction History",
    [(248, "Synthetic"), (332, "Synthetic"), (420, "Total")],
    [(144, "Activity")],
    [(144, "Beginning Balance"), (248, "$20,000.00"), (332, "$10,000.00"), (420, "$50,000.00")],
    [(144, "Ending Balance"), (248, "$21,000.00"), (332, "$10,500.00"), (420, "$46,650.00")],
    "https://example.invalid/statement 2/2",
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

    streams: list[bytearray] = [bytearray()]
    y = PAGE_H - 45
    for line in lines:
        stream = streams[-1]
        if line == PAGE_BREAK:
            streams.append(bytearray())
            y = PAGE_H - 45
            continue
        if isinstance(line, tuple) and line and line[0] == "raw":
            _, items, advance = line
            for x, dy, text in items:
                draw_text(stream, text, x, y + dy)
            y -= advance
            continue
        if isinstance(line, list):
            for x, text in line:
                draw_text(stream, text, x, y)
        elif line:
            draw_text(stream, line, X, y)
        y -= LINE_H

    # Objects: 1 catalog, 2 pages, 3 font, then a page and its content per page.
    page_nums = [4 + 2 * i for i in range(len(streams))]
    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{n} 0 R" for n in page_nums)
    add_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>".encode())
    add_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for n, stream in zip(page_nums, streams):
        add_obj(
            n,
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (PAGE_W, PAGE_H, n + 1)
            ).encode(),
        )
        add_obj(n + 1, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream")

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
        choices=("all", "baseline", "zero-omitted", "generic-exchange", "statement-details"),
        default="all",
    )
    args = parser.parse_args()
    out_dir = os.path.dirname(os.path.abspath(__file__))
    variants = {
        "baseline": (OUT_NAME, LINES),
        "zero-omitted": (ZERO_OMITTED_OUT_NAME, ZERO_OMITTED_LINES),
        "generic-exchange": (GENERIC_EXCHANGE_OUT_NAME, GENERIC_EXCHANGE_LINES),
        "statement-details": (STATEMENT_DETAILS_OUT_NAME, STATEMENT_DETAILS_LINES),
    }
    selected = variants.values() if args.variant == "all" else (variants[args.variant],)
    for name, lines in selected:
        path = os.path.join(out_dir, name)
        build_pdf(lines, path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
