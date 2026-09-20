"""Schwab Retirement Plan Services 401(k) parser coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parser_common
from conftest import approx
from institutions import schwab_401k_brokerage_pdf as schwab_401k


FIXTURES = Path(__file__).parent / "fixtures"
EXPECTATIONS = FIXTURES / "schwab-401k-synthetic-202606.expectations.json"


def test_schwab_401k_synthetic_statement(run_statement):
    expected = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    stmt = run_statement(
        "schwab-401k-synthetic-202606.pdf",
        "--expected-parser",
        "schwab_401k_brokerage_pdf.py",
    )

    assert stmt.institution == expected["institution"]
    assert stmt.statement_date == expected["statementDate"]
    assert len(stmt.brokerage_holdings) == expected["holdingCount"]
    assert len(stmt.brokerage_transactions) == expected["transactionCount"]
    assert all(row["account"] == "" for row in stmt.brokerage_holdings)
    assert all(row["accountType"] == expected["accountType"] for row in stmt.brokerage_holdings)

    growth = stmt.brokerage_holdings[0]
    assert growth["description"] == "Synthetic Growth Trust"
    assert growth["symbol"] == "SYNTHETIC GROWTH TRUST"
    assert approx(growth["quantity"], 100.0)
    assert approx(growth["price"], 220.0)
    assert approx(growth["current_value"], 22000.0)
    assert approx(growth["percent_of_account"], 20.0)

    stable = stmt.brokerage_holdings[2]
    assert stable["description"] == "Synthetic Stable Value Fund"
    assert "quantity" not in stable
    assert "price" not in stable
    assert stable["is_cash_equivalent"] is True
    assert approx(stable["current_value"], 55000.0)
    # Real Schwab RPS statements can print the percentage only on the
    # category heading, leaving a cash-equivalent holding's own cell blank.
    assert approx(stable["percent_of_account"], 50.0)
    assert approx(sum(row["current_value"] for row in stmt.brokerage_holdings), expected["endingValue"])

    employee, employer, fee = stmt.brokerage_transactions
    assert employee["action"] == "Employee Contribution"
    assert employee["transaction_type"] == "contribution"
    assert approx(employee["amount"], 3000.0)
    assert employer["action"] == "Employer Contribution"
    assert approx(employer["amount"], 1500.0)
    assert fee["transaction_type"] == "fee"
    assert approx(fee["amount"], -5.0)


def test_compact_text_layer_summary_and_period() -> None:
    """Cover the spacing and wrap order observed in a real RPS text layer."""
    pages = [
        "\n".join(
            [
                "Periodcovered:APRIL1,2026TOJUNE30,2026",
                "Changein PlanAccountValue",
                "BeginningValue$100,000.00$95,000.00",
                "YourContributions3,000.006,000.00",
                "EmployerContributions1,500.003,000.00",
                "IndividualTransactionFees*0.000.00",
                # The monetary columns precede the wrapped Fees* suffix in
                # extraction order on the real statement.
                "PlanAdministrationandOther(5.00)(10.00)",
                "Fees*",
                "Gain/Loss/NetIncome5,505.006,010.00",
                "EndingValue$110,000.00$110,000.00",
            ]
        )
    ]

    assert schwab_401k._statement_date(pages[0]) == "2026-06-30"
    assert schwab_401k._summary(pages) == {
        "beginning": 100000.0,
        "employee": 3000.0,
        "employer": 1500.0,
        "transaction_fees": 0.0,
        "plan_fees": -5.0,
        "gain_loss": 5505.0,
        "ending": 110000.0,
    }


def test_schwab_401k_detector_does_not_claim_retail_statement():
    matched, _ = schwab_401k.detect(
        "Charles Schwab\nSchwab One Brokerage Account\nAccount Summary\nStatement Period"
    )
    assert matched is False


def test_schwab_401k_missing_control_has_privacy_safe_diagnostic(dump_pages):
    pages = dump_pages("schwab-401k-synthetic-202606.pdf")
    broken = [
        page.replace("Ending Value", "Closing Total").replace("EndingValue", "ClosingTotal")
        for page in pages
    ]

    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        schwab_401k.parse(broken, str(FIXTURES / "schwab-401k-synthetic-202606.pdf"))

    _, diagnostic = parser_common.parser_failure(
        schwab_401k,
        raised.value,
        "pdf",
        {"pageCount": len(pages), "textPageCount": len(pages)},
        "\n".join(broken),
    )
    assert diagnostic["code"] == "PARSER_REQUIRED_DATA_MISSING"
    assert diagnostic["stage"] == "summary"
    assert diagnostic["missingFields"] == ["endingValue"]
    assert diagnostic["parserRevision"] == 1
    encoded = json.dumps(diagnostic)
    assert "$110,000.00" not in encoded
    assert "TEST PARTICIPANT" not in encoded
