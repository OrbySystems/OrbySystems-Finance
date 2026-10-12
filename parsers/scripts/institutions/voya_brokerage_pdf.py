# SPDX-License-Identifier: Apache-2.0
"""Voya Financial retirement-plan quarterly statement ("Activity Statement for
Your 401(k) Plan").

The statement prints a period-level balance bridge and a per-fund snapshot:

    Investment  Balance on  Contributions/Transfers  Investment Gain  Balance on  Shares  Price
    <fund name> $545,087.19 $0.00 $994.70 $548,199.15 667.3633 $39.7895
    Total       $545,087.19 $0.00 $3,111.96 $548,199.15

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
_HOLDING_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<begin>{_MONEY})\s+(?P<contrib>{_MONEY})\s+(?P<gain>{_MONEY})\s+"
    rf"(?P<end>{_MONEY})\s+(?P<shares>[\d,]+(?:\.\d+)?)\s+(?P<price>\$[\d,]+(?:\.\d+)?)$"
)
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
            name = re.sub(r"\s+", " ", m.group("name")).strip()
            holdings.append({
                "symbol": name.upper(),
                "description": name,
                "quantity": common.parse_amount(m.group("shares")),
                "price": common.parse_amount(m.group("price")),
                "current_value": common.parse_amount(m.group("end")),
                "type": "Mutual Fund",
            })

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
