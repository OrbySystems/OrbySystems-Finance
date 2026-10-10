"""E*TRADE from Morgan Stanley CLIENT STATEMENT layout (etrade_brokerage).

Every page text here is invented: the shapes follow the Client Statement
layout (cover, CHANGE IN VALUE, BALANCE SHEET | CASH FLOW, HOLDINGS by
section, CASH FLOW ACTIVITY BY DATE, the MMF sweep table, TRANSFERS,
CORPORATE ACTIONS AND ADDITIONAL ACTIVITY), the names and figures do not
come from any statement.
"""

from __future__ import annotations

import json
import shutil

import pytest

import parser_common
import statement_checks
from conftest import SCRIPTS
from institutions import etrade_brokerage


HOLDER = "TEST HOLDER"
ACCOUNT = "111-222333-444"


def _cover(period: str, beginning: str, ending: str) -> str:
    return "\n".join([
        f"CLIENT STATEMENT For the Period {period}",
        f"STATEMENT FOR: Beginning Total Value {beginning}",
        f"{HOLDER} Ending Total Value {ending}",
        "Morgan Stanley Smith Barney LLC. Member SIPC. www.etrade.com",
        "E*TRADE is a business of Morgan Stanley.",
        HOLDER,
        "1 SAMPLE STREET",
    ])


def _page(period: str, banner: str, body: list[str], account: str = ACCOUNT, number: int = 2) -> str:
    return "\n".join([
        f"CLIENT STATEMENT For the Period {period} Page {number} of 9",
        f"Morgan Stanley at Work Self-Directed Account {HOLDER}",
        f"Account {banner} {account} {HOLDER}",
        *body,
    ])


def _summary(beginning, credits, debits, net, change, ending, period_cols="(3/1/27-3/31/27) (1/1/27-3/31/27)"):
    return [
        "CHANGE IN VALUE OF YOUR ACCOUNT (includes accrued interest)",
        "This Period This Year",
        period_cols,
        f"TOTAL BEGINNING VALUE {beginning} {beginning}",
        f"Credits {credits} {credits}",
        f"Debits {debits} {debits}",
        "Security Transfers — —",
        f"Net Credits/Debits/Transfers {net} {net}",
        f"Change in Value {change} 9.9% 1.0%",
        f"TOTAL ENDING VALUE {ending} {ending}",
    ]


def _parse(pages: list[str]) -> tuple[dict, list[dict]]:
    result = etrade_brokerage.parse(pages, "unused.pdf")
    parser_common.validate_multi_table_parse_result(result, "etrade_brokerage")
    results = statement_checks.evaluate(result["checks"], result["tables"], result["statementDate"])
    return result, results


# --- the Client Statement layout ---------------------------------------------

PERIOD = "March 1-31, 2027"
SUMMARY = _summary("$20,000.00", "—", "—", "—", "512.00", "$20,512.00")
CASH_FLOW = [
    "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
    "Last Period This Period This Period This Year",
    "(as of 2/28/27) (as of 3/31/27) (3/1/27-3/31/27) (1/1/27-3/31/27)",
    "Cash, BDP, MMFs $1,000.00 $1,262.50 OPENING CASH, BDP, MMFs $1,000.00 —",
    "Stocks 15,000.00 15,249.50 Purchases — (500.00)",
    "ETFs & CEFs 4,000.00 4,000.00 Sales and Redemptions 240.00 740.00",
    "Total Assets $20,000.00 $20,512.00",
    "Income and Distributions 22.50 22.50",
    "Cash, BDP, MMFs (Debit) — — Total Investment Related Activity $262.50 $262.50",
    "Total Liabilities (outstanding balance) — — Electronic Transfers-Credits — 1,000.00",
    "TOTAL VALUE $20,000.00 $20,512.00 Electronic Transfers-Debits — —",
    "Total Cash Related Activity — $1,000.00",
    "Total Card/Check Activity — —",
    "CLOSING CASH, BDP, MMFs $1,262.50 $1,262.50",
    "INCOME AND DISTRIBUTION SUMMARY GAIN/(LOSS) SUMMARY",
    "Qualified Dividends — —",
    "Short-Term Gain — — $214.50",
    "Other Dividends 15.00 15.00",
    "Interest 7.50 7.50",
    "Income And Distributions $22.50 $22.50",
    "TOTAL INCOME AND DISTRIBUTIONS $22.50 $22.50 TOTAL GAIN/(LOSS) — — $2,889.50",
]
HOLDINGS_CASH = [
    "Investment Objectives (in order of priority): Growth Brokerage Account",
    "HOLDINGS",
    "This section reports positions purchased/sold on a trade date basis.",
    "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
    "7-Day",
    "Description Market Value Current Yield % Est Ann Income APY %",
    "MORGAN STANLEY BANK N.A. # $1,262.50 — $1.00 0.050",
    "Percentage",
    "of Holdings Market Value Est Ann Income",
    "CASH, BDP, AND MMFs 6.15% $1,262.50 $1.00",
]
STOCKS_HEAD = [
    "STOCKS",
    "COMMON STOCKS",
    "Unrealized Current",
    "Security Description Quantity Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %",
]
STOCK_ROWS = [
    "ALPHA WIDGETS INC (AWI) 100.000 $120.000 $10,000.00 $12,000.00 $2,000.00 $150.00 1.25",
    "Rating: Morgan Stanley: 1, Morningstar: 2; Next Dividend Payable 05/2027; Asset Class: Equities",
    "BETA FOODS CORP (BFC) 50.000 65.500 3,000.00 3,275.00 275.00 — —",
    "Asset Class: Equities",
    "COMMON STOCKS $13,000.00 $15,275.00 $2,275.00 $150.00 0.98%",
]
OPTION_ROWS = [
    'OPTIONS (Contract Prices are reported to only the third decimal (which may display as "$0.000"))',
    "Number of Unrealized",
    "Security Description Contracts Contract Price Total Cost Market Value Gain/(Loss)",
    "CALL ALPHA WIDGETS INC AT 130.000 EXPIRES 04/16/2027 (1.000) $0.255 $(240.00) $(25.50) $214.50",
    "(AWI 270416C00130000)",
    "Short Position; Asset Class: Equities",
    "OPTIONS $(240.00) $(25.50) $214.50",
]
STOCKS_TOTAL = [
    "Percentage Unrealized Current",
    "of Holdings Total Cost Market Value Gain/(Loss) Est Ann Income Yield %",
    "STOCKS 74.34% $12,760.00 $15,249.50 $2,489.50 $150.00 0.98%",
    "Total Stocks (Long) $15,275.00",
    "Total Stocks (Short) $(25.50)",
]
ETF_ROWS = [
    "EXCHANGE-TRADED & CLOSED-END FUNDS",
    "Unrealized Current",
    "Security Description Quantity Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %",
    "SAMPLE TOTAL MARKET ETF (STM) 40.000 $100.000 $3,600.00 $4,000.00 $400.00 $60.00 1.50",
    "Next Dividend Payable 04/2027; Asset Class: Equities",
    "Percentage Unrealized Current",
    "of Holdings Total Cost Market Value Gain/(Loss) Est Ann Income Yield %",
    "EXCHANGE-TRADED & CLOSED-END FUNDS 19.50% $3,600.00 $4,000.00 $400.00 $60.00 1.50%",
    "Percentage Unrealized Est Ann Income Current",
    "of Holdings Total Cost Market Value Gain/(Loss) Accrued Interest Yield %",
    "TOTAL VALUE 100.00% $16,360.00 $20,512.00 $2,889.50 $211.00 1.03%",
    "—",
    "ALLOCATION OF ASSETS",
    "Cash, BDP, MMFs $1,262.50 — — — — —",
    "Stocks — $15,249.50 — — — —",
]
ACTIVITY = [
    "ACTIVITY",
    "CASH FLOW ACTIVITY BY DATE",
    "Activity Settlement",
    "Date Date Activity Type Description Comments Quantity Price Credits/(Debits)",
    "3/10 3/11 Sold CALL AWI 04/16/27 130.000 ACTED AS AGENT 1.000 $2.4000 $240.00",
    "UNSOLICITED TRADE; OPENING",
    "3/15 Dividend SAMPLE TOTAL MARKET ETF 15.00",
    "3/31 Interest Income MORGAN STANLEY BANK N.A. (Period 03/01-03/31) 7.50",
    "NET CREDITS/(DEBITS) $262.50",
    "Purchase and Sale transactions above may have received an average price execution.",
    "MONEY MARKET FUND (MMF) AND BANK DEPOSIT PROGRAM ACTIVITY",
    "Activity",
    "Date Activity Type Description Credits/(Debits)",
    "3/11 Automatic Investment BANK DEPOSIT PROGRAM $240.00",
    "3/15 Automatic Investment BANK DEPOSIT PROGRAM 15.00",
    "3/31 Automatic Investment BANK DEPOSIT PROGRAM 7.50",
    "NET ACTIVITY FOR PERIOD $262.50",
    "TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY",
    "OPTIONS EXPIRATIONS, EXERCISES AND ASSIGNMENTS",
    "Activity",
    "Date Activity Type Description Comments Contracts",
    "3/22 Option Expired PUT BFC 03/19/27 60.000 EXPIRED OPTIONS 2.000",
    "MESSAGES",
    "Options Disclosure Document Available",
    "On 3/31 we updated the terms of our client agreement; it is available online.",
]


def _base_pages() -> list[str]:
    return [
        _cover(PERIOD, "(as of 3/1/27) $20,000.00", "(as of 3/31/27) $20,512.00"),
        "CLIENT STATEMENT For the Period March 1-31, 2027 Page 1 of 9\nStandard Disclosures\nSIPC coverage is up to $500,000.",
        _page(PERIOD, "Summary", SUMMARY + CASH_FLOW),
        _page(PERIOD, "Detail", HOLDINGS_CASH + STOCKS_HEAD + STOCK_ROWS + OPTION_ROWS + STOCKS_TOTAL, number=4),
        _page(PERIOD, "Detail", ETF_ROWS, number=5),
        _page(PERIOD, "Detail", ACTIVITY, number=6),
    ]


def test_client_statement_reads_every_section_and_its_checks_hold() -> None:
    result, checks = _parse(_base_pages())

    assert result["institution"] == "E*TRADE from Morgan Stanley"
    assert result["statementDate"] == "2027-03-31"
    holdings = {row["symbol"]: row for row in result["tables"]["brokerage_holdings"]}
    assert list(holdings) == ["CASH", "AWI", "BFC", "AWI270416C130", "STM"]
    assert all(row["account"] == "3444" for row in holdings.values())
    assert all(row["provider_account_id"] == ACCOUNT for row in holdings.values())
    assert holdings["CASH"]["current_value"] == pytest.approx(1262.50)
    assert holdings["CASH"]["is_cash_equivalent"] is True
    assert holdings["CASH"]["description"] == "MORGAN STANLEY BANK N.A."
    assert holdings["AWI"]["type"] == "Stock"
    assert holdings["AWI"]["quantity"] == pytest.approx(100.0)
    assert holdings["AWI"]["price"] == pytest.approx(120.0)
    assert holdings["AWI"]["cost_basis_total"] == pytest.approx(10000.0)
    assert holdings["AWI"]["estimated_annual_income"] == pytest.approx(150.0)
    assert holdings["AWI"]["estimated_yield"] == pytest.approx(1.25)
    assert "estimated_annual_income" not in holdings["BFC"]
    option = holdings["AWI270416C130"]
    assert option["type"] == "Options"
    assert option["quantity"] == pytest.approx(-1.0)
    assert option["current_value"] == pytest.approx(-25.50)
    assert option["cost_basis_total"] == pytest.approx(-240.0)
    # A valid OSI code printed under the contract names the same contract.
    assert etrade_brokerage._osi_symbol("AWI", "270416C00130000") == "AWI270416C130"
    assert holdings["STM"]["type"] == "ETF"

    rows = result["tables"]["brokerage_transactions"]
    assert [(r["date"], r["action"], r["transaction_type"], r["amount"]) for r in rows] == [
        ("2027-03-10", "Sold", "sell", 240.0),
        ("2027-03-15", "Dividend", "dividend", 15.0),
        ("2027-03-31", "Interest Income", "interest", 7.5),
        ("2027-03-22", "Option Expired", "corporate_action", 0.0),
    ]
    sold, dividend, interest, expired = rows
    assert sold["symbol"] == "AWI270416C130"  # the holding's own OCC code
    # A sale's quantity is positive; the type says it left the account.
    assert sold["quantity"] == pytest.approx(1.0) and sold["price"] == pytest.approx(2.4)
    assert sold["description"].endswith("UNSOLICITED TRADE; OPENING")
    assert dividend["symbol"] == "STM"
    assert "symbol" not in interest
    assert expired["symbol"] == "BFC270319P60"
    assert expired["subtype"] == "Out" and expired["quantity"] == pytest.approx(2.0)
    assert parser_common.corporate_event(expired) == "expired"
    # The sweep table mirrors the cash rows and is not emitted.
    assert not any("BANK DEPOSIT PROGRAM" in r["description"] for r in rows)

    # One total per set of rows: an answer adds a not-read line to one
    # check only, so a second total over the same rows would stay failing.
    assert [(c["kind"], c["label"]) for c in checks] == [
        ("sum", "Credits/Debits"),
        ("sum", "CASH FLOW ACTIVITY BY DATE"),
        ("unread", "CASH FLOW ACTIVITY BY DATE"),
        ("unread", "TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY"),
    ]
    assert all(c["ok"] for c in checks), checks


def test_rows_and_sections_split_across_a_page_break() -> None:
    pages = _base_pages()
    holdings_a = HOLDINGS_CASH + STOCKS_HEAD + STOCK_ROWS[:2] + ["418KDPLM"]
    holdings_b = (
        ["COMMON STOCKS (CONTINUED)", "Unrealized Current",
         "Security Description Quantity Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %"]
        + STOCK_ROWS[2:] + OPTION_ROWS[:4]
    )
    # The contract's "(ROOT ...)" line lands on the next page.
    holdings_c = OPTION_ROWS[4:] + STOCKS_TOTAL
    activity_a = ACTIVITY[:5] + ["418KDPLM", "903311"]
    activity_b = [
        "CASH FLOW ACTIVITY BY DATE (CONTINUED)",
        "Activity Settlement",
        "Date Date Activity Type Description Comments Quantity Price Credits/(Debits)",
    ] + ACTIVITY[5:]
    split = pages[:3] + [
        _page(PERIOD, "Detail", holdings_a, number=4),
        _page(PERIOD, "Detail", holdings_b, number=5),
        _page(PERIOD, "Detail", holdings_c, number=6),
        pages[4],
        _page(PERIOD, "Detail", activity_a, number=7),
        _page(PERIOD, "Detail", activity_b, number=8),
    ]
    whole, _ = _parse(pages)
    result, checks = _parse(split)

    assert result["tables"] == whole["tables"]
    assert all(c["ok"] for c in checks), checks
    sold = result["tables"]["brokerage_transactions"][0]
    assert sold["description"] == "CALL AWI 04/16/27 130.000 ACTED AS AGENT UNSOLICITED TRADE; OPENING"


def _activity_statement(rows: list[str], net: str, cash_flow: list[str], summary: list[str],
                        holdings: list[str], period: str = PERIOD) -> list[str]:
    return [
        _cover(period, "$1.00", "$1.00"),
        _page(period, "Summary", summary + cash_flow),
        _page(period, "Detail", holdings, number=3),
        _page(period, "Detail", [
            "ACTIVITY",
            "CASH FLOW ACTIVITY BY DATE",
            "Activity Settlement",
            "Date Date Activity Type Description Comments Quantity Price Credits/(Debits)",
            *rows,
            f"NET CREDITS/(DEBITS) {net}",
            "MESSAGES",
        ], number=4),
    ]


def _simple_holdings(cash: str, total: str) -> list[str]:
    return [
        "HOLDINGS",
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "Description Market Value Current Yield % Est Ann Income APY %",
        f"MORGAN STANLEY BANK N.A. # {cash} — — 0.050",
        f"CASH, BDP, AND MMFs 79.00% {cash} —",
        "STOCKS",
        "COMMON STOCKS",
        "Security Description Quantity Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %",
        "BETA FOODS CORP (BFC) 10.000 $65.000 $650.00 $650.00 $0.00 — —",
        "Asset Class: Equities",
        "STOCKS 20.40% $650.00 $650.00 $0.00 — —",
        "EXCHANGE-TRADED & CLOSED-END FUNDS",
        "SAMPLE TOTAL MARKET ETF (STM) 0.150 $100.000 $15.00 $15.00 $0.00 — —",
        "EXCHANGE-TRADED & CLOSED-END FUNDS 0.60% $15.00 $15.00 $0.00 — —",
        f"TOTAL VALUE 100.00% $665.00 {total} $0.00 — —",
    ]


def test_trades_transfers_fees_and_reinvestment_are_classified() -> None:
    rows = [
        "3/2 Funds Received ACH TRANSFER FROM BANK $1,000.00",
        "3/5 3/6 Bought BETA FOODS CORP ACTED AS AGENT 10.000 $65.0000 $(650.00)",
        "UNSOLICITED TRADE",
        "3/12 3/13 Sold ALPHA WIDGETS INC ACTED AS AGENT 5.000 120.0000 599.95",
        "3/15 Dividend Reinvestment SAMPLE TOTAL MARKET ETF REINVESTMENT 0.150 100.0000 (15.00)",
        "3/15 Qualified Dividend SAMPLE TOTAL MARKET ETF 15.00",
        "3/20 Service Fee ANNUAL ACCOUNT FEE (25.00)",
        "3/25 Funds Transferred ACH TRANSFER TO BANK (300.00)",
        "3/28 Journal TRANSFER TO 111-222333-555 (100.00)",
        "3/29 Foreign Tax Withheld SAMPLE TOTAL MARKET ETF (1.50)",
        "3/30 Margin Interest MARGIN INTEREST CHARGED (2.00)",
    ]
    cash_flow = [
        "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
        "Cash, BDP, MMFs $2,000.00 $2,521.45 OPENING CASH, BDP, MMFs $2,000.00 $2,000.00",
        "Purchases (650.00) (650.00)",
        "Dividend Reinvestments (15.00) (15.00)",
        "Sales and Redemptions 599.95 599.95",
        "Income and Distributions 13.50 13.50",
        "Total Investment Related Activity $(51.55) $(51.55)",
        "Electronic Transfers-Credits 1,000.00 1,000.00",
        "Electronic Transfers-Debits (300.00) (300.00)",
        "Other Debits (127.00) (127.00)",
        "Total Cash Related Activity $573.00 $573.00",
        "CLOSING CASH, BDP, MMFs $2,521.45 $2,521.45",
    ]
    summary = _summary("$2,612.95", "1,000.00", "(427.00)", "$573.00", "0.50", "$3,186.45")
    result, checks = _parse(_activity_statement(
        rows, "$521.45", cash_flow, summary, _simple_holdings("$2,521.45", "$3,186.45")))

    got = [
        (r["action"], r["transaction_type"], r.get("symbol", ""), r.get("quantity"), r["amount"])
        for r in result["tables"]["brokerage_transactions"]
    ]
    assert got == [
        ("Funds Received", "deposit", "", None, 1000.0),
        ("Bought", "buy", "BFC", 10.0, -650.0),
        ("Sold", "sell", "", 5.0, 599.95),
        ("Dividend Reinvestment", "buy", "STM", 0.15, -15.0),
        ("Qualified Dividend", "dividend", "STM", None, 15.0),
        ("Service Fee", "fee", "", None, -25.0),
        ("Funds Transferred", "withdrawal", "", None, -300.0),
        ("Journal", "internal_transfer", "", None, -100.0),
        ("Foreign Tax Withheld", "tax", "STM", None, -1.5),
        ("Margin Interest", "fee", "", None, -2.0),
    ]
    for row in result["tables"]["brokerage_transactions"]:
        assert row["transaction_type"] in parser_common.TRANSACTION_TYPES
    flows = [r for r in result["tables"]["brokerage_transactions"] if parser_common.classifies_as_flow(r)]
    assert [r["action"] for r in flows] == ["Funds Received", "Funds Transferred", "Journal"]
    # Margin interest may or may not be counted in the summary's Debits, so
    # the Credits/Debits check is not made: only the checks that hold
    # whatever the words are.
    assert [(c["kind"], c["label"]) for c in checks] == [
        ("sum", "CASH FLOW ACTIVITY BY DATE"),
        ("unread", "CASH FLOW ACTIVITY BY DATE"),
    ]
    assert all(c["ok"] for c in checks), checks
    # Without it, money in and out plus the service fee are Credits + Debits.
    no_margin = [row for row in rows if "Margin Interest" not in row]
    cash_flow_no_margin = [line.replace("(127.00)", "(125.00)").replace("2,521.45", "2,523.45")
                           .replace("$573.00", "$575.00") for line in cash_flow]
    summary_no_margin = _summary("$2,612.95", "1,000.00", "(425.00)", "$575.00", "0.50", "$3,188.45")
    result, checks = _parse(_activity_statement(
        no_margin, "$523.45", cash_flow_no_margin, summary_no_margin, _simple_holdings("$2,523.45", "$3,188.45")))
    assert [(c["kind"], c["label"]) for c in checks] == [
        ("sum", "Credits/Debits"),
        ("sum", "CASH FLOW ACTIVITY BY DATE"),
        ("unread", "CASH FLOW ACTIVITY BY DATE"),
    ]
    flow_check = result["checks"][0]
    assert [result["tables"]["brokerage_transactions"][i]["action"] for i in flow_check["rows"]] == [
        "Funds Received", "Service Fee", "Funds Transferred", "Journal",
    ]
    assert all(c["ok"] for c in checks), checks


def test_activity_word_table_maps_to_the_closed_vocabulary() -> None:
    for word, ttype, _, _ in etrade_brokerage._ACTIVITY_WORDS:
        for candidate in ttype.split("/"):
            assert candidate.lstrip("+-") in parser_common.TRANSACTION_TYPES, (word, ttype)
    words = {word for word, *_ in etrade_brokerage._ACTIVITY_WORDS}
    for required in (
        "Bought", "Sold", "Sold Short", "Bought to Cover", "Bought to Close", "Dividend",
        "Qualified Dividend", "Dividend Reinvestment", "Interest Income", "Interest",
        "Funds Transferred", "Funds Received", "Electronic Transfer", "Wire", "ACH", "Journal",
        "Service Fee", "Margin Interest", "Foreign Tax Withheld", "Foreign Tax Paid",
        "Return of Capital", "Cash in Lieu", "Capital Gain",
    ):
        assert required in words, required
    flows = {"deposit", "withdrawal", "internal_transfer"}
    for word in ("Funds Received", "Funds Transferred", "Journal", "Electronic Transfer", "Wire", "ACH"):
        ttype = next(t for w, t, *_ in etrade_brokerage._ACTIVITY_WORDS if w == word)
        assert {part.lstrip("+-") for part in ttype.split("/")} <= flows | parser_common.FLOW_TRANSACTION_TYPES


def test_assigned_option_is_a_corporate_action_with_its_occ_code() -> None:
    pages = _base_pages()
    activity = list(ACTIVITY)
    at = activity.index("3/22 Option Expired PUT BFC 03/19/27 60.000 EXPIRED OPTIONS 2.000")
    activity[at:at + 1] = [
        "3/19 Option Assigned CALL BFC 03/19/27 55.000 ASSIGNED OPTIONS 1.000",
        "3/22 Option Expired PUT BFC 03/19/27 60.000 EXPIRED OPTIONS 2.000",
    ]
    pages[-1] = _page(PERIOD, "Detail", activity, number=6)
    result, checks = _parse(pages)

    assigned = next(r for r in result["tables"]["brokerage_transactions"] if r["action"] == "Option Assigned")
    assert assigned["transaction_type"] == "corporate_action"
    assert assigned["subtype"] == "Out"
    assert assigned["amount"] == 0.0
    assert assigned["symbol"] == "BFC270319C55"
    assert parser_common.OCC_SYMBOL.match(assigned["symbol"])
    assert assigned["quantity"] == pytest.approx(1.0)  # a written contract closed
    assert parser_common.corporate_event(assigned) == "assigned"
    assert all(c["ok"] for c in checks)


def test_december_january_period_dates_rows_in_both_years() -> None:
    period = "December 1- January 31, 2027"
    summary = _summary("$1,000.00", "—", "—", "—", "22.50", "$1,022.50",
                       "(12/1/26-1/31/27) (1/1/27-1/31/27)")
    cash_flow = [
        "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
        "Cash, BDP, MMFs $1,000.00 $1,022.50 OPENING CASH, BDP, MMFs $1,000.00 $1,000.00",
        "Income and Distributions 22.50 22.50",
        "Total Cash Related Activity — —",
        "CLOSING CASH, BDP, MMFs $1,022.50 $1,022.50",
    ]
    holdings = [
        "HOLDINGS",
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "MORGAN STANLEY BANK N.A. # $1,022.50 — — 0.050",
        "CASH, BDP, AND MMFs 100.00% $1,022.50 —",
        "TOTAL VALUE 100.00% — $1,022.50 N/A — —",
    ]
    rows = [
        "12/15 Dividend SAMPLE TOTAL MARKET ETF 20.00",
        "1/31 Interest Income MORGAN STANLEY BANK N.A. (Period 01/01-01/31) 2.50",
    ]
    result, checks = _parse(_activity_statement(rows, "$22.50", cash_flow, summary, holdings, period))

    assert result["statementDate"] == "2027-01-31"
    assert [r["date"] for r in result["tables"]["brokerage_transactions"]] == ["2026-12-15", "2027-01-31"]
    assert all(c["ok"] for c in checks), checks
    start, end = etrade_brokerage._period("For the Period December 1, 2026 - January 31, 2027")
    assert (start.isoformat(), end.isoformat()) == ("2026-12-01", "2027-01-31")
    assert etrade_brokerage._resolve_date("12/31", start, end) == "2026-12-31"
    assert etrade_brokerage._resolve_date("1/2", start, end) == "2027-01-02"
    single = etrade_brokerage._period("CLIENT STATEMENT For the Period June 1-30, 2027 Page 2 of 9")
    assert (single[0].isoformat(), single[1].isoformat()) == ("2027-06-01", "2027-06-30")


def test_unknown_activity_word_is_reported_as_unread_not_dropped() -> None:
    rows = [
        "3/8 3/9 Bought BETA FOODS CORP ACTED AS AGENT 10.000 $65.0000 $(650.00)",
        "3/14 Goodwill Credit ACCOUNT ADJUSTMENT 25.00",
        "3/31 Interest Income MORGAN STANLEY BANK N.A. (Period 03/01-03/31) 0.75",
    ]
    cash_flow = [
        "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
        "Cash, BDP, MMFs $1,000.00 $375.75 OPENING CASH, BDP, MMFs $1,000.00 $1,000.00",
        "Purchases (650.00) (650.00)",
        "Income and Distributions 0.75 0.75",
        "Other Credits 25.00 25.00",
        "Total Cash Related Activity $25.00 $25.00",
        "CLOSING CASH, BDP, MMFs $375.75 $375.75",
    ]
    summary = _summary("$1,000.00", "25.00", "—", "$25.00", "15.75", "$1,040.75")
    holdings = _simple_holdings("$375.75", "$1,040.75")
    pages = _activity_statement(rows, "$(624.25)", cash_flow, summary, holdings)
    result, checks = _parse(pages)

    actions = [r["action"] for r in result["tables"]["brokerage_transactions"]]
    assert actions == ["Bought", "Interest Income"]
    unread = next(c for c in result["checks"] if c["kind"] == "unread")
    assert unread["lines"] == [{"page": 4, "line": 9, "text": "3/14 Goodwill Credit ACCOUNT ADJUSTMENT 25.00"}]
    assert pages[3].split("\n")[8] == "3/14 Goodwill Credit ACCOUNT ADJUSTMENT 25.00"
    by_kind = {(c["kind"], c["label"]): c for c in checks}
    assert by_kind[("sum", "CASH FLOW ACTIVITY BY DATE")]["ok"] is False
    assert by_kind[("unread", "CASH FLOW ACTIVITY BY DATE")]["ok"] is False
    # With a line unread, no per-kind summary check is made: it would only
    # repeat the gap.
    assert ("sum", "Purchases") not in by_kind
    summary_only = statement_checks.diagnostic_summary(checks)
    assert "Goodwill" not in json.dumps(summary_only) and "25.00" not in json.dumps(summary_only)


def test_holdings_that_do_not_reconcile_fail_with_a_private_diagnostic() -> None:
    pages = _base_pages()
    broken = [line for line in STOCK_ROWS if not line.startswith("BETA FOODS")]
    pages[3] = _page(PERIOD, "Detail", HOLDINGS_CASH + STOCKS_HEAD + broken + OPTION_ROWS + STOCKS_TOTAL, number=4)

    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        etrade_brokerage.parse(pages, "unused.pdf")
    assert raised.value.diagnostic_code == "PARSER_RECONCILIATION_FAILED"
    assert raised.value.diagnostic_stage == "holdings"
    _, diagnostic = parser_common.parser_failure(
        etrade_brokerage, raised.value, "pdf", {"pageCount": len(pages), "textPageCount": len(pages)},
        "\n".join(pages),
    )
    encoded = json.dumps(diagnostic)
    assert "$" not in encoded and ACCOUNT not in encoded and "BETA" not in encoded
    assert diagnostic["parserRevision"] == etrade_brokerage.PARSER_REVISION


def test_an_unreadable_holding_line_fails_instead_of_dropping_the_position() -> None:
    pages = _base_pages()
    odd = STOCK_ROWS[:2] + ["GAMMA HOLDINGS UNITS 12.000 4.100 40.00 49.20 9.20 — —"] + STOCK_ROWS[2:]
    pages[3] = _page(PERIOD, "Detail", HOLDINGS_CASH + STOCKS_HEAD + odd + OPTION_ROWS + STOCKS_TOTAL, number=4)
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        etrade_brokerage.parse(pages, "unused.pdf")
    assert raised.value.diagnostic_stage == "holdings"
    assert raised.value.diagnostic_code in {"PARSER_UNCLASSIFIED_ROW", "PARSER_RECONCILIATION_FAILED"}


def test_two_accounts_each_read_and_checked_on_their_own() -> None:
    other = "111-222333-555"
    second_summary = _summary("$500.00", "—", "—", "—", "—", "$500.00")
    second_holdings = [
        "HOLDINGS",
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "MORGAN STANLEY BANK N.A. # $500.00 — — 0.050",
        "CASH, BDP, AND MMFs 100.00% $500.00 —",
        "TOTAL VALUE 100.00% — $500.00 N/A — —",
    ]
    pages = _base_pages() + [
        _page(PERIOD, "Summary", second_summary, account=other, number=7),
        _page(PERIOD, "Detail", second_holdings, account=other, number=8),
    ]
    result, checks = _parse(pages)
    holdings = result["tables"]["brokerage_holdings"]
    assert [(h["symbol"], h["account"]) for h in holdings][-1] == ("CASH", "3555")
    assert {h["provider_account_id"] for h in holdings} == {ACCOUNT, other}
    assert all(c["ok"] for c in checks)
    assert all(c["label"].endswith(f"({ACCOUNT})") for c in checks)


def test_module_works_as_a_drop_in_replacement(tmp_path) -> None:
    """Installed alone in the user's parsers folder, the module is loaded
    outside the institutions package (parser_common.load_extra_parsers)."""
    shutil.copy(SCRIPTS / "institutions" / "etrade_brokerage.py", tmp_path / "etrade_brokerage.py")
    modules, misses = parser_common.load_extra_parsers(str(tmp_path), "pdf")
    assert misses == []
    (module,) = modules
    assert not parser_common.is_bundled(module)
    pages = _base_pages()
    assert module.detect("\n".join(pages[:3]))[0]
    result = module.parse(pages, "unused.pdf")
    parser_common.validate_multi_table_parse_result(result, module.__name__)
    assert len(result["tables"]["brokerage_holdings"]) == 5


# --- review round 1 ------------------------------------------------------------

def _with_activity(activity: list[str]) -> list[str]:
    pages = _base_pages()
    pages[-1] = _page(PERIOD, "Detail", activity, number=6)
    return pages


def _app_includes(result: dict, results: list[dict]) -> dict:
    """The answers OrbySystems builds for "add these lines": each explained
    line goes to the last failing check whose missing-lines explanation
    names it, else to the first total with the unread check's label."""
    counted = {}
    for c in results:
        if not c["ok"] and c["kind"] != "unread" and c["explanation"]["kind"] == "missing-lines":
            for ref in c["explanation"]["lines"]:
                counted[(ref["check"], ref["line"])] = c["index"]
    include = []
    for c in results:
        if c["kind"] != "unread":
            continue
        section = next((o for o in results if o["kind"] != "unread" and o["label"] == c["label"]), None)
        for i, line in enumerate(c["lines"]):
            check = counted.get((c["index"], i), section["index"] if section else -1)
            include.append({"table": "brokerage_transactions", "check": check, "row": line["suggested"],
                            "line": {"check": c["index"], "line": i}})
    return {"include": include}


def _answered(result: dict, adjust: dict) -> list[dict]:
    tables, checks = result["tables"], result["checks"]
    statement_checks.apply_adjustments(tables, checks, adjust)
    parser_common.validate_multi_table_parse_result(result, "etrade_brokerage")
    return statement_checks.evaluate(checks, tables, result["statementDate"])


def test_sells_carry_a_negative_quantity_and_an_expiry_closes_the_side_traded() -> None:
    activity = list(ACTIVITY)
    at = activity.index("NET CREDITS/(DEBITS) $262.50")
    activity[at:at + 1] = [
        "3/24 3/25 Sold PUT BFC 03/19/27 60.000 ACTED AS AGENT 2.000 $0.0500 $10.00",
        "UNSOLICITED TRADE; CLOSING",
        "NET CREDITS/(DEBITS) $272.50",
    ]
    result, checks = _parse(_with_activity(activity))
    rows = result["tables"]["brokerage_transactions"]
    sold_to_open, _, _, sold_to_close, expired = rows
    assert sold_to_open["quantity"] == pytest.approx(1.0)
    assert sold_to_close["symbol"] == "BFC270319P60" and sold_to_close["quantity"] == pytest.approx(2.0)
    # Sold to close: the put was held, so its expiry takes 2 contracts away.
    assert expired["symbol"] == "BFC270319P60" and expired["quantity"] == pytest.approx(2.0)
    assert expired["subtype"] == "Out"
    assert all(c["ok"] for c in checks), checks


def test_an_added_line_leaves_every_check_holding() -> None:
    """A not-read line is counted in one total only, so after the user adds
    it nothing is left failing - with NET CREDITS/(DEBITS) printed, and with
    only opening and closing cash to go by."""
    activity = list(ACTIVITY)
    at = activity.index("NET CREDITS/(DEBITS) $262.50")
    activity[at:at + 1] = ["3/20 Goodwill Credit ACCOUNT ADJUSTMENT 25.00", "NET CREDITS/(DEBITS) $287.50"]
    pages = _with_activity(activity)
    pages[2] = pages[2].replace("CLOSING CASH, BDP, MMFs $1,262.50", "CLOSING CASH, BDP, MMFs $1,287.50")
    without_net = list(pages)
    without_net[-1] = without_net[-1].replace("NET CREDITS/(DEBITS) $287.50\n", "")

    for statement, total in ((pages, "sum"), (without_net, "balance")):
        result, checks = _parse(statement)
        by_label = [(c["kind"], c["label"], c["ok"]) for c in checks]
        assert (total, "CASH FLOW ACTIVITY BY DATE", False) in by_label
        assert ("unread", "CASH FLOW ACTIVITY BY DATE", False) in by_label
        adjust = _app_includes(result, checks)
        assert [inc["row"]["amount"] for inc in adjust["include"]] == [25.0]
        assert all(c["ok"] for c in _answered(result, adjust))


def test_money_moved_under_a_non_flow_word_holds_the_import() -> None:
    """The summary's Credits + Debits are the rows that move money in and
    out: $100 in that the rows book as interest fails that check instead of
    counting as investment gain."""
    rows = [
        "3/5 Deposit EXTERNAL CASH CONTRIBUTION $500.00",
        "3/10 Withdrawal CASH DISTRIBUTION $(200.00)",
        "3/20 Interest FUNDS FROM LINKED BANK $100.00",
        "3/28 Qualified Dividend SAMPLE TOTAL MARKET ETF $100.00",
    ]
    cash_flow = [
        "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
        "Cash, BDP, MMFs $1,000.00 $1,500.00 OPENING CASH, BDP, MMFs $1,000.00 $1,000.00",
        "CLOSING CASH, BDP, MMFs $1,500.00 $1,500.00",
    ]
    summary = _summary("$2,612.95", "600.00", "(200.00)", "$400.00", "(1,447.95)", "$1,565.00")
    result, checks = _parse(_activity_statement(rows, "$500.00", cash_flow, summary,
                                                _simple_holdings("$900.00", "$1,565.00")))
    by_kind = {(c["kind"], c["label"]): c for c in checks}
    assert by_kind[("sum", "CASH FLOW ACTIVITY BY DATE")]["ok"] is True
    flows = by_kind[("sum", "Credits/Debits")]
    assert flows["ok"] is False and (flows["parsed"], flows["expected"]) == (300.0, 400.0)


CORPORATE = [
    "TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY",
    "SECURITY TRANSFERS",
    "Activity",
    "Date Activity Type Security (Symbol) Comments Quantity Accrued Interest Amount",
    "3/2 Transfer into Account ALPHA WIDGETS INC (AWI) 20.000 — $2,400.00",
    "STOCK PLAN RELEASE",
    "3/9 Transfer out of Account BETA FOODS CORP (BFC) 10.000 — (655.00)",
    "TRANSFER TO",
    "111-222333-555",
    "SPECIFIC TAX LOT",
    "SELECTED",
    "3/16 Transfer into Account ALPHA WIDGETS INC (AWI) 10.000 $12.50 1,200.00",
    "STOCK PLAN RELEASE",
    "TOTAL SECURITY TRANSFERS $2,945.00",
    "OPTIONS EXPIRATIONS, EXERCISES AND ASSIGNMENTS",
    "Activity",
    "Date Activity Type Description Comments Contracts",
    "3/22 Option Expired PUT BFC 03/19/27 60.000 2.000",
    "EXPIRED OPTIONS",
    "3/23 Option Expired CALL BFC 03/19/27 70.000 1.000",
    "EXPIRED OPTIONS",
    "MESSAGES",
    "Options Disclosure Document Available",
]


def _corporate_pages(corporate: list[str]) -> list[str]:
    activity = ACTIVITY[:ACTIVITY.index("TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY")] + corporate
    return _with_activity(activity)


def test_comment_lines_under_a_transfer_never_end_the_table() -> None:
    result, checks = _parse(_corporate_pages(CORPORATE))
    rows = result["tables"]["brokerage_transactions"][3:]
    assert [(r["action"], r.get("symbol"), r.get("quantity"), r["amount"]) for r in rows] == [
        ("Transfer into Account", "AWI", 20.0, 2400.0),
        ("Transfer out of Account", "BFC", 10.0, -655.0),
        ("Transfer into Account", "AWI", 10.0, 1200.0),  # the accrued interest cell is not the quantity
        ("Option Expired", "BFC270319P60", 2.0, 0.0),
        ("Option Expired", "BFC270319C70", 1.0, 0.0),
    ]
    assert rows[0]["description"] == "ALPHA WIDGETS INC (AWI) STOCK PLAN RELEASE"
    assert rows[1]["description"] == "BETA FOODS CORP (BFC) TRANSFER TO SPECIFIC TAX LOT SELECTED"
    assert rows[4]["description"] == "CALL BFC 03/19/27 70.000 EXPIRED OPTIONS"
    transfers = next(c for c in checks if c["kind"] == "sum" and c["label"].startswith("TRANSFERS"))
    assert (transfers["parsed"], transfers["expected"]) == (2945.0, 2945.0)
    assert all(c["ok"] for c in checks), checks


def test_a_transfer_after_what_looked_like_the_tables_end_is_reported() -> None:
    corporate = CORPORATE[:6] + [
        "IMPORTANT NOTICE",
        "Shares released from your stock plan are shown at their market value on the release date.",
        "3/16 Transfer into Account ALPHA WIDGETS INC (AWI) 10.000 — 1,200.00",
        "TOTAL SECURITY TRANSFERS $3,600.00",
        "MESSAGES",
    ]
    result, checks = _parse(_corporate_pages(corporate))
    unread = next(c for c in checks if c["kind"] == "unread" and c["label"].startswith("TRANSFERS"))
    assert [line["text"] for line in unread["lines"]] == [
        "3/16 Transfer into Account ALPHA WIDGETS INC (AWI) 10.000 — 1,200.00"
    ]
    transfers = next(c for c in checks if c["kind"] == "sum" and c["label"].startswith("TRANSFERS"))
    assert transfers["ok"] is False and transfers["explanation"]["kind"] == "missing-lines"
    assert all(c["ok"] for c in _answered(result, _app_includes(result, checks)))


def test_tax_lot_and_fund_lot_blocks_read_across_pages_and_suffixes() -> None:
    summary = _summary("$28,000.00", "—", "—", "—", "654.00", "$28,654.00")
    lots_head = "Security Description Trade Date Quantity Unit Cost Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %"
    page_a = [
        "HOLDINGS",
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "MORGAN STANLEY BANK N.A. # $1,000.00 — — 0.050",
        "CASH, BDP, AND MMFs 3.49% $1,000.00 —",
        "STOCKS",
        "COMMON STOCKS",
        lots_head,
        # The term glued to the gain.
        "CONTOSO SOFTWARE CORP (CSFT) 3/14/25 100.000 $80.000 $115.000 $8,000.00 $11,500.00 $3,500.00LT",
        "418KDPLM",
    ]
    page_b = [
        "COMMON STOCKS (CONTINUED)",
        lots_head,
        # A footnote letter after the term.
        "6/2/26 50.000 92.500 115.000 4,625.00 5,750.00 1,125.00 ST A",
        "Total 150.000 12,625.00 17,250.00 4,625.00 LT 144.00 0.83",
        "Asset Class: Equities",
        "COMMON STOCKS $12,625.00 $17,250.00 $4,625.00 $144.00 0.83%",
        "STOCKS 60.20% $12,625.00 $17,250.00 $4,625.00 $144.00 0.83%",
        "MUTUAL FUNDS",
        "OPEN-END MUTUAL FUNDS",
        lots_head,
        # A fund in lot form: lots, then Purchases / Reinvestments, then Total.
        "REDWOOD BALANCED FUND CL A (RDBAX) 4/1/24 400.000 $23.000 $25.500 $9,200.00 $10,200.00 $1,000.00 LT",
        "2/18/27 8.000 25.000 25.500 200.00 204.00 4.00 ST",
        "Purchases 400.000 9,200.00 10,200.00 1,000.00 LT",
        "Short Term Reinvestments 8.000 200.00 204.00 4.00 ST",
        "Total 408.000 9,400.00 10,404.00 1,004.00 480.00 4.61",
        "Total Purchases vs Market Value 9,200.00 10,404.00",
        "Net Value Increase/(Decrease) 1,204.00",
        "MUTUAL FUNDS 36.31% $9,400.00 $10,404.00 $1,004.00 $480.00 4.61%",
        "TOTAL VALUE 100.00% $22,025.00 $28,654.00 $5,629.00 $624.00 2.18%",
    ]
    pages = [
        _cover(PERIOD, "$28,000.00", "$28,654.00"),
        _page(PERIOD, "Summary", summary),
        _page(PERIOD, "Detail", page_a, number=3),
        _page(PERIOD, "Detail", page_b, number=4),
    ]
    result, _ = _parse(pages)
    holdings = {h["symbol"]: h for h in result["tables"]["brokerage_holdings"]}
    assert list(holdings) == ["CASH", "CSFT", "RDBAX"]
    assert (holdings["CSFT"]["quantity"], holdings["CSFT"]["current_value"]) == (150.0, 17250.0)
    assert holdings["CSFT"]["cost_basis_total"] == pytest.approx(12625.0)
    assert (holdings["RDBAX"]["quantity"], holdings["RDBAX"]["current_value"]) == (408.0, 10404.0)
    assert holdings["RDBAX"]["type"] == "Mutual Fund"


def test_a_security_no_holding_names_gets_no_symbol() -> None:
    activity = list(ACTIVITY)
    activity[activity.index("3/15 Dividend SAMPLE TOTAL MARKET ETF 15.00")] = (
        # A scrambled sample fakes some words of a name on a dated line,
        # keeping their length: still the held ETF.
        "3/15 Dividend RAVITO TOTAL MARKET HEZ 15.00"
    )
    at = activity.index("NET CREDITS/(DEBITS) $262.50")
    activity[at:at + 1] = [
        # Sold out this month: shares two words with the held ETF's name.
        "3/12 3/13 Sold SAMPLE TOTAL BOND ETF ACTED AS AGENT 10.000 50.0000 500.00",
        "3/20 Dividend SAMPLE TOTAL BOND ETF 4.00",
        "NET CREDITS/(DEBITS) $766.50",
    ]
    result, checks = _parse(_with_activity(activity))
    symbols = [(r["action"], r.get("symbol", ""), r["description"][:20])
               for r in result["tables"]["brokerage_transactions"] if r["transaction_type"] != "corporate_action"]
    assert symbols == [
        ("Sold", "AWI270416C130", "CALL AWI 04/16/27 13"),
        ("Dividend", "STM", "RAVITO TOTAL MARKET "),
        ("Interest Income", "", "MORGAN STANLEY BANK "),
        ("Sold", "", "SAMPLE TOTAL BOND ET"),
        ("Dividend", "", "SAMPLE TOTAL BOND ET"),
    ]
    assert all(c["ok"] for c in checks), checks


def test_the_balance_sheets_unsettled_line_is_not_a_cash_flow_figure() -> None:
    def read(texts: list[str]) -> dict:
        lines = [etrade_brokerage._Line(1, no, text) for no, text in enumerate(texts, 1)]
        return etrade_brokerage._cash_flow_summary(lines)

    head = "BALANCE SHEET (^ includes accrued interest) CASH FLOW"
    # The month after a trade left unsettled at month end.
    after = read([
        head,
        "Cash, BDP, MMFs $1,000.00 $2,548.08 OPENING CASH, BDP, MMFs $2,417.36 —",
        "Net Unsettled Purchases/Sales 89.45 — Prior Net Unsettled Purchases/Sales 89.45 89.45",
        "Income and Distributions 41.27 965.77",
        "CLOSING CASH, BDP, MMFs $2,548.08 $2,417.36",
    ])
    assert (after["opening"], after["unsettled"], after["closing"]) == (2417.36, 89.45, 2548.08)
    alone = read([head, "OPENING CASH, BDP, MMFs $2,417.36 —", "Net Unsettled Purchases/Sales 89.45 —",
                  "Prior Net Unsettled Purchases/Sales 89.45 89.45", "CLOSING CASH, BDP, MMFs $2,548.08 —"])
    assert alone["unsettled"] == 89.45
    # The month of the trade.
    during = read([
        head,
        "Net Unsettled Purchases/Sales — (700.02) Sales and Redemptions 299.98 299.98",
        "Total Assets $1,450.00 $3,226.57 Net Unsettled Purch/Sales 700.02 700.02",
        "CLOSING CASH, BDP, MMFs $1,712.59 $1,712.59",
    ])
    assert during["unsettled"] == 700.02


def test_an_emptied_account_has_no_holdings_and_the_others_still_import() -> None:
    other = "111-222333-555"
    empty_summary = _summary("—", "—", "—", "—", "—", "—")
    for detail in (["MESSAGES", "Your account has no holdings or activity this period."],
                   ["HOLDINGS", "TOTAL VALUE — — — — —", "MESSAGES"]):
        pages = _base_pages() + [
            _page(PERIOD, "Summary", empty_summary, account=other, number=7),
            _page(PERIOD, "Detail", detail, account=other, number=8),
        ]
        result, checks = _parse(pages)
        assert {h["provider_account_id"] for h in result["tables"]["brokerage_holdings"]} == {ACCOUNT}
        assert len(result["tables"]["brokerage_holdings"]) == 5
        assert all(c["ok"] for c in checks)


def test_an_option_without_an_occ_code_never_takes_another_contracts_or_the_stocks_symbol() -> None:
    assert etrade_brokerage._occ_symbol("AWI1", etrade_brokerage._expiry("03/19/27"), "CALL", "50.000") == ""
    assert etrade_brokerage._occ_symbol("BRK'B", etrade_brokerage._expiry("03/19/27"), "CALL", "50.000") == "BRKB270319C50"
    pages = _base_pages()
    # An adjusted contract (deliverable changed by a corporate action).
    pages[3] = pages[3].replace("(AWI 270416C00130000)", "(AWI1 270416C00130000)")
    activity = list(ACTIVITY)
    at = activity.index("3/22 Option Expired PUT BFC 03/19/27 60.000 EXPIRED OPTIONS 2.000")
    activity[at + 1:at + 1] = [
        "3/23 Option Expired CALL AWI1 03/19/27 50.000 EXPIRED OPTIONS 1.000",
        "3/23 Option Expired PUT BETA FOODS CORP NEW 03/19/27 65.000 EXPIRED OPTIONS 1.000",
    ]
    pages[-1] = _page(PERIOD, "Detail", activity, number=6)
    result, checks = _parse(pages)
    holdings = [h["symbol"] for h in result["tables"]["brokerage_holdings"]]
    assert "AWI1 270416C00130000" in holdings and "AWI270416C130" not in holdings
    expired = [r for r in result["tables"]["brokerage_transactions"] if r["action"] == "Option Expired"]
    assert [r.get("symbol") for r in expired] == ["BFC270319P60", None, None]
    assert all(c["ok"] for c in checks), checks


def test_a_dash_amount_is_a_row_with_its_value_missing() -> None:
    activity = list(ACTIVITY)
    at = activity.index("3/15 Dividend SAMPLE TOTAL MARKET ETF 15.00")
    activity.insert(at + 1, "3/16 Dividend SAMPLE TOTAL MARKET ETF —")
    result, checks = _parse(_with_activity(activity))
    row = next(r for r in result["tables"]["brokerage_transactions"] if r["date"] == "2027-03-16")
    assert (row["transaction_type"], row["amount"], row["amount_missing"], row["symbol"]) == ("dividend", 0.0, True, "STM")
    assert all(c["ok"] for c in checks), checks


def test_detection_keeps_working_on_a_scrambled_legal_line() -> None:
    # A scrambler keeps "TRADE is a business of Morgan Stanley" (a parser
    # phrase) but fakes the single letter before the "*".
    head = "\n".join(_base_pages()[:3]).replace("E*TRADE is a business", "K*TRADE is a business")
    assert etrade_brokerage.detect(head)[0]
    wealth = head.replace("K*TRADE is a business of Morgan Stanley.", "Morgan Stanley Wealth Management")
    assert not etrade_brokerage.detect(wealth)[0]


# --- review round 2 ------------------------------------------------------------

CARD_ROWS = [
    "3/2 Funds Received ACH TRANSFER FROM BANK $1,000.00",
    "3/15 Dividend SAMPLE TOTAL MARKET ETF 48.75",
    "3/31 Margin Interest MARGIN INTEREST CHARGED (3.10)",
    "3/31 Interest Income MORGAN STANLEY BANK N.A. (Period 03/01-03/31) 0.40",
]
CARD_SECTIONS = [
    "CHECKING ACTIVITY",
    "Check Date Date",
    "Number Written Cleared Payee Amount",
    "1001 3/12 3/15 GREEN LAWN SERVICE (500.00)",
    "TOTAL CHECKING ACTIVITY $(500.00)",
    "DEBIT CARD ACTIVITY",
    "Transaction Settlement",
    "Date Date Merchant Amount",
    "3/8 3/9 Debit Card SUPERMARKET 123 SPRINGFIELD (84.20)",
    "3/19 3/20 Debit Card Refund HARDWARE STORE 15.00",
    "TOTAL DEBIT CARD ACTIVITY $(69.20)",
]


def _card_statement(rows=CARD_ROWS, net="$1,046.05", sections=CARD_SECTIONS, closing="$3,476.85",
                    debits="(587.30)", change_net="$427.70", ending="$4,141.85") -> list[str]:
    """Cash moved by check and debit card, listed in sections of their own
    after CASH FLOW ACTIVITY BY DATE: the summary counts them in Debits and
    in Total Card/Check Activity, NET CREDITS/(DEBITS) does not."""
    summary = _summary("$3,665.00", "1,015.00", debits, change_net, "49.15", ending)
    cash_flow = [
        "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
        f"Cash, BDP, MMFs $3,000.00 {closing} OPENING CASH, BDP, MMFs $3,000.00 $3,000.00",
        "Total Card/Check Activity (569.20) (569.20)",
        f"CLOSING CASH, BDP, MMFs {closing} {closing}",
    ]
    activity = [
        "ACTIVITY",
        "CASH FLOW ACTIVITY BY DATE",
        "Activity Settlement",
        "Date Date Activity Type Description Comments Quantity Price Credits/(Debits)",
        *rows,
        f"NET CREDITS/(DEBITS) {net}",
        *sections,
        "MESSAGES",
        "Nothing to report this period.",
    ]
    return [
        _cover(PERIOD, "$3,665.00", ending),
        _page(PERIOD, "Summary", summary + cash_flow),
        _page(PERIOD, "Detail", _simple_holdings(closing, ending), number=3),
        _page(PERIOD, "Detail", activity, number=4),
    ]


def test_card_and_check_rows_are_withdrawals_checked_against_the_cash_flow() -> None:
    """Spending by check or debit card leaves the account: never dropped as
    if it were investment loss, whatever else is on the statement."""
    result, checks = _parse(_card_statement())
    rows = result["tables"]["brokerage_transactions"]
    cards = [(r["date"], r["action"], r["transaction_type"], r["amount"], r["description"], r.get("reference"))
             for r in rows[4:]]
    assert cards == [
        ("2027-03-12", "Check", "withdrawal", -500.0, "GREEN LAWN SERVICE", "1001"),
        ("2027-03-08", "Debit Card", "withdrawal", -84.2, "SUPERMARKET 123 SPRINGFIELD", None),
        ("2027-03-19", "Debit Card Refund", "deposit", 15.0, "HARDWARE STORE", None),
    ]
    assert all(parser_common.classifies_as_flow(r) for r in rows[4:])
    by_kind = {(c["kind"], c["label"]): c for c in checks}
    card = by_kind[("sum", "CHECKING ACTIVITY / DEBIT CARD ACTIVITY")]
    assert (card["parsed"], card["expected"]) == (-569.2, -569.2)
    assert ("unread", "CHECKING ACTIVITY / DEBIT CARD ACTIVITY") in by_kind
    # Margin interest may or may not be in Debits: no Credits/Debits check.
    assert ("sum", "Credits/Debits") not in by_kind
    assert all(c["ok"] for c in checks), checks

    # Without it, the card rows count in Credits/Debits too.
    plain = [r for r in CARD_ROWS if "Margin" not in r]
    result, checks = _parse(_card_statement(plain, "$1,049.15", closing="$3,479.95", debits="(584.20)",
                                            change_net="$430.80", ending="$4,144.95"))
    flows = next(c for c in checks if c["label"] == "Credits/Debits")
    assert (flows["parsed"], flows["expected"]) == (430.8, 430.8)
    assert all(c["ok"] for c in checks), checks

    # Sections this parser cannot find: the import is held, never clean.
    result, checks = _parse(_card_statement(sections=[]))
    missing = next(c for c in checks if c["label"] == "Total Card/Check Activity")
    assert missing["ok"] is False and (missing["parsed"], missing["expected"]) == (0, -569.2)
    assert len(result["tables"]["brokerage_transactions"]) == 4

    # The same rows listed in CASH FLOW ACTIVITY BY DATE as well: the
    # sections repeat them, and they are read once.
    inside = CARD_ROWS + [
        "3/9 Debit Card SUPERMARKET 123 SPRINGFIELD (84.20)",
        "3/15 Check 1001 GREEN LAWN SERVICE (500.00)",
        "3/20 Debit Card Refund HARDWARE STORE 15.00",
    ]
    result, checks = _parse(_card_statement(inside, "$476.85"))
    rows = result["tables"]["brokerage_transactions"]
    assert [(r["action"], r["transaction_type"], r["amount"]) for r in rows[4:]] == [
        ("Debit Card", "withdrawal", -84.2), ("Check", "withdrawal", -500.0), ("Debit Card Refund", "deposit", 15.0),
    ]
    assert len(rows) == 7
    assert all(c["ok"] for c in checks), checks


def test_an_unread_money_line_once_added_leaves_every_check_holding() -> None:
    """A deposit under a word the parser does not know is in both the
    summary's Credits and NET CREDITS/(DEBITS), but the app adds it to one
    total: Credits/Debits is made only when every line was read."""
    rows = [
        "3/10 3/11 Sold BETA FOODS CORP ACTED AS AGENT 5.000 $80.0000 $399.95",
        "3/15 Qualified Dividend BETA FOODS CORP 48.75",
        "3/16 Incoming Transfer FROM EXTERNAL BANK 2,500.00",
        "3/31 Interest Income MORGAN STANLEY BANK N.A. (Period 03/01-03/31) 0.40",
    ]
    cash_flow = [
        "BALANCE SHEET (^ includes accrued interest) CASH FLOW",
        "Cash, BDP, MMFs $1,000.00 $3,949.10 OPENING CASH, BDP, MMFs $1,000.00 $1,000.00",
        "Total Card/Check Activity — —",
        "CLOSING CASH, BDP, MMFs $3,949.10 $3,949.10",
    ]
    summary = _summary("$2,000.00", "2,500.00", "—", "$2,500.00", "114.10", "$4,614.10")
    result, checks = _parse(_activity_statement(rows, "$2,949.10", cash_flow, summary,
                                                _simple_holdings("$3,949.10", "$4,614.10")))
    assert [(c["kind"], c["label"], c["ok"]) for c in checks] == [
        ("sum", "CASH FLOW ACTIVITY BY DATE", False),
        ("unread", "CASH FLOW ACTIVITY BY DATE", False),
    ]
    assert checks[0]["explanation"]["kind"] == "missing-lines"
    adjust = _app_includes(result, checks)
    assert [inc["row"]["amount"] for inc in adjust["include"]] == [2500.0]
    assert all(c["ok"] for c in _answered(result, adjust))


def test_a_trade_whose_name_the_column_cut_short_keeps_its_ticker() -> None:
    names = {
        "BEACON LIGHT MEDIA INC SER A": "BLMA",
        "LANTERN NETWORKS HOLDINGS CL B": "LNHB",
        "RAYMOND JAMES FINANCIAL INC": "RJF",
        "ISHARES MSCI JAPAN ETF": "EWJ",
    }
    tickers = set(names.values())
    for description, symbol in (
        ("BEACON LIGHT MEDIA INC ACTED AS AGENT", "BLMA"),
        ("BEACON LIGHT MEDIA INC SER ACTED AS AGENT", "BLMA"),
        ("BEACON LIGHT MEDIA INC SE ACTED AS PRINCIPAL", "BLMA"),
        ("LANTERN NETWORKS HOLDINGS ACTED AS AGENT", "LNHB"),
        ("RAYMOND JAMES ACTED AS AGENT", "RJF"),
        # Not held: a fund family's name with another word of the same length.
        ("ISHARES MSCI CHINA ETF", ""),
        ("RAYMOND ACTED AS AGENT", ""),
    ):
        assert etrade_brokerage._symbol_for(description, names, tickers) == symbol, description
    # A scrambled sample's fakes keep their length and alternate consonant
    # and vowel; a real word mostly does not.
    assert etrade_brokerage._fake_shaped("TAVOKENI") and not etrade_brokerage._fake_shaped("CHINA")

    activity = list(ACTIVITY)
    at = activity.index("NET CREDITS/(DEBITS) $262.50")
    activity[at:at + 1] = [
        "3/12 3/13 Bought ALPHA WIDGETS ACTED AS AGENT 10.000 $120.0000 $(1,200.00)",
        "INC UNSOLICITED TRADE",
        "NET CREDITS/(DEBITS) $(937.50)",
    ]
    result, checks = _parse(_with_activity(activity))
    bought = next(r for r in result["tables"]["brokerage_transactions"] if r["action"] == "Bought")
    assert (bought["symbol"], bought["quantity"]) == ("AWI", 10.0)
    assert all(c["ok"] for c in checks), checks


def _lots_pages(page_a: list[str], *more: list[str]) -> list[str]:
    summary = _summary("$28,000.00", "—", "—", "—", "654.00", "$28,654.00")
    return [
        _cover(PERIOD, "$28,000.00", "$28,654.00"),
        _page(PERIOD, "Summary", summary),
        _page(PERIOD, "Detail", page_a, number=3),
        *(_page(PERIOD, "Detail", page, number=4 + i) for i, page in enumerate(more)),
    ]


def test_a_parent_continued_heading_keeps_an_open_lot_or_fund_block() -> None:
    lots_head = "Security Description Trade Date Quantity Unit Cost Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %"
    page_a = [
        "HOLDINGS",
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "MORGAN STANLEY BANK N.A. # $1,000.00 — — 0.050",
        "CASH, BDP, AND MMFs 3.49% $1,000.00 —",
        "STOCKS",
        "COMMON STOCKS",
        lots_head,
        "CONTOSO SOFTWARE CORP (CSFT) 3/14/25 100.000 $80.000 $115.000 $8,000.00 $11,500.00 $3,500.00 LT",
    ]
    lots_rest = [
        lots_head,
        "6/2/26 50.000 92.500 115.000 4,625.00 5,750.00 1,125.00 ST",
        "Total 150.000 12,625.00 17,250.00 4,625.00 144.00 0.83",
        "COMMON STOCKS $12,625.00 $17,250.00 $4,625.00 $144.00 0.83%",
        "STOCKS 60.20% $12,625.00 $17,250.00 $4,625.00 $144.00 0.83%",
        "MUTUAL FUNDS",
        "OPEN-END MUTUAL FUNDS",
        lots_head,
        "REDWOOD BALANCED FUND CL A (RDBAX) 4/1/24 400.000 $23.000 $25.500 $9,200.00 $10,200.00 $1,000.00 LT",
    ]
    fund_rest = [
        lots_head,
        "2/18/27 8.000 25.000 25.500 200.00 204.00 4.00 ST",
        "Purchases 400.000 9,200.00 10,200.00 1,000.00 LT",
        "Short Term Reinvestments 8.000 200.00 204.00 4.00 ST",
        "Total 408.000 9,400.00 10,404.00 1,004.00 480.00 4.61",
        "MUTUAL FUNDS 36.31% $9,400.00 $10,404.00 $1,004.00 $480.00 4.61%",
        "TOTAL VALUE 100.00% $22,025.00 $28,654.00 $5,629.00 $624.00 2.18%",
    ]
    for stocks_heads, fund_heads in (
        (["STOCKS (CONTINUED)"], ["MUTUAL FUNDS (CONTINUED)"]),
        (["STOCKS (CONTINUED)", "COMMON STOCKS (CONTINUED)"],
         ["MUTUAL FUNDS (CONTINUED)", "OPEN-END MUTUAL FUNDS (CONTINUED)"]),
    ):
        result, _ = _parse(_lots_pages(page_a, stocks_heads + lots_rest, fund_heads + fund_rest))
        holdings = {h["symbol"]: h for h in result["tables"]["brokerage_holdings"]}
        assert (holdings["CSFT"]["quantity"], holdings["CSFT"]["current_value"]) == (150.0, 17250.0)
        assert (holdings["RDBAX"]["quantity"], holdings["RDBAX"]["current_value"]) == (408.0, 10404.0)


def test_a_preferred_tickers_hyphen_or_space_is_read_as_a_class_suffix() -> None:
    assert etrade_brokerage._ticker("HFC-PA") == "HFC.PA"
    assert etrade_brokerage._ticker("HFC PRA") == "HFC.PRA"
    assert etrade_brokerage._ticker("CL A") is None and etrade_brokerage._ticker("SER A") is None
    for printed, symbol in (("HFC-PA", "HFC.PA"), ("HFC PRA", "HFC.PRA"), ("HFC.PRA", "HFC.PRA")):
        holdings = [
            "HOLDINGS",
            "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
            "MORGAN STANLEY BANK N.A. # $1,000.00 — — 0.050",
            "CASH, BDP, AND MMFs 28.49% $1,000.00 —",
            "PREFERRED STOCKS",
            "Security Description Quantity Share Price Total Cost Market Value Gain/(Loss) Est Ann Income Yield %",
            f"HARBOR FINANCIAL CORP 5.250% PFD SER A ({printed}) 100.000 $25.100 $2,500.00 $2,510.00 $10.00 $131.25 5.23",
            "PREFERRED STOCKS 71.51% $2,500.00 $2,510.00 $10.00 $131.25 5.23%",
            "TOTAL VALUE 100.00% $2,500.00 $3,510.00 $10.00 $131.25 3.74%",
        ]
        pages = [
            _cover(PERIOD, "$3,510.00", "$3,510.00"),
            _page(PERIOD, "Summary", _summary("$3,510.00", "—", "—", "—", "—", "$3,510.00")),
            _page(PERIOD, "Detail", holdings, number=3),
        ]
        result, _ = _parse(pages)
        preferred = result["tables"]["brokerage_holdings"][-1]
        assert (preferred["symbol"], preferred["type"], preferred["current_value"]) == (symbol, "Preferred Stock", 2510.0)


# --- review round 3 ------------------------------------------------------------

def _read_holdings(texts: list[str], ending: float) -> tuple[list[dict], float]:
    lines = [etrade_brokerage._Line(1, no, text) for no, text in enumerate(["HOLDINGS", *texts], 1)]
    rows, total, _ = etrade_brokerage._holdings(lines, etrade_brokerage._Account(ACCOUNT), "2027-03-31", ending)
    return rows, total


def test_a_january_statements_december_card_rows_belong_to_the_year_before() -> None:
    from datetime import date

    january = (date(2032, 1, 1), date(2032, 1, 31))
    assert etrade_brokerage._resolve_date("12/28", *january) == "2031-12-28"
    assert etrade_brokerage._resolve_date("1/12", *january) == "2032-01-12"
    check = etrade_brokerage._card_row("1003 12/28 1/3 JOHN SMITH LANDSCAPING $(250.00)", "CHECKING ACTIVITY", *january)
    card = etrade_brokerage._card_row("12/30 1/2 GROCERY STORE SPRINGFIELD ZZ (60.00)", "DEBIT CARD ACTIVITY", *january)
    assert (check["date"], check["amount"]) == ("2031-12-28", -250.0)
    assert (card["date"], card["amount"]) == ("2031-12-30", -60.0)
    # A December statement's row posted in January is the next year's.
    assert etrade_brokerage._resolve_date("1/2", date(2031, 12, 1), date(2031, 12, 31)) == "2032-01-02"


def test_the_account_title_sets_the_account_type_never_the_holders_name() -> None:
    title = "Morgan Stanley at Work Self-Directed Account TEST HOLDER"
    roth = [page.replace(title, "Roth IRA TEST HOLDER") for page in _base_pages()]
    result, checks = _parse(roth)
    rows = result["tables"]["brokerage_holdings"] + result["tables"]["brokerage_transactions"]
    assert {row["accountType"] for row in rows} == {"Roth IRA"}
    assert all(c["ok"] for c in checks), checks

    # A holder named Roth on a self-directed account: the name is the
    # cover's mailing-address line, not part of the title.
    surname = [page.replace("TEST HOLDER", "DAVID ROTH") for page in _base_pages()]
    result, _ = _parse(surname)
    rows = result["tables"]["brokerage_holdings"] + result["tables"]["brokerage_transactions"]
    assert {row["accountType"] for row in rows} == {"Brokerage"}

    holders = {"ALEX QUILL &", "ALEX QUILL"}
    assert etrade_brokerage._account_title("Morgan Stanley at Work Roth IRA ALEX QUILL", holders) == \
        "Morgan Stanley at Work Roth IRA"
    assert etrade_brokerage._account_title("Active Assets Account IRA GOLDBERG &", set()) == "Active Assets Account"
    assert etrade_brokerage._account_title("Rollover IRA", set()) == "Rollover IRA"


def test_a_held_tickers_first_word_never_claims_another_issuers_rows() -> None:
    names = {"GE AEROSPACE": "GE", "ACME CORPORATION": "ACM"}
    tickers = set(names.values())
    for description, symbol in (
        ("GE VERNOVA INC ACTED AS AGENT", ""),          # a spin-off, not held
        ("GE VERNOVA INC FRACT SHARE LIQUIDATION", ""),
        ("GE AEROSPACE", "GE"),
        ("ACM ACME CORPORATION", "ACM"),                 # ticker, then the holding's name
        ("ACM", "ACM"),
    ):
        assert etrade_brokerage._symbol_for(description, names, tickers) == symbol, description

    activity = list(ACTIVITY)
    at = activity.index("NET CREDITS/(DEBITS) $262.50")
    activity[at:at + 1] = [
        "3/12 3/13 Sold BFC SPINCO INC ACTED AS AGENT 10.000 50.0000 500.00",
        "3/20 Dividend BFC BETA FOODS CORP 4.00",
        "NET CREDITS/(DEBITS) $766.50",
    ]
    result, checks = _parse(_with_activity(activity))
    rows = result["tables"]["brokerage_transactions"]
    assert [r.get("symbol", "") for r in rows if r["date"] in ("2027-03-12", "2027-03-20")] == ["", "BFC"]
    assert all(c["ok"] for c in checks), checks


def test_a_short_option_with_no_market_value_is_read_at_zero() -> None:
    head = [
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "MORGAN STANLEY BANK N.A. # $1,000.00 — — 0.050",
        "CASH, BDP, AND MMFs 33.33% $1,000.00 —",
        "STOCKS",
        "COMMON STOCKS",
        "BETA FOODS CORP (BFC) 100.000 $20.000 $1,500.00 $2,000.00 $500.00 — —",
        "Asset Class: Equities",
        "COMMON STOCKS $1,500.00 $2,000.00 $500.00 — —",
        'OPTIONS (Contract Prices are reported to only the third decimal (which may display as "$0.000"))',
    ]
    tail = [
        "(BFC 270416C00025000)",
        "Short Position; Asset Class: Equities",
        "OPTIONS $(40.00) — $40.00",
        "STOCKS 66.67% $1,460.00 $2,000.00 $540.00 — —",
        "Total Stocks (Long) $2,000.00",
        "TOTAL VALUE 100.00% $1,460.00 $3,000.00 $540.00 — —",
    ]
    for price, value in (("—", "—"), ("N/A", "N/A"), ("$0.000", "—"), ("$0.000", "N/A")):
        row = f"CALL BETA FOODS CORP AT 25.000 EXPIRES 04/16/2027 1.000 {price} $(40.00) {value} $40.00"
        rows, total = _read_holdings(head + [row] + tail, 3000.0)
        option = next(r for r in rows if r["type"] == "Options")
        assert (option["symbol"], option["quantity"], option["current_value"], option["cost_basis_total"]) == \
            ("BFC270416C25", -1.0, 0.0, -40.0)
        assert next(r for r in rows if r["symbol"] == "BFC")["quantity"] == 100.0
        assert total == 3000.0

    # A "Short Position" note under a row that was not read never turns the
    # position above it short.
    reader = etrade_brokerage._HoldingsReader()
    reader.read([etrade_brokerage._Line(1, no, text) for no, text in enumerate([
        "STOCKS", "COMMON STOCKS",
        "BETA FOODS CORP (BFC) 100.000 $20.000 $1,500.00 $2,000.00 $500.00 — —",
        "OPTIONS",
        "CALL BETA FOODS CORP AT 25.000 EXPIRES 04/16/2027 1.000 N/A N/A N/A N/A",
        "Short Position; Asset Class: Equities",
    ], 1)])
    assert reader.positions[0].quantity == 100.0


def test_cash_with_a_month_end_unsettled_trade_is_its_projected_settled_balance() -> None:
    stocks = [
        "STOCKS",
        "COMMON STOCKS",
        "BETA FOODS CORP (BFC) 100.000 $20.000 $1,500.00 $2,000.00 $500.00 — —",
        "COMMON STOCKS $1,500.00 $2,000.00 $500.00 — —",
        "STOCKS 44.38% $1,500.00 $2,000.00 $500.00 — —",
        "TOTAL VALUE 100.00% $1,500.00 $4,506.81 $500.00 — —",
    ]
    for subtotal in ("CASH, BDP, AND MMFs 0.97% $2,417.36 —", "CASH, BDP, AND MMFs $2,417.36 —"):
        rows, total = _read_holdings([
            "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
            "MORGAN STANLEY BANK N.A. # $2,417.36 — — 0.050",
            subtotal,
            "NET UNSETTLED PURCHASES/SALES $89.45",
            "CASH, BDP, AND MMFs (PROJECTED SETTLED BALANCE) 55.62% $2,506.81",
            *stocks,
        ], 4506.81)
        assert [(r["symbol"], r["current_value"]) for r in rows] == [("CASH", 2506.81), ("BFC", 2000.0)], subtotal
        assert total == 4506.81


def test_funds_paid_and_other_dividend_are_classified() -> None:
    from datetime import date

    period = (date(2027, 6, 1), date(2027, 6, 30))
    for text, expected in (
        ("6/29 Funds Paid ACH TRANSFER TO CHASE BANK XXXXXX4421 (6,000.00)", ("Funds Paid", "withdrawal", -6000.0)),
        ("6/24 Other Dividend SAMPLE LARGE CAP ETF 31.85", ("Other Dividend", "dividend", 31.85)),
    ):
        row = etrade_brokerage._cash_flow_row(None, etrade_brokerage._DATED_RE.match(text), *period)
        assert (row["action"], row["transaction_type"], row["amount"]) == expected


def test_money_moved_between_two_accounts_of_the_package_is_an_internal_transfer() -> None:
    other = "111-222333-555"

    def account(number: str, begin: str, credits: str, debits: str, net: str, ending: str, rows: list[str]):
        holdings = [
            "HOLDINGS",
            "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
            f"MORGAN STANLEY BANK N.A. # {ending} — — 0.050",
            f"CASH, BDP, AND MMFs 100.00% {ending} —",
            f"TOTAL VALUE 100.00% — {ending} N/A — —",
        ]
        activity = ["ACTIVITY", "CASH FLOW ACTIVITY BY DATE",
                    "Date Date Activity Type Description Comments Quantity Price Credits/(Debits)",
                    *rows, f"NET CREDITS/(DEBITS) {net}", "MESSAGES"]
        return [
            _page(PERIOD, "Summary", _summary(begin, credits, debits, net, "—", ending), account=number),
            _page(PERIOD, "Detail", holdings + activity, account=number, number=3),
        ]

    pages = [_cover(PERIOD, "$1,700.00", "$1,800.00")]
    pages += account(ACCOUNT, "$1,500.00", "—", "(500.00)", "$(500.00)", "$1,000.00",
                     ["3/12 Funds Transferred ACH TRANSFER (500.00)", f"TO {other}"])
    pages += account(other, "$200.00", "600.00", "—", "$600.00", "$800.00",
                     ["3/12 Funds Received ACH TRANSFER 500.00", f"FROM {ACCOUNT}",
                      "3/20 Funds Received ACH TRANSFER FROM 999-000000-111 100.00"])
    result, checks = _parse(pages)
    rows = result["tables"]["brokerage_transactions"]
    assert [(r["provider_account_id"], r["transaction_type"], r["amount"]) for r in rows] == [
        (ACCOUNT, "internal_transfer", -500.0),
        (other, "internal_transfer", 500.0),
        (other, "deposit", 100.0),  # from an account outside the statement: money in
    ]
    assert all(c["ok"] for c in checks), checks


def test_an_na_accrued_interest_cell_keeps_a_transfers_quantity() -> None:
    from datetime import date

    period = (date(2027, 5, 1), date(2027, 5, 31))
    for text, quantity, amount in (
        ("5/2 Transfer into Account ACME ROBOTICS INC (ACMR) 20.000 N/A 960.00", 20.0, 960.0),
        ("5/22 Transfer out of Account OLD MILL BANCORP (OMB) 30.000 N/A (600.00)", 30.0, -600.0),
        ("5/2 Transfer into Account ACME ROBOTICS INC (ACMR) 20.000 — 960.00", 20.0, 960.0),
    ):
        row = etrade_brokerage._corporate_row(etrade_brokerage._DATED_RE.match(text), *period)
        assert (row["_quantity"], row["_amount"]) == (quantity, amount), text
        assert "N/A" not in row["description"]


def test_a_fixed_income_subtotal_split_by_a_page_foot_still_closes_its_section() -> None:
    rows, total = _read_holdings([
        "CASH, BANK DEPOSIT PROGRAM AND MONEY MARKET FUNDS",
        "MORGAN STANLEY BANK N.A. # $6,150.00 — $3.00 0.050",
        "CASH, BDP, AND MMFs 38.45% $6,150.00 $3.00",
        "CORPORATE FIXED INCOME",
        "CORPORATE BONDS",
        "DELTA POWER CO 10,000.000 98.250 10,050.00 450.00 4.58",
        "Coupon Rate 4.500%; Matures 03/15/2032; CUSIP 24702RAB7 10,020.00 9,825.00 (195.00) 18.75",
        "Percentage Orig Total Cost Unrealized Est Ann Income Current",
        "CORPORATE FIXED INCOME 10,000.000 $10,050.00 $450.00 4.58%",
        "418KDPLM",
        "903311",
        "CORPORATE FIXED INCOME (CONTINUED)",
        "of Holdings Face Value Adj Total Cost Market Value Gain/(Loss) Accrued Interest Yield %",
        "$10,020.00 $9,825.00 $(195.00) $18.75",
        "TOTAL CORPORATE FIXED INCOME 61.55% $9,843.75",
        "(includes accrued interest)",
        "TOTAL VALUE 100.00% $16,170.00 $15,993.75 $(195.00) $21.75 2.00%",
    ], 15993.75)
    assert [(r["symbol"], r["current_value"]) for r in rows] == [("CASH", 6150.0), ("24702RAB7", 9825.0)]
    assert total == 15993.75


# --- corporate actions as orby-core's tax lots read them ----------------------

def _shares_after_split(before: float, row: dict) -> float:
    """orby-core's pkg/ingest/tax_lots.go applySplitRatio: every open lot is
    scaled by (before + change) / before, so a split row's quantity has to be
    the size of the change in shares, never the new total, with the direction
    in subtype (Out for a reverse split)."""
    change = -row["quantity"] if row["subtype"] == "Out" else row["quantity"]
    return before * ((before + change) / before)


def test_split_rows_carry_the_signed_share_change_tax_lots_apply() -> None:
    # Holdings print the month-end (post-split) quantities: AWI 100, BFC 50
    # and STM 40, so the splits took them from 50, 250 and 160 shares.
    activity = list(ACTIVITY)
    at = activity.index("3/22 Option Expired PUT BFC 03/19/27 60.000 EXPIRED OPTIONS 2.000")
    activity[at + 1:at + 1] = [
        "CORPORATE ACTIONS",
        "Activity",
        "Date Activity Type Description Comments Quantity",
        "3/5 Stock Split ALPHA WIDGETS INC (AWI) 2 FOR 1 SPLIT 50.000",
        "3/6 Reverse Split BETA FOODS CORP (BFC) 1 FOR 5 REVERSE SPLIT (200.000)",
        # Printed unsigned, as this section prints contracts: a reverse split
        # still only removes shares.
        "3/7 Reverse Stock Split SAMPLE TOTAL MARKET ETF (STM) 1 FOR 4 REVERSE SPLIT 120.000",
        "3/8 Stock Dividend ALPHA WIDGETS INC (AWI) 2% STOCK DIVIDEND 2.000",
        "3/9 Spin-Off GAMMA PARTS CORP (GPC) SPIN-OFF FROM AWI 10.000",
        "3/12 Merger Out OLD MILL BANCORP (OMB) (30.000)",
        "3/12 Merger In BETA FOODS CORP (BFC) 15.000",
        "3/13 Exchange Delivered Out DELTA HOLDINGS CL A (DHA) (20.000)",
        "3/13 Exchange Received In DELTA HOLDINGS CL B (DHB) 20.000",
    ]
    pages = _base_pages()
    pages[-1] = _page(PERIOD, "Detail", activity, number=6)
    result, checks = _parse(pages)
    assert all(c["ok"] for c in checks), checks

    rows = {r["action"]: r for r in result["tables"]["brokerage_transactions"]
            if r["transaction_type"] == "corporate_action" and r["action"] != "Option Expired"}
    got = {action: (r["symbol"], r["quantity"], r["subtype"], r["amount"], parser_common.corporate_event(r))
           for action, r in rows.items()}
    assert got == {
        # The vocabulary's "split"/"reverse_split" events: lots are rescaled.
        "Stock Split": ("AWI", 50.0, "In", 0.0, "split"),
        "Reverse Split": ("BFC", 200.0, "Out", 0.0, "reverse_split"),
        "Reverse Stock Split": ("STM", 120.0, "Out", 0.0, "reverse_split"),
        # No event: tax lots flag the position rather than rescale it.
        "Stock Dividend": ("AWI", 2.0, "In", 0.0, ""),
        "Spin-Off": ("GPC", 10.0, "In", 0.0, ""),
        "Exchange Delivered Out": ("DHA", 20.0, "Out", 0.0, ""),
        "Exchange Received In": ("DHB", 20.0, "In", 0.0, ""),
        # Read by their exact action as merger_out / merger_in legs.
        "Merger Out": ("OMB", 30.0, "Out", 0.0, ""),
        "Merger In": ("BFC", 15.0, "In", 0.0, ""),
    }
    assert _shares_after_split(50.0, rows["Stock Split"]) == pytest.approx(100.0)
    assert _shares_after_split(250.0, rows["Reverse Split"]) == pytest.approx(50.0)
    assert _shares_after_split(160.0, rows["Reverse Stock Split"]) == pytest.approx(40.0)
