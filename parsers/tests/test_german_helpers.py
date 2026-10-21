"""common.py's German amount and date helpers (parse_german_amount,
parse_german_date, GERMAN_AMOUNT), for statements that write 1.234,56 and
30.09.2026.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_german_helpers.py)
"""

from __future__ import annotations

import re

import pytest

from institutions import common

AMOUNTS = [
    ("1.234,56", 1234.56),
    ("0,99", 0.99),
    ("1234,56", 1234.56),
    ("12.345.678,90", 12345678.90),
    ("-2.417,36", -2417.36),
    ("+2.350,00", 2350.00),
    ("318,26-", -318.26),
    ("1.083,52 -", -1083.52),
    ("5,18+", 5.18),
    ("- 3,90", -3.90),
    ("  57,84  ", 57.84),
]

NOT_AMOUNTS = [
    "1,234.56",      # a US amount
    "1.234",         # no cents
    "1.23,45",       # a thousands group of two digits
    "12,3",          # one decimal
    "-318,26-",      # signed at both ends
    "EUR 3,90",
    "",
]


@pytest.mark.parametrize("raw, value", AMOUNTS)
def test_a_german_amount_is_read_with_its_sign_on_either_side(raw, value):
    assert common.parse_german_amount(raw) == pytest.approx(value)


@pytest.mark.parametrize("raw", NOT_AMOUNTS)
def test_anything_else_is_not_a_german_amount(raw):
    with pytest.raises(ValueError):
        common.parse_german_amount(raw)


def test_the_pattern_finds_what_the_parser_reads():
    line = re.compile(r"^(.*?)\s(" + common.GERMAN_AMOUNT + r")$")
    for text, amount in (("01.10.2026Lastschrift -57,84", "-57,84"),
                         ("Abrechnung 30.09.2026 318,26-", "318,26-"),
                         ("Kontostand in EUR am 30.09.2026 1.083,52 -", "1.083,52 -"),
                         ("Gutschrift 2.350,00", "2.350,00")):
        m = line.match(text)
        assert m and m.group(2) == amount, text
        common.parse_german_amount(m.group(2))
    assert not line.match("Rechnung 2026 1,234.56")


def test_a_full_date_needs_no_statement():
    assert common.parse_german_date("30.09.2026") == "2026-09-30"
    assert common.parse_german_date("1.2.2027") == "2027-02-01"
    assert common.parse_german_date("30.09.26") == "2026-09-30"
    assert common.parse_german_date(" 29.02.2028 ") == "2028-02-29"


@pytest.mark.parametrize("raw", ["31.04.2026", "29.02.2027", "45.39.2026", "30-09-2026", "2026-09-30", "30.0926"])
def test_a_date_that_does_not_exist_or_is_not_german_is_refused(raw):
    with pytest.raises(ValueError):
        common.parse_german_date(raw)


def test_a_date_without_a_year_takes_the_statements():
    assert common.parse_german_date("05.10.", "2026-10-31") == "2026-10-05"
    assert common.parse_german_date("05.10", "2026-10-31") == "2026-10-05"
    # Across a new year, the year that puts it nearest the statement.
    assert common.parse_german_date("30.12.", "2027-01-15") == "2026-12-30"
    assert common.parse_german_date("02.01.", "2026-12-31") == "2027-01-02"
    # 29 February only in a year that has one.
    assert common.parse_german_date("29.02.", "2028-03-31") == "2028-02-29"


def test_a_date_without_a_year_needs_a_statement_date():
    with pytest.raises(ValueError):
        common.parse_german_date("05.10.")
    with pytest.raises(ValueError):
        common.parse_german_date("05.10.", "31.10.2026")
