from pathlib import Path

import pytest

import parser_common
from conftest import approx
from institutions import merrill_lynch_cma


def test_merrill_cma_synthetic_page():
    pages = ["""
Online at mymerrill.com Account Number: 1X1-11X11 24-Hour Assistance: (800) MERRILL
CMA ACCOUNT December 01, 2025 - December 31, 2025
YOUR CMA ASSETS
CASH 110,760.48 110,760.48 110,760.48
EQUITIES
ACME CORPORATION ACM 10.0000 100.00 15.0000 150.00 50.00
YOUR CMA TRANSACTIONS
DIVIDENDS/INTEREST INCOME TRANSACTIONS
12/30 BANK DEPOSIT INTEREST Bank Interest 0.87
SECURITY TRANSACTIONS
12/14 CD SECURITY 5 Redemption -385,000.0000 385,000.00
CASH / OTHER TRANSACTIONS
12/08 CHECK DEPOSIT Funds Received 5,461.69
12/11 TO BAC# 1X1-11X13 Withdrawal 1,500.00
YOUR CMA MONEY ACCOUNT TRANSACTIONS
12/03 ML BANK DEPOSIT PROGRAM 25,000.00 12/18 PREFERRED DEPOSIT 1,761.00
"""]

    matched, reason = merrill_lynch_cma.detect(pages[0])
    assert matched, reason

    result = merrill_lynch_cma.parse(pages, "")
    parser_common.validate_multi_table_parse_result(result, "merrill_lynch_cma")
    assert result["institution"] == "Merrill Lynch"
    assert result["statementDate"] == "2025-12-31"

    tables = result["tables"]
    holdings = tables["brokerage_holdings"]
    assert len(holdings) == 2
    assert holdings[0]["symbol"] == "CASH"
    assert holdings[0]["is_cash_equivalent"] is True
    assert approx(holdings[0]["current_value"], 110760.48)
    assert holdings[1]["symbol"] == "ACM"
    assert holdings[1]["type"] == "Equity"
    assert approx(holdings[1]["quantity"], 10)
    assert approx(holdings[1]["current_value"], 150)

    txns = tables["brokerage_transactions"]
    assert len(txns) == 4
    assert txns[0]["action"] == "Interest"
    assert txns[0]["date"] == "2025-12-30"
    assert approx(txns[0]["amount"], 0.87)
    assert txns[1]["action"] == "Redemption"
    assert approx(txns[1]["amount"], 385000)
    assert txns[2]["action"] == "Money Account Sweep"
    assert txns[3]["action"] == "Money Account Sweep"

    cash = tables["cash_transactions"]
    assert len(cash) == 2
    assert cash[0]["accountType"] == "Cash Management"
    assert approx(cash[0]["amount"], 5461.69)
    assert approx(cash[1]["amount"], -1500)


def test_merrill_cma_rejects_report_types():
    wealth = "Primary Account: 1X1-11X11 WEALTH MANAGEMENT REPORT December 01, 2025 - December 31, 2025"
    trust = "YOUR TRUST MANAGEMENT ACCOUNT STATEMENT OF PRINCIPAL INVESTMENTS December 01, 2025 - December 31, 2025"
    assert merrill_lynch_cma.detect(wealth)[0] is False
    assert merrill_lynch_cma.detect(trust)[0] is False


def test_merrill_cma_public_samples_smoke(run_statement):
    sample_dir = Path(__file__).resolve().parents[3] / "merrill_statement_samples"
    core = sample_dir / "merrill-cma-core-sample-statement.pdf"
    supplemental = sample_dir / "merrill-cma-supplemental-sample-statement.pdf"
    if not core.exists() or not supplemental.exists():
        pytest.skip("Merrill public sample PDFs not present")

    core_stmt = run_statement(str(core))
    assert core_stmt.institution == "Merrill Lynch"
    assert core_stmt.statement_date == ""
    assert any(h["symbol"] == "CASH" for h in core_stmt.brokerage_holdings)
    assert any(h["symbol"] == "RNGD" for h in core_stmt.brokerage_holdings)

    supplemental_stmt = run_statement(str(supplemental))
    assert supplemental_stmt.institution == "Merrill Lynch"
    assert any(h["symbol"] == "VSGL" for h in supplemental_stmt.brokerage_holdings)
