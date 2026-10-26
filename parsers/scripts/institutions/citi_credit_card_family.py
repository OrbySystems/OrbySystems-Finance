"""Citi credit-card statements in a layout no parser here reads yet.

citi_credit_card reads the Citi layouts it knows. Any other Citi card
statement is claimed here instead, and read the same way - which fails on a
layout it does not know, with a diagnostic that names Citi and says which
of a card statement's fields were found. This module is untested, so that
failure offers the Statement Scrambler, whose sample of the statement is
what a parser for its layout is built from. In citi_credit_card itself the
claim would take on that parser's tier, and a provisional or verified
parser's failure is not offered the scrambler.

Tried after citi_credit_card (PRIORITY), whose statements this would
otherwise claim first.
"""

import re

import parser_common

from institutions import citi_credit_card

SUPPORT_TIER = parser_common.SUPPORT_TIER_UNTESTED
PRIORITY = 110
INSTITUTION = citi_credit_card.INSTITUTION
DIAGNOSTIC_MARKERS = citi_credit_card.DIAGNOSTIC_MARKERS
DIAGNOSTIC_FIELDS = citi_credit_card.DIAGNOSTIC_FIELDS
DIAGNOSTIC_SIGNALS = citi_credit_card.DIAGNOSTIC_SIGNALS

_CARD_MARKERS = (
    "payment due date",
    "minimum payment due",
    "credit limit",
    "cash advance limit",
    "payments, credits and adjustments",
    "interest charge calculation",
)


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    citi_brand = "citicards.com" in lower or bool(re.search(r"\bciti(?:bank)?\b", lower))
    if citi_brand and sum(marker in lower for marker in _CARD_MARKERS) >= 2:
        return True, "matched a Citi credit-card statement in a layout not yet supported"
    return False, "Citi credit-card markers not found"


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:
    return citi_credit_card.parse(pages_text, pdf_path, vision)
