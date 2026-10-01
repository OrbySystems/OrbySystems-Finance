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
    assert diagnostic["parserRevision"] == 3
    assert diagnostic["signals"]["credits"] is True
    assert diagnostic["counts"]["holdingsParsed"] == 1
    assert "$" not in json.dumps(diagnostic)


def test_at_work_investments_and_activity(run_statement) -> None:
    stmt = run_statement(
        "etrade-at-work-investments-synthetic-202608.pdf",
        "--expected-parser",
        "etrade_brokerage.py",
    )
    assert stmt.institution == "E*TRADE from Morgan Stanley"
    assert stmt.statement_date == "2026-08-31"
    assert len(stmt.brokerage_holdings) == 3
    assert len(stmt.brokerage_transactions) == 3

    holdings = {row["symbol"]: row for row in stmt.brokerage_holdings}
    assert approx(holdings["CASH"]["current_value"], 1000.00)
    assert approx(holdings["ACM"]["quantity"], 10.0)
    assert approx(holdings["ACM"]["current_value"], 5000.00)
    assert approx(holdings["SIF"]["cost_basis_total"], 4500.00)
    assert all(row["account"] == "2468" for row in stmt.brokerage_holdings)

    transactions = {row["action"]: row for row in stmt.brokerage_transactions}
    assert transactions["Deposit"]["transaction_type"] == "deposit"
    assert approx(transactions["Deposit"]["amount"], 500.00)
    assert transactions["Withdrawal"]["transaction_type"] == "withdrawal"
    assert approx(transactions["Withdrawal"]["amount"], -200.00)
    assert transactions["Qualified Dividend"]["transaction_type"] == "dividend"
    assert approx(transactions["Qualified Dividend"]["amount"], 100.00)


def test_at_work_redacted_cover_still_detects_and_numeric_period_parses() -> None:
    head = "\n".join([
        "CLIENT STATEMENT For the Period xxxxxx x xxxx xxxx",
        "Morgan Stanley Smith Barney LLC. Member SIPC.",
        "E*TRADE is a business of Morgan Stanley.",
    ])
    matched, reason = etrade_brokerage.detect(head)
    assert matched, reason

    start, end = etrade_brokerage._period(
        "This Period (8/1/26-8/31/26) (1/1/26-8/31/26)"
    )
    assert start.isoformat() == "2026-08-01"
    assert end.isoformat() == "2026-08-31"
