"""N26 account statement (Kontoauszug) parser.

Format: the PDF Kontoauszug N26 issues for a month, in German. Every page
of bookings has the same three lines at its top and its foot:

    Kontoauszug Nr. 5/2027
    01.05.2027 bis 31.05.2027
    Beschreibung Verbuchungsdatum Betrag
    Beispiel Markt GmbH 03.05.2027 -42,17€
    Mastercard • Lebensmittel
    Wertstellung 02.05.2027
    Max Mustermann 06.05.2027 +1.500,00€
    <Art der Buchung>
    IBAN: DE12 3456 7890 1234 5678 90 • BIC: ABCDDEFFXXX
    Miete Mai
    Wertstellung 06.05.2027
    ...
    Max Mustermann Erstellt am
    Musterstraße 1, 12345 Musterstadt 01.06.2027
    IBAN: DE.. • BIC: NTSBDEB1XXX Nr. 5/2027
    1 / 4

Each booking is a line that ends with its booking date and its amount,
signed and followed by "€"; the lines below it, up to its "Wertstellung"
(value date) line, describe it: the rest of the payee's name, the kind of
booking ("Mastercard • <Kategorie>", or a heading saying it is a direct
debit or a credit), the other party's IBAN and BIC, and the reference. A
booking that a page break cuts carries on below the next page's header. A
page of its own, after the bookings, sums the month up:

    Dein alter Kontostand +1.234,56€
    Ausgehende Transaktionen -2.000,00€
    Eingehende Transaktionen +3.000,00€
    Dein neuer Kontostand +2.234,56€

Amounts are read as printed, in the sign this codebase uses, and in euros,
which every row carries as currency_code when the app accepts it. The
statement prints no running balance; one is derived from the opening
Kontostand. The statement's own arithmetic is reported as checks: the
opening Kontostand plus every booking is the closing one, the money out is
the outgoing total and the money in the incoming one, and every line that
ends in a signed euro amount but was not read is listed (CONTRACT.md,
"Checks").

Built from a scrambled sample of a real statement (README_addparser.md),
which faked most words, N26's own name among them: detect() reads the
layout, not the bank's name. The other party's IBAN and BIC are left out of
a booking's description; the holder's own IBAN is masked to its last four
digits wherever a description repeats it.
"""

import re
from datetime import date

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 2

INSTITUTION = "N26"

_FIGURE = r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}"
# An amount at the end of a line, as N26 prints its own: signed and
# followed by "€" ("-1.204,50€", "+18,40 €"), a zero perhaps unsigned
# ("0,00€"). An amount in a SEPA reference is written "85,00 EUR", never
# so: the reference can't carry "€".
_EURO = r"([+-]|(?=0,00))\s?(" + _FIGURE + r")\s?€"
_DATE = r"\d{2}\.\d{2}\.\d{4}"

# A booking: "Beispiel Markt GmbH 03.05.2027 -42,17€".
_BOOKING_RE = re.compile(r"^(.*?)\s*(" + _DATE + r")\s+" + _EURO + r"$")
# A line that ends in a signed euro amount the way a booking does: one not
# read as a booking or a summary line is reported.
_AMOUNT_LINE_RE = re.compile(r"[+-]\s?" + _FIGURE + r"\s?€$")
# The summary's lines: "Dein alter Kontostand +1.234,56€", no date.
_SUMMARY_LINE_RE = re.compile(r"^(\D*?\S)\s+" + _EURO + r"$")
_OPENING_RE = re.compile(r"\balter\s+Kontostand\b|\bold\s+balance\b", re.I)
_CLOSING_RE = re.compile(r"\bneuer\s+Kontostand\b|\bnew\s+balance\b", re.I)
# The line that ends a booking's description: "Wertstellung 02.05.2027".
_VALUE_DATE_RE = re.compile(r"^(?:Wertstellung|Value\s+date)\b\s*:?\s*" + _DATE + r"$", re.I)
# The statement's period, on each page's second line: "01.05.2027 bis 31.05.2027".
_PERIOD_RE = re.compile(r"^(" + _DATE + r")\s+\S+\s+(" + _DATE + r")$")
# The column header that ends a page's header.
_COLUMNS_RE = re.compile(r"\b(?:Betrag|Amount)$")
# An IBAN and BIC line, a booking's or the holder's in the page's foot.
_IBAN_LINE_RE = re.compile(r"^IBAN:?\s*([A-Z]{2}\d{2}(?:\s?[A-Z0-9]){10,30}?)\s*[•·|]\s*BIC\b")
_PAGE_NUMBER_RE = re.compile(r"^\d+\s*/\s*\d+$")
# A page number printed inside the foot's last line: "… BIC: … 1 / 4 Nr. 5/2027".
_INLINE_PAGE_NUMBER_RE = re.compile(r"\s\d{1,3}\s/\s\d{1,3}(?=\s|$)")
# N26's BIC, which the holder's "IBAN: … • BIC:" line in the foot carries.
# Anywhere else it is no sign of N26: another bank's booking can name an
# N26 account.
_N26_BIC_RE = re.compile(r"\bBIC\b:?\s*NTSBDEB1")


def _currency_accepted() -> bool:
    """Whether the app running this accepts currency_code on a row: from
    the release after 1.0.2 on (orby-core docs/currency-on-cash-rows.md)."""
    return hasattr(parser_common, "normalize_currency_codes")


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def detect(head_text: str) -> tuple[bool, str]:
    """An N26 statement, German or English, by its layout: the scrambled
    sample it was built from faked N26's name and BIC. Its bookings (a line
    ending in a date and a signed € amount, then a Wertstellung line), or
    for a month without any its Kontostand lines, or N26's BIC on an
    "IBAN: … • BIC:" line; and the holder's "IBAN: … • BIC:" line."""
    lines = _lines(head_text)
    bookings = (any(_BOOKING_RE.match(s) for s in lines)
                and any(_VALUE_DATE_RE.match(s) for s in lines))
    balances = any((m := _SUMMARY_LINE_RE.match(s)) and (_OPENING_RE.search(m.group(1)) or _CLOSING_RE.search(m.group(1)))
                   for s in lines)
    iban_lines = [s for s in lines if _IBAN_LINE_RE.match(s)]
    missing = [name for name, found in (
        ("Kontoauszug or Statement", re.search(r"\bKontoauszug\b|\bStatement\b", head_text)),
        ("bookings ('DD.MM.YYYY ±N,NN€', then Wertstellung) or a Kontostand line",
         bookings or balances or any(_N26_BIC_RE.search(s) for s in iban_lines)),
        ("'IBAN: … • BIC:' line", iban_lines),
    ) if not found]
    if missing:
        return False, "N26 Kontoauszug marker(s) not found: " + ", ".join(missing)
    return True, "matched N26 Kontoauszug (Kontoauszug, bookings or Kontostand ending in a signed €, IBAN • BIC)"


def _amount(sign: str | None, figure: str) -> float:
    value = float(figure.replace(".", "").replace(",", "."))
    return -value if sign == "-" else value


def _iso(raw: str) -> str:
    day, month, year = raw.split(".")
    return date(int(year), int(month), int(day)).isoformat()


def _without_page_number(lines: list[str]) -> list[str]:
    while lines and not lines[-1]:
        lines = lines[:-1]
    if lines and _PAGE_NUMBER_RE.match(lines[-1]):
        lines = lines[:-1]
    return lines


def _footer_starts(pages: list[list[str]]) -> list[int]:
    """Where each page's footer begins: the run of lines at its end, its
    page number aside, that more than half of the other pages end with too
    (the only other, for two pages), or where most of them print no foot,
    that another page ends with. A booking or a Wertstellung line is never
    footer, and neither is a summary line. Two bookings that page breaks
    cut after the same detail line (a direct debit's heading) end their two
    pages alike, but not the rest: the line stays theirs."""
    # A page number inside the foot's last line would make every page's
    # foot differ: it is left out of the comparison.
    bodies = [[_INLINE_PAGE_NUMBER_RE.sub("", s) for s in _without_page_number(p)] for p in pages]
    starts = []
    for i, lines in enumerate(bodies):
        shared = []
        for j, other in enumerate(bodies):
            if i == j:
                continue
            k = 0
            while (k < len(lines) and k < len(other) and lines[-1 - k] == other[-1 - k]
                   and not _BOOKING_RE.match(lines[-1 - k]) and not _VALUE_DATE_RE.match(lines[-1 - k])
                   and not _SUMMARY_LINE_RE.match(lines[-1 - k])):
                k += 1
            shared.append(k)
        # The longest run that more than half of the others share, else
        # the longest any other shares.
        shared.sort(reverse=True)
        most = shared[len(shared) // 2] if shared else 0
        starts.append(len(lines) - (most or (shared[0] if shared else 0)))
    return starts


def _header_end(lines: list[str]) -> int:
    """The index of a page's first line below its header: the line after
    the column header, else after the period line, within the top lines."""
    top = lines[:6]
    for n, s in enumerate(top):
        if _COLUMNS_RE.search(s) and not _BOOKING_RE.match(s):
            return n + 1
    for n, s in enumerate(top):
        if _PERIOD_RE.match(s):
            return n + 1
    return 0


def _own_iban(pages: list[list[str]], footers: list[int]) -> str:
    """The holder's IBAN: the one in the pages' foot, else the one most
    pages print."""
    in_foot: dict[str, int] = {}
    anywhere: dict[str, int] = {}
    for lines, start in zip(pages, footers):
        seen = set()
        for n, s in enumerate(lines):
            m = _IBAN_LINE_RE.match(s)
            if not m:
                continue
            iban = re.sub(r"\s", "", m.group(1))
            if n >= start:
                in_foot[iban] = in_foot.get(iban, 0) + 1
            if iban not in seen:
                anywhere[iban] = anywhere.get(iban, 0) + 1
                seen.add(iban)
    for counts in (in_foot, anywhere):
        if counts:
            best = max(counts.values())
            if counts is in_foot or best > 1 or len(pages) == 1:
                return min(iban for iban, c in counts.items() if c == best)
    return ""


def _mask(text: str, iban: str) -> str:
    """The holder's own IBAN, wherever a description repeats it, down to
    its last four digits; and the account number inside it."""
    def hide(m: re.Match) -> str:
        figure = re.sub(r"\s", "", m.group(0))
        return "*" * (len(figure) - 4) + figure[-4:]

    for number in (iban, iban[12:].lstrip("0") if iban.startswith("DE") else ""):
        if len(number) < 6:
            continue
        pattern = r"(?<![\dA-Z])" + r"\s?".join(re.escape(c) for c in number) + r"(?!\d)"
        text = re.sub(pattern, hide, text)
    return text


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [_lines(t) for t in pages_text]
    footers = _footer_starts(pages)

    period = None
    for lines in pages:
        period = next((m for m in map(_PERIOD_RE.match, lines[:6]) if m), None)
        if period:
            break

    transactions: list[dict] = []
    details: list[list[str]] = []
    unread: list[dict] = []
    # The summary blocks: each a list of (label, amount), the opening
    # Kontostand first, and the index of the first booking it sums up.
    summaries: list[dict] = []
    block = None
    reading = None  # the booking whose description lines follow
    for p, lines in enumerate(pages):
        first, last = _header_end(lines), footers[p]
        for n in range(first, last):
            s = lines[n]
            if not s or _PAGE_NUMBER_RE.match(s):
                continue
            b = _BOOKING_RE.match(s)
            if b:
                block = None
                try:
                    day = _iso(b.group(2))
                except ValueError:
                    unread.append({"page": p + 1, "line": n + 1, "text": s})
                    reading = None
                    continue
                transactions.append({"date": day, "amount": _amount(b.group(3), b.group(4)), "balance": None})
                details.append([b.group(1)])
                reading = len(transactions) - 1
                continue
            m = _SUMMARY_LINE_RE.match(s)
            if m and (_OPENING_RE.search(m.group(1)) or block is not None):
                if _OPENING_RE.search(m.group(1)):
                    block = {"lines": [], "at": [], "from": summaries[-1]["to"] if summaries else 0, "to": len(transactions)}
                    summaries.append(block)
                block["lines"].append((m.group(1), _amount(m.group(2), m.group(3))))
                block["at"].append({"page": p + 1, "line": n + 1, "text": s})
                if _CLOSING_RE.search(m.group(1)):
                    block = None
                reading = None
                continue
            block = None
            if _VALUE_DATE_RE.match(s):
                reading = None
                continue
            if _AMOUNT_LINE_RE.search(s):
                unread.append({"page": p + 1, "line": n + 1, "text": s})
                continue
            if reading is not None and not _IBAN_LINE_RE.match(s):
                details[reading].append(s)
    # One summary sums up every booking, wherever it is printed; of
    # several, each sums up the bookings above it, and the last also those
    # below it.
    if len(summaries) == 1:
        summaries[0]["from"], summaries[0]["to"] = 0, len(transactions)
    elif summaries:
        summaries[-1]["to"] = max(summaries[-1]["to"], len(transactions))

    if not transactions and not summaries:
        raise parser_common.ParserDiagnosticError(
            "no booking ('<payee> DD.MM.YYYY ±N,NN€') and no Kontostand summary found",
            code="PARSER_REQUIRED_DATA_MISSING", stage="transactions", missing_fields=("transactions",))

    if period:
        statement_date = _iso(period.group(2))
    elif transactions:
        statement_date = max(t["date"] for t in transactions)
    else:
        raise parser_common.ParserDiagnosticError(
            "no statement period ('DD.MM.YYYY bis DD.MM.YYYY') and no booking to date the statement by",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("statementDate",))

    iban = _own_iban(pages, footers)
    for t, parts in zip(transactions, details):
        t["description"] = _mask(" ".join(x for x in parts if x), iban) or "Buchung"

    checks: list[dict] = []
    for s in summaries:
        rows = list(range(s["from"], s["to"]))
        opening = next((v for label, v in s["lines"] if _OPENING_RE.search(label)), None)
        closing = next((v for label, v in s["lines"] if _CLOSING_RE.search(label)), None)
        label = next((label for label, _ in s["lines"] if _CLOSING_RE.search(label)), "Kontoauszug")
        if opening is None or closing is None:
            # A summary with no closing Kontostand: its lines are reported.
            unread.extend(s["at"])
            continue
        checks.append({"kind": "balance", "label": label, "table": "cash_transactions",
                       "rows": rows, "opening": opening, "closing": closing})
        middle = [(label, v) for label, v in s["lines"]
                  if not _OPENING_RE.search(label) and not _CLOSING_RE.search(label)]
        for want_out in (True, False):
            same = [(label, v) for label, v in middle
                    if (v < 0 if want_out else v > 0)
                    or (v == 0 and re.search(r"ausgeh|outgoing" if want_out else r"eingeh|incoming", label, re.I))]
            if len(same) == 1:
                checks.append({"kind": "sum", "label": same[0][0], "table": "cash_transactions",
                               "rows": [i for i in rows if (transactions[i]["amount"] < 0) == want_out
                                        and transactions[i]["amount"] != 0],
                               "expected": same[0][1]})
    if len(summaries) == 1 and checks:
        common.apply_running_balance(transactions, checks[0]["opening"])
    if unread:
        unread.sort(key=lambda line: (line["page"], line["line"]))
        checks.append({"kind": "unread", "label": "Kontoauszug", "lines": unread})

    common.tag_account(transactions, common.last4_digits(iban), "Checking")
    keys = ["date", "description", "amount", "balance", "account", "accountType"]
    if _currency_accepted():
        for t in transactions:
            t["currency_code"] = "EUR"
        keys.append("currency_code")

    return {
        "institution": INSTITUTION,
        "statementDate": statement_date,
        "transactions": [{k: t[k] for k in keys} for t in transactions],
        "checks": checks,
    }
