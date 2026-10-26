"""Unit tests for parser_common's spreadsheet header/footer helpers
(looks_like_header_row / grid_header_and_rows), used by csv_statement.py
for both the CSV and .xlsx paths.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_parser_common_helpers.py)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pkg", "ingest", "py"))
import parser_common  # noqa: E402


class HeaderRowTest(unittest.TestCase):
    def test_looks_like_header_row(self):
        self.assertTrue(parser_common.looks_like_header_row(["Date", "Description", "Amount"]))
        self.assertTrue(parser_common.looks_like_header_row(["Settlement date", "Symbol", "Amount", "", ""]))
        # a data row: has a date and a number
        self.assertFalse(parser_common.looks_like_header_row(["2024-01-02", "Coffee", "-5.00"]))
        self.assertFalse(parser_common.looks_like_header_row(["8/30/2020", "VMRAX", "$74.28"]))
        # a one-cell preamble / footer line
        self.assertFalse(parser_common.looks_like_header_row(["Custom report created on: 09/01/2026."]))
        self.assertFalse(parser_common.looks_like_header_row(["", "", ""]))

    def test_grid_header_and_rows_strips_preamble_and_footer(self):
        grid = [
            ["Custom report created on: 09/01/2026.", "", ""],
            ["This report only includes ...", "", ""],
            ["Settlement date", "Symbol", "Amount"],
            ["8/30/2020", "VMRAX", ""],
            ["3/19/2024", "VMRAX", "$74.29"],
            [],
            ["DISCLOSURES"],
            ["*Note on account protection ..."],
        ]
        header, data = parser_common.grid_header_and_rows(grid)
        self.assertEqual(header, ["Settlement date", "Symbol", "Amount"])
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0], ["8/30/2020", "VMRAX", ""])

    def test_grid_header_and_rows_plain_table(self):
        grid = [["Date", "Amount"], ["2024-01-01", "-5.00"], ["2024-01-02", "10.00"]]
        header, data = parser_common.grid_header_and_rows(grid)
        self.assertEqual(header, ["Date", "Amount"])
        self.assertEqual(len(data), 2)

    def test_grid_header_and_rows_no_header_falls_back(self):
        grid = [["a"], ["b"]]
        header, data = parser_common.grid_header_and_rows(grid)
        self.assertEqual(header, ["a"])
        self.assertEqual(data, [["b"]])


if __name__ == "__main__":
    unittest.main()


def _retail(**row):
    base = {"date": "2026-03-02", "description": "Sample item", "amount": -10.0, "order_id": "A-1",
            "line_type": "purchase"}
    base.update(row)
    return {"institution": "Sample Store", "statementDate": "", "tables": {"retail_items": [base]}}


def test_a_retail_row_says_whether_it_is_a_purchase_or_a_refund():
    import pytest

    parser_common.validate_multi_table_parse_result(_retail(), "m")
    parser_common.validate_multi_table_parse_result(_retail(line_type="refund", amount=10.0), "m")
    missing = _retail()
    del missing["tables"]["retail_items"][0]["line_type"]
    for bad, says in ((missing, "missing key"), (_retail(line_type="return"), "must be one of"),
                      (_retail(line_type="refund"), "money back is positive"),
                      (_retail(amount=10.0), "money spent is negative")):
        with pytest.raises(ValueError, match=says):
            parser_common.validate_multi_table_parse_result(bad, "m")


def test_subscribe_and_save_is_a_bool():
    import pytest

    parser_common.validate_multi_table_parse_result(_retail(subscribe_and_save=True), "m")
    with pytest.raises(ValueError, match="must be a bool"):
        parser_common.validate_multi_table_parse_result(_retail(subscribe_and_save="yes"), "m")


class PageTextTest(unittest.TestCase):
    def test_words_set_in_small_type_stay_apart(self):
        # "Statement" and "Period" 2pt apart: under pdfplumber's flat 3pt,
        # so extract_text() glues them; page_text() reads a space. Run in a
        # subprocess: test_bofa_checking_unit.py stubs pdfplumber in this one.
        import subprocess
        import tempfile

        script = (
            "import sys, pdfplumber, parser_common\n"
            "from reportlab.pdfgen import canvas\n"
            "c = canvas.Canvas(sys.argv[1]); c.setFont('Helvetica', 8)\n"
            "c.drawString(72, 700, 'Statement')\n"
            "c.drawString(72 + c.stringWidth('Statement', 'Helvetica', 8) + 2, 700, 'Period')\n"
            "c.drawString(72, 680, 'Kerning'); c.save()\n"
            "with pdfplumber.open(sys.argv[1]) as pdf:\n"
            "    page = pdf.pages[0]\n"
            "    print(page.extract_text().split('\\n')[0])\n"
            "    print(parser_common.page_text(page).replace('\\n', '|'))\n"
        )
        scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, "-c", script, os.path.join(tmp, "small.pdf")],
                                 cwd=scripts, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.split("\n")[:2], ["StatementPeriod", "Statement Period|Kerning"])

    def _read(self, drawing: str) -> list[str]:
        """[extract_text's lines, page_text's lines] of a page drawn by
        drawing (reportlab, canvas c), read in a subprocess: see above."""
        import json
        import subprocess
        import tempfile

        script = (
            "import json, sys, pdfplumber, parser_common\n"
            "from reportlab.pdfgen import canvas\n"
            "c = canvas.Canvas(sys.argv[1])\n"
            "def tiny(x, y, text):\n"
            "    t = c.beginText(x, y); t.setFont('Helvetica', 0.24); t.setHorizScale(1000); t.textOut(text); c.drawText(t)\n"
            + drawing +
            "c.save()\n"
            "with pdfplumber.open(sys.argv[1]) as pdf:\n"
            "    page = pdf.pages[0]\n"
            "    print(json.dumps([(page.extract_text(x_tolerance_ratio=parser_common.SPACE_GAP_EM) or '').splitlines(),\n"
            "                      parser_common.page_text(page).splitlines()]))\n"
        )
        scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, "-c", script, os.path.join(tmp, "page.pdf")],
                                 cwd=scripts, capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_microprint_is_as_small_as_it_is_measured_and_keeps_its_line(self):
        # 0.5pt text in a row's middle, on its baseline: it is narrow for
        # its size, so measured right, and read where it always was.
        by_tops, lines = self._read(
            "c.setFont('Helvetica', 9); c.drawString(72, 700, '09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00')\n"
            "c.setFont('Helvetica', 0.5); c.drawString(150, 700, 'ORIGINALDOCUMENTSECURITYLINE')\n"
            "c.drawString(20, 700, 'DOCID')\n"
        )
        self.assertEqual(lines, by_tops)
        self.assertIn("09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00", lines)

    def test_a_label_too_small_to_measure_takes_the_size_of_the_values_on_its_line(self):
        # Mostly 12pt print, the labels' values 8.5pt: at the page's usual
        # size, a label would still be read apart from its value.
        by_tops, lines = self._read(
            "c.setFont('Helvetica', 12)\n"
            "for n in range(12): c.drawString(72, 500 - 16 * n, 'Important information about your account number %d' % n)\n"
            "tiny(60, 700, 'Account number ending in:'); c.setFont('Helvetica', 8.5); c.drawString(150, 700, '4455')\n"
            "tiny(40, 690.5, 'Billing Period:'); c.drawString(70, 690.5, '08/15/26-09/14/26')\n"
        )
        self.assertNotIn("Account number ending in: 4455", by_tops)
        self.assertEqual(lines[:2], ["Account number ending in: 4455", "Billing Period: 08/15/26-09/14/26"])

    def test_a_page_with_a_character_too_small_to_measure_reads_as_extract_text_lays_it_out(self):
        # A 0.24pt character far from the rest changes no line, so the page
        # reads exactly as extract_text has it - margin text running up the
        # side, drawn between two lines, included: only extract_text's own
        # layout (chars_to_textmap) keeps it between them.
        import subprocess
        import tempfile

        script = (
            "import sys, pdfplumber, parser_common\n"
            "from reportlab.pdfgen import canvas\n"
            "c = canvas.Canvas(sys.argv[1]); c.setFont('Helvetica', 10)\n"
            "c.drawString(72, 700, 'Statement Period 01/15/2026 to 02/14/2026')\n"
            "c.saveState(); c.translate(30, 400); c.rotate(90); c.drawString(0, 0, 'REF 9921 MARGIN'); c.restoreState()\n"
            "c.drawString(72, 680, 'Previous Balance 1,234.56')\n"
            "c.setFont('Helvetica', 0.24); c.drawString(500, 100, 'x'); c.save()\n"
            "with pdfplumber.open(sys.argv[1]) as pdf:\n"
            "    page = pdf.pages[0]\n"
            "    assert any(ch['size'] < 1 for ch in page.chars)\n"
            "    print(page.extract_text(x_tolerance_ratio=parser_common.SPACE_GAP_EM) == parser_common.page_text(page))\n"
        )
        scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, "-c", script, os.path.join(tmp, "margin.pdf")],
                                 cwd=scripts, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "True")
