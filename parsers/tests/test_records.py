"""The parsers of somebody's records: OrbySystems' import CSV and the money
apps' exports. Each reads its own format exactly, signs every amount so it
is negative when the person is poorer, says it reads records (RECORDS), and
leaves an account it can't name by number to OrbySystems to ask about.
Fixtures: tests/generators/gen-records-samples.py."""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import app_export  # noqa: E402


def amounts(stmt):
    return [t["amount"] for t in stmt.transactions]


def test_import_csv_transactions(run_statement):
    stmt = run_statement("orbysystems-transactions-synthetic-sample.csv", "--expected-parser", "orbysystems_transactions_csv.py")
    assert stmt.raw["parser"]["records"] is True
    assert stmt.institution == "", "two banks, so each row keeps its own"
    assert [(t["date"], t["amount"], t["account"], t["accountType"], t["institution"]) for t in stmt.transactions] == [
        ("2019-01-05", -84.2, "4417", "Checking", "Harbor Bank"),
        ("2019-01-07", -45.0, "9921", "Credit Card", "Meridian Card"),
        ("2019-01-15", 3200.0, "4417", "Checking", "Harbor Bank"),
        ("2019-01-20", 45.0, "9921", "Credit Card", "Meridian Card"),
    ]
    assert stmt.transactions[0]["account_name"] == "Joint checking"
    assert stmt.transactions[0]["balance"] == 915.8 and stmt.transactions[1]["balance"] is None


def test_import_csv_investment_transactions(run_statement):
    stmt = run_statement("orbysystems-investment-transactions-synthetic-sample.csv", "--expected-parser", "orbysystems_investments_csv.py")
    assert stmt.raw["parser"]["records"] is True
    assert stmt.institution == "Vantage Brokerage"
    rows = stmt.brokerage_transactions
    assert [(r["transaction_type"], r["amount"], r.get("symbol"), r.get("quantity")) for r in rows] == [
        ("buy", -1600.0, "VTI", 10.0), ("contribution", 6000.0, None, None), ("dividend", 12.3, "VTI", None),
        ("transfer_in", 0.0, "BND", 5.0), ("sell", 700.0, "VTI", 4.0),
    ]
    assert rows[3]["subtype"] == "In", "a transfer says which way it went"
    assert all((r["account"], r["accountType"]) == ("3301", "Roth IRA") for r in rows)


def test_import_csv_holdings(run_statement):
    stmt = run_statement("orbysystems-holdings-synthetic-sample.csv", "--expected-parser", "orbysystems_investments_csv.py")
    holdings = stmt.brokerage_holdings
    assert stmt.statement_date == "", "each holding is dated by its own as_of"
    assert [(h["symbol"], h["quantity"], h["price_as_of"], h.get("current_value")) for h in holdings] == [
        ("VTI", 120.0, "2024-12-31", 25260.0), ("CASH", 1500.25, "2024-12-31", 1500.25), ("VTI", 125.0, "2025-06-30", 28750.0),
    ]
    assert holdings[1]["is_cash_equivalent"] is True
    assert holdings[0]["cost_basis_total"] == 18000.0


def _write(tmp_path, name, rows):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


def _dispatch(path, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / "csv_statement.py"), str(path), "--strict", *args],
                          cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


HEADER = ["date", "description", "amount", "account_type", "institution", "account_last4"]


@pytest.mark.parametrize("row, value, error", [
    (["03/05/2019", "Grocer", "-1.00", "Checking", "Harbor Bank", "4417"], "03/05/2019", "row 2, column date: '03/05/2019' is not a date"),
    (["2019-03-05", "Grocer", "$1.00", "Checking", "Harbor Bank", "4417"], "$1.00", "row 2, column amount: '$1.00' is not a plain number"),
    (["2019-03-05", "Grocer", "1,000.00", "Checking", "Harbor Bank", "4417"], "1,000.00", "row 2, column amount: '1,000.00' is not a plain number"),
    (["2019-03-05", "Grocer", "-1.00", "Chequing", "Harbor Bank", "4417"], "Chequing", "row 2, column account_type: 'Chequing' is not one of"),
    (["2019-03-05", "Grocer", "-1.00", "Checking", "Harbor Bank", "000123454417"], "000123454417", "row 2, column account_last4: '000123454417' is not four digits"),
    (["2019-03-05", "", "-1.00", "Checking", "Harbor Bank", "4417"], "", "row 2, column description: is empty"),
])
def test_an_import_csv_value_out_of_form_stops_the_read(tmp_path, row, value, error):
    from csv_institutions import orbysystems_transactions_csv as parser
    with pytest.raises(ValueError) as raised:
        parser.parse([dict(zip(HEADER, row))], "t.csv")
    assert str(raised.value).startswith(error), "the reader names the row, the column and what's wrong"
    out = _dispatch(_write(tmp_path, "t.csv", [HEADER, row]))
    assert "error" in out and out["diagnostic"]["parserId"] == "orbysystems_transactions_csv", out
    if value:
        assert value not in json.dumps(out), "the dispatcher's message and diagnostic hold no value of the file"


def test_an_import_csv_header_is_exact(tmp_path):
    out = _dispatch(_write(tmp_path, "t.csv", [HEADER + ["memo"], ["2019-03-05", "Grocer", "-1.00", "Checking", "Harbor Bank", "4417", "x"]]))
    assert out.get("detected") is False, "an unknown column means it isn't the import CSV"
    out = _dispatch(_write(tmp_path, "t.csv", [HEADER[:-1], ["2019-03-05", "Grocer", "-1.00", "Checking", "Harbor Bank"]]))
    assert out.get("detected") is False


def test_an_import_csv_reader_names_the_row(tmp_path):
    sys.path.insert(0, str(SCRIPTS / "csv_institutions"))
    from csv_institutions import orbysystems_transactions_csv as parser
    with pytest.raises(ValueError, match=r"row 3, column amount: '1\.000,00' is not a plain number"):
        parser.parse([dict(zip(HEADER, ["2019-03-05", "Grocer", "-1.00", "Checking", "Harbor Bank", "4417"])),
                      dict(zip(HEADER, ["2019-03-06", "Cafe", "1.000,00", "Checking", "Harbor Bank", "4417"]))], "t.csv")


def test_a_negative_quantity_on_a_trade_is_refused():
    from csv_institutions import orbysystems_investments_csv as parser
    header = ["date", "description", "transaction_type", "amount", "symbol", "quantity", "account_type", "institution", "account_last4"]
    with pytest.raises(ValueError, match="row 2, column quantity: is negative on a sell"):
        parser.parse([dict(zip(header, ["2020-06-01", "Sold", "sell", "700", "VTI", "-4", "Brokerage", "Vantage", "3301"]))], "t.csv")


def test_mint(run_statement):
    stmt = run_statement("mint-synthetic-sample.csv", "--expected-parser", "mint_csv.py")
    assert stmt.raw["parser"]["records"] is True
    assert amounts(stmt) == [3200.0, -5.75, -42.1, 47.85], "debit out, credit in"
    assert [t["date"] for t in stmt.transactions] == ["2020-03-02", "2020-03-03", "2020-03-04", "2020-03-15"]
    assert {(t["account_name"], t["accountType"], t["account"]) for t in stmt.transactions} == {
        ("Harbor Checking", "Checking", ""), ("Meridian Visa", "Credit Card", "")}, "named, with no number: asked about"


def test_ynab(run_statement):
    stmt = run_statement("ynab-register-synthetic-sample.csv", "--expected-parser", "ynab_register_csv.py")
    assert [(t["description"], t["amount"], t["account_name"]) for t in stmt.transactions] == [
        ("Lakeshore Grocer", -84.23, "Harbor Checking"),
        ("Acme Widgets", 3200.0, "Harbor Checking"),
        ("Corner Coffee", -5.75, "Meridian Card"),
        ("Transfer : Harbor Checking", 5.75, "Meridian Card"),
    ], "no starting balance, no tracking account's adjustment"


def test_ynab_day_first_dates_and_decimal_commas(tmp_path):
    path = _write(tmp_path, "ynab.csv", [
        ["Account", "Flag", "Date", "Payee", "Category Group/Category", "Category Group", "Category", "Memo", "Outflow", "Inflow", "Cleared"],
        ["Girokonto", "", "05.03.2021", "Bäckerei", "Alltag: Essen", "Alltag", "Essen", "", "1.234,56€", "0,00€", "Cleared"],
    ])
    out = _dispatch(path, "--expected-parser", "ynab_register_csv.py")
    row = out["tables"]["cash_transactions"][0]
    assert (row["date"], row["amount"]) == ("2021-03-05", -1234.56)


def test_monarch(run_statement):
    stmt = run_statement("monarch-synthetic-sample.csv", "--expected-parser", "monarch_csv.py")
    assert [(t["description"], t["amount"]) for t in stmt.transactions] == [
        ("Acme Widgets", 3200.0), ("Lakeshore Grocer", -61.3), ("CORNER COFFEE #12", -4.5)]
    assert stmt.transactions[0]["account_name"] == "Harbor Checking (...4417)"


def test_tiller_files_rows_under_their_accounts(run_statement):
    stmt = run_statement("tiller-synthetic-sample.csv", "--expected-parser", "tiller_csv.py")
    assert [(t["amount"], t["account"], t.get("institution", ""), t["accountType"]) for t in stmt.transactions] == [
        (-38.12, "9921", "Meridian Card", "Credit Card"),
        (3200.0, "4417", "Harbor Bank", "Checking"),
        (-1850.0, "4417", "Harbor Bank", "Checking"),
        (-20.0, "", "", ""),
    ], "Account # and Institution file a row; the wallet, with neither, is asked about"
    assert stmt.transactions[3]["account_name"] == "Wallet"


def test_simplifi(run_statement):
    stmt = run_statement("simplifi-synthetic-sample.csv", "--expected-parser", "simplifi_csv.py")
    assert [(t["date"], t["amount"], t["account_name"]) for t in stmt.transactions] == [
        ("2024-06-01", 3200.0, "Harbor Checking"), ("2024-06-02", -71.15, "Meridian Visa")]


def test_empower(run_statement):
    stmt = run_statement("empower-synthetic-sample.csv", "--expected-parser", "empower_csv.py")
    assert amounts(stmt) == [3200.0, -61.3, 61.3]
    assert stmt.transactions[1]["accountType"] == "Credit Card"


def test_an_export_from_one_app_is_not_taken_for_anothers():
    fixtures = Path(__file__).resolve().parent / "fixtures"
    expected = {
        "mint-synthetic-sample.csv": "mint_csv", "ynab-register-synthetic-sample.csv": "ynab_register_csv",
        "monarch-synthetic-sample.csv": "monarch_csv", "tiller-synthetic-sample.csv": "tiller_csv",
        "simplifi-synthetic-sample.csv": "simplifi_csv", "empower-synthetic-sample.csv": "empower_csv",
        "orbysystems-transactions-synthetic-sample.csv": "orbysystems_transactions_csv",
        "orbysystems-holdings-synthetic-sample.csv": "orbysystems_investments_csv",
    }
    for name, parser in expected.items():
        out = _dispatch(fixtures / name)
        assert out["parser"]["id"] == parser, (name, out.get("parser"))


@pytest.mark.parametrize("raw, want", [
    ("$1,234.56", 1234.56), ("-$45.00", -45.0), ("$-45.00", -45.0), ("(45.00)", -45.0), ("84,23€", 84.23),
    ("1.234,56 €", 1234.56), ("C$210.45", 210.45), ("3200.0", 3200.0), ("12", 12.0), ("45.00-", -45.0),
])
def test_app_money(raw, want):
    assert app_export.money(raw) == pytest.approx(want)


def test_app_money_refuses_text():
    with pytest.raises(ValueError):
        app_export.money("n/a")


def test_app_dates():
    assert app_export.date("3/5/2024") == "2024-03-05"
    assert app_export.date("03/05/24") == "2024-03-05"
    assert app_export.date("05.03.2024", "dmy") == "2024-03-05"
    assert app_export.date("2024-03-05") == "2024-03-05"
    assert app_export.date_order(["01/02/2021", "13/02/2021"]) == "dmy"
    assert app_export.date_order(["01/02/2021", "12/31/2021"]) == "mdy"
    assert app_export.date_order(["05.03.2021"]) == "dmy"


def test_check_reports_accounts_and_every_problem(tmp_path):
    import import_csv

    path = _write(tmp_path, "t.csv", [
        HEADER + ["account_name"],
        ["2019-01-05", "Grocer", "-84.20", "Checking", "Harbor Bank", "4417", "Joint"],
        ["2019-01-15", "Payroll", "3200", "Checking", "Harbor Bank", "4417", "Joint"],
        ["01/20/2019", "Cafe", "$4.50", "Credit Card", "Meridian Card", "9921", ""],
        ["2019-01-21", "Short row"],
    ])
    out = import_csv.check(str(path))
    assert out["kind"] == "transactions" and out["rows"] == 4
    joint = next(a for a in out["accounts"] if a["last4"] == "4417")
    assert (joint["rows"], joint["first"], joint["last"], joint["in"], joint["out"], joint["name"]) == (2, "2019-01-05", "2019-01-15", 3200.0, -84.2, "Joint")
    assert [(p["row"], p["column"]) for p in out["problems"]] == [(4, "date"), (4, "amount"), (5, "")]
    assert "is not a date as YYYY-MM-DD" in out["problems"][0]["problem"]


def test_check_says_why_a_file_is_not_the_import_csv(tmp_path):
    import import_csv

    out = import_csv.check(str(_write(tmp_path, "t.csv", [["Date", "Payee", "Amount"], ["2019-01-05", "Grocer", "-1"]])))
    assert out["kind"] == "" and "missing column(s)" in out["problems"][0]["problem"]
