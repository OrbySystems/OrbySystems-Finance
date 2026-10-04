"""Charles Schwab retail brokerage parser regression coverage.

The generator emits expectations beside the synthetic PDF so fixture data and
assertions move together.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from conftest import FIXTURES, approx
from institutions import schwab_brokerage


_EXPECT = FIXTURES / "schwab-retail-synthetic-202608.expectations.json"


def _expectations() -> dict:
    if not _EXPECT.exists():
        pytest.skip("regenerate with tests/generators/gen-schwab-brokerage-synthetic-sample.py")
    return json.loads(_EXPECT.read_text(encoding="utf-8"))


def test_synthetic_statement_end_to_end(run_statement) -> None:
    want = _expectations()
    stmt = run_statement(want["file"], "--expected-parser", "schwab_brokerage.py")
    assert stmt.institution == want["institution"]
    assert stmt.statement_date == want["statementDate"]

    holdings = stmt.brokerage_holdings
    positions = {h["symbol"]: h["current_value"] for h in holdings}
    assert positions == want["positions"]
    assert {h["account"] for h in holdings} == {want["account"]}
    assert {h["accountType"] for h in holdings} == {want["accountType"]}
    assert approx(sum(h["current_value"] for h in holdings), want["endingValue"])

    cash = next(h for h in holdings if h["symbol"] == "CASH")
    assert cash["is_cash_equivalent"] is True
    bond = next(h for h in holdings if h["symbol"] == "111111SY1")
    assert bond["security_id_type"] == "CUSIP" and bond["cusip"] == "111111SY1"
    alph = next(h for h in holdings if h["symbol"] == "ALPH")
    assert "GLOBAL SYNTHETIC INNOVATION HOLDING" in alph["description"]

    transactions = stmt.brokerage_transactions
    assert len(transactions) == want["transactionCount"]
    assert all(t.get("symbol") != want["pendingSymbolExcluded"] for t in transactions)
    totals: dict[str, float] = {}
    for row in transactions:
        kind = row["transaction_type"]
        totals[kind] = round(totals.get(kind, 0.0) + row["amount"], 2)
        assert row["account"] == want["account"]
        assert row["accountType"] == want["accountType"]
    assert totals == want["transactionTotals"]
    deposit = next(t for t in transactions if t["transaction_type"] == "deposit")
    assert "SYNTHETIC-001" in deposit["description"]

    # The nine duplicate Bank Sweep movements are reconciled internally but
    # not emitted, the pending purchase is skipped, and the two stock-plan
    # rows remain non-cash corporate actions even though Schwab prints market
    # values in their Amount column.
    assert len(transactions) == 11
    corporate = [t for t in transactions if t["transaction_type"] == "corporate_action"]
    assert len(corporate) == 2
    assert all(t["amount"] == 0.0 and t["action"] == "Stock Plan Activity" for t in corporate)
    assert corporate[0]["date"] == corporate[1]["date"]


def test_detection_rejects_guides_sibling_formats_and_other_brokers() -> None:
    matched, _ = schwab_brokerage.detect("Schwab Account Summary educational guide")
    assert matched is False

    matched, _ = schwab_brokerage.detect(
        "Charles Schwab Advisor Services Statement Format\n"
        "Statement Period: August 1 - 31, 2026\nAccount Summary\n"
        "Account Number: 1111\nBrokerage Account"
    )
    assert matched is False

    matched, _ = schwab_brokerage.detect(
        "Fidelity Investments\nINVESTMENT REPORT\nAugust 1, 2026 - August 31, 2026\n"
        "Account Summary"
    )
    assert matched is False


def test_account_summary_mismatch_fails_loudly() -> None:
    broken = {
        "Beginning Value": 100.0,
        "Deposits": 10.0,
        "Withdrawals": 0.0,
        "Dividends and Interest": 0.0,
        "Transfer of Securities (In/Out)": 0.0,
        "Market Value Change": 0.0,
        "Fees": 0.0,
        "Ending Value": 999.0,
    }
    with pytest.raises(ValueError, match="Account Summary does not reconcile"):
        schwab_brokerage._reconcile_account_summary(broken)


def test_compact_current_statement_summaries() -> None:
    account = schwab_brokerage._current_account_summary(
        [
            "BeginningAccountValue $100.00 $100.00",
            "Deposits $10.00 $10.00",
            "Withdrawals ($5.00) ($5.00)",
            "DividendsandInterest $1.00 $1.00",
            "TransferofSecurities $0.00 $0.00",
            "MarketAppreciation/(Depreciation) $2.00 $2.00",
            "Expenses ($1.00) ($1.00)",
            "EndingAccountValue $107.00 $107.00",
        ]
    )
    schwab_brokerage._reconcile_account_summary(account)

    transactions = schwab_brokerage._current_transaction_summary(
        [
            "BeginningCash*asof08/01 + Deposits + Withdrawals + Purchases + "
            "Sales/Redemptions + Dividends/Interest + Expenses = EndingCash*asof08/31",
            "$10.00 $20.00 ($5.00) ($4.00) $2.00 $1.00 ($1.00) $23.00",
        ]
    )
    assert transactions == {
        "Beginning Cash": 10.0,
        "Deposits": 20.0,
        "Withdrawals": -5.0,
        "Purchases": -4.0,
        "Sales/Redemptions": 2.0,
        "Dividends/Interest": 1.0,
        "Fees": -1.0,
        "Ending Cash": 23.0,
    }


@pytest.mark.parametrize(
    ("printed", "amount", "term"),
    [
        ("123.45,(ST)", 123.45, "Short-term"),
        ("67.89(LT)", 67.89, "Long-term"),
        ("(12.34),(LT)", -12.34, "Long-term"),
    ],
)
def test_realized_gain_term_glued_to_amount(printed: str, amount: float, term: str) -> None:
    block = [(10.0, [{"text": printed, "x0": 100.0, "top": 10.0}])]
    parsed, parsed_term = schwab_brokerage._cell_realized_gain(block, (90.0, 150.0))
    assert parsed == amount
    assert parsed_term == term


def test_summary_without_a_line_for_activity_the_account_had_none_of() -> None:
    # A real January 2026 statement printed no Transfer of Securities line.
    account = schwab_brokerage._current_account_summary(
        [
            "BeginningAccountValue $100.00 $100.00",
            "Deposits 0.00 0.00",
            "Withdrawals (95.00) (95.00)",
            "DividendsandInterest 0.50 0.50",
            "MarketAppreciation/(Depreciation) 2.00 2.00",
            "Expenses 0.00 0.00",
            "EndingAccountValue $7.50 $7.50",
        ]
    )
    assert "Transfer of Securities (In/Out)" not in account
    schwab_brokerage._reconcile_account_summary(account)


def test_a_left_out_summary_line_does_not_excuse_one_that_does_not_add_up() -> None:
    with pytest.raises(ValueError, match="Account Summary does not reconcile"):
        schwab_brokerage._reconcile_account_summary(
            {"Beginning Value": 100.0, "Withdrawals": -95.0, "Ending Value": 7.5}
        )
    with pytest.raises(ValueError, match="missing Schwab control total"):
        schwab_brokerage._reconcile_account_summary({"Withdrawals": -95.0, "Ending Value": 5.0})


def _word(text: str, x0: float, top: float) -> dict:
    return {"text": text, "x0": x0, "top": top}


def test_positioned_table_ends_at_a_totals_line_whatever_its_label(monkeypatch) -> None:
    # A scrambled sample replaces "Total Transactions" with a made-up word.
    # The totals line is still a totals line: left margin, no date, amounts.
    rows = [
        (100.0, [_word(t, x, 100.0) for t, x in (
            ("Date", 40), ("Category", 80), ("Action", 130), ("Symbol/", 180), ("Description", 230),
            ("Quantity", 330), ("Price/Rate", 380), ("Charges/", 430), ("Amount", 480), ("Realized", 530),
        )]),
        (120.0, [_word(t, x, 120.0) for t, x in (
            ("01/13", 40), ("Sale", 80), ("ABCD", 180), ("SYNTHETIC", 230), ("(10.0000)", 330),
            ("12.3400", 380), ("1.00", 430), ("123.40", 480), ("20.00,(ST)", 530),
        )]),
        (135.0, [_word(t, x, 135.0) for t, x in (("01/29", 40), ("Interest", 80), ("BANK", 230), ("0.50", 480))]),
        (150.0, [_word(t, x, 150.0) for t, x in (("Zimuripacukoneger", 40), ("($1.00)", 430), ("$20.00", 530))]),
    ]

    class _PDF:
        pages = [object()]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(schwab_brokerage.pdfplumber, "open", lambda _path: _PDF())
    monkeypatch.setattr(schwab_brokerage, "_word_rows", lambda _page: rows)

    def parse() -> list[dict]:
        return schwab_brokerage._parse_positioned_transactions(
            "statement.pdf", date(2026, 1, 1), date(2026, 1, 31), "1234", "Brokerage", "1234-5678"
        )

    with monkeypatch.context() as m:
        m.setattr(schwab_brokerage, "_is_totals_row", lambda *_: False)
        assert parse()[1].get("realized_gain") == 20.0  # what the check prevents

    sale, interest = parse()
    assert sale["transaction_type"] == "sell" and sale["realized_gain"] == 20.0
    assert interest["transaction_type"] == "interest" and interest["amount"] == 0.5
    assert "realized_gain" not in interest
