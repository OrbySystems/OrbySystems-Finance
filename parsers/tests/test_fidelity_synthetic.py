"""Fidelity brokerage parser, ported from
pkg/ingest/fidelity_synthetic_test.go's TestExtractFidelitySynthetic and
TestExtractFidelitySyntheticYearEnd.

Expected values are not transcribed here - the generators
(tests/generators/gen-fidelity-synthetic-sample.py and
gen-fidelity-year-end-sample.py) emit them alongside the PDFs, so fixture
data and assertions move together.
"""

import json

import pytest

from conftest import FIXTURES, approx
from institutions import fidelity_brokerage

_EXPECT = FIXTURES / "fidelity-synthetic-expectations.json"
_YEAR_END_EXPECT = FIXTURES / "fidelity-synthetic-year-end-expectations.json"


def test_merger_out_direct_exchanged_for_cusip_note():
    row = {"_name": "EXXON MOBIL CORP COM"}
    fidelity_brokerage._collect_corporate_note(row, "EXCHANGED FOR 30233Q108")
    assert row["related_security_id"] == "30233Q108"


def test_merger_in_wraps_mer_from_cusip():
    row = {"_name": "QXO INC COM NEW MER FROM"}
    fidelity_brokerage._collect_inline_corporate_note(row)
    assert row["_await_merger_from"]
    fidelity_brokerage._collect_corporate_note(row, "89055F103")
    assert row["related_security_id"] == "89055F103"
    assert row["_name"] == "QXO INC COM NEW"


@pytest.mark.parametrize(
    ("name", "notes", "successor", "reference", "clean_name"),
    [
        (
            "EXXON MOBIL CORP COM EXCHANGED",
            ["FOR CUSIP", "30233Q108 MER PAYOUT #REOR", "M0051755570000"],
            "30233Q108", "M0051755570000", "EXXON MOBIL CORP COM",
        ),
        (
            "TOPBUILD CORP COM EXCHANGED FOR",
            ["20.20", "SHARES OF CUSIP 82846H405 MER", "PAYOUT #REOR M0051757350000"],
            "82846H405", "M0051757350000", "TOPBUILD CORP COM",
        ),
    ],
)
def test_merger_out_wrapped_exchange_note(name, notes, successor, reference, clean_name):
    row = {"_name": name}
    fidelity_brokerage._collect_inline_corporate_note(row)
    for note in notes:
        fidelity_brokerage._collect_corporate_note(row, note)
    assert row["related_security_id"] == successor
    assert row["reference"] == reference
    assert row["_name"] == clean_name


def test_merger_legs_fill_missing_link_from_cusips():
    incoming = {
        "date": "2026-07-08", "action": "Merger In",
        "security_id": "82846H405", "related_security_id": "89055F103",
    }
    outgoing = {
        "date": "2026-07-08", "action": "Merger Out",
        "security_id": "89055F103",
    }
    fidelity_brokerage._link_merger_legs([incoming, outgoing])
    assert outgoing["related_security_id"] == "82846H405"


def _statements():
    if not _EXPECT.exists():
        pytest.skip("regenerate with tests/generators/gen-fidelity-synthetic-sample.py")
    return json.loads(_EXPECT.read_text())["statements"]


@pytest.mark.parametrize("want", _statements(), ids=lambda w: w["statementDate"])
def test_extract_fidelity_synthetic(run_statement, want):
    stmt = run_statement(want["file"], "--expected-parser", "fidelity_brokerage.py")
    assert stmt.institution == "Fidelity Investments"
    assert stmt.statement_date == want["statementDate"]

    got = {}
    for h in stmt.brokerage_holdings:
        key = h["symbol"]
        if h.get("position_type"):
            key += "/" + h["position_type"]
        if h.get("current_value") is not None:
            got[key] = got.get(key, 0.0) + h["current_value"]
        assert h["account"] == want["account"] and h["accountType"] == want["accountType"], key

    assert len(got) == len(want["positions"]), (got, want["positions"])
    for key, value in want["positions"].items():
        assert approx(got.get(key, 0.0), value), (key, got.get(key), value)

    bought = sold = income = flows = charges = 0.0
    for tx in stmt.brokerage_transactions:
        action = tx.get("action", "")
        if action == "Buy":
            bought += tx["amount"]
        elif action == "Sell":
            sold += tx["amount"]
        elif action in ("Dividend", "Reinvestment", "Interest"):
            income += tx["amount"]
        elif action in ("Deposit", "Withdrawal"):
            flows += tx["amount"]
        elif action in ("Fee", "Margin Interest"):
            # Read from the Account Summary's Subtractions breakdown, which
            # is the only place a statement reports either one - no Activity
            # row prints them.
            charges += tx["amount"]
        else:
            assert tx.get("transaction_type") == "corporate_action", (action, tx["description"])

    assert approx(bought, want["securitiesBought"])
    assert approx(sold, want["securitiesSold"])
    assert approx(income, want["income"])
    assert approx(charges, want.get("charges", 0.0)), (charges, want.get("charges"))
    assert approx(flows, want["netFlows"])

    assert len(stmt.transactions) == 0
    closing = sum(
        h["current_value"]
        for h in stmt.brokerage_holdings
        if h.get("is_cash_equivalent") and h.get("current_value") is not None
    )
    assert approx(closing, want["closingCoreBalance"])


def test_fidelity_merger_with_cash_payout(run_statement):
    """The March statement's merger exchanges one CUSIP for another and
    the outgoing leg also pays cash in lieu ("*EXCHANGED FOR CUSIP ... +
    $1.145* MER PAYOUT"). The payout in the Amount column is kept; the
    asterisk-wrapped annotation and its $-figure do not leak into the
    description; the space-less "#REORCM..." reference is still read."""
    if not _EXPECT.exists():
        pytest.skip("regenerate with tests/generators/gen-fidelity-synthetic-sample.py")
    stmt = run_statement(
        "fidelity-synthetic-202603.pdf", "--expected-parser", "fidelity_brokerage.py"
    )

    corp = [t for t in stmt.brokerage_transactions if t.get("transaction_type") == "corporate_action"]
    out = next(t for t in corp if t["action"] == "Merger Out")
    inc = next(t for t in corp if t["action"] == "Merger In")

    assert approx(out["amount"], 1832.00)
    assert out["description"] == "ZENITH FUSION HOLDINGS COM"
    assert "*" not in out["description"] and "$" not in out["description"]
    assert out["security_id"] == "666666FF6" and out["related_security_id"] == "777777GG7"
    assert out["reference"] == "CM0099887766000"

    assert approx(inc["amount"], 0.0)
    assert inc["security_id"] == "777777GG7" and inc["related_security_id"] == "666666FF6"
    assert inc["reference"] == "M0099887766001"


def test_fidelity_spinoff_distribution(run_statement):
    """The February statement's spin-off: a brand new symbol (ZQHH,
    spun off from the already-held ZQFF) whose only Activity row is a
    "Distribution" under Dividends/Interest/Other Income with real
    shares but NO dollar figure at all ("- -" for both price and
    amount), followed by its own "SPINOFF FROM:(ZQFF )" continuation
    line. Before fidelity_brokerage.py recognized this shape, it fell
    through to the unmatched-line branch and got silently appended onto
    the PRECEDING row's own description - this also asserts that row
    (the "Interest FULLY PAID" credit right before it) came out clean."""
    stmt = run_statement(
        "fidelity-synthetic-202602.pdf", "--expected-parser", "fidelity_brokerage.py"
    )

    spinoff = next(t for t in stmt.brokerage_transactions if t.get("symbol") == "ZQHH")
    assert spinoff["action"] == "Distribution"
    assert spinoff["transaction_type"] == "corporate_action"
    assert spinoff["subtype"] == "spinoff"
    assert approx(spinoff["quantity"], 20.0)
    assert approx(spinoff["amount"], 0.0)
    assert spinoff["security_id"] == "888888HH8"
    assert spinoff["related_security_id"] == "ZQFF"
    assert "SPINOFF" not in spinoff["description"]

    # The row printed immediately before it must not have absorbed any
    # of the spin-off's own text.
    interest = next(t for t in stmt.brokerage_transactions if t["action"] == "Interest")
    assert interest["description"] == "Interest FULLY PAID"
    assert approx(interest["amount"], 3.44)

    # The new position itself: no begin_value (brand new this month,
    # renders as "unavailable" on a real statement) and its own real
    # cost basis, which comes ONLY from this Holdings row - the Activity
    # row above carries no dollar amount to derive it from.
    holding = next(h for h in stmt.brokerage_holdings if h.get("symbol") == "ZQHH")
    assert approx(holding["quantity"], 20.0)
    assert approx(holding["cost_basis_total"], 628.30)


def test_extract_fidelity_synthetic_year_end(run_statement):
    if not _YEAR_END_EXPECT.exists():
        pytest.skip("regenerate with tests/generators/gen-fidelity-year-end-sample.py")
    want = json.loads(_YEAR_END_EXPECT.read_text())

    stmt = run_statement(want["file"], "--expected-parser", "fidelity_brokerage.py")
    assert stmt.institution == "Fidelity Investments"
    assert stmt.statement_date == want["statementDate"]
    assert len(stmt.transactions) == 0 and len(stmt.brokerage_transactions) == 0
    assert len(stmt.brokerage_holdings) == len(want["positions"])

    total = core = 0.0
    for h in stmt.brokerage_holdings:
        assert h["symbol"], h.get("description")
        assert h["account"] == want["account"] and h["accountType"] == want["accountType"]
        wanted = want["positions"][h["symbol"]]
        assert h.get("current_value") is not None and approx(h["current_value"], wanted)
        total += h["current_value"]

        want_cost = want["costBasis"].get(h["symbol"])
        if want_cost is None:
            assert h.get("cost_basis_total") is None
        else:
            assert h.get("cost_basis_total") is not None and approx(h["cost_basis_total"], want_cost)

        if h.get("is_cash_equivalent") and h.get("current_value") is not None:
            core += h["current_value"]

    assert approx(total, want["totalHoldings"])
    assert approx(core, want["coreValue"])


# Fidelity does not issue a statement per account. A household with a Roth
# gets ONE report carrying every account, each with its own Account
# Summary, Holdings and Activity sections.
#
# Getting this wrong is silent rather than loud: tag every row with a
# single account and a Roth's holdings land under the taxable brokerage
# account, or the reverse. The portfolio still adds up, and because tax
# treatment is derived from the account, an entire retirement balance can
# be reported as taxable.
_COMBINED = "fidelity-synthetic-combined-202608.pdf"

# Registration, last-4, positions and value per account, from
# gen-fidelity-synthetic-sample.py's build_combined.
_COMBINED_ACCOUNTS = {
    "3775": ("Brokerage", 1, 2_500.00),
    "6614": ("Roth IRA", 3, 65_981.00),
    "9787": ("Traditional IRA", 1, 431.00),
}


def test_combined_statement_splits_by_account(run_statement):
    stmt = run_statement(_COMBINED, "--expected-parser", "fidelity_brokerage.py")
    assert stmt.institution == "Fidelity Investments"
    assert stmt.statement_date == "2026-08-31"

    got = {}
    for h in stmt.brokerage_holdings:
        count, value = got.get(h["account"], (0, 0.0))
        got[h["account"]] = (count + 1, value + (h.get("current_value") or 0.0))

    assert set(got) == set(_COMBINED_ACCOUNTS), (sorted(got), sorted(_COMBINED_ACCOUNTS))
    for account, (kind, positions, value) in _COMBINED_ACCOUNTS.items():
        assert got[account][0] == positions, (account, got[account])
        assert approx(got[account][1], value), (account, got[account][1], value)
        types = {h["accountType"] for h in stmt.brokerage_holdings if h["account"] == account}
        assert types == {kind}, (account, types)

    # The whole report still foots to the portfolio value it prints.
    assert approx(sum(v[1] for v in got.values()),
                  sum(v[2] for v in _COMBINED_ACCOUNTS.values()))


def test_combined_statement_keeps_loaned_securities(run_statement):
    """A share out on loan is still owned and still counted in Total
    Holdings, and it prints "unknown" where a cost basis would be.

    Both halves matter: an unrecognised section loses the position, and an
    unrecognised placeholder makes the row match nothing at all. Neither
    is silent - the holdings total stops reconciling against the
    statement's own - which is how this was found on a real statement.
    """
    stmt = run_statement(_COMBINED, "--expected-parser", "fidelity_brokerage.py")
    loaned = [h for h in stmt.brokerage_holdings if h["symbol"] == "ZQLL"]
    assert len(loaned) == 1, [h["symbol"] for h in stmt.brokerage_holdings]
    assert approx(loaned[0]["current_value"], 291.00)
    assert loaned[0]["account"] == "6614"
    # "unknown" means no figure, not a figure of zero.
    assert loaned[0].get("cost_basis_total") is None, loaned[0]
