"""Repair-grade diagnostic coverage for custom top-20 statement parsers."""

from __future__ import annotations

import importlib
import json
import re

import pytest

from conftest import FIXTURES
import parser_common
from institutions import edward_jones_brokerage
from institutions import fidelity_brokerage
from institutions import fidelity_401k_brokerage_pdf
from institutions import provisional_brokerage_common as provisional
from institutions import schwab_401k_brokerage_pdf
from institutions import schwab_brokerage
from institutions import vanguard_brokerage


_PROFILE_MODULES = {
    "ameriprise": "ameriprise_brokerage",
    "apex_clearing": "apex_clearing_brokerage",
    "bny_pershing": "bny_pershing_brokerage",
    "empower": "empower_investments",
    "etrade": "etrade_brokerage",
    "interactive_brokers": "interactive_brokers_activity",
    "jp_morgan_wealth": "jp_morgan_wealth_brokerage",
    "lpl_financial": "lpl_financial_brokerage",
    "merrill_wealth": "merrill_wealth_management",
    "morgan_stanley_wealth": "morgan_stanley_wealth_brokerage",
    "principal": "principal_retirement",
    "raymond_james": "raymond_james_brokerage",
    "robinhood": "robinhood_brokerage",
    "t_rowe_price": "t_rowe_price_brokerage",
    "ubs_wealth": "ubs_wealth_management",
    "wells_fargo_advisors": "wells_fargo_advisors",
}


def _diagnostic(module, pages: list[str], pdf_path) -> dict:
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        module.parse(pages, str(pdf_path))
    _, diagnostic = parser_common.parser_failure(
        module,
        raised.value,
        "pdf",
        {"pageCount": len(pages), "textPageCount": len(pages)},
        "\n".join(pages),
    )
    encoded = json.dumps(diagnostic)
    assert "$" not in encoded
    assert diagnostic["signals"]
    assert diagnostic["counts"]["financialLabelRows"] > 0
    assert diagnostic["counts"]["sectionMarkersPresent"] > 0
    assert diagnostic["parserRevision"] == 1
    return diagnostic


def test_top20_primary_pdf_families_declare_repair_grade_contract() -> None:
    modules = [
        fidelity_brokerage,
        schwab_brokerage,
        vanguard_brokerage,
        edward_jones_brokerage,
        *(
            importlib.import_module(f"institutions.{_PROFILE_MODULES[key]}")
            for key in provisional.PROFILES
        ),
    ]
    assert len(modules) == 20
    for module in modules:
        assert module.DIAGNOSTIC_MARKERS
        assert module.DIAGNOSTIC_FIELDS
        assert module.DIAGNOSTIC_SIGNALS
        assert module.DIAGNOSTIC_COUNTS
        assert module.DIAGNOSTIC_TERMS
        assert module.PARSER_REVISION >= 1

    # NetBenefits and Schwab Retirement Plan Services are additional
    # institution-specific families alongside the top-20 primary contract.
    assert fidelity_401k_brokerage_pdf.PARSER_REVISION >= 5
    assert schwab_401k_brokerage_pdf.PARSER_REVISION >= 1


def test_schwab_failure_has_repair_grade_diagnostics(dump_pages) -> None:
    filename = "schwab-retail-synthetic-202608.pdf"
    pages = dump_pages(filename)
    broken = [page.replace("Total Positions", "Positions Control") for page in pages]
    assert broken != pages

    diagnostic = _diagnostic(schwab_brokerage, broken, FIXTURES / filename)
    assert diagnostic["code"] == "PARSER_REQUIRED_DATA_MISSING"
    assert diagnostic["stage"] == "holdings"
    assert diagnostic["missingFields"] == ["totalPositions"]
    assert diagnostic["fieldPresence"]["totalPositions"] is False
    assert diagnostic["sections"]["holdings"] is True


def test_edward_jones_failure_has_repair_grade_diagnostics(dump_pages) -> None:
    filename = "edward-jones-synthetic-202608.pdf"
    pages = dump_pages(filename)
    broken = [page.replace("Total Account Value", "Account Control") for page in pages]
    assert broken != pages

    diagnostic = _diagnostic(edward_jones_brokerage, broken, FIXTURES / filename)
    assert diagnostic["code"] == "PARSER_REQUIRED_DATA_MISSING"
    assert diagnostic["stage"] == "holdings"
    assert diagnostic["fieldPresence"]["totalAccountValue"] is False
    assert diagnostic["sections"]["holdings"] is True


def test_vanguard_failure_has_repair_grade_diagnostics(dump_pages) -> None:
    filename = "vanguard-voyager-synthetic-sample.pdf"
    pages = dump_pages(filename)
    broken = [
        re.sub(r"(?m)^[A-Z][a-z]+ \d{1,2}, \d{4},", "Statement Date Missing,", page)
        for page in pages
    ]
    assert broken != pages

    diagnostic = _diagnostic(vanguard_brokerage, broken, FIXTURES / filename)
    assert diagnostic["code"] == "PARSER_STATEMENT_DATE_INVALID"
    assert diagnostic["stage"] == "metadata"
    assert diagnostic["sections"]["holdings"] is True
    assert diagnostic["sections"]["activity"] is True


def test_fidelity_failure_has_repair_grade_diagnostics(dump_pages) -> None:
    filename = "fidelity-synthetic-202601.pdf"
    pages = dump_pages(filename)
    broken = [
        re.sub(
            r"(?m)^(Total Holdings\s+)(?:-?\$?-?[\d,]+\.\d+)",
            r"\g<1>$0.01",
            page,
        )
        for page in pages
    ]
    assert broken != pages

    diagnostic = _diagnostic(fidelity_brokerage, broken, FIXTURES / filename)
    assert diagnostic["code"] == "PARSER_RECONCILIATION_FAILED"
    assert diagnostic["stage"] == "holdings"
    assert diagnostic["fieldPresence"]["totalHoldings"] is True
    assert diagnostic["reconciliationDirection"] == "printedEndingBelowParsedEquation"
    assert diagnostic["sections"]["activity"] is True
