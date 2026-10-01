"""A dropped-in parser's debug prints must not corrupt dispatcher JSON."""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import FIXTURES, SCRIPTS


def test_pdf_extra_parser_debug_prints_are_suppressed(tmp_path):
    parser = tmp_path / "noisy_citi.py"
    parser.write_text(
        """\
from institutions import citi_credit_card as bundled

print("Imported noisy parser")

def detect(head_text):
    print("Matched: private transaction text")
    return bundled.detect(head_text)

def parse(pages_text, pdf_path, vision=None):
    print("Groups: ('private', '101.75')")
    return bundled.parse(pages_text, pdf_path, vision)
"""
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "bank_statement.py"),
            str(FIXTURES / "citi-costco-synthetic-sample.pdf"),
            "--extra-parsers-dir",
            str(tmp_path),
            "--only-extra-parser",
            parser.name,
        ],
        cwd=SCRIPTS,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["detected"] is True
    assert result["institution"] == "Citi"
    assert "Matched:" not in proc.stdout
    assert "Groups:" not in proc.stdout
    assert "Imported noisy parser" not in proc.stdout
