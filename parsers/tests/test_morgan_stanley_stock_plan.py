"""Coverage for Morgan Stanley participant share purchase statements."""

from __future__ import annotations

import pytest

from institutions import morgan_stanley_stock_plan as parser


PAGES = [
    """STATEMENT For the Period October 1 (cid:151) December 31, 2021
Morgan Stanley Smith Barney LLC. Member SIPC.
Plan Number: 123F Morgan Stanley Global Stock Plan Services
Issuer Description: EXAMPLE INC CL C P.O. Box 123
Account Number: MS987654
Share Purchase and Holdings Summary
Opening Value Closing Value
(as of 10/1/21) (as of 12/31/21)
Number of Shares 2.000 3.000
Share Price $10.0000 $12.0000
Share Value $20.00 $36.00
Cash Value $0.00 $0.00
Net Unsettled Cash $0.00 $0.00
Total Account Value $20.00 $36.00
The quarter-end market closing price is utilized to calculate the Share Value.
""",
    """STATEMENT For the Period October 1 (cid:151) December 31, 2021 Page2 of 3
Account Number: MS987654
SHARE PURCHASE AND HOLDINGS
Gross
Transaction Date Activity Type Quantity Price Amount Total Taxes and Fees Total Net Amount
10/25/21 Release 2.000 $11.0000
10/28/21 Sale 1.000 12.0000 $12.00 $0.10 $11.90
11/1/21 Proceeds Disbursement (11.90)
Sell Transactions are provided as of trade date.
""",
]


def test_stock_plan_statement_extracts_reconciled_holdings_and_activity() -> None:
    matched, _ = parser.detect("\n".join(PAGES))
    assert matched
    result = parser.parse(PAGES, "synthetic.pdf")
    assert result["institution"] == "Morgan Stanley Global Stock Plan Services"
    assert result["statementDate"] == "2021-12-31"
    holding, = result["tables"]["brokerage_holdings"]
    assert holding["quantity"] == 3.0
    assert holding["current_value"] == 36.0
    assert holding["symbol"] == "EXAMPLE INC CL C"
    rows = result["tables"]["brokerage_transactions"]
    assert [row["transaction_type"] for row in rows] == ["transfer_in", "sell", "withdrawal"]
    assert [row["amount"] for row in rows] == [22.0, 11.9, -11.9]
    assert rows[1]["commission_and_fees"] == 0.1


def test_stock_plan_rejects_unreconciled_share_balance() -> None:
    broken = [PAGES[0].replace("Number of Shares 2.000 3.000", "Number of Shares 2.000 4.000"), PAGES[1]]
    with pytest.raises(ValueError, match="share value does not reconcile"):
        parser.parse(broken, "synthetic.pdf")


def test_stock_plan_rejects_unknown_activity() -> None:
    broken = [PAGES[0], PAGES[1].replace("10/25/21 Release 2.000 $11.0000", "10/25/21 Dividend $22.00")]
    with pytest.raises(ValueError, match="unsupported.*activity row"):
        parser.parse(broken, "synthetic.pdf")


def test_stock_plan_detection_requires_its_specific_layout() -> None:
    matched, _ = parser.detect("Morgan Stanley Smith Barney LLC\nCLIENT STATEMENT\nAccount Summary\nHOLDINGS")
    assert not matched
