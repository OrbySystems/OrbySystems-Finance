"""A file in the parsers folder that doesn't load is named, not passed over in
silence (parser_common.unloaded_extra_parsers, CONTRACT.md
"unloadedExtraParsers").

A drop-in that fails to load - a syntax error, a relative import, no
detect()/parse() - is skipped, and a bundled parser of its name goes on
reading statements in its place. Before this, its error reached the user only
inside a "not recognized" reason: a fix that never ran, or a new parser that
never ran, looked like the statement's fault. Each read now names every such
file with a code for why, and never quotes the exception; --check-extra-parsers
answers for the whole folder; and a read that asks for one parser by name
fails at once when that one doesn't load, with the error in its message.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_unloaded_drop_ins.py)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

import parser_common
from bank_statement import _PARSERS as PDF_PARSERS
from conftest import FIXTURES, SCRIPTS

_DETECT_PARSE = '''
def detect(head_text):
    return False, "never"


def parse(pages_text, pdf_path, vision=None):
    return {}
'''

# Each way a file fails to load, and what the report says of it.
_UNLOADED = {
    "syntax": ("def detect(head_text:\n    return False, ''\n", {"code": parser_common.LOAD_SYNTAX, "line": 1}),
    "relative_import": ("import parser_common\nfrom . import common\n" + _DETECT_PARSE,
                        {"code": parser_common.LOAD_RELATIVE_IMPORT, "line": 2}),
    "missing_module": ("import pandas_that_is_not_here\n" + _DETECT_PARSE,
                       {"code": parser_common.LOAD_MISSING_MODULE, "line": 1, "module": "pandas_that_is_not_here"}),
    "bad_import": ("from institutions.common import no_such_helper\n" + _DETECT_PARSE,
                   {"code": parser_common.LOAD_IMPORT, "line": 1}),
    "dataclass": ("from __future__ import annotations\nfrom dataclasses import dataclass\n\n\n@dataclass\nclass Row:\n"
                  "    amount: float\n" + _DETECT_PARSE, {"code": parser_common.LOAD_DATACLASS, "line": 5}),
    "no_parse": ("def detect(head_text):\n    return False, ''\n", {"code": parser_common.LOAD_NO_DETECT_PARSE}),
    "raises": ("import parser_common\nraise ValueError('PRIVATE 01/15 $9,876.54')\n" + _DETECT_PARSE,
               {"code": parser_common.LOAD_ERROR, "line": 2, "error": "ValueError"}),
}


@pytest.mark.parametrize("kind", sorted(_UNLOADED))
def test_each_way_a_file_fails_to_load_is_named_with_its_code(kind, tmp_path):
    source, want = _UNLOADED[kind]
    (tmp_path / f"zz_{kind}.py").write_text(source)
    (tmp_path / "zz_loads.py").write_text(_DETECT_PARSE)
    unloaded = []
    modules, _ = parser_common.load_extra_parsers(str(tmp_path), "pdf", unloaded=unloaded)
    assert [m.__name__ for m in modules] == ["zz_loads"]
    reported = parser_common.unloaded_extra_parsers(unloaded, PDF_PARSERS)
    assert reported == [{"file": f"zz_{kind}.py", "stage": "load", **want}]
    # The exception's own text never reaches the report.
    for private in ("PRIVATE", "9,876.54", "01/15", "invalid syntax", "no known parent", "no_such_helper"):
        assert private not in json.dumps(reported)


def test_a_file_named_like_a_bundled_parser_says_which_one_reads_in_its_place(tmp_path):
    (tmp_path / "chase-credit-card.py").write_text("def detect(head_text:\n")
    unloaded = []
    parser_common.load_extra_parsers(str(tmp_path), "pdf", unloaded=unloaded)
    (entry,) = parser_common.unloaded_extra_parsers(unloaded, PDF_PARSERS)
    assert entry["replaces"] == "chase_credit_card"


# --- the dispatchers, end to end ------------------------------------------

def _dispatch(script, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          cwd=SCRIPTS, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1])


def _broken_chase(parsers):
    """The documented fix gone wrong: a copy of the bundled Chase parser
    with a line that doesn't compile."""
    source = (SCRIPTS / "institutions" / "chase_credit_card.py").read_text()
    (parsers / "chase_credit_card.py").write_text(source + "\ndef broken(:\n    pass\n")
    return source.count("\n") + 2


def test_a_broken_fix_is_named_and_the_bundled_parser_reads_in_its_place(tmp_path):
    line = _broken_chase(tmp_path)
    (tmp_path / "zz_loads.py").write_text(_DETECT_PARSE)
    code, out = _dispatch("bank_statement.py", FIXTURES / "chase-synthetic-sample.pdf", "--extra-parsers-dir", tmp_path)
    assert code == 0, out
    assert out["parser"] == {"id": "chase_credit_card", "tier": out["parser"]["tier"], "bundled": True}
    assert out["unloadedExtraParsers"] == [{"file": "chase_credit_card.py", "code": parser_common.LOAD_SYNTAX,
                                            "stage": "load", "line": line, "replaces": "chase_credit_card"}]
    assert "failedExtraParsers" not in out


def test_a_statement_nothing_reads_names_the_parser_that_did_not_load(tmp_path):
    (tmp_path / "zztest_bank.py").write_text("from . import common\n" + _DETECT_PARSE)
    code, out = _dispatch("bank_statement.py", FIXTURES / "plugin-test-sample.pdf", "--extra-parsers-dir", tmp_path)
    assert code == 0, out
    assert out["detected"] is False
    assert out["unloadedExtraParsers"] == [{"file": "zztest_bank.py", "code": parser_common.LOAD_RELATIVE_IMPORT,
                                            "stage": "load", "line": 1}]
    assert "zztest_bank.py" not in json.dumps(out["diagnostic"])


_CLAIMS_AND_FAILS = '''
def detect(head_text):
    return "ZZTEST-PLUGIN-MARKER" in head_text, "zztest marker"


def parse(pages_text, pdf_path, vision=None):
    raise ValueError("unclassified transaction row: 01/15 PRIVATE SECURITY $9,876.54")
'''


def test_a_failed_read_names_both_the_parser_that_failed_and_the_one_that_did_not_load(tmp_path):
    (tmp_path / "aaa_claims.py").write_text(_CLAIMS_AND_FAILS)
    (tmp_path / "half_done.py").write_text("def detect(head_text):\n    return False, ''\n")
    code, out = _dispatch("bank_statement.py", FIXTURES / "plugin-test-sample.pdf", "--extra-parsers-dir", tmp_path)
    assert code == 1, out
    assert [f["file"] for f in out["failedExtraParsers"]] == ["aaa_claims.py"]
    assert out["unloadedExtraParsers"] == [{"file": "half_done.py", "code": parser_common.LOAD_NO_DETECT_PARSE,
                                            "stage": "load"}]


@pytest.mark.parametrize("flag", ["--expected-parser", "--only-extra-parser"])
def test_the_parser_asked_for_fails_at_once_when_it_does_not_load(flag, tmp_path):
    line = _broken_chase(tmp_path)
    code, out = _dispatch("bank_statement.py", FIXTURES / "chase-synthetic-sample.pdf",
                          "--extra-parsers-dir", tmp_path, flag, "chase_credit_card.py")
    assert code == 1, out
    # The message is for whoever is building or trying the file: the error itself.
    assert "chase_credit_card.py doesn't load" in out["error"] and f"line {line}" in out["error"]
    # The diagnostic may be reported: no file name, no exception text.
    assert out["diagnostic"]["code"] == parser_common.LOAD_SYNTAX
    assert out["diagnostic"]["stage"] == "load" and out["diagnostic"]["parserId"] == "external_parser"
    for private in ("chase_credit_card", "invalid syntax", "never closed", f"line {line}"):
        assert private not in json.dumps(out["diagnostic"])
    assert out["unloadedExtraParsers"][0]["file"] == "chase_credit_card.py"


def test_the_csv_dispatcher_names_them_too(tmp_path):
    export = tmp_path / "export.csv"
    export.write_text("Zztest Date,Zztest Description,Zztest Amount\n2026-01-01,Coffee,-4.50\n")
    parsers = tmp_path / "parsers"
    parsers.mkdir()
    (parsers / "zztest_csv.py").write_text("from . import common\n\ndef detect(header, sample_rows):\n    return True, ''\n")
    code, out = _dispatch("csv_statement.py", export, "--extra-parsers-dir", parsers)
    assert code == 0, out
    assert out["unloadedExtraParsers"] == [{"file": "zztest_csv.py", "code": parser_common.LOAD_RELATIVE_IMPORT,
                                            "stage": "load", "line": 1}]


def test_check_extra_parsers_answers_for_the_whole_folder_and_reads_nothing(tmp_path):
    _broken_chase(tmp_path)
    (tmp_path / "zz_loads.py").write_text(_DETECT_PARSE)
    # Named like a bundled CSV parser: the one check covers both dispatchers.
    csv_name = sorted(p.name for p in (SCRIPTS / "csv_institutions").glob("[a-z]*.py"))[0]
    (tmp_path / csv_name).write_text("from . import common\n")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "bank_statement.py"), "--check-extra-parsers",
                           "--extra-parsers-dir", str(tmp_path)], cwd=SCRIPTS, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert set(out) == {"unloadedExtraParsers"}
    by_file = {e["file"]: e for e in out["unloadedExtraParsers"]}
    assert set(by_file) == {"chase_credit_card.py", csv_name}
    assert by_file["chase_credit_card.py"]["replaces"] == "chase_credit_card"
    assert by_file[csv_name]["replaces"] == csv_name[:-3]
    assert by_file[csv_name]["code"] == parser_common.LOAD_RELATIVE_IMPORT


def test_a_clean_folder_reports_nothing(tmp_path):
    shutil.copy(SCRIPTS / "institutions" / "chase_credit_card.py", tmp_path / "chase_credit_card.py")
    code, out = _dispatch("bank_statement.py", FIXTURES / "chase-synthetic-sample.pdf", "--extra-parsers-dir", tmp_path)
    assert code == 0, out
    assert "unloadedExtraParsers" not in out
    assert out["parser"]["bundled"] is False
