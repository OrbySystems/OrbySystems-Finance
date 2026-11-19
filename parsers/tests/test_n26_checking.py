"""N26 Kontoauszug (n26_checking).

The demo statement is generated from invented data by
tests/generators/gen-n26-checking-sample.py. The page texts in the unit
tests below are invented too: their shapes follow the statement's layout,
their names and figures come from no statement.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys

import pytest

import parser_common
import statement_checks
from conftest import FIXTURES, REPO, SCRIPTS, approx
from institutions import n26_checking, sparkasse_checking

DEMO = "n26-checking-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "N26"
    assert stmt.statement_date == "2027-03-31"
    assert stmt.raw["parser"] == {"id": "n26_checking", "tier": "provisional", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 13
    # The account's last four digits, from the holder's IBAN at the foot.
    assert {(r["account"], r["accountType"]) for r in rows} == {("6789", "Checking")}
    assert {r["currency_code"] for r in rows} == {"EUR"}

    # Every check holds, and nothing was left unread.
    results = stmt.raw["checkResults"]
    assert [(r["kind"], r["label"], r["ok"]) for r in results] == [
        ("balance", "Dein neuer Kontostand", True),
        ("sum", "Ausgehende Transaktionen", True),
        ("sum", "Eingehende Transaktionen", True),
    ]

    # In the order printed, money out negative, money in positive.
    assert [r["date"] for r in rows][:3] == ["2027-03-01", "2027-03-01", "2027-03-02"]
    assert approx(rows[0]["amount"], -6.40)
    assert approx(rows[2]["amount"], 3215.60)
    assert rows[0]["description"] == "Bäckerei Kornblume Mastercard • Lebensmittel"
    # The cash machine's bank is in the description, and the statement is still N26's.
    assert rows[3]["description"] == "Sparkasse Musterstadt Mastercard • Bargeld"
    # A payee wrapped onto a second line, and a SEPA reference with its own
    # "EUR" amount, which is no booking.
    assert rows[4]["description"] == ("Stadtwerke Musterstadt Energie und Wasser Versorgung GmbH Lastschriften "
                                      "Abschlag Strom 03/2027 Vertrag 4400123 78,00 EUR")
    assert approx(rows[4]["amount"], -78.00)
    # A booking cut by the page break: page 1's foot and page 2's header are
    # in no description, and the other party's IBAN and BIC are left out.
    assert rows[6]["description"] == "Versicherung Beispiel AG Lastschriften Beitrag Hausrat 03/2027 Vers.-Nr. HR-552013"
    # The holder's own IBAN, repeated in a reference, keeps only its last four digits.
    assert rows[7]["description"] == "Jana Musterfrau Gutschriften Umbuchung auf ******************6789"
    for r in rows:
        assert not re.search(r"Erstellt am|Musterstraße|Beispielpark|IBAN|BIC|Verbuchungsdatum|Wertstellung|\d / \d",
                             r["description"]), r

    # The running balance starts from the opening Kontostand and ends on the closing one.
    assert approx(rows[0]["balance"], 1475.95)
    assert approx(rows[-1]["balance"], 3615.89)


def test_the_generator_makes_the_committed_demo_statement(tmp_path):
    spec = importlib.util.spec_from_file_location("gen_n26", REPO / "tests" / "generators" / "gen-n26-checking-sample.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    out = tmp_path / DEMO
    gen.main(str(out))
    assert out.read_bytes() == (FIXTURES / DEMO).read_bytes(), "regenerate the demo statement and read its diff"


# --- invented page texts -----------------------------------------------------

_HEADER = ["Kontoauszug Nr. 7/2027", "01.07.2027 bis 31.07.2027", "Beschreibung Verbuchungsdatum Betrag"]
_IBAN = "DE00100110010000123456"
_FOOTER = ["Max Muster Erstellt am", "Beispielweg 1, 54321 Beispielstadt 01.08.2027",
           f"IBAN: {_IBAN} • BIC: NTSBDEB1XXX Nr. 7/2027"]


def _summary(opening: str, out: str, inn: str, closing: str) -> list[str]:
    return ["Zusammenfassung Nr. 7/2027", "01.07.2027 bis 31.07.2027", "Beschreibung",
            f"Dein alter Kontostand {opening}", f"Ausgehende Transaktionen {out}",
            f"Eingehende Transaktionen {inn}", f"Dein neuer Kontostand {closing}"]


_NOTES = ["Kontoauszug", "01.07.2027 bis 31.07.2027", "Hinweise", "Bitte prüfe deinen Kontoauszug."]

_BOOKINGS = ["Beispiel Markt 03.07.2027 -40,00€", "Mastercard • Lebensmittel", "Wertstellung 02.07.2027",
             "Muster GmbH 15.07.2027 +100,00€", "Gutschriften", "IBAN: DE00999900001234567890 • BIC: MUSTDEFFXXX",
             "Erstattung 4711", "Wertstellung 15.07.2027"]


def _pages(*bodies: list[str], footer: list[str] = _FOOTER) -> list[str]:
    """Each body a page, the bookings pages under the header, every page
    over the foot and its page number."""
    return ["\n".join([*body, *footer, f"{n} / {len(bodies)}"]) for n, body in enumerate(bodies, 1)]


def _statement(bookings: list[str] = _BOOKINGS, summary=("+500,00€", "-40,00€", "+100,00€", "+560,00€")):
    return _pages([*_HEADER, *bookings], _summary(*summary), _NOTES)


def _parse(pages: list[str]):
    out = n26_checking.parse(pages, "statement.pdf", None)
    parser_common.validate_parse_result(out, "n26_checking")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]},
                                        out["statementDate"])
    return out, results


def _failed(results) -> set[str]:
    return {r["kind"] for r in results if not r["ok"]}


def _unread(results) -> list[str]:
    return [line["text"] for r in results if r["kind"] == "unread" for line in r["lines"]]


def test_a_clean_statement_passes_every_check():
    out, results = _parse(_statement())
    assert (out["institution"], out["statementDate"]) == ("N26", "2027-07-31")
    rows = out["transactions"]
    assert [(r["date"], r["amount"], r["balance"]) for r in rows] == [("2027-07-03", -40.0, 460.0),
                                                                      ("2027-07-15", 100.0, 560.0)]
    assert [r["description"] for r in rows] == ["Beispiel Markt Mastercard • Lebensmittel",
                                                "Muster GmbH Gutschriften Erstattung 4711"]
    assert {(r["account"], r["accountType"]) for r in rows} == {("3456", "Checking")}
    assert [r["kind"] for r in results] == ["balance", "sum", "sum"]
    assert _failed(results) == set()


def test_bookings_that_do_not_add_up_fail_their_checks():
    out, results = _parse(_statement(summary=("+500,00€", "-45,00€", "+100,00€", "+555,00€")))
    assert len(out["transactions"]) == 2
    assert _failed(results) == {"balance", "sum"}


def test_a_detail_line_two_pages_end_on_is_no_footer():
    # Two bookings cut by a page break after the same detail line: both
    # pages end on it above the foot, but every other page doesn't, so it
    # is the bookings' own.
    cut = "Lastschriften"
    page1 = [*_HEADER, "Beispiel Markt 03.07.2027 -40,00€", "Mastercard • Lebensmittel", "Wertstellung 02.07.2027",
             "Stadtwerke Beispielstadt 05.07.2027 -30,00€", cut]
    page2 = [*_HEADER, "IBAN: DE00999900001234567890 • BIC: MUSTDEFFXXX", "Abschlag Juli", "Wertstellung 05.07.2027",
             "Beispiel Telefon AG 08.07.2027 -20,00€", cut]
    page3 = [*_HEADER, "IBAN: DE00999900009876543210 • BIC: MUSTDEFFXXX", "Rechnung Juli", "Wertstellung 08.07.2027",
             "Muster GmbH 15.07.2027 +100,00€", "Gutschriften", "Wertstellung 15.07.2027"]
    out, results = _parse(_pages(page1, page2, page3, _summary("+500,00€", "-90,00€", "+100,00€", "+510,00€"), _NOTES))
    assert [r["description"] for r in out["transactions"]] == [
        "Beispiel Markt Mastercard • Lebensmittel",
        "Stadtwerke Beispielstadt Lastschriften Abschlag Juli",
        "Beispiel Telefon AG Lastschriften Rechnung Juli",
        "Muster GmbH Gutschriften",
    ]
    assert _failed(results) == set()


def test_the_foot_is_found_when_most_pages_print_none():
    # Only the two pages of bookings print the foot, and the first cuts a
    # booking: the holder's name and address stay out of its description.
    tail = [*_FOOTER]
    page1 = [*_HEADER, "Beispiel Markt 03.07.2027 -40,00€", "Mastercard • Lebensmittel", "Wertstellung 02.07.2027",
             "Stadtwerke Beispielstadt 05.07.2027 -30,00€", "Lastschriften", *tail, "1 / 4"]
    page2 = [*_HEADER, "IBAN: DE00999900001234567890 • BIC: MUSTDEFFXXX", "Abschlag Juli", "Wertstellung 05.07.2027",
             "Muster GmbH 15.07.2027 +100,00€", "Gutschriften", "Wertstellung 15.07.2027", *tail, "2 / 4"]
    summary = [*_summary("+500,00€", "-70,00€", "+100,00€", "+530,00€"), "3 / 4"]
    out, results = _parse(["\n".join(page1), "\n".join(page2), "\n".join(summary), "\n".join([*_NOTES, "4 / 4"])])
    assert [r["description"] for r in out["transactions"]] == ["Beispiel Markt Mastercard • Lebensmittel",
                                                               "Stadtwerke Beispielstadt Lastschriften Abschlag Juli",
                                                               "Muster GmbH Gutschriften"]
    assert _failed(results) == set()


def test_a_page_number_inside_the_foots_last_line_leaves_the_foot_out():
    footer = [*_FOOTER[:2], f"IBAN: {_IBAN} • BIC: NTSBDEB1XXX {{n}} Nr. 7/2027"]
    bodies = [[*_HEADER, "Beispiel Markt 03.07.2027 -40,00€", "Mastercard • Lebensmittel"],
              [*_HEADER, "Wertstellung 02.07.2027", "Muster GmbH 15.07.2027 +100,00€", "Gutschriften",
               "Wertstellung 15.07.2027"],
              _summary("+500,00€", "-40,00€", "+100,00€", "+560,00€"), _NOTES]
    pages = ["\n".join([*body, *footer[:2], footer[2].format(n=f"{n} / {len(bodies)}")])
             for n, body in enumerate(bodies, 1)]
    out, results = _parse(pages)
    assert [r["description"] for r in out["transactions"]] == ["Beispiel Markt Mastercard • Lebensmittel",
                                                               "Muster GmbH Gutschriften"]
    assert _failed(results) == set()


def test_a_euro_amount_in_a_reference_is_part_of_the_description():
    out, results = _parse(_statement([
        "Stadtwerke Beispielstadt 06.07.2027 -40,00€", "Lastschriften",
        "IBAN: DE00999900001234567890 • BIC: MUSTDEFFXXX", "Abschlag faellig 06.07.2027 40,00 EUR",
        "Wertstellung 06.07.2027", *_BOOKINGS[3:]]))
    assert [r["amount"] for r in out["transactions"]] == [-40.0, 100.0]
    assert out["transactions"][0]["description"].endswith("Abschlag faellig 06.07.2027 40,00 EUR")
    assert _failed(results) == set()


def test_a_line_ending_in_a_signed_euro_amount_that_is_no_booking_is_reported():
    out, results = _parse(_statement([*_BOOKINGS[:2], "Rueckzahlung -50,00€", *_BOOKINGS[2:]]))
    assert len(out["transactions"]) == 2
    assert _unread(results) == ["Rueckzahlung -50,00€"]


def test_a_booking_whose_date_does_not_exist_is_reported_not_read():
    out, results = _parse(_statement(["Beispiel Markt 31.06.2027 -40,00€", *_BOOKINGS[1:]]))
    assert [r["amount"] for r in out["transactions"]] == [100.0]
    assert _unread(results) == ["Beispiel Markt 31.06.2027 -40,00€"]
    assert "balance" in _failed(results)


def test_the_holders_own_iban_is_masked_with_and_without_its_spaces():
    for written in (_IBAN, "DE00 1001 1001 0000 1234 56"):
        out, _ = _parse(_statement([*_BOOKINGS[:4], "Gutschriften", f"Umbuchung von {written}",
                                    "Wertstellung 15.07.2027"]))
        description = out["transactions"][1]["description"]
        assert "123456" not in description.replace(" ", "") and description.endswith("3456"), description


def test_a_month_without_bookings_reads_no_rows_and_holds():
    out, results = _parse(_pages([*_HEADER], _summary("+500,00€", "0,00€", "0,00€", "+500,00€"), _NOTES))
    assert out["transactions"] == []
    # The zero totals are checked too, over no rows.
    assert [(r["kind"], r["label"]) for r in results] == [("balance", "Dein neuer Kontostand"),
                                                          ("sum", "Ausgehende Transaktionen"),
                                                          ("sum", "Eingehende Transaktionen")]
    assert _failed(results) == set()


def test_a_negative_balance():
    out, results = _parse(_statement(summary=("-1.234,56€", "-40,00€", "+100,00€", "-1.174,56€")))
    assert out["transactions"][-1]["balance"] == -1174.56
    assert _failed(results) == set()


def test_a_statement_with_no_booking_and_no_summary_fails_with_a_diagnostic():
    with pytest.raises(parser_common.ParserDiagnosticError) as e:
        n26_checking.parse(_pages([*_HEADER, "Keine Buchungen"], _NOTES), "s.pdf", None)
    assert e.value.diagnostic_code == "PARSER_REQUIRED_DATA_MISSING"
    assert e.value.missing_fields == ("transactions",)


def test_an_app_that_does_not_accept_a_currency_gets_none(monkeypatch):
    # 1.0.2 and earlier reject currency_code, and with it the statement.
    monkeypatch.delattr(parser_common, "normalize_currency_codes")
    out, results = _parse(_statement())
    assert out["transactions"] and not any("currency_code" in r for r in out["transactions"])
    assert _failed(results) == set()


# --- detect() ----------------------------------------------------------------

def test_detect_takes_an_n26_kontoauszug():
    matched, reason = n26_checking.detect("\n".join(_statement()[:3]))
    assert matched, reason


def test_detect_takes_the_layout_when_the_words_are_faked():
    # A scrambled sample: N26's name and BIC faked, and the summary's words.
    text = "\n".join(_statement()).replace("NTSBDEB1XXX", "WUKOFEZ1XXX").replace("Dein", "Zoka")
    matched, reason = n26_checking.detect(text)
    assert matched, reason


def test_detect_takes_a_month_without_bookings_and_an_english_statement():
    assert n26_checking.detect("\n".join(_pages([*_HEADER], _summary("+5,00€", "0,00€", "0,00€", "+5,00€"))))[0]
    english = ["Statement No. 7/2027", "01.07.2027 until 31.07.2027", "Description Booking Date Amount",
               "Beispiel Markt 03.07.2027 -40,00€", "Mastercard • Food & Groceries", "Value Date 02.07.2027"]
    assert n26_checking.detect("\n".join(_pages(english)))[0]


def test_detect_takes_n26s_bic_on_the_holders_iban_line_alone():
    # No booking and no Kontostand line on the pages detect() reads.
    assert n26_checking.detect("\n".join(_pages([*_HEADER, "Keine Buchungen"])))[0]
    # The BIC elsewhere is no sign of N26: another bank's statement whose
    # booking names an N26 account, under its own IBAN | BIC line.
    other = ["Beispielbank AG", "Account Statement 07/2027", "IBAN: DE00 9999 0000 0001 2345 67 | BIC: BSPBDEFFXXX",
             "03.07.2027 Transfer to Max Muster 40.00", "Recipient IBAN DE00100110010000123456, BIC NTSBDEB1XXX"]
    matched, reason = n26_checking.detect("\n".join(other))
    assert not matched, reason


def test_detect_refuses_a_sparkasse_or_cooperative_banks_kontoauszug():
    sparkasse = ["S Sparkasse", "Sparkasse Beispielstadt", "Kontoauszug 7/2027 Blatt 1 von 1",
                 "Girokonto 7654321, DE00 9999 0000 0007 6543 21", "Datum Erläuterung Betrag EUR",
                 "Kontostand am 30.06.2027, Auszug Nr. 6 100,00", "01.07.2027Lastschrift -60,00",
                 "Kontostand am 31.07.2027 um 19:30 Uhr 40,00"]
    volksbank = ["Volksbank Beispieltal eG", "Kontoauszug Nr. 7/2027 Blatt 1/1",
                 "Kontokorrent 4471938205 EUR IBAN DE00 9999 0517 5407 3249 31", "Bu-Tag Wert Vorgang",
                 "alter Kontostand vom 30.06.2027 100,00 H", "01.07. 01.07. Lastschrift 60,00 S",
                 "neuer Kontostand vom 31.07.2027 40,00 H"]
    for text in (sparkasse, volksbank):
        matched, reason = n26_checking.detect("\n".join(text))
        assert not matched, reason


# The pages detect() reads of each PDF, read as the dispatcher reads them,
# in a process of their own: test_bofa_checking_unit.py stubs pdfplumber in
# this one.
_HEAD_TEXTS = (
    "import json, sys, pdfplumber, parser_common\n"
    "out = {}\n"
    "for path in sys.argv[1:]:\n"
    "    with pdfplumber.open(path) as pdf:\n"
    "        out[path] = '\\n'.join(parser_common.page_text(p) for p in pdf.pages[:3])\n"
    "print(json.dumps(out))\n"
)


def _head_texts(paths) -> dict[str, str]:
    paths = [str(p) for p in paths]
    out = subprocess.run([sys.executable, "-c", _HEAD_TEXTS, *paths], cwd=SCRIPTS, capture_output=True, text=True,
                         check=True).stdout
    return json.loads(out)


def test_sparkasse_refuses_the_demo_statement_that_names_one():
    # The demo's first pages hold a booking at a Sparkasse's cash machine,
    # Kontoauszug, Kontostand and a DE IBAN: Sparkasse's own words.
    (head,) = _head_texts([FIXTURES / DEMO]).values()
    assert "Sparkasse" in head
    matched, reason = sparkasse_checking.detect(head)
    assert not matched and "N26" in reason, reason


def test_detect_refuses_every_other_fixture():
    # Bundled, it is tried before the parsers named after it in the
    # alphabet: Sparkasse's, VR Bank's, Wells Fargo's, and private ones.
    paths = [p for p in sorted(FIXTURES.glob("*.pdf")) if p.name != DEMO]
    texts = _head_texts(paths)
    assert len(texts) == len(paths) > 30
    claimed = [path for path, text in texts.items() if n26_checking.detect(text)[0]]
    assert claimed == []
