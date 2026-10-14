"""Voya 401(k) plan statement parser coverage (synthetic fixture)."""
import importlib.util
from pathlib import Path

import pytest

from conftest import approx

FIXTURE = "voya-401k-pdf-synthetic-sample.pdf"


def test_voya_synthetic_statement(run_statement):
    stmt = run_statement(FIXTURE, "--expected-parser", "voya_401k_pdf.py")
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


def _load_parser(request):
    # A drop-in copy under test when OrbySystems runs the suite with one
    # (--extra-parsers-dir), else the bundled parser.
    extra = request.config.getoption("--extra-parsers-dir")
    if extra and (Path(extra) / "voya_401k_pdf.py").exists():
        path = Path(extra) / "voya_401k_pdf.py"
        spec = importlib.util.spec_from_file_location("voya_401k_pdf_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    from institutions import voya_401k_pdf
    return voya_401k_pdf


# A fixed/stable-value account prints N/A for Shares and Price; category
# headings sit between fund rows. Invented plan, funds and figures.
_FIXED_ACCOUNT_PAGES = [
    "January 01, 2031 - March 31, 2031\nVoya Financial At Your Service\n"
    "Account Balance on 01/01/2031 $12,000.00\nAccount Balance on 03/31/2031 $12,300.00\n",
    "January 01, 2031 - March 31, 2031\n"
    "Activity Statement for Your 401(K) Plan 77B456\n"
    "YourCurrentInvestmentPortfolioforPlan77B456\n"
    "Balance on Investment Balance on Number of Unit/Share\n"
    "Investment Option 01/01/2031 Total Activity Gain 03/31/2031 Units/Shares Price\n"
    "Stability of Principal\n"
    "Voya Fixed Account $7,000.00 $0.00 $70.00 $7,070.00 N/A N/A\n"
    "Large Cap/Value\n"
    "Synthetic Equity Fund C $5,000.00 $0.00 $230.00 $5,230.00 261.5000 $20.0000\n"
    "Total $12,000.00 $0.00 $300.00 $12,300.00\n",
]


def test_voya_fixed_account_without_units(request):
    parser = _load_parser(request)
    ok, _ = parser.detect("\n".join(_FIXED_ACCOUNT_PAGES))
    assert ok
    result = parser.parse(_FIXED_ACCOUNT_PAGES, "")
    assert result["statementDate"] == "2031-03-31"
    holdings = result["tables"]["brokerage_holdings"]
    assert len(holdings) == 2
    fixed, equity = holdings
    assert fixed["description"] == "Voya Fixed Account"
    assert approx(fixed["current_value"], 7070.0)
    assert "quantity" not in fixed and "price" not in fixed
    assert fixed["account"] == "B456" and fixed["accountType"] == "401(k)"
    assert equity["description"] == "Synthetic Equity Fund C"
    assert approx(equity["quantity"], 261.5)
    assert approx(equity["price"], 20.0)
    assert approx(sum(h["current_value"] for h in holdings), 12300.0)


def test_voya_unrecognized_portfolio_row_fails_loudly(request):
    parser = _load_parser(request)
    pages = [_FIXED_ACCOUNT_PAGES[0], _FIXED_ACCOUNT_PAGES[1].replace("N/A N/A", "? ?")]
    with pytest.raises(Exception, match="Unrecognized Voya portfolio row"):
        parser.parse(pages, "")
