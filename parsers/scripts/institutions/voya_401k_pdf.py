# SPDX-License-Identifier: Apache-2.0
"""Voya Financial retirement-plan quarterly statement ("Activity Statement for
Your 401(k) Plan").

The statement prints a period-level balance bridge and a per-fund snapshot:

    Investment  Balance on  Contributions/Transfers  Investment Gain  Balance on  Shares  Price
    <fund name> $545,087.19 $0.00 $994.70 $548,199.15 667.3633 $39.7895
    Total       $545,087.19 $0.00 $3,111.96 $548,199.15

A fund with no unit value - typically the plan's fixed/stable-value account -
prints N/A in both the Shares and Price columns and is still a holding:

    Voya Fixed Account $46,692.19 $0.00 $656.46 $47,963.44 N/A N/A

Such a row carries no quantity/price, only its balance. (The original parser
required numeric shares/price, dropped this row, and then failed its Total
reconciliation.)

It prints no itemized transactions, so only brokerage_holdings is returned.
Funds carry no ticker, so the fund name is used as the symbol. The fund
ending balances are checked against the printed Total and the headline
account balance; a mismatch raises.
"""

from __future__ import annotations

import re
from datetime import datetime

import parser_common
from institutions import common

KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
INSTITUTION = "Voya"
_ACCOUNT_TYPE = "401(k)"
_EPS = 0.02

NOT_APPLICABLE = {
    "option:*": "A 401(k) plan holds no option contracts.",
    "corporate_event:*": "A plan statement reports contributions and fund balances, not corporate actions.",
}

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_PERIOD_RE = re.compile(
    rf"({_MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})\s*-\s*({_MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})"
)
_MONEY = r"-?\$[\d,]+\.\d{2}"
_NA = r"N/A|--"
_HOLDING_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<begin>{_MONEY})\s+(?P<contrib>{_MONEY})\s+(?P<gain>{_MONEY})\s+"
    rf"(?P<end>{_MONEY})\s+(?P<shares>[\d,]+(?:\.\d+)?|{_NA})\s+(?P<price>\$[\d,]+(?:\.\d+)?|{_NA})$"
)
_MONEY_TOKEN_RE = re.compile(_MONEY)
_TOTAL_RE = re.compile(rf"^Total\s+{_MONEY}\s+{_MONEY}\s+{_MONEY}\s+(?P<end>{_MONEY})$")
_BALANCE_RE = re.compile(rf"Account Balance on \d{{2}}/\d{{2}}/\d{{4}}\s+(?P<amt>{_MONEY})")
_PLAN_RE = re.compile(r"Activity Statement for Your 401\(K\) Plan\s+([A-Za-z0-9]+)", re.I)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def detect(head_text: str) -> tuple[bool, str]:
    compact = _compact(head_text)
    required = {
        "Voya": "voya",
        "Activity Statement for Your 401(K) Plan": "activitystatementforyour401(k)plan",
        "Balance on": "balanceon",
    }
    missing = [label for label, marker in required.items() if marker not in compact]
    if missing:
        return False, "missing Voya plan-statement marker(s): " + ", ".join(missing)
    return True, "found Voya 401(k) plan activity statement"


def _statement_date(text: str) -> str:
    match = _PERIOD_RE.search(text)
    if not match:
        return ""
    raw = f"{match.group(4)} {match.group(5)}, {match.group(6)}"
    try:
        return datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _number(raw: str) -> float | None:
    """A numeric Shares/Price cell, or None for a printed N/A."""
    return None if re.fullmatch(_NA, raw) else common.parse_amount(raw)


def _holding(m: re.Match) -> dict:
    name = re.sub(r"\s+", " ", m.group("name")).strip()
    row = {"symbol": name.upper(), "description": name}
    for key, group in (("quantity", "shares"), ("price", "price")):
        value = _number(m.group(group))
        if value is not None:
            row[key] = value
    row["current_value"] = common.parse_amount(m.group("end"))
    # A fund priced per unit is a mutual fund/CIT; one with no units (N/A) is
    # a fixed or stable-value account carried at its balance.
    row["type"] = "Mutual Fund" if "quantity" in row else "Fixed Account"
    return row


def _fail(message: str, code: str = "PARSER_REQUIRED_DATA_MISSING", stage: str = "parsing"):
    return parser_common.ParserDiagnosticError(message, code=code, stage=stage)


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    plan = _PLAN_RE.search(text)
    # No account number is printed; the plan number (e.g. 37C129) identifies it.
    account = plan.group(1)[-4:] if plan else ""

    holdings: list[dict] = []
    printed_total = None
    in_table = False
    for raw in text.splitlines():
        line = raw.strip()
        compact = _compact(line)
        if "currentinvestmentportfolio" in compact:
            in_table = True
            continue
        if not in_table:
            continue
        total = _TOTAL_RE.match(line)
        if total:
            printed_total = common.parse_amount(total.group("end"))
            break
        m = _HOLDING_RE.match(line)
        if m:
            holdings.append(_holding(m))
        elif len(_MONEY_TOKEN_RE.findall(line)) >= 4:
            # A balance-bridge row in a shape we don't know: fail here, naming
            # it, rather than at the Total check with a short sum.
            raise _fail(
                f"Unrecognized Voya portfolio row: {line!r}",
                code="PARSER_RECONCILIATION_FAILED", stage="holdings",
            )

    if not holdings:
        raise _fail("No fund rows found in the Voya investment portfolio table.")
    held = sum(h["current_value"] for h in holdings)
    if printed_total is None:
        raise _fail("Voya portfolio Total line not found.")
    if abs(held - printed_total) > _EPS:
        raise _fail(
            f"Fund balances sum to {held:.2f} but the printed Total is {printed_total:.2f}.",
            code="PARSER_RECONCILIATION_FAILED", stage="holdings",
        )
    headline = _BALANCE_RE.findall(text)
    if headline and abs(common.parse_amount(headline[-1]) - printed_total) > _EPS:
        raise _fail("Headline account balance disagrees with the portfolio Total.")

    for h in holdings:
        h["percent_of_account"] = round(h["current_value"] / printed_total * 100, 2) if printed_total else 0.0
    common.tag_account(holdings, account, _ACCOUNT_TYPE)
    return {
        "institution": INSTITUTION,
        "statementDate": _statement_date(text),
        "tables": {"brokerage_holdings": holdings},
    }
