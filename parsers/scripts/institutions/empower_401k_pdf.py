"""Empower 401(k) retirement-plan quarterly statements.

The statement layout looks like:

    Empower
    Statement Period: 04/01/2029 - 06/30/2029
    Acct Nbr: 734                         (the label word may differ)
    Plan: 949435-62
    Balance as of March 31, 2029  $719,660.91 $68,851.31 $833,677.88   (Employee, Employer, Total)
    Payroll Contributions / Change in Value / Expenses
    Balance as of June 30, 2029   ...
    <Beginning Balance, Deposits, Change in Value, Withdrawals, Expenses, Ending Balance, Shares>
    <Category>                                        (a one-word line, no figures)
    <Fund name> 645,105.10 632.20 53,915.45 -2.44 103,238.86 3,635.706
    <fund name continued>                             (a line wrapped under the row)
    Totals 833,677.88 3,279.48 99,127.53 -21.72 936,063.17
    ...
    What activity ... this period?
    Deposits/Contributions
    Contribution Mar 31, 2029 Apr 02, 2029 546.58     (payroll date, posted date, amount)
    Total Deposits/Contributions 3,279.48
    Expenses
    Plan Administration ... Fee Apr 13, 2029 -7.24
    Total Expenses -21.72

Funds carry no ticker, so the fund name is the holding's symbol. The fund
ending balances must equal the printed Totals row and the headline balance,
the balance bridge must add up, and each activity section is checked against
its own printed total; a mismatch raises (holdings) or is reported as a check.
"""

from __future__ import annotations

import re
from datetime import datetime

import parser_common
from institutions import common

KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED
INSTITUTION = "Empower"

NOT_APPLICABLE = {
    "option:*": "A 401(k) plan holds no option contracts.",
    "corporate_event:*": "A plan statement reports contributions and fund balances, not corporate actions.",
}

_ACCOUNT_TYPE = "401(k)"
_EPS = 0.02
_NUM = r"-?\$?\d[\d,]*\.\d+"
_NUM_RE = re.compile(_NUM)
_MONEY = r"-?\$?[\d,]+\.\d{2}"
_DATE = r"[A-Z][a-z]{2}\s+\d{1,2},\s*\d{4}"

_PERIOD_RE = re.compile(r"Statement\s+Period:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})")
_ACCT_RE = re.compile(r"\bAcct\s+\S+:\s*([\dXx*-]+)")
_PLAN_RE = re.compile(r"\bPlan:\s*([\w-]+)")
_HEADLINE_RE = re.compile(rf"(?m)^\$?([\d,]+\.\d{{2}})\s*$")
_BRIDGE_ROW_RE = re.compile(rf"^(?P<label>.+?)\s+(?P<emp>{_MONEY})\s+(?P<er>{_MONEY})\s+(?P<total>{_MONEY})$")
_FUND_HEADER_RE = re.compile(r"Balance\s+Deposits\s+in\s*Value\s+Transfers\s*/\s*Expenses\s+Balance\s+Shares")
_TOTALS_RE = re.compile(rf"^Totals?\s+((?:{_NUM}\s*)+)$")
_FOOTER_RE = re.compile(r"\bPage\s+\d+\s+of\s+\d+\s*$")
_ACTIVITY_RE = re.compile(rf"^(?P<desc>.+?)\s+(?P<d1>{_DATE})(?:\s+(?P<d2>{_DATE}))?\s+(?P<amt>{_MONEY})(?:\s+(?P<detail>.+))?$")
_SECTION_TOTAL_RE = re.compile(rf"^Total\s+(?P<name>.+?)\s+(?P<amt>{_MONEY})$")

# Activity section title -> (transaction_type, action), most specific first.
_SECTION_TYPES = [
    ("rollover", "rollover_in", "Rollover"),
    ("transfer", "transfer_in", "Transfer"),
    ("contribution", "contribution", "Contribution"),
    ("deposit", "contribution", "Contribution"),
    ("withdraw", "withdrawal", "Withdrawal"),
    ("distribution", "distribution", "Distribution"),
    ("expense", "fee", "Fee"),
    ("fee", "fee", "Fee"),
    ("dividend", "dividend", "Dividend"),
    ("interest", "interest", "Interest"),
]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _is_plan_statement(head_text: str) -> tuple[bool, str]:
    compact = _compact(head_text)
    required = {
        "Empower": "empower",
        "Statement Period": "statementperiod",
        "Vested Balance as of": "vestedbalanceas",
        "Employee Employer Total": "employeeemployertotal",
    }
    missing = [label for label, marker in required.items() if marker not in compact]
    if missing:
        return False, "missing Empower plan-statement marker(s): " + ", ".join(missing)
    return True, "found Empower retirement-plan statement"


def detect(head_text: str) -> tuple[bool, str]:
    return _is_plan_statement(head_text)


def _fail(message: str, code: str = "PARSER_REQUIRED_DATA_MISSING", stage: str = "parsing"):
    return parser_common.ParserDiagnosticError(message, code=code, stage=stage)


def _amount(text: str) -> float:
    return common.parse_amount(text)


def _statement_date(text: str) -> str:
    match = _PERIOD_RE.search(text)
    if not match:
        return ""
    try:
        return datetime.strptime(match.group(2), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _account(text: str) -> str:
    match = _ACCT_RE.search(text) or _PLAN_RE.search(text)
    return common.last4_digits(match.group(1)) if match else ""


def _bridge(text: str) -> tuple[float, float, float]:
    """(opening, sum of the rows between, closing) of the balance bridge's Total column."""
    opening, between = None, 0.0
    for raw in text.splitlines():
        match = _BRIDGE_ROW_RE.match(raw.strip())
        if not match:
            continue
        label, total = _compact(match.group("label")), _amount(match.group("total"))
        if label.startswith("balanceasof"):
            if opening is not None:
                return opening, between, total
            opening = total
        elif opening is not None:
            between += total
    raise _fail("Empower balance bridge (Balance as of ... rows) not found.", stage="summary")


def _check_bridge(text: str, ending: float) -> None:
    opening, between, closing = _bridge(text)
    if abs(opening + between - closing) > _EPS:
        raise _fail(
            f"Balance bridge does not add up: {opening:.2f} + {between:.2f} != {closing:.2f}.",
            code="PARSER_RECONCILIATION_FAILED", stage="summary",
        )
    headline = _HEADLINE_RE.search(text)
    for printed in ([closing] + ([_amount(headline.group(1))] if headline else [])):
        if abs(printed - ending) > _EPS:
            raise _fail(
                f"Fund balances sum to {ending:.2f} but the statement prints {printed:.2f}.",
                code="PARSER_RECONCILIATION_FAILED", stage="holdings",
            )


def _fund_lines(pages_text: list[str]) -> tuple[list[tuple[str, str]], float | None]:
    """The fund table's lines as ("row"/"text", line) pairs, and its printed Totals."""
    entries: list[tuple[str, str]] = []
    printed_total = None
    for page in pages_text:
        inside = False
        for raw in page.splitlines():
            line = raw.strip()
            if _FUND_HEADER_RE.search(line):
                inside = True
                continue
            if not inside or not line or _FOOTER_RE.search(line):
                continue
            total = _TOTALS_RE.match(line)
            if total:
                printed_total = _amount(_NUM_RE.findall(total.group(1))[-1])
                inside = False
                continue
            kind = "row" if len(_NUM_RE.findall(line)) >= 3 else "text"
            if kind == "text" and line.rstrip().endswith("?"):
                inside = False
                continue
            entries.append((kind, line))
    return entries, printed_total


def _category_names(text: str) -> set[str]:
    """Compact fund-category names from the 'How is your account invested' list."""
    return {_compact(m.group(1)) for m in re.finditer(r"(?m)^\d+(?:\.\d+)?%\s+(.+?)\s*$", text)}


def _holdings(pages_text: list[str], text: str) -> tuple[list[dict], float]:
    entries, printed_total = _fund_lines(pages_text)
    categories = _category_names(text)
    funds: list[dict] = []
    for index, (kind, line) in enumerate(entries):
        if kind == "row":
            numbers = list(_NUM_RE.finditer(line))
            name = line[:numbers[0].start()].strip()
            funds.append({
                "name": name,
                "begin": _amount(numbers[0].group()),
                "ending": _amount(numbers[-2].group()),
                "shares": _amount(numbers[-1].group()),
            })
            continue
        previous = entries[index - 1][0] if index else "start"
        following = entries[index + 1][0] if index + 1 < len(entries) else "end"
        if _compact(line) in categories or previous != "row":
            continue  # a category heading, or the heading after a wrapped name
        # A line right after a fund row wraps that fund's name, unless it is a
        # one-word heading that introduces the next fund row.
        if following == "row" and " " not in line:
            continue
        funds[-1]["name"] += " " + line
    if not funds:
        raise _fail("No fund rows found in the Empower account-balance table.", stage="holdings")
    if printed_total is None:
        raise _fail("Empower fund table Totals row not found.", stage="holdings")
    held = round(sum(f["ending"] for f in funds), 2)
    if abs(held - printed_total) > _EPS:
        raise _fail(
            f"Fund balances sum to {held:.2f} but the printed Totals is {printed_total:.2f}.",
            code="PARSER_RECONCILIATION_FAILED", stage="holdings",
        )
    rows = []
    for fund in funds:
        name = re.sub(r"\s+", " ", fund["name"]).strip()
        rows.append({
            "symbol": name.upper(),
            "description": name,
            "quantity": abs(fund["shares"]),
            "current_value": fund["ending"],
            "percent_of_account": round(fund["ending"] / printed_total * 100, 2) if printed_total else 0.0,
            "type": "Mutual Fund",
        })
    return rows, printed_total


def _section_type(title: str) -> tuple[str, str]:
    lowered = title.casefold()
    for key, kind, action in _SECTION_TYPES:
        if key in lowered:
            return kind, action
    return "other", "Other"


def _activity(pages_text: list[str]) -> tuple[list[dict], list[dict]]:
    """Dated activity rows plus a sum check per section's printed total."""
    rows: list[dict] = []
    checks: list[dict] = []
    in_activity = False
    section = None
    section_rows: list[int] = []
    for page in pages_text:
        for raw in page.splitlines():
            line = raw.strip()
            if re.search(r"Date\s+Date\s+Amount", line):
                in_activity = True
                continue
            if not in_activity or not line or _FOOTER_RE.search(line):
                continue
            if line.endswith("?"):
                in_activity = False
                continue
            total = _SECTION_TOTAL_RE.match(line)
            if total:
                checks.append({
                    "kind": "sum", "label": f"Total {total.group('name')}",
                    "table": "brokerage_transactions", "rows": list(section_rows),
                    "expected": _amount(total.group("amt")),
                })
                continue
            match = _ACTIVITY_RE.match(line)
            if match and section:
                kind, action = _section_type(section)
                if re.search(r"\bCapital\s+Gains?\b", match.group("desc"), re.I):
                    kind, action = "capital_gain", "Capital Gain"
                amount = _amount(match.group("amt"))
                posted = match.group("d2") or match.group("d1")
                section_rows.append(len(rows))
                row = {
                    "date": datetime.strptime(re.sub(r"\s+", " ", posted), "%b %d, %Y").strftime("%Y-%m-%d"),
                    "description": re.sub(r"\s+", " ", match.group("desc")),
                    "amount": amount,
                    "action": action,
                    "transaction_type": kind,
                }
                detail = match.group("detail")
                if detail and kind in {"dividend", "capital_gain"}:
                    # Investment-option text is followed by shares and unit price.
                    figures = re.search(rf"\s+({_NUM})\s+({_NUM})$", detail)
                    if figures:
                        row["quantity"] = abs(_amount(figures.group(1)))
                        row["price"] = abs(_amount(figures.group(2)))
                rows.append(row)
            elif not match and not _NUM_RE.search(line):
                section, section_rows = line, []
    return rows, checks


def _parse_plan(pages_text: list[str]) -> dict:
    text = "\n".join(pages_text)
    holdings, total = _holdings(pages_text, text)
    _check_bridge(text, total)
    account = _account(text)
    transactions, checks = _activity(pages_text)
    for row in transactions:
        if not row["description"].strip():
            raise _fail("Empower activity row has no description.")
    common.tag_account(holdings, account, _ACCOUNT_TYPE)
    common.tag_account(transactions, account, _ACCOUNT_TYPE)
    tables = {"brokerage_holdings": holdings}
    if transactions:
        parser_common.set_directions(transactions)
        tables["brokerage_transactions"] = transactions
    result = {"institution": INSTITUTION, "statementDate": _statement_date(text), "tables": tables}
    if checks:
        result["checks"] = checks
    return result


def parse(pages_text: list[str], pdf_path: str) -> dict:
    if not detect("\n".join(pages_text[:3]))[0]:
        raise _fail("This is not an Empower 401(k) plan statement.", stage="detection")
    return _parse_plan(pages_text)
