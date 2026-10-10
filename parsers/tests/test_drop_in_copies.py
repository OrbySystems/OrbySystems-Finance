"""Every bundled parser can be fixed the documented way: copied into the
user's parsers folder and edited there (CLAUDE.md, "Fixing a bundled parser
without a release").

There the copy is loaded on its own, outside the institutions package
(parser_common.load_extra_parsers). A relative import (`from . import
common`) has no package to resolve against, so the copy fails to load and is
skipped - and the bundled parser goes on reading the statement in its place,
so the edit silently never applies. Bundled modules import what they share
absolutely (`from institutions import common`), which resolves both ways.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_drop_in_copies.py)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import parser_common
from bank_statement import _PARSERS as PDF_PARSERS
from conftest import FIXTURES, SCRIPTS
from csv_statement import _PARSERS as CSV_PARSERS

_BUNDLED = [(m, "pdf", PDF_PARSERS) for m in PDF_PARSERS] + [(m, "csv", CSV_PARSERS) for m in CSV_PARSERS]


@pytest.mark.parametrize(
    "module, tag, bundled", _BUNDLED, ids=[m.__name__.rsplit(".", 1)[-1] for m, _, _ in _BUNDLED]
)
def test_a_copy_of_the_bundled_parser_loads_from_the_parsers_folder(module, tag, bundled, tmp_path):
    source = Path(module.__file__)
    shutil.copy(source, tmp_path / source.name)
    copies, misses = parser_common.load_extra_parsers(str(tmp_path), tag)
    assert misses == []
    (copy,) = copies
    assert not parser_common.is_bundled(copy)
    # It takes the bundled parser's own place in the try order.
    merged = parser_common.merge_parsers(bundled, [copy])
    assert len(merged) == len(bundled)
    assert merged.index(copy) == bundled.index(module)


# Appended to the copy: a user's edit, as small as one can be.
_EDIT = '''

_bundled_parse = parse


def parse(*args, **kwargs):
    result = _bundled_parse(*args, **kwargs)
    result["institution"] = "Edited Copy Bank"
    return result
'''


def test_an_edited_copy_reads_the_statement_in_the_bundled_parsers_place(tmp_path):
    """The whole workflow, through the dispatcher, with a parser that
    imports common: the edited copy, not the bundled parser, reads the
    statement."""
    copy = tmp_path / "chase_credit_card.py"
    shutil.copy(SCRIPTS / "institutions" / "chase_credit_card.py", copy)
    with open(copy, "a", encoding="utf-8") as f:
        f.write(_EDIT)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "bank_statement.py"), str(FIXTURES / "chase-synthetic-sample.pdf"),
         "--extra-parsers-dir", str(tmp_path)],
        cwd=SCRIPTS, capture_output=True, text=True,
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert proc.returncode == 0, out
    assert out["parser"]["id"] == "chase_credit_card"
    assert out["parser"]["bundled"] is False, "the bundled parser read it: the copy did not load"
    assert out["institution"] == "Edited Copy Bank"
    assert out["tables"]["cash_transactions"]
