"""Voya 401(k) plan statement parser coverage (synthetic fixture)."""
from conftest import approx

FIXTURE = "voya-brokerage-pdf-synthetic-sample.pdf"


def test_voya_synthetic_statement(run_statement):
    stmt = run_statement(FIXTURE, "--expected-parser", "voya-brokerage-pdf.py")
    assert stmt.institution == "Voya"
    assert stmt.statement_date == "2030-03-31"
    assert len(stmt.brokerage_transactions) == 0
    assert len(stmt.brokerage_holdings) == 2
    assert all(h["account"] == "A123" and h["accountType"] == "401(k)" for h in stmt.brokerage_holdings)

    index, bond = stmt.brokerage_holdings
    assert index["description"] == "Synthetic Index Fund A"
    assert approx(index["quantity"], 100.0)
    assert approx(index["price"], 105.0)
    assert approx(index["current_value"], 10500.0)
    assert approx(bond["current_value"], 20460.0)
    assert approx(sum(h["current_value"] for h in stmt.brokerage_holdings), 30960.0)
