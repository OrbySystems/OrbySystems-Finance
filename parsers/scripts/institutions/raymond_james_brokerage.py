"""Provisional raymond james investment-statement parser."""

from __future__ import annotations

from . import provisional_brokerage_common as core


KIND = core.KIND
SUPPORT_TIER = core.SUPPORT_TIER
PROFILE_KEY = "raymond_james"
INSTITUTION = core.PROFILES[PROFILE_KEY]["institution"]
DIAGNOSTIC_MARKERS = core.diagnostic_markers(PROFILE_KEY)
DIAGNOSTIC_FIELDS = core.diagnostic_fields(PROFILE_KEY)
DIAGNOSTIC_SIGNALS = core.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = core.DIAGNOSTIC_COUNTS
DIAGNOSTIC_TERMS = core.DIAGNOSTIC_TERMS
PARSER_REVISION = core.PARSER_REVISION

def detect(head_text: str) -> tuple[bool, str]:
    return core.detect_profile(head_text, PROFILE_KEY)


def parse(pages_text: list[str], pdf_path: str) -> dict:
    return core.parse_profile(pages_text, pdf_path, PROFILE_KEY)
