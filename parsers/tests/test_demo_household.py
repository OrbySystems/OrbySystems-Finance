"""The bundled example household: its parsers, and the claims the
onboarding copy makes about it.

Two different jobs here, deliberately in one file. The first half is
ordinary parser regression coverage. The second half checks that the
HOUSEHOLD still demonstrates what the product says it demonstrates - it
sits just under an IRMAA tier, one position dominates its taxable account,
and its bonds are in the wrong places. Those are load-bearing: the
onboarding screens quote them, so a holding edited without thought would
make the product's own teaching examples wrong while every test still
passed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "demo"
SCRIPTS = REPO / "scripts"

BROKERAGE = sorted(DEMO.glob("vantage-brokerage-*.pdf"))
CARDS = sorted(DEMO.glob("meridian-card-*.pdf"))

# OrbySystems also runs this suite from the copy it embeds, so that a user who
# drops in their own parser can test it from the app. That copy carries
# scripts/ and tests/ but not demo/, which is embedded separately and
# shipped as product content rather than as fixtures - so from there, none
# of this can run.
#
# Skipping rather than failing is right for that case and dangerous in
# general: a whole module that quietly skips is how coverage disappears.
# What makes it safe here is that the demo's presence is asserted on the
# GO side by pkg/demodata's TestBundledStatementsArePresent, which runs in
# CI with no fixtures needed - so a deleted demo fails there loudly rather
# than going green everywhere.
if not DEMO.is_dir() or not BROKERAGE:
    pytest.skip(
        "the demo/ tree is not present - this is the embedded copy of the suite, which "
        "ships scripts/ and tests/ but not the bundled statements",
        allow_module_level=True)


def run(path: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "bank_statement.py"), str(path)],
        cwd=SCRIPTS, capture_output=True, text=True)
    out = proc.stdout.strip()
    assert out, f"no stdout for {path.name} (exit {proc.returncode}):\n{proc.stderr}"
    obj = json.loads(out.splitlines()[-1])
    assert "error" not in obj, f"{path.name}: {obj['error']}"
    assert obj.get("detected"), f"{path.name} was not recognized by any parser"
    return obj


def test_the_demo_statements_exist():
    # Regenerate with tests/generators/gen-demo-household.py. Without them
    # every test below would skip, and a silently empty demo is how the
    # onboarding path breaks without anybody noticing.
    assert len(BROKERAGE) == 6, f"expected 6 brokerage statements, found {len(BROKERAGE)}"
    assert len(CARDS) == 2, f"expected 2 card statements, found {len(CARDS)}"


@pytest.mark.parametrize("path", BROKERAGE, ids=lambda p: p.name)
def test_brokerage_statement_parses(path):
    obj = run(path)
    assert obj["institution"] == "Vantage Brokerage"
    assert obj["statementDate"]
    tables = obj["tables"]
    holdings = tables["brokerage_holdings"]
    txns = tables["brokerage_transactions"]

    # Three accounts, every one classified. An unclassified account is
    # never treated as taxable, so the tax answers would silently go
    # missing rather than come out wrong - which is correct behaviour and
    # a broken demo.
    accounts = {(h["account"], h["accountType"]) for h in holdings}
    assert accounts == {("2041", "Individual"), ("6683", "Roth IRA"), ("3390", "Rollover IRA")}, accounts

    assert len(holdings) == 8, f"expected 8 positions, got {len(holdings)}"
    for h in holdings:
        assert h["quantity"] > 0 and h["price"] > 0
        assert h["current_value"] > 0 and h["cost_basis_total"] > 0
        # Asset location is answerable only if the statement carries the
        # forward income per position.
        assert h["estimated_annual_income"] >= 0

    assert txns, "a statement with no activity teaches nothing about flows"


@pytest.mark.parametrize("path", BROKERAGE, ids=lambda p: p.name)
def test_every_activity_row_is_classified(path):
    """No row relies on its action alone.

    This is the parser-contract rule from scripts/transaction_vocabulary.json:
    money entering or leaving has to be recognisable as such, because every
    growth figure is computed net of it. A parser written today that left it
    to convention would be reintroducing the defect the vocabulary exists to
    prevent.
    """
    sys.path.insert(0, str(SCRIPTS))
    import parser_common  # noqa: E402

    for row in run(path)["tables"]["brokerage_transactions"]:
        assert row.get("transaction_type"), f"{row['action']!r} row carries no transaction_type"
        assert row["transaction_type"] in parser_common.TRANSACTION_TYPES, row["transaction_type"]
        if row["action"] in ("Deposit", "Withdrawal"):
            assert parser_common.classifies_as_flow(row), \
                f"a {row['action']} is not recognised as money moving: {row}"


def test_the_ledger_balances():
    """Nothing is bought with money that appears from nowhere.

    The benchmark dataset shipped for months with 49,239.94 of securities
    funded by nothing, which made every growth figure report those
    purchases as investment gain. The demo must not teach the same lie.
    """
    net = 0.0
    for path in BROKERAGE:
        for row in run(path)["tables"]["brokerage_transactions"]:
            net += row["amount"]
    assert abs(net) < 0.05, f"the demo ledger nets to {net:,.2f}, not 0.00"


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.name)
def test_card_statement_parses_with_orbysystems_signs(path):
    obj = run(path)
    assert obj["institution"] == "Meridian Card"
    txns = obj["tables"]["cash_transactions"]
    assert len(txns) == 12, f"expected 12 transactions, got {len(txns)}"

    charges = [t for t in txns if "AUTOPAY" not in t["description"]]
    payments = [t for t in txns if "AUTOPAY" in t["description"]]
    assert payments, "no payment row, so the sign convention is untested"

    # OrbySystems' convention, not the issuer's: negative means poorer. A
    # statement read in the issuer's own signs produces a household that
    # appears to earn money by buying groceries.
    assert all(t["amount"] < 0 for t in charges), "a purchase is not negative"
    assert all(t["amount"] > 0 for t in payments), "a card payment is not positive"
    for t in txns:
        assert t["accountType"] == "Credit Card"
        assert t["account"] == "8814"


def test_a_card_statement_that_does_not_reconcile_is_rejected():
    """The reconciliation is the parser's own check that it read every row.

    A missed row gives a spending total that is wrong by exactly that row
    and entirely plausible, which nothing downstream can detect - so the
    parser has to refuse rather than return it.
    """
    sys.path.insert(0, str(SCRIPTS))
    from institutions import meridian_card  # noqa: E402

    text = (DEMO / "meridian-card-202603.pdf").read_bytes()
    assert text  # the fixture is present

    summary = {"Previous Balance": 1000.00, "New Balance": 1500.00}
    with pytest.raises(ValueError, match="does not reconcile"):
        meridian_card._reconcile(summary, [{"amount": 100.00}])
    # And the correct case passes quietly.
    meridian_card._reconcile(summary, [{"amount": 500.00}])


# --- the teaching examples ---------------------------------------------

def final_holdings() -> list[dict]:
    return run(BROKERAGE[-1])["tables"]["brokerage_holdings"]


def test_one_position_dominates_the_taxable_account():
    """The Concentrated Position Study is the product sold first, so the
    demo has to contain the problem it solves."""
    taxable = [h for h in final_holdings() if h["account"] == "2041"]
    total = sum(h["current_value"] for h in taxable)
    biggest = max(taxable, key=lambda h: h["current_value"])
    # The position it MEANS, not whichever happens to be largest: a
    # broad-market fund at a third of an account is diversification, and a
    # test that accepted it would let the demo quietly lose its point.
    assert biggest["symbol"] == "NVDA", \
        f"{biggest['symbol']} is the largest taxable position, not the concentrated one"
    share = biggest["current_value"] / total
    assert 0.28 <= share <= 0.36, f"the largest position is {share:.1%} of the taxable account"
    gain = biggest["current_value"] - biggest["cost_basis_total"]
    assert gain > 250_000, f"its embedded gain is only {gain:,.0f}"


def test_the_bonds_are_in_the_wrong_places():
    """Income-throwing assets in the taxable account, and tax-free space
    spent on assets that would barely have been taxed anyway."""
    holdings = final_holdings()
    taxable_bonds = sum(h["current_value"] for h in holdings
                        if h["account"] == "2041" and h["symbol"] in ("BND", "SGOV"))
    assert taxable_bonds > 250_000, "the taxable account holds too few bonds to make the point"

    roth = [h for h in holdings if h["account"] == "6683"]
    roth_total = sum(h["current_value"] for h in roth)
    roth_bonds = sum(h["current_value"] for h in roth if h["symbol"] in ("BND", "SGOV"))
    assert roth_bonds / roth_total > 0.9, "the Roth is not the wasted tax-free space it should be"


def test_the_portfolio_is_the_size_the_onboarding_copy_says():
    total = sum(h["current_value"] for h in final_holdings())
    assert 1_750_000 < total < 1_900_000, f"the demo portfolio is {total:,.0f}"
