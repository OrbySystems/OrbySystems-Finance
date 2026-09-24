"""Regression coverage for E*TRADE Morgan Stanley at Work statements."""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES, approx
import parser_common
from institutions import etrade_brokerage


EXPECTATIONS = FIXTURES / "etrade-at-work-synthetic-202406.expectations.json"


def test_at_work_statement_end_to_end(run_statement, dump_pages) -> None:
    want = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    pages = dump_pages(want["file"])

    matched, reason = etrade_brokerage.detect("\n".join(pages[:3]))
    assert matched, reason

    stmt = run_statement(
        want["file"], "--expected-parser", "etrade_brokerage.py"
    )
    assert stmt.institution == want["institution"]
    assert stmt.statement_date == want["statementDate"]
    assert stmt.brokerage_transactions == []
    assert len(stmt.brokerage_holdings) == want["holdingCount"]

    cash = stmt.brokerage_holdings[0]
    assert cash["symbol"] == "CASH"
    assert cash["is_cash_equivalent"] is True
    assert cash["account"] == want["account"]
    assert cash["accountType"] == want["accountType"]
    assert cash["provider_account_id"] == want["providerAccountId"]
    assert approx(cash["current_value"], want["endingValue"])


def test_at_work_nonzero_activity_fails_instead_of_silently_dropping_rows() -> None:
    pages = [
        "\n".join(
            [
                "CLIENT STATEMENT For the Period April 1- June30, 2024",
                "Morgan Stanley Smith Barney LLC. Member SIPC.",
                "E*TRADE is a business of Morgan Stanley.",
                "Account Summary 999-111111-2468 SUBJECT TO TEST RULES",
                "TOTAL BEGINNING VALUE $2,500.00 $2,500.00",
                "Credits $100.00 $100.00",
                "Debits — —",
                "Security Transfers — —",
                "Net Credits/Debits/Transfers $100.00 $100.00",
                "Change in Value — —",
                "TOTAL ENDING VALUE $2,600.00 $2,600.00",
                "HOLDINGS",
                "MORGAN STANLEY BANK N.A. $2,600.00 — — 0.010",
                "TOTAL VALUE 100.00% — $2,600.00 N/A — —",
            ]
        )
    ]

    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        etrade_brokerage.parse(pages, "unused.pdf")

    assert raised.value.diagnostic_code == "PARSER_ACTIVITY_ROWS_NOT_FOUND"
    assert raised.value.diagnostic_stage == "activity"
    _, diagnostic = parser_common.parser_failure(
        etrade_brokerage,
        raised.value,
        "pdf",
        {"pageCount": 1, "textPageCount": 1},
        pages[0],
    )
    assert diagnostic["parserRevision"] == 2
    assert diagnostic["signals"]["credits"] is True
    assert diagnostic["counts"]["holdingsParsed"] == 1
    assert "$" not in json.dumps(diagnostic)
