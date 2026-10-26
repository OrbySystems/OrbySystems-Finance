"""Privacy and stability tests for reportable parser diagnostics."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

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
        "schemaVersion": 5,
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


def test_unknown_format_diagnostic_says_whether_it_reads_like_a_statement() -> None:
    statement = [
        "LAKESHORE CREDIT UNION\nStatement Period 01/01/2026 - 01/31/2026\n"
        "Beginning Balance $1,234.56\n01/05 PAYMENT TO MOSBY 20.00 1,214.56\n"
        "01/09 DEPOSIT 100.00 1,314.56\nEnding Balance $1,314.56"
    ]
    diagnostic = parser_common.unsupported_format_diagnostic("pdf", {"pageCount": 1}, statement)
    assert diagnostic["signals"]["beginningBalance"] and diagnostic["signals"]["endingBalance"]
    assert diagnostic["counts"] == {"financialLabelRows": 4, "datedActivityRows": 2}
    encoded = json.dumps(diagnostic)
    for private in ("LAKESHORE", "MOSBY", "1,234.56", "Beginning Balance"):
        assert private not in encoded

    letter = ["Dear member,\nThank you for being with us since 2001.\nRegards"]
    diagnostic = parser_common.unsupported_format_diagnostic("pdf", {"pageCount": 1}, letter)
    assert "signals" not in diagnostic
    assert diagnostic["counts"] == {"financialLabelRows": 0, "datedActivityRows": 0}


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


def _bundled(**attrs) -> SimpleNamespace:
    return SimpleNamespace(__name__="institutions.test_card", INSTITUTION="Example Card", **attrs)


def test_line_shape_masks_letters_and_digits_and_names_other_characters() -> None:
    assert parser_common.line_shape("Billing Period: 10/15/25-11/14/25") == "Aaaaaaa Aaaaaa: 99/99/99-99/99/99"
    assert parser_common.line_shape("Billing\u00a0Period:\t10/15/25\u201311/14/25") == (
        "Aaaaaaa<U+00A0>Aaaaaa:<U+0009>99/99/99<U+2013>99/99/99")
    # A letter or digit of any script is masked like any other, so it can't
    # be read back; an amount says nothing of its size, nor a dollar sign
    # alone of one.
    assert parser_common.line_shape("Caf\u00e9 $4.50") == "Aaaa <amount>"
    assert parser_common.line_shape("Jos\u00e9 M\u00fcller \u0418\u0432\u0430\u043d \u738b\u5c0f\u660e") == "Aaaa Aaaaaa Aaaa aaa"
    assert parser_common.line_shape("$\uff11,\uff12\uff13\uff14.\uff15\uff16 \U0001d7cf\U0001d7d0 \ufb01 \ue041") == (
        "<amount> 99 a <pua>")
    assert parser_common.line_shape("New balance -$1,234.56 CR (98.76)") == "Aaa aaaaaaa -<amount> AA (<amount>)"
    assert parser_common.line_shape("Value ($) 1.234,56") == "Aaaaa (<U+0024>) <amount>"
    # A dotted date is not an amount.
    assert parser_common.line_shape("Datum 01.10.2025") == "Aaaaa 99.99.9999"
    long = parser_common.line_shape("\u00a0" * 100)
    assert len(long) <= 160 and long == "<U+00A0>" * 20
    assert parser_common.line_shape("x" * 500) == "a" * 100


def test_field_lines_say_how_each_label_was_found_without_the_text() -> None:
    module = _bundled(DIAGNOSTIC_FIELDS={
        "billingPeriod": "Billing Period",
        "newBalance": "New balance",
        "previousBalance": "Previous balance",
        "paymentDueDate": "Payment Due Date",
        "creditLimit": "Credit Limit",
        "minimumPaymentDue": "Minimum Payment Due",
    })
    pages = [
        "MOSBY TRAVEL CARD\nBilling\u00a0Period: 10/15/25-11/14/25\nNew balance $1,234.56",
        "",
        "PPrreevviioouuss  bbaallaannccee $98.76\nPayment Due\nDate 12/10/25\nCredit Limit\n\n$5,000.00",
    ]
    _, diagnostic = parser_common.parser_failure(
        module, ValueError("internal MOSBY 1,234.56"), "pdf", {"pageCount": 3}, pages)

    lines = diagnostic["fieldLines"]
    assert lines["billingPeriod"] == {"match": "normalized", "page": 1, "line": 2,
                                      "shape": "Aaaaaaa<U+00A0>Aaaaaa: 99/99/99-99/99/99",
                                      "next": "Aaa aaaaaaa <amount>"}
    assert lines["newBalance"]["match"] == "exact"
    assert lines["newBalance"]["shape"] == "Aaa aaaaaaa <amount>"
    assert "next" not in lines["newBalance"]
    assert lines["previousBalance"]["match"] == "letters"
    assert lines["previousBalance"]["page"] == 3
    assert lines["paymentDueDate"]["match"] == "split"
    assert (lines["paymentDueDate"]["shape"], lines["paymentDueDate"]["next"]) == ("Aaaaaaa Aaa", "Aaaa 99/99/99")
    # The value on a line of its own, past an empty one.
    assert lines["creditLimit"]["next"] == "<amount>"
    assert lines["minimumPaymentDue"] == {"match": "missing"}
    encoded = json.dumps(diagnostic)
    for private in ("MOSBY", "10/15/25", "1,234.56", "98.76", "5,000.00", "Billing", "$"):
        assert private not in encoded


def test_a_parser_without_fields_of_its_own_is_looked_at_for_any_statements_fields() -> None:
    pages = ["LAKESHORE CREDIT UNION\nStatement Period 01/01/2026 - 01/31/2026\nBeginning Balance $1,234.56"]
    _, diagnostic = parser_common.parser_failure(_bundled(), ValueError("boom"), "pdf", {}, pages)

    lines = diagnostic["fieldLines"]
    assert set(lines) == {"statementPeriod", "openingBalance", "closingBalance", "accountNumber"}
    assert lines["statementPeriod"]["shape"] == "Aaaaaaaaa Aaaaaa 99/99/9999 - 99/99/9999"
    assert lines["openingBalance"]["match"] == "exact"
    assert lines["closingBalance"] == {"match": "missing"}


def test_text_stats_count_what_the_text_is_made_of_never_what_it_says() -> None:
    pages = ["Caf\u00e9 \ufb01nance\u00a0charge (cid:12)(cid:7)\n\nTotal \u2013 \ufffd", "", "Page 3"]
    _, diagnostic = parser_common.parser_failure(_bundled(), ValueError("boom"), "pdf", {}, pages)

    assert diagnostic["textStats"] == {"lineCount": 3, "pageChars": [len(pages[0]), 0, 6], "cidGlyphs": 2,
                                       "nonAsciiLetters": 1, "compatibilityLetters": 1, "privateUseChars": 0}
    # Letters are counted, never named: the "é" as a letter, the ligature
    # as a compatibility form of plain ones.
    assert diagnostic["unusualChars"] == {"U+00A0": 1, "U+2013": 1, "U+FFFD": 1}


def test_a_failure_names_the_fields_it_could_not_read() -> None:
    fields = {"billingPeriod": "Billing Period", "newBalance": "New balance", "creditLimit": "Credit Limit"}
    error = parser_common.ParserDiagnosticError(
        "internal", code="PARSER_REQUIRED_DATA_MISSING", stage="metadata",
        missing_fields=("billingPeriod", "newBalance", "notDeclared"))
    for tier, opening in (
        (parser_common.SUPPORT_TIER_VERIFIED, "could not parse the metadata section. "),
        (parser_common.SUPPORT_TIER_PROVISIONAL, "is not covered yet. "),
        (parser_common.SUPPORT_TIER_UNTESTED, "did not read cleanly. "),
    ):
        message, _ = parser_common.parser_failure(
            _bundled(SUPPORT_TIER=tier, DIAGNOSTIC_FIELDS=fields), error, "pdf", {}, "")
        assert opening + "It could not read the statement's Billing Period and New balance. No data" in message

    one = parser_common.ParserDiagnosticError(
        "internal", code="PARSER_REQUIRED_DATA_MISSING", stage="metadata", missing_fields=("creditLimit",))
    message, _ = parser_common.parser_failure(_bundled(DIAGNOSTIC_FIELDS=fields), one, "pdf", {}, "")
    assert "It could not read the statement's Credit Limit. No data" in message
    message, _ = parser_common.parser_failure(_bundled(DIAGNOSTIC_FIELDS=fields), ValueError("x"), "pdf", {}, "")
    assert "could not read the statement's" not in message


def test_declined_parsers_are_the_institutions_bundled_parsers_tried_first() -> None:
    verified = SimpleNamespace(__name__="institutions.example_card", INSTITUTION="Example Card")
    other = SimpleNamespace(__name__="institutions.other_bank", INSTITUTION="Other Bank")
    drop_in = SimpleNamespace(__name__="example_card", INSTITUTION="Example Card")
    family = SimpleNamespace(__name__="institutions.example_card_family", INSTITUTION="Example Card")
    later = SimpleNamespace(__name__="institutions.example_card_later", INSTITUTION="Example Card")
    parsers = [verified, other, drop_in, family, later]

    _, diagnostic = parser_common.parser_failure(family, ValueError("x"), "pdf", {}, "", parsers)
    assert diagnostic["declinedParsers"] == ["example_card"]
    _, diagnostic = parser_common.parser_failure(verified, ValueError("x"), "pdf", {}, "", parsers)
    assert "declinedParsers" not in diagnostic


def test_an_external_parser_gets_no_lines_or_text_counts() -> None:
    module = SimpleNamespace(__name__="local_parser", DIAGNOSTIC_FIELDS={"billingPeriod": "Billing Period"})
    _, diagnostic = parser_common.parser_failure(
        module, ValueError("x"), "pdf", {}, ["Billing Period: 10/15/25-11/14/25\u00a0"], [module])
    for key in ("fieldLines", "textStats", "unusualChars", "declinedParsers"):
        assert key not in diagnostic


def test_a_label_far_along_its_line_is_shaped_from_where_it_is() -> None:
    module = _bundled(DIAGNOSTIC_FIELDS={"newBalance": "New balance"})
    warning = "If you make only the minimum payment each period, you will pay more in interest "
    pages = [warning + "and it will take longer. New balance $1,234.56\n" + " " * 110 + "$98.76"]
    _, diagnostic = parser_common.parser_failure(module, ValueError("x"), "pdf", {}, pages)

    line = diagnostic["fieldLines"]["newBalance"]
    column = len(warning) + len("and it will take longer. ") - 20 + 1
    assert line["column"] == column and line["nextColumn"] == column
    # From 20 characters before the label: "t will take longer. New balance".
    assert line["shape"] == "a aaaa aaaa aaaaaa. Aaa aaaaaaa <amount>"
    assert line["next"] == " " * (110 - column + 1) + "<amount>"


def test_a_label_split_across_lines_is_found_where_a_doubled_letter_joins_them() -> None:
    module = _bundled(DIAGNOSTIC_FIELDS={"statementTotal": "Statement Total"})
    _, diagnostic = parser_common.parser_failure(
        module, ValueError("x"), "pdf", {}, ["Account Statement\nTotal $5.00"])
    assert diagnostic["fieldLines"]["statementTotal"]["match"] == "split"


def test_a_generic_account_label_is_not_found_in_any_line_that_says_account() -> None:
    _, diagnostic = parser_common.parser_failure(
        _bundled(), ValueError("x"), "pdf", {}, ["Account Summary\nPayments $5.00"])
    assert diagnostic["fieldLines"]["accountNumber"] == {"match": "missing"}


def test_field_lines_fit_a_report_the_missing_fields_first() -> None:
    fields = {f"field{n}": f"Label number {n:02d}" for n in range(16)}
    pages = ["\n".join(f"Label number {n:02d} " + "x" * 200 + "\n" + "y" * 200 for n in range(16))]
    error = parser_common.ParserDiagnosticError(
        "x", code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("field15",))
    _, diagnostic = parser_common.parser_failure(_bundled(DIAGNOSTIC_FIELDS=fields), error, "pdf", {}, pages)

    lines = diagnostic["fieldLines"]
    assert list(lines) == list(fields)
    assert sum(len(line.get("shape", "")) + len(line.get("next", "")) for line in lines.values()) <= 2400
    assert "shape" in lines["field15"] and "next" in lines["field15"]
    assert "shape" not in lines["field14"] and lines["field14"]["match"] == "exact"


@pytest.mark.parametrize("amount", [
    "$1,234.56", "1,234.56", "-55.10", "1.234,56", "\u20b91,23,456.00", "1,23,456.00",
    "1'234.56", "1 234,56", "1\u202f234,56", "1234567.8", "\u20ac 5000", "\u00a312",
])
def test_an_amount_is_never_shaped_by_its_digits(amount) -> None:
    assert parser_common.line_shape(f"Total {amount} due").replace("-", "") == "Aaaaa <amount> aaa"


def test_an_amount_a_window_cuts_is_still_an_amount() -> None:
    # Cut alone, "1,234,5" and ",567" would read as no amount at all.
    assert parser_common.line_shape("a" * 92 + " 1,234,567").endswith(" <amount>")
    assert parser_common.line_shape("x" * 95 + " $1,234,567 end", 102) == "<amount> aaa"
    # Dates, versions and bare whole numbers keep their digits: they can't
    # be told from a year or a count.
    assert parser_common.line_shape("08.15.26 v1.2.3 9000") == "99.99.99 a9.9.9 9999"


def test_marks_and_unassigned_code_points_are_masked_never_named() -> None:
    # A decomposed accent is a mark; U+0378 is unassigned, perhaps a letter
    # in a newer Unicode than this Python's.
    assert parser_common.line_shape("e\u0301 \u0378 \u0915\u093f") == "aa <pua> aa"
    _, diagnostic = parser_common.parser_failure(_bundled(), ValueError("x"), "pdf", {}, ["e\u0301\u0378"])
    assert "unusualChars" not in diagnostic
    assert diagnostic["textStats"]["nonAsciiLetters"] == 1
    assert diagnostic["textStats"]["privateUseChars"] == 1


def test_a_labels_column_is_the_label_not_an_earlier_word_ending_like_it() -> None:
    module = _bundled(DIAGNOSTIC_FIELDS={"newBalance": "New balance"})
    line = "Renew your card online " + "x" * 90 + " New balance $5.00"
    _, diagnostic = parser_common.parser_failure(module, ValueError("x"), "pdf", {}, [line])
    assert diagnostic["fieldLines"]["newBalance"]["shape"].endswith("Aaa aaaaaaa <amount>")


def test_a_fault_in_the_text_diagnostics_leaves_them_out_not_the_failure(monkeypatch) -> None:
    def broken(*args):
        raise TypeError("a fault")

    monkeypatch.setattr(parser_common, "line_shape", broken)
    module = _bundled(SUPPORT_TIER=parser_common.SUPPORT_TIER_VERIFIED, DIAGNOSTIC_FIELDS={"newBalance": "New balance"})
    message, diagnostic = parser_common.parser_failure(module, ValueError("x"), "pdf", {}, ["New balance $5.00"])
    assert "No data was imported" in message
    assert diagnostic["fieldPresence"] == {"newBalance": True}
    assert "fieldLines" not in diagnostic
