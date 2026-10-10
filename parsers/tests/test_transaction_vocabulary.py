"""Every action a bundled parser emits must be a word somebody has classified.

WHY THIS TEST EXISTS. Money entering or leaving an account is detected from
two fields - `transaction_type` when the parser sets one, `action` otherwise -
and anything that matches neither is not an error, it is *investment gain*.
A parser calling a contribution "Rollover" instead of "Deposit" makes the
account appear to have earned its own deposits, with no warning anywhere. The
parser store makes that likely by design: the whole point is that strangers
write parsers for institutions nobody here has seen.

So the closure rule, which is also what OrbySystems' import guard applies:

  * a row that sets `transaction_type` is classified. Its `action` is free
    prose and is not checked - a corporate action's label is lifted verbatim
    out of the statement ("Merger Out", "Assigned Out"), so checking it would
    be wrong.
  * a row that sets no `transaction_type` is classified by `action` alone, so
    that action must appear in scripts/transaction_vocabulary.json.

A new parser that invents a name therefore fails here, in CI, rather than in
somebody's answer. The fix is one line of JSON - in flows[].actions if the
word means money moved, in non_flow_actions if it does not - or, better, set
`transaction_type` on the row and the question does not arise.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(SCRIPTS))
import parser_common  # noqa: E402

# Below this many rows the sweep is not exercising anything and a green run
# would be meaningless. Several fixtures are real redacted statements that are
# gitignored (see .gitignore), so the count has to be satisfiable from the
# COMMITTED synthetic fixtures alone - otherwise this fails on a fresh clone
# and passes only on the machine that has the private ones, which is the
# failure mode this number exists to prevent.
_MIN_ROWS = 40


#: Warnings the fixtures' parsers drew in backwards-compatible mode (the
#: importer's default), by fixture: a bundled parser must draw none.
_RULE_WARNINGS: dict[str, list[str]] = {}


def _statement_rows() -> tuple[list[tuple[str, dict]], int]:
    """Every brokerage_transactions row from every fixture present, tagged
    with the fixture that produced it, plus the fixture count."""
    rows: list[tuple[str, dict]] = []
    seen = 0
    for path in sorted(FIXTURES.iterdir()):
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".csv", ".xlsx"}:
            continue
        script = "csv_statement.py" if suffix in {".csv", ".xlsx"} else "bank_statement.py"
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / script), str(path)],
            cwd=SCRIPTS, capture_output=True, text=True,
        )
        out = proc.stdout.strip()
        if not out:
            continue  # unreadable or unrecognized; other tests cover that
        try:
            obj = json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            continue
        if "error" in obj or not obj.get("detected"):
            continue
        seen += 1
        if obj.get("warnings"):
            _RULE_WARNINGS[path.name] = obj["warnings"]
        for row in (obj.get("tables") or {}).get("brokerage_transactions") or []:
            rows.append((path.name, row))
    return rows, seen


@pytest.fixture(scope="module")
def swept():
    rows, fixtures = _statement_rows()
    return rows, fixtures


@pytest.fixture
def strict():
    """Strict mode (backwards compatibility off) for a test that calls the
    validator directly, as the dispatchers' --strict flag does."""
    parser_common.set_strict(True)
    yield
    parser_common.set_strict(False)


def test_bundled_parsers_break_no_contract_rule(swept):
    """Read the importer's way (backwards compatible), no bundled parser
    draws a contract warning; the parser tests run strict and would fail it."""
    assert not _RULE_WARNINGS, _RULE_WARNINGS


def test_sweep_is_not_vacuous(swept):
    """A pass with no rows behind it is the one outcome worse than a failure."""
    rows, fixtures = swept
    assert fixtures > 0, "no fixture was recognized by any dispatcher"
    assert len(rows) >= _MIN_ROWS, (
        f"only {len(rows)} brokerage rows from {fixtures} fixtures - under the "
        f"{_MIN_ROWS} this check needs to mean anything. Committed synthetic "
        f"fixtures are missing, so the vocabulary is not actually being tested."
    )


def test_every_unclassified_action_is_in_the_vocabulary(swept):
    rows, _ = swept
    offenders: dict[str, set[str]] = {}
    for fixture, row in rows:
        word = parser_common.unclassified_action(row)
        if word:
            offenders.setdefault(word, set()).add(fixture)
    if offenders:
        lines = [
            f"  {word!r}  (from {', '.join(sorted(fixtures))})"
            for word, fixtures in sorted(offenders.items())
        ]
        pytest.fail(
            "action values that no classification explains:\n"
            + "\n".join(lines)
            + "\n\nEach row carries no transaction_type, so its action is all "
            "there is to go on, and an unknown action counts as investment "
            "gain rather than as money moving. Fix either by setting "
            "transaction_type on the row (preferred - see "
            "scripts/transaction_vocabulary.json) or by adding the word to "
            "flows[].actions / non_flow_actions in that file."
        )


def test_flow_rows_are_actually_detected_as_flow(swept):
    """The rows we call deposits and withdrawals must classify as flow.

    Guards the other direction: the vocabulary could list a word and the
    classifier still miss it if the two ever drift apart.
    """
    rows, _ = swept
    for fixture, row in rows:
        action = (row.get("action") or "").strip()
        if action in parser_common.FLOW_ACTIONS:
            assert parser_common.classifies_as_flow(row), (
                f"{fixture}: action {action!r} is a flow word but the row does "
                f"not classify as flow: {row!r}"
            )


def test_vocabulary_lists_do_not_overlap():
    """A word cannot mean both 'money moved' and 'money did not move'."""
    both = parser_common.FLOW_ACTIONS & parser_common.NON_FLOW_ACTIONS
    assert not both, f"actions in both flow and non-flow lists: {sorted(both)}"


def test_flow_transaction_types_are_in_the_closed_vocabulary():
    unknown = parser_common.FLOW_TRANSACTION_TYPES - parser_common.TRANSACTION_TYPES
    assert not unknown, (
        f"flows[] name transaction_type values missing from transaction_types: "
        f"{sorted(unknown)}"
    )


def test_every_flow_entry_is_well_formed():
    for entry in parser_common.VOCABULARY["flows"]:
        assert entry["direction"] in {"in", "out", "sign"}, entry
        assert isinstance(entry["external"], bool), entry
        assert entry["actions"], f"{entry['transaction_type']} lists no actions"


# --- What a row MEANS, beyond money movement -------------------------------
#
# OrbySystems resolves every row to one transaction_type value before any
# income, tax-lot, option or performance figure reads it (pkg/ingest/flow.go's
# classExpr, exposed as v_scoped_transactions.transaction_class). Those figures
# used to match action words instead - 'Dividend', 'Interest', 'Fee', 'Buy',
# 'Sell', 'Reinvestment', 'Expired Out', 'Assigned Out' - so a parser that
# followed this contract, setting transaction_type and passing the issuer's
# own word through as action ('Qualified Dividend', 'Reinvest', 'Advisory
# Fee'), had those rows silently left out of every one of them.


def test_non_flow_classes_are_well_formed():
    seen: dict[str, str] = {}
    for entry in parser_common.VOCABULARY["non_flow_classes"]:
        ttype = entry["transaction_type"]
        assert ttype in parser_common.TRANSACTION_TYPES, entry
        assert entry["actions"], f"{ttype} lists no actions"
        for action in entry["actions"]:
            assert action in parser_common.NON_FLOW_ACTIONS, (
                f"{action!r} is classed as {ttype} but is not in non_flow_actions, "
                f"so the import guard and CI would still call it unknown"
            )
            assert action not in parser_common.FLOW_ACTIONS, (
                f"{action!r} is both a flow word and classed as {ttype}"
            )
            assert action not in seen, f"{action!r} is classed as both {seen[action]} and {ttype}"
            seen[action] = ttype


def test_corporate_action_events_are_well_formed():
    seen: dict[str, str] = {}
    for entry in parser_common.VOCABULARY["corporate_action_events"]:
        assert entry["words"], f"{entry['event']} lists no words"
        for word in entry["words"]:
            assert word.isalpha() and word.islower(), (
                f"{word!r}: event words are matched against lower-cased whole words, "
                f"so they must be lower-case letters"
            )
            assert word not in seen, f"{word!r} names both {seen[word]} and {entry['event']}"
            seen[word] = entry["event"]


def test_transaction_class_prefers_transaction_type_then_action():
    tc = parser_common.transaction_class
    assert tc({"transaction_type": "dividend", "action": "Qualified Dividend"}) == "dividend"
    assert tc({"transaction_type": "buy", "action": "Reinvest"}) == "buy"
    assert tc({"transaction_type": "fee", "action": "Advisory Fee"}) == "fee"
    assert tc({"action": "Dividend"}) == "dividend"
    assert tc({"action": "Reinvestment"}) == "buy"
    assert tc({"action": "Deposit"}) == "deposit"
    # A charge, not income.
    assert tc({"action": "Margin Interest"}) == "fee"
    # A transaction_type outside the vocabulary is no classification at all.
    assert tc({"transaction_type": "Dividend", "action": "Dividend"}) == "dividend"
    assert tc({"action": "Something Else"}) == ""


def test_corporate_event_reads_the_label_of_a_corporate_action():
    ce = parser_common.corporate_event
    assert ce({"transaction_type": "corporate_action", "action": "Expired Out"}) == "expired"
    assert ce({"transaction_type": "corporate_action", "action": "Option Expiration"}) == "expired"
    assert ce({"transaction_type": "corporate_action", "action": "Assigned Out"}) == "assigned"
    assert ce({"action": "ASSIGNMENT"}) == "assigned"
    assert ce({"transaction_type": "corporate_action", "action": "Merger Out"}) == ""
    # A trade is never an expiry, whatever its label says.
    assert ce({"transaction_type": "sell", "action": "Assigned Out"}) == ""


def test_looks_like_option_contract():
    looks = parser_common.looks_like_option_contract
    assert looks({"description": "You Sold CALL (AVGO) BROADCOM INC COM SEP 18 26 $420 (100 SHS)"})
    assert looks({"description": "PUT AAPL 01/16/2026 150.00"})
    assert looks({"description": "AAPL 16JAN26 150 C CALL"})
    # A covered-call fund is a fund, and an assignment's stock leg is stock.
    assert not looks({"description": "Dividend Received GLOBAL X NASDAQ 100 COVERED CALL ETF"})
    assert not looks({"description": "You Sold BROADCOM INC COM ASSIGNED CALLS"})


def test_every_bundled_row_resolves_to_a_class(swept):
    """A row that resolves to no class is in no income, tax-lot, option or
    performance figure. Set transaction_type, or class the word in
    non_flow_classes."""
    rows, _ = swept
    offenders: dict[tuple[str, str], set[str]] = {}
    for fixture, row in rows:
        if not parser_common.transaction_class(row):
            key = (row.get("action") or "", row.get("transaction_type") or "")
            offenders.setdefault(key, set()).add(fixture)
    assert not offenders, "rows that resolve to no transaction class:\n" + "\n".join(
        f"  action={a!r} transaction_type={t!r}  (from {', '.join(sorted(f))})"
        for (a, t), f in sorted(offenders.items()))


def test_option_contract_rows_carry_an_occ_symbol(swept):
    """OrbySystems recognises an option by its symbol's OCC shape alone; a
    contract row carrying a CUSIP or a bare ticker is in no option figure."""
    rows, _ = swept
    bad = [(fixture, row.get("symbol"), row.get("description"))
           for fixture, row in rows
           if parser_common.looks_like_option_contract(row)
           and not parser_common.OCC_SYMBOL.match(row.get("symbol") or "")]
    assert not bad, "option contract rows without an OCC symbol:\n" + "\n".join(
        f"  {f}: symbol={s!r} description={d!r}" for f, s, d in bad)


# --- corporate_event: the parser says what a corporate action IS ----------


def test_every_corporate_action_sets_a_valid_corporate_event(swept):
    """The Go side reads corporate_event and never the issuer's word, so a
    bundled parser that leaves it out has its corporate actions derived from
    text - which is exactly what the field exists to avoid."""
    rows, _ = swept
    missing: dict[str, set[str]] = {}
    for fixture, row in rows:
        if row.get("transaction_type") != "corporate_action":
            continue
        event = row.get("corporate_event")
        assert event in parser_common.CORPORATE_EVENTS, (
            f"{fixture}: corporate action {row.get('action')!r} has corporate_event {event!r}"
        )
        if not event:
            missing.setdefault(fixture, set()).add(row.get("action", ""))
    assert not missing, f"corporate actions with no corporate_event: {missing}"


def test_directional_rows_say_which_way_in_subtype(swept):
    """Every transfer_in / transfer_out / internal_transfer / corporate_action
    row states its direction in subtype, "In" or "Out"."""
    rows, _ = swept
    missing = sorted({
        (fixture, row.get("transaction_type"), row.get("action"), row.get("subtype"))
        for fixture, row in rows
        if row.get("transaction_type") in parser_common.DIRECTIONAL_TYPES
        and row.get("subtype") not in ("In", "Out")
    })
    assert not missing, f"directional rows with no In/Out subtype: {missing}"


def test_quantity_is_never_signed(swept):
    rows, _ = swept
    signed = sorted({
        (fixture, row.get("transaction_type"), row.get("action"), row["quantity"])
        for fixture, row in rows
        if isinstance(row.get("quantity"), (int, float)) and row["quantity"] < 0
    })
    assert not signed, f"negative quantity (direction belongs in subtype): {signed}"


def test_set_directions_fills_and_unsigns():
    rows = [
        {"transaction_type": "transfer_out", "amount": -5.0, "quantity": -3.0},
        {"transaction_type": "internal_transfer", "amount": 0.0, "quantity": 4.0, "subtype": "transfer"},
        {"transaction_type": "internal_transfer", "amount": -9.0, "quantity": 9.0},
        {"transaction_type": "corporate_action", "corporate_event": "merger_out", "amount": 0.0, "quantity": -7.0},
        {"transaction_type": "corporate_action", "corporate_event": "reverse_split", "amount": 0.0, "quantity": -2.0},
        {"transaction_type": "corporate_action", "corporate_event": "other", "amount": 0.0, "quantity": 2.0, "subtype": "Out"},
        {"transaction_type": "sell", "amount": 10.0, "quantity": -1.0},
    ]
    parser_common.set_directions(rows)
    assert [r.get("subtype") for r in rows] == ["Out", "In", "Out", "Out", "Out", "Out", None]
    assert all(r["quantity"] >= 0 for r in rows)


def test_parse_rejects_contradictory_directions(strict):
    def result(**row):
        base = {"date": "2026-01-02", "description": "d", "amount": 0.0, "account": "1234", "accountType": "Brokerage"}
        return {"institution": "X", "statementDate": "", "tables": {"brokerage_transactions": [{**base, **row}]}}
    ok = parser_common.validate_multi_table_parse_result
    ok(result(transaction_type="transfer_in", subtype="In", amount=5.0), "m")
    ok(result(transaction_type="internal_transfer", subtype="Out", amount=-5.0), "m")
    with pytest.raises(ValueError, match="always 'In'"):
        ok(result(transaction_type="transfer_in", subtype="Out"), "m")
    with pytest.raises(ValueError, match="cash moving in is positive"):
        ok(result(transaction_type="internal_transfer", subtype="Out", amount=5.0), "m")


def test_corporate_event_directions_are_well_formed():
    directions = parser_common.CORPORATE_EVENT_DIRECTIONS
    assert set(directions) <= parser_common.CORPORATE_EVENTS
    assert set(directions.values()) <= {"In", "Out"}
    for event in parser_common.CORPORATE_EVENTS:
        if event.endswith("_in") or event.endswith("_out"):
            assert directions[event] == ("In" if event.endswith("_in") else "Out"), event


def test_parse_rejects_a_subtype_that_contradicts_the_event(strict):
    def result(event, subtype):
        return {"institution": "X", "statementDate": "", "tables": {"brokerage_transactions": [{
            "date": "2026-01-02", "description": "d", "amount": 0.0, "account": "1234",
            "accountType": "Brokerage", "transaction_type": "corporate_action",
            "corporate_event": event, "subtype": subtype, "quantity": 1.0}]}}
    parser_common.validate_multi_table_parse_result(result("merger_in", "In"), "m")
    parser_common.validate_multi_table_parse_result(result("split", "Out"), "m")  # no fixed direction
    with pytest.raises(ValueError, match="direction goes in subtype"):  # strict: In or Out is required
        parser_common.validate_multi_table_parse_result(result("merger_in", "other"), "m")
    with pytest.raises(ValueError, match="always 'In'"):
        parser_common.validate_multi_table_parse_result(result("merger_in", "Out"), "m")
    with pytest.raises(ValueError, match="always 'Out'"):
        parser_common.validate_multi_table_parse_result(result("expired", "In"), "m")


def test_corporate_events_are_well_formed():
    events = parser_common.VOCABULARY["corporate_events"]
    assert len(events) == len(set(events))
    assert "other" in events and "share_distribution" in events
    for entry in parser_common.VOCABULARY["corporate_event_labels"]:
        assert entry["event"] in parser_common._DIRECTED_EVENTS or entry["event"] in events
        assert entry["words"]
        for word in entry["words"]:
            assert word.isalpha() and word.islower(), word


def test_label_event_reads_stated_events_only():
    le = parser_common.label_event
    assert le("Stock Split") == "split"
    assert le("Reverse Stock Split") == "reverse_split"
    assert le("Option Expiration") == "expired"
    assert le("Assigned Out") == "assigned"
    assert le("Merger In", "In") == "merger_in"
    assert le("Merger Out", "Out") == "merger_out"
    assert le("Merger") == ""  # no direction, no guess
    assert le("Spin-off") == "spinoff"
    assert le("Conversion", "Out") == "conversion_out"
    assert le("In Lieu Of Frx Share") == "cash_in_lieu"
    # A bare distribution states nothing: the parser decides, never this.
    assert le("Distribution") == ""
    assert le("Stock Plan Activity") == ""


def test_parse_rejects_an_unknown_corporate_event(strict):
    row = {"date": "2026-01-02", "description": "x", "amount": 0.0, "account": "1", "accountType": "Brokerage",
           "transaction_type": "corporate_action", "corporate_event": "stock_split_ish"}
    with pytest.raises(ValueError, match="corporate_event"):
        parser_common.validate_multi_table_parse_result(
            {"institution": "X", "statementDate": "2026-01-31", "tables": {"brokerage_transactions": [row]}}, "t")
    row["corporate_event"] = "split"
    row["transaction_type"] = "buy"
    with pytest.raises(ValueError, match="only a corporate_action row"):
        parser_common.validate_multi_table_parse_result(
            {"institution": "X", "statementDate": "2026-01-31", "tables": {"brokerage_transactions": [row]}}, "t")


# --- NOT_APPLICABLE: a parser says what its format cannot contain ----------


def test_expand_not_applicable():
    terms, errors = parser_common.expand_not_applicable({
        "option:*": "no options",
        "corporate_event:split": "no splits",
        "transaction_type:nonsense": "x",
        "option:call": "",
    })
    assert not any(t.startswith("transaction_type") for t in terms)
    assert terms["option:call"] == "no options"  # the blank reason on option:call is dropped, * stays
    assert set(f"option:{k}" for k in parser_common.OPTION_KINDS) <= set(terms)
    assert terms["corporate_event:split"] == "no splits"
    assert len(errors) == 2


def test_every_bundled_not_applicable_declaration_is_valid():
    import importlib, pkgutil
    import csv_institutions, institutions
    for pkg in (institutions, csv_institutions):
        for info in pkgutil.iter_modules(pkg.__path__):
            module = importlib.import_module(f"{pkg.__name__}.{info.name}")
            _, errors = parser_common.expand_not_applicable(getattr(module, "NOT_APPLICABLE", {}))
            assert not errors, f"{module.__name__}: {errors}"


def _brokerage_result(*rows):
    base = {"date": "2026-01-02", "description": "d", "amount": 0.0, "account": "1234", "accountType": "Brokerage"}
    return {"institution": "X", "statementDate": "", "tables": {"brokerage_transactions": [{**base, **r} for r in rows]}}


def test_strict_rejects_what_backwards_compatible_mode_only_warns_about():
    old_style = _brokerage_result(
        {"transaction_type": "corporate_action", "quantity": -5.0},
        {"transaction_type": "internal_transfer", "amount": -9.0, "quantity": -1.0},
        {"transaction_type": "corporate_action", "corporate_event": "bogus", "subtype": "In", "quantity": 1.0},
        {"transaction_type": "sell", "corporate_event": "split", "amount": 5.0, "quantity": 1.0},
    )
    try:
        parser_common.set_strict(True)
        with pytest.raises(ValueError):
            parser_common.validate_multi_table_parse_result(old_style, "old_parser")

        parser_common.set_strict(False)
        parser_common.validate_multi_table_parse_result(old_style, "old_parser")  # accepted
        warnings = parser_common.take_rule_warnings()
        joined = "\n".join(warnings)
        for fragment in ("no corporate_event", "subtype None", "quantity -5.0", "not in the vocabulary", "only a corporate_action row"):
            assert fragment in joined, (fragment, warnings)
        assert "older parsers keep working" in joined
        # A value that must not reach the importer is dropped, not passed on.
        rows = old_style["tables"]["brokerage_transactions"]
        assert "corporate_event" not in rows[2] and "corporate_event" not in rows[3]
        # Taking the warnings forgets them.
        assert parser_common.take_rule_warnings() == []
    finally:
        parser_common.set_strict(False)


def test_backwards_compatible_warnings_count_rows_once_per_rule():
    try:
        parser_common.set_strict(False)
        parser_common.validate_multi_table_parse_result(
            _brokerage_result(*[{"transaction_type": "sell", "quantity": -1.0, "amount": 1.0}] * 3), "old_parser")
        (warning,) = parser_common.take_rule_warnings()
        assert warning.startswith("old_parser.parse(): tables['brokerage_transactions'][0]")
        assert "(and 2 more rows)" in warning
    finally:
        parser_common.set_strict(False)
