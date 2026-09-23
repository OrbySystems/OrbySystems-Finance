from conftest import approx


def test_fidelity_netbenefits_401k_csv_synthetic(run_statement):
    stmt = run_statement(
        "fidelity-netbenefits-401k-csv-synthetic-sample.csv",
        "--expected-parser",
        "fidelity_netbenefits_401k_csv.py",
    )

    assert stmt.institution == "Fidelity NetBenefits"
    assert len(stmt.transactions) == 0
    assert len(stmt.brokerage_holdings) == 0
    assert len(stmt.brokerage_transactions) == 7

    for txn in stmt.brokerage_transactions:
        assert txn["account"] == ""
        assert txn["accountType"] == "401(k)"

    dividend = stmt.brokerage_transactions[0]
    assert dividend["date"] == "2026-06-25"
    assert dividend["description"] == "Dividend - SYNTH GROWTH FUND"
    assert dividend["action"] == "Dividend"
    assert dividend["symbol"] == "SYNTH GROWTH FUND"
    assert dividend["transaction_type"] == "dividend"
    assert dividend["subtype"] == "interest"
    assert approx(dividend["amount"], 1928.69)
    assert approx(dividend["quantity"], 115.076)

    revenue = stmt.brokerage_transactions[1]
    assert revenue["action"] == "Revenue Credit"
    assert revenue["transaction_type"] == "income"
    assert revenue["subtype"] == "other_income"
    assert approx(revenue["amount"], 14.46)

    exchange_out = stmt.brokerage_transactions[2]
    assert exchange_out["description"] == "Exchange Out - SYNTH BOND FUND"
    assert exchange_out["action"] == "Transfer Out"
    assert exchange_out["transaction_type"] == "internal_transfer"
    assert exchange_out["subtype"] == "transfer"
    assert approx(exchange_out["amount"], -500.00)
    assert approx(exchange_out["quantity"], -40.0)

    change_in_mv = stmt.brokerage_transactions[3]
    assert change_in_mv["action"] == "Change In Market Value"
    assert change_in_mv["transaction_type"] == "other"
    assert approx(change_in_mv["amount"], 25.00)
    assert approx(change_in_mv["quantity"], 0.0)

    exchange_in = stmt.brokerage_transactions[4]
    assert exchange_in["description"] == "Exchange In - SYNTH GROWTH FUND"
    assert exchange_in["action"] == "Transfer In"
    assert exchange_in["transaction_type"] == "internal_transfer"
    assert exchange_in["subtype"] == "transfer"
    assert approx(exchange_in["amount"], 500.00)

    # The two exchange legs net to zero - an internal move between funds,
    # not new money entering the account.
    assert approx(exchange_out["amount"] + exchange_in["amount"], 0.00)

    contribution = stmt.brokerage_transactions[5]
    assert contribution["action"] == "Contributions"
    assert contribution["transaction_type"] == "contribution"
    assert approx(contribution["amount"], 250.00)

    balance_forward = stmt.brokerage_transactions[6]
    assert balance_forward["date"] == "2010-06-23"
    assert balance_forward["action"] == "Balance Forward"
    assert balance_forward["transaction_type"] == "other"
    assert approx(balance_forward["amount"], 3000.00)
