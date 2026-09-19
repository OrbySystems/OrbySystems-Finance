import json

import pytest

import parser_common
from conftest import approx
from institutions import fidelity_401k_brokerage_pdf as netbenefits


def test_fidelity_401k_brokerage_pdf_synthetic(run_statement):
    stmt = run_statement("fidelity-401k-brokerage-pdf-synthetic-sample.pdf")

    assert stmt.institution == "Fidelity NetBenefits"
    assert stmt.statement_date == "2026-06-30"
    assert len(stmt.transactions) == 0

    assert len(stmt.brokerage_holdings) == 3
    first_holding = stmt.brokerage_holdings[0]
    assert first_holding["account"] == "2468"
    assert first_holding["accountType"] == "401(k)"
    assert first_holding["symbol"] == "SYNTHETIC GROWTH INDEX FUND"
    assert first_holding["description"] == "Synthetic Growth Index Fund"
    assert approx(first_holding["quantity"], 60.0)
    assert approx(first_holding["price"], 101.25)
    assert approx(first_holding["current_value"], 6075.00)

    assert len(stmt.brokerage_transactions) == 6
    first_txn = stmt.brokerage_transactions[0]
    assert first_txn["account"] == "2468"
    assert first_txn["accountType"] == "401(k)"
    assert first_txn["date"] == "2026-06-30"
    assert first_txn["description"] == "Exchange In - Synthetic Growth Index"
    assert first_txn["action"] == "Transfer In"
    assert approx(first_txn["amount"], 500.00)

    out = stmt.brokerage_transactions[1]
    assert out["description"] == "Exchange Out - Blue Horizon Bond"
    assert out["action"] == "Transfer Out"
    assert approx(out["amount"], -250.00)

    revenue = stmt.brokerage_transactions[2]
    assert revenue["description"] == "Revenue Credit - Synthetic Growth Index"
    assert revenue["action"] == "Revenue Credit"
    assert approx(revenue["amount"], 10.00)

    div = stmt.brokerage_transactions[5]
    assert div["description"] == "Dividends & Interest - Blue Horizon Bond"
    assert div["action"] == "Dividend/Interest"
    assert approx(div["amount"], 12.50)


def test_fidelity_401k_omitted_zero_activity_rows(run_statement):
    stmt = run_statement("fidelity-401k-zero-omitted-synthetic-sample.pdf")

    assert stmt.institution == "Fidelity NetBenefits"
    assert stmt.statement_date == "2026-09-17"
    assert len(stmt.brokerage_holdings) == 2
    assert len(stmt.brokerage_transactions) == 4
    revenue = [txn for txn in stmt.brokerage_transactions if txn["action"] == "Revenue Credit"]
    dividends = [txn for txn in stmt.brokerage_transactions if txn["action"] == "Dividend/Interest"]
    assert len(revenue) == 2
    assert len(dividends) == 2
    assert approx(sum(txn["amount"] for txn in revenue), 60.84)


def test_fidelity_401k_generic_exchange_and_separate_dividends(run_statement):
    stmt = run_statement("fidelity-401k-generic-exchange-synthetic-sample.pdf")

    assert stmt.institution == "Fidelity NetBenefits"
    assert stmt.statement_date == "2026-09-30"
    assert len(stmt.brokerage_holdings) == 3
    assert len(stmt.brokerage_transactions) == 6

    exchanges = [txn for txn in stmt.brokerage_transactions if txn["subtype"] == "transfer"]
    assert len(exchanges) == 3
    assert exchanges[0]["account"] == "9753"
    assert exchanges[0]["description"] == "Exchange Out - Synthetic Growth Index"
    assert exchanges[0]["action"] == "Transfer Out"
    assert approx(exchanges[0]["amount"], -500.00)
    assert exchanges[1]["description"] == "Exchange In - Blue Horizon Bond"
    assert exchanges[1]["action"] == "Transfer In"
    assert approx(exchanges[1]["amount"], 200.00)
    assert exchanges[2]["description"] == "Exchange In - Stable Value"
    assert exchanges[2]["action"] == "Transfer In"
    assert approx(exchanges[2]["amount"], 300.00)
    assert approx(sum(txn["amount"] for txn in exchanges), 0.00)

    dividends = [txn for txn in stmt.brokerage_transactions if txn["action"] == "Dividend/Interest"]
    assert len(dividends) == 3
    assert approx(sum(txn["amount"] for txn in dividends), 50.00)


def test_fidelity_401k_v4_label_aliases_are_canonicalized():
    lines = [
        "Your Account Activity",
        "Beginning Balance $100.00",
        "Exchanges -$20.00 $20.00 $0.00",
        "Change In Market Value $10.00",
        "Dividend & Interest $5.00",
        "Ending Balance $115.00",
        "Your Account Information",
    ]

    assert netbenefits._activity_totals(lines) == {
        "Beginning Balance": 100.0,
        "Exchange": 0.0,
        "Change In Market Value": 10.0,
        "Dividends & Interest": 5.0,
        "Ending Balance": 115.0,
    }
    signals, counts, terms = netbenefits._activity_diagnostic_context(lines)
    assert signals["exchange"] is True
    assert signals["dividendsInterest"] is True
    assert counts["unclassifiedActivityLabels"] == 0
    assert terms == []


def test_fidelity_401k_reconciliation_report_has_safe_activity_structure():
    lines = [
        "Your Account Activity",
        "Beginning Balance $100.00",
        "Contributions $25.00",
        "Special Allocation $5.00",
        "Change In Market Value $10.00",
        "Ending Balance $140.00",
        "Your Account Information",
    ]
    signals, counts, terms = netbenefits._activity_diagnostic_context(lines)
    counts.update(
        {
            "parsedActivityComponents": 3,
            "emittedActivityRows": 0,
            "holdingsParsed": 0,
        }
    )

    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        netbenefits._validate(
            [],
            None,
            {
                "Beginning Balance": 100.0,
                "Change In Market Value": 10.0,
                "Ending Balance": 140.0,
            },
            signals,
            counts,
            terms,
        )

    _, diagnostic = parser_common.parser_failure(
        netbenefits,
        raised.value,
        "pdf",
        {"pageCount": 3, "textPageCount": 3},
        "\n".join(lines),
    )

    assert diagnostic["schemaVersion"] == 3
    assert diagnostic["signals"]["contributions"] is True
    assert diagnostic["signals"]["withdrawals"] is False
    assert diagnostic["counts"] == {
        "activityLabelRows": 5,
        "recognizedActivityLabels": 4,
        "unclassifiedActivityLabels": 1,
        "parsedActivityComponents": 3,
        "emittedActivityRows": 0,
        "holdingsParsed": 0,
        "maxAmountsPerActivityRow": 1,
        "negativeActivityRows": 0,
        "unclassifiedPositiveLabels": 1,
        "unclassifiedNegativeLabels": 0,
        "unclassifiedZeroLabels": 0,
        "unclassifiedLabelWords": 2,
        "reconciliationCandidates": 1,
    }
    assert diagnostic["unclassifiedLabelTerms"] == ["allocation"]
    assert diagnostic["reconciliationDirection"] == "printedEndingAboveParsedEquation"
    assert diagnostic["parserRevision"] == 5
    encoded = json.dumps(diagnostic)
    assert "Special Allocation" not in encoded
    assert "$100.00" not in encoded
