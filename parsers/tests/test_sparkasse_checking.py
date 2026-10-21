"""Sparkasse Girokonto Kontoauszug (sparkasse_checking).

The demo statement is generated from invented data by
tests/generators/gen-sparkasse-checking-sample.py. The page texts in the
unit tests below are invented too: their shapes follow the statement's
layout, their names and figures come from no statement.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest

import parser_common
import statement_checks
from conftest import FIXTURES, SCRIPTS, approx
from institutions import common, sparkasse_checking

DEMO = "sparkasse-checking-synthetic-sample.pdf"


def test_demo_statement(run_statement):
    stmt = run_statement(DEMO)
    assert stmt.institution == "Sparkasse Musterstadt"
    assert stmt.statement_date == "2026-10-31"
    assert stmt.raw["parser"] == {"id": "sparkasse_checking", "tier": "provisional", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 10
    # The account's last four digits, from the IBAN.
    assert {(r["account"], r["accountType"]) for r in rows} == {("4567", "Checking")}
    # In the currency the column header names.
    assert {r["currency_code"] for r in rows} == {"EUR"}

    # Every check holds, and nothing was left unread.
    results = stmt.raw["checkResults"]
    assert [(r["kind"], r["label"], r["ok"]) for r in results] == [("balance", "Kontoauszug", True)]

    # In the order printed, money out negative, a credit positive.
    assert [r["date"] for r in rows][:3] == ["2026-10-01", "2026-10-01", "2026-10-02"]
    by_text = {r["description"].split(" ")[0]: r for r in rows}
    assert approx(by_text["Entgeltabrechnung"]["amount"], -3.90)
    assert approx(by_text["Dauerauftrag"]["amount"], -850.00)
    salary = rows[2]
    assert salary["description"] == "Gutschrift Muster Werkzeugbau GmbH Gehalt Oktober 2026"
    assert approx(salary["amount"], 2350.00)
    # A description line that ends in an amount is still a description line.
    assert rows[3]["description"].startswith("Lastschrift Stadtwerke Musterstadt GmbH Abschlag Strom 10/2026 57,84- ")
    assert approx(rows[3]["amount"], -57.84)

    # The bookings carry on to page 2: page 1's footer and page 2's header
    # are in no description.
    assert rows[7]["description"] == "Bargeldauszahlung Sparkasse Musterstadt GA 0042 DATUM 13.10.2026, 15.25 UHR"
    assert rows[6]["description"] == ("Lastschrift Beispiel Versicherung AG Jahresbeitrag Hausrat "
                                      "Mandat VS-77 Gläubiger-ID DE11ZZZ00000000001")
    for r in rows:
        assert not re.search(r"Vorstand|www\.|Finanzgruppe|Blatt|Erläuterung", r["description"]), r

    # The running balance starts from the opening Kontostand and ends on the
    # closing one.
    assert approx(rows[0]["balance"], -1208.07)
    assert approx(rows[-1]["balance"], -1310.52)


def test_the_demo_statement_reads_the_same_as_a_drop_in_on_an_app_without_the_german_helpers(tmp_path):
    """A copy delivered for a request runs against the user's installed
    common.py; apps released before the German helpers lack them. Here the
    helpers are taken out of a copy of the scripts, and the bundled parser
    with them, and the parser is loaded from a parsers folder as the app
    loads a delivered one."""
    scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "institutions" / "sparkasse_checking.py").unlink()
    with open(scripts / "institutions" / "common.py", "a", encoding="utf-8") as f:
        f.write("\ndel GERMAN_AMOUNT, parse_german_amount, parse_german_date\n")
    drop_in = tmp_path / "parsers"
    drop_in.mkdir()
    shutil.copy(SCRIPTS / "institutions" / "sparkasse_checking.py", drop_in)

    def read(script_dir, *args):
        proc = subprocess.run([sys.executable, str(script_dir / "bank_statement.py"), str(FIXTURES / DEMO),
                               "--strict", *args], cwd=script_dir, capture_output=True, text=True)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    old = read(scripts, "--extra-parsers-dir", str(drop_in), "--only-extra-parser", "sparkasse_checking.py")
    assert old["parser"]["bundled"] is False, old
    assert not old.get("unloadedExtraParsers") and not old.get("failedExtraParsers"), old
    new = read(SCRIPTS)
    assert old["tables"] == new["tables"]
    assert old["checkResults"] == new["checkResults"]


# --- invented page texts -----------------------------------------------------

_FOOTER = [
    "Sparkasse Beispielstadt Vorstand: A. Beispiel, B. Muster",
    "Beispielplatz 2 54321 Beispielstadt www.sparkasse-beispielstadt.example",
    "Sparkassen-Finanzgruppe",
]
_ACCOUNT = "Girokonto 7654321, DE00 9999 0000 0007 6543 21"
_OPENING = "Kontostand am 31.03.2027, Auszug Nr. 3 100,00"
_CLOSING = "Kontostand am 30.04.2027 um 19:30 Uhr 50,00"
_NOTES = "\n".join(["S Sparkasse", "Beispielstadt", "Kontoauszug 4/2027 Blatt 2 von 2",
                    f"{_ACCOUNT}, Max Muster", "Hinweise zum Kontoauszug:",
                    "Bitte erheben Sie Einwendungen gegen einzelne Buchungen unverzüglich.", *_FOOTER])


def _statement(bookings: list[str], *, opening: str = _OPENING, closing: str = _CLOSING,
               account: str = _ACCOUNT, after: tuple[str, ...] = ()) -> list[str]:
    first = "\n".join(["S Sparkasse", "Sparkasse Beispielstadt", "Beispielstadt", "Herrn", "Max Muster",
                       "Beispielweg 1", "54321 Beispielstadt", "1. Mai 2027", "Kontoauszug 4/2027 Blatt 1 von 2",
                       account, "Datum Erläuterung Betrag EUR", opening, *bookings, closing, *after, *_FOOTER])
    return [first, _NOTES]


_BOOKINGS = ["01.04.2027Lastschrift -60,00", "Stadtwerke Beispielstadt", "Mandat 1 Gläubiger-ID DE00ZZZ0",
             "15.04.2027Gutschrift 10,00", "Erstattung"]


def _parse(pages: list[str]):
    out = sparkasse_checking.parse(pages, "statement.pdf", None)
    parser_common.validate_parse_result(out, "sparkasse_checking")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]},
                                        out["statementDate"])
    return out, results


def _failed(results) -> set[str]:
    return {r["kind"] for r in results if not r["ok"]}


def _unread(results) -> list[str]:
    return [line["text"] for r in results if r["kind"] == "unread" for line in r["lines"]]


def test_a_clean_statement_passes_every_check():
    out, results = _parse(_statement(_BOOKINGS))
    assert out["institution"] == "Sparkasse Beispielstadt"
    assert out["statementDate"] == "2027-04-30"
    rows = out["transactions"]
    assert [(r["date"], r["amount"], r["balance"]) for r in rows] == [("2027-04-01", -60.0, 40.0),
                                                                      ("2027-04-15", 10.0, 50.0)]
    assert [r["description"] for r in rows] == ["Lastschrift Stadtwerke Beispielstadt Mandat 1 Gläubiger-ID DE00ZZZ0",
                                                "Gutschrift Erstattung"]
    assert {(r["account"], r["accountType"]) for r in rows} == {("4321", "Checking")}
    assert _failed(results) == set()


def test_an_amount_signed_behind_is_read_with_its_sign():
    out, results = _parse(_statement(["01.04.2027Abrechnung 31.03.2027 60,00-", "siehe Anlage Nr. 1",
                                      "15.04.2027Gutschrift 10,00 +"]))
    assert [r["amount"] for r in out["transactions"]] == [-60.0, 10.0]
    assert _failed(results) == set()


def test_a_negative_opening_and_closing_balance():
    out, results = _parse(_statement(["01.04.2027Gutschrift 1.500,00"],
                                     opening="Kontostand am 31.03.2027, Auszug Nr. 3 -1.234,56",
                                     closing="Kontostand am 30.04.2027 um 19:30 Uhr 265,44"))
    assert out["transactions"][0]["balance"] == 265.44
    assert _failed(results) == set()


def test_a_month_without_bookings_reads_no_rows_and_holds():
    out, results = _parse(_statement([], closing="Kontostand am 30.04.2027 um 19:30 Uhr 100,00"))
    assert out["transactions"] == []
    assert _failed(results) == set()


def test_a_booking_whose_date_does_not_exist_is_reported_not_read():
    out, results = _parse(_statement(["31.04.2027Lastschrift -60,00", "Stadtwerke Beispielstadt",
                                      "15.04.2027Gutschrift 10,00"]))
    assert [r["amount"] for r in out["transactions"]] == [10.0]
    assert _failed(results) == {"unread", "balance"}
    assert _unread(results) == ["31.04.2027Lastschrift -60,00"]


def test_a_dated_line_in_the_bookings_that_is_not_a_booking_is_reported():
    out, results = _parse(_statement(["01.04.2027Lastschrift -60,00", "02.04.2027 Rechnung Nr. 5",
                                      "15.04.2027Gutschrift 10,00"]))
    assert len(out["transactions"]) == 2
    assert _unread(results) == ["02.04.2027 Rechnung Nr. 5"]


def test_a_dated_line_with_an_amount_outside_the_bookings_is_reported_and_small_print_is_not():
    pages = _statement(_BOOKINGS, after=("Anzahl Anlagen 1",))
    pages.insert(1, "\n".join(["S Sparkasse", "Beispielstadt", "Kontoauszug 4/2027 Blatt 2 von 3", "Anlage 1",
                               "Abrechnung 31.03.2027 3,90-", "Die Zinssätze gelten ab dem",
                               "31.03.2027 unverändert.", "20.04.2027Lastschrift -5,00", *_FOOTER]))
    out, results = _parse(pages)
    assert len(out["transactions"]) == 2
    assert _failed(results) == {"unread"}
    assert _unread(results) == ["20.04.2027Lastschrift -5,00"]


def test_bookings_carry_on_across_a_page_under_its_repeated_header():
    page1 = "\n".join(["S Sparkasse", "Sparkasse Beispielstadt", "Herrn", "Max Muster",
                       "Kontoauszug 4/2027 Blatt 1 von 3", _ACCOUNT, "Datum Erläuterung Betrag EUR", _OPENING,
                       "01.04.2027Lastschrift -60,00", "Stadtwerke Beispielstadt", *_FOOTER])
    page2 = "\n".join(["S Sparkasse", "Beispielstadt", "Kontoauszug 4/2027 Blatt 2 von 3",
                       f"{_ACCOUNT}, Max Muster", "Datum Erläuterung Betrag EUR",
                       "15.04.2027Gutschrift 10,00", "Erstattung", _CLOSING, *_FOOTER])
    notes = _NOTES.replace("Blatt 2 von 2", "Blatt 3 von 3")
    out, results = _parse([page1, page2, notes])
    assert [r["description"] for r in out["transactions"]] == ["Lastschrift Stadtwerke Beispielstadt",
                                                               "Gutschrift Erstattung"]
    assert _failed(results) == set()


def test_an_opening_balance_printed_without_its_comma_is_found_by_its_words():
    out, results = _parse(_statement(_BOOKINGS, opening="Kontostand am 31.03.2027 100,00"))
    assert len(out["transactions"]) == 2
    assert _failed(results) == set()


def test_a_missing_opening_or_closing_balance_fails_with_a_diagnostic():
    with pytest.raises(parser_common.ParserDiagnosticError) as e:
        sparkasse_checking.parse(_statement(_BOOKINGS, opening="Datum Erläuterung Betrag EUR"), "s.pdf", None)
    assert e.value.diagnostic_code == "PARSER_REQUIRED_DATA_MISSING"
    assert e.value.missing_fields == ("openingBalance",)
    with pytest.raises(parser_common.ParserDiagnosticError) as e:
        sparkasse_checking.parse(_statement(_BOOKINGS, closing="Bitte beachten Sie die Hinweise."), "s.pdf", None)
    assert e.value.missing_fields == ("closingBalance",)


def test_a_savings_account_says_so():
    out, _ = _parse(_statement(_BOOKINGS, account="Tagesgeld 7654321, DE00 9999 0000 0007 6543 21"))
    assert {r["accountType"] for r in out["transactions"]} == {"Savings"}
    out, _ = _parse(_statement(_BOOKINGS, account="Sparkassen-Girokonto 7654321, DE00 9999 0000 0007 6543 21"))
    assert {r["accountType"] for r in out["transactions"]} == {"Checking"}


def test_the_rows_are_in_the_currency_the_column_header_names():
    out, _ = _parse(_statement(_BOOKINGS))
    assert {r["currency_code"] for r in out["transactions"]} == {"EUR"}
    out, _ = _parse([p.replace("Betrag EUR", "Betrag USD") for p in _statement(_BOOKINGS)])
    assert {r["currency_code"] for r in out["transactions"]} == {"USD"}
    # A header whose word a scrambler faked names none: a Sparkasse account is in euros.
    out, _ = _parse([p.replace("Betrag EUR", "Wuraso BAZ") for p in _statement(_BOOKINGS)])
    assert {r["currency_code"] for r in out["transactions"]} == {"EUR"}


def test_an_app_that_does_not_accept_a_currency_gets_none(monkeypatch):
    # 1.0.2 and earlier reject currency_code, and with it the statement.
    monkeypatch.delattr(parser_common, "normalize_currency_codes")
    out, results = _parse(_statement(_BOOKINGS))
    assert out["transactions"] and not any("currency_code" in r for r in out["transactions"])
    assert _failed(results) == set()


# --- detect() ----------------------------------------------------------------

def test_detect_takes_the_statements_own_words():
    matched, reason = sparkasse_checking.detect("\n".join(_statement(_BOOKINGS)))
    assert matched and "Kontoauszug" in reason


def test_detect_takes_the_layout_when_the_words_are_not_there():
    # A sample scrambled before the scrambler knew German: every German word
    # faked, the IBAN's country too. Sparkasse, the shapes and the
    # punctuation are kept.
    text = "\n".join(_statement(_BOOKINGS))
    for word, fake in (("Kontoauszug", "Wuhabelibot"), ("Kontostand", "Gamesodite"), ("Girokonto", "Lepumoxa"),
                       ("DE00", "QX00"), (" am ", " ze "), ("Auszug Nr.", "Pibeke Ko.")):
        text = text.replace(word, fake)
    matched, reason = sparkasse_checking.detect(text)
    assert matched and "layout" in reason
    out, results = _parse([text])
    assert [r["amount"] for r in out["transactions"]] == [-60.0, 10.0]
    assert out["transactions"][0]["account"] == "4321"
    assert _failed(results) == set()


def test_detect_refuses_what_is_not_a_sparkasse_kontoauszug():
    text = "\n".join(_statement(_BOOKINGS))
    assert sparkasse_checking.detect(re.sub("sparkasse", "Volksbank", text, flags=re.I))[0] is False
    assert sparkasse_checking.detect(
        "S Sparkasse\nSparkasse Beispielstadt\nKreditkartenabrechnung\nSaldo 12,00\n" + _ACCOUNT)[0] is False


# --- the copy of the German helpers a drop-in falls back to ----------------------

def test_the_fallback_helpers_agree_with_commons(monkeypatch):
    assert sparkasse_checking._AMOUNT_FALLBACK == common.GERMAN_AMOUNT
    amounts = ["1.234,56", "-2.417,36", "+2.350,00", "318,26-", "1.083,52 -", "5,18+", "0,99", "1234,56"]
    dates = ["30.09.2026", "01.10.2026", "29.02.2028"]
    expected = ([common.parse_german_amount(a) for a in amounts], [common.parse_german_date(d) for d in dates])
    monkeypatch.delattr(common, "parse_german_amount")
    monkeypatch.delattr(common, "parse_german_date")
    assert ([sparkasse_checking._amount(a) for a in amounts],
            [sparkasse_checking._date(d) for d in dates]) == expected
    for bad in ("31.04.2026", "45.39.2026"):
        with pytest.raises(ValueError):
            sparkasse_checking._date(bad)
