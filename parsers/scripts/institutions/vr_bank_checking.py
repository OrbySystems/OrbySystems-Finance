"""Volksbank and Raiffeisenbank (VR Bank) statement (Kontoauszug) parser.

Format: the PDF Kontoauszug of the cooperative banks (Volksbanken,
Raiffeisenbanken, VR Banken and the like, each its own "eG"), which share
one layout from their common banking system. Page 1, after the bank's name
and the holder's address:

    EUR-Konto Kontonummer 1234567
    VR Bank Musterstadt eG Kontoauszug Nr. 1/2026
    erstellt am 31.03.2026 18:42 Blatt 1 von 1
    IBAN: DE12 3456 0000 0001 2345 67 BIC: GENODEF1XXX
    Bu-Tag Wert Vorgang
    alter Kontostand vom 31.12.2025 1.234,56 H
    02.01. 02.01. Basislastschrift PN:931 57,84 S
    Stadtwerke Musterstadt GmbH Abschlag 01/2026
    31.03. 31.03. Abschluss PN:905 12,40 S
    ...
    neuer Kontostand vom 31.03.2026 1.164,32 H

Each booking is a line that starts with its booking day and value date,
without their year ("02.07. 02.07."), then the booking text, a "PN:nnn"
reference, and the amount marked S (Soll, money out) or H (Haben, money
in); the lines below it, up to the next booking, describe it. The bookings
run from "alter Kontostand" to "neuer Kontostand", across pages when there
are many: a page the bookings carry on to repeats the header above them,
which is skipped, and an "Übertrag" line carries the balance between pages
and is not a booking. The quarterly "Abschluss" (interest and fees) is a
booking like any other, its details below it.

The year of a booking comes from the statement's own dates: each takes the
year that puts it between the opening and closing Kontostand dates (an
annual statement covers twelve months). Amounts are read in the sign
this codebase uses (S negative, an overdrawn balance included), in the
account's currency ("EUR-Konto"), which every row carries as currency_code
when the app accepts it. The statement prints no running balance; one is
derived from the opening Kontostand. The statement's own arithmetic is
reported as checks: opening Kontostand plus every booking is the closing
Kontostand, and every line that starts with a booking's two dates but was
not read is listed (CONTRACT.md, "Checks").

Built from a scrambled sample of a real statement (README_addparser.md);
the scrambler kept the statement's German words, so detect() is anchored
on them and on the layout, not on one bank's name.
"""

import re
from datetime import date

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1

INSTITUTION = "VR Bank"

_AMOUNT = r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}"
# An amount with its S or H mark, at the end of a line: "1.234,56 H", "12,40S".
_MARKED = r"(" + _AMOUNT + r")\s?([SH])"
# A Kontostand's amount; a zero balance may be printed without its mark.
_BALANCE = r"(" + _AMOUNT + r")(?:\s?([SH]))?"
# A date with or without its year: "30.09.", "30.09.2026".
_DATE = r"\d{2}\.\d{2}\.(?:\d{4}|\d{2})?"
_YEARLESS = r"\d{2}\.\d{2}\."

_OPENING_RE = re.compile(r"^alter\s+Kontostand\b(?:.*?(\d{2}\.\d{2}\.\d{4}))?.*?\s" + _BALANCE + r"$", re.I)
_CLOSING_RE = re.compile(r"^neuer\s+Kontostand\b(?:.*?(\d{2}\.\d{2}\.\d{4}))?.*?\s" + _BALANCE + r"$", re.I)

# A booking: "02.07. 02.07. Basislastschrift PN:931 57,84 S".
_BOOKING_RE = re.compile(r"^(" + _DATE + r")\s+(" + _DATE + r")\s*(.*?)\s*" + _MARKED + r"$")
# A line that starts like a booking: two dates without their year, or any
# two dates with an amount at the end. One not read is reported; a purpose
# line that starts with a period ("01.01.2026 31.03.2026 Beitrag") is not.
_TWO_DATES_RE = re.compile(r"^(?:" + _YEARLESS + r"\s+" + _YEARLESS + r"(?:\s|$)|"
                           + _DATE + r"\s+" + _DATE + r"\s.*\s" + _AMOUNT + r"\s?[SH]?$)")
# Outside the bookings, a dated line ending in a marked amount is a booking
# in a part of the statement this parser doesn't know.
_DATED_AMOUNT_RE = re.compile(r"^" + _DATE + r"\s.*\s" + _MARKED + r"$")
# The booking's reference at the end of its text: "PN:931".
_REFERENCE_RE = re.compile(r"\s*\b[A-Z]{1,3}:\s?\d+$")
# The balance carried between pages: "Übertrag auf Blatt 2 1.234,56 H".
_CARRY_RE = re.compile(r"^(?:Übertrag|Uebertrag)\b", re.I)
# A line with no letter or digit (a rule across the page), or a lone code
# in the page's margin ("4410", "K01234567"): never a booking's description.
_RULE_RE = re.compile(r"^[\W_]*$")
_CODE_RE = re.compile(r"^[A-Z]{0,2}\d+$")

_ACCOUNT_RE = re.compile(r"\bKontonummer\s*:?\s*(\d[\d ]*\d)")
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?\d{4}){4}\s?\d{2})\b")
_DE_IBAN_RE = re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b")
_HEADER_RE = re.compile(r"\bBu\.?-?\s?Tag\b.*\bWert\b.*\bVorgang\b")
_CURRENCY_RE = re.compile(r"\b([A-Z]{3})-Konto\b")
# A savings product's name on the account line; Sparda is a bank.
_SAVINGS_RE = re.compile(r"tagesgeld|festgeld|spar(?!da|kasse)", re.I)
_BANK_NAME_RE = re.compile(r"\beG\b|volksbank|raiffeisenbank|\bVR[ -]?Bank\b|sparda|\bPSD\b", re.I)


def _currency_accepted() -> bool:
    """Whether the app running this accepts currency_code on a row: from
    the release after 1.0.2 on (orby-core docs/currency-on-cash-rows.md)."""
    return hasattr(parser_common, "normalize_currency_codes")


def detect(head_text: str) -> tuple[bool, str]:
    missing = [name for name, found in (
        ("Kontoauszug", "Kontoauszug" in head_text),
        ("alter Kontostand", re.search(r"alter\s+Kontostand", head_text, re.I)),
        ("Bu-Tag Wert Vorgang", _HEADER_RE.search(head_text)),
        ("DE IBAN", _DE_IBAN_RE.search(head_text)),
    ) if not found]
    if missing:
        return False, "VR Bank Kontoauszug marker(s) not found: " + ", ".join(missing)
    return True, "matched VR Bank Kontoauszug (Kontoauszug, alter Kontostand, Bu-Tag Wert Vorgang, DE IBAN)"


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def _amount(figure: str, mark: str | None) -> float:
    value = float(figure.replace(".", "").replace(",", "."))
    return -value if (mark or "").upper() == "S" else value


def _footer_starts(pages: list[list[str]]) -> list[int]:
    """Where each page's footer begins: the run of lines at its end that
    another page ends with too. A booking is never footer."""
    starts = []
    for i, lines in enumerate(pages):
        longest = 0
        for j, other in enumerate(pages):
            if i == j:
                continue
            k = 0
            while (k < len(lines) and k < len(other) and lines[-1 - k] == other[-1 - k]
                   and not _BOOKING_RE.match(lines[-1 - k])):
                k += 1
            longest = max(longest, k)
        starts.append(len(lines) - longest)
    return starts


def _find(pages: list[list[str]], regex: re.Pattern, after: tuple[int, int] = (0, -1)):
    for p in range(after[0], len(pages)):
        for n, s in enumerate(pages[p]):
            if (p, n) > after:
                m = regex.match(s)
                if m:
                    return p, n, m
    return None


def _account(lines: list[str]) -> tuple[str, str, list[str]]:
    """The account's last four digits, its type, and the numbers that name
    it in full (masked wherever a description repeats them)."""
    full: list[str] = []
    number = ""
    product = ""
    for n, s in enumerate(lines):
        m = _ACCOUNT_RE.search(s)
        if m:
            number = re.sub(r"\D", "", m.group(1))
            product = " ".join(lines[max(0, n - 1):n + 1])
            full.append(number)
            break
    for s in lines:
        m = _DE_IBAN_RE.search(s)
        if m:
            iban = re.sub(r"\s", "", m.group(0))
            full.append(iban)
            if not number:
                number = iban
                product = s
            break
    account_type = "Savings" if _SAVINGS_RE.search(product) else "Checking"
    return common.last4_digits(number), account_type, full


def _mask(text: str, full: list[str]) -> str:
    """The holder's own account number and IBAN, wherever a description
    repeats them, down to their last four digits."""
    def hide(m: re.Match) -> str:
        figure = re.sub(r"\s", "", m.group(0))
        return "*" * (len(figure) - 4) + figure[-4:]

    # The IBAN first: it holds the account number.
    for number in sorted(full, key=len, reverse=True):
        core = number.lstrip("0")
        if len(core) < 6:
            continue
        # Leading zeros may be printed or not ("Konto 0001234567").
        pattern = r"(?<![\dA-Z])(?:0\s?)*" + r"\s?".join(re.escape(c) for c in core) + r"(?!\d)"
        text = re.sub(pattern, hide, text)
    return text


def _institution(lines: list[str]) -> str:
    """The bank's own name, "VR Bank Musterstadt eG", from the top of page 1."""
    for s in lines[:12]:
        if _BANK_NAME_RE.search(s) and not re.search(r"\d|@|www\.|:", s) and len(s.split()) <= 8:
            return s
    return INSTITUTION


def _iso(raw: str, opening: str, closing: str) -> str:
    """A booking day as YYYY-MM-DD. One without its year ("15.03.") takes
    the year that puts it between the opening and closing Kontostand dates,
    which an annual statement needs; failing that, the year nearest the
    closing date. ValueError if there is no such day."""
    m = re.match(r"^(\d{2})\.(\d{2})\.$", raw)
    if m and opening:
        low, high = date.fromisoformat(opening), date.fromisoformat(closing)
        for year in range(high.year, low.year - 1, -1):
            try:
                day = date(year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
            if low <= day <= high:
                return day.isoformat()
    return common.parse_german_date(raw, closing)


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [_lines(t) for t in pages_text]
    found = _find(pages, _OPENING_RE)
    if found is None:
        raise parser_common.ParserDiagnosticError(
            "no opening balance line ('alter Kontostand vom DD.MM.YYYY <amount> S|H') found",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("openingBalance",))
    open_page, open_line, m = found
    opening_date, opening = m.group(1), _amount(m.group(2), m.group(3))
    found = _find(pages, _CLOSING_RE, (open_page, open_line))
    if found is None:
        raise parser_common.ParserDiagnosticError(
            "no closing balance line ('neuer Kontostand vom DD.MM.YYYY <amount> S|H') after the bookings",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("closingBalance",))
    close_page, close_line, m = found
    closing_date, closing = m.group(1), _amount(m.group(2), m.group(3))

    def iso_or_blank(raw: str | None) -> str:
        try:
            return common.parse_german_date(raw or "")
        except ValueError:
            return ""

    opening_iso, statement_date = iso_or_blank(opening_date), iso_or_blank(closing_date)
    if not statement_date:
        statement_date, opening_iso = opening_iso, ""
    if not statement_date:
        raise parser_common.ParserDiagnosticError(
            "no date on the 'neuer Kontostand' or 'alter Kontostand' line to take the bookings' year from",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("statementDate",))

    page_one = pages[open_page][:open_line]
    account, account_type, full = _account(page_one)

    footer = _footer_starts(pages)
    transactions: list[dict] = []
    descriptions: list[list[str]] = []
    unread: list[dict] = []
    reading = None  # the index of the booking whose description lines follow
    for p in range(open_page, close_page + 1):
        lines = pages[p]
        first = open_line + 1 if p == open_page else 0
        last = close_line if p == close_page else footer[p]
        # A page the bookings carry on to repeats the header above them,
        # which is skipped up to its "Bu-Tag Wert Vorgang" line; the lines
        # after that, up to the first booking, carry on the last page's
        # last booking. A page that prints no such line is skipped up to
        # its first booking.
        header_at = None
        if p > open_page:
            header_at = next((n for n in range(first, last) if _HEADER_RE.search(pages[p][n])), None)
            if header_at is None:
                reading = None
        in_header = p > open_page
        booked = False  # a booking read on this page yet
        paused = False  # an Übertrag below this page's bookings: the rest is the page's foot
        for n in range(first, last):
            s = lines[n]
            dated = _TWO_DATES_RE.match(s)
            if in_header and not dated and (header_at is None or n <= header_at):
                continue
            in_header = False
            if _CARRY_RE.match(s):
                # "Übertrag auf Blatt 2" closes a page's bookings, and
                # "Übertrag von Blatt 1" opens the next page's.
                paused = booked
                continue
            b = _BOOKING_RE.match(s) if dated else None
            day = None
            if b:
                try:
                    day = _iso(b.group(1), opening_iso, statement_date)
                except ValueError:
                    day = None
            if day:
                transactions.append({"date": day, "amount": _amount(b.group(4), b.group(5)), "balance": None})
                descriptions.append([_REFERENCE_RE.sub("", b.group(3)) or "Buchung"])
                reading, booked, paused = len(transactions) - 1, True, False
            elif dated:
                unread.append({"page": p + 1, "line": n + 1, "text": s})
                reading = None
            elif (reading is not None and not paused and s
                  and not _RULE_RE.match(s) and not _CODE_RE.match(s)):
                descriptions[reading].append(s)

    # A dated line ending in a marked amount outside the bookings is a
    # booking in a part of the statement this parser doesn't know:
    # reported, not dropped.
    for q, lines in enumerate(pages):
        for n, s in enumerate(lines):
            if (open_page, open_line) <= (q, n) <= (close_page, close_line):
                continue
            if _DATED_AMOUNT_RE.match(s):
                unread.append({"page": q + 1, "line": n + 1, "text": s})
    unread.sort(key=lambda line: (line["page"], line["line"]))

    for t, parts in zip(transactions, descriptions):
        t["description"] = _mask(" ".join(parts), full)
    common.apply_running_balance(transactions, opening)
    common.tag_account(transactions, account, account_type)
    keys = ["date", "description", "amount", "balance", "account", "accountType"]
    if _currency_accepted():
        currency = next((c.group(1) for c in map(_CURRENCY_RE.search, page_one) if c), "EUR")
        for t in transactions:
            t["currency_code"] = currency
        keys.append("currency_code")

    checks: list[dict] = [{"kind": "balance", "label": "Kontoauszug", "table": "cash_transactions",
                           "rows": list(range(len(transactions))), "opening": opening, "closing": closing}]
    if unread:
        checks.append({"kind": "unread", "label": "Kontoauszug", "lines": unread})

    return {
        "institution": _institution(pages[0]),
        "statementDate": statement_date,
        "transactions": [{k: t[k] for k in keys} for t in transactions],
        "checks": checks,
    }
