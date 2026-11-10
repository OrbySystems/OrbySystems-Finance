"""--use-parser (orby-core platform/finance/ingest.ClassifyStatements's
cache, read back by a real import): names the parser a prior classify of
this exact file content already found, so detect() finds it on its first
try - but still runs, in a list with just that one parser moved to the
front (parser_common.prioritize_parser), so the result is identical to a
plain call either way; it's a performance hint, never an assertion.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_use_parser.py)
"""

from __future__ import annotations

from types import SimpleNamespace

import parser_common
from conftest import _fixture_path, _run


def _module(name: str) -> SimpleNamespace:
    return SimpleNamespace(__name__=name)


def test_prioritize_parser_moves_a_dotted_py_filename_to_the_front():
    # The dispatcher's own --use-parser value is a filename
    # ("wells_fargo_checking.py"), while a module's __name__ carries no
    # extension ("institutions.wells_fargo_checking") - parser_name_key
    # alone mishandles the ".py" (it would strip to "py", not the parser's
    # name), so this exercises the same explicit strip
    # check_expected_parser already does.
    a, b, c = _module("institutions.chase_checking"), _module("institutions.wells_fargo_checking"), _module("institutions.bofa_checking")
    out = parser_common.prioritize_parser([a, b, c], "wells_fargo_checking.py")
    assert out == [b, a, c]


def test_prioritize_parser_leaves_order_unchanged_when_name_is_unknown():
    a, b = _module("institutions.chase_checking"), _module("institutions.bofa_checking")
    assert parser_common.prioritize_parser([a, b], "no_such_parser.py") == [a, b]
    assert parser_common.prioritize_parser([a, b], None) == [a, b]
    assert parser_common.prioritize_parser([a, b], "") == [a, b]


def test_use_parser_reaches_the_same_result_as_a_plain_read():
    path = _fixture_path("wells-fargo-synthetic-sample.pdf")
    if not path.exists():
        import pytest

        pytest.skip("fixture not present locally")
    plain = _run("bank_statement.py", path, [])
    named = _run("bank_statement.py", path, ["--use-parser", "wells_fargo_checking.py"])
    assert named["detected"] is True
    assert named["parser"]["id"] == plain["parser"]["id"] == "wells_fargo_checking"
    assert named["tables"] == plain["tables"]


def test_a_stale_or_unknown_name_falls_back_to_the_full_list():
    # Exactly as if --use-parser were never given: the rest of the list is
    # tried in its usual order, which still finds the real match.
    path = _fixture_path("wells-fargo-synthetic-sample.pdf")
    if not path.exists():
        import pytest

        pytest.skip("fixture not present locally")
    out = _run("bank_statement.py", path, ["--use-parser", "no_such_parser.py"])
    assert out["detected"] is True
    assert out["parser"]["id"] == "wells_fargo_checking"


def test_use_parser_works_with_detect_only_too():
    path = _fixture_path("wells-fargo-synthetic-sample.pdf")
    if not path.exists():
        import pytest

        pytest.skip("fixture not present locally")
    out = _run("bank_statement.py", path, ["--detect-only", "--use-parser", "wells_fargo_checking.py"])
    assert out["detected"] is True
    assert out["parserId"] == "wells_fargo_checking"
