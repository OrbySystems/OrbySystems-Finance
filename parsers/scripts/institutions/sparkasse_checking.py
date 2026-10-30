"""Sparkasse Girokonto statement (Kontoauszug) parser.

Format: the PDF Kontoauszug a Sparkasse sends to its online banking
customers. The Sparkassen (some 350 of them, each its own bank) share one
layout, so this reads any of them. Page 1, after the bank's name and the
holder's address:

    Kontoauszug 10/2026 Blatt 1 von 4
    Girokonto 1234567, DE12 3005 0000 0001 2345 67
    Datum Erläuterung Betrag EUR
    Kontostand am 30.09.2026, Auszug Nr. 9 1.204,17
    01.10.2026Lastschrift -57,84
    Stadtwerke Musterstadt GmbH Abschlag 10/2026
    Mandat 4711 Gläubiger-ID DE98ZZZ09999999999
    02.10.2026Gutschrift 2.350,00
    Muster GmbH Gehalt Oktober
    Kontostand am 31.10.2026 um 20:05 Uhr 3.496,33

Each booking is a line that starts with its date, run into the booking
text, and ends with the signed amount in German form (-2.417,36); the
lines below it, up to the next booking, describe it. The bookings run from
the first Kontostand line to the second, across pages when there are many:
each page repeats the header above them and the bank's footer below them,
and both are skipped. Fee and interest statements follow as attachments
(Entgeltabrechnung, Rechnungsabschluss, with trailing-minus amounts like
318,26-), then notes; their totals are already bookings, so they are not
read.

Amounts are printed in the sign this codebase uses (money out negative),
in the currency the column header names ("Betrag EUR"; EUR if it names
none), which every row carries as currency_code when the app accepts it.
The statement prints no running balance; one is derived from the opening
Kontostand. The statement's own arithmetic is reported as checks: opening
Kontostand plus every booking is the closing Kontostand, and every dated
line that looks like a booking but was not read is listed (CONTRACT.md,
"Checks").

Built from a scrambled sample of a real statement (README_addparser.md).
The scrambler of the time knew no German: every German word in the sample
was faked, and so were the digits of every DD.MM.YYYY date. So the section
is found by the shape of its lines - the opening Kontostand line's date
followed by a comma, the closing one's starting with the same two words -
and never by a word the sample faked. detect() takes the statement's own
words (Sparkasse, Kontoauszug, Kontostand, a DE IBAN), or the name
Sparkasse with that layout.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
PARSER_REVISION = 2

INSTITUTION = "Sparkasse"

# The German helpers are common.py's. A copy delivered as a drop-in runs
# against the common.py of the user's installed app, and apps released
# before the helpers were added (1.0.2 and earlier) don't have them, so it
# falls back to these. tests/test_sparkasse_checking.py holds the two to
# the same answers.
_AMOUNT_FALLBACK = r"[+-]?\s?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?:\s?[+-])?"
_AMOUNT = getattr(common, "GERMAN_AMOUNT", _AMOUNT_FALLBACK)


def _amount(raw: str) -> float:
    if hasattr(common, "parse_german_amount"):
        return common.parse_german_amount(raw)
    s = re.sub(r"\s", "", raw)
    value = float(s.strip("+-").replace(".", "").replace(",", "."))
    return -value if "-" in s else value


def _date(raw: str) -> str:
    """DD.MM.YYYY as YYYY-MM-DD; ValueError if there is no such day."""
    if hasattr(common, "parse_german_date"):
        return common.parse_german_date(raw)
    return datetime.strptime(raw, "%d.%m.%Y").strftime("%Y-%m-%d")


_DATE = r"\d{2}\.\d{2}\.\d{4}"

# The opening balance: "Kontostand am 30.09.2026, Auszug Nr. 9 1.204,17".
# Two words, the date and a comma - the comma tells it from the closing
# line - then anything, then the amount.
_OPENING_RE = re.compile(r"^([^\d\s]\S*\s+\S+)\s+(" + _DATE + r"),\s.*?\s(" + _AMOUNT + r")$")
# The same line by its words, for a statement that prints no comma there;
# never the closing line, which has the time.
_OPENING_WORDS_RE = re.compile(r"^(Kontostand\s+am)\s+(" + _DATE + r")\b(?!.*\d:\d{2}).*?\s(" + _AMOUNT + r")$")

# A booking: "01.10.2026Lastschrift -57,84", the date run into the text.
_BOOKING_RE = re.compile(r"^(" + _DATE + r")\s*(\S.*?)\s+(" + _AMOUNT + r")$")
# Any line that starts with a date. In the bookings, one not read as a
# booking is reported; elsewhere, only one that also ends with an amount.
_DATED_RE = re.compile(r"^" + _DATE)
_ENDS_WITH_AMOUNT_RE = re.compile(r"\s" + _AMOUNT + r"$")

# "DE12 3005 0000 0001 2345 67": a German IBAN, 22 characters. Read by its
# shape, any two letters; detect() asks for DE.
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?\d{4}){4}\s?\d{2})\b")
_DE_IBAN_RE = re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b")

# A savings product's name on the account line ("Tagesgeld", "Sparkonto",
# "S-Prämiensparen"); "Sparkasse" itself is not one.
_SAVINGS_RE = re.compile(r"tagesgeld|festgeld|spar(?!kasse)", re.I)

# The column header names the amounts' currency: "Datum Erläuterung Betrag EUR".
_CURRENCY_RE = re.compile(r"\bBetrag\s+([A-Z]{3})$")


def _currency_accepted() -> bool:
    """Whether the app running this accepts currency_code on a row. It does
    from the release after 1.0.2 on, whose parser_common brought
    normalize_currency_codes with it; 1.0.2 and earlier reject the key, and
    with it the statement. A copy delivered to an older app leaves it out,
    and its rows import as US dollars until a re-import on a newer app
    corrects them in place (orby-core docs/currency-on-cash-rows.md)."""
    return hasattr(parser_common, "normalize_currency_codes")


def detect(head_text: str) -> tuple[bool, str]:
    if not re.search(r"sparkasse", head_text, re.I):
        return False, "'Sparkasse' not found"
    lines = _lines(head_text)
    if "Kontoauszug" in head_text and "Kontostand" in head_text and _DE_IBAN_RE.search(head_text):
        return True, "matched Sparkasse Kontoauszug (Kontoauszug, Kontostand, DE IBAN)"
    if _IBAN_RE.search(head_text) and any(_OPENING_RE.match(s) for s in lines):
        return True, "matched Sparkasse Kontoauszug by its layout (IBAN, opening balance line)"
    return False, "'Sparkasse' found, but no Kontoauszug: no IBAN and opening balance line ('Kontostand am DD.MM.YYYY, Auszug Nr. N')"


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def _footer_starts(pages: list[list[str]]) -> list[int]:
    """Where each page's footer begins: the run of lines at its end that
    another page ends with too (the bank's address, board and register).
    A booking is never footer, however alike two pages end."""
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


def _opening(pages: list[list[str]]) -> tuple[int, int, re.Match] | None:
    for regex in (_OPENING_RE, _OPENING_WORDS_RE):
        for p, lines in enumerate(pages):
            for n, s in enumerate(lines):
                m = regex.match(s)
                if m:
                    return p, n, m
    return None


def _account(lines: list[str]) -> tuple[str, str]:
    """The account's last four digits and its type, from the IBAN line
    above the bookings: "Girokonto 1234567, DE12 …"."""
    for s in lines:
        m = _IBAN_RE.search(s)
        if m:
            product = re.sub(r"[\d,]", " ", s[:m.start()])
            return common.last4_digits(m.group(1)), "Savings" if _SAVINGS_RE.search(product) else "Checking"
    return "", "Checking"


def _institution(lines: list[str]) -> str:
    """The bank's own name, "Sparkasse Musterstadt", from the top of page
    1: the first short line naming a Sparkasse that isn't the logo."""
    for s in lines:
        if (re.search(r"sparkasse", s, re.I) and not re.match(r"^\S?\s*Sparkasse$", s)
                and not re.search(r"\d|@|www\.|:", s) and len(s.split()) <= 6):
            return s
    return INSTITUTION


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [_lines(t) for t in pages_text]
    found = _opening(pages)
    if found is None:
        raise parser_common.ParserDiagnosticError(
            "no opening balance line ('Kontostand am DD.MM.YYYY, Auszug Nr. N <amount>') found",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("openingBalance",))
    open_page, open_line, m = found
    label, opening_date, opening = m.group(1), m.group(2), _amount(m.group(3))
    # The closing balance starts with the opening's two words and a date
    # with no comma after it: "Kontostand am 31.10.2026 um 20:05 Uhr …".
    closing_re = re.compile(r"^" + re.escape(label) + r"\s+(" + _DATE + r")(?!,)\b.*?\s(" + _AMOUNT + r")$")
    # The same words with the comma: another opening line, never a booking.
    balance_line_re = re.compile(r"^" + re.escape(label) + r"\s+" + _DATE + r"\b")

    footer = _footer_starts(pages)
    transactions: list[dict] = []
    descriptions: list[list[str]] = []
    unread: list[dict] = []
    closing = closing_date = close_at = None
    reading = None  # the index of the booking whose description lines follow
    for p in range(open_page, len(pages)):
        lines = pages[p]
        # A page the bookings carry on to repeats the header above them;
        # it is skipped up to the first booking.
        in_header = p > open_page
        first = open_line + 1 if p == open_page else 0
        for n in range(first, footer[p]):
            s = lines[n]
            if not s:
                continue
            c = closing_re.match(s)
            if c:
                closing_date, closing, close_at = c.group(1), _amount(c.group(2)), (p, n)
                break
            if balance_line_re.match(s):
                reading = None
                continue
            dated = _DATED_RE.match(s)
            if in_header and not dated:
                continue
            in_header = False
            b = _BOOKING_RE.match(s) if dated else None
            if b:
                try:
                    date = _date(b.group(1))
                except ValueError:
                    b = None
            if b:
                transactions.append({"date": date, "amount": _amount(b.group(3)), "balance": None})
                descriptions.append([b.group(2)])
                reading = len(transactions) - 1
            elif dated:
                unread.append({"page": p + 1, "line": n + 1, "text": s})
                reading = None
            elif reading is not None:
                descriptions[reading].append(s)
        if closing is not None:
            break
        reading = None
    if closing is None:
        raise parser_common.ParserDiagnosticError(
            "no closing balance line ('Kontostand am DD.MM.YYYY um HH:MM Uhr <amount>') after the bookings",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("closingBalance",))

    # A dated line ending in an amount outside the bookings is a booking in
    # a part of the statement this parser doesn't know: reported, not dropped.
    for q, lines in enumerate(pages):
        for n, s in enumerate(lines):
            if (open_page, open_line) <= (q, n) <= close_at:
                continue
            if _DATED_RE.match(s) and _ENDS_WITH_AMOUNT_RE.search(s):
                unread.append({"page": q + 1, "line": n + 1, "text": s})
    unread.sort(key=lambda line: (line["page"], line["line"]))

    for t, parts in zip(transactions, descriptions):
        t["description"] = " ".join(parts)
    common.apply_running_balance(transactions, opening)
    page_one = pages[open_page][:open_line]
    account, account_type = _account(page_one)
    common.tag_account(transactions, account, account_type)
    keys = ["date", "description", "amount", "balance", "account", "accountType"]
    if _currency_accepted():
        currency = next((m.group(1) for m in map(_CURRENCY_RE.search, page_one) if m), "EUR")
        for t in transactions:
            t["currency_code"] = currency
        keys.append("currency_code")

    checks: list[dict] = [{"kind": "balance", "label": "Kontoauszug", "table": "cash_transactions",
                           "rows": list(range(len(transactions))), "opening": opening, "closing": closing}]
    if unread:
        checks.append({"kind": "unread", "label": "Kontoauszug", "lines": unread})

    statement_date = ""
    for raw in (closing_date, opening_date):
        try:
            statement_date = _date(raw)
            break
        except ValueError:
            continue

    return {
        "institution": _institution(pages[0]),
        "statementDate": statement_date,
        "transactions": [{k: t[k] for k in keys} for t in transactions],
        "checks": checks,
    }
