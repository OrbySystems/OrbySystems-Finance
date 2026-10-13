# SPDX-License-Identifier: Apache-2.0
"""Fidelity NetBenefits 401(k) retirement savings statement PDF.

This format is exported from the NetBenefits "Statement Details" page,
not Fidelity's ordinary monthly brokerage "INVESTMENT REPORT". It prints
an ending holdings snapshot ("Market Value of Your Account": per fund, the
shares, price and market value at both ends of the period) and aggregate
activity TOTALS for the period (Exchange In/Out, Revenue Credit, Dividends
& Interest, Change In Market Value). It does not print itemized
transactions, even though the page has a "Detailed Transaction History"
heading.

So this parser reads the holdings and nothing else (revision 7). An early
revision reconstructed per-fund "transaction" rows from the activity
totals, but a total is not a transaction: it cannot say which of several
same-day, same-fund dividends or exchanges it stands for, and those rows
misrepresented the account's real activity. Revisions 4-6 then refused
the PDF altogether and pointed at the NetBenefits "Transaction History"
CSV export (csv_institutions/fidelity_netbenefits_401k_csv.py), which is
itemized. That stays the way to get transactions; the CSV has no holdings,
so the two exports complement each other. A PDF is still refused when it
has no readable holdings table.

**Fund names wrap.** A fund's name can take two or three lines of the
Investment column, centered on its row of figures, so pdfplumber's text
puts part of the name on the figures' line and the rest on the line above
or below - and a category label ("Large Cap", "Stable Value") sits on a
line of its own just above the first fund in it. Text alone cannot tell
the label from the first line of a wrapped name, but their positions can:
the lines of one name sit within half a line of the figures' line (about
8pt apart in the real statement), a category label a full line or more
above them (about 13pt). With the PDF available the names are read from
word positions (`_holdings_from_pdf`); without it (a text-only test) from
the figures' line alone.

No account number is printed: `account` is left blank, as in the CSV
export, and the app asks for its last four digits on import.
"""

from __future__ import annotations

import re
from datetime import datetime

import parser_common
from institutions import common

KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED

# Terms this format cannot contain, so Data Metrics says "not applicable"
# instead of "not seen". Only what the statement cannot hold - never what this
# parser merely does not read.
NOT_APPLICABLE = {
    "option:*": "A 401(k) plan holds no option contracts.",
    "corporate_event:*": "A plan statement reports contributions, exchanges and fund activity, not corporate actions on securities.",
}
PARSER_REVISION = 7

_INSTITUTION = "Fidelity NetBenefits"
_ACCOUNT_TYPE = "401(k)"
_EPS = 0.01

_PERIOD_RE = re.compile(
    r"Statement Period:\s*(\d{2})/(\d{2})/(\d{4})\s+to\s+(\d{2})/(\d{2})/(\d{4})"
)
_ACCOUNT_RE = re.compile(r"\bAccount(?: Number| #)?:\s*([A-Za-z0-9Xx*#-]+)", re.I)
_MONEY_RE = re.compile(r"-?\$[\d,]+\.\d{2,4}")
_NA = r"N/A"
_QTY = rf"(?:[\d,]+\.\d{{3,4}}|{_NA})"
_PRICE = rf"(?:\$[\d,]+\.\d{{2,4}}|{_NA})"
_VALUE = r"-?\$[\d,]+\.\d{2}"
# A fund's row of figures: shares, price and market value at the start and
# the end of the period, after whatever part of its name shares the line.
_HOLDING_ROW_RE = re.compile(
    rf"^(?P<name>.*?)\s*(?P<begin_qty>{_QTY})\s+(?P<end_qty>{_QTY})\s+"
    rf"(?P<begin_price>{_PRICE})\s+(?P<end_price>{_PRICE})\s+"
    rf"(?P<begin_value>{_VALUE})\s+(?P<end_value>{_VALUE})$"
)
_FIGURE_RE = re.compile(rf"^(?:{_QTY}|{_PRICE}|{_VALUE})$")
_SECTION_START = "market value of your account"
_TOTALS_RE = re.compile(rf"^Account Totals\s+({_VALUE})\s+({_VALUE})$")
# The table's own column headings and the browser's page header and footer,
# none of which is part of a fund's name.
_HEADER_RE = re.compile(
    r"^(?:Shares/|Price as of|Market Value|Investment\b|\d{2}/\d{2}/\d{4}|of \d{2}/\d{2}/\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2},|[a-z]+://)",
    re.I,
)
# How far from its row of figures a line of the same fund's name can sit.
_NAME_BAND = 9.0


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    if "fidelity netbenefits" not in lower:
        return False, "'fidelity netbenefits' not found"
    if "retirement savings statement" not in lower:
        return False, "'retirement savings statement' not found"
    if not _PERIOD_RE.search(head_text):
        return False, "no NetBenefits statement period found"
    return True, "matched Fidelity NetBenefits retirement savings statement"


def _fail(message: str, code: str = "PARSER_REQUIRED_DATA_MISSING", stage: str = "holdings"):
    return parser_common.ParserDiagnosticError(message, code=code, stage=stage)


def _statement_date(text: str) -> str:
    match = _PERIOD_RE.search(text)
    if not match:
        return ""
    mm, dd, yyyy = match.group(4), match.group(5), match.group(6)
    try:
        return datetime.strptime(f"{mm}/{dd}/{yyyy}", "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _account(text: str) -> str:
    match = _ACCOUNT_RE.search(text)
    return common.last4_digits(match.group(1)) if match else ""


def _figure(raw: str) -> float | None:
    """A Shares or Price cell, or None for a printed N/A."""
    return None if raw == "N/A" else common.parse_amount(raw.replace("$", ""))


def _holding(name: str, m: re.Match, statement_date: str) -> dict:
    name = re.sub(r"\s+", " ", name).strip()
    # A plan fund has no ticker: its name is its symbol, as in the CSV export.
    row = {"symbol": re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9&*.-]+", " ", name.upper())).strip(),
           "description": name}
    for key, group in (("quantity", "end_qty"), ("price", "end_price")):
        value = _figure(m.group(group))
        if value is not None:
            row[key] = value
    row["current_value"] = common.parse_amount(m.group("end_value").replace("$", ""))
    row["currency_code"] = "USD"
    if statement_date:
        row["price_as_of"] = statement_date
    # A fund priced per share is a mutual fund or collective trust; one with
    # no shares (N/A) is a fixed or stable-value account carried at its value.
    row["type"] = "Mutual Fund" if "quantity" in row else "Fixed Account"
    return row


def _holdings_from_text(pages_text: list[str], statement_date: str) -> tuple[list[dict], float | None]:
    """Holdings from the extracted text: a wrapped name keeps only the part on
    its figures' line. Used when the PDF itself cannot be read."""
    holdings: list[dict] = []
    total = None
    in_section = False
    for text in pages_text:
        for raw in text.splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if _SECTION_START in line.lower():
                in_section = True
                continue
            if not in_section:
                continue
            totals = _TOTALS_RE.match(line)
            if totals:
                total = common.parse_amount(totals.group(2).replace("$", ""))
                return holdings, total
            m = _HOLDING_ROW_RE.match(line)
            if m:
                holdings.append(_holding(m.group("name"), m, statement_date))
    return holdings, total


def _lines(page) -> list[tuple[float, list[dict]]]:
    """The page's words grouped into lines by their top, in reading order."""
    lines: list[tuple[float, list[dict]]] = []
    for word in sorted(page.extract_words(x_tolerance=2, y_tolerance=3), key=lambda w: (w["top"], w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]) <= 3:
            lines[-1][1].append(word)
        else:
            lines.append((word["top"], [word]))
    return [(top, sorted(words, key=lambda w: w["x0"])) for top, words in lines]


def _holdings_from_pdf(pdf_path: str, statement_date: str) -> tuple[list[dict], float | None] | None:
    """Holdings with every line of each fund's name, read from word positions.
    None when the PDF cannot be read or has no holdings table."""
    try:
        import pdfplumber

        pdf = pdfplumber.open(pdf_path)
    except Exception:  # noqa: BLE001 - the text-only reading still works
        return None

    holdings: list[dict] = []
    total = None
    in_section = False
    found = False
    with pdf:
        for page in pdf.pages:
            rows = []      # (top, match, the name words on the figures' line)
            names = []     # (top, words) of lines holding only text
            for top, words in _lines(page):
                text = " ".join(w["text"] for w in words)
                if _SECTION_START in text.lower():
                    in_section = found = True
                    continue
                if not in_section:
                    continue
                totals = _TOTALS_RE.match(text)
                if totals:
                    total = common.parse_amount(totals.group(2).replace("$", ""))
                    in_section = False
                    break
                m = _HOLDING_ROW_RE.match(text)
                if m:
                    first_figure = next(i for i, w in enumerate(words) if _FIGURE_RE.match(w["text"]))
                    rows.append((top, m, words[:first_figure]))
                elif not _MONEY_RE.search(text) and not _HEADER_RE.match(text):
                    names.append((top, words))
            # Each text line goes to the nearest row of figures within half a
            # line; one farther away is a category label or a heading.
            parts: list[list[dict]] = [list(own) for _, _, own in rows]
            for top, words in names:
                if not rows:
                    break
                nearest = min(range(len(rows)), key=lambda i: abs(rows[i][0] - top))
                if abs(rows[nearest][0] - top) <= _NAME_BAND:
                    parts[nearest].extend(words)
            for (_, m, _), words in zip(rows, parts):
                ordered = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
                holdings.append(_holding(" ".join(w["text"] for w in ordered), m, statement_date))
            if total is not None:
                break
    if not found:
        return None
    return holdings, total


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    statement_date = _statement_date(text)
    read = _holdings_from_pdf(pdf_path, statement_date) if pdf_path else None
    holdings, printed_total = read if read is not None else _holdings_from_text(pages_text, statement_date)

    if not holdings:
        raise _fail("No fund rows found in the NetBenefits Market Value of Your Account table.")
    if printed_total is None:
        raise _fail("NetBenefits Account Totals line not found.")
    held = sum(h["current_value"] for h in holdings)
    if abs(held - printed_total) > _EPS:
        raise _fail(
            f"Fund values sum to {held:.2f} but the printed Account Totals is {printed_total:.2f}.",
            code="PARSER_RECONCILIATION_FAILED",
        )

    # A fund sold out during the period still prints, at $0.00: it is not held.
    held_rows = [h for h in holdings if abs(h["current_value"]) > _EPS]
    common.tag_account(held_rows, _account(text), _ACCOUNT_TYPE)
    return {
        "institution": _INSTITUTION,
        "statementDate": statement_date,
        "tables": {"brokerage_holdings": held_rows},
    }
