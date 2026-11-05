"""Axis-aligned reflected glyphs stay on their visual lines."""

import parser_common
import subprocess
import sys
from pathlib import Path


class ReflectedPage:
    def __init__(self):
        self.chars = []
        for row, text in enumerate(("The trustee shall distribute income.", "The beneficiary receives the principal.")):
            for i, letter in enumerate(text):
                top = 100 + row * 20 + (i % 3) * .6
                self.chars.append({
                    "text": letter, "x0": 72 + i * 6, "x1": 78 + i * 6,
                    "top": top, "bottom": top + 13, "doctop": top,
                    "size": 13, "upright": False,
                    "matrix": (.62, 0, 0, -1.3119, 72 + i * 6, top),
                })

    def extract_text(self, **kwargs):
        return " ".join(c["text"] for c in self.chars)


def _check_reflected_text():
    page = ReflectedPage()
    original = [dict(c) for c in page.chars]
    assert parser_common.page_text(page).splitlines() == [
        "The trustee shall distribute income.",
        "The beneficiary receives the principal.",
    ]
    assert page.chars == original


def test_reflected_horizontal_text_keeps_words_and_lines():
    # Other parser tests stub pdfplumber globally; use the same isolated
    # process pattern as test_parser_common_helpers.PageTextTest.
    tests = Path(__file__).resolve().parent
    subprocess.run([
        sys.executable, "-B", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from test_reflected_text import _check_reflected_text; _check_reflected_text()",
        str(tests),
    ], cwd=tests.parent / "scripts", check=True, capture_output=True, text=True)


def test_rotated_skewed_and_unmeasured_orientation_is_preserved():
    for matrix in ((0, 1, -1, 0, 0, 0), (1, .1, 0, -1, 0, 0),
                   (1, 0, .1, -1, 0, 0), (-1, 0, 0, 1, 0, 0), None):
        assert parser_common._horizontal_chars([{"upright": False, "matrix": matrix}]) is None
