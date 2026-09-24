#!/usr/bin/env python3
"""Generate a deterministic, fictional Schwab-like retail statement.

The artifact follows the documented section hierarchy and column meanings,
but it is visibly marked as synthetic and does not reproduce Schwab artwork.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "schwab-retail-synthetic-202608.pdf"
EXPECT = ROOT / "fixtures" / "schwab-retail-synthetic-202608.expectations.json"

PAGE_WIDTH, PAGE_HEIGHT = 612, 792
INK = (0x20 / 255, 0x28 / 255, 0x33 / 255)
BLUE = (0x13 / 255, 0x67 / 255, 0xA8 / 255)
PALE = (0xE9 / 255, 0xF2 / 255, 0xF8 / 255)
MUTED = (0x5E / 255, 0x6B / 255, 0x75 / 255)
WHITE = (1.0, 1.0, 1.0)


def _escape_pdf_text(value: str) -> bytes:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", "replace")
    )


class MiniCanvas:
    """Tiny dependency-free PDF canvas for this deterministic fixture.

    It implements only the drawing calls below. The parser repository keeps
    fixture generation stdlib-only (apart from its declared test packages), so
    depending on a general-purpose PDF library here would make
    ``make regen-fixtures`` fail in a clean checkout.
    """

    _FONTS = {
        "Helvetica": "F1",
        "Helvetica-Bold": "F2",
        "Courier": "F3",
        "Courier-Bold": "F4",
    }

    def __init__(self, output: Path):
        self.output = output
        self.pages: list[bytearray] = []
        self.current = bytearray()
        self.font = "Helvetica"
        self.font_size = 10.0

    def _op(self, value: str | bytes) -> None:
        self.current.extend(value.encode() if isinstance(value, str) else value)
        self.current.extend(b"\n")

    def setFillColor(self, color: tuple[float, float, float]) -> None:  # noqa: N802 - canvas-compatible API
        self._op(f"{color[0]:.4f} {color[1]:.4f} {color[2]:.4f} rg")

    def setStrokeColor(self, color: tuple[float, float, float]) -> None:  # noqa: N802
        self._op(f"{color[0]:.4f} {color[1]:.4f} {color[2]:.4f} RG")

    def setFont(self, font: str, size: float) -> None:  # noqa: N802
        self.font = font
        self.font_size = size

    def rect(self, x: float, y: float, width: float, height: float, *, fill: int, stroke: int) -> None:
        operator = "B" if fill and stroke else "f" if fill else "S"
        self._op(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {operator}")

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self._op(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def drawString(self, x: float, y: float, value: str) -> None:  # noqa: N802
        font = self._FONTS[self.font]
        self._op(f"BT /{font} {self.font_size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm (".encode()
                 + _escape_pdf_text(value) + b") Tj ET")

    def drawRightString(self, x: float, y: float, value: str) -> None:  # noqa: N802
        # Exact for Courier and close enough for the short Helvetica headers.
        width_factor = 0.6 if self.font.startswith("Courier") else 0.51
        width = len(value) * self.font_size * width_factor
        self.drawString(x - width, y, value)

    def showPage(self) -> None:  # noqa: N802
        self.pages.append(self.current)
        self.current = bytearray()

    def save(self) -> None:
        self.showPage()
        page_count = len(self.pages)
        object_count = 6 + 2 * page_count
        objects: list[bytes] = [b""] * (object_count + 1)
        page_numbers = [8 + 2 * i for i in range(page_count)]

        objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = " ".join(f"{number} 0 R" for number in page_numbers)
        objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode()
        objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
        objects[6] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>"

        resources = b"<< /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R >> >>"
        for index, stream in enumerate(self.pages):
            content_number = 7 + 2 * index
            page_number = content_number + 1
            objects[content_number] = (
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + bytes(stream) + b"endstream"
            )
            objects[page_number] = (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                + resources + f" /Contents {content_number} 0 R >>".encode()
            )

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number in range(1, object_count + 1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode())
            output.extend(objects[number])
            output.extend(b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {object_count + 1}\n".encode())
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode())
        output.extend(
            f"trailer\n<< /Size {object_count + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n".encode()
        )
        self.output.write_bytes(output)


class Statement:
    def __init__(self, output: Path):
        output.parent.mkdir(parents=True, exist_ok=True)
        self.c = MiniCanvas(output)
        self.page = 0
        self.y = 0.0

    def header(self, section: str = "") -> None:
        if self.page:
            self.c.showPage()
        self.page += 1
        self.c.setFillColor(INK)
        self.c.rect(0, PAGE_HEIGHT - 82, PAGE_WIDTH, 82, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 16)
        self.c.drawString(36, PAGE_HEIGHT - 34, "CHARLES SCHWAB")
        self.c.setFont("Helvetica", 8)
        self.c.drawString(36, PAGE_HEIGHT - 51, "SYNTHETIC TEST DATA - NOT AN OFFICIAL SCHWAB STATEMENT")
        # Current real retail statements identify the account and compact date
        # range without literal "Account Number" / "Statement Period" labels.
        # The real PDF includes a registered-mark glyph between "One" and
        # "Account". This tiny stdlib PDF writer intentionally uses only the
        # base Latin font encoding, so omit the glyph while preserving the
        # same extracted words the detector anchors on.
        self.c.drawRightString(PAGE_WIDTH - 36, PAGE_HEIGHT - 30, "Schwab One Account of")
        self.c.drawRightString(PAGE_WIDTH - 36, PAGE_HEIGHT - 44, "SYNTHETIC HOUSEHOLD")
        self.c.drawRightString(PAGE_WIDTH - 36, PAGE_HEIGHT - 58, "INDIVIDUAL/TOD 1111-9999 August1-31,2026")
        if section:
            self.c.setFillColor(BLUE)
            self.c.setFont("Helvetica-Bold", 8)
            self.c.drawString(36, PAGE_HEIGHT - 96, section)
        self.y = PAGE_HEIGHT - 112

    def title(self, text: str) -> None:
        # Leave enough white space that the title bar never covers the
        # preceding table's last baseline.
        self.y -= 10
        self.c.setFillColor(BLUE)
        self.c.rect(36, self.y - 4, PAGE_WIDTH - 72, 19, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 10)
        self.c.drawString(42, self.y + 1, text)
        self.y -= 22

    def subhead(self, text: str) -> None:
        # The pale group bar sits between position rows; without this gap its
        # top edge can cover the descenders on the preceding row.
        self.y -= 5
        self.c.setFillColor(PALE)
        self.c.rect(36, self.y - 3, PAGE_WIDTH - 72, 16, fill=1, stroke=0)
        self.c.setFillColor(INK)
        self.c.setFont("Helvetica-Bold", 8)
        self.c.drawString(42, self.y + 1, text)
        self.y -= 18

    def line(self, text: str, *, size: float = 8, font: str = "Courier", indent: float = 42, leading: float = 12) -> None:
        self.c.setFillColor(INK)
        self.c.setFont(font, size)
        self.c.drawString(indent, self.y, text)
        self.y -= leading

    def transaction_header(self) -> None:
        self.c.setFillColor(INK)
        self.c.setFont("Helvetica-Bold", 5.2)
        # Match the production two-line header: several labels begin on the
        # physical line above the Date/Category/Action anchor row.
        for x, text in [
            (200, "Symbol/"),
            (459, "Price/Rate"),
            (504, "Charges/"),
        ]:
            self.c.drawString(x, self.y, text)
        self.y -= 8
        for x, text in [
            (42, "Date"),
            (76, "Category"),
            (128, "Action"),
            (200, "CUSIP"),
            (250, "Description"),
            (414, "Quantity"),
            (459, "per Share($)"),
            (504, "Interest($)"),
            (550, "Amount($)"),
        ]:
            self.c.drawString(x, self.y, text)
        self.y -= 11

    def transaction_row(
        self,
        date: str,
        category: str,
        action: str,
        symbol: str,
        description: str,
        quantity: str = "-",
        price: str = "-",
        charges: str = "-",
        amount: str = "0.00",
        continuation: str = "",
    ) -> None:
        """Draw cells independently, including current grouped-row quirks."""
        self.c.setFillColor(INK)
        self.c.setFont("Helvetica", 5.4)
        self.c.drawString(42, self.y, date)
        category_lines = category.split(" ", 1) if category == "Other Activity" else [category]
        self.c.drawString(76, self.y, category_lines[0])
        self.c.drawString(128, self.y, action)
        self.c.drawString(200, self.y, symbol)
        self.c.drawString(250, self.y, description)
        if quantity not in {"-", "--"}:
            self.c.drawRightString(451, self.y, quantity)
        if price not in {"-", "--"}:
            self.c.drawRightString(496, self.y, price)
        if charges not in {"-", "--"}:
            self.c.drawRightString(520, self.y, charges)
        self.c.drawRightString(582, self.y, amount)
        extra_line = category_lines[1] if len(category_lines) == 2 else ""
        if extra_line or continuation:
            self.y -= 8
            if extra_line:
                self.c.drawString(76, self.y, extra_line)
            if continuation:
                self.c.drawString(250, self.y, continuation)
            self.y -= 7
        else:
            self.y -= 11

    def footer(self) -> None:
        self.c.setStrokeColor((0xCC / 255, 0xD5 / 255, 0xDC / 255))
        self.c.line(36, 38, PAGE_WIDTH - 36, 38)
        self.c.setFillColor(MUTED)
        self.c.setFont("Helvetica", 7)
        self.c.drawString(36, 25, "Fictional values for parser validation only. No real person, account, or security is represented.")
        self.c.drawRightString(PAGE_WIDTH - 36, 25, f"Page {self.page} of 4")

    def save(self) -> None:
        self.c.save()


def build() -> None:
    s = Statement(OUT)

    s.header("ACCOUNT OVERVIEW")
    s.title("Account Summary")
    for label, value in [
        ("Beginning Value", "120,000.00"),
        ("Deposits", "10,000.00"),
        ("Withdrawals", "(2,500.00)"),
        ("Dividends and Interest", "239.85"),
        ("Transfer of Securities (In/Out)", "0.00"),
        ("Market Value Change", "640.00"),
        ("Fees", "(75.00)"),
        ("Ending Value", "128,304.85"),
    ]:
        s.line(f"{label:<48}{value:>16}", size=8.2)
    s.title("Positions - Summary")
    for label, value in [
        ("Beginning Value", "120,000.00"),
        ("Transfer of Securities (In/Out)", "0.00"),
        ("Dividends Reinvested", "120.00"),
        ("Cash Activity", "7,544.85"),
        ("Change in Market Value", "640.00"),
        ("Ending Value", "128,304.85"),
    ]:
        s.line(f"{label:<48}{value:>16}", size=8.2)
    s.title("Cash and Cash Investments")
    s.line("Symbol  Description                                                        Value", size=7)
    s.line("CASH  BANK SWEEP                                                      7,064.85", size=7.4)
    s.footer()

    s.header("POSITIONS")
    s.title("Positions")
    s.subhead("Equities")
    s.line("Symbol  Description                              Quantity      Price        Value      Cost Basis", size=6.6)
    s.line("ALPH  ALPHA TECHNOLOGIES CLASS A  100.0000  425.5000  42,550.00  38,000.00", size=6.8)
    s.line("GLOBAL SYNTHETIC INNOVATION HOLDING", size=6.8, indent=78)
    s.line("BRVO  BRAVO INDUSTRIES INC  250.0000  125.0000  31,250.00  26,000.00", size=6.8)
    s.subhead("Mutual Funds")
    s.line("QWAV  QUANTUM WAVE INDEX FUND  300.0000  95.4000  28,620.00  24,900.00", size=6.8)
    s.subhead("Fixed Income")
    s.line("CUSIP  Description                       Coupon  Maturity      Par       Price       Value", size=6.4)
    s.line("111111SY1  SYNTHETIC MUNICIPAL BOND  3.750%  08/01/2035  15,000.0000  118.8000  17,820.00", size=6.2)
    s.subhead("Options")
    s.line("QWAV260918C100  QWAV SEP 18 2026 100 CALL  2.0000  500.0000  1,000.00  650.00", size=6.5)
    s.line("Total Positions                                                      128,304.85", size=8.2, font="Courier-Bold")
    s.footer()

    s.header("TRANSACTIONS")
    s.title("Transactions - Summary")
    for label, value in [
        ("Beginning Cash", "1,220.00"),
        ("Deposits", "10,000.00"),
        ("Withdrawals", "(2,500.00)"),
        ("Purchases", "(4,220.00)"),
        ("Sales/Redemptions", "2,400.00"),
        ("Dividends/Interest", "239.85"),
        ("Fees", "(75.00)"),
        ("Ending Cash", "7,064.85"),
    ]:
        s.line(f"{label:<48}{value:>16}", size=8.2)
    s.title("Transaction Details")
    s.transaction_header()
    s.transaction_row(
        "08/02", "Other Activity", "StockPlanActivity", "ALPH", "STOCK PLAN SHARE DELIVERY",
        "5.0000", amount="2,050.00",
    )
    # Schwab prints a date once for a group and leaves subsequent rows blank.
    s.transaction_row(
        "", "Other Activity", "StockPlanActivity", "BRVO", "STOCK PLAN SHARE DELIVERY",
        "2.0000", amount="240.00",
    )
    s.transaction_row(
        "08/03", "Deposit", "Deposit", "CASH", "ACH DEPOSIT SYNTHETIC BANK",
        amount="10,000.00", continuation="REFERENCE SYNTHETIC-001",
    )
    s.transaction_row(
        "08/05", "Withdrawal", "Withdrawal", "CASH", "ELECTRONIC FUNDS TRANSFER",
        amount="(2,500.00)",
    )
    s.transaction_row(
        "08/08", "Purchase", "Buy", "ALPH", "ALPHA TECHNOLOGIES CLASS A",
        "10.0000", "410.0000", "0.00", "(4,100.00)",
    )
    s.transaction_row(
        "08/10", "Purchase", "Reinvest", "QWAV", "DIVIDEND REINVESTMENT",
        "1.2579", "95.3987", "0.00", "(120.00)",
    )
    s.footer()

    s.header("TRANSACTIONS CONTINUED")
    s.title("Transaction Details (Continued)")
    s.transaction_header()
    s.transaction_row(
        "08/12", "Sale", "Sell", "BRVO", "BRAVO INDUSTRIES INC",
        "20.0000", "120.0000", "0.00", "2,400.00",
    )
    s.transaction_row("08/15", "Dividend", "Qualified Dividend", "ALPH", "QUALIFIED DIVIDEND", amount="120.00")
    s.transaction_row("08/18", "Dividend", "Cash Dividend", "QWAV", "CASH DIVIDEND", amount="100.00")
    s.transaction_row("08/25", "Interest", "Bank Interest", "CASH", "BANK SWEEP INTEREST", amount="19.85")
    s.transaction_row("08/31", "Fee", "Advisory Fee", "CASH", "ADVISORY PROGRAM FEE", amount="(75.00)")
    s.line("Total Transaction Details                                              2,044.85", size=7.2, font="Courier-Bold")
    s.title("Bank Sweep Activity")
    s.line("Date  Description                                                  Amount       Balance", size=6.4)
    s.line("Beginning Balance                                                              1,220.00", size=6.8)
    sweep = [
        ("08/03", "BANK CREDIT FROM BROKERAGE", "10,000.00", "11,220.00"),
        ("08/05", "BANK TRANSFER TO BROKERAGE", "(2,500.00)", "8,720.00"),
        ("08/08", "BANK TRANSFER TO BROKERAGE", "(4,100.00)", "4,620.00"),
        ("08/10", "BANK TRANSFER TO BROKERAGE", "(120.00)", "4,500.00"),
        ("08/12", "BANK CREDIT FROM BROKERAGE", "2,400.00", "6,900.00"),
        ("08/15", "BANK CREDIT FROM BROKERAGE", "120.00", "7,020.00"),
        ("08/18", "BANK CREDIT FROM BROKERAGE", "100.00", "7,120.00"),
        ("08/25", "BANK INTEREST", "19.85", "7,139.85"),
        ("08/31", "BANK TRANSFER TO BROKERAGE", "(75.00)", "7,064.85"),
    ]
    for dt, desc, amount, balance in sweep:
        s.line(f"{dt}  {desc}  {amount}  {balance}", size=6.2, leading=9)
    s.line("Ending Balance                                                                 7,064.85", size=6.8, font="Courier-Bold")
    s.title("Pending/Open Activities")
    s.line("08/31  Purchase  Buy  PEND  PENDING UNSETTLED PURCHASE  5.0000  10.0000  0.00  (50.00)", size=5.8)
    s.footer()
    s.save()

    expected = {
        "file": OUT.name,
        "institution": "Charles Schwab",
        "statementDate": "2026-08-31",
        "account": "9999",
        "accountType": "Brokerage",
        "endingValue": 128304.85,
        "positions": {
            "CASH": 7064.85,
            "ALPH": 42550.00,
            "BRVO": 31250.00,
            "QWAV": 28620.00,
            "111111SY1": 17820.00,
            "QWAV260918C100": 1000.00,
        },
        "transactionCount": 11,
        "transactionTotals": {
            "corporate_action": 0.00,
            "buy": -4220.00,
            "sell": 2400.00,
            "dividend": 220.00,
            "interest": 19.85,
            "deposit": 10000.00,
            "withdrawal": -2500.00,
            "fee": -75.00,
        },
        "pendingSymbolExcluded": "PEND",
        "closingSweepBalance": 7064.85,
    }
    EXPECT.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
