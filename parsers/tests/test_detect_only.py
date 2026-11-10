"""--detect-only (orby-core platform/finance/ingest.ClassifyStatements):
both dispatchers stop the instant detect() picks a module - or fails to -
reporting that module's own static kind straight from its KIND attribute,
without ever calling parse(). Classification needs nothing past this: it's
how a folder of statements is sorted into the project of their kind without
paying a full parse's cost for files nothing is about to import.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_detect_only.py)
"""

from __future__ import annotations

from conftest import _fixture_path, _run


def test_bank_dispatcher_detects_without_parsing():
    path = _fixture_path("wells-fargo-synthetic-sample.pdf")
    if not path.exists():
        import pytest

        pytest.skip("fixture not present locally")
    out = _run("bank_statement.py", path, ["--detect-only"])
    assert out["detected"] is True
    assert out["kind"] == "bank"
    assert out["parserId"]
    assert out["bundled"] is True
    # Nothing a real parse would add - this is the whole point.
    assert "tables" not in out and "institution" not in out and "checkResults" not in out


def test_csv_dispatcher_detects_without_parsing():
    path = _fixture_path("amazon-order-history-synthetic-sample.csv")
    if not path.exists():
        import pytest

        pytest.skip("fixture not present locally")
    out = _run("csv_statement.py", path, ["--detect-only"])
    assert out["detected"] is True
    assert out["kind"] == "retail"
    assert out["parserId"]
    assert out["bundled"] is True
    assert "tables" not in out and "institution" not in out


def test_no_match_is_unaffected_by_detect_only():
    # A real PDF no bundled parser's detect() claims: --detect-only and a
    # normal read agree on "not detected", with the same diagnostic - the
    # no-match path already returned before parse() runs, detect-only or
    # not (bank_statement.py's "if module is None:" branch).
    path = _fixture_path("wells-fargo-synthetic-sample.pdf")
    if not path.exists():
        import pytest

        pytest.skip("fixture not present locally")
    detect_only = _run("bank_statement.py", path, ["--detect-only", "--kind", "retail"])
    assert detect_only["detected"] is False
    plain = _run("bank_statement.py", path, ["--kind", "retail"])
    assert plain["detected"] is False
    assert detect_only["diagnostic"]["code"] == plain["diagnostic"]["code"]
