#!/usr/bin/env python3
"""Generates tests/fixtures/n26-checking-synthetic-sample.pdf, the demo
statement behind tests/test_n26_checking.py.

Every name, number and address here is invented: the holder, the payees,
the references and the IBANs are made up (every IBAN's check digits are 00,
which no real IBAN has), so the fixture can live in git. N26's BIC is the
bank's own. The layout follows N26's monthly Kontoauszug in German:

  - every page: "Kontoauszug Nr. N/YYYY", the period "DD.MM.YYYY bis
    DD.MM.YYYY" and, on a page of bookings, the column header "Beschreibung
    Verbuchungsdatum Betrag"; at its foot the holder's name and "Erstellt
    am", their address and the date, "IBAN: … • BIC: …" with the
    statement's number, then the page number "N / M"
  - each booking a line with the payee, the booking date and the amount,
    signed and followed by "€"; below it the rest of a long payee's name,
    the kind of booking (a card payment's "Mastercard • <Kategorie>", or
    "Lastschriften" or "Gutschriften"), the other party's IBAN and BIC, the
    reference, and "Wertstellung DD.MM.YYYY", which ends it
  - a booking cut by the page break, carrying on below page 2's header; a
    cash withdrawal at a Sparkasse's machine on page 1, so the pages a
    parser's detect() reads name a Sparkasse; a SEPA reference with its own
    "EUR" amount; a transfer in whose reference repeats the holder's IBAN
  - a page of its own summing the month up ("Dein alter Kontostand",
    outgoing, incoming, "Dein neuer Kontostand"), then a page of notes

The month adds up: the opening Kontostand plus the bookings is the closing
one, and the money out and in are the outgoing and incoming totals.

Regenerate with:  python3 tests/generators/gen-n26-checking-sample.py

Needs pdfminer (pdfplumber's), for the font's widths: amounts are set
right-aligned, as the statement sets them.
"""

import os

from pdfminer.fontmetrics import FONT_METRICS

PAGE_W, PAGE_H = 595, 842
FONT_SIZE = 8
LINE_H = 11
X_LEFT = 40
X_DATE = 380  # a booking's date starts here
X_AMOUNT = 555  # amounts, and the foot's right-hand column, end here
TOP = 800

NUMBER = "3/2027"
PERIOD = ("01.03.2027", "31.03.2027")
CREATED = "02.04.2027"
HOLDER = "Jana Musterfrau"
ADDRESS = "Am Beispielpark 4, 12345 Musterstadt"
IBAN = "DE00100110010123456789"
BIC = "NTSBDEB1XXX"
OPENING_BALANCE = 1482.35


def card(payee, day, amount, category, value):
    return (payee, day, amount, [f"Mastercard • {category}"], value)


def debit(payee, day, amount, iban, bic, reference):
    return (payee, day, amount, ["Lastschriften", f"IBAN: {iban} • BIC: {bic}", *reference], day)


def credit(payee, day, amount, iban, bic, reference):
    return (payee, day, amount, ["Gutschriften", f"IBAN: {iban} • BIC: {bic}", *reference], day)


# (payee, booking date, amount, detail lines, value date). A payee too long
# for its column carries on on the line below, split where it is written
# here with "|".
PAGE_1 = [
    card("Bäckerei Kornblume", "01.03.2027", -6.40, "Lebensmittel", "28.02.2027"),
    debit("Beispiel Wohnbau eG", "01.03.2027", -945.00, "DE00999910011234567890", "BEISDEHHXXX",
          ["Miete März 2027 Whg. 3 links"]),
    credit("Musterwerk Feinoptik GmbH", "02.03.2027", 3215.60, "DE00999920020987654321", "MUSTDEFFXXX",
           ["Lohn/Gehalt 02/2027"]),
    card("Sparkasse Musterstadt", "04.03.2027", -150.00, "Bargeld", "03.03.2027"),
    debit("Stadtwerke Musterstadt Energie und Wasser|Versorgung GmbH", "05.03.2027", -78.00,
          "DE00999930031122334455", "SWMUDE2HXXX", ["Abschlag Strom 03/2027 Vertrag 4400123 78,00 EUR"]),
    card("Buchhandlung Seitenweise", "09.03.2027", -24.90, "Freizeit & Unterhaltung", "08.03.2027"),
]
# Cut by the page break after its first detail line.
CUT = debit("Versicherung Beispiel AG", "10.03.2027", -32.15, "DE00999940040011223344", "VBAGDE66XXX",
            ["Beitrag Hausrat 03/2027 Vers.-Nr. HR-552013"])
CUT_AFTER = 1
PAGE_2 = [
    credit(HOLDER, "12.03.2027", 250.00, "DE00999950050099887766", "ZWEIDEFFXXX",
           [f"Umbuchung auf {IBAN}"]),
    card("Drogerie Beispielmarkt", "15.03.2027", -17.85, "Haushalt & Nebenkosten", "14.03.2027"),
    debit("Mobilfunk Muster GmbH", "18.03.2027", -19.99, "DE00999960060055443322", "MOBMDEMMXXX",
          ["Rechnung 03/2027 Kd.-Nr. 77120450"]),
    card("Tankstelle am Ring", "22.03.2027", -61.30, "Transport & Auto", "21.03.2027"),
    credit("Paul Beispiel", "25.03.2027", 42.00, "DE00999970070066778899", "FREUDEM1XXX",
           ["Anteil Geburtstagsgeschenk"]),
    card("Bio-Markt Grünzeug", "29.03.2027", -38.47, "Lebensmittel", "28.03.2027"),
]
BOOKINGS = [*PAGE_1, CUT, *PAGE_2]

NOTES = [
    "Hinweise zu deinem Kontoauszug",
    "Prüfe die Buchungen auf diesem Kontoauszug gleich, wenn du ihn erhältst, und melde uns jede, die",
    "du nicht erkennst. Antworten auf häufige Fragen zum Konto findest du im Hilfe-Bereich.",
]


def de(value: float) -> str:
    """-1234.5 -> '-1.234,50€': N26's own amounts, money in with a plus."""
    figure = f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("-" if value < 0 else "+") + figure + "€"


def money_out() -> float:
    return round(sum(b[2] for b in BOOKINGS if b[2] < 0), 2)


def money_in() -> float:
    return round(sum(b[2] for b in BOOKINGS if b[2] > 0), 2)


def closing_balance() -> float:
    return round(OPENING_BALANCE + money_out() + money_in(), 2)


_WIDTHS = FONT_METRICS["Helvetica"][1]


def _width(text: str) -> float:
    return sum(_WIDTHS.get(c, _WIDTHS["?"]) for c in text) * FONT_SIZE / 1000.0


def _booking_lines(booking, cut_after=None):
    """A booking's lines, each a list of (x, text); x below zero
    right-aligns the text at -x. With cut_after, the lines after that many
    detail lines are returned apart: the next page's."""
    payee, day, amount, details, value = booking
    names = payee.split("|")
    first = [[(X_LEFT, names[0]), (X_DATE, day), (-X_AMOUNT, de(amount))]]
    rest = [[(X_LEFT, s)] for s in [*names[1:], *details, f"Wertstellung {value}"]]
    if cut_after is None:
        return first + rest, []
    cut = len(names) - 1 + cut_after
    return first + rest[:cut], rest[cut:]


def build_pages():
    """Each page a list of (x, y, text)."""
    head = [f"Kontoauszug Nr. {NUMBER}", f"{PERIOD[0]} bis {PERIOD[1]}"]
    columns = [(X_LEFT, "Beschreibung"), (X_DATE, "Verbuchungsdatum"), (-X_AMOUNT, "Betrag")]
    bodies = []

    page1 = [[(X_LEFT, head[0])], [(X_LEFT, head[1])], columns]
    for b in PAGE_1:
        page1 += _booking_lines(b)[0]
    cut_here, cut_next = _booking_lines(CUT, CUT_AFTER)
    bodies.append(page1 + cut_here)

    page2 = [[(X_LEFT, head[0])], [(X_LEFT, head[1])], columns, *cut_next]
    for b in PAGE_2:
        page2 += _booking_lines(b)[0]
    bodies.append(page2)

    bodies.append([[(X_LEFT, f"Zusammenfassung Nr. {NUMBER}")], [(X_LEFT, head[1])], [(X_LEFT, "Beschreibung")],
                   *[[(X_LEFT, label), (-X_AMOUNT, de(value))] for label, value in (
                       ("Dein alter Kontostand", OPENING_BALANCE), ("Ausgehende Transaktionen", money_out()),
                       ("Eingehende Transaktionen", money_in()), ("Dein neuer Kontostand", closing_balance()))]])
    bodies.append([[(X_LEFT, "Kontoauszug")], [(X_LEFT, head[1])], *[[(X_LEFT, s)] for s in NOTES]])

    pages = []
    for n, body in enumerate(bodies, 1):
        items, y = [], TOP
        for line in body:
            items.extend((x, y, text) for x, text in line)
            y -= LINE_H
        for y, left, right in ((95, HOLDER, "Erstellt am"), (84, ADDRESS, CREATED),
                               (73, f"IBAN: {IBAN} • BIC: {BIC}", f"Nr. {NUMBER}")):
            items += [(X_LEFT, y, left), (-X_AMOUNT, y, right)]
        number = f"{n} / {len(bodies)}"
        items.append(((PAGE_W - _width(number)) / 2, 50, number))
        pages.append(items)
    return pages


def escape(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("cp1252")


def build_pdf(pages, path):
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}

    def add_obj(num: int, body: bytes):
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    page_obj_nums = [4 + 2 * i for i in range(len(pages))]
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    add_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    # WinAnsiEncoding, so umlauts, "•" and "€" extract as they print.
    add_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    for i, items in enumerate(pages):
        page_num, content_num = page_obj_nums[i], page_obj_nums[i] + 1
        add_obj(page_num, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode())
        stream = bytearray()
        for x, y, s in items:
            if x < 0:
                x = -x - _width(s)
            stream.extend(f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm (".encode())
            stream.extend(escape(s))
            stream.extend(b") Tj ET\n")
        add_obj(content_num, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream")

    xref_pos = len(out)
    count = max(offsets) + 1
    out.extend(f"xref\n0 {count}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for num in range(1, count):
        out.extend(f"{offsets[num]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())

    with open(path, "wb") as f:
        f.write(bytes(out))


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "n26-checking-synthetic-sample.pdf")


def main(path: str = OUT):
    build_pdf(build_pages(), path)
    print(f"wrote {path}")
    print(f"  {len(BOOKINGS)} bookings, opening {de(OPENING_BALANCE)}, out {de(money_out())}, "
          f"in {de(money_in())}, closing {de(closing_balance())}")


if __name__ == "__main__":
    main()
