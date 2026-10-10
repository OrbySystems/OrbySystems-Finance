"""Backwards-compatible mode, end to end. A parser written before the
direction / corporate_event / unsigned-quantity rules (a user's own) is still
read when a statement is imported, with a warning for each rule it breaks;
with --strict, which is how a parser is written and tested, the same output
is refused.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_backcompat_mode.py)
"""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import SCRIPTS

_OLD_BROKERAGE_CSV_PARSER = '''
KIND = "brokerage"


def detect(header, sample_rows):
    return "Zztest Qty" in header, "zztest header"


def parse(rows, path):
    base = {"date": "2026-01-02", "account": "1234", "accountType": "Brokerage"}
    return {
        "institution": "Zztest Brokerage",
        "statementDate": "",
        "tables": {"brokerage_transactions": [
            {**base, "description": "Sold 5 XYZ", "amount": 500.0, "symbol": "XYZ",
             "transaction_type": "sell", "quantity": -5.0},
            {**base, "description": "Reverse split", "amount": 0.0, "symbol": "XYZ",
             "transaction_type": "corporate_action", "action": "Reverse Split", "quantity": -9.0},
            {**base, "description": "Moved out", "amount": -100.0,
             "transaction_type": "internal_transfer", "action": "Transfer Out"},
        ]},
    }
'''


def _run(tmp_path, *flags):
    export = tmp_path / "export.csv"
    export.write_text("Zztest Date,Zztest Qty\n2026-01-02,5\n")
    parsers = tmp_path / "parsers"
    parsers.mkdir(exist_ok=True)
    (parsers / "old_user_parser.py").write_text(_OLD_BROKERAGE_CSV_PARSER)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "csv_statement.py"), str(export), "--extra-parsers-dir", str(parsers), *flags],
        cwd=SCRIPTS, capture_output=True, text=True,
    )
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1])


def test_importing_reads_an_old_parser_and_warns(tmp_path):
    code, out = _run(tmp_path)
    assert code == 0, out
    assert out["parser"]["id"] == "old_user_parser"
    assert len(out["tables"]["brokerage_transactions"]) == 3
    joined = "\n".join(out["warnings"])
    for fragment in ("quantity -5.0", "no corporate_event", "direction goes in subtype"):
        assert fragment in joined, (fragment, out["warnings"])
    assert "older parsers keep working" in joined


def test_strict_refuses_the_same_parser(tmp_path):
    code, out = _run(tmp_path, "--strict")
    assert code != 0 or not out.get("detected", True) or "warnings" not in out
    assert out.get("tables") is None, out
    assert out.get("failedExtraParsers") or out.get("diagnostic") or out.get("error") or out.get("reason"), out
