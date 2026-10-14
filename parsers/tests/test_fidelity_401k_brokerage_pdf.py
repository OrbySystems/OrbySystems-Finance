"""Fidelity NetBenefits Statement Details PDF coverage (synthetic fixtures).

Revision 7 reads the holdings snapshot and nothing else: the PDF prints
only activity totals, so transactions still come from the Transaction
History CSV export (see the parser's docstring)."""
import importlib.util
from pathlib import Path

import pytest

import parser_common
from conftest import approx

PARSER = "fidelity_401k_brokerage_pdf.py"
BASELINE = "fidelity-401k-brokerage-pdf-synthetic-sample.pdf"
ZERO_OMITTED = "fidelity-401k-zero-omitted-synthetic-sample.pdf"
GENERIC_EXCHANGE = "fidelity-401k-generic-exchange-synthetic-sample.pdf"
STATEMENT_DETAILS = "fidelity-401k-statement-details-synthetic-sample.pdf"


def _load_parser(request):
    # A drop-in copy under test when OrbySystems runs the suite with one
    # (--extra-parsers-dir), else the bundled parser.
    extra = request.config.getoption("--extra-parsers-dir")
    if extra and (Path(extra) / PARSER).exists():
        spec = importlib.util.spec_from_file_location("fidelity_401k_under_test", Path(extra) / PARSER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    from institutions import fidelity_401k_brokerage_pdf
    return fidelity_401k_brokerage_pdf


def _holdings(stmt):
    assert stmt.institution == "Fidelity NetBenefits"
    assert len(stmt.transactions) == 0
    assert len(stmt.brokerage_transactions) == 0
    return stmt.brokerage_holdings


def test_detects_netbenefits_statement(request, dump_pages):
    parser = _load_parser(request)
    matched, _ = parser.detect("\n".join(dump_pages(BASELINE)))
    assert matched


def test_rejects_other_text(request):
    parser = _load_parser(request)
    matched, reason = parser.detect("some unrelated statement text")
    assert not matched
    assert "fidelity netbenefits" in reason.lower()


def test_baseline_holdings(run_statement):
    holdings = _holdings(run_statement(BASELINE, "--expected-parser", PARSER))
    assert [h["description"] for h in holdings] == [
        "Synthetic Growth Index Fund", "Blue Horizon Bond Pool", "Stable Value Income Fd",
    ]
    # This layout prints its category labels without class headings, so
    # the label is the classification.
    assert [h.get("subtype") for h in holdings] == ["INDEX FUNDS (PASSIVELY MANAGED)", "Bond", "Income"]
    assert not any("sector" in h for h in holdings)
    assert all(h["account"] == "2468" and h["accountType"] == "401(k)" for h in holdings)
    growth = holdings[0]
    assert growth["symbol"] == "SYNTHETIC GROWTH INDEX FUND"
    assert approx(growth["quantity"], 60.0)
    assert approx(growth["price"], 101.25)
    assert approx(growth["current_value"], 6075.0)
    assert growth["price_as_of"] == "2026-06-30"
    assert growth["type"] == "Mutual Fund"
    assert approx(sum(h["current_value"] for h in holdings), 10388.0)


def test_zero_omitted_holdings(run_statement):
    stmt = run_statement(ZERO_OMITTED, "--expected-parser", PARSER)
    holdings = _holdings(stmt)
    assert stmt.statement_date == "2026-09-17"
    assert len(holdings) == 2
    assert approx(sum(h["current_value"] for h in holdings), 11000.0)


def test_generic_exchange_holdings(run_statement):
    holdings = _holdings(run_statement(GENERIC_EXCHANGE, "--expected-parser", PARSER))
    assert len(holdings) == 3
    assert all(h["account"] == "9753" for h in holdings)
    assert approx(sum(h["current_value"] for h in holdings), 10250.0)


def test_statement_details_wrapped_names_and_labels(run_statement):
    # The Q3 2026 layout: names wrapped over two lines, either line on the
    # figures' line; class headings with subtotals and labels above the
    # first fund under them; the table carried onto a second page; no
    # account number printed.
    stmt = run_statement(STATEMENT_DETAILS, "--expected-parser", PARSER)
    holdings = _holdings(stmt)
    assert stmt.statement_date == "2026-09-30"
    assert [h["description"] for h in holdings] == [
        "Synthetic Total Market Index K", "Synthetic Growth Pool K", "Synthetic Widget Co Stock Fund",
        "Synthetic Stable Value Fund", "Synthetic Target Date 2045 K",
    ]
    assert all(h["account"] == "" and h["accountType"] == "401(k)" for h in holdings)

    stable = holdings[3]
    assert stable["type"] == "Fixed Account"
    assert "quantity" not in stable and "price" not in stable
    assert approx(stable["current_value"], 15150.0)
    # The fund sold out during the quarter prints at $0.00 and is not held.
    assert not any("2030" in h["description"] for h in holdings)
    assert approx(sum(h["current_value"] for h in holdings), 53950.0)


def test_statement_details_classes_from_headings(run_statement):
    # Each fund carries the class heading it is filed under and the label
    # under that heading - including the Company Stock fund at the top of
    # page 2, whose Stock heading was printed on page 1 only.
    holdings = _holdings(run_statement(STATEMENT_DETAILS, "--expected-parser", PARSER))
    classes = [(h["type"], h.get("subtype"), h.get("sector")) for h in holdings]
    assert classes == [
        ("Mutual Fund", "Stock", "Large Cap"),
        ("Mutual Fund", "Stock", "Large Cap"),
        ("Stock", "Stock", "Company Stock"),
        ("Fixed Account", "Bond", "Stable Value"),
        ("Mutual Fund", "Blended Fund Investments", None),
    ]


def test_text_only_keeps_the_figures_line_name(request, dump_pages):
    # Without the PDF a wrapped name keeps only its part on the figures'
    # line, and only the class headings can be read - a label line looks
    # like part of a name. The values are the same.
    parser = _load_parser(request)
    result = parser.parse(dump_pages(STATEMENT_DETAILS), "")
    holdings = result["tables"]["brokerage_holdings"]
    assert [h["description"] for h in holdings] == [
        "Synthetic Total", "Growth Pool K", "Synthetic Widget", "Synthetic Stable", "Synthetic Target",
    ]
    assert [h.get("subtype") for h in holdings] == ["Stock", "Stock", "Stock", "Bond", "Blended Fund Investments"]
    assert not any("sector" in h for h in holdings)
    assert approx(sum(h["current_value"] for h in holdings), 53950.0)


def test_totals_mismatch_fails(request, dump_pages):
    parser = _load_parser(request)
    pages = [p.replace("Account Totals $52,000.00 $53,950.00", "Account Totals $52,000.00 $53,000.00")
             for p in dump_pages(STATEMENT_DETAILS)]
    assert pages != dump_pages(STATEMENT_DETAILS)
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        parser.parse(pages, "")
    assert raised.value.diagnostic_code == "PARSER_RECONCILIATION_FAILED"


def test_no_holdings_table_fails(request, dump_pages):
    parser = _load_parser(request)
    pages = [p.replace("Market Value of Your Account", "Something Else") for p in dump_pages(STATEMENT_DETAILS)]
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        parser.parse(pages, "")
    assert raised.value.diagnostic_code == "PARSER_REQUIRED_DATA_MISSING"
