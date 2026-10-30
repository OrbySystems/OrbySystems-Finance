"""KeyPoint Credit Union statement of account (keypoint_credit_union).

The demo statement, a copy with its labels' words run together, and a
trust's statement that names KeyPoint only by its web address are generated
from invented data by
tests/generators/gen-keypoint-credit-union-sample.py. The page texts in the
unit tests below are its pages, changed: their shapes follow the
statement's layout, their names and figures come from no statement.
"""

from __future__ import annotations

import pytest

import parser_common
import statement_checks
from institutions import keypoint_credit_union

DEMO = "keypoint-credit-union-synthetic-sample.pdf"
RUN_TOGETHER = "keypoint-credit-union-run-together-synthetic-sample.pdf"
TRUST = "keypoint-credit-union-trust-synthetic-sample.pdf"


def _parse(pages: list[str]):
    out = keypoint_credit_union.parse(pages, "unused.pdf", None)
    parser_common.validate_parse_result(out, "keypoint_credit_union")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return out, results


def _failed(results) -> set[tuple[str, str]]:
    return {(r["kind"], r["label"]) for r in results if not r["ok"]}


def _unread(out) -> list[str]:
    return [line["text"] for c in out["checks"] if c["kind"] == "unread" for line in c["lines"]]


# Every account reads, each row signed by the balance after it, and every
# check the statement's figures give holds.
def test_demo_statement(run_statement):
    stmt = run_statement(DEMO, "--expected-parser", "keypoint_credit_union.py")
    assert (stmt.institution, stmt.statement_date) == ("KeyPoint Credit Union", "2026-12-31")
    assert stmt.raw["parser"] == {"id": "keypoint_credit_union", "tier": "verified", "bundled": True}
    by_account: dict[tuple[str, str], list[float]] = {}
    for t in stmt.transactions:
        by_account.setdefault((t["account"], t["accountType"]), []).append(t["amount"])
    assert by_account == {
        ("5678", "Checking"): [-150.0, 2500.0, -1000.0, -96.3, -700.0, -5.0],
        # Carried on to the next page under the column header alone.
        ("0001", "Savings"): [1000.0, -250.0, 1.05],
        ("0009", "Savings"): [50.0, 0.03],
    }
    # The opening balance lines move no money and are not rows.
    assert "Beginning Balance" not in {t["description"] for t in stmt.transactions}
    results = stmt.raw["checkResults"]
    assert len(results) == 9 and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


# Claimed by its layout and KeyPoint's name together: another credit union
# printing the same summary is not read as KeyPoint.
def test_detect_needs_the_layout_and_keypoints_name(dump_pages):
    head = "\n".join(dump_pages(DEMO))
    assert keypoint_credit_union.detect(head)[0] is True
    assert keypoint_credit_union.detect(head.replace("KeyPoint", "Lakeshore"))[0] is False
    assert keypoint_credit_union.detect(head.replace("Withdrawal Deposit Balance", "Amount Balance"))[0] is False


# A statement that names KeyPoint only by its web address, a trust's in the
# layout of a second scrambled sample, reads like any other: the money
# market account carried on to a page with its column header and no rows,
# and the savings account with no activity checked though it has no rows.
def test_a_statement_that_names_keypoint_only_by_its_web_address(run_statement, dump_pages):
    assert "keypoint" not in "\n".join(dump_pages(TRUST)).lower()
    stmt = run_statement(TRUST, "--expected-parser", "keypoint_credit_union.py")
    assert (stmt.institution, stmt.statement_date) == ("KeyPoint Credit Union", "2026-12-31")
    assert stmt.raw["parser"] == {"id": "keypoint_credit_union", "tier": "verified", "bundled": True}
    by_account: dict[tuple[str, str], list[float]] = {}
    for t in stmt.transactions:
        by_account.setdefault((t["account"], t["accountType"]), []).append(t["amount"])
    assert by_account == {
        ("5670", "Checking"): [200.0, -325.0, 400.0, -325.0, 300.0],
        ("0002", "Money Market"): [-200.0, -400.0, -300.0, 1.95],
    }
    results = stmt.raw["checkResults"]
    assert len(results) == 9 and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    assert sum("REGULAR SAVINGS Account No. 0003" in r["label"] for r in results) == 3


# KeyPoint's web address names it as its name does, never without the
# layout, and never in a row: another credit union's member can pay KeyPoint.
def test_detect_takes_keypoints_web_address_for_its_name(dump_pages):
    head = "\n".join(dump_pages(TRUST))
    assert keypoint_credit_union.detect(head)[0] is True
    assert keypoint_credit_union.detect(head.replace("Statement of Account", "Account Summary"))[0] is False
    elsewhere = head.replace("kpcu.com", "lakeshorecu.org")
    assert keypoint_credit_union.detect(elsewhere)[0] is False
    paying = elsewhere.replace("12/12 Check 2001", "12/12 Bill Pay KPCU.COM LOAN PMT")
    assert paying != elsewhere and keypoint_credit_union.detect(paying)[0] is False


# A file can hold two statements of one period: the trust's sample started
# its own on page 4 of 7. Each reads as it does alone, its accounts not
# joined to the other's.
def test_two_statements_in_one_file_read_as_each_does_alone(dump_pages):
    demo, trust = dump_pages(DEMO), dump_pages(TRUST)
    out, results = _parse(demo + trust)
    assert out["transactions"] == _parse(demo)[0]["transactions"] + _parse(trust)[0]["transactions"]
    assert len(results) == 18 and _failed(results) == set()


# The scrambled sample's text ran labels' words together ("PostDate",
# "AccountNo."), as the statement's own text layer may: read either way, the
# statement reads the same.
def test_labels_with_their_words_run_together_read_the_same(run_statement, dump_pages):
    lines = [line for page in dump_pages(RUN_TOGETHER) for line in page.splitlines()]
    assert "PostDate TransactionDescription Withdrawal Deposit Balance" in lines
    assert "FREE CHECKING AccountNo.12345678" in lines and "EndDate: 12/31/2026" in lines
    spaced = run_statement(DEMO, "--expected-parser", "keypoint_credit_union.py")
    joined = run_statement(RUN_TOGETHER, "--expected-parser", "keypoint_credit_union.py")
    assert (joined.institution, joined.statement_date) == (spaced.institution, spaced.statement_date)

    def key(t):
        return t["date"], t["account"], t["accountType"], t["amount"], t["balance"]
    assert [key(t) for t in joined.transactions] == [key(t) for t in spaced.transactions]
    results = joined.raw["checkResults"]
    assert len(results) == 9 and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


@pytest.mark.parametrize("name", ["AUTO LOAN", "VISA PLATINUM"])
def test_an_account_that_is_a_debt_is_reported_not_read(dump_pages, name):
    pages = dump_pages(DEMO)
    debt = "\n".join([
        f"{name} Account No. 12340050",
        "Beginning Dividend Service Ending",
        "Balance + Deposits + Paid - Withdrawals - Charges = Balance",
        "$9,000.00 $0.00 $0.00 $350.00 $0.00 $8,650.00",
        "Post Date Transaction Description Withdrawal Deposit Balance",
        "12/10 Payment 350.00 8,650.00",
    ])
    changed = [page.replace("Federally insured by NCUA", debt + "\nFederally insured by NCUA") for page in pages]
    assert changed != pages
    out, results = _parse(changed)
    assert len(out["transactions"]) == 11
    assert _unread(out) == ["12/10 Payment 350.00 8,650.00"]


# A name that says no kind is passed on as printed, for the app to report
# as unclassified (common.classify_account_type), never guessed.
def test_an_account_name_that_gives_no_type_is_passed_on_as_printed(dump_pages):
    pages = [page.replace("HOLIDAY CLUB", "EVERYDAY REWARDS") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert {t["accountType"] for t in out["transactions"] if t["account"] == "0009"} == {"EVERYDAY REWARDS"}
    assert _failed(results) == set()


# A dated line with a balance and no amount that moves the balance is a row
# whose amount did not read: reported, and the account's checks fail. The
# rows after it go on from its balance, so they keep their signs.
def test_a_balance_line_that_moves_the_balance_is_reported_not_read(dump_pages):
    pages = [page.replace("12/20 Check 1002 700.00 1,753.70", "12/20 Check 1002 1,753.70") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert _unread(out) == ["12/20 Check 1002 1,753.70"]
    assert ("balance", "FREE CHECKING Account No. 5678") in _failed(results)
    assert [t["amount"] for t in out["transactions"] if t["description"] == "Monthly Service Charge"] == [-5.0]
    assert ("sum", "FREE CHECKING Account No. 5678: deposits and dividends") not in _failed(results)


# An account whose heading did not read has its lines reported, never joined
# to the account before it.
def test_an_account_whose_heading_did_not_read_is_reported_not_read(dump_pages):
    pages = [page.replace("REGULAR SAVINGS Account No. 12340001", "REGULAR SAVINGS Account No. 12340001 Joint")
             for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert {t["account"] for t in out["transactions"]} == {"5678", "0009"}
    assert len(_unread(out)) == 4  # the savings account's opening line and its three rows
    assert not {label for _, label in _failed(results) if "5678" in label}


# A row whose date runs into its text is reported, never passed over.
def test_a_row_whose_date_runs_into_its_text_is_reported_not_read(dump_pages):
    pages = [page.replace("12/02 Check 1001", "12/02Check 1001") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert _unread(out) == ["12/02Check 1001 150.00 1,050.00"]
    assert ("balance", "FREE CHECKING Account No. 5678") in _failed(results)


# A row dated outside the statement's period is reported, not moved into
# another year.
def test_a_row_dated_outside_the_period_is_reported_not_read(dump_pages):
    pages = [page.replace("12/15 POS Purchase", "11/15 POS Purchase") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert _unread(out) == ["11/15 POS Purchase SAMPLE GROCERY 96.30 2,453.70"]
    assert ("balance", "FREE CHECKING Account No. 5678") in _failed(results)
    # The row after it goes on from its balance.
    assert [t["amount"] for t in out["transactions"] if t["description"] == "Check 1002"] == [-700.0]


# A sentence that ends in an account number is not an account's heading,
# so the rows after it stay with their account.
def test_a_sentence_that_ends_in_an_account_number_heads_no_account(dump_pages):
    row = "12/05 ACH Deposit SAMPLE EMPLOYER PAYROLL 2,500.00 3,550.00"
    pages = [page.replace(row, row + "\nDirect deposits use Account No. 12345678") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert len(out["transactions"]) == 11 and _failed(results) == set()


# A statement's rows take its end date's year, December's on a statement
# ending in January the year before.
def test_a_december_row_on_a_january_statement_is_the_year_before(dump_pages):
    pages = [page.replace("End Date: 12/31/2026", "End Date: 01/31/2027").replace("12/31/2026", "01/31/2027")
             .replace("12/31 Credit Dividend 0.03", "01/02 Credit Dividend 0.03") for page in dump_pages(DEMO)]
    out, _ = _parse(pages)
    assert out["statementDate"] == "2027-01-31"
    dates = {t["date"] for t in out["transactions"] if t["account"] == "0009"}
    assert dates == {"2026-12-15", "2027-01-02"}


# Without its End Date a statement has no date to read rows by: the parse
# fails, naming the field.
def test_a_statement_with_no_end_date_says_so(dump_pages):
    pages = [page.replace("End Date: 12/31/2026", "") for page in dump_pages(DEMO)]
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        keypoint_credit_union.parse(pages, "unused.pdf")
    assert raised.value.missing_fields == ("endDate",)
