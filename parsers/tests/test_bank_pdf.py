"""Bank / credit-card statement PDF parsers, ported from
pkg/ingest/statement_test.go's TestExtractStatement* cases. Every fixture
here is a committed or on-demand-generated synthetic PDF, so this is the
portable regression net that runs everywhere.
"""

import json
import subprocess
import sys

import pytest

import parser_common
import statement_checks
from conftest import FIXTURES, SCRIPTS, approx
from institutions import citi_credit_card, citi_credit_card_family, star_one_credit_union, technology_credit_union


def _running_balance(txns, opening):
    running = opening
    for i, t in enumerate(txns):
        running += t["amount"]
        assert t["balance"] is not None, f"txn {i} ({t['description']}): balance is nil"
        assert approx(t["balance"], running), (
            f"txn {i} ({t['description']}): balance {t['balance']:.2f}, want {running:.2f}"
        )
    return running


def test_wells_fargo_synthetic(run_statement):
    stmt = run_statement("wells-fargo-synthetic-sample.pdf")
    assert stmt.institution == "Wells Fargo"
    assert stmt.first_account == "7890"
    assert stmt.first_account_type == "Checking"
    assert stmt.statement_date == "2025-03-31"
    assert len(stmt.transactions) == 14

    deposits = sum(t["amount"] for t in stmt.transactions if t["amount"] > 0)
    withdrawals = -sum(t["amount"] for t in stmt.transactions if t["amount"] <= 0)
    assert approx(deposits, 8550.42)
    assert approx(withdrawals, 5296.45)

    closing = _running_balance(stmt.transactions, 5000.00)
    assert approx(closing, 8253.97)

    want = [
        (0, "2025-03-01", "Zelle From Alex Rivera", 1200.00),
        (1, "2025-03-01", "Zelle to Jamie Lee", -85.50),
        (3, "2025-03-03", "Northwind Traders Payables", 2500.00),
        (4, "2025-03-05", "Acme Corp Payroll", 3000.00),
        (5, "2025-03-05", "Acme Corp Reversal", -3000.00),
        (7, "2025-03-08", "Check 101", -250.00),
        (9, "2025-03-12", "Deposited OR Cashed Check 102", -1000.00),
        (10, "2025-03-20", "Instant Pmt From Stp", 1850.00),
        (13, "2025-03-31", "Interest Payment", 0.42),
    ]
    for idx, date, desc, amount in want:
        t = stmt.transactions[idx]
        assert t["date"] == date
        assert t["description"].startswith(desc), (idx, t["description"], desc)
        assert approx(t["amount"], amount), (idx, t["amount"], amount)

    assert "Rent Share For March" in stmt.transactions[0]["description"]
    assert stmt.transactions[0].get("reference") == "Ab12Cd34Ef56"


def test_chase_synthetic(run_statement):
    stmt = run_statement("chase-synthetic-sample.pdf")
    assert stmt.institution == "Chase"
    assert stmt.first_account == "8899"
    assert stmt.first_account_type == "Credit Card"
    assert stmt.statement_date == "2026-01-22"
    assert len(stmt.transactions) == 10

    closing = _running_balance(stmt.transactions, -1200.00)
    assert approx(closing, -827.01)

    want = [
        (0, "2025-12-28", "Payment Thank You Bill Pay Service", 1500.00),
        (1, "2026-01-05", "RIVERSIDE OUTFITTERS REFUND", 45.00),
        (2, "2025-12-24", "COFFEE HOUSE 12", -18.75),
        (3, "2025-12-26", "FAKE AIR", -842.10),
        (4, "2025-12-31", "GROCERY MART #221", -96.43),
        (8, "2026-01-20", "DINER ON MAIN", -41.05),
        (9, "2026-01-21", "EBOOK STORE*4Q7XR", -0.99),
    ]
    for idx, date, desc, amount in want:
        t = stmt.transactions[idx]
        assert t["date"] == date
        assert t["description"].startswith(desc), (idx, t["description"], desc)
        assert approx(t["amount"], amount), (idx, t["amount"], amount)

    assert "ORD LHR" in stmt.transactions[3]["description"]
    foreign = stmt.transactions[6]["description"]
    assert "POUND STERLING" in foreign and "EXCHG RATE" in foreign


def test_citi_costco_synthetic(run_statement):
    stmt = run_statement(
        "citi-costco-synthetic-sample.pdf",
        "--expected-parser",
        "citi_credit_card.py",
    )
    assert stmt.institution == "Citi"
    assert stmt.first_account == "4455"
    assert stmt.first_account_type == "Credit Card"
    assert stmt.statement_date == "2026-09-14"
    assert len(stmt.transactions) == 6

    # In date order, so the latest row carries the New balance.
    assert [t["date"] for t in stmt.transactions] == sorted(t["date"] for t in stmt.transactions)
    closing = _running_balance(stmt.transactions, -300.00)
    assert approx(closing, -385.00)
    assert stmt.raw["checkResults"] and all(c["ok"] for c in stmt.raw["checkResults"])

    payment = next(t for t in stmt.transactions if t["description"].startswith("AUTOPAY"))
    assert payment["date"] == "2026-09-10"
    assert approx(payment["amount"], 300.00)
    credit = next(t for t in stmt.transactions if t["date"] == "2026-09-11")
    assert approx(credit["amount"], 25.00)
    purchase = stmt.transactions[0]
    assert purchase["date"] == "2026-08-21"
    assert approx(purchase["amount"], -45.00)


def test_citi_costco_with_labels_too_small_to_measure(run_statement):
    # Citi's November 2025 layout: labels pdfminer measures at a quarter of
    # a point, beside ordinary values. Read by their tops, the billing
    # period's dates joined the account line over them, letter by letter,
    # and nothing read. Read in a subprocess: test_bofa_checking_unit.py
    # stubs pdfplumber in this one.
    script = (
        "import json, sys, pdfplumber, parser_common\n"
        "with pdfplumber.open(sys.argv[1]) as pdf:\n"
        "    page = pdf.pages[0]\n"
        "    print(json.dumps([(page.extract_text(x_tolerance_ratio=parser_common.SPACE_GAP_EM) or '').splitlines(),\n"
        "                      parser_common.page_text(page).splitlines()]))\n"
    )
    out = subprocess.run([sys.executable, "-c", script, str(FIXTURES / "citi-costco-small-labels-synthetic-sample.pdf")],
                         cwd=SCRIPTS, capture_output=True, text=True, check=True).stdout
    by_tops, lines = json.loads(out)
    assert "Billing Period:" in by_tops and not any("08/15/26-09/14/26" in line for line in by_tops)
    assert lines[1:3] == ["Account number ending in: 4455", "Billing Period: 08/15/26-09/14/26"]

    stmt = run_statement("citi-costco-small-labels-synthetic-sample.pdf", "--expected-parser", "citi_credit_card.py")
    assert (stmt.statement_date, stmt.first_account, len(stmt.transactions)) == ("2026-09-14", "4455", 6)
    assert stmt.raw["checkResults"] and all(c["ok"] for c in stmt.raw["checkResults"])


def test_citi_reads_a_row_that_runs_into_the_column_beside_it(dump_pages):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    beside = [page.replace(row, row + " Costco Cash Back Rewards Summary") for page in pages]
    out = citi_credit_card.parse(beside, "unused.pdf")
    assert len(out["transactions"]) == 6 and not [c for c in out["checks"] if c["kind"] == "unread"]

    # A line of the rewards summary's ledger: its figure, after a dot leader
    # and signed "+", is never a row's amount.
    ledger = [page.replace(row, row + " Gas and EV charging 4% ...... +$5.00") for page in pages]
    out = citi_credit_card.parse(ledger, "unused.pdf")
    assert len(out["transactions"]) == 6 and not [c for c in out["checks"] if c["kind"] == "unread"]
    assert -250.00 in [t["amount"] for t in out["transactions"]]
    # Nothing in the ledger line is shaped like an amount, so a figure in
    # the description is never taken for the row's amount.
    figured = [page.replace(row, "09/04 09/04 COSTCO WHSE #0100 SAMPLE 12.50 CITY CA 250.00 and EV charging ...... +$0.60")
               for page in pages]
    out = citi_credit_card.parse(figured, "unused.pdf")
    assert -250.00 in [t["amount"] for t in out["transactions"]] and -12.50 not in [t["amount"] for t in out["transactions"]]

    # A figure beside it in any other form: the row is read by its own
    # amount, the first on its line, when every check it is in holds...
    figure = [page.replace(row, row + " Total Earned: +$5.00") for page in pages]
    out = citi_credit_card.parse(figure, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6 and all(r["ok"] for r in results)
    assert -250.00 in [t["amount"] for t in out["transactions"]]
    # ... and held for review, as not read, when one doesn't.
    unconfirmed = [page.replace("Previous balance $300.00", "Previous balance $310.00") for page in figure]
    out = citi_credit_card.parse(unconfirmed, "unused.pdf")
    assert len(out["transactions"]) == 5
    assert [[line["text"] for line in c["lines"]] for c in out["checks"] if c["kind"] == "unread"] == [
        [row + " Total Earned: +$5.00"]]


def test_citi_costco_reads_the_table_beside_its_rewards_summary(run_statement, dump_pages):
    # A Costco card prints its rewards summary in a column beside the
    # transaction table, and the text reads a row, or a section's heading,
    # and the column's line level with it as one line, a line of the
    # summary's ledger and its figure among them. Until 27 Oct 2026 such a
    # row was left unread and its heading missed, so a purchase heading
    # missed put the purchases with the payments.
    lines = [line for page in dump_pages("citi-costco-rewards-column-synthetic-sample.pdf") for line in page.splitlines()]
    assert "08/24 08/24 SAMPLE EV CHARGING CA $15.00 and EV charging ........... +$0.60" in lines
    assert "09/10 AUTOPAY 260807000000000RAUTOPAY AUTO-PMT -$300.00 last statement ............ +$12.40" in lines
    assert "Standard Purchases Earned this period ........ +$8.10" in lines
    assert "purchases ............ +$5.70" in lines  # the ledger's own line: no heading
    stmt = run_statement("citi-costco-rewards-column-synthetic-sample.pdf", "--expected-parser", "citi_credit_card.py")
    assert len(stmt.transactions) == 6
    assert sorted(t["amount"] for t in stmt.transactions) == [-250.0, -100.0, -45.0, -15.0, 25.0, 300.0]
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    assert "unread" not in {r["kind"] for r in results}


@pytest.mark.parametrize("ledger", ["Earned this period ...... +$8.10", "1% on all other purchases ...... +$2.10"])
def test_citi_reads_a_purchases_heading_beside_a_ledger_line(dump_pages, ledger):
    # Missed, the heading leaves the purchases under Payments, Credits and
    # Adjustments, and both of the Account Summary's checks fail.
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    merged = [page.replace("Standard Purchases", "Standard Purchases " + ledger) for page in pages]
    assert merged != pages
    out = citi_credit_card.parse(merged, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6 and all(r["ok"] for r in results)


_CITI_THREE_PAGE = "citi-costco-three-page{}-synthetic-sample.pdf"


def _citi_unread(results) -> list[tuple[int, int, str]]:
    return [(line["page"], line["line"], line["text"]) for r in results if r["kind"] == "unread" for line in r["lines"]]


def test_citi_costco_reads_an_autopay_beside_a_year(run_statement, dump_pages):
    # A two-card statement whose autopay row runs on into the rewards
    # column's "Your 2026 reward will follow". Revision 5 allowed no figure
    # there, so the payment was not read: a tester's statement, its
    # diagnostic giving this line's shape at page 3, line 17.
    lines = dump_pages(_CITI_THREE_PAGE.format(""))[2].splitlines()
    assert statement_checks.shape(lines[16]) == (
        "99/99 AAAAAAA 999999999999999AAAAAAAA AAAA-AAA -$999.99 Aaaa 9999 aaaaaa aaaa aaaaaa")
    stmt = run_statement(_CITI_THREE_PAGE.format(""), "--expected-parser", "citi_credit_card.py")
    assert len(stmt.transactions) == 6 and 300.0 in [t["amount"] for t in stmt.transactions]
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


@pytest.mark.parametrize("variant", ["-amount-beside", "-first-row-beside"])
def test_citi_never_takes_a_rows_amount_from_the_column_beside_it(run_statement, variant):
    # A purchase runs on into the rewards column's "Year to Date : $31.40":
    # the authorized user's row, or - a tester's statement - the primary
    # cardholder's first. Until revision 6 the row read as $31.40 and the
    # purchases check failed with nothing to show why; revision 6 held it for
    # review; it is read by its own amount, every check holding.
    stmt = run_statement(_CITI_THREE_PAGE.format(variant), "--expected-parser", "citi_credit_card.py")
    amounts = [t["amount"] for t in stmt.transactions]
    assert -31.40 not in amounts and len(amounts) == 6
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


def test_citi_suggests_a_held_rows_own_amount_for_review(dump_pages):
    # Held for review when a check over it fails, the purchase run on into
    # "Year to Date : $31.40" is suggested at its own amount, which accounts
    # for the purchases it leaves out. Until 28 Oct 2026 the suggestion was
    # the column's $31.40 and explained nothing.
    pages = [page.replace("Previous balance $300.00", "Previous balance $310.00")
             for page in dump_pages(_CITI_THREE_PAGE.format("-amount-beside"))]
    out = citi_credit_card.parse(pages, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert [(line["text"], line["suggested"]["amount"]) for r in results if r["kind"] == "unread" for line in r["lines"]] == [
        ("09/06 09/06 COSTCO GAS #0100 SAMPLE CITY CA $25.00 Year to Date : $31.40", -25.0)]
    purchases = [r for r in results if r["label"] == "Account Summary: purchases, cash advances, fees and interest"]
    assert [r["explanation"]["kind"] for r in purchases] == ["missing-lines"]


def test_citi_reads_a_charge_printed_without_a_date(run_statement, dump_pages):
    # An interest charge with no date is read by its own amount, dated the
    # closing date, when its section's total - level with column text, read
    # since revision 6 - and the summary's checks confirm it...
    stmt = run_statement(_CITI_THREE_PAGE.format("-undated-interest"), "--expected-parser", "citi_credit_card.py")
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    charge = [t for t in stmt.transactions if t["description"] == "INTEREST CHARGED TO STANDARD PURCH"]
    assert [(t["date"], t["amount"]) for t in charge] == [("2026-09-14", -4.20)]
    # ... and held for review, as not read, when they don't.
    pages = [page.replace("TOTAL INTEREST FOR THIS PERIOD $4.20", "TOTAL INTEREST FOR THIS PERIOD $5.20")
             for page in dump_pages(_CITI_THREE_PAGE.format("-undated-interest"))]
    out = citi_credit_card.parse(pages, "unused.pdf")
    assert [line["text"] for c in out["checks"] if c["kind"] == "unread" for line in c["lines"]] == [
        "INTEREST CHARGED TO STANDARD PURCH $4.20"]


def test_citi_reads_a_row_beside_a_ledger_line_signed_minus(dump_pages):
    # The rewards ledger prints a certificate's amount signed "-" ("reward
    # certificate amount ...... -$12.40"): beside a row it is no figure of
    # the row's, and in the fees section no charge, which revision 6 took
    # it for.
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    ledger = "certificate amount ...... -$15.00"
    changed = [page.replace(row, row + " " + ledger).replace("Fees Charged", "Fees Charged\n" + ledger) for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6 and all(r["ok"] for r in results)
    assert not [c for c in out["checks"] if c["kind"] == "unread"]
    # Read outright, as the ledger's other lines are: a check failing for
    # another reason doesn't hold the row for review.
    off = [page.replace("Previous balance $300.00", "Previous balance $310.00") for page in changed]
    out = citi_credit_card.parse(off, "unused.pdf")
    assert len(out["transactions"]) == 6 and not [c for c in out["checks"] if c["kind"] == "unread"]


def test_citi_reads_a_credits_heading_beside_a_column_figure(run_statement, dump_pages):
    # The authorized user's Payments, Credits and Adjustments heading level
    # with "Year to Date : $31.40" is a heading, printed in title case as
    # Citi prints its headings: its return is a credit. Until revision 8 the
    # heading was missed and the return read with the purchases.
    stmt = run_statement(_CITI_THREE_PAGE.format("-credits-beside"), "--expected-parser", "citi_credit_card.py")
    assert 20.0 in [t["amount"] for t in stmt.transactions]
    results = stmt.raw["checkResults"]
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    # The same words in capitals, as a charge prints them, head nothing.
    pages = [page.replace("Payments, Credits and Adjustments Year to Date : $31.40",
                          "PAYMENTS, CREDITS AND ADJUSTMENTS Year to Date : $31.40")
             for page in dump_pages(_CITI_THREE_PAGE.format("-credits-beside"))]
    out = citi_credit_card.parse(pages, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert not all(r["ok"] for r in results)


@pytest.mark.parametrize("beside", ["Your 2026 reward will follow", "4% on eligible gas", "12 visits this year"])
def test_citi_reads_a_row_beside_figures_that_are_not_money(dump_pages, beside):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    changed = [page.replace(row, row + " " + beside) for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6 and all(r["ok"] for r in results)


@pytest.mark.parametrize("column", ["Your 2026 reward will follow", "Year to Date : $31.40"])
def test_citi_reads_a_header_heading_and_total_beside_column_text(dump_pages, column):
    # The table's header, a heading and a section's total level with column
    # text, a "$" figure of its own in it or not, all read. The fees total,
    # $1.50 with no fee rows, fails its check alone: the heading read, the
    # purchases are in their own section and the summary's checks hold.
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    changed = [page.replace("Sale Post", "Sale Post " + column)
               .replace("Standard Purchases", "Standard Purchases " + column)
               .replace("TOTAL FEES FOR THIS PERIOD $0.00", "TOTAL FEES FOR THIS PERIOD $1.50 " + column)
               for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6
    assert {r["label"] for r in results if not r["ok"]} == {"Fees Charged"}


@pytest.mark.parametrize("stray", ["09/12 09/12 SAMPLE STORE CITY CA $9.00 Your 2026 reward will follow",
                                   "09/12 09/12 SAMPLE STORE CITY CA $9.00 Year to Date : $31.40 so far"])
def test_citi_reports_a_row_outside_the_table_that_runs_into_column_text(dump_pages, stray):
    # A row outside the table is reported, whatever the column beside it ran
    # on into it.
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    changed = [page.replace("Interest charge calculation", "Interest charge calculation\n" + stray) for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    assert [line["text"] for c in out["checks"] if c["kind"] == "unread" for line in c["lines"]] == [stray]


# A tentative reading no check covers is confirmed by nothing: when the
# summary doesn't read, the row is held for review, never kept.
def test_citi_holds_a_tentative_reading_no_check_covers(dump_pages):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    held = "09/04 09/04 COSTCO WHSE #0100 SAMPLE $1.00 CITY CA $250.00"
    changed = [page.replace(row, held).replace("Previous balance", "Opening figure").replace("New balance", "Closing figure")
               .replace("Purchases +", "Buys +") for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    assert -1.00 not in [t["amount"] for t in out["transactions"]]
    assert [line["text"] for c in out["checks"] if c["kind"] == "unread" for line in c["lines"]] == [held]


# A figure shaped like money right after a row's amount ("$250.00 5.00
# back") is no text beside it: the row is only a tentative reading, held for
# review when a check over it fails.
def test_citi_holds_a_row_followed_by_a_money_shaped_figure_when_unconfirmed(dump_pages):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    changed = [page.replace(row, row + " 5.00 back").replace("Previous balance $300.00", "Previous balance $310.00")
               for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    assert [line["text"] for c in out["checks"] if c["kind"] == "unread" for line in c["lines"]] == [row + " 5.00 back"]


# A line of the rewards column standing alone in Fees Charged or Interest
# Charged, or level with the Interest Charged heading, is no charge: the
# statement reads clean, a tentative row elsewhere kept.
def test_citi_takes_no_column_line_in_the_fees_sections_for_a_charge(dump_pages):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    changed = [page.replace(row, row + " Total Earned: +$5.00")
               .replace("Fees Charged", "Fees Charged\nYear to Date : $31.40")
               .replace("Interest Charged", "Interest Charged Year to Date : $31.40") for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6 and all(r["ok"] for r in results)
    assert not [c for c in out["checks"] if c["kind"] == "unread"]


# A dated line whose only figure is the column's - after a label's colon or a
# ledger's dot leader - is no row: reported, never read as that figure.
@pytest.mark.parametrize("tail", ["Year to Date : $250.00", "certificate amount ...... -$250.00"])
def test_citi_never_reads_a_column_figure_as_a_rows_amount(dump_pages, tail):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    row = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00"
    line = "09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA " + tail
    out = citi_credit_card.parse([page.replace(row, line) for page in pages], "unused.pdf")
    assert len(out["transactions"]) == 5
    assert [l["text"] for c in out["checks"] if c["kind"] == "unread" for l in c["lines"]] == [line]


# An undated charge level with a line of the rewards ledger is read by its
# own amount, the ledger line left aside, its section's total confirming it.
def test_citi_reads_an_undated_charge_beside_a_ledger_line(dump_pages):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    changed = [page.replace("TOTAL FEES FOR THIS PERIOD $0.00", "LATE FEE $41.00 4% on eligible gas ...... +$1.80\n"
                            "TOTAL FEES FOR THIS PERIOD $41.00").replace("Fees +$0.00", "Fees +$41.00")
               .replace("New balance $385.00", "New balance $426.00") for page in pages]
    out = citi_credit_card.parse(changed, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert all(r["ok"] for r in results), [r for r in results if not r["ok"]]
    assert [(t["description"], t["amount"]) for t in out["transactions"] if t["description"] == "LATE FEE"] == [("LATE FEE", -41.0)]


def test_citi_takes_a_ledger_line_of_its_own_for_no_heading(dump_pages):
    # "purchases ...... +$5.70" ends a ledger line of the rewards summary
    # ("2% on Costco and Costco.com / purchases"); read as the Purchases
    # heading, it would put the payments after it with the purchases. It
    # holds the bound on what runs on from a heading, which revision 4 had
    # by allowing nothing.
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    heading = "Payments, Credits and Adjustments"
    stray = [page.replace(heading, heading + "\npurchases ...... +$5.70") for page in pages]
    assert stray != pages
    out = citi_credit_card.parse(stray, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 6 and all(r["ok"] for r in results)


def test_citi_costco_holds_changed_activity_for_review(dump_pages):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    broken = [page.replace("$250.00", "$251.00") for page in pages]
    out = citi_credit_card.parse(broken, "unused.pdf")
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]},
                                        out["statementDate"])
    assert {r["label"] for r in results if not r["ok"]} == {
        "Account Summary", "Account Summary: purchases, cash advances, fees and interest"}


_CITI_PERIOD_LINE = "Billing Period: 08/15/26-09/14/26"


@pytest.mark.parametrize("variant", [
    "Billing\u00a0Period:\u00a008/15/26-09/14/26",  # no-break spaces
    "BillingPeriod:08/15/26-09/14/26",  # words glued, as small type can read
    "Billing Period 08/15/26 - 09/14/26",  # no colon
    "Billing Period: 8/15/26-9/14/26",  # one-digit months
    "Billing Period: 08/15/2026-09/14/2026",
    "Billing Period: 08/15/26\u201309/14/26",  # en dash
    "Billing Period: 08/15/26 \u2014 09/14/26",  # em dash
    "Billing Period: 08/15/26\u221209/14/26",  # minus sign
    "Billing Period: 08/15/26 to 09/14/26",
])
def test_citi_reads_the_billing_period_however_the_text_gives_it(dump_pages, variant):
    pages = dump_pages("citi-costco-synthetic-sample.pdf")
    changed = [page.replace(_CITI_PERIOD_LINE, variant) for page in pages]
    assert changed != pages
    assert citi_credit_card.detect("\n".join(changed))[0] is True
    out = citi_credit_card.parse(changed, "unused.pdf")
    assert out["statementDate"] == "2026-09-14"
    assert out["transactions"] == citi_credit_card.parse(pages, "unused.pdf")["transactions"]


@pytest.mark.parametrize("line", [
    "BillingPeriod:08/15/26-09/14/2630 days",  # a year glued to the next word
    "Billing Period: 08/15/26-09/14/202",
    "Billing Period: 09/14/26-08/15/26",
])
def test_citi_takes_no_billing_period_that_is_not_a_billing_cycle(line):
    assert citi_credit_card._period(line) == (None, None)


def _read_changed_fixture(tmp_path, name: str, *replacements: tuple[str, str]) -> dict:
    """The dispatcher's answer for a committed fixture with some of its text
    changed. Each replacement is the same length as what it replaces, so the
    PDF's byte offsets still hold."""
    data = (FIXTURES / name).read_bytes()
    for old, new in replacements:
        assert len(old) == len(new) and data.count(old.encode()) >= 1
        data = data.replace(old.encode(), new.encode())
    path = tmp_path / name
    path.write_bytes(data)
    proc = subprocess.run([sys.executable, str(SCRIPTS / "bank_statement.py"), str(path), "--strict"],
                          cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_citi_billing_period_with_impossible_dates_says_so(tmp_path):
    out = _read_changed_fixture(tmp_path, "citi-costco-synthetic-sample.pdf",
                                (_CITI_PERIOD_LINE, "Billing Period: 08/15/26-13/14/26"))
    diagnostic = out["diagnostic"]
    assert diagnostic["parserId"] == "citi_credit_card"
    assert diagnostic["supportTier"] == "verified"
    assert diagnostic["missingFields"] == ["billingPeriod"]
    assert diagnostic["signals"] == {"billingPeriodDatesInvalid": True}
    assert "It could not read the statement's Billing Period." in out["error"]
    assert diagnostic["fieldLines"]["billingPeriod"] == {
        "match": "exact", "page": 1, "line": 4,
        "shape": "Aaaaaaa Aaaaaa: 99/99/99-99/99/99", "next": "Aaaaaaa Aaaaaaa"}
    assert len(diagnostic["textStats"]["pageChars"]) == 2
    assert "declinedParsers" not in diagnostic


def test_a_citi_billing_period_no_pattern_reads_is_shown_as_its_shape(tmp_path):
    # Dots for slashes: the label is there, so citi_credit_card claims the
    # statement, reads it again (_read_again: nothing to resize), and fails,
    # showing the line the period was on.
    out = _read_changed_fixture(tmp_path, "citi-costco-synthetic-sample.pdf",
                                (_CITI_PERIOD_LINE, "Billing Period: 08.15.26-09.14.26"),
                                ("SEPTEMBER STATEMENT", "Credit Limit $9,000"))
    diagnostic = out["diagnostic"]
    assert (diagnostic["parserId"], diagnostic["supportTier"]) == ("citi_credit_card", "verified")
    assert "declinedParsers" not in diagnostic
    assert diagnostic["missingFields"] == ["billingPeriod"]
    assert diagnostic["signals"] == {"billingPeriodDatesInvalid": False}
    assert diagnostic["fieldLines"]["billingPeriod"]["shape"] == "Aaaaaaa Aaaaaa: 99.99.99-99.99.99"
    assert diagnostic["fieldLines"]["creditLimit"]["match"] == "exact"
    assert diagnostic["fieldLines"]["paymentDueDate"] == {"match": "missing"}
    assert "It could not read the statement's Billing Period." in out["error"]
    encoded = json.dumps(out)
    for private in ("08.15.26", "4455", "AUTOPAY", "9,000", "$"):
        assert private not in encoded


def test_a_citi_statement_the_verified_parser_turns_down_says_so(tmp_path):
    # No billing period at all: citi_credit_card declines, and
    # citi_credit_card_family, which a credit limit makes claim it, fails.
    out = _read_changed_fixture(tmp_path, "citi-costco-synthetic-sample.pdf",
                                (_CITI_PERIOD_LINE, "Statement Date: 08.15.26-09.14.26"),
                                ("SEPTEMBER STATEMENT", "Credit Limit $9,000"))
    diagnostic = out["diagnostic"]
    assert diagnostic["parserId"] == "citi_credit_card_family"
    assert diagnostic["declinedParsers"] == ["citi_credit_card"]
    assert diagnostic["missingFields"] == ["billingPeriod"]
    assert diagnostic["fieldLines"]["billingPeriod"] == {"match": "missing"}
    assert "It could not read the statement's Billing Period." in out["error"]


def test_citi_reads_a_statement_again_where_an_older_app_misread_its_labels():
    # OrbySystems 1.0.3 reads pages with plain extract_text and nothing
    # resized: the small-labels statement's period is lost to the line
    # above. Delivered to it, citi_credit_card claims the statement and
    # reads it again. Its own copy of the resizing is parser_common's: on
    # every fixture, on microprint, and on a page of mostly larger print.
    # Read in a subprocess: test_bofa_checking_unit.py stubs pdfplumber.
    script = (
        "import json, sys, pdfplumber, parser_common, statement_checks\n"
        "from institutions import citi_credit_card as cc\n"
        "with pdfplumber.open(sys.argv[1]) as pdf:\n"
        "    pages = [p.extract_text() or '' for p in pdf.pages]\n"
        "pages = [p for p in pages if p]\n"
        "import glob, os, tempfile\n"
        "from reportlab.pdfgen import canvas\n"
        "drawn = []\n"
        "def draw(name, *runs):\n"
        "    path = os.path.join(tempfile.mkdtemp(), name); c = canvas.Canvas(path)\n"
        "    for x, y, size, scale, text in runs:\n"
        "        t = c.beginText(x, y); t.setFont('Helvetica', size); t.setHorizScale(scale); t.textOut(text); c.drawText(t)\n"
        "    c.save(); drawn.append(path)\n"
        "draw('microprint.pdf', (72, 700, 9, 100, '09/04 09/04 COSTCO WHSE #0100 SAMPLE CITY CA $250.00'), (150, 700, 0.5, 100, 'ORIGINALDOCUMENT'))\n"
        "draw('larger.pdf', *[(72, 500 - 16 * n, 12, 100, 'Important information about your account') for n in range(12)],\n"
        "     (40, 690.5, 0.24, 1000, 'Billing Period:'), (70, 690.5, 8.5, 100, '08/15/26-09/14/26'))\n"
        "same = True\n"
        "for path in drawn + glob.glob(os.path.join(os.path.dirname(sys.argv[1]), '*.pdf')):\n"
        "    with pdfplumber.open(path) as pdf:\n"
        "        same = same and all(cc._own_resize_unmeasured(p.chars) == parser_common._resize_unmeasured(p.chars) for p in pdf.pages)\n"
        "out = cc.parse(pages, sys.argv[1])\n"
        "results = statement_checks.evaluate(out['checks'], {'cash_transactions': out['transactions']}, out['statementDate'])\n"
        "print(json.dumps([cc.detect('\\n'.join(pages[:2]))[0], bool(cc._PERIOD_RE.search('\\n'.join(pages))), same,\n"
        "                  out['statementDate'], len(out['transactions']), all(r['ok'] for r in results)]))\n"
    )
    out = subprocess.run([sys.executable, "-c", script, str(FIXTURES / "citi-costco-small-labels-synthetic-sample.pdf")],
                         cwd=SCRIPTS, capture_output=True, text=True, check=True).stdout
    claimed, period_read, same, statement_date, rows, checks_hold = json.loads(out)
    assert claimed and not period_read and same
    assert (statement_date, rows, checks_hold) == ("2026-09-14", 6, True)


def test_citi_annual_summary_synthetic(run_statement):
    stmt = run_statement(
        "citi-annual-synthetic-sample.pdf",
        "--expected-parser",
        "citi_credit_card.py",
    )
    assert stmt.institution == "Citi"
    assert stmt.statement_date == "2025-12-31"
    assert len(stmt.transactions) == 7
    assert all(t["accountType"] == "Credit Card" for t in stmt.transactions)
    assert all(t["balance"] is None for t in stmt.transactions)

    alice = [t for t in stmt.transactions if t["account"] == "1111"]
    bob = [t for t in stmt.transactions if t["account"] == "2222"]
    assert len(alice) == 4
    assert len(bob) == 3
    assert approx(sum(t["amount"] for t in alice), -225.00)
    assert approx(sum(t["amount"] for t in bob), -220.00)
    refund = next(t for t in bob if "RETURN" in t["description"])
    assert approx(refund["amount"], 20.00)


def test_citi_annual_rejects_changed_complete_category_subtotal(dump_pages):
    pages = dump_pages("citi-annual-synthetic-sample.pdf")
    broken = [page.replace("Subtotal $150.00", "Subtotal $151.00") for page in pages]
    with pytest.raises(ValueError, match="subtotal does not reconcile"):
        citi_credit_card.parse(broken, "unused.pdf")


def test_citi_card_layouts_no_parser_reads_are_claimed_for_untested_diagnostics():
    text = """Citi Card
Payment Due Date 10/15/2026
Minimum Payment Due $25.00
Credit Limit $10,000.00
New Balance $500.00
"""
    # citi_credit_card claims only the layouts it reads; the rest are
    # citi_credit_card_family's, which is untested.
    assert citi_credit_card.detect(text)[0] is False
    matched, reason = citi_credit_card_family.detect(text)
    assert matched is True
    assert "not yet supported" in reason

    with pytest.raises(parser_common.ParserDiagnosticError) as exc:
        citi_credit_card_family.parse([text], "unused.pdf")
    assert exc.value.diagnostic_code == "PARSER_REQUIRED_DATA_MISSING"
    assert exc.value.diagnostic_stage == "metadata"
    assert exc.value.missing_fields == ("billingPeriod",)
    message, diagnostic = parser_common.parser_failure(
        citi_credit_card_family,
        exc.value,
        "pdf",
        {"pageCount": 1, "textPageCount": 1},
        text,
    )
    # Untested: the failure offers a scrambled copy rather than questions.
    assert "not been confirmed on real statements" in message
    assert "scrambled copy" in message
    assert diagnostic["parserId"] == "citi_credit_card_family"
    assert diagnostic["institution"] == "Citi"
    assert diagnostic["supportTier"] == "untested"
    assert diagnostic["missingFields"] == ["billingPeriod"]
    assert diagnostic["fieldPresence"]["paymentDueDate"] is True
    assert diagnostic["fieldPresence"]["minimumPaymentDue"] is True
    assert "It could not read the statement's Billing Period." in message
    assert diagnostic["fieldLines"]["billingPeriod"] == {"match": "missing"}
    assert diagnostic["fieldLines"]["paymentDueDate"]["shape"] == "Aaaaaaa Aaa Aaaa 99/99/9999"


def test_bofa_credit_card(run_statement):
    stmt = run_statement("bofa-cc-stmt-sample.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.first_account == "7777"
    assert stmt.first_account_type == "Credit Card"
    assert stmt.statement_date == "2019-08-05"
    assert len(stmt.transactions) == 10

    closing = _running_balance(stmt.transactions, -1150.50)
    assert approx(closing, -570.49)

    purchase = stmt.transactions[0]
    assert purchase["description"].startswith("ROOM MATE MILAN")
    assert approx(purchase["amount"], -45.16)
    assert purchase.get("reference") == "5049"

    payments = [t for t in stmt.transactions if t["description"].startswith("PAYMENT")]
    assert payments, "expected a PAYMENT transaction"
    assert approx(payments[-1]["amount"], 1150.50)


def test_bofa_combined_statement_2012(run_statement):
    stmt = run_statement("bofa-sample-statement-2012.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.statement_date == "2012-12-06"
    assert len(stmt.transactions) == 12

    checking = [t for t in stmt.transactions if t["accountType"] == "Checking"]
    savings = [t for t in stmt.transactions if t["accountType"] == "Savings"]
    assert len(checking) == 11
    assert len(savings) == 1
    assert savings[0]["account"] == "1790"
    assert approx(savings[0]["amount"], 1.02)
    assert savings[0]["balance"] is not None and approx(savings[0]["balance"], 124704.89)

    running = _running_balance(checking, 86703.94)
    assert approx(running, 84653.73)
    for t in checking:
        assert t["account"] == "7777"

    hoa = [t for t in checking if t["description"].startswith("Hoa Online Pay")]
    assert hoa and approx(hoa[0]["amount"], -506.95)


def test_bofa_combined_2012_synthetic(run_statement):
    stmt = run_statement("bofa-combined-2012-synthetic-sample.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.statement_date == "2012-12-06"
    assert len(stmt.transactions) == 4

    checking = [t for t in stmt.transactions if t["accountType"] == "Checking"]
    savings = [t for t in stmt.transactions if t["accountType"] == "Savings"]
    assert checking and savings
    for t in checking:
        assert t["account"] == "1111"
    for t in savings:
        assert t["account"] == "2222"
    assert approx(_running_balance(checking, 1000.00), 1801.50)
    assert approx(_running_balance(savings, 5000.00), 5005.00)


def test_bofa_checking_combined_2018_synthetic(run_statement):
    stmt = run_statement("bofa-checking-combined-2018-synthetic-sample.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.statement_date == "2020-02-05"
    assert len(stmt.transactions) == 3

    checking = [t for t in stmt.transactions if t["accountType"] == "Checking"]
    savings = next(t for t in stmt.transactions if t["accountType"] == "Savings")
    assert len(checking) == 2
    for t in checking:
        assert t["account"] == "1111"
    assert approx(_running_balance(checking, 1000.00), 1800.00)
    assert savings["account"] == "2222"
    assert approx(savings["amount"], 5.00)
    assert approx(savings["balance"], 5005.00)


def test_bofa_savings_legacy_single_account_synthetic(run_statement):
    stmt = run_statement("bofa-savings-legacy-single-account-synthetic-sample.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.statement_date == "2013-03-31"
    assert len(stmt.transactions) == 0


def test_bofa_checking_with_check_images(run_statement):
    # ensureVision is not wired here (as in the Go test): only the
    # always-correct-without-OCR parts are asserted.
    stmt = run_statement("bofa-sample-statement.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.first_account == "9041"
    assert stmt.first_account_type == "Checking"
    assert stmt.statement_date == "2016-05-12"
    assert stmt.raw.get("accountOwners") == [{"account": "9041", "ownerName": "MARILYN MOSBY"}]

    want_checks = {
        "CHECK #1409": -65, "CHECK #1439": -314, "CHECK #1440": -307,
        "CHECK #1441": -220, "CHECK #1412": -15, "CHECK #1442": -262,
        "CHECK #1443": -159, "CHECK #1444": -300, "CHECK #1410": -200,
        "CHECK #1445": -190, "CHECK #1446": -30, "CHECK #1447": -450,
        "CHECK #1448": -100,
    }
    got = {
        t["description"]: t["amount"]
        for t in stmt.transactions
        if t["description"].startswith("CHECK #")
    }
    assert len(got) == len(want_checks), got
    for desc, amount in want_checks.items():
        assert desc in got and approx(got[desc], amount), (desc, got.get(desc), amount)


def test_bofa_checking_with_check_images_layout_b(run_statement):
    stmt = run_statement("bofa-stmt-checks-synthetic-sample.pdf")
    assert stmt.institution == "Bank of America"
    assert stmt.raw.get("accountOwners") == [{"account": stmt.first_account, "ownerName": "JONATHAN DOE"}]
    assert stmt.first_account_type == "Checking"
    assert stmt.statement_date == "2025-01-23"

    want_checks = {"CHECK #568": -300, "CHECK #514": -96}
    got = {
        t["description"]: t["amount"]
        for t in stmt.transactions
        if t["description"].startswith("CHECK #")
    }
    assert len(got) == len(want_checks), got
    for desc, amount in want_checks.items():
        assert desc in got and approx(got[desc], amount), (desc, got.get(desc), amount)


def _accounts(stmt) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    for t in stmt.transactions:
        by_type.setdefault(f"{t['accountType']} {t['account']}", []).append(t)
    return by_type


def test_star_one_credit_union_synthetic(run_statement):
    stmt = run_statement("star-one-credit-union-synthetic-sample.pdf", "--expected-parser", "star_one_credit_union.py")
    assert (stmt.institution, stmt.statement_date) == ("Star One Credit Union", "2026-09-30")
    accounts = _accounts(stmt)
    # The member number with each account's suffix, its last four digits.
    assert sorted(accounts) == ["Checking 7897", "Savings 7891"]
    assert [t["amount"] for t in accounts["Savings 7891"]] == [2.51]
    checking = accounts["Checking 7897"]
    # Which column each amount was in comes from the balances.
    assert [t["amount"] for t in checking] == [-42.18, 1300.0, -500.0, -119.84, 1300.0, -1000.0, 0.15]
    assert checking[0]["description"] == "POS DEBIT SAMPLE GROCERY SAMPLE CITY CA"
    assert checking[-1]["balance"] == 2468.13
    assert stmt.raw["checkResults"] and all(c["ok"] for c in stmt.raw["checkResults"])


@pytest.mark.parametrize("name", ["AUTO LOAN", "SHARE SECURED LOAN"])
def test_star_one_reports_an_account_it_does_not_read(dump_pages, name):
    # A loan, whatever else its name says, is not read as savings.
    pages = dump_pages("star-one-credit-union-synthetic-sample.pdf")
    loan = (f"{name} ACCT# 70\n"
            "Beginning Balance Deposits/Credits Withdrawals/Debits Ending Balance YTD Dividends\n"
            "$ 13,000.00 $ 0.00 $ 350.00 $ 12,650.00 $ 0.00\n"
            "Date Transaction Description Deposit Withdrawal Balance\n"
            "SEP10 PAYMENT 350.00 12,650.00\n")
    changed = [page.replace("YTD ACCOUNT SUMMARY", loan + "YTD ACCOUNT SUMMARY") for page in pages]
    assert changed != pages
    out = star_one_credit_union.parse(changed, "unused.pdf")
    assert len(out["transactions"]) == 8
    [unread] = [c for c in out["checks"] if c["kind"] == "unread"]
    assert [line["text"] for line in unread["lines"]] == ["SEP10 PAYMENT 350.00 12,650.00"]


def test_star_one_places_a_row_its_balances_cannot(dump_pages):
    # A Beginning Balance that doesn't meet the first row's balance (as a
    # scrambled sample's can be): the row is placed by the account's
    # totals, and the balance check is the one that fails.
    pages = dump_pages("star-one-credit-union-synthetic-sample.pdf")
    changed = [page.replace("$ 1,530.00 $ 2,600.15", "$ 9,999.00 $ 2,600.15")
               .replace("$ 1,204.17 $ 2.51", "$ 9,999.00 $ 2.51") for page in pages]
    assert changed != pages
    out = star_one_credit_union.parse(changed, "unused.pdf")
    first = {t["accountType"]: t["amount"] for t in reversed(out["transactions"])}
    # The savings account's first row a deposit, the checking account's a withdrawal.
    assert first == {"Savings": 2.51, "Checking": -42.18}
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert [r["label"] for r in results if not r["ok"]] == ["REGULAR SAVINGS ACCOUNT ACCT# 1", "CHECKING ACCOUNT ACCT# 7"]


def test_star_one_keeps_a_description_to_its_own_lines(dump_pages):
    # A footer is not part of a description, and a description line that
    # ends in "ACCT# 1" heads no account.
    pages = dump_pages("star-one-credit-union-synthetic-sample.pdf")
    payroll = "SEP05 ACH CREDIT SAMPLE EMPLOYER PAYROLL 1,300.00 2,787.82"
    transfer = "SEP15 WITHDRAWAL TRANSFER TO SAMPLE BANK 500.00 2,287.82"
    changed = [page.replace(payroll, payroll + "\nFederally insured by NCUA")
               .replace(transfer, transfer + "\nTO REGULAR SAVINGS ACCT# 1") for page in pages]
    assert changed != pages
    out = star_one_credit_union.parse(changed, "unused.pdf")
    descriptions = {t["date"]: t["description"] for t in out["transactions"] if t["accountType"] == "Checking"}
    assert descriptions["2026-09-05"] == "ACH CREDIT SAMPLE EMPLOYER PAYROLL"
    assert descriptions["2026-09-15"] == "WITHDRAWAL TRANSFER TO SAMPLE BANK TO REGULAR SAVINGS ACCT# 1"
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert len(out["transactions"]) == 8 and all(r["ok"] for r in results)


def test_technology_credit_union_synthetic(run_statement):
    stmt = run_statement("technology-credit-union-synthetic-sample.pdf", "--expected-parser", "technology_credit_union.py")
    assert (stmt.institution, stmt.statement_date) == ("Technology Credit Union", "2026-09-30")
    accounts = _accounts(stmt)
    assert sorted(accounts) == ["Checking 0987", "Savings 0123"]
    assert [t["amount"] for t in accounts["Savings 0123"]] == [-200.0, 2.44]
    checking = accounts["Checking 0987"]
    assert [t["amount"] for t in checking] == [-61.2, 200.0, -88.35, 0.13]
    assert checking[0]["description"] == "Withdrawal POS SAMPLE GROCERY SAMPLE CITY CA"
    assert stmt.raw["checkResults"] and all(c["ok"] for c in stmt.raw["checkResults"])


def test_technology_credit_union_signs_an_unsigned_amount_by_its_balance(dump_pages):
    # The sample printed no withdrawal, so how it signs one is not known.
    pages = dump_pages("technology-credit-union-synthetic-sample.pdf")
    unsigned = [page.replace("UTILITY -88.35", "UTILITY 88.35").replace("Checking -200.00", "Checking 200.00")
                for page in pages]
    assert unsigned != pages
    out = technology_credit_union.parse(unsigned, "unused.pdf")
    assert [t["amount"] for t in out["transactions"]] == [-200.0, 2.44, -61.2, 200.0, -88.35, 0.13]


def test_technology_credit_union_is_known_by_its_layout_without_its_name(dump_pages):
    # The scrambled sample this parser was built from kept no word naming
    # the credit union.
    pages = dump_pages("technology-credit-union-synthetic-sample.pdf")
    unnamed = "\n".join(pages).replace("www.techcu.com", "")
    assert technology_credit_union.detect(unnamed)[0] is True
    # The same words, but no account named under the column header by a
    # long number, are another statement's.
    other = unnamed.replace("1234567890123", "123456").replace("9876543210987", "987654")
    assert technology_credit_union.detect(other)[0] is False


@pytest.mark.parametrize("name", ["AUTO LOAN", "SHARE SECURED LOAN"])
def test_technology_credit_union_reports_an_account_it_does_not_read(dump_pages, name):
    pages = dump_pages("technology-credit-union-synthetic-sample.pdf")
    loan = ("Loans\n"
            "Date Transaction Description Amount Balance\n"
            f"{name} 5555555555\n"
            "09/01 Starting Balance $12,000.00\n"
            "09/10 Payment -350.00 11,650.00\n"
            f"09/30 Ending Balance for {name} $11,650.00\n")
    changed = [page.replace("Total Dividends Paid", loan + "Total Dividends Paid") for page in pages]
    assert changed != pages
    out = technology_credit_union.parse(changed, "unused.pdf")
    assert len(out["transactions"]) == 6
    [unread] = [c for c in out["checks"] if c["kind"] == "unread"]
    assert [line["text"] for line in unread["lines"]] == ["09/10 Payment -350.00 11,650.00"]


def test_technology_credit_union_reads_an_account_carried_on_to_the_next_page(dump_pages):
    # The next page repeats the column header and names the account again.
    [page] = dump_pages("technology-credit-union-synthetic-sample.pdf")
    head, tail = page.split("09/15 Deposit Transfer from Savings")
    pages = [head + "Page: 1 of 2", "Page: 2 of 2\nDate Transaction Description Amount Balance\n"
             "INTEREST CHECKING 9876543210987\n09/15 Deposit Transfer from Savings" + tail]
    out = technology_credit_union.parse(pages, "unused.pdf")
    assert len(out["transactions"]) == 6
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert all(r["ok"] for r in results)


def test_technology_credit_union_checks_only_the_totals_its_summary_names(dump_pages):
    # A month with no withdrawals names none: "Summary: 1 Deposit : $2.44".
    pages = dump_pages("technology-credit-union-synthetic-sample.pdf")
    changed = [page.replace("09/15 Withdrawal Transfer to Checking -200.00 1,329.17\n", "")
               .replace("$1,529.17", "$1,329.17").replace(" 1 Withdrawal : $200.00", "") for page in pages]
    assert changed != pages
    out = technology_credit_union.parse(changed, "unused.pdf")
    labels = [c["label"] for c in out["checks"]]
    assert "SHARE SAVINGS: withdrawals" not in labels and "SHARE SAVINGS: deposits" in labels
    results = statement_checks.evaluate(out["checks"], {"cash_transactions": out["transactions"]}, out["statementDate"])
    assert all(r["ok"] for r in results)


def test_technology_credit_union_keeps_a_footer_out_of_a_description(dump_pages):
    pages = dump_pages("technology-credit-union-synthetic-sample.pdf")
    row = "09/15 Deposit Transfer from Savings 200.00 3,211.46"
    changed = [page.replace(row, row + "\nFederally insured by NCUA") for page in pages]
    assert changed != pages
    out = technology_credit_union.parse(changed, "unused.pdf")
    assert "Deposit Transfer from Savings" in [t["description"] for t in out["transactions"]]
