"""A dropped-in parser that claims a statement and fails is passed over
(parser_common.read_claimed): the statement is read as if that file weren't
installed, and the dispatcher names it under "failedExtraParsers", outside
the diagnostic. A bundled parser that fails still ends the read, and a
dispatcher asked for one parser (--expected-parser) passes nothing over.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_drop_in_fallthrough.py)
"""

from __future__ import annotations

import json
import subprocess
import sys

import parser_common
from conftest import FIXTURES, SCRIPTS


class _Fake:
    """A parser module: claims when told to, then reads or raises."""

    def __init__(self, name, claims=True, reads=True):
        self.__name__ = name
        self.claims, self.reads = claims, reads

    def detect(self, *_):
        return self.claims, "claims" if self.claims else "doesn't claim"

    def parse(self, *_):
        if not self.reads:
            raise ValueError("unclassified transaction row: 01/15 PRIVATE SECURITY $9,876.54")
        return {"read by": self.__name__}


def _read(parsers, bundled=(), fall_through=True):
    first, _ = parser_common.detect(lambda m: m.detect(), parsers)
    return parser_common.read_claimed(first, lambda m: m.parse(), lambda m: m.detect(), list(parsers), list(bundled), fall_through)


def _names(failed):
    return [m.__name__ for m, _ in failed]


def test_a_failing_drop_in_is_passed_over_for_the_next_that_claims_it():
    broken, reads = _Fake("aaa-broken-banking-pdf", reads=False), _Fake("citi-costco")
    read = _read([_Fake("institutions.bofa_checking", claims=False), broken, _Fake("bbb-other", claims=False), reads])
    assert read.module is reads and read.result == {"read by": "citi-costco"} and read.error is None
    assert _names(read.failed) == ["aaa-broken-banking-pdf"]


def test_a_failing_override_gives_the_bundled_parser_back_its_slot():
    bundled = [_Fake("institutions.bofa_checking_combined"), _Fake("institutions.bofa_checking"), _Fake("institutions.chase")]
    override = _Fake("bofa_checking_combined", reads=False)
    parsers = parser_common.merge_parsers(bundled, [override])
    assert parsers[0] is override
    read = _read(parsers, bundled)
    assert read.module is bundled[0], "not read by the bundled parser the override replaced"
    assert _names(read.failed) == ["bofa_checking_combined"]


def test_without_the_drop_in_the_dispatch_goes_on_as_before():
    # The bundled parser the override replaced doesn't claim this one, so the
    # next that does reads it - as it would with no override installed.
    bundled = [_Fake("institutions.bofa_checking_combined", claims=False), _Fake("institutions.bofa_checking")]
    override = _Fake("bofa_checking_combined", reads=False)
    read = _read(parser_common.merge_parsers(bundled, [override]), bundled)
    assert read.module is bundled[1]


def test_a_failing_bundled_parser_ends_the_read():
    # bofa_checking's detect() also claims a combined statement: falling
    # past bofa_checking_combined would read every account as one.
    combined, single = _Fake("institutions.bofa_checking_combined", reads=False), _Fake("institutions.bofa_checking")
    read = _read([combined, single, _Fake("my-own-bofa-parser")], [combined, single])
    assert read.module is combined and read.result is None
    assert isinstance(read.error, ValueError)
    assert read.failed == []

    # Also when the drop-in before it failed: the bundled failure is the one
    # that ends it, and the drop-in is named beside it.
    override = _Fake("bofa_checking_combined", reads=False)
    read = _read(parser_common.merge_parsers([combined, single], [override]), [combined, single])
    assert read.module is combined and read.error is not None
    assert _names(read.failed) == ["bofa_checking_combined"]


def test_when_nothing_else_claims_it_the_read_ends_on_the_drop_in():
    first, second = _Fake("aaa-broken", reads=False), _Fake("bbb-broken", reads=False)
    read = _read([_Fake("institutions.chase", claims=False), first, second])
    assert read.module is second and read.error is not None and read.result is None
    assert _names(read.failed) == ["aaa-broken", "bbb-broken"]


def test_no_fall_through_when_one_parser_is_asked_for():
    broken = _Fake("aaa-broken", reads=False)
    read = _read([broken, _Fake("zzz-reads")], fall_through=False)
    assert read.module is broken and read.error is not None
    assert read.failed == []


def test_failed_extra_parsers_names_the_file_and_never_quotes_the_failure():
    read = _read([_Fake("aaa-broken-banking-pdf", reads=False), _Fake("zzz-reads")])
    reported = parser_common.failed_extra_parsers(read.failed)
    assert reported == [{"file": "aaa-broken-banking-pdf.py", "code": "PARSER_UNCLASSIFIED_ROW", "stage": "activity"}]
    for private in ("PRIVATE SECURITY", "9,876.54", "01/15"):
        assert private not in json.dumps(reported)


# --- the dispatchers, end to end, with drop-ins in a parsers directory ---

_PDF_BROKEN = '''
def detect(head_text):
    if "ZZTEST-PLUGIN-MARKER" in head_text:
        return True, "found zztest marker"
    return False, "zztest marker not found"


def parse(pages_text, pdf_path, vision=None):
    raise ValueError("unclassified transaction row: 01/15 PRIVATE SECURITY $9,876.54")
'''

_PDF_READS = '''
def detect(head_text):
    if "ZZTEST-PLUGIN-MARKER" in head_text:
        return True, "found zztest marker"
    return False, "zztest marker not found"


def parse(pages_text, pdf_path, vision=None):
    return {
        "institution": "Zztest Bank",
        "statementDate": "2026-01-01",
        "transactions": [{
            "date": "2026-01-01", "description": "Test Txn", "amount": -12.34,
            "balance": None, "account": "0000", "accountType": "Checking",
        }],
    }
'''


def _dispatch(script, path, extra_dir, *args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), str(path), "--extra-parsers-dir", str(extra_dir), *args],
        cwd=SCRIPTS, capture_output=True, text=True,
    )
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1])


def test_pdf_a_broken_drop_in_no_longer_blocks_the_one_that_reads_it(tmp_path):
    (tmp_path / "aaa-broken-banking-pdf.py").write_text(_PDF_BROKEN)
    (tmp_path / "zzz_reads.py").write_text(_PDF_READS)
    code, out = _dispatch("bank_statement.py", FIXTURES / "plugin-test-sample.pdf", tmp_path)
    assert code == 0, out
    assert out["detected"] is True and out["institution"] == "Zztest Bank"
    assert out["parser"]["id"] == "zzz_reads"
    assert out["failedExtraParsers"] == [{"file": "aaa-broken-banking-pdf.py", "code": "PARSER_UNCLASSIFIED_ROW", "stage": "activity"}]


def test_pdf_a_broken_override_falls_back_to_the_bundled_parser(tmp_path):
    (tmp_path / "wells_fargo_checking.py").write_text(
        'def detect(head_text):\n    return True, "claims everything"\n\n\n'
        'def parse(pages_text, pdf_path, vision=None):\n    raise ValueError("half-written")\n'
    )
    code, out = _dispatch("bank_statement.py", FIXTURES / "wells-fargo-synthetic-sample.pdf", tmp_path)
    assert code == 0, out
    assert out["parser"] == {"id": "wells_fargo_checking", "tier": out["parser"]["tier"], "bundled": True}
    assert out["tables"]["cash_transactions"], "the bundled parser read nothing"
    assert [f["file"] for f in out["failedExtraParsers"]] == ["wells_fargo_checking.py"]


def test_pdf_a_broken_drop_in_alone_is_named_outside_the_diagnostic(tmp_path):
    (tmp_path / "aaa-broken-banking-pdf.py").write_text(_PDF_BROKEN)
    code, out = _dispatch("bank_statement.py", FIXTURES / "plugin-test-sample.pdf", tmp_path)
    assert code == 1
    assert out["diagnostic"]["parserId"] == "external_parser"
    assert out["diagnostic"]["code"] == "PARSER_UNCLASSIFIED_ROW"
    assert out["error"].startswith("A parser in your parsers folder claimed this statement")
    assert out["failedExtraParsers"] == [{"file": "aaa-broken-banking-pdf.py", "code": "PARSER_UNCLASSIFIED_ROW", "stage": "activity"}]
    # The file name, and anything the parser raised, stay out of what may
    # be reported: the message and the diagnostic.
    reportable = json.dumps({"error": out["error"], "diagnostic": out["diagnostic"]})
    for private in ("aaa-broken", "PRIVATE SECURITY", "9,876.54"):
        assert private not in reportable


def test_pdf_the_parser_asked_for_is_not_passed_over(tmp_path):
    (tmp_path / "aaa-broken-banking-pdf.py").write_text(_PDF_BROKEN)
    (tmp_path / "zzz_reads.py").write_text(_PDF_READS)
    code, out = _dispatch("bank_statement.py", FIXTURES / "plugin-test-sample.pdf", tmp_path,
                          "--expected-parser", "aaa-broken-banking-pdf.py")
    assert code == 1 and "failedExtraParsers" not in out
    assert out["diagnostic"]["parserId"] == "external_parser"


_CSV_BROKEN = '''
def detect(header, sample_rows):
    return "Zztest Amount" in header, "zztest header"


def parse(rows, path):
    raise ValueError("no transaction rows found")
'''

_CSV_READS = '''
def detect(header, sample_rows):
    return "Zztest Amount" in header, "zztest header"


def parse(rows, path):
    return {
        "institution": "Zztest Bank",
        "statementDate": "",
        "transactions": [{
            "date": "2026-01-0" + str(i + 1), "description": r["Zztest Description"], "amount": float(r["Zztest Amount"]),
            "balance": None, "account": "", "accountType": "Checking",
        } for i, r in enumerate(rows)],
    }
'''


def test_csv_a_broken_drop_in_no_longer_blocks_the_one_that_reads_it(tmp_path):
    export = tmp_path / "export.csv"
    export.write_text("Zztest Date,Zztest Description,Zztest Amount\n2026-01-01,Coffee,-4.50\n2026-01-02,Refund,12.00\n")
    parsers = tmp_path / "parsers"
    parsers.mkdir()
    (parsers / "aaa-broken-banking.py").write_text(_CSV_BROKEN)
    (parsers / "zzz_reads.py").write_text(_CSV_READS)
    code, out = _dispatch("csv_statement.py", export, parsers)
    assert code == 0, out
    assert out["parser"]["id"] == "zzz_reads" and len(out["tables"]["cash_transactions"]) == 2
    assert out["failedExtraParsers"] == [{"file": "aaa-broken-banking.py", "code": "PARSER_ACTIVITY_ROWS_NOT_FOUND", "stage": "activity"}]

    # One that changes the rows before it fails hands the next parser the
    # export as it was, not what it left.
    (parsers / "aaa-broken-banking.py").write_text(_CSV_BROKEN.replace(
        'raise ValueError("no transaction rows found")', 'rows.pop(0)\n    rows[0]["Zztest Amount"] = "0"\n    raise ValueError("no transaction rows found")'))
    code, out = _dispatch("csv_statement.py", export, parsers)
    assert code == 0, out
    assert [r["amount"] for r in out["tables"]["cash_transactions"]] == [-4.5, 12.0]

    (parsers / "zzz_reads.py").unlink()
    code, out = _dispatch("csv_statement.py", export, parsers)
    assert code == 1
    assert out["diagnostic"]["rowCount"] == 2
    assert [f["file"] for f in out["failedExtraParsers"]] == ["aaa-broken-banking.py"]
    assert "aaa-broken" not in json.dumps({"error": out["error"], "diagnostic": out["diagnostic"]})
