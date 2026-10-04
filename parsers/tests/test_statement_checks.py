"""statement_checks: a statement's own arithmetic, checked and explained.

A parser reports what the statement prints about itself; the dispatcher
evaluates it. A failure is explained from the numbers - that explanation is
what OrbySystems asks the user about - and the user's answers re-run the
parse. These cover each kind of check, each explanation, the answers, what
may leave the machine, and both ends of a dispatcher run.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import parser_common
import statement_checks as sc
from conftest import SCRIPTS


def rows(*amounts, balances=None):
    out = []
    for i, a in enumerate(amounts):
        out.append({"date": "2026-01-%02d" % (i + 2), "description": "Row %d" % i, "amount": a,
                    "balance": balances[i] if balances else None, "account": "8899", "accountType": "Credit Card"})
    return out


def one(results):
    assert len(results) == 1
    return results[0]


class TestValidate:
    def test_well_formed_checks_pass(self):
        tables = {"cash_transactions": rows(-10.0, -20.0)}
        sc.validate_checks([
            {"kind": "sum", "label": "Purchases", "table": "cash_transactions", "rows": [0, 1], "expected": -30.0},
            {"kind": "balance", "label": "Summary", "table": "cash_transactions", "rows": [0, 1], "opening": 0, "closing": -30},
            {"kind": "running", "label": "Summary", "table": "cash_transactions", "rows": [0, 1]},
            {"kind": "unread", "label": "Purchases", "lines": [{"page": 1, "line": 4, "text": "x"}]},
        ], tables, "institutions.example")

    @pytest.mark.parametrize("check, message", [
        ({"kind": "total", "label": "x"}, "kind"),
        ({"kind": "sum", "label": "", "table": "cash_transactions", "rows": [], "expected": 0}, "label"),
        ({"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [0]}, "missing"),
        ({"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [0], "expected": 1, "note": "y"}, "unexpected"),
        ({"kind": "sum", "label": "x", "table": "brokerage_holdings", "rows": [], "expected": 0}, "did not return"),
        ({"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [5], "expected": 0}, "index"),
        ({"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [0, 0], "expected": 0}, "each once"),
        ({"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [0], "expected": "1"}, "number"),
        ({"kind": "unread", "label": "x", "lines": [{"page": 1, "text": "y"}]}, "lines"),
    ])
    def test_a_malformed_check_fails_by_name(self, check, message):
        with pytest.raises(ValueError, match=message) as err:
            sc.validate_checks([check], {"cash_transactions": rows(-10.0)}, "institutions.example")
        assert "institutions.example.parse(): checks[0]" in str(err.value)

    def test_the_validators_take_checks_for_both_kinds(self):
        bank = {"institution": "X", "statementDate": "", "transactions": rows(-1.0),
                "checks": [{"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [3], "expected": -1}]}
        with pytest.raises(ValueError, match="checks"):
            parser_common.validate_parse_result(bank, "institutions.example")
        brokerage = {"institution": "X", "statementDate": "", "tables": {"cash_transactions": rows(-1.0)},
                     "checks": [{"kind": "sum", "label": "x", "table": "cash_transactions", "rows": [0], "expected": -1}]}
        parser_common.validate_multi_table_parse_result(brokerage, "institutions.example")


class TestEvaluate:
    tables = {"cash_transactions": rows(-12.5, -7.5, 40.0)}

    def check(self, **kw):
        return {"kind": "sum", "label": "Purchases", "table": "cash_transactions", "rows": [0, 1], **kw}

    def test_a_sum_that_holds(self):
        r = one(sc.evaluate([self.check(expected=-20.0)], self.tables))
        assert r["ok"] and r["parsed"] == -20.0 and r["expected"] == -20.0 and r["rowCount"] == 2

    def test_cents_of_rounding_are_not_a_failure(self):
        assert one(sc.evaluate([self.check(expected=-20.004)], self.tables))["ok"]

    def test_a_section_read_with_its_sign_reversed(self):
        r = one(sc.evaluate([self.check(expected=20.0)], self.tables))
        assert not r["ok"] and r["explanation"] == {"kind": "sign", "rows": [0, 1], "lines": []}

    def test_one_row_with_its_sign_reversed(self):
        r = one(sc.evaluate([self.check(expected=-5.0)], self.tables))  # -12.5 + 7.5
        assert r["explanation"]["kind"] == "row-sign" and r["explanation"]["rows"] == [1]

    def test_a_row_that_should_not_count(self):
        r = one(sc.evaluate([self.check(expected=-12.5)], self.tables))
        assert r["explanation"]["kind"] == "extra-row" and r["explanation"]["rows"] == [1]

    def test_a_line_the_parser_did_not_read(self):
        checks = [self.check(expected=-50.0),
                  {"kind": "unread", "label": "Purchases", "lines": [{"page": 1, "line": 9, "text": "01/06 BOOK STORE $30.00"}]}]
        result, unread = sc.evaluate(checks, self.tables, "2026-01-22")
        assert result["explanation"] == {"kind": "missing-lines", "rows": [], "lines": [{"check": 1, "line": 0}]}
        assert not unread["ok"]
        assert unread["lines"][0]["suggested"]["amount"] == -30.0  # the section's sign: money out

    def test_nothing_explains_it(self):
        assert one(sc.evaluate([self.check(expected=-99.99)], self.tables))["explanation"]["kind"] == "none"

    def test_a_balance(self):
        check = {"kind": "balance", "label": "Summary", "table": "cash_transactions", "rows": [0, 1, 2],
                 "opening": -100.0, "closing": -80.0}
        assert one(sc.evaluate([check], self.tables))["ok"]
        check["closing"] = -120.0
        r = one(sc.evaluate([check], self.tables))
        assert not r["ok"] and r["parsed"] == -80.0 and r["expected"] == -120.0

    def test_a_running_balance_breaks_where_a_row_has_its_sign_reversed(self):
        tables = {"cash_transactions": rows(-10.0, 5.0, -2.0, balances=[90.0, 85.0, 83.0])}
        check = {"kind": "running", "label": "Checking", "table": "cash_transactions", "rows": [0, 1, 2], "opening": 100.0}
        r = one(sc.evaluate([check], tables))
        assert not r["ok"] and r["explanation"] == {"kind": "row-sign", "rows": [1], "lines": []}
        tables["cash_transactions"][1]["amount"] = -5.0
        assert one(sc.evaluate([check], tables))["ok"]


class TestSuggestRow:
    def test_reads_date_description_and_amount(self):
        row = sc.suggest_row("12/30 BOOK STORE #12 $1,030.00", "2026-01-22", -1,
                             {"account": "8899", "accountType": "Credit Card"})
        # A December row on a January statement is last year's.
        assert row == {"date": "2025-12-30", "description": "BOOK STORE #12", "amount": -1030.0,
                       "balance": None, "account": "8899", "accountType": "Credit Card"}

    def test_a_printed_sign_reverses_the_section_sign(self):
        assert sc.suggest_row("01/05 REFUND 45.00 CR", "2026-01-22", -1)["amount"] == 45.0
        assert sc.suggest_row("01/05 REFUND (45.00)", "2026-01-22", 1)["amount"] == -45.0
        assert sc.suggest_row("01/05/2026 DEPOSIT 45.00", "", 1)["date"] == "2026-01-05"

    def test_a_line_without_a_date_or_amount_is_not_a_row(self):
        assert sc.suggest_row("BOOK STORE 30.00", "2026-01-22", -1) is None
        assert sc.suggest_row("01/05 POUND STERLING", "2026-01-22", -1) is None
        assert sc.suggest_row("13/45 NOT A DATE 1.00", "2026-01-22", -1) is None


class TestAdjustments:
    def test_flip_exclude_and_include_and_renumber_the_checks(self):
        tables = {"cash_transactions": rows(-10.0, 999.0, -20.0)}
        checks = [{"kind": "sum", "label": "Purchases", "table": "cash_transactions", "rows": [0, 1, 2], "expected": -60.0}]
        sc.apply_adjustments(tables, checks, {
            "flip": [{"table": "cash_transactions", "rows": [0]}],
            "exclude": [{"table": "cash_transactions", "row": 1}],
            "include": [{"table": "cash_transactions", "check": 0, "row": rows(-50.0)[0]}],
        })
        assert [r["amount"] for r in tables["cash_transactions"]] == [10.0, -20.0, -50.0]
        assert checks[0]["rows"] == [0, 1, 2]
        assert one(sc.evaluate(checks, tables))["ok"]

    def test_an_included_or_dismissed_line_is_settled(self):
        tables = {"cash_transactions": rows(-10.0)}
        checks = [{"kind": "sum", "label": "Purchases", "table": "cash_transactions", "rows": [0], "expected": -40.0},
                  {"kind": "unread", "label": "Purchases", "lines": [
                      {"page": 1, "line": 3, "text": "01/04 A $30.00"}, {"page": 1, "line": 4, "text": "01/05 B TOTAL 1.00"}]}]
        sc.apply_adjustments(tables, checks, {
            "include": [{"table": "cash_transactions", "check": 0, "row": rows(-30.0)[0], "line": {"check": 1, "line": 0}}],
            "dismiss": [{"check": 1, "line": 1}],
        })
        assert checks[1]["lines"] == []
        assert [r["ok"] for r in sc.evaluate(checks, tables)] == [True, True]

    def test_malformed_answers_are_refused(self):
        with pytest.raises(ValueError):
            sc.validate_adjustments({"flip": "all"})
        with pytest.raises(ValueError):
            sc.validate_adjustments({"rewrite": []})


class TestWhatMayLeaveTheMachine:
    def test_the_diagnostic_carries_no_label_text_or_amount(self):
        checks = [{"kind": "sum", "label": "MARILYN MOSBY PURCHASES", "table": "cash_transactions", "rows": [0, 1],
                   "expected": -1234.56},
                  {"kind": "unread", "label": "MARILYN MOSBY PURCHASES",
                   "lines": [{"page": 2, "line": 7, "text": "01/06 MOSBY DENTAL 4417 $86.20"}]}]
        tables = {"cash_transactions": rows(-12.5, -7.5)}
        summary = sc.diagnostic_summary(sc.evaluate(checks, tables, "2026-01-22"))
        encoded = json.dumps(summary)
        for private in ("MOSBY", "MARILYN", "DENTAL", "4417", "86.20", "1234.56", "12.5", "Purchases"):
            assert private not in encoded
        assert summary[0] == {"kind": "sum", "ok": False, "rowCount": 2, "explanation": "none"}
        assert summary[1]["lines"] == [{"page": 2, "line": 7, "shape": "99/99 AAAAA AAAAAA 9999 $99.99"}]


def _dispatch(pdf, *args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / "bank_statement.py"), str(pdf), *args],
                          cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _chase_like(path, rows_text):
    """A one-page statement in the Chase card layout (the parser's own
    fixture generator draws the full one), with the rows given."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    lines = ["Manage your account online: www.chase.com", "Account Number: XXXX XXXX XXXX 8899",
             "Previous Balance $100.00", "New Balance $150.00", "Opening/Closing Date 12/23/25 - 01/22/26",
             "Transaction Merchant Name or Transaction Description $ Amount", "PURCHASE", *rows_text]
    y = 740
    for line in lines:
        c.drawString(72, y, line)
        y -= 16
    c.save()


def test_a_reconciling_statement_names_its_parser(run_statement):
    stmt = run_statement("chase-synthetic-sample.pdf")
    assert stmt.raw["parser"] == {"id": "chase_credit_card", "tier": "verified", "bundled": True}
    assert [(r["kind"], r["ok"]) for r in stmt.raw["checkResults"]] == [("balance", True)]


def test_a_failed_check_holds_and_the_answers_clear_it(tmp_path):
    pdf = tmp_path / "stmt.pdf"
    # The second purchase prints "$30.00", which the Chase row pattern
    # does not take: it is reported as not read, and the Account summary
    # (100 + 20 + 30 = 150) comes up short by exactly it.
    _chase_like(pdf, ["12/24 COFFEE HOUSE 20.00", "12/26 BOOK STORE $30.00"])
    first = _dispatch(pdf)
    assert first["detected"] and "error" not in first
    balance, unread = first["checkResults"]
    assert not balance["ok"] and balance["explanation"]["kind"] == "missing-lines"
    suggested = unread["lines"][0]["suggested"]
    assert suggested["date"] == "2025-12-26" and suggested["amount"] == -30.0

    answer = {"include": [{"table": "cash_transactions", "check": 0, "row": suggested,
                           "line": {"check": 1, "line": 0}}]}
    second = _dispatch(pdf, "--adjust", json.dumps(answer))
    assert [r["ok"] for r in second["checkResults"]] == [True, True]  # the line is now read, too
    assert [r["amount"] for r in second["tables"]["cash_transactions"]] == [-20.0, -30.0]

    # Set aside as not a transaction instead: the line is settled, and the
    # Account summary is left honestly short.
    third = _dispatch(pdf, "--adjust", json.dumps({"dismiss": [{"check": 1, "line": 0}]}))
    assert [r["ok"] for r in third["checkResults"]] == [False, True]


def test_bad_answers_are_an_error_not_a_parse(tmp_path):
    pdf = tmp_path / "stmt.pdf"
    _chase_like(pdf, ["12/24 COFFEE HOUSE 20.00"])
    assert "error" in _dispatch(pdf, "--adjust", "{not json")
    assert "error" in _dispatch(pdf, "--adjust", json.dumps({"rewrite": []}))
