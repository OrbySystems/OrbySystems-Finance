"""Citi checking statement parser regression tests."""

import pytest

import parser_common
from conftest import approx
from institutions import citi_checking


def test_citi_checking_synthetic(run_statement):
    stmt = run_statement(
        "citi-checking-synthetic-sample.pdf",
        "--expected-parser",
        "citi_checking.py",
    )
    assert stmt.institution == "Citi"
    assert stmt.statement_date == "2026-09-30"
    assert stmt.first_account == "4321"
    assert stmt.first_account_type == "Checking"
    assert stmt.raw["parser"] == {"id": "citi_checking", "tier": "provisional", "bundled": True}

    rows = stmt.transactions
    assert len(rows) == 5
    assert [row["amount"] for row in rows] == [500.0, -600.0, -40.0, 10.0, -70.0]
    assert approx(rows[-1]["balance"], 800.0)
    assert rows[-1]["description"] == "SAMPLE TRANSFER REFERENCE TEXT"
    assert len(stmt.raw["checkResults"]) == 3
    assert all(result["ok"] for result in stmt.raw["checkResults"])


def test_citi_checking_rejects_a_truncated_statement_without_reconciliation_values():
    page = """September 1 - September 30, 2026
Citi Test Account ending in 4321
Checking
Everyday Checking 0000004321
Activity
Date Description Amount Subtracted Amount Added Balance
09/01/26 Opening Balance 1,000.00
09/02/26 SAMPLE PAYROLL 500.00 1,500.00
"""

    with pytest.raises(parser_common.ParserDiagnosticError) as error:
        citi_checking.parse([page], "unused.pdf")

    assert error.value.diagnostic_code == "PARSER_REQUIRED_DATA_MISSING"
    assert error.value.missing_fields == ("closingBalance", "statementTotals")
