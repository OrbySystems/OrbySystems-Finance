"""currency_code on a bank/card transaction (CONTRACT.md, "Currency"): optional,
absent means US dollars, three letters in any case, printed upper-cased by the
dispatcher. Nothing is converted.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_currency_code.py)
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import parser_common
from conftest import SCRIPTS


def _bank(**txn):
    row = {"date": "2026-09-30", "description": "REWE SAGT DANKE", "amount": -42.17, "balance": 1200.0,
           "account": "1234", "accountType": "Checking"}
    row.update(txn)
    return {"institution": "Sparkasse", "statementDate": "2026-09-30", "transactions": [row]}


def test_a_row_without_a_currency_is_valid_and_left_alone():
    result = _bank()
    parser_common.validate_parse_result(result, "p")
    result["tables"] = {"cash_transactions": result.pop("transactions")}
    assert "currency_code" not in parser_common.normalize_currency_codes(result)["tables"]["cash_transactions"][0]


@pytest.mark.parametrize("code", ["EUR", "eur", " Eur "])
def test_three_letters_in_any_case_are_accepted_and_upper_cased(code):
    result = _bank(currency_code=code)
    parser_common.validate_parse_result(result, "p")
    result["tables"] = {"cash_transactions": result.pop("transactions")}
    assert parser_common.normalize_currency_codes(result)["tables"]["cash_transactions"][0]["currency_code"] == "EUR"


def test_an_empty_currency_is_the_same_as_none():
    result = _bank(currency_code="")
    parser_common.validate_parse_result(result, "p")
    result["tables"] = {"cash_transactions": result.pop("transactions")}
    assert "currency_code" not in parser_common.normalize_currency_codes(result)["tables"]["cash_transactions"][0]


@pytest.mark.parametrize("code", ["Euro", "€", "EURO", "E1R", 978])
def test_anything_but_a_code_fails_by_name(code):
    with pytest.raises(ValueError, match="currency_code"):
        parser_common.validate_parse_result(_bank(currency_code=code), "p")


def test_a_brokerage_parsers_cash_rows_take_it_too():
    row = dict(_bank()["transactions"][0], currency_code="chf")
    result = {"institution": "X", "statementDate": "", "tables": {"cash_transactions": [row]}}
    parser_common.validate_multi_table_parse_result(result, "p")
    assert parser_common.normalize_currency_codes(result)["tables"]["cash_transactions"][0]["currency_code"] == "CHF"
    row["currency_code"] = "Swiss francs"
    with pytest.raises(ValueError, match="currency_code"):
        parser_common.validate_multi_table_parse_result(result, "p")


_DROP_IN = '''
def detect(header, sample_rows):
    return header[:3] == ["Buchungstag", "Verwendungszweck", "Betrag"], "header"

def parse(rows, path):
    return {"institution": "Sparkasse", "statementDate": "", "transactions": [
        {"date": "2026-09-30", "description": r["Verwendungszweck"], "amount": float(r["Betrag"]),
         "balance": None, "account": "1234", "accountType": "Checking", "currency_code": "eur"}
        for r in rows]}
'''


def test_the_dispatcher_prints_it_upper_cased(tmp_path):
    parsers = tmp_path / "parsers"
    parsers.mkdir()
    (parsers / "sparkasse_test_checking.py").write_text(_DROP_IN)
    statement = tmp_path / "export.csv"
    statement.write_text("Buchungstag,Verwendungszweck,Betrag\n30.09.2026,REWE SAGT DANKE,-42.17\n")
    out = subprocess.run([sys.executable, str(SCRIPTS / "csv_statement.py"), str(statement),
                          "--extra-parsers-dir", str(parsers), "--strict"],
                         capture_output=True, text=True, check=True)
    rows = json.loads(out.stdout)["tables"]["cash_transactions"]
    assert [r["currency_code"] for r in rows] == ["EUR"]
