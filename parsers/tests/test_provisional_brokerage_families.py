"""End-to-end coverage for the documented provisional statement families."""

from __future__ import annotations

import importlib
import json

import pytest

from conftest import FIXTURES, approx
import parser_common
from institutions import provisional_brokerage_common as core


CASES = [
    (key, FIXTURES / f"{profile['slug']}-synthetic-202608.expectations.json")
    for key, profile in core.PROFILES.items()
]

PROFILE_MODULES = {
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


@pytest.mark.parametrize(("profile_key", "expectations_path"), CASES)
def test_synthetic_statement_end_to_end(profile_key, expectations_path, run_statement) -> None:
    want = json.loads(expectations_path.read_text(encoding="utf-8"))
    stmt = run_statement(
        want["file"],
        "--expected-parser",
        f"{PROFILE_MODULES[profile_key]}.py",
    )
    assert stmt.institution == want["institution"]
    assert stmt.statement_date == want["statementDate"]

    holdings = stmt.brokerage_holdings
    assert {row["symbol"]: row["current_value"] for row in holdings} == want["positions"]
    assert approx(sum(row["current_value"] for row in holdings), want["endingValue"])
    assert {row["account"] for row in holdings} == {want["account"]}
    assert {row["accountType"] for row in holdings} == {want["accountType"]}
    assert {row["provider_account_id"] for row in holdings} == {want["providerAccountId"]}

    cash = next(row for row in holdings if row["symbol"] == "CASH")
    assert cash["is_cash_equivalent"] is True
    bond = next(row for row in holdings if row["symbol"] == "123456AB7")
    assert bond["security_id_type"] == "CUSIP" and bond["cusip"] == "123456AB7"
    stock = next(row for row in holdings if row["symbol"] == "ALPH")
    assert "Global Innovation Holding" in stock["description"]

    transactions = stmt.brokerage_transactions
    assert len(transactions) == want["transactionCount"]
    totals: dict[str, float] = {}
    for row in transactions:
        kind = row["transaction_type"]
        totals[kind] = round(totals.get(kind, 0.0) + row["amount"], 2)
        assert row["account"] == want["account"]
        assert row["accountType"] == want["accountType"]
        assert row["provider_account_id"] == want["providerAccountId"]
    assert totals == want["transactionTotals"]
    sale = next(row for row in transactions if row["transaction_type"] == "sell")
    assert approx(sale["realized_gain"], want["realizedGain"])
    assert sale["realized_gain_term"] == "Long-term"


@pytest.mark.parametrize("profile_key", list(core.PROFILES))
def test_detection_requires_institution_specific_structure(profile_key: str) -> None:
    profile = core.PROFILES[profile_key]
    matched, _ = core.detect_profile(
        f"{profile['brand']}\n{profile['title']}\nStatement Period: {core.PERIOD}\n"
        f"Account Number: {profile['account_id']}\n{profile['summary']}",
        profile_key,
    )
    assert matched is False

    matched, _ = core.detect_profile(
        f"UNRELATED BROKER\n{profile['title']}\nStatement Period: {core.PERIOD}\n"
        f"Account Number: {profile['account_id']}\n{profile['summary']}\n{profile['holdings']}",
        profile_key,
    )
    assert matched is False


@pytest.mark.parametrize(("profile_key", "expectations_path"), CASES)
def test_provisional_failure_has_repair_grade_diagnostics(
    profile_key, expectations_path, dump_pages
) -> None:
    want = json.loads(expectations_path.read_text(encoding="utf-8"))
    profile = core.PROFILES[profile_key]
    pages = dump_pages(want["file"])
    ending_label = profile["labels"]["ending"]
    broken_pages = [page.replace(ending_label, "Closing Control") for page in pages]

    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        core.parse_profile(broken_pages, "unused.pdf", profile_key)

    module = importlib.import_module(f"institutions.{PROFILE_MODULES[profile_key]}")
    _, diagnostic = parser_common.parser_failure(
        module,
        raised.value,
        "pdf",
        {"pageCount": len(pages), "textPageCount": len(pages)},
        "\n".join(broken_pages),
    )

    assert diagnostic["code"] == "PARSER_REQUIRED_DATA_MISSING"
    assert diagnostic["stage"] == "summary"
    assert diagnostic["missingFields"] == ["endingValue"]
    assert diagnostic["fieldPresence"]["beginningValue"] is True
    assert diagnostic["fieldPresence"]["endingValue"] is False
    assert diagnostic["signals"]["beginningBalance"] is True
    assert diagnostic["counts"]["summaryComponents"] == 6
    assert diagnostic["counts"]["sectionMarkersPresent"] >= 5
    assert diagnostic["parserRevision"] == module.PARSER_REVISION
    encoded = json.dumps(diagnostic)
    assert profile["account_id"] not in encoded
    assert "$" not in encoded

def test_summary_mismatch_fails_loudly() -> None:
    profile = core.PROFILES["raymond_james"]
    labels = profile["labels"]
    lines = [
        profile["summary"],
        f"{labels['beginning']} $100.00",
        f"{labels['deposits']} $10.00",
        f"{labels['withdrawals']} -$5.00",
        f"{labels['income']} $1.00",
        f"{labels['fees']} -$1.00",
        f"{labels['market']} $2.00",
        f"{labels['ending']} $999.00",
        profile["holdings"],
    ]
    with pytest.raises(ValueError, match="account summary does not reconcile"):
        core._summary(lines, profile)


def test_resolves_activity_dates_across_year_end() -> None:
    start = core.date(2025, 12, 27)
    end = core.date(2026, 1, 30)
    assert core._resolve_date("12/29", start, end) == "2025-12-29"
    assert core._resolve_date("01/15", start, end) == "2026-01-15"
