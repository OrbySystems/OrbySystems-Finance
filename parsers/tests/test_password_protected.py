"""A PDF that needs a password to open (orby-core
docs/password-protected-pdfs.md): bank_statement.py says so with a code
instead of an empty error, and opens it with the password the app passes on
stdin (--password-stdin), never on the command line. A PDF encrypted with an
empty user password, as some banks send theirs, opens as before."""

import json
import subprocess
import sys
from pathlib import Path

from reportlab.lib import pdfencrypt
from reportlab.pdfgen import canvas

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
PASSWORD = "Sunil1984"


def _pdf(path: Path, user_password: str) -> Path:
    """A one-page PDF, encrypted with user_password (empty: opens without one)."""
    encryption = pdfencrypt.StandardEncryption(user_password, ownerPassword="owner-only-secret", canPrint=1)
    c = canvas.Canvas(str(path), encrypt=encryption)
    c.drawString(72, 720, "Statement of Account")
    c.save()
    return path


def _run(path: Path, *args: str, password: str | None = None) -> tuple[int, dict, str]:
    cmd = [sys.executable, str(SCRIPTS / "bank_statement.py"), str(path), *args]
    if password is not None:
        cmd.append("--password-stdin")
    proc = subprocess.run(cmd, cwd=SCRIPTS, capture_output=True, text=True, input=password)
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1]), proc.stdout + proc.stderr


def test_a_locked_pdf_read_without_its_password_says_so(tmp_path):
    locked = _pdf(tmp_path / "locked.pdf", PASSWORD)
    for args in ((), ("--dump-text",), ("--check-password",)):
        code, out, _ = _run(locked, *args)
        assert code == 1, args
        assert out["code"] == "PDF_PASSWORD_REQUIRED", args
        assert "password-protected" in out["error"], args


def test_the_wrong_password_is_said_so_and_never_repeated(tmp_path):
    locked = _pdf(tmp_path / "locked.pdf", PASSWORD)
    for args in ((), ("--dump-text",), ("--check-password",)):
        code, out, printed = _run(locked, *args, password="not-it-1984")
        assert code == 1, args
        assert out["code"] == "PDF_PASSWORD_INCORRECT", args
        assert "not-it-1984" not in printed, args


def test_a_password_the_pdf_cannot_take_is_wrong_and_never_repeated(tmp_path):
    # pdfminer encodes an older PDF's password in Latin-1: a character outside
    # it is no password of this PDF's, and Python's error would quote it.
    locked = _pdf(tmp_path / "locked.pdf", PASSWORD)
    for args in ((), ("--dump-text",), ("--check-password",)):
        code, out, printed = _run(locked, *args, password="Asha€१९८४")
        assert code == 1, args
        assert out["code"] == "PDF_PASSWORD_INCORRECT", args
        assert "€" not in printed and "१" not in printed, args


def test_the_right_password_opens_it(tmp_path):
    locked = _pdf(tmp_path / "locked.pdf", PASSWORD)
    assert _run(locked, "--check-password", password=PASSWORD)[:2] == (0, {"opens": True})
    code, out, _ = _run(locked, "--dump-text", password=PASSWORD)
    assert code == 0 and "Statement of Account" in out["pages"][0]
    # Read for a statement: opened, and simply no parser's.
    code, out, printed = _run(locked, password=PASSWORD)
    assert code == 0 and out["detected"] is False and "code" not in out
    assert PASSWORD not in printed
    # Typed at a terminal, with its newline.
    assert _run(locked, "--check-password", password=PASSWORD + "\n")[:2] == (0, {"opens": True})


def test_a_pdf_encrypted_with_an_empty_password_opens_as_before(tmp_path):
    open_one = _pdf(tmp_path / "owner-only.pdf", "")
    assert _run(open_one, "--check-password")[:2] == (0, {"opens": True})
    code, out, _ = _run(open_one, "--dump-text")
    assert code == 0 and "Statement of Account" in out["pages"][0]
    code, out, _ = _run(open_one)
    assert code == 0 and out["detected"] is False and "code" not in out
