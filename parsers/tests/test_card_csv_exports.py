"""The card issuers' and banks' CSV export parsers: American Express,
Capital One (card and 360), Discover. Each reads its own layout, signs every
amount so it is negative when the person is poorer (a card purchase
negative, a payment to the card positive), and files each row under the
card's last four digits where the export gives them. Fixtures:
tests/generators/gen-card-csv-samples.py."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def rows(stmt):
    return [(t["date"], t["description"], t["amount"], t["account"], t["accountType"]) for t in stmt.transactions]


def test_amex_with_details(run_statement):
    stmt = run_statement("amex-detailed-synthetic-sample.csv", "--expected-parser", "amex_csv.py")
    assert stmt.institution == "American Express"
    assert rows(stmt) == [
        ("2024-03-02", "LAKESHORE GROCER", -84.2, "1004", "Credit Card"),
        ("2024-03-05", "NORTHSIDE FUEL", -38.12, "1004", "Credit Card"),
        ("2024-03-15", "ONLINE PAYMENT - THANK YOU", 122.32, "1004", "Credit Card"),
    ], "a charge is negative, the payment positive; the additional card's charge is billed to the account paid"
    assert stmt.transactions[0]["reference"] == "320240620123456789"
    assert "parser" in stmt.raw and not stmt.raw["parser"].get("records"), "an issuer's export is a statement, not records"


def test_amex_older_layout_names_no_account(run_statement):
    stmt = run_statement("amex-synthetic-sample.csv", "--expected-parser", "amex_csv.py")
    assert rows(stmt) == [
        ("2024-04-01", "CORNER COFFEE", -5.75, "", "Credit Card"),
        ("2024-04-03", "RETURN CREDIT", 19.99, "", "Credit Card"),
    ], "no Account # column: the import asks which account it is"


def test_capital_one_card(run_statement):
    stmt = run_statement("capital-one-card-synthetic-sample.csv", "--expected-parser", "capital_one_card_csv.py")
    assert stmt.institution == "Capital One"
    assert rows(stmt) == [
        ("2024-05-01", "LAKESHORE GROCER", -61.3, "9921", "Credit Card"),
        ("2024-05-03", "NORTHSIDE FUEL", -45.0, "9921", "Credit Card"),
        ("2024-05-20", "CAPITAL ONE AUTOPAY PYMT", 106.3, "9921", "Credit Card"),
    ], "Debit is money out, Credit money in"


def test_capital_one_360(run_statement):
    stmt = run_statement("capital-one-360-synthetic-sample.csv", "--expected-parser", "capital_one_360_csv.py")
    assert [(t["date"], t["amount"], t["balance"], t["account"]) for t in stmt.transactions] == [
        ("2024-06-03", 3200.0, 4115.8, "4417"),
        ("2024-06-04", -61.3, 4054.5, "4417"),
        ("2024-06-10", -500.0, 3554.5, "4417"),
    ]
    assert stmt.transactions[0]["accountType"] == "", "checking or savings: the file doesn't say, so the import asks"


def test_discover_card(run_statement):
    stmt = run_statement("discover-card-synthetic-sample.csv", "--expected-parser", "discover_card_csv.py")
    assert stmt.institution == "Discover"
    assert rows(stmt) == [
        ("2024-07-01", "LAKESHORE GROCER", -84.23, "", "Credit Card"),
        ("2024-07-04", "NORTHSIDE FUEL", -38.12, "", "Credit Card"),
        ("2024-07-20", "INTERNET PAYMENT - THANK YOU", 1502.74, "", "Credit Card"),
    ], "a purchase is negative, the payment positive; no card number, so the import asks"


def test_each_export_is_read_by_its_own_parser():
    expected = {
        "amex-detailed-synthetic-sample.csv": "amex_csv", "amex-synthetic-sample.csv": "amex_csv",
        "capital-one-card-synthetic-sample.csv": "capital_one_card_csv",
        "capital-one-360-synthetic-sample.csv": "capital_one_360_csv",
        "discover-card-synthetic-sample.csv": "discover_card_csv",
    }
    for name, parser in expected.items():
        proc = subprocess.run([sys.executable, str(SCRIPTS / "csv_statement.py"), str(FIXTURES / name), "--strict"],
                              cwd=SCRIPTS, capture_output=True, text=True)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert out.get("parser", {}).get("id") == parser, (name, out.get("parser"), out.get("error"))


def test_amex_plain_download_is_not_claimed(tmp_path):
    path = tmp_path / "activity.csv"
    path.write_text("Date,Description,Amount\n03/02/2024,LAKESHORE GROCER,84.20\n")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "csv_statement.py"), str(path), "--strict"],
                          cwd=SCRIPTS, capture_output=True, text=True)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out.get("detected") is False, "three common columns are no evidence of Amex"


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def _dispatch(path, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / "csv_statement.py"), str(path), "--strict", *args],
                          cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


AMEX_HEADER = "Date,Description,Card Member,Account #,Amount,Extended Details,Appears On Your Statement As,Address,City/State,Zip Code,Country,Reference,Category\n"


def test_amex_amounts_in_any_form_and_a_blank_description(tmp_path):
    path = _write(tmp_path, "amex.csv", AMEX_HEADER
                  + '03/02/2024,,PAT EXAMPLE,-21004,"$1,234.56",,BOOKSHOP 0042,,,,,,\n'
                  + "03/03/2024,REFUND,PAT EXAMPLE,-21004,(5.00),,REFUND,,,,,,\n")
    out = _dispatch(path, "--expected-parser", "amex_csv.py")
    got = [(t["description"], t["amount"]) for t in out["tables"]["cash_transactions"]]
    assert got == [("BOOKSHOP 0042", -1234.56), ("REFUND", 5.0)], "the statement wording stands in for a blank description"


def test_amex_from_another_country_is_not_claimed(tmp_path):
    path = _write(tmp_path, "amex-uk.csv",
                  "Date,Description,Card Member,Account #,Amount,Extended Details,Appears On Your Statement As,Address,Town/City,Postcode,Country,Reference,Category\n"
                  + "15/03/2024,GROCER,PAT EXAMPLE,-21004,84.20,,GROCER,,LONDON,SW1A 1AA,UNITED KINGDOM,,\n")
    assert _dispatch(path).get("detected") is False, "day-first pounds are not read as US dollars"


def test_amex_bills_every_card_to_the_account_paid(tmp_path):
    path = _write(tmp_path, "amex.csv", AMEX_HEADER
                  + "03/02/2024,GROCER,SAM EXAMPLE,-21012,10.00,,GROCER,,,,,,\n"
                  + "03/03/2024,FUEL,SAM EXAMPLE,-21012,20.00,,FUEL,,,,,,\n"
                  + "03/10/2024,AUTOPAY PAYMENT RECEIVED - THANK YOU,PAT EXAMPLE,-21004,-30.00,,PAYMENT,,,,,,\n")
    out = _dispatch(path, "--expected-parser", "amex_csv.py")
    assert {t["account"] for t in out["tables"]["cash_transactions"]} == {"1004"}, "the card the payments arrive on, not the most rows'"


def test_capital_one_reads_debit_and_credit_as_written(tmp_path):
    path = _write(tmp_path, "c1.csv", "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n"
                  + '2024-05-01,2024-05-02,009921,GROCER,Grocery,"$1,234.56",\n'
                  + "2024-05-02,2024-05-03,009921,GROCER REVERSAL,Grocery,-20.00,\n")
    out = _dispatch(path, "--expected-parser", "capital_one_card_csv.py")
    got = [(t["amount"], t["account"]) for t in out["tables"]["cash_transactions"]]
    assert got == [(-1234.56, "9921"), (20.0, "9921")], "a reversal written negative in Debit is money back"


def test_discover_amounts_with_symbols(tmp_path):
    path = _write(tmp_path, "d.csv", "Trans. Date,Post Date,Description,Amount,Category\n"
                  + '07/01/2024,07/02/2024,GROCER,"$1,234.56",Supermarkets\n'
                  + "07/20/2024,07/20/2024,PAYMENT,-$45.00,Payments and Credits\n")
    out = _dispatch(path, "--expected-parser", "discover_card_csv.py")
    assert [t["amount"] for t in out["tables"]["cash_transactions"]] == [-1234.56, 45.0]


def test_a_failure_names_the_institution(tmp_path):
    path = _write(tmp_path, "d.csv", "Trans. Date,Post Date,Description,Amount,Category\n07/01/2024,07/02/2024,GROCER,,Supermarkets\n")
    out = _dispatch(path)
    assert out["diagnostic"]["institution"] == "Discover"
