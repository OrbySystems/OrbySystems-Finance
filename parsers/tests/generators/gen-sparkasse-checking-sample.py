#!/usr/bin/env python3
"""Generates tests/fixtures/sparkasse-checking-synthetic-sample.pdf, the demo
statement behind tests/test_sparkasse_checking.py.

Every name, number and address here is invented ("Sparkasse Musterstadt"
is no bank; the IBAN's check digits are 00, which no real IBAN has), so the
fixture can live in git and give the Sparkasse parser regression coverage
that runs for everyone. The layout follows a real Girokonto Kontoauszug's,
as a scrambled sample of one showed it:

  - page 1: the bank's name, the holder's address, the date, then
    "Kontoauszug MM/YYYY Blatt N von M", the account line with its IBAN and
    the "Datum Erläuterung Betrag EUR" column header
  - the opening "Kontostand am DD.MM.YYYY, Auszug Nr. N", the bookings, and
    the closing "Kontostand am DD.MM.YYYY um HH:MM Uhr"
  - each booking's date run into its text ("01.10.2026Lastschrift"), the
    signed German amount at the end ("-57,84"; a credit unsigned), and its
    description lines below, one of them ending in an amount
  - the fee and interest attachments (Entgeltabrechnung, Rechnungsabschluss)
    with trailing-minus amounts ("12,40-", "1.083,52 -"), a line of their
    small print starting with a date, then the notes page
  - the same footer on every page

The sample's bookings fitted on page 1. These carry on to page 2, under the
repeated page header, which the real layout is assumed to do the same way.

Regenerate with:  python3 tests/generators/gen-sparkasse-checking-sample.py
"""

import os

PAGE_W, PAGE_H = 595, 842
FONT_SIZE = 8
LINE_H = 11
X_LEFT = 50
X_AMOUNT = 480

BANK = "Sparkasse Musterstadt"
HOLDER = "Erika Mustermann"
ACCOUNT_LINE = "Girokonto 1234567, DE00 1234 5678 0001 2345 67"
OPENING_BALANCE = -1204.17  # overdrawn, as the overdraft interest says
PAGES = 5

FOOTER = [
    f"{BANK} Vorstand: Max Beispiel (Vorsitzender), Eva Muster Sitz: Musterstadt",
    "Amtsgericht Musterstadt HRA 9999 BIC: MUSTDE00XXX USt-IdNr.: DE000000000",
    "Musterplatz 1 12345 Musterstadt www.sparkasse-musterstadt.example Telefon 01234 5678-0",
    "Sparkassen-Finanzgruppe",
]

# (date, booking text, amount as printed, description lines). Money out is
# printed with a minus, money in unsigned.
BOOKINGS = [
    ("01.10.2026", "Entgeltabrechnung", -3.90, ["siehe Anlage Nr. 1"]),
    ("01.10.2026", "Abrechnung 30.09.2026", -12.40, ["siehe Anlage Nr. 2"]),
    ("02.10.2026", "Gutschrift", 2350.00, ["Muster Werkzeugbau GmbH", "Gehalt Oktober 2026"]),
    ("02.10.2026", "Lastschrift", -57.84, ["Stadtwerke Musterstadt GmbH Abschlag Strom 10/2026 57,84-",
                                           "Mandat 0815-A Gläubiger-ID DE98ZZZ09999999999"]),
    ("05.10.2026", "Kartenzahlung / Wert: 04.10.2026", -23.45,
     ["BAECKEREI BEISPIEL//MUSTERSTADT/DE 2026-10-04T08:12 Folgenr.003", "Verfalld.2028-12"]),
    ("06.10.2026", "Dauerauftrag", -850.00, ["Hans Vermieter", "Miete Oktober Musterweg 5"]),
    ("09.10.2026", "Lastschrift", -1234.56, ["Beispiel Versicherung AG Jahresbeitrag Hausrat",
                                             "Mandat VS-77 Gläubiger-ID DE11ZZZ00000000001"]),
    # Page 1 ends here (PAGE_BREAK_AFTER).
    ("13.10.2026", "Bargeldauszahlung", -200.00, [f"{BANK} GA 0042", "DATUM 13.10.2026, 15.25 UHR"]),
    ("20.10.2026", "Überweisung", -120.00, ["Max Mustermann", "Geschenk"]),
    ("28.10.2026", "Gutschrift", 45.80, ["Versandhaus Beispiel Erstattung 4711"]),
]
PAGE_BREAK_AFTER = 7

FEE = 3.90
VAT = round(FEE * 19 / 119, 2)
INTEREST = 12.40


def de(value: float) -> str:
    """-1234.56 -> '-1.234,56': a booking's or Kontostand's amount, money in unsigned."""
    return ("-" if value < 0 else "") + _figure(value)


def de_behind(value: float, sep: str = "") -> str:
    """-12.4 -> '12,40-', or '12,40 -' with sep " ": the attachments' amounts."""
    return _figure(value) + sep + ("-" if value < 0 else "+")


def _figure(value: float) -> str:
    return f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def closing_balance() -> float:
    return round(OPENING_BALANCE + sum(b[2] for b in BOOKINGS), 2)


def build_pages():
    """Each page a list of (x, y, text)."""
    pages = []

    def page(head: list[str], body: list) -> None:
        y, items = PAGE_H - 50, []
        for line in head:
            items.append((X_LEFT, y, line))
            y -= LINE_H
        for row in body:
            if isinstance(row, tuple):  # a line with an amount in the right column
                items.append((X_LEFT, y, row[0]))
                items.append((X_AMOUNT, y, row[1]))
            else:
                items.append((X_LEFT, y, row))
            y -= LINE_H
        y = 50 + LINE_H * len(FOOTER)
        for line in FOOTER:
            items.append((X_LEFT, y, line))
            y -= LINE_H
        pages.append(items)

    def page_header(number: int) -> list[str]:
        return ["S Sparkasse", "Musterstadt", f"Kontoauszug 10/2026 Blatt {number} von {PAGES}",
                f"{ACCOUNT_LINE}, {HOLDER}"]

    def bookings(rows) -> list:
        out = []
        for date, text, amount, details in rows:
            out.append((date + text, de(amount)))
            out.extend(details)
        return out

    first, rest = BOOKINGS[:PAGE_BREAK_AFTER], BOOKINGS[PAGE_BREAK_AFTER:]
    page(["S Sparkasse", BANK, "Musterstadt", "Frau", HOLDER, "Musterweg 5", "12345 Musterstadt",
             "27. Oktober 2026", f"Kontoauszug 10/2026 Blatt 1 von {PAGES}", ACCOUNT_LINE,
             "Datum Erläuterung Betrag EUR"],
         [("Kontostand am 30.09.2026, Auszug Nr. 9", de(OPENING_BALANCE)), *bookings(first)])
    page([*page_header(2), "Datum Erläuterung Betrag EUR"], [
        *bookings(rest),
        ("Kontostand am 31.10.2026 um 20:05 Uhr", de(closing_balance())),
        "Der Kontostand berücksichtigt nicht die Buchungen mit späterer Wertstellung, bitte beachten Sie die",
        "Hinweise zum Kontoauszug.",
        "Anzahl Anlagen 2",
        "Eingeräumte Kontoüberziehung EUR: 3.000,00",
    ])
    page([*page_header(3), "Entgeltabrechnung: Anlage 1"], [
        ("Entgelte vom 01.09.2026 bis 30.09.2026", de_behind(-FEE)),
        ("Kontoführung (Grundpreis)", de_behind(-FEE)),
        f"enthalten 19% Umsatzsteuer auf {de_behind(-FEE)} {de_behind(VAT)} {de_behind(VAT)}",
        "--------------",
        ("Abrechnung 30.09.2026", de_behind(-FEE)),
        "Es handelt sich hier um eine umsatzsteuerpflichtige Leistung.",
        "Rechnungsnummer: 20261001-MS001-00000000001",
        "Bitte beachten Sie die Hinweise zum Kontoauszug.",
    ])
    page([*page_header(4), "Rechnungsabschluss: Anlage 2"], [
        ("Kontostand in EUR am 30.09.2026", de_behind(OPENING_BALANCE, " ")),
        "--------------",
        "Abrechnungszeitraum vom 01.07.2026 bis 30.09.2026",
        ("Zinsen für eingeräumte Kontoüberziehung", de_behind(-INTEREST)),
        "11,2500 v.H. Zinssatz bis 30.09.2026",
        "--------------",
        ("Abrechnung 30.09.2026", de_behind(-INTEREST)),
        "Die Zinssätze für eingeräumte und geduldete Überziehungen gelten ab dem",
        "30.09.2026 unverändert. Einzelheiten entnehmen Sie bitte dem Preis- und Leistungsverzeichnis.",
        ("Kontostand/Rechnungsabschluss in EUR am 30.09.2026", de_behind(OPENING_BALANCE - INTEREST, " ")),
        "Rechnungsnummer: 20261001-MS002-00000000002",
        "Bitte beachten Sie die Hinweise zum Kontoauszug.",
    ])
    page([*page_header(5), "Hinweise zum Kontoauszug:"], [
        "Bitte erheben Sie Einwendungen gegen einzelne Buchungen unverzüglich.",
        "Guthaben sind als Einlagen nach Maßgabe des Einlagensicherungsgesetzes entschädigungsfähig.",
        "Der Rechnungsabschluss gilt als genehmigt, wenn Sie nicht innerhalb von sechs Wochen widersprechen.",
    ])
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
    # WinAnsiEncoding, so umlauts and ß extract as they print.
    add_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    for i, items in enumerate(pages):
        page_num, content_num = page_obj_nums[i], page_obj_nums[i] + 1
        add_obj(page_num, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode())
        stream = bytearray()
        for x, y, s in items:
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


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "sparkasse-checking-synthetic-sample.pdf")


def main():
    build_pdf(build_pages(), OUT)
    print(f"wrote {OUT}")
    print(f"  {len(BOOKINGS)} bookings, opening {de(OPENING_BALANCE)}, closing {de(closing_balance())}")


if __name__ == "__main__":
    main()
