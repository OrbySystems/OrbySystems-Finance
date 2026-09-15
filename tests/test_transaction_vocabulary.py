"""Every action a bundled parser emits must be a word somebody has classified.

WHY THIS TEST EXISTS. Money entering or leaving an account is detected from
two fields - `transaction_type` when the parser sets one, `action` otherwise -
and anything that matches neither is not an error, it is *investment gain*.
A parser calling a contribution "Rollover" instead of "Deposit" makes the
account appear to have earned its own deposits, with no warning anywhere. The
parser store makes that likely by design: the whole point is that strangers
write parsers for institutions nobody here has seen.

So the closure rule, which is also what Orby's import guard applies:

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
        for row in (obj.get("tables") or {}).get("brokerage_transactions") or []:
            rows.append((path.name, row))
    return rows, seen


@pytest.fixture(scope="module")
def swept():
    rows, fixtures = _statement_rows()
    return rows, fixtures


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
