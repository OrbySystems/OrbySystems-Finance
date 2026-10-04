"""Every bundled parser says how far its format has been confirmed.

The support tier decides what OrbySystems offers when a statement does not
read cleanly (parser_common's SUPPORT_TIER_* block): a verified or
provisional parser's failure asks the user and reports what went wrong, an
untested one's offers the Statement Scrambler. So a bundled parser must
declare its tier on one line of its own - never inherit it, never fall back
to a default - and OrbySystems' Go catalog (orby-core pkg/parsercatalog)
reads that same line to check its own table against.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import parser_common

SCRIPTS = Path(parser_common.__file__).resolve().parent
TIER_LINE = re.compile(r"^SUPPORT_TIER = parser_common\.SUPPORT_TIER_([A-Z]+)$", re.M)
TIERS = {"VERIFIED", "PROVISIONAL", "UNTESTED", "DEMO"}


def bundled_parsers() -> list[Path]:
    out = []
    for folder in ("institutions", "csv_institutions"):
        for path in sorted((SCRIPTS / folder).glob("*.py")):
            text = path.read_text()
            if re.search(r"^def detect\(", text, re.M) and re.search(r"^def parse\(", text, re.M):
                out.append(path)
    return out


def test_every_bundled_parser_declares_its_tier_on_a_line_of_its_own() -> None:
    parsers = bundled_parsers()
    assert len(parsers) > 30
    for path in parsers:
        found = TIER_LINE.findall(path.read_text())
        assert len(found) == 1, f"{path.name}: declare SUPPORT_TIER = parser_common.SUPPORT_TIER_<TIER> once"
        assert found[0] in TIERS, f"{path.name}: unknown tier {found[0]}"


def test_a_parser_that_declares_no_tier_is_untested() -> None:
    # A dropped-in parser written before tiers, or with a typo: nothing says
    # its format was ever confirmed.
    assert parser_common.module_support_tier(SimpleNamespace()) == "untested"
    assert parser_common.module_support_tier(SimpleNamespace(SUPPORT_TIER="supported")) == "untested"
    assert parser_common.module_support_tier(SimpleNamespace(SUPPORT_TIER="verified")) == "verified"


def test_each_tier_says_what_happens_next_when_a_statement_does_not_read() -> None:
    def failure(tier: str) -> str:
        module = SimpleNamespace(__name__="institutions.example_bank", INSTITUTION="Example Bank", SUPPORT_TIER=tier)
        message, diagnostic = parser_common.parser_failure(module, ValueError("boom"), "pdf", {})
        assert diagnostic["supportTier"] == tier
        assert diagnostic["schemaVersion"] == 4
        return message

    assert "scrambled copy" in failure(parser_common.SUPPORT_TIER_UNTESTED)
    assert "provisional Example Bank format" in failure(parser_common.SUPPORT_TIER_PROVISIONAL)
    for tier in (parser_common.SUPPORT_TIER_VERIFIED, parser_common.SUPPORT_TIER_DEMO):
        message = failure(tier)
        assert "scrambled" not in message and "provisional" not in message
