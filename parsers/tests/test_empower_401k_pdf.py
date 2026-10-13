"""Synthetic Empower 401(k) plan-statement regression tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import parser_common
from conftest import approx

FIXTURE = "empower-401k-pdf-synthetic-sample.pdf"
PARSER_FILE = "empower_401k_pdf.py"


def _module(request):
    path = Path(request.config.getoption("--extra-parsers-dir")) / PARSER_FILE
    spec = importlib.util.spec_from_file_location("empower_plan_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_statement(run_statement):
    stmt = run_statement(FIXTURE, "--expected-parser", PARSER_FILE)
    assert stmt.institution == "Empower"
    assert stmt.statement_date == "2026-09-30"
    assert len(stmt.brokerage_holdings) == 3
    assert len(stmt.brokerage_transactions) == 9
    first = stmt.brokerage_transactions[0]
    assert first["account"] == "5678"
    assert first["accountType"] == "401(k)"
    assert first["date"] == "2026-07-17"
    assert first["description"] == "Contribution"
    assert approx(first["amount"], 200.0)
    credit = stmt.brokerage_transactions[3]
    assert credit["date"] == "2026-07-13"
    assert credit["description"] == "Investment Option Service Fee Credit"
    assert approx(credit["amount"], 2.0)
    gain = stmt.brokerage_transactions[-1]
    assert gain["date"] == "2026-09-16"
    assert gain["description"] == "Long Term Capital Gain"
    assert gain["transaction_type"] == "capital_gain"
    assert approx(gain["amount"], 18.0)
    assert approx(gain["quantity"], 0.3)
    assert all(row["account"] == "5678" and row["accountType"] == "401(k)"
               for row in stmt.brokerage_holdings + stmt.brokerage_transactions)
    assert [h["description"] for h in stmt.brokerage_holdings] == [
        "Sample Target 2045 Trust Class A",
        "Fictional Large Cap Index",
        "Imaginary Bond Fund Admin Shares",
    ]
    assert approx(sum(h["current_value"] for h in stmt.brokerage_holdings), 103990.0)


def test_printed_activity_totals(request, dump_pages):
    module = _module(request)
    pages = dump_pages(FIXTURE)
    result = module.parse(pages, "unused.pdf")
    checks = result["checks"]
    transactions = result["tables"]["brokerage_transactions"]
    assert {check["label"] for check in checks} == {
        "Total Deposits/Contributions", "Total Expenses", "Total Dividends/Capital Gains"
    }
    for check in checks:
        assert approx(sum(transactions[i]["amount"] for i in check["rows"]), check["expected"])


def test_detect_is_specific_to_plan(request, dump_pages):
    module = _module(request)
    pages = dump_pages(FIXTURE)
    assert module.detect("\n".join(pages[:3]))[0]
    assert not module.detect("\n".join(pages[:3]).replace("Empower", "OtherBank"))[0]
    assert not module.detect("EMPOWER BROKERAGE\nBROKERAGE ACCOUNT STATEMENT")[0]


def test_holdings_mismatch_fails_loudly(request, dump_pages):
    module = _module(request)
    pages = dump_pages(FIXTURE)
    pages = [page.replace("103,990.00\nHow is my account broken down?",
                          "103,991.00\nHow is my account broken down?") for page in pages]
    with pytest.raises(parser_common.ParserDiagnosticError, match="printed Totals"):
        module.parse(pages, "unused.pdf")
