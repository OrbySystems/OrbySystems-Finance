"""Sample (demo) brokerage parsers, ported from the fixture-based
TestExtract* cases in pkg/ingest/brokerage_test.go. Synthetic fixtures
only - the DB-storage tests (TestInsert*) stay on the Go side.
"""

from conftest import approx


def test_sample_brokerage_pdf(run_statement):
    stmt = run_statement(
        "brokerage-synthetic-sample.pdf", "--expected-parser", "sample_brokerage.py"
    )
    assert stmt.institution == "Sample Brokerage Services"
    assert stmt.statement_date == "2026-06-30"

    assert len(stmt.brokerage_holdings) == 2
    h = stmt.brokerage_holdings[0]
    assert h["symbol"] == "AAPL" and approx(h["current_value"], 2105.00)
    assert h["account"] == "123456789" and h["accountType"] == "Brokerage"

    assert len(stmt.brokerage_transactions) == 3
    buy = stmt.brokerage_transactions[0]
    assert buy["symbol"] == "AAPL" and buy["action"] == "Buy" and approx(buy["amount"], -410.00)
    div = stmt.brokerage_transactions[1]
    assert div["action"] == "Dividend" and div.get("quantity") is None

    assert len(stmt.transactions) == 2
    cash = stmt.transactions[0]
    assert cash["description"] == "Dividend Received VOO"
    assert approx(cash["amount"], 12.45) and approx(cash["balance"], 512.45)


def _assert_sample_brokerage_export(stmt):
    assert stmt.institution == "Sample Brokerage Services"
    assert len(stmt.transactions) == 0
    assert len(stmt.brokerage_holdings) == 0
    assert len(stmt.brokerage_transactions) == 3
    buy = stmt.brokerage_transactions[0]
    assert buy["symbol"] == "AAPL" and buy["action"] == "Buy"
    assert approx(buy["amount"], -410.00) and buy["accountType"] == "Brokerage"
    div = stmt.brokerage_transactions[1]
    assert div["action"] == "Dividend" and div.get("quantity") is None


def test_sample_brokerage_csv(run_statement):
    _assert_sample_brokerage_export(
        run_statement(
            "brokerage-csv-synthetic-sample.csv",
            "--expected-parser",
            "sample_brokerage_csv.py",
        )
    )


def test_sample_brokerage_xlsx(run_statement):
    _assert_sample_brokerage_export(
        run_statement(
            "brokerage-xlsx-synthetic-sample.xlsx",
            "--expected-parser",
            "sample_brokerage_csv.py",
        )
    )
