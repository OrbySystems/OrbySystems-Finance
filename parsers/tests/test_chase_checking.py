"""Chase checking and savings statement (chase_checking); the Chase card
statement is chase_credit_card's (test_bank_pdf.py).

The demo statement is generated from invented data by
tests/generators/gen-chase-checking-sample.py. The page texts in the unit
tests below are its pages, changed: their shapes follow the statement's
layout, their names and figures come from no statement.
"""

from __future__ import annotations

import pytest

import parser_common
import statement_checks
from institutions import chase_checking, chase_credit_card

DEMO = "chase-checking-synthetic-sample.pdf"
# The same statement with a marker read run into the first page's last row,
# its date's first digit among the marker's letters (the generator's
# MARKER_RUN_IN_OUT).
MARKER_RUN_IN = "chase-checking-marker-run-in-synthetic-sample.pdf"
RUN_IN_ROW = "*end*transact1iondetail 0/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10"


def _parse(pages: list[str]):
    out = chase_checking.parse(pages, "unused.pdf", None)
    parser_common.validate_parse_result(out, "chase_checking")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    return out, results


def _failed(results) -> set[tuple[str, str]]:
    return {(r["kind"], r["label"]) for r in results if not r["ok"]}


def _unread(out) -> list[str]:
    return [line["text"] for c in out["checks"] if c["kind"] == "unread" for line in c["lines"]]


# Every account reads, each row signed as printed, and every check the
# statement's figures give holds.
def test_demo_statement(run_statement):
    stmt = run_statement(DEMO, "--expected-parser", "chase_checking.py")
    assert (stmt.institution, stmt.statement_date) == ("Chase", "2026-10-31")
    assert stmt.raw["parser"] == {"id": "chase_checking", "tier": "verified", "bundled": True}
    by_account: dict[tuple[str, str], list[float]] = {}
    for t in stmt.transactions:
        by_account.setdefault((t["account"], t["accountType"]), []).append(t["amount"])
    assert by_account == {
        # Its heading prints no number: the balance summary's row has it.
        ("4567", "Checking"): [-54.9, 2500.0, -1000.0, -100.0, -500.0],
        ("4321", "Savings"): [1000.0, -600.0, 1.25],
    }
    descriptions = [t["description"] for t in stmt.transactions]
    # An outgoing transfer's own date is dropped; the line under a row
    # continues it, but the next page's top does not.
    assert "Online Payment 2222222222 To Sample Utility Transaction#: 3333333333 Reference#: 4444444444" in descriptions
    assert not any("Primary Account" in d or "through" in d or "*end*" in d for d in descriptions)
    results = stmt.raw["checkResults"]
    assert len(results) == 8 and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


# Claimed by the bank's name and its deposit layout; a Chase card statement
# stays chase_credit_card's, and this one is not that parser's.
def test_detect_tells_the_deposit_statement_from_the_card_statement(dump_pages):
    head = "\n".join(dump_pages(DEMO))
    assert chase_checking.detect(head)[0] is True
    assert chase_credit_card.detect(head)[0] is False
    assert chase_checking.detect(head.replace("JPMorgan Chase Bank", "Sample Bank").replace("Chase.com", "sample.com"))[0] is False
    card = "\n".join(dump_pages("chase-synthetic-sample.pdf"))
    assert chase_checking.detect(card)[0] is False and chase_credit_card.detect(card)[0] is True


# A sample made under the name "Chase" fakes "JPMorgan" in the bank's name:
# the web site the statement prints still names the bank. Without either
# the layout alone claims nothing.
def test_a_statement_whose_bank_name_was_faked_is_claimed_by_the_web_site(dump_pages):
    pages = [page.replace("JPMorgan Chase Bank", "Sampleton Chase Bank") for page in dump_pages(DEMO)]
    assert "JPMorgan" not in "\n".join(pages) and "Chase.com" in "\n".join(pages)
    assert chase_checking.detect("\n".join(pages))[0] is True
    out, results = _parse(pages)
    assert len(out["transactions"]) == 8 and _failed(results) == set()
    assert chase_checking.detect("\n".join(pages).replace("Chase.com", "Sampleton.com"))[0] is False


# A marker read run into a row, its date's first digit among the marker's
# letters, is not part of the row: the row reads, its date whole again, and
# every check holds, as on the statement without it.
def test_a_marker_run_into_a_row_is_read_without_it(run_statement, dump_pages):
    assert RUN_IN_ROW in dump_pages(MARKER_RUN_IN)[0].splitlines()
    stmt = run_statement(MARKER_RUN_IN, "--expected-parser", "chase_checking.py")
    demo = run_statement(DEMO, "--expected-parser", "chase_checking.py")
    assert stmt.transactions == demo.transactions
    assert {"date": "2026-10-15", "description": "ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234",
            "amount": -100.0} in [{k: t[k] for k in ("date", "description", "amount")} for t in stmt.transactions]
    results = stmt.raw["checkResults"]
    assert len(results) == 8 and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


# The marker's words run together or not, with a digit of the date among
# them or beside it, the row reads the same.
@pytest.mark.parametrize("run_in", [
    "*end*transact1ion detail 0/15",
    "*end*transaction detail 10/15",
    "*end*transactiondetail10/15",
    "*end*t1ransactiondetail 0/15",
])
def test_a_marker_run_into_a_row_reads_in_either_form(dump_pages, run_in):
    pages = [page.replace(RUN_IN_ROW.split(" ATM")[0], run_in) for page in dump_pages(MARKER_RUN_IN)]
    assert any(line.startswith(run_in) for line in pages[0].splitlines())
    out, results = _parse(pages)
    assert out["transactions"] == _parse(dump_pages(DEMO))[0]["transactions"]
    assert _failed(results) == set()


# A row a marker took more of the date from than one digit, or a row whose
# date is not at its start at all, is reported: never passed over as the
# end of the row above it.
@pytest.mark.parametrize("row", [
    "*end*transact1ion0detail /15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10",
    "ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10",
])
def test_a_row_whose_date_did_not_read_is_reported_not_read(dump_pages, row):
    pages = [page.replace(RUN_IN_ROW, row) for page in dump_pages(MARKER_RUN_IN)]
    out, results = _parse(pages)
    assert _unread(out) == [row]
    assert ("balance", "Checking 4567") in _failed(results)


# A marker's digit put back before a date that then isn't the period's: the
# line is reported as printed, as any row dated outside the period.
def test_a_marker_run_in_date_outside_the_period_is_reported_as_printed(dump_pages):
    row = RUN_IN_ROW.replace("transact1ion", "transact2ion")
    pages = [page.replace(RUN_IN_ROW, row) for page in dump_pages(MARKER_RUN_IN)]
    out, results = _parse(pages)
    assert _unread(out) == [row]
    assert ("balance", "Checking 4567") in _failed(results)


# A statement's labels can run their words together in its text; read either
# way, the statement reads the same.
def test_labels_with_their_words_run_together_read_the_same(dump_pages):
    pages = dump_pages(DEMO)
    joined = [page.replace("CHECKING SUMMARY", "CHECKINGSUMMARY").replace("SAVINGS SUMMARY", "SAVINGSSUMMARY")
              .replace("TRANSACTION DETAIL", "TRANSACTIONDETAIL").replace(" (continued)", "(continued)")
              .replace("DATE DESCRIPTION AMOUNT BALANCE", "DATEDESCRIPTIONAMOUNTBALANCE")
              .replace("Beginning Balance", "BeginningBalance").replace("Ending Balance", "EndingBalance")
              .replace("Account Number:", "AccountNumber:").replace(" through ", "through")
              .replace("October 01, 2026", "Statement periodOctober 01, 2026")
              for page in pages]
    assert joined != pages
    assert chase_checking.detect("\n".join(joined))[0] is True
    out, results = _parse(joined)
    assert out["transactions"] == _parse(pages)[0]["transactions"]
    assert _failed(results) == set()


# A row's description never runs on into the next page's top, even with no
# footer under it or period over it.
def test_a_description_stops_at_the_page_break(dump_pages):
    first, second = dump_pages(DEMO)
    pages = [first.replace("Page 1 of 2", ""), second.replace("October 01, 2026 through October 31, 2026\n", "", 1)]
    assert pages[1].startswith("Primary Account")
    out, results = _parse(pages)
    assert not any("Primary Account" in t["description"] for t in out["transactions"])
    assert _failed(results) == set()


# A line a Chase marker ran into ends the row above it, as the marker alone
# does: its text never continues the row's description.
def test_a_line_a_marker_ran_into_ends_the_row_above(dump_pages):
    row = "10/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10"
    pages = [page.replace(row, row + "\n*end*transaction detailIMPORTANT NOTICE ABOUT FEES") for page in dump_pages(DEMO)]
    assert pages != dump_pages(DEMO)
    out, results = _parse(pages)
    assert "ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234" in [t["description"] for t in out["transactions"]]
    assert _failed(results) == set()


# A summary that prints how many of each kind there were, and their total
# on its Ending Balance, reads the same.
def test_a_summary_with_counts_reads_the_same(dump_pages):
    first, second = dump_pages(DEMO)
    first = (first.replace("Deposits and Additions 2,500.00", "Deposits and Additions 1 2,500.00")
             .replace("Electronic Withdrawals -1,500.00", "Electronic Withdrawals 2 -1,500.00")
             .replace("Ending Balance $2,045.10", "Ending Balance 5 $2,045.10", 1))
    assert "Ending Balance 5 $2,045.10" in first
    out, results = _parse([first, second])
    assert len(out["transactions"]) == 8 and _failed(results) == set()


# An account number printed in another account's rows is that row's, never
# the next account's: one whose heading prints none takes its number from
# the balance summary.
def test_an_account_number_in_a_row_is_not_the_next_accounts(dump_pages):
    pages = [page.replace("Transaction#: 3333333333 Reference#: 4444444444", "To Acct Account Number: 000000009999999")
             .replace("PAT EXAMPLE Account Number: 000000007654321", "PAT EXAMPLE Account Number:") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert {t["account"] for t in out["transactions"] if t["accountType"] == "Savings"} == {"4321"}
    assert any(t["description"].endswith("To Acct Account Number: 000000009999999") for t in out["transactions"])
    assert _failed(results) == set()


# A number one account's heading prints is never another account's, even
# when the balance summary's balances would match.
def test_an_account_never_borrows_a_number_another_account_printed(dump_pages):
    pages = [page.replace("Chase Total Checking 000000001234567 $1,200.00 $2,045.10\n", "")
             .replace("Chase Savings 000000007654321 5,000.00 5,401.25", "Chase Savings 000000007654321 $1,200.00 $2,045.10")
             for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert {t["account"] for t in out["transactions"] if t["accountType"] == "Checking"} == {""}
    assert {t["account"] for t in out["transactions"] if t["accountType"] == "Savings"} == {"4321"}
    # Without its number the account is told apart by its place.
    assert ("balance", "Checking (account 1)") not in _failed(results)
    assert "Checking (account 1)" in {c["label"] for c in out["checks"]}


# A summary whose Ending Balance did not read ends at the transaction detail:
# the account's rows are reported, and the detail is not read as more of its
# summary.
def test_a_summary_whose_ending_balance_did_not_read_reports_its_rows(dump_pages):
    first, second = dump_pages(DEMO)
    first = first.replace("Ending Balance $2,045.10", "Ending Balance (see below)", 1)
    out, _ = _parse([first, second])
    assert len(_unread(out)) == 5
    assert not [c for c in out["checks"] if c["label"].startswith("Checking")]


# A transaction detail whose summary heading did not read is reported, never
# joined to the account before it.
def test_an_account_whose_summary_heading_did_not_read_is_reported_not_read(dump_pages):
    pages = [page.replace("SAVINGS SUMMARY", "SAVINGS ACCOUNT SUMMARY") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert {t["account"] for t in out["transactions"]} == {"4567"}
    assert len(_unread(out)) == 3
    assert not {label for _, label in _failed(results) if "4567" in label}


# A row whose printed balance doesn't follow from the one before it fails the
# running check, though every total holds.
def test_a_balance_that_does_not_follow_fails_the_running_check(dump_pages):
    pages = [page.replace("-54.90 1,145.10", "-54.90 1,999.10") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert _failed(results) == {("running", "Checking 4567")}


# A money market account's summary heading, with its words run together or
# not, names its type.
@pytest.mark.parametrize("heading", ["MONEY MARKET SUMMARY", "MONEYMARKETSUMMARY"])
def test_a_money_market_summary_names_its_type(dump_pages, heading):
    pages = [page.replace("SAVINGS SUMMARY", heading) for page in dump_pages(DEMO)]
    out, _ = _parse(pages)
    assert {t["accountType"] for t in out["transactions"] if t["account"] == "4321"} == {"Money Market"}


# A description line with "through" in it continues the row; only the period
# printed at a page's top is page furniture.
def test_a_description_line_with_through_in_it_continues_the_row(dump_pages):
    pages = [page.replace("Transaction#: 3333333333 Reference#: 4444444444", "Paid through Sample Pay Reference#: 4444444444")
             for page in dump_pages(DEMO)]
    out, _ = _parse(pages)
    assert "Online Payment 2222222222 To Sample Utility Paid through Sample Pay Reference#: 4444444444" in {
        t["description"] for t in out["transactions"]}


# An account whose number is printed nowhere is left for the app to ask,
# never guessed.
def test_an_account_number_printed_nowhere_is_left_empty(dump_pages):
    pages = [page.replace("Chase Total Checking 000000001234567 $1,200.00 $2,045.10\n", "") for page in dump_pages(DEMO)]
    assert pages != dump_pages(DEMO)
    out, results = _parse(pages)
    assert {t["account"] for t in out["transactions"] if t["accountType"] == "Checking"} == {""}
    assert _failed(results) == set()


# A dated line in the detail that is not a row is reported, and the
# account's checks fail.
def test_a_dated_line_that_is_not_a_row_is_reported_not_read(dump_pages):
    row = "10/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00 2,545.10"
    pages = [page.replace(row, "10/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00")
             for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert _unread(out) == ["10/15 ATM Withdrawal 10/15 100 Sample St Sample City CA Card 1234 -100.00"]
    assert ("balance", "Checking 4567") in _failed(results)


# A row dated outside the statement's period is reported, not moved into
# another year.
def test_a_row_dated_outside_the_period_is_reported_not_read(dump_pages):
    pages = [page.replace("10/05 Payroll Deposit", "09/05 Payroll Deposit") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert _unread(out) == ["09/05 Payroll Deposit SAMPLE EMPLOYER PPD ID: 0000000000 2,500.00 3,645.10"]
    assert ("balance", "Checking 4567") in _failed(results)


# A dated line ending in an amount outside every transaction detail is a row
# of a part this parser doesn't know: reported, a marker run into it or not.
@pytest.mark.parametrize("marker", ["", "*end*summar1y 0/12"])
def test_a_row_outside_the_transaction_detail_is_reported_not_read(dump_pages, marker):
    stray = "10/12 Overdraft Fee Refund 25.00"
    printed = (marker + stray[len("10/12"):]) if marker else stray
    pages = [page.replace("JPMorgan Chase Bank, N.A. Member FDIC", printed + "\nJPMorgan Chase Bank, N.A. Member FDIC")
             for page in dump_pages(DEMO)]
    out, _ = _parse(pages)
    assert _unread(out) == [printed]


# A statement's rows take its end date's year, December's on a statement
# ending in January the year before.
def test_a_december_row_on_a_january_statement_is_the_year_before(dump_pages):
    pages = [page.replace("October 01, 2026 through October 31, 2026", "December 01, 2026 through January 02, 2027")
             .replace("10/31 Interest Payment", "01/02 Interest Payment").replace("10/", "12/") for page in dump_pages(DEMO)]
    out, results = _parse(pages)
    assert out["statementDate"] == "2027-01-02"
    assert {t["date"][:4] for t in out["transactions"] if t["description"] == "Interest Payment"} == {"2027"}
    assert {t["date"][:4] for t in out["transactions"] if t["description"] != "Interest Payment"} == {"2026"}
    assert _failed(results) == set()


# Without its period a statement has no date to read rows by: the parse
# fails, naming the field.
def test_a_statement_with_no_period_says_so(dump_pages):
    pages = [page.replace("October 01, 2026 through October 31, 2026", "") for page in dump_pages(DEMO)]
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        chase_checking.parse(pages, "unused.pdf")
    assert raised.value.missing_fields == ("statementPeriod",)
