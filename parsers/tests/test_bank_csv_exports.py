"""The big banks' CSV export parsers: Chase cards, Citi cards, Bank of
America checking and cards, Wells Fargo. Each reads its own layout, signs
every amount negative when the person is poorer, names the institution as
its PDF statement parser does, so a CSV and a statement of one account
file under the same account, and takes the account's digits or kind from
the download's name where the bank puts them there. Fixtures:
tests/generators/gen-bank-csv-samples.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import app_export  # noqa: E402


def rows(stmt):
    return [(t["date"], t["description"], t["amount"], t["account"], t["accountType"]) for t in stmt.transactions]


def _dispatch(path, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / "csv_statement.py"), str(path), "--strict", *args],
                          cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_chase_card_takes_the_card_from_the_file_name(run_statement):
    stmt = run_statement("Chase9921_Activity20240301_20240331_20240401.CSV", "--expected-parser", "chase_card_csv.py")
    assert stmt.institution == "Chase", "as the Chase card statement parser names it"
    assert rows(stmt) == [
        ("2024-03-02", "LAKESHORE GROCER", -84.2, "9921", "Credit Card"),
        ("2024-03-05", "NORTHSIDE FUEL", -38.12, "9921", "Credit Card"),
        ("2024-03-09", "BOOKSHOP RETURN", 19.99, "9921", "Credit Card"),
        ("2024-03-20", "AUTOMATIC PAYMENT - THANK", 102.33, "9921", "Credit Card"),
    ]


def test_chase_card_renamed_is_asked_about(tmp_path):
    src = (FIXTURES / "Chase9921_Activity20240301_20240331_20240401.CSV").read_text()
    path = tmp_path / "march.csv"
    path.write_text(src)
    out = _dispatch(path, "--expected-parser", "chase_card_csv.py")
    assert {t["account"] for t in out["tables"]["cash_transactions"]} == {""}


def test_citi_card(run_statement):
    stmt = run_statement("citi-card-synthetic-sample.csv", "--expected-parser", "citi_card_csv.py")
    assert stmt.institution == "Citi"
    assert rows(stmt) == [
        ("2024-04-02", "LAKESHORE GROCER", -126.44, "", "Credit Card"),
        ("2024-04-04", "NORTHSIDE FUEL", -38.12, "", "Credit Card"),
        ("2024-04-15", "ONLINE PAYMENT, THANK YOU", 164.56, "", "Credit Card"),
    ], "Debit is a charge, Credit (written negative) a payment; the pending row is left out"


def test_bofa_checking_skips_the_summary_and_the_beginning_balance(run_statement):
    stmt = run_statement("bofa-checking-synthetic-sample.csv", "--expected-parser", "bofa_checking_csv.py")
    assert stmt.institution == "Bank of America"
    assert [(t["date"], t["amount"], t["balance"]) for t in stmt.transactions] == [
        ("2024-05-02", 3200.0, 4200.0), ("2024-05-03", -61.3, 4138.7), ("2024-05-15", -1850.0, 2288.7),
    ]
    assert {(t["account"], t["accountType"]) for t in stmt.transactions} == {("", "")}, "the import asks which account"


def test_bofa_card(run_statement):
    stmt = run_statement("May2024_9921.csv", "--expected-parser", "bofa_card_csv.py")
    assert rows(stmt) == [
        ("2024-05-03", "LAKESHORE GROCER", -61.3, "9921", "Credit Card"),
        ("2024-05-04", "NORTHSIDE FUEL", -45.0, "9921", "Credit Card"),
        ("2024-05-20", "PAYMENT - THANK YOU", 106.3, "9921", "Credit Card"),
    ]
    assert stmt.transactions[0]["reference"] == "24692164123000012345678"


def test_bofa_card_signed_as_the_balance_moves_is_negated(tmp_path):
    path = tmp_path / "May2024_9921.csv"
    path.write_text("Posted Date,Reference Number,Payee,Address,Amount\n"
                    "05/03/2024,1,LAKESHORE GROCER,,61.30\n05/20/2024,2,PAYMENT - THANK YOU,,-61.30\n")
    out = _dispatch(path, "--expected-parser", "bofa_card_csv.py")
    assert [t["amount"] for t in out["tables"]["cash_transactions"]] == [-61.3, 61.3]


def test_wells_fargo_checking_has_no_header(run_statement):
    stmt = run_statement("Checking1.csv", "--expected-parser", "wells_fargo_csv.py")
    assert stmt.institution == "Wells Fargo"
    assert rows(stmt) == [
        ("2024-06-03", "ACME WIDGETS PAYROLL", 3200.0, "", "Checking"),
        ("2024-06-04", "PURCHASE AUTHORIZED ON 06/03 LAKESHORE GROCER", -61.3, "", "Checking"),
        ("2024-06-10", "CHECK # 1043", -1850.0, "", "Checking"),
    ], "every row, the first included, though the dispatcher took it for a header"


def test_wells_fargo_card_signed_as_the_balance_moves_is_negated(run_statement):
    stmt = run_statement("CreditCard1.csv", "--expected-parser", "wells_fargo_csv.py")
    assert [(t["amount"], t["accountType"]) for t in stmt.transactions] == [
        (-84.23, "Credit Card"), (-38.12, "Credit Card"), (122.35, "Credit Card")]


def test_each_export_is_read_by_its_own_parser():
    expected = {
        "Chase9921_Activity20240301_20240331_20240401.CSV": "chase_card_csv",
        "citi-card-synthetic-sample.csv": "citi_card_csv",
        "bofa-checking-synthetic-sample.csv": "bofa_checking_csv",
        "May2024_9921.csv": "bofa_card_csv",
        "Checking1.csv": "wells_fargo_csv",
        "CreditCard1.csv": "wells_fargo_csv",
    }
    for name, parser in expected.items():
        out = _dispatch(FIXTURES / name)
        assert out.get("parser", {}).get("id") == parser, (name, out.get("parser"), out.get("error"))


@pytest.mark.parametrize("rows_, sign", [
    ([(-61.3, "GROCER"), (106.3, "PAYMENT - THANK YOU")], 1),
    ([(61.3, "GROCER"), (-106.3, "PAYMENT - THANK YOU")], -1),
    ([(61.3, "GROCER"), (12.0, "FUEL"), (-5.0, "RETURN")], -1),
    ([(-61.3, "GROCER"), (-12.0, "FUEL"), (5.0, "RETURN")], 1),
    # A merchant's bill payment charged to the card is a purchase.
    ([(-85.0, "ATT*BILL PAYMENT"), (-40.0, "CITY UTILITY BILL PAYMENT"), (-61.3, "GROCER"), (186.3, "PAYMENT - THANK YOU")], 1),
    # A late payment fee is a charge, not a payment: the payment decides.
    ([(61.3, "GROCER"), (29.0, "LATE PAYMENT FEE"), (-61.3, "AUTOPAY PAYMENT")], -1),
    # A returned-payment fee is a charge, though "returned" reads like money back.
    ([(61.3, "GROCER"), (35.0, "RETURNED PAYMENT FEE"), (29.0, "RETURNED PAYMENT FEE"), (-61.3, "ONLINE PAYMENT")], -1),
    # A refund alone is money back.
    ([(19.99, "BOOKSHOP REFUND")], 1),
    ([(-19.99, "BOOKSHOP REFUND")], -1),
])
def test_card_sign(rows_, sign):
    assert app_export.card_sign(rows_) == sign


def test_bofa_checking_with_its_summary_deleted(tmp_path):
    path = tmp_path / "stmt.csv"
    path.write_text('Date,Description,Amount,Running Bal.\n05/02/2024,"PAYROLL","3,200.00","4,200.00"\n')
    out = _dispatch(path, "--expected-parser", "bofa_checking_csv.py")
    assert [t["amount"] for t in out["tables"]["cash_transactions"]] == [3200.0]


def test_wells_fargo_checking_rows_are_never_resigned(tmp_path):
    path = tmp_path / "Checking1.csv"
    path.write_text('"06/03/2024","3200.00","*","","ACME WIDGETS PAYROLL"\n'
                    '"06/04/2024","-120.00","*","","CITI CARD ONLINE PAYMENT"\n'
                    '"06/05/2024","-850.00","*","1043","CHECK # 1043"\n')
    out = _dispatch(path, "--expected-parser", "wells_fargo_csv.py")
    assert [t["amount"] for t in out["tables"]["cash_transactions"]] == [3200.0, -120.0, -850.0], \
        "a checking account's card payment is money out, and a check's number may fill the fourth column"


def test_bofa_checking_row_without_an_amount_fails(tmp_path):
    path = tmp_path / "stmt.csv"
    path.write_text('Date,Description,Amount,Running Bal.\n05/02/2024,"PAYROLL",,"4,200.00"\n')
    out = _dispatch(path)
    assert "error" in out and out["diagnostic"]["parserId"] == "bofa_checking_csv"
