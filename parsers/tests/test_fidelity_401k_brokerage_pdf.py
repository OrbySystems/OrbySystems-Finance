import pytest

import parser_common
from institutions import fidelity_401k_brokerage_pdf as netbenefits


def test_fidelity_401k_pdf_still_recognized_but_rejected(dump_pages):
    pages = dump_pages("fidelity-401k-brokerage-pdf-synthetic-sample.pdf")
    matched, reason = netbenefits.detect("\n".join(pages))

    # Every marker this format normally matches on is still checked -
    # this isn't "unrecognized", it's a deliberate refusal - but detect()
    # itself now always declines so the CSV-guidance reason reaches the
    # caller verbatim (see the module docstring for why).
    assert matched is False
    assert "csv" in reason.lower()
    assert "transaction history" in reason.lower()


def test_fidelity_401k_pdf_rejects_non_netbenefits_text_for_a_different_reason():
    matched, reason = netbenefits.detect("some unrelated statement text")
    assert matched is False
    assert "fidelity netbenefits" in reason.lower()
    assert "csv" not in reason.lower()


def test_fidelity_401k_pdf_dispatcher_reports_not_detected_with_csv_guidance(run_statement):
    with pytest.raises(AssertionError, match="(?i)not detected"):
        run_statement("fidelity-401k-brokerage-pdf-synthetic-sample.pdf")


def test_fidelity_401k_pdf_parse_is_unreachable_but_still_refuses_directly(dump_pages):
    pages = dump_pages("fidelity-401k-brokerage-pdf-synthetic-sample.pdf")
    with pytest.raises(parser_common.ParserDiagnosticError) as raised:
        netbenefits.parse(pages, "fidelity-401k-brokerage-pdf-synthetic-sample.pdf")

    assert "csv" in str(raised.value).lower()
    assert raised.value.diagnostic_code == "PARSER_REQUIRED_DATA_MISSING"
