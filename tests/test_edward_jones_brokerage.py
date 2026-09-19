"""Edward Jones provisional brokerage parser regression coverage."""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES, approx
from institutions import edward_jones_brokerage


_EXPECT = FIXTURES / "edward-jones-synthetic-202608.expectations.json"


def _expectations() -> dict:
    if not _EXPECT.exists():
        pytest.skip("regenerate with tests/generators/gen-edward-jones-brokerage-synthetic-sample.py")
    return json.loads(_EXPECT.read_text(encoding="utf-8"))


def test_synthetic_statement_end_to_end(run_statement) -> None:
    want = _expectations()
    stmt = run_statement(want["file"])
    assert stmt.institution == want["institution"]
    assert stmt.statement_date == want["statementDate"]

    holdings = stmt.brokerage_holdings
    assert {h["symbol"]: h["current_value"] for h in holdings} == want["positions"]
    assert approx(sum(h["current_value"] for h in holdings), want["endingValue"])
    assert {h["account"] for h in holdings} == {want["account"]}
    assert {h["accountType"] for h in holdings} == {want["accountType"]}
    assert {h["provider_account_id"] for h in holdings} == {want["providerAccountId"]}

    cash = next(h for h in holdings if h["symbol"] == "CASH")
    assert cash["is_cash_equivalent"] is True
    bond = next(h for h in holdings if h["symbol"] == "123456AB7")
    assert bond["security_id_type"] == "CUSIP" and bond["cusip"] == "123456AB7"
    stock = next(h for h in holdings if h["symbol"] == "ALPH")
    assert "Global Innovation Holding" in stock["description"]

    transactions = stmt.brokerage_transactions
    assert len(transactions) == want["transactionCount"]
    totals: dict[str, float] = {}
    for row in transactions:
        kind = row["transaction_type"]
        totals[kind] = round(totals.get(kind, 0.0) + row["amount"], 2)
        assert row["account"] == want["account"]
        assert row["accountType"] == want["accountType"]
    assert totals == want["transactionTotals"]
    assert len([t for t in transactions if t["transaction_type"].startswith("transfer_")]) == 2

    deposit = next(t for t in transactions if t["transaction_type"] == "deposit")
    assert "SYNTHETIC-EDJ-001" in deposit["description"]
    sale = next(t for t in transactions if t["transaction_type"] == "sell")
    assert approx(sale["realized_gain"], want["realizedGain"])
    assert sale["realized_gain_term"] == "Long-term"
    assert stmt.transactions == []


def test_detection_rejects_guide_and_other_brokers() -> None:
    matched, _ = edward_jones_brokerage.detect(
        "Edward Jones | Member SIPC\nUnderstanding my statement\nValue Summary\nAsset Details"
    )
    assert matched is False

    matched, _ = edward_jones_brokerage.detect(
        "Fidelity Investments Member SIPC\nStatement Period: July 1, 2026 - July 31, 2026\n"
        "Account Number: 1234\nValue Summary\nAsset Details"
    )
    assert matched is False


def test_value_summary_mismatch_fails_loudly() -> None:
    lines = [
        "Value Summary",
        "Beginning Value $100.00",
        "Assets Added to Account $10.00",
        "Assets Withdrawn from Account -$5.00",
        "Fees and Charges -$1.00",
        "Change in Value $2.00",
        "Ending Value $999.00",
        "Asset Details",
    ]
    with pytest.raises(ValueError, match="Value Summary does not reconcile"):
        edward_jones_brokerage._value_summary(lines)


def test_resolves_statement_period_across_year_end() -> None:
    start = edward_jones_brokerage.date(2025, 12, 27)
    end = edward_jones_brokerage.date(2026, 1, 30)
    assert edward_jones_brokerage._resolve_date("12/29", start, end) == "2025-12-29"
    assert edward_jones_brokerage._resolve_date("01/15", start, end) == "2026-01-15"
