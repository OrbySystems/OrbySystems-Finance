"""Privacy and stability tests for reportable parser diagnostics."""

from __future__ import annotations

import json
from types import SimpleNamespace

import parser_common


def test_provisional_failure_excludes_raw_exception_and_marker_text() -> None:
    module = SimpleNamespace(
        __name__="institutions.test_brokerage",
        INSTITUTION="Example Brokerage",
        SUPPORT_TIER=parser_common.SUPPORT_TIER_PROVISIONAL,
        DIAGNOSTIC_MARKERS={"activity": "Account Activity", "holdings": "Positions"},
    )
    private_row = "01/15 SECRET FUND ABCDX $98,765.43 Account 123456789"
    message, diagnostic = parser_common.parser_failure(
        module,
        ValueError(f"unclassified activity row: {private_row}"),
        "pdf",
        {"pageCount": 6, "textPageCount": 5},
        "Account Activity\nPositions\n" + private_row,
    )

    encoded = json.dumps({"message": message, "diagnostic": diagnostic})
    assert diagnostic["supportTier"] == "provisional"
    assert diagnostic["code"] == "PARSER_UNCLASSIFIED_ROW"
    assert diagnostic["stage"] == "activity"
    assert diagnostic["sections"] == {"activity": True, "holdings": True}
    assert diagnostic["pageCount"] == 6
    for private in (private_row, "ABCDX", "98,765.43", "123456789"):
        assert private not in encoded


def test_unknown_format_diagnostic_excludes_detection_reasons() -> None:
    diagnostic = parser_common.unsupported_format_diagnostic(
        "pdf", {"pageCount": 3, "textPageCount": 2}
    )
    assert diagnostic == {
        "schemaVersion": 3,
        "reference": "PARSER-NOT-FOUND",
        "code": "PARSER_NOT_FOUND",
        "parserId": "",
        "institution": "",
        "supportTier": "unsupported",
        "inputFormat": "pdf",
        "stage": "detection",
        "pageCount": 3,
        "textPageCount": 2,
    }


def test_missing_fields_are_explicit_and_module_allowlisted() -> None:
    module = SimpleNamespace(
        __name__="institutions.test_brokerage",
        INSTITUTION="Example Brokerage",
        DIAGNOSTIC_FIELDS={
            "beginningBalance": "Beginning Balance",
            "endingBalance": "Ending Balance",
        },
        DIAGNOSTIC_SIGNALS=("contributions", "withdrawals"),
        DIAGNOSTIC_COUNTS=("activityLabelRows", "unclassifiedActivityLabels"),
        DIAGNOSTIC_TERMS=("allocation", "transfer"),
        PARSER_REVISION=7,
    )
    error = parser_common.ParserDiagnosticError(
        "internal detail with Account 123456789 and $98,765.43",
        code="PARSER_REQUIRED_DATA_MISSING",
        stage="activity",
        missing_fields=("endingBalance", "privateAccount123456789", "endingBalance"),
        signals={"contributions": True, "privateAccount123456789": True},
        counts={"activityLabelRows": 4, "privateAmount98765": 98765},
        unclassified_terms=("allocation", "privateAccount123456789"),
        reconciliation_direction="printedEndingAboveParsedEquation",
    )
    message, diagnostic = parser_common.parser_failure(
        module, error, "pdf", {}, "Beginning Balance $10,000.00"
    )

    assert diagnostic["code"] == "PARSER_REQUIRED_DATA_MISSING"
    assert diagnostic["stage"] == "activity"
    assert diagnostic["fieldPresence"] == {
        "beginningBalance": True,
        "endingBalance": False,
    }
    assert diagnostic["missingFields"] == ["endingBalance"]
    assert diagnostic["signals"] == {"contributions": True}
    assert diagnostic["counts"] == {"activityLabelRows": 4}
    assert diagnostic["unclassifiedLabelTerms"] == ["allocation"]
    assert diagnostic["reconciliationDirection"] == "printedEndingAboveParsedEquation"
    assert diagnostic["parserRevision"] == 7
    encoded = json.dumps({"message": message, "diagnostic": diagnostic})
    assert "123456789" not in encoded
    assert "98,765.43" not in encoded


def test_external_parser_cannot_publish_missing_fields() -> None:
    module = SimpleNamespace(
        __name__="local_parser",
        DIAGNOSTIC_FIELDS=("account123456789",),
    )
    error = parser_common.ParserDiagnosticError(
        "internal",
        code="PARSER_REQUIRED_DATA_MISSING",
        stage="activity",
        missing_fields=("account123456789",),
        signals={"account123456789": True},
        counts={"account123456789": 1},
        unclassified_terms=("account123456789",),
        reconciliation_direction="printedEndingBelowParsedEquation",
    )
    _, diagnostic = parser_common.parser_failure(module, error, "pdf", {}, "")

    assert "missingFields" not in diagnostic
    assert "signals" not in diagnostic
    assert "counts" not in diagnostic
    assert "unclassifiedLabelTerms" not in diagnostic
    assert "reconciliationDirection" not in diagnostic


def test_enrich_parser_error_preserves_specific_metadata_and_adds_context() -> None:
    original = parser_common.ParserDiagnosticError(
        "private $123.45 detail",
        code="PARSER_RECONCILIATION_FAILED",
        stage="summary",
        signals={"endingBalance": True},
        counts={"summaryComponents": 6},
        reconciliation_direction="printedEndingAboveParsedEquation",
    )
    enriched = parser_common.enrich_parser_error(
        original,
        signals={"beginningBalance": True, "endingBalance": False},
        counts={"financialLabelRows": 8, "summaryComponents": 5},
        unclassified_terms=("transfer",),
    )

    assert enriched.diagnostic_code == "PARSER_RECONCILIATION_FAILED"
    assert enriched.diagnostic_stage == "summary"
    assert enriched.diagnostic_signals == {
        "beginningBalance": True,
        "endingBalance": True,
    }
    assert enriched.diagnostic_counts == {
        "financialLabelRows": 8,
        "summaryComponents": 6,
    }
    assert enriched.unclassified_terms == ("transfer",)
    assert enriched.reconciliation_direction == "printedEndingAboveParsedEquation"
