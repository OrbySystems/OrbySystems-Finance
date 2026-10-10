"""E*TRADE investment-statement parser.

The documented provisional layout is still handled by the shared profile
core (provisional_brokerage_common). Every other statement this module
claims is the E*TRADE from Morgan Stanley "CLIENT STATEMENT" (the Morgan
Stanley Smith Barney layout, also used for Morgan Stanley at Work
self-directed accounts): a cover, disclosure pages, then for each account
an Account Summary (change in value, balance sheet | cash flow, income |
gain summaries) and an Account Detail (HOLDINGS, ACTIVITY, MESSAGES).
Detection never depends on those later pages.

What is read, per account (the account number on each page's "Account
Summary"/"Account Detail" banner says which account a page belongs to,
and the title above it - "Roth IRA", "Active Assets Account" - its
accountType):

  * CHANGE IN VALUE OF YOUR ACCOUNT - the This Period column only. Its own
    identities (credits + debits + security transfers = net; beginning +
    net + change = ending) must hold, or the parse fails.
  * CASH FLOW (merged on the same lines as the BALANCE SHEET) - opening and
    closing cash and the This Period figure of each line, for checks.
  * HOLDINGS - the bank deposit / money market rows, then every section
    read by row shape: "DESCRIPTION (TICKER) qty price cost value [gain]
    [income] [yield]", option contracts "CALL|PUT <name> AT <strike>
    <EXPIRES> mm/dd/yyyy contracts price cost value gain" (their OCC code is
    built from the description and the "(ROOT ...)" line under it), mutual
    fund Purchases/Reinvestments/Total blocks and tax-lot blocks (the
    position is the "Total" line). Continuation lines (ratings, asset
    class, next dividend, short-position notes) and page headers are
    skipped. Rows are validated against their own section subtotal,
    section totals against the holdings TOTAL VALUE, and that against
    TOTAL ENDING VALUE. A mismatch FAILS the parse (stage "holdings"):
    holdings carry no amount, so they cannot be expressed as CONTRACT
    checks, and a portfolio missing a position must not be imported as a
    clean read.
  * CASH FLOW ACTIVITY BY DATE - every row, classified by its activity
    word (_ACTIVITY_WORDS). An unknown word, or a dated line that cannot be
    read, is not dropped and does not fail the parse: it is reported in an
    "unread" check, and the sum check below then explains the gap. A dash
    in the Credits/(Debits) column is a row with amount_missing.
  * TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY - option
    expirations/assignments/exercises and other corporate actions become
    corporate_action rows (amount 0.00), security transfers transfer_in /
    transfer_out rows. Upper-case comment lines under a row ("STOCK PLAN
    RELEASE") never end the table; a row found after what looked like its
    end is reported as unread.
  * DEBIT CARD ACTIVITY, CHECKING ACTIVITY, CHECKS WRITTEN and BILL PAY -
    every dated row, as a withdrawal (a deposit when it is a credit), when
    that cash is not already in CASH FLOW ACTIVITY BY DATE (closing cash
    less opening cash differs from NET CREDITS/(DEBITS)).
  * The MONEY MARKET FUND (MMF) AND BANK DEPOSIT PROGRAM ACTIVITY table is
    the settlement-date sweep of the same cash the cash-flow rows already
    record, and UNSETTLED PURCHASES/SALES ACTIVITY repeats trades already
    listed; neither is emitted.

The statement's own arithmetic is returned as checks (CONTRACT.md,
"Checks"; table brokerage_transactions), each line that was not read
claimed by one total only (see _checks): the rows that move money in and
out sum to the summary's Credits + Debits, when every line was read; the
cash-flow rows sum to NET CREDITS/(DEBITS), or, when that is not printed,
take opening cash to closing cash; card and check rows sum to the cash
that moved outside the cash-flow table; security transfers sum to TOTAL
SECURITY TRANSFERS; and lines that looked like rows but were not read are
listed under their section's label.

Quantities are never signed: the type says a sale left the account, and a
transfer or corporate action says which way it went in subtype (In / Out).

This file is also installed on its own as a drop-in replacement
(~/.orby/ingest/parsers/etrade_brokerage.py). parser_common.load_extra_parsers
loads such a file outside the institutions package, so it imports its
helpers absolutely ("from institutions import ..."), which works both
bundled and dropped in.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re

import parser_common

from institutions import common
from institutions import diagnostic_helpers
from institutions import provisional_brokerage_common as core


KIND = core.KIND
SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PROFILE_KEY = "etrade"
INSTITUTION = core.PROFILES[PROFILE_KEY]["institution"]
DIAGNOSTIC_MARKERS = {
    **core.diagnostic_markers(PROFILE_KEY),
    "client_statement": "CLIENT STATEMENT",
    "cash_flow": "CASH FLOW",
    "account_detail": "Account Detail",
    "cash_flow_activity": "CASH FLOW ACTIVITY BY DATE",
    "net_credits_debits": "NET CREDITS/(DEBITS)",
    "corporate_actions": "TRANSFERS, CORPORATE ACTIONS AND",
    "bank_deposit_program": "CASH, BANK DEPOSIT PROGRAM",
}
DIAGNOSTIC_FIELDS = {
    **core.diagnostic_fields(PROFILE_KEY),
    "statementPeriod": "For the Period",
    "accountIdentifier": "Account Summary",
    "totalBeginningValue": "TOTAL BEGINNING VALUE",
    "securityTransfers": "Security Transfers",
    "netCreditsDebitsTransfers": "Net Credits/Debits/Transfers",
    "changeInValue": "Change in Value",
    "totalEndingValue": "TOTAL ENDING VALUE",
    "cashHolding": "MORGAN STANLEY BANK N.A.",
    "totalValue": "TOTAL VALUE",
    "openingCash": "OPENING CASH",
    "closingCash": "CLOSING CASH",
}
DIAGNOSTIC_SIGNALS = core.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = tuple(core.DIAGNOSTIC_COUNTS) + (
    "unreadActivityLines",
    "unrecognizedHoldingLines",
)
DIAGNOSTIC_TERMS = core.DIAGNOSTIC_TERMS
PARSER_REVISION = 5

# --- statement period and account ------------------------------------------

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTHS = "|".join(_MONTH_NAMES)
_MONTH_NUMBERS = {name.casefold(): number for number, name in enumerate(_MONTH_NAMES, 1)}
# "For the Period March 1-31, 2027", "April 1- June30, 2024",
# "August 1- August 31, 2026", "December 1, 2025 - January 31, 2026".
_AT_WORK_PERIOD_RE = re.compile(
    rf"For\s+the\s+Period\s+(?P<start_month>{_MONTHS})\s*(?P<start_day>\d{{1,2}})"
    rf"(?:\s*,\s*(?P<start_year>\d{{4}}))?\s*-\s*"
    rf"(?:(?P<end_month>{_MONTHS})\s*)?(?P<end_day>\d{{1,2}}),\s*(?P<end_year>\d{{4}})",
    re.I,
)
# "(3/1/27-3/31/27)" - the This Period column heading, when the cover's
# period is masked.
_AT_WORK_NUMERIC_PERIOD_RE = re.compile(
    r"\((?P<start_month>\d{1,2})/(?P<start_day>\d{1,2})/(?P<start_year>\d{2,4})\s*"
    r"-\s*(?P<end_month>\d{1,2})/(?P<end_day>\d{1,2})/(?P<end_year>\d{2,4})\)"
)
# Every account page's banner: "Account Summary 123-456789-012 <holder>" /
# "Account Detail ...". A masked number ("123-XXX789-012") still names the
# account; a fully masked one names none.
_ACCOUNT_BANNER_RE = re.compile(r"^Account (?:Summary|Detail)\b(?P<rest>.*)$")
_ACCOUNT_ID_RE = re.compile(r"^\s+(?P<account>(?=[\dXx*-]*\d)[\dXx*][\dXx*-]{4,}[\dXx*])(?=\s|$)")
_PAGE_FURNITURE_RE = re.compile(r"^(?:CLIENT STATEMENT\b|Page \d+ of \d+$)")
# Scan/route codes printed at a page foot ("418KDPLM", "903311").
_FOOTER_CODE_RE = re.compile(r"^(?=[A-Z]*\d)[A-Z0-9]{5,12}$")

# --- cells -------------------------------------------------------------------

_MONEY = r"(?:\$?\(\s*\$?[\d,]+\.\d{2}\s*\)|\(\s*\$?[\d,]+\.\d{2}\s*\)|-?\$?-?[\d,]+\.\d{2})"
_ZERO_CELL = {"--", "—", "–", "-"}
_REDACTED_TOKEN_RE = re.compile(r"^(?:x+|\$?\(?0[0,]*0*\.00\)?)$", re.I)
_SUMMARY_CELL = rf"(?:{_MONEY}|—|–|--|-)"
_NUMBER_TOKEN_RE = re.compile(r"^(?:\$?\(\$?[\d,]*\d\.\d+\)|-?\$?-?[\d,]*\d\.\d+)$")
_INTEGER_TOKEN_RE = re.compile(r"^\$?\(?\$?[\d,]*\d\)?$")
_PERCENT_TOKEN_RE = re.compile(r"^-?\(?[\d,]*\d(?:\.\d+)?\)?%$")
_DATE_TOKEN_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_DECIMAL_IN_LINE_RE = re.compile(r"(?<![\w.])\$?\(?\$?[\d,]*\d\.\d+\)?(?![\w.%/])")
# Cells a holding prints instead of a figure.
_PLACEHOLDER_PHRASES = re.compile(r"\b(?:Please Provide|Pending Corporate Actions?|Not Available)\b", re.I)
# A tax lot's gain carries its term, sometimes glued to it ("1,125.00ST"),
# and may end with a footnote letter ("1,125.00 ST A").
_GLUED_TERM_RE = re.compile(r"(\d\.\d{2}\)?)(ST|LT)(?=\s|$)")
_FOOTNOTE_TAIL_RE = re.compile(r"(?:\d\.\d{2}\)?|\s[SL]T)(?P<note>\s+[A-Z])$")


def _holdings_text(text: str) -> str:
    """A holdings line with placeholders as N/A, a glued term spaced off
    and a trailing footnote letter dropped."""
    text = _PLACEHOLDER_PHRASES.sub("N/A", text)
    text = _GLUED_TERM_RE.sub(r"\1 \2", text)
    note = _FOOTNOTE_TAIL_RE.search(text)
    if note:
        text = text[:note.start("note")]
    return text


def _amount(raw: str) -> float:
    value = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    if value.startswith("-"):
        negative, value = not negative, value[1:]
    parsed = float(value)
    return -parsed if negative else parsed


def _cell_value(token: str) -> float | None:
    """A figure, or None for a dash, N/A or a placeholder."""
    if token in _ZERO_CELL or token.upper() in {"N/A", "NA"}:
        return None
    if _NUMBER_TOKEN_RE.match(token) or _INTEGER_TOKEN_RE.match(token):
        return _amount(token)
    return None


def _is_cell(token: str) -> bool:
    return (
        token in _ZERO_CELL
        or token.upper() == "N/A"
        or bool(_NUMBER_TOKEN_RE.match(token))
        or bool(_PERCENT_TOKEN_RE.match(token))
    )


def _split_cells(text: str, allow=_is_cell) -> tuple[str, list[str]]:
    """Splits a line into its leading label and the run of cells at its end."""
    tokens = text.split()
    cut = len(tokens)
    while cut > 0 and allow(tokens[cut - 1]):
        cut -= 1
    return " ".join(tokens[:cut]), tokens[cut:]


def _numeric_cells(cells: list[str]) -> list[str]:
    return [cell for cell in cells if not _PERCENT_TOKEN_RE.match(cell)]


def _decimal_count(text: str) -> int:
    return len(_DECIMAL_IN_LINE_RE.findall(text))


def _close(left: float, right: float, terms: int = 1) -> bool:
    # Half a cent per printed figure: every row is rounded to the cent.
    return abs(left - right) <= 0.005 * max(1, terms) + 0.01


def _reconcile(label: str, parsed: float, printed: float, stage: str, terms: int = 1) -> None:
    if not _close(parsed, printed, terms):
        raise diagnostic_helpers.reconciliation_error(
            f"{label} does not reconcile: parsed {parsed:.2f}, printed {printed:.2f}",
            parsed,
            printed,
            stage,
        )


# --- detection ---------------------------------------------------------------

# The cover's legal line. It is matched from "TRADE ..." on: a scrambled
# sample keeps that part (a parser phrase), but the single letter before
# the "*" only when the user typed an E*TRADE-like name. It still tells an
# E*TRADE statement from a Morgan Stanley Wealth one, which has the same
# layout and title.
_LEGAL_MARKER = "E*TRADE is a business of Morgan Stanley"
_LEGAL_MARKER_KEY = _LEGAL_MARKER.split("*", 1)[1].casefold()  # "trade is a business of morgan stanley"


def _looks_like_at_work(text: str) -> bool:
    lower = text.casefold()
    return (
        "client statement" in lower
        and _LEGAL_MARKER_KEY in lower
        and "morgan stanley smith barney llc" in lower
    )


def _detect_at_work(head_text: str) -> tuple[bool, str]:
    lower = head_text.casefold()
    required = {
        "CLIENT STATEMENT": "client statement" in lower,
        "E*TRADE/Morgan Stanley legal marker": _LEGAL_MARKER_KEY in lower,
        "Morgan Stanley Smith Barney LLC": "morgan stanley smith barney llc" in lower,
    }
    missing = [label for label, found in required.items() if not found]
    if missing:
        return False, "missing E*TRADE at Work marker(s): " + ", ".join(missing)
    return True, "found E*TRADE Morgan Stanley at Work Client Statement"


def detect(head_text: str) -> tuple[bool, str]:
    matched, reason = _detect_at_work(head_text)
    if matched:
        return matched, reason
    legacy_matched, legacy_reason = core.detect_profile(head_text, PROFILE_KEY)
    if legacy_matched:
        return legacy_matched, legacy_reason
    return False, f"{reason}; {legacy_reason}"


# --- period, account, lines --------------------------------------------------

def _year(raw: str) -> int:
    return 2000 + int(raw) if len(raw) == 2 else int(raw)


def _period(text: str) -> tuple[date, date]:
    match = _AT_WORK_PERIOD_RE.search(text)
    if match:
        try:
            end_year = int(match.group("end_year"))
            start_month = _MONTH_NUMBERS[match.group("start_month").casefold()]
            end_month = _MONTH_NUMBERS[(match.group("end_month") or match.group("start_month")).casefold()]
            if match.group("start_year"):
                start_year = int(match.group("start_year"))
            else:
                start_year = end_year - 1 if start_month > end_month else end_year
            start = date(start_year, start_month, int(match.group("start_day")))
            end = date(end_year, end_month, int(match.group("end_day")))
            if start <= end:
                return start, end
        except ValueError:
            pass
    numeric = _AT_WORK_NUMERIC_PERIOD_RE.search(text)
    if numeric:
        try:
            return (
                date(_year(numeric.group("start_year")), int(numeric.group("start_month")), int(numeric.group("start_day"))),
                date(_year(numeric.group("end_year")), int(numeric.group("end_month")), int(numeric.group("end_day"))),
            )
        except ValueError:
            pass
    raise parser_common.ParserDiagnosticError(
        "E*TRADE at Work statement period not found",
        code="PARSER_STATEMENT_DATE_INVALID",
        stage="metadata",
        missing_fields=("statementPeriod",),
    )


# Plain classes, not dataclasses: a drop-in is loaded by
# spec_from_file_location without a sys.modules entry, and Python 3.12's
# dataclass machinery looks its module up there.
class _Line:
    __slots__ = ("page", "no", "text")

    def __init__(self, page: int, no: int, text: str) -> None:
        self.page = page  # 1-based
        self.no = no      # 1-based, counting blank lines, as the page text has them
        self.text = text


class _Account:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.lines: list[_Line] = []
        self.title = ""  # the account's title, its holder's name removed

    @property
    def account(self) -> str:
        return common.last4_digits(self.provider_id)

    @property
    def account_type(self) -> str:
        # "Roth IRA", "IRA", "Rollover IRA" ...; a self-directed or Active
        # Assets account is an ordinary taxable brokerage account.
        return common.classify_account_type(self.title, "Brokerage")


def _account_title(line: str, holder_lines: set[str]) -> str:
    """The account title on the page-header line above an account banner,
    which also carries the holder's name: "Morgan Stanley at Work
    Self-Directed Account ALEX QUILL &", "Roth IRA ALEX QUILL". The name is
    the longest end of the line the cover prints as a line of its own (the
    mailing address); without one, a title naming an "Account" ends there.
    A holder's surname must never classify the account ("... Account
    DAVID ROTH")."""
    tokens = line.split()
    for cut in range(1, len(tokens)):
        suffix = " ".join(tokens[cut:])
        if suffix in holder_lines and re.search(r"[A-Za-z]", suffix):
            return " ".join(tokens[:cut])
    if line in holder_lines and not re.search(r"[a-z]", line):
        return ""  # the holder's name alone
    for position in range(len(tokens) - 1, -1, -1):
        if tokens[position] == "Account":
            return " ".join(tokens[:position + 1])
    return line


def _accounts(pages_text: list[str]) -> list[_Account]:
    """The statement's lines grouped by the account whose banner heads the
    page they are on, with page headers and footers removed. Lines before
    the first account banner (cover, disclosures) belong to none."""
    accounts: dict[str, _Account] = {}
    titles: dict[str, str] = {}
    holder_lines: set[str] = set()
    current: _Account | None = None
    unnamed = _Account("")
    any_banner = False
    for page_no, page in enumerate(pages_text, 1):
        numbered = [
            (index, raw.strip())
            for index, raw in enumerate(page.split("\n"), 1)
            if raw.strip()
        ]
        # The page header runs through the last account banner among the
        # page's first lines (it follows the holder's name).
        header_end = -1
        for position, (_, text) in enumerate(numbered[:8]):
            if _ACCOUNT_BANNER_RE.match(text):
                header_end = position
        for position, (index, text) in enumerate(numbered):
            banner = _ACCOUNT_BANNER_RE.match(text)
            if banner:
                any_banner = True
                found = _ACCOUNT_ID_RE.match(banner.group("rest"))
                if found:
                    provider_id = found.group("account")
                    current = accounts.setdefault(provider_id, _Account(provider_id))
                    if provider_id not in titles and 0 < position <= header_end:
                        above = numbered[position - 1][1]
                        if not _PAGE_FURNITURE_RE.match(above) and not _ACCOUNT_BANNER_RE.match(above):
                            titles[provider_id] = above
                continue
            if not any_banner:
                # The cover: the mailing address prints the holder's name
                # ("ALEX QUILL &", which a page header may print without "&").
                holder_lines.update({text, re.sub(r"\s*&$", "", text)})
            if position <= header_end or _PAGE_FURNITURE_RE.match(text):
                continue
            line = _Line(page_no, index, text)
            unnamed.lines.append(line)
            if current is not None:
                current.lines.append(line)
    if not any_banner or not accounts:
        return [unnamed]
    for provider_id, account in accounts.items():
        account.title = _account_title(titles.get(provider_id, ""), holder_lines)
    return list(accounts.values())


# --- CHANGE IN VALUE OF YOUR ACCOUNT ----------------------------------------

_AT_WORK_SUMMARY_LABELS = {
    "beginning": ("TOTAL BEGINNING VALUE", "totalBeginningValue"),
    "credits": ("Credits", "credits"),
    "debits": ("Debits", "debits"),
    "security_transfers": ("Security Transfers", "securityTransfers"),
    "net_transfers": ("Net Credits/Debits/Transfers", "netCreditsDebitsTransfers"),
    "market_change": ("Change in Value", "changeInValue"),
    "ending": ("TOTAL ENDING VALUE", "totalEndingValue"),
}


def _first_period_cell(line: str, label: str) -> float | None:
    match = re.match(
        rf"^{re.escape(label)}\s+(?P<value>{_SUMMARY_CELL})(?:\s|$)",
        line,
        re.I,
    )
    if not match:
        return None
    raw = match.group("value")
    return 0.0 if raw in _ZERO_CELL else _amount(raw)


def _summary(lines: list[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in lines:
        for key, (label, _) in _AT_WORK_SUMMARY_LABELS.items():
            if key in values:
                continue
            value = _first_period_cell(line, label)
            if value is not None:
                values[key] = value

    missing = [
        field_id
        for key, (_, field_id) in _AT_WORK_SUMMARY_LABELS.items()
        if key not in values
    ]
    if missing:
        raise parser_common.ParserDiagnosticError(
            "missing E*TRADE at Work account-summary controls",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="summary",
            missing_fields=missing,
        )

    core._require_close(
        "E*TRADE at Work net credits/debits/transfers",
        values["credits"] + values["debits"] + values["security_transfers"],
        values["net_transfers"],
        "summary",
    )
    core._require_close(
        "E*TRADE at Work account summary",
        values["beginning"] + values["net_transfers"] + values["market_change"],
        values["ending"],
        "summary",
    )
    return values


# --- CASH FLOW (the right half of the balance-sheet lines) -------------------

_CASH_FLOW_LABELS = {
    "opening": r"OPENING CASH(?:,\s*[^\s,$]+){1,2}",
    "purchases": r"Purchases",
    "reinvestments": r"Dividend Reinvestments",
    "sales": r"Sales and Redemptions",
    "income": r"Income and Distributions",
    "investment_total": r"Total Investment Related Activity",
    # The cash flow's own wordings: "Net Unsettled Purch/Sales" in the month
    # of a trade unsettled at month end, "Prior Net Unsettled
    # Purchases/Sales" in the month after. The BALANCE SHEET prints its own
    # "Net Unsettled Purchases/Sales <Last Period> <This Period>" at the
    # start of a line, and that is not a cash-flow figure.
    "unsettled": r"Prior\s+Net Unsettled Purch(?:ases)?/Sales|Net Unsettled Purch/Sales",
    "cash_total": r"Total Cash Related Activity",
    "card_total": r"Total Card/Check Activity",
    "closing": r"CLOSING CASH(?:,\s*[^\s,$]+){1,2}",
}
_CASH_FLOW_LABEL_RES = {
    key: re.compile(rf"(?:^|\s)(?:{pattern})\s+(?P<value>{_SUMMARY_CELL})(?=\s|$)")
    for key, pattern in _CASH_FLOW_LABELS.items()
}
# The full wording, on the cash-flow (right-hand) half of a merged line only.
_CASH_FLOW_UNSETTLED_RIGHT_RE = re.compile(
    rf"\s(?<!Prior\s)Net Unsettled Purchases/Sales\s+(?P<value>{_SUMMARY_CELL})(?=\s|$)"
)


def _cash_flow_summary(lines: list[_Line]) -> dict[str, float]:
    """This Period figures of the CASH FLOW summary. It shares its lines
    with the BALANCE SHEET, so labels are found anywhere on a line, and
    only between the CASH FLOW heading and CLOSING CASH."""
    start = next(
        (
            index for index, line in enumerate(lines)
            if re.search(r"\bCASH FLOW$", line.text) or line.text.endswith("CASH FLOW")
        ),
        None,
    )
    if start is None:
        return {}
    values: dict[str, float] = {}
    for line in lines[start + 1:start + 40]:
        for key, pattern in _CASH_FLOW_LABEL_RES.items():
            for match in pattern.finditer(line.text):
                raw = match.group("value")
                value = 0.0 if raw in _ZERO_CELL else _amount(raw)
                values[key] = values.get(key, 0.0) + value if key == "unsettled" else value
        for match in _CASH_FLOW_UNSETTLED_RIGHT_RE.finditer(line.text):
            raw = match.group("value")
            values["unsettled"] = values.get("unsettled", 0.0) + (0.0 if raw in _ZERO_CELL else _amount(raw))
        if "CLOSING CASH" in line.text:
            break
    return values


# --- HOLDINGS ---------------------------------------------------------------

# A class or series suffix follows ".", "'", "/" or "-" ("BRK'B", "HFC-PA"),
# or a space before a preferred series ("HFC PRA"); all read as ".".
_TICKER_RE = re.compile(
    r"^(?=[A-Z0-9.'/ -]*[A-Z])[A-Z0-9]{1,6}(?:[.'/-][A-Z0-9]{1,4}|\s(?=P)[A-Z]{1,4})?$"
)
_PAREN_RE = re.compile(r"\(([^()]{1,14})\)")
_PCT_TOTAL_RE = re.compile(
    r"^(?P<label>[^\d$]*[A-Za-z][^\d$]*?)\s+(?P<pct>-?[\d,]*\d(?:\.\d+)?)%\s+(?P<tail>\S.*)$"
)
_LONG_SHORT_RE = re.compile(rf"^Total\s+[A-Za-z&/ -]+?\s+\((?P<side>Long|Short)\)\s+(?P<value>{_MONEY})$")
_OCC_LINE_RE = re.compile(r"^\((?P<root>[A-Z][A-Z0-9.']{0,9})\s+(?P<code>[^()\s]{4,24})\)$")
_OSI_RE = re.compile(r"^(?P<ymd>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")
_OPTION_HOLDING_RE = re.compile(
    r"^(?P<right>CALL|PUT)S?\s+(?P<name>.+?)\s+AT\s+(?P<strike>[\d,]*\d(?:\.\d+)?)\s+"
    r"(?P<word>[A-Z]+)\s+(?P<exp>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<tail>\S.*)$"
)
_OPTION_COMPACT_RE = re.compile(
    r"^(?P<right>CALL|PUT)S?\s+(?P<name>.+?)\s+(?P<exp>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<strike>[\d,]*\d(?:\.\d+)?)(?=\s|$)(?P<rest>.*)$"
)
_LEGACY_POSITION_RE = re.compile(
    rf"^(?P<description>.+?)\s+(?P<symbol>[A-Z][A-Z0-9.\-]{{0,9}})\s+"
    rf"(?P<quantity>[\d,]+(?:\.\d+)?)\s+(?P<price>{_MONEY})\s+"
    rf"(?P<cost>{_MONEY})\s+(?P<market>{_MONEY})(?:\s+(?P<rest>.*))?$"
)
_CASH_BANK_RE = re.compile(r"^MORGAN STANLEY (?:PRIVATE )?BANK\b")
_CASH_SUBTOTAL_RE = re.compile(
    r"^(?:CASH,\s*\S+,?\s+AND\s+\S+|BANK DEPOSITS?|MONEY MARKET FUNDS?|TOTAL CASH\b.*)",
    re.I,
)
_HOLDINGS_END_RE = re.compile(
    r"^(?:ALLOCATION OF ASSETS\b|ACTIVITY$|CASH FLOW ACTIVITY BY DATE\b|MESSAGES$)"
)
_FUND_SUMMARY_LABEL_RE = re.compile(r"^(?:(?:Short|Long)[ -]Term )?(?:Reinvestments|Purchases)$")
_GENERIC_NAME_WORDS = frozenset(
    "A B C D INC CORP CORPORATION CO COMPANY LTD LIMITED PLC LLC LP L.P. NEW CL CLASS THE OF AND & "
    "ETF ETFS FUND FUNDS TRUST TR SHS SH SHARES COM ADR ADS SA NV AG SE HLDGS HOLDINGS HOLDING "
    "GROUP INTL INTERNATIONAL DEL N.A. NA".split()
)

_KIND_TYPES = {
    "cash": "Cash",
    "stock": "Stock",
    "preferred": "Preferred Stock",
    "options": "Options",
    "etf": "ETF",
    "mutual_fund": "Mutual Fund",
    "fixed_income": "Fixed Income",
    "uit": "Unit Investment Trust",
    "other": "Security",
}


def _section_kind(label: str, previous: str | None) -> str | None:
    upper = label.upper()
    if upper.startswith("OPTION"):
        return "options"
    if re.search(r"\bCASH\b|BANK DEPOSIT|MONEY MARKET", upper):
        return "cash"
    if "PREFERRED" in upper:
        return "preferred"
    if re.search(r"EXCHANGE-TRADED|\bETFS?\b|CLOSED-END", upper):
        return "etf"
    if "MUTUAL FUND" in upper:
        return "mutual_fund"
    if "UNIT INVESTMENT TRUST" in upper:
        return "uit"
    if re.search(r"FIXED INCOME|BONDS?\b|TREASUR|GOVERNMENT|CERTIFICATES? OF DEPOSIT|MUNICIPAL|AGENCY", upper):
        return "fixed_income"
    if re.search(r"STOCKS?\b|EQUIT", upper):
        return "stock"
    if re.search(r"ALTERNATIVE|STRUCTURED|^OTHER\b", upper):
        return "other"
    return previous


def _heading(text: str) -> str | None:
    """A section heading inside HOLDINGS: an upper-case line with no
    figures. "OPTIONS (Contract Prices are ...)" is the options heading."""
    if text == "OPTIONS" or text.startswith("OPTIONS ("):
        return "OPTIONS"
    if re.search(r"[\d$%#;:]", text) or re.search(r"[a-z]", text):
        return None
    if not re.fullmatch(r"[A-Z&,.'/()\- ]+", text):
        return None
    label = re.sub(r"\s*\(CONTINUED\)$", "", text).strip()
    return label if len(re.sub(r"[^A-Z]", "", label)) >= 3 else None


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*\(CONTINUED\)$", "", label.strip(), flags=re.I)).upper()


def _ticker(raw: str) -> str | None:
    raw = raw.strip()
    if not _TICKER_RE.match(raw):
        return None
    return re.sub(r"['/ -]", ".", raw)


def _strike(raw: str) -> str | None:
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _expiry(raw: str) -> date | None:
    try:
        month, day, year = raw.split("/")
        return date(_year(year), int(month), int(day))
    except ValueError:
        return None


def _adjusted_root(root: str) -> bool:
    """An adjusted contract's root carries a digit ("ACMR1"): its
    deliverable differs from the standard contract's, and an OCC code
    (letters only) cannot name it."""
    return bool(re.search(r"\d", root or ""))


def _occ_symbol(root: str, expiry: date | None, right: str, strike_raw: str) -> str:
    # A share-class separator ("BRK'B", "BRK.B", "BRK/B") is dropped; a
    # digit is not: the code would name the standard contract instead.
    root = re.sub(r"[.'/]", "", (root or "").upper())
    strike = _strike(strike_raw)
    if not re.fullmatch(r"[A-Z]+", root) or expiry is None or strike is None:
        return ""
    symbol = f"{root}{expiry:%y%m%d}{right[0].upper()}{strike}"
    return symbol if parser_common.OCC_SYMBOL.match(symbol) else ""


def _osi_symbol(root: str, code: str) -> str:
    """The contract a valid OSI code "(ROOT 270416C00130000)" names, else ''."""
    match = _OSI_RE.match(code)
    if not match:
        return ""
    ymd = match.group("ymd")
    try:
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
    except ValueError:
        return ""
    strike = str(Decimal(match.group("strike")) / 1000)
    return _occ_symbol(root, expiry, match.group("right"), strike)


class _Position:
    def __init__(self, kind: str, row: dict, value: float, quantity: float | None, *,
                 option: dict | None = None, block: str = "", block_price: float | None = None,
                 accrued: float = 0.0) -> None:
        self.kind = kind
        self.row = row
        self.value = value
        self.quantity = quantity
        self.option = option
        self.block = block            # "", "fund" (Purchases/Reinvestments/Total) or "lots"
        self.block_price = block_price
        self.accrued = accrued        # a bond's accrued interest, in its section total only


def _holding_row(kind: str, symbol: str, description: str, *, quantity=None, price=None,
                 cost=None, value=0.0, income=None, yield_pct=None) -> dict:
    row = {
        "symbol": symbol,
        "description": re.sub(r"\s+", " ", description).strip() or symbol,
    }
    if quantity is not None:
        row["quantity"] = quantity
    if price is not None:
        row["price"] = price
    if cost is not None:
        row["cost_basis_total"] = cost
    row["current_value"] = value
    if income is not None:
        row["estimated_annual_income"] = income
    if yield_pct is not None:
        row["estimated_yield"] = yield_pct
    row["type"] = _KIND_TYPES.get(kind, "Security")
    return row


def _security_cells(kind: str, cells: list[str]) -> dict | None:
    """qty price cost value [gain] [income] [yield] -> holding figures."""
    values = [_cell_value(cell) for cell in cells]
    if len(cells) < 4 or values[0] is None or values[3] is None:
        return None
    return {
        "quantity": values[0],
        "price": values[1],
        "cost": values[2],
        "value": values[3],
        "income": values[5] if len(values) > 5 else None,
        "yield_pct": values[6] if len(values) > 6 else None,
    }


def _ticker_row(text: str) -> tuple[str, str, list[str]] | None:
    """(description, ticker, tail tokens) for "DESCRIPTION (TICKER) ..."."""
    for match in reversed(list(_PAREN_RE.finditer(text))):
        symbol = _ticker(match.group(1))
        if not symbol:
            continue
        tail = text[match.end():].split()
        if not tail:
            continue
        description = text[:match.start()].strip()
        if not description:
            continue
        return description, symbol, tail
    return None


class _HoldingsReader:
    """Reads one account's HOLDINGS section, validating as it goes."""

    def __init__(self) -> None:
        self.positions: list[_Position] = []
        self.kind: str | None = None
        self.group_start = 0
        self.heading_start: dict[str, int] = {}
        self.covered: set[int] = set()
        self.subtotals: list[float] = []
        self.cash_adjustment = 0.0
        self.group_totals: list[float] = []
        self.last_group: tuple[int, int] | None = None
        self.total: float | None = None
        self.unrecognized = 0
        self.sections = 0
        self.pending: _Position | None = None
        self.section: str | None = None           # the last heading read
        self.bond: dict | None = None             # a bond's first line, until its CUSIP line
        self.bond_subtotal: str | None = None     # a fixed income subtotal, until its second line
        self.note_target: _Position | None = None  # the row a "Short Position" note below describes
        self.last_group_kind: str | None = None

    # -- groups and subtotals ------------------------------------------------

    def _finish_pending(self) -> None:
        self.pending = None
        self.bond = None
        self.bond_subtotal = None

    def _check_group(self, label: str, start: int, expected: float) -> None:
        indices = range(start, len(self.positions))
        uncovered = [i for i in indices if i not in self.covered]
        covered_any = any(i in self.covered for i in indices)
        if not covered_any:
            parsed = sum(self.positions[i].value + self.positions[i].accrued for i in uncovered) + self.cash_adjustment
            _reconcile(f"E*TRADE holdings {label}", parsed, expected, "holdings", len(uncovered))
        elif uncovered:
            parsed = (
                sum(self.positions[i].value + self.positions[i].accrued for i in uncovered)
                + sum(self.subtotals)
                + self.cash_adjustment
            )
            _reconcile(f"E*TRADE holdings {label}", parsed, expected, "holdings", len(uncovered) + 1)
        # A group whose rows are all covered by their own subtotals is not
        # checked against the group line: a scrambled sample keeps each
        # section's rows = subtotal, but not subtotals = group.

    def _close_group(self, label: str, expected: float) -> None:
        self._finish_pending()
        self._check_group(label, self.group_start, expected)
        if self.kind == "cash" and abs(self.cash_adjustment) > 0.0001:
            # NET UNSETTLED PURCHASES/SALES: the cash holding is the
            # projected settled balance the group line prints.
            cash = [p for p in self.positions[self.group_start:] if p.row.get("symbol") == "CASH"]
            _reconcile(
                "E*TRADE holdings projected settled cash",
                sum(p.value for p in self.positions[self.group_start:]) + self.cash_adjustment,
                expected,
                "holdings",
                len(self.positions) - self.group_start + 1,
            )
            if cash:
                cash[0].value += self.cash_adjustment
                cash[0].row["current_value"] = round(cash[0].value, 2)
        self.group_totals.append(expected)
        self.last_group = (self.group_start, len(self.positions))
        self.last_group_kind = self.kind
        self.group_start = len(self.positions)
        self.note_target = None
        self.heading_start = {}
        self.subtotals = []
        self.cash_adjustment = 0.0
        self.sections += 1

    def _reopen_settled_cash(self) -> None:
        """A month-end unsettled trade: "CASH, BDP, AND MMFs 0.97% $2,417.36",
        "NET UNSETTLED PURCHASES/SALES $89.45", then "CASH, BDP, AND MMFs
        (PROJECTED SETTLED BALANCE) 1.01% $2,506.81". The first line closed the
        cash group; the projected line closes it again, in place of the
        first: its rows plus the adjustment are the projected balance, and
        TOTAL VALUE counts that once."""
        if (
            self.kind == "cash"
            and self.last_group_kind == "cash"
            and self.last_group is not None
            and self.group_start == len(self.positions)
            and abs(self.cash_adjustment) > 0.0001
            and not self.subtotals
            and self.group_totals
        ):
            self.group_start = self.last_group[0]
            self.group_totals.pop()
            self.sections -= 1
            self.last_group = None

    def _subtotal(self, label: str, cells: list[str]) -> bool:
        key = _normalize_label(label)
        known = key in self.heading_start
        if not known and not (self.kind == "cash" and _CASH_SUBTOTAL_RE.match(label)):
            return False
        numeric = _numeric_cells(cells)
        if not numeric:
            return False
        self._finish_pending()
        if self.kind == "fixed_income":
            # "CORPORATE FIXED INCOME face orig-cost income yield", then a
            # line of its own: adj-cost value gain accrued.
            self.bond_subtotal = key
            return True
        index = 0 if self.kind == "cash" or len(numeric) == 1 else 1
        printed = _cell_value(numeric[index])
        self._cover(key, 0.0 if printed is None else printed, 0.0)
        return True

    def _cover(self, key: str, printed: float, accrued: float) -> None:
        start = self.heading_start.get(key, self.group_start)
        rows = [i for i in range(start, len(self.positions)) if i not in self.covered]
        _reconcile(
            f"E*TRADE holdings section {key}",
            sum(self.positions[i].value for i in rows),
            printed,
            "holdings",
            len(rows),
        )
        self.covered.update(rows)
        self.subtotals.append(printed + accrued)
        self.note_target = None

    def _fixed_income(self, text: str) -> bool:
        """A bond or CD: "DESCRIPTION face price orig-cost income yield", then
        "Coupon Rate ...; Matures ...; CUSIP X adj-cost value gain accrued"."""
        if self.bond_subtotal is not None:
            label, cells = _split_cells(text)
            numeric = _numeric_cells(cells)
            if not _decimal_count(text):
                return True  # a column header between the subtotal's two lines (a page break)
            key, self.bond_subtotal = self.bond_subtotal, None
            if not label and numeric:
                values = [_cell_value(cell) for cell in numeric]
                value = values[1] if len(values) >= 2 else values[0]
                accrued = values[3] if len(values) >= 4 and values[3] is not None else 0.0
                self._cover(key, value or 0.0, accrued)
                return True
        cusip = re.search(r"\bCUSIP\s+(?P<cusip>[0-9A-Z]{9})\b", text)
        if self.bond is not None and (cusip or re.search(r"\b(?:Coupon Rate|Matures)\b", text)):
            _, cells = _split_cells(text)
            values = [_cell_value(cell) for cell in _numeric_cells(cells)]
            if len(values) >= 2 and values[1] is not None:
                bond, self.bond = self.bond, None
                symbol = cusip.group("cusip") if cusip else ""
                row = _holding_row(
                    "fixed_income", symbol or bond["description"], bond["description"],
                    quantity=bond["face"], price=bond["price"],
                    cost=values[0] if values[0] is not None else bond["cost"],
                    value=values[1], income=bond["income"], yield_pct=bond["yield"],
                )
                if symbol:
                    row["cusip"] = symbol
                    row["security_id"] = symbol
                    row["security_id_type"] = "CUSIP"
                accrued = values[3] if len(values) >= 4 and values[3] is not None else 0.0
                self._add(_Position("fixed_income", row, values[1], bond["face"], accrued=accrued))
                return True
        label, cells = _split_cells(text)
        if (
            label
            and len(cells) >= 3
            and re.match(r"^[\d,]+\.\d{3}$", cells[0])
            and _normalize_label(label) not in self.heading_start  # a section subtotal
        ):
            values = [_cell_value(cell) for cell in cells]
            self.bond = {
                "description": label,
                "face": values[0],
                "price": values[1],
                "cost": values[2],
                "income": values[3] if len(values) > 3 else None,
                "yield": values[4] if len(values) > 4 else None,
            }
            return True
        return False

    # -- rows ---------------------------------------------------------------

    def _add(self, position: _Position) -> None:
        self.positions.append(position)
        self.note_target = position

    def _option(self, text: str) -> bool:
        match = _OPTION_HOLDING_RE.match(text)
        if match:
            name, strike, exp, tail = match.group("name"), match.group("strike"), match.group("exp"), match.group("tail")
        else:
            match = _OPTION_COMPACT_RE.match(text)
            if not match:
                return False
            name, strike, exp = match.group("name"), match.group("strike"), match.group("exp")
            tail = match.group("rest")
        tokens = tail.split()
        if not tokens or not all(_is_cell(token) for token in tokens):
            return False
        values = [_cell_value(token) for token in tokens]
        if len(values) < 4 or values[0] is None:
            return False
        if values[3] is None:
            # A short option with a cost and no market value: the statement
            # assumes $0 ("Where market value information is not available
            # ... we assume that market value is $0").
            if values[2] is None:
                return False
            values[3] = 0.0
        quantity, price, cost, value = values[0], values[1], values[2], values[3]
        row = _holding_row("options", "", text[: len(text) - len(tail)].strip(),
                           quantity=quantity, price=price, cost=cost, value=value)
        self._add(_Position("options", row, value, quantity, option={
            "right": match.group("right"),
            "name": name.strip(),
            "strike": strike,
            "expiry": _expiry(exp),
            "root": "",
            "osi": "",
        }))
        return True

    def _security(self, text: str) -> bool:
        found = _ticker_row(text)
        if not found:
            return False
        description, symbol, tail = found
        kind = self.kind or "other"
        first = tail[0]
        if first in {"Purchases", "Reinvestments"} and all(_is_cell(t) for t in tail[1:]):
            # A mutual fund block: the position is its "Total" line, or
            # this line when the block has none.
            values = [_cell_value(t) for t in tail[1:]]
            if len(values) < 4 or values[0] is None:
                return False
            if first == "Purchases":
                quantity, price, cost, value = values[0], values[1], values[2], values[3]
            else:
                quantity, price, cost, value = values[0], values[1], values[2], values[3]
            row = _holding_row(kind, symbol, description, quantity=quantity, price=price, cost=cost, value=value or 0.0)
            position = _Position(kind, row, value or 0.0, quantity, block="fund", block_price=price)
            self._add(position)
            self.pending = position
            return True
        if _DATE_TOKEN_RE.match(first) and all(_is_cell(t) or t in {"LT", "ST"} for t in tail[1:]):
            # A tax-lot block: trade date qty unit-cost price cost value gain term.
            values = [_cell_value(t) for t in tail[1:] if t not in {"LT", "ST"}]
            if len(values) < 6 or values[0] is None or values[4] is None:
                return False
            row = _holding_row(kind, symbol, description, quantity=values[0], price=values[2],
                               cost=values[3], value=values[4])
            position = _Position(kind, row, values[4], values[0], block="lots", block_price=values[2])
            self._add(position)
            self.pending = position
            return True
        if not all(_is_cell(t) for t in tail):
            return False
        if kind == "cash":
            values = [_cell_value(t) for t in tail]
            if values[0] is None:
                return False
            row = _holding_row("cash", symbol, description, value=values[0])
            row["type"] = "Money Market Fund"
            row["is_cash_equivalent"] = True
            self._add(_Position("cash", row, values[0], None))
            return True
        figures = _security_cells(kind, tail)
        if figures is None:
            return False
        row = _holding_row(kind, symbol, description, quantity=figures["quantity"], price=figures["price"],
                           cost=figures["cost"], value=figures["value"], income=figures["income"],
                           yield_pct=figures["yield_pct"])
        self._add(_Position(kind, row, figures["value"], figures["quantity"]))
        return True

    def _block_line(self, text: str) -> bool:
        """A line inside a fund or tax-lot block."""
        position = self.pending
        if position is None:
            return False
        label, cells = _split_cells(text, lambda t: _is_cell(t) or t in {"LT", "ST"})
        if label == "Total":
            values = [_cell_value(t) for t in cells if t not in {"LT", "ST"}]
            if len(values) < 3 or values[0] is None or values[2] is None:
                return False
            quantity, cost, value = values[0], values[1], values[2]
            income = values[4] if len(values) > 4 else None
            yield_pct = values[5] if len(values) > 5 else None
            position.quantity, position.value = quantity, value
            row = position.row
            row["quantity"] = quantity
            if cost is not None:
                row["cost_basis_total"] = cost
            else:
                row.pop("cost_basis_total", None)
            row["current_value"] = value
            if income is not None:
                row["estimated_annual_income"] = income
            if yield_pct is not None:
                row["estimated_yield"] = yield_pct
            self.pending = None
            return True
        if _FUND_SUMMARY_LABEL_RE.match(label) and cells:
            # A fund's Purchases/Reinvestments lines - in lot form they
            # follow the lots - summarise the block; "Total" is the position.
            return True
        if position.block == "lots" and _DATE_TOKEN_RE.match(label) and len(cells) >= 5:
            return True  # another lot of the same position
        return False

    def _cash_row(self, text: str) -> bool:
        if not (self.kind == "cash" or (self.kind is None and _CASH_BANK_RE.match(text))):
            return False
        if _ticker_row(text):
            return False
        label, cells = _split_cells(text)
        numeric = _numeric_cells(cells)
        if not label or not numeric or not re.match(rf"^{_MONEY}$", numeric[0]):
            return False
        if any(_REDACTED_TOKEN_RE.match(cell) for cell in numeric[:1]):
            return True  # a masked balance: nothing to read
        value = _amount(numeric[0])
        description = re.sub(r"\s*#\s*$", "", label).strip()
        income = _cell_value(numeric[2]) if len(numeric) >= 4 else None
        row = _holding_row("cash", "CASH", description, value=value, income=income)
        row["type"] = "Cash"
        row["is_cash_equivalent"] = True
        self._add(_Position("cash", row, value, None))
        return True

    def _legacy_row(self, text: str) -> bool:
        if self.kind in {"cash", "options", "fixed_income"}:
            return False
        match = _LEGACY_POSITION_RE.match(text)
        if not match or any(
            "x" in match.group(name).casefold() for name in ("quantity", "price", "cost", "market")
        ):
            return False
        kind = self.kind or "other"
        row = _holding_row(
            kind,
            match.group("symbol"),
            match.group("description"),
            quantity=float(match.group("quantity").replace(",", "")),
            price=_amount(match.group("price")),
            cost=_amount(match.group("cost")),
            value=_amount(match.group("market")),
        )
        self._add(_Position(kind, row, row["current_value"], row["quantity"]))
        return True

    # -- the section --------------------------------------------------------

    def read(self, lines: list[_Line]) -> None:
        for line in lines:
            text = _holdings_text(line.text)
            if _FOOTER_CODE_RE.match(text):
                continue  # a page foot's scan code ("418KDPLM", "903311")
            pct = _PCT_TOTAL_RE.match(text)
            if pct and pct.group("label").upper().startswith("TOTAL VALUE"):
                cells = pct.group("tail").split()
                if not cells or not all(_is_cell(cell) for cell in cells):
                    continue
                numeric = _numeric_cells(cells)
                printed = _cell_value(numeric[1] if len(numeric) >= 2 else numeric[0]) if numeric else None
                if printed is None:
                    continue
                self._finish_pending()
                expected = printed - sum(self.group_totals)
                self._check_group("total", self.group_start, expected)
                self.total = printed
                return
            if re.match(r"^TOTAL MARKET VALUE\b", text):
                continue
            if text.startswith("TOTAL VALUE") and not pct:
                label, cells = _split_cells(text)
                numeric = _numeric_cells(cells)
                if label.startswith("TOTAL VALUE") and numeric:
                    printed = _cell_value(numeric[1] if len(numeric) >= 2 else numeric[0])
                    if printed is None and all(cell in _ZERO_CELL for cell in numeric):
                        printed = 0.0  # an emptied account: "TOTAL VALUE — — — — —"
                    if printed is not None:
                        self._finish_pending()
                        self._check_group("total", self.group_start, printed - sum(self.group_totals))
                        self.total = printed
                        return
            long_short = _LONG_SHORT_RE.match(text)
            if long_short:
                self._long_short(long_short.group("side"), _amount(long_short.group("value")))
                continue
            if pct and all(_is_cell(cell) for cell in pct.group("tail").split()):
                numeric = _numeric_cells(pct.group("tail").split())
                if numeric:
                    index = 0 if self.kind == "cash" or len(numeric) == 1 else 1
                    printed = _cell_value(numeric[index])
                    self._reopen_settled_cash()
                    self._close_group(_normalize_label(pct.group("label")), printed or 0.0)
                    continue
            heading = _heading(text)
            if heading:
                key = _normalize_label(heading)
                continued = re.search(r"\(CONTINUED\)$", text) is not None
                if self.pending is not None and self.pending.block and not continued:
                    # A fund or lot block ends at a new heading, but not at
                    # a "(CONTINUED)" heading after a page break: its own
                    # section's or a parent category's ("STOCKS (CONTINUED)"
                    # above "COMMON STOCKS (CONTINUED)").
                    self._finish_pending()
                self.kind = _section_kind(key, self.kind)
                self.heading_start.setdefault(key, len(self.positions))
                self.section = key
                continue
            occ = _OCC_LINE_RE.match(text)
            if occ:
                for position in reversed(self.positions):
                    if position.option is not None:
                        if not position.option["root"]:
                            position.option["root"] = occ.group("root")
                            position.option["osi"] = occ.group("code")
                        break
                continue
            if text.startswith("Short Position"):
                # The note describes the row above it, and only one that was
                # read: never a position above a row that was not.
                last = self.note_target
                if last is not None and last.quantity is not None and last.quantity > 0:
                    last.quantity = -last.quantity
                    last.row["quantity"] = last.quantity
                continue
            if self.pending is not None and self._block_line(text):
                continue
            if re.match(r"^NET UNSETTLED PURCHASES/SALES\b", text, re.I) and self.kind == "cash":
                _, cells = _split_cells(text)
                numeric = _numeric_cells(cells)
                if numeric and _cell_value(numeric[0]) is not None:
                    self.cash_adjustment += _cell_value(numeric[0])
                continue
            if self.kind == "options" and self._option(text):
                continue
            if self.kind == "fixed_income" and self._fixed_income(text):
                continue
            if self._security(text):
                continue
            label, cells = _split_cells(text)
            if label and cells and self._subtotal(label, cells):
                continue
            if self._cash_row(text):
                continue
            if self._legacy_row(text):
                continue
            if self.kind != "options" and self._option(text):
                continue
            if _decimal_count(text):
                self.note_target = None  # a figure line not read
            if _decimal_count(text) >= 3:
                self.unrecognized += 1

    def _long_short(self, side: str, printed: float) -> None:
        if self.last_group is None:
            return
        start, end = self.last_group
        rows = self.positions[start:end]
        if side == "Long":
            chosen = [p for p in rows if p.quantity is None or p.quantity >= 0]
        else:
            chosen = [p for p in rows if p.quantity is not None and p.quantity < 0]
        _reconcile(f"E*TRADE holdings {side.lower()} positions", sum(p.value for p in chosen), printed,
                   "holdings", len(chosen))

    def finish(self, names: dict[str, str]) -> None:
        for position in self.positions:
            option = position.option
            if option is None:
                continue
            if _adjusted_root(option["root"]):
                # Kept as printed, never merged into the standard contract.
                printed = f"{option['root']} {option['osi']}".strip()
                position.row["symbol"] = printed or position.row["description"]
                continue
            symbol = _occ_symbol(option["root"], option["expiry"], option["right"], option["strike"])
            if not symbol:
                root = names.get(_normalize_label(option["name"]), "")
                if not root and re.fullmatch(r"[A-Z]{1,6}", option["name"]):
                    root = option["name"]
                symbol = _occ_symbol(root, option["expiry"], option["right"], option["strike"])
            if not symbol and option["root"] and option["osi"]:
                symbol = _osi_symbol(option["root"], option["osi"])
            position.row["symbol"] = symbol or position.row["description"]


def _holdings(lines: list[_Line], account: _Account, statement_date: str,
              ending: float | None = None) -> tuple[list[dict], float, _HoldingsReader]:
    start = next((index for index, line in enumerate(lines) if line.text == "HOLDINGS"), None)
    reader = _HoldingsReader()
    empty = ending is not None and abs(ending) < 0.005
    if start is None and empty:
        # An account worth nothing (a stock-plan account after a sale)
        # prints no HOLDINGS at all.
        return [], 0.0, reader
    if start is not None:
        section: list[_Line] = []
        for line in lines[start + 1:]:
            if _HOLDINGS_END_RE.match(line.text):
                break
            section.append(line)
        try:
            reader.read(section)
        except parser_common.ParserDiagnosticError as error:
            if not reader.unrecognized:
                raise
            # A section that does not add up after a line shaped like a
            # position was not read: say so, rather than only that it
            # does not add up.
            raise parser_common.ParserDiagnosticError(
                f"E*TRADE holdings rows not recognized ({error})",
                code="PARSER_UNCLASSIFIED_ROW",
                stage="holdings",
                counts={"unrecognizedHoldingLines": reader.unrecognized},
                reconciliation_direction=error.reconciliation_direction,
            ) from error
    if reader.total is None:
        if reader.unrecognized:
            raise parser_common.ParserDiagnosticError(
                "E*TRADE holdings rows not recognized",
                code="PARSER_UNCLASSIFIED_ROW",
                stage="holdings",
                counts={"unrecognizedHoldingLines": reader.unrecognized},
            )
        raise parser_common.ParserDiagnosticError(
            "E*TRADE at Work holdings total not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("totalValue",),
        )
    if not reader.positions and not (empty and abs(reader.total) < 0.005):
        raise parser_common.ParserDiagnosticError(
            "E*TRADE at Work cash holding not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("cashHolding",),
        )
    if reader.unrecognized:
        # Every section reconciled, but a line shaped like a position was
        # not read: a missed section can carry its own subtotal with it.
        raise parser_common.ParserDiagnosticError(
            "E*TRADE holdings rows not recognized",
            code="PARSER_UNCLASSIFIED_ROW",
            stage="holdings",
            counts={"unrecognizedHoldingLines": reader.unrecognized},
        )
    names = {
        _normalize_label(p.row["description"]): p.row["symbol"]
        for p in reader.positions
        if p.option is None and p.row.get("symbol") not in ("", "CASH")
    }
    reader.finish(names)

    rows: list[dict] = []
    cash_rows = [p for p in reader.positions if p.row.get("symbol") == "CASH"]
    for position in reader.positions:
        if position.row.get("symbol") == "CASH" and len(cash_rows) > 1:
            if position is not cash_rows[0]:
                continue
            # One CASH holding per account: several bank deposit rows are
            # one balance (holdings are unique by account and symbol).
            first = dict(position.row)
            first["current_value"] = round(sum(p.value for p in cash_rows), 2)
            first["description"] = "; ".join(dict.fromkeys(p.row["description"] for p in cash_rows))
            incomes = [p.row["estimated_annual_income"] for p in cash_rows if "estimated_annual_income" in p.row]
            if incomes:
                first["estimated_annual_income"] = round(sum(incomes), 2)
            row = first
        else:
            row = dict(position.row)
        row["currency_code"] = "USD"
        row["price_as_of"] = statement_date
        row["account"] = account.account
        row["accountType"] = account.account_type
        row["provider_account_id"] = account.provider_id
        rows.append(row)
    return rows, reader.total, reader


# --- ACTIVITY ---------------------------------------------------------------

# (printed activity word, transaction_type, CASH FLOW summary line it is
# counted in, whether that line is certain). A transaction_type "+a/-b"
# depends on the row's sign. Words are matched longest first, in the case
# the statement prints them (Title Case; descriptions are upper case).
_ACTIVITY_WORDS: tuple[tuple[str, str, str, bool], ...] = (
    # trades
    ("Bought", "buy", "purchases", True),
    ("Buy", "buy", "purchases", True),
    ("Purchase", "buy", "purchases", True),
    ("Purchased", "buy", "purchases", True),
    ("Bought to Cover", "buy", "purchases", True),
    ("Bought to Close", "buy", "purchases", True),
    ("Bought to Open", "buy", "purchases", True),
    ("Buy to Cover", "buy", "purchases", True),
    ("Buy to Close", "buy", "purchases", True),
    ("Buy to Open", "buy", "purchases", True),
    ("Cover Short", "buy", "purchases", True),
    ("Short Cover", "buy", "purchases", True),
    ("Sold", "sell", "sales", True),
    ("Sell", "sell", "sales", True),
    ("Sale", "sell", "sales", True),
    ("Sold Short", "sell", "sales", True),
    ("Short Sale", "sell", "sales", True),
    ("Sell Short", "sell", "sales", True),
    ("Sold to Open", "sell", "sales", True),
    ("Sold to Close", "sell", "sales", True),
    ("Sell to Open", "sell", "sales", True),
    ("Sell to Close", "sell", "sales", True),
    ("Redemption", "redemption", "sales", True),
    ("Redeemed", "redemption", "sales", False),
    ("Return of Principal", "redemption", "sales", False),
    ("Principal Payment", "redemption", "sales", False),
    ("Maturity", "redemption", "sales", False),
    ("Cash in Lieu", "sell", "", False),
    ("Cash in Lieu of Fractional Shares", "sell", "", False),
    # reinvestment (a reinvestment is a buy)
    ("Dividend Reinvestment", "buy", "reinvestments", True),
    ("Dividend Reinvested", "buy", "reinvestments", True),
    ("Reinvested Dividend", "buy", "reinvestments", True),
    ("Reinvestment", "buy", "reinvestments", True),
    ("Reinvest", "buy", "reinvestments", True),
    ("Capital Gain Reinvestment", "buy", "reinvestments", True),
    ("Interest Reinvestment", "buy", "reinvestments", True),
    # income
    ("Dividend", "dividend", "income", True),
    ("Dividends", "dividend", "income", True),
    ("Qualified Dividend", "dividend", "income", True),
    ("Non-Qualified Dividend", "dividend", "income", True),
    ("Nonqualified Dividend", "dividend", "income", True),
    ("Ordinary Dividend", "dividend", "income", True),
    ("Other Dividend", "dividend", "income", True),
    ("Other Dividends", "dividend", "income", True),
    ("Tax Exempt Dividend", "dividend", "income", True),
    ("Tax-Exempt Dividend", "dividend", "income", True),
    ("Special Dividend", "dividend", "income", True),
    ("Foreign Dividend", "dividend", "income", True),
    ("Cash Dividend", "dividend", "income", True),
    ("Dividend Received", "dividend", "income", True),
    ("Interest", "interest", "income", True),
    ("Interest Income", "interest", "income", True),
    ("Tax Exempt Interest Income", "interest", "income", True),
    ("Tax-Exempt Interest Income", "interest", "income", True),
    ("Tax Exempt Interest", "interest", "income", True),
    ("Bank Interest", "interest", "income", True),
    ("Credit Interest", "interest", "income", True),
    ("Interest Credit", "interest", "income", True),
    ("Interest Earned", "interest", "income", True),
    ("Bond Interest", "interest", "income", True),
    ("Capital Gain", "capital_gain", "income", True),
    ("Capital Gains", "capital_gain", "income", True),
    ("Capital Gain Distribution", "capital_gain", "income", True),
    ("Capital Gains Distribution", "capital_gain", "income", True),
    ("Long Term Capital Gain", "capital_gain", "income", True),
    ("Short Term Capital Gain", "capital_gain", "income", True),
    ("Long-Term Capital Gain", "capital_gain", "income", True),
    ("Short-Term Capital Gain", "capital_gain", "income", True),
    ("LT Capital Gain", "capital_gain", "income", True),
    ("ST Capital Gain", "capital_gain", "income", True),
    ("Partnership Distribution", "income", "income", False),
    ("Return of Capital", "other", "", False),
    # money in and out
    ("Funds Received", "deposit", "cash", True),
    ("Funds Transferred", "withdrawal", "cash", True),
    ("Funds Disbursed", "withdrawal", "cash", True),
    ("Funds Paid", "withdrawal", "cash", True),
    ("Deposit", "deposit", "cash", True),
    ("Cash Deposit", "deposit", "cash", True),
    ("Check Deposit", "deposit", "cash", True),
    ("Direct Deposit", "deposit", "cash", True),
    ("Mobile Deposit", "deposit", "cash", True),
    ("Withdrawal", "withdrawal", "cash", True),
    ("Cash Withdrawal", "withdrawal", "cash", True),
    ("Electronic Transfer", "+deposit/-withdrawal", "cash", True),
    ("Electronic Transfers", "+deposit/-withdrawal", "cash", True),
    ("Electronic Funds Transfer", "+deposit/-withdrawal", "cash", True),
    ("EFT", "+deposit/-withdrawal", "cash", True),
    ("ACH", "+deposit/-withdrawal", "cash", True),
    ("ACH Transfer", "+deposit/-withdrawal", "cash", True),
    ("ACH Deposit", "deposit", "cash", True),
    ("ACH Credit", "deposit", "cash", True),
    ("ACH Withdrawal", "withdrawal", "cash", True),
    ("ACH Debit", "withdrawal", "cash", True),
    ("Automated Deposit", "deposit", "cash", True),
    ("Automated Payment", "withdrawal", "cash", True),
    ("Wire", "+deposit/-withdrawal", "cash", True),
    ("Wire Transfer", "+deposit/-withdrawal", "cash", True),
    ("Wire Received", "deposit", "cash", True),
    ("Wire In", "deposit", "cash", True),
    ("Wire Sent", "withdrawal", "cash", True),
    ("Wire Out", "withdrawal", "cash", True),
    ("Wire Transferred", "withdrawal", "cash", True),
    ("Fed Wire", "+deposit/-withdrawal", "cash", True),
    ("Cash Transfer", "internal_transfer", "cash", True),
    ("Transfer Between Accounts", "internal_transfer", "cash", True),
    ("Internal Transfer", "internal_transfer", "cash", True),
    ("Journal", "internal_transfer", "cash", False),
    ("Journal Entry", "internal_transfer", "cash", False),
    ("Cash Journal", "internal_transfer", "cash", False),
    ("Journaled", "internal_transfer", "cash", False),
    ("Electronic Transfer", "+deposit/-withdrawal", "cash", True),
    ("Contribution", "contribution", "cash", False),
    ("IRA Contribution", "contribution", "cash", False),
    ("Employee Contribution", "contribution", "cash", False),
    ("Employer Contribution", "contribution", "cash", False),
    ("Prior Year Contribution", "contribution", "cash", False),
    ("Current Year Contribution", "contribution", "cash", False),
    ("Distribution", "+income/-distribution", "", False),
    ("IRA Distribution", "distribution", "cash", False),
    ("Required Minimum Distribution", "distribution", "cash", False),
    ("Normal Distribution", "distribution", "cash", False),
    ("Early Distribution", "distribution", "cash", False),
    ("Rollover", "+rollover_in/-rollover_out", "cash", False),
    ("Rollover Contribution", "rollover_in", "cash", False),
    ("Rollover Distribution", "rollover_out", "cash", False),
    # spending by card, check or bill payment (the CASH FLOW summary's
    # Total Card/Check Activity); a refund or a deposited check is money in
    ("Debit Card", "+deposit/-withdrawal", "card", True),
    ("Debit Card Purchase", "+deposit/-withdrawal", "card", True),
    ("Debit Card Refund", "+deposit/-withdrawal", "card", True),
    ("Debit Card Credit", "+deposit/-withdrawal", "card", True),
    ("ATM Withdrawal", "+deposit/-withdrawal", "card", True),
    ("Check", "+deposit/-withdrawal", "card", True),
    ("Check Paid", "+deposit/-withdrawal", "card", True),
    ("Checks Written", "+deposit/-withdrawal", "card", True),
    ("Bill Payment", "+deposit/-withdrawal", "card", True),
    ("Bill Pay", "+deposit/-withdrawal", "card", True),
    # charges and taxes
    ("Fee", "fee", "", False),
    ("Fees", "fee", "", False),
    ("Service Fee", "fee", "", False),
    ("Account Fee", "fee", "", False),
    ("Annual Fee", "fee", "", False),
    ("Annual Account Fee", "fee", "", False),
    ("Maintenance Fee", "fee", "", False),
    ("Advisory Fee", "fee", "", False),
    ("Management Fee", "fee", "", False),
    ("Wire Fee", "fee", "", False),
    ("Transfer Fee", "fee", "", False),
    ("ADR Fee", "fee", "", False),
    ("Regulatory Fee", "fee", "", False),
    ("Commission", "fee", "", False),
    ("Fee Reversal", "fee", "", False),
    ("Fee Refund", "fee", "", False),
    ("Margin Interest", "fee", "", False),
    ("Margin Interest Charged", "fee", "", False),
    ("Interest Charged", "fee", "", False),
    ("Debit Interest", "fee", "", False),
    ("Foreign Tax Withheld", "tax", "", False),
    ("Foreign Tax Paid", "tax", "", False),
    ("Foreign Tax", "tax", "", False),
    ("Foreign Withholding", "tax", "", False),
    ("Foreign Tax Refund", "tax", "", False),
    ("Federal Tax Withheld", "tax", "", False),
    ("Federal Withholding", "tax", "", False),
    ("State Tax Withheld", "tax", "", False),
    ("State Withholding", "tax", "", False),
    ("Backup Withholding", "tax", "", False),
    ("NRA Withholding", "tax", "", False),
    ("Tax Withheld", "tax", "", False),
)

# The TRANSFERS, CORPORATE ACTIONS AND ADDITIONAL ACTIVITY table: share and
# contract movements (amount 0.00) and security transfers.
_CORPORATE_WORDS: tuple[tuple[str, str], ...] = (
    ("Option Expired", "expired"),
    ("Option Expiration", "expired"),
    ("Expired", "expired"),
    ("Expiration", "expired"),
    ("Option Assigned", "assigned"),
    ("Option Assignment", "assigned"),
    ("Assigned", "assigned"),
    ("Assignment", "assigned"),
    ("Option Exercised", "exercised"),
    ("Option Exercise", "exercised"),
    ("Exercised", "exercised"),
    ("Exercise", "exercised"),
    ("Transfer into Account", "transfer_in"),
    ("Transfer Into Account", "transfer_in"),
    ("Transfer In", "transfer_in"),
    ("Securities Received", "transfer_in"),
    ("Security Received", "transfer_in"),
    ("Received", "transfer_in"),
    ("Transfer out of Account", "transfer_out"),
    ("Transfer Out of Account", "transfer_out"),
    ("Transfer Out", "transfer_out"),
    ("Securities Delivered", "transfer_out"),
    ("Security Delivered", "transfer_out"),
    ("Delivered", "transfer_out"),
    ("Exchange Received In", "in"),
    ("Exchange Delivered Out", "out"),
    ("Merger In", "in"),
    ("Merger Out", "out"),
    ("Merger", "signed"),
    # A split row's quantity is the change in shares, which orby-core's tax
    # lots apply as a split ratio (tax_lots.go applySplitRatio: the action's
    # word "split" or "reverse" names the event). A reverse split only ever
    # removes shares, so it is negative even when printed unsigned, as this
    # section prints contracts; a forward split keeps the printed sign.
    ("Stock Split", "signed"),
    ("Forward Split", "signed"),
    ("Reverse Split", "out"),
    ("Reverse Stock Split", "out"),
    ("Stock Dividend", "signed"),
    ("Spin-Off", "signed"),
    ("Spinoff", "signed"),
    ("Spin Off", "signed"),
    ("Name Change", "signed"),
    ("Symbol Change", "signed"),
    ("Tender", "signed"),
    ("Conversion", "signed"),
    ("Exchange", "signed"),
    ("Redemption", "signed"),
)


def _corporate_event(label: str, event: str, subtype: str) -> str:
    """corporate_event for a TRANSFERS, CORPORATE ACTIONS row. The vocabulary's
    stated events come from the shared label reader; what is left are the
    shapes E*TRADE prints without a cause (a stock dividend, a name change, a
    tender), which stay observed kinds or "other"."""
    if event in {"expired", "assigned", "exercised"}:
        return event
    stated = parser_common.label_event(label, subtype)
    if stated:
        return stated
    words = label.lower()
    incoming = subtype == "In"
    if "stock dividend" in words:
        return "share_distribution"
    if any(w in words for w in ("name change", "symbol change")):
        return "conversion_in" if incoming else "conversion_out"
    if any(w in words for w in ("exchange", "tender", "redemption")):
        return "share_exchange_in" if incoming else "share_exchange_out"
    return "other"


def _by_length(words):
    return tuple(sorted(words, key=lambda item: len(item[0]), reverse=True))


_ACTIVITY_WORDS_SORTED = _by_length(_ACTIVITY_WORDS)
_CORPORATE_WORDS_SORTED = _by_length(_CORPORATE_WORDS)

_DATED_RE = re.compile(
    r"^(?P<d1>\d{1,2}/\d{1,2})(?![/\d])(?:\s+(?P<d2>\d{1,2}/\d{1,2})(?![/\d]))?\s+(?P<body>\S.*)$"
)
_DATED_START_RE = re.compile(r"^\d{1,2}/\d{1,2}(?![/\d])\s")
_AMOUNT_TAIL_RE = re.compile(rf"\s(?P<amount>{_MONEY})$")
_DASH_TAIL_RE = re.compile(r"\s(?P<amount>—|–|--|-)$")
# A cell between a transfer's quantity and its amount (Accrued Interest).
_ACCRUED_TAIL_RE = re.compile(rf"\s(?:{_MONEY}|—|–|--|-|N/?A)$")
# Rows whose shares or contracts leave the account carry a negative
# quantity, as the option figures read it (a sell to open is a row with
# quantity < 0) and as the other brokerage parsers emit it.
_OUTGOING_TYPES = frozenset({"sell", "redemption"})
_QTY_PRICE_TAIL_RE = re.compile(r"\s(?P<qty>\(?-?[\d,]+\.\d+\)?)\s+(?P<price>\$?[\d,]+\.\d{3,})$")
_QTY_TAIL_RE = re.compile(r"\s(?P<qty>\(?-?[\d,]*\d\.\d{3,}\)?)$")
_MONEY_END_RE = re.compile(rf"(?:^|\s){_MONEY}$")
_NET_CREDITS_RE = re.compile(rf"^NET CREDITS/\(DEBITS\)\s+(?P<value>{_SUMMARY_CELL})(?:\s|$)")
_SECURITY_TRANSFERS_TOTAL_RE = re.compile(rf"^TOTAL SECURITY TRANSFERS\s+(?P<value>{_SUMMARY_CELL})(?:\s|$)")
_COLUMN_HEADER_RE = re.compile(r"^(?:Activity|Date|Pending)\b")
_SKIPPED_SECTION_RE = re.compile(
    r"^(?:UNSETTLED PURCHASES/SALES ACTIVITY|MARGIN LOAN INTEREST SCHEDULE|MESSAGES$|"
    r"DEBIT CARD|CHECKING ACTIVITY|CHECKS WRITTEN|OPEN ORDERS|HOLDINGS$|ALLOCATION OF ASSETS|"
    r"ELECTRONIC TRANSFERS ACTIVITY|BILL PAY|REALIZED GAIN)"
)
# Sections listing cash spent by debit card, check or bill payment, outside
# CASH FLOW ACTIVITY BY DATE (the summary's Total Card/Check Activity):
# "DEBIT CARD ACTIVITY", "CHECKING ACTIVITY", "CHECKS WRITTEN", "BILL PAY".
_CARD_SECTION_RE = re.compile(
    r"^(?P<label>(?:DEBIT CARD|CHECKING ACTIVITY|CHECKS WRITTEN|BILL PAY)[A-Z0-9 &/,'-]*?)\s*(?:\(CONTINUED\))?$"
)
# A row there: the check number when it comes first, the transaction (and
# settlement or cleared) date, the merchant or payee, the amount.
_CARD_DATE = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?(?![/\d])"
_CARD_ROW_RE = re.compile(
    rf"^(?:(?P<number>\d{{1,10}})\s+)?(?P<d1>{_CARD_DATE})(?:\s+(?P<d2>{_CARD_DATE}))?"
    rf"(?:\s+(?P<body>.*?))?\s+(?P<amount>{_MONEY})$"
)
_CARD_START_RE = re.compile(rf"^(?:\d{{1,10}}\s+)?{_CARD_DATE}\s")
_CARD_TOTAL_RE = re.compile(rf"^(?P<sub>SUB-?)?TOTAL\b.*?\s(?P<value>{_MONEY})$", re.I)
# An upper-case heading with one of these words ends those sections.
_SECTION_WORD_RE = re.compile(r"\b(?:ACTIVITY|TRANSFERS|DETAIL|SUMMARY|SCHEDULE|ORDERS|MESSAGES)\b")
_CUSIP_RE = re.compile(r"\[(?P<cusip>[0-9]{3}[0-9A-Z]{5}[0-9])\]")  # "... DUE2032-01-15 [4124866N7]"
_OPTION_TRADE_RE = re.compile(
    r"^(?P<right>CALL|PUT)S?\s+(?P<root>[A-Z][A-Z0-9.']{0,9})\s+(?P<exp>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<strike>[\d,]*\d(?:\.\d+)?)(?=\s|$)"
)
_TITLE_WORD_RE = re.compile(r"^[A-Z][a-z]+\b")


def _match_word(text: str, words) -> tuple | None:
    """The activity word at the start of text, as (entry, printed word)."""
    for entry in words:
        label = entry[0]
        size = len(label)
        if len(text) < size or text[:size].casefold() != label.casefold():
            continue
        if len(text) > size and text[size] != " ":
            continue
        printed = text[:size]
        if printed != label and not re.search(r"[a-z]", printed):
            continue  # an upper-case description word, not the activity type
        if _TITLE_WORD_RE.match(text[size:].strip()):
            # "Dividend Adjustment ...": a longer activity word we do not
            # know (descriptions print in upper case).
            continue
        return entry, printed
    return None


def _resolve_date(raw: str, start: date, end: date) -> str:
    """A month/day in the period, else the nearest date to it: a card or
    check transaction made in December and posted in January belongs to
    the year before a January statement's, not to its December."""
    month, day = (int(value) for value in raw.split("/"))
    candidates = []
    for year in range(start.year - 1, end.year + 2):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("invalid activity date")
    inside = [d for d in candidates if start <= d <= end]
    if inside:
        return inside[0].isoformat()

    def distance(d: date) -> int:
        return (start - d).days if d < start else (d - end).days

    return min(candidates, key=distance).isoformat()


def _option_symbol_from_text(description: str, names: dict[str, str]) -> str:
    match = _OPTION_TRADE_RE.match(description)
    if match:
        return _occ_symbol(match.group("root"), _expiry(match.group("exp")), match.group("right"), match.group("strike"))
    compact = _OPTION_COMPACT_RE.match(description) or _OPTION_HOLDING_RE.match(description)
    if compact:
        root = names.get(_normalize_label(compact.group("name")), "")
        return _occ_symbol(root, _expiry(compact.group("exp")), compact.group("right"), compact.group("strike"))
    return ""


def _looks_like_option(description: str) -> bool:
    """A CALL or PUT with an expiry date: a contract, whose symbol can only
    be its OCC code (parser_common.looks_like_option_contract's test, which
    an older installed parser_common may lack)."""
    shared = getattr(parser_common, "looks_like_option_contract", None)
    if shared is not None and shared({"description": description}):
        return True
    return bool(
        re.search(r"\b(?:CALL|PUT)S?\b", description, re.I)
        and re.search(r"\b\d{1,2}/\d{1,2}/\d{2}(?:\d{2})?\b", description)
    )


def _distinctive(words) -> set[str]:
    return {w for w in words if w not in _GENERIC_NAME_WORDS and len(w) > 1}


# Where the Comments column starts on an activity row's first line ("...
# INC ACTED AS AGENT", "UNSOLICITED TRADE"): the description before it is
# the security's name, cut short when the column is too narrow for it.
_COMMENTS_START_RE = re.compile(r"\s(?:ACTED AS\b|UNSOLICITED\b|SOLICITED TRADE\b)")
_FAKE_CONSONANTS = frozenset("bcdfghjklmnprstvwz")
_FAKE_VOWELS = frozenset("aeiou")


def _fake_shaped(word: str) -> bool:
    """Whether a word has the shape of the Statement Scrambler's fakes
    (scramble_statement.Scrambler.fake_word): a consonant, then vowel and
    consonant letters in turn. A real word that differs from a holding's
    ("CHINA" for "JAPAN") mostly does not."""
    lower = word.lower()
    return bool(lower) and all(
        letter in (_FAKE_VOWELS if position % 2 else _FAKE_CONSONANTS)
        for position, letter in enumerate(lower)
    )


def _same_name(text: list[str], name: list[str]) -> bool:
    """Whether an activity description names the holding called name, word
    by word from the start, allowing only what the same name can look like
    there: the name cut short ("ASSOCIAT" for "ASSOCIATES", or a last word
    of one or two letters after at least two distinctive words), or, in a
    scrambled sample, a word faked to another of the same length (a dated
    line keeps fewer real words than a holdings line, and every fake has
    _fake_shaped's shape). A word that differs otherwise - "MID-CAP" for
    "500", "CHINA" for "JAPAN", or any differing figure - is another
    security: a fund family's names share most of their words. The caller
    cuts the description at the Comments column (_COMMENTS_START_RE), so a
    name shorter than the holding's is not compared with "ACTED AS
    AGENT"; words after a whole name are never compared."""
    if not text or not name:
        return False
    matched = 0
    for position, (got, want) in enumerate(zip(text, name)):
        if got == want:
            matched += want not in _GENERIC_NAME_WORDS and len(want) > 1
            continue
        if want.startswith(got) and (len(got) >= 3 or (position == len(text) - 1 and matched >= 2)):
            return True  # the name, cut short here
        if len(got) == len(want) and got.isalpha() and want.isalpha() and _fake_shaped(got):
            continue  # a scrambled word
        return False
    return True


def _ticker_then_name(ticker: str, rest: str, names: dict[str, str]) -> bool:
    """Whether "TICKER rest" names the holding with that ticker: the rest is
    empty or that holding's name ("ACM ACME CORPORATION"), never another
    issuer's that merely starts with a held ticker ("GE VERNOVA INC" when
    GE AEROSPACE is held)."""
    if not rest:
        return True
    for name, symbol in names.items():
        if symbol != ticker:
            continue
        if rest == name or rest.startswith(name + " ") or (len(rest) >= 3 and name.startswith(rest)):
            return True
        if _same_name(rest.split(), name.split()):
            return True
    return False


def _symbol_for(description: str, names: dict[str, str], tickers: set[str]) -> str:
    """The ticker the holdings print for the security a row names."""
    text = re.sub(r"\s+", " ", description).strip().upper()
    for paren in reversed(_PAREN_RE.findall(text)):
        symbol = _ticker(paren)
        if symbol and symbol in tickers:
            return symbol
    comments = _COMMENTS_START_RE.search(text)
    if comments:
        text = text[:comments.start()]
    for name in sorted(names, key=len, reverse=True):
        if text == name or text.startswith(name + " "):
            return names[name]
    first, _, rest = text.partition(" ")
    if len(first) >= 2 and first in tickers and _ticker_then_name(first, rest, names):
        return first
    words = _distinctive(text.split())
    best, best_score, tie = "", 0, False
    for name, symbol in names.items():
        own = _distinctive(name.split())
        overlap = len(own & words)
        if overlap < 2 or overlap * 2 < len(own) or not _same_name(text.split(), name.split()):
            continue
        if overlap > best_score:
            best, best_score, tie = symbol, overlap, False
        elif overlap == best_score and symbol != best:
            tie = True
    return "" if tie else best


class _Activity:
    def __init__(self) -> None:
        self.present = False
        self.rows: list[dict] = []              # cash-flow rows
        self.meta: list[dict] = []              # per cash row: bucket, certain
        self.corporate: list[dict] = []         # transfers / corporate actions
        self.transfer_rows: list[int] = []      # indices into corporate
        self.unread: list[dict] = []
        self.corporate_unread: list[dict] = []
        self.net_credits: float | None = None
        self.corporate_label = ""
        self.security_transfers_total: float | None = None
        self.card_rows: list[dict] = []         # debit card, check and bill payment rows
        self.card_unread: list[dict] = []
        self.card_labels: list[str] = []        # those sections' headings, in order
        self.card_totals: list[float] = []      # their TOTAL lines


def _is_continuation(text: str) -> bool:
    if len(text) > 80 or _FOOTER_CODE_RE.match(text) or _COLUMN_HEADER_RE.match(text):
        return False
    if _MONEY_END_RE.search(text):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _cash_flow_row(ln: _Line, match: re.Match, start: date, end: date) -> dict | None:
    body = match.group("body")
    amount = _AMOUNT_TAIL_RE.search(" " + body) or _DASH_TAIL_RE.search(" " + body)
    if not amount:
        return None
    raw_amount = amount.group("amount")
    rest = (" " + body)[: amount.start()].strip()
    quantity = price = None
    qty_price = _QTY_PRICE_TAIL_RE.search(" " + rest)
    if qty_price:
        quantity = abs(_amount(qty_price.group("qty")))
        price = _amount(qty_price.group("price"))
        rest = (" " + rest)[: qty_price.start()].strip()
    found = _match_word(rest, _ACTIVITY_WORDS_SORTED)
    if not found:
        return None
    (label, ttype, bucket, certain), printed = found
    description = rest[len(printed):].strip()
    try:
        when = _resolve_date(match.group("d1"), start, end)
    except ValueError:
        return None
    missing = raw_amount in _ZERO_CELL  # a dash: the statement printed no cash value
    value = 0.0 if missing else _amount(raw_amount)
    if "/" in ttype:
        if missing:
            return None  # a two-way word with no amount has no direction to read
        positive, negative = (part[1:] for part in ttype.split("/"))
        ttype = positive if value >= 0 else negative
    if quantity is not None and ttype in _OUTGOING_TYPES:
        quantity = -quantity  # shares or contracts leaving the account
    row = {
        "date": when,
        "description": description or printed,
        "amount": value,
        "action": printed,
        "transaction_type": ttype,
        "quantity": quantity,
        "price": price,
        "_bucket": bucket,
        "_certain": certain,
        "_word": label,
        "_base": description,
    }
    if missing:
        row["amount_missing"] = True
    return row


_CARD_WORDS_SORTED = tuple(entry for entry in _ACTIVITY_WORDS_SORTED if entry[2] == "card")


def _card_date(raw: str, start: date, end: date) -> str:
    parts = raw.split("/")
    if len(parts) == 3:
        return date(_year(parts[2]), int(parts[0]), int(parts[1])).isoformat()
    return _resolve_date(raw, start, end)


def _card_row(text: str, section: str, start: date, end: date) -> dict | None:
    """A debit card, check or bill payment row, as a deposit or withdrawal
    by its printed sign."""
    match = _CARD_ROW_RE.match(text)
    if not match:
        return None
    try:
        when = _card_date(match.group("d1"), start, end)
    except ValueError:
        return None
    value = _amount(match.group("amount"))
    body = (match.group("body") or "").strip()
    found = _match_word(body, _CARD_WORDS_SORTED)
    if found:
        printed = found[1]
        rest = body[len(printed):].strip()
    else:
        printed = "Debit Card" if section.startswith("DEBIT") else "Bill Payment" if section.startswith("BILL") else "Check"
        rest = body
    number = match.group("number")
    if not number and re.fullmatch(r"#?\d{1,10}", rest):
        number = rest.lstrip("#")  # "Check 1001"
    if not rest or rest.lstrip("#") == number:
        description = f"{printed} {number}" if number else printed
    else:
        description = rest
    row = {
        "date": when,
        "description": description,
        "amount": value,
        "action": printed,
        "transaction_type": "deposit" if value > 0 else "withdrawal",
    }
    if number:
        row["reference"] = number
    return row


def _corporate_row(match: re.Match, start: date, end: date) -> dict | None:
    body = match.group("body")
    found = _match_word(body, _CORPORATE_WORDS_SORTED)
    if not found:
        return None
    (label, event), printed = found
    rest = body[len(printed):].strip()
    amount = None
    tail = _AMOUNT_TAIL_RE.search(" " + rest)
    if tail and not re.search(r"\.\d{3,}\)?$", tail.group("amount")):
        amount = _amount(tail.group("amount"))
        rest = (" " + rest)[: tail.start()].strip()
    quantity = None
    qty = _QTY_TAIL_RE.search(" " + rest)
    if not qty:
        # The security transfers table prints Quantity | Accrued Interest |
        # Amount: an accrued-interest cell (a figure or a dash), or a dash
        # amount, can sit after the quantity.
        trimmed = rest
        for _ in range(2):
            cell = _ACCRUED_TAIL_RE.search(" " + trimmed)
            if not cell:
                break
            trimmed = (" " + trimmed)[: cell.start()].strip()
            qty = _QTY_TAIL_RE.search(" " + trimmed)
            if qty:
                rest = trimmed
                break
    if qty:
        quantity = _amount(qty.group("qty"))
        rest = (" " + rest)[: qty.start()].strip()
    if quantity is None and amount is None:
        return None
    try:
        when = _resolve_date(match.group("d1"), start, end)
    except ValueError:
        return None
    return {
        "date": when,
        "description": rest or printed,
        "action": printed,
        "_event": event,
        "_amount": amount,
        "_quantity": quantity,
        "_base": rest,
    }


def _activity(lines: list[_Line], start: date, end: date) -> _Activity:
    result = _Activity()
    mode: str | None = None
    last: dict | None = None
    continued = 0
    card_section = ""
    messages = False
    for index, ln in enumerate(lines):
        text = ln.text
        if text.startswith("CASH FLOW ACTIVITY BY DATE"):
            if mode != "cash" and "CONTINUED" not in text.upper():
                last = None
            mode, result.present = "cash", True
            continue
        if text.startswith("MONEY MARKET FUND (MMF)") or "BANK DEPOSIT PROGRAM ACTIVITY" in text:
            mode, last = "sweep", None
            continue
        if text.startswith("TRANSFERS, CORPORATE ACTIONS"):
            if not result.corporate_label:
                result.corporate_label = re.sub(r"\s*\(CONTINUED\)$", "", text, flags=re.I)
            if mode != "corporate":
                last = None
            mode = "corporate"
            continue
        if text == "MESSAGES":
            messages = True  # the account's last section: headings in it are prose
        card = _CARD_SECTION_RE.match(text)
        if card and not messages:
            card_section = card.group("label")
            if card_section not in result.card_labels:
                result.card_labels.append(card_section)
            mode, last = "card", None
            continue
        if _SKIPPED_SECTION_RE.match(text):
            mode, last = None, None
            continue
        if mode == "card":
            if _COLUMN_HEADER_RE.match(text) or _FOOTER_CODE_RE.match(text):
                continue
            total = _CARD_TOTAL_RE.match(text)
            if total:
                if not total.group("sub"):
                    result.card_totals.append(_amount(total.group("value")))
                continue
            if _heading(text) and _SECTION_WORD_RE.search(text):
                mode = None  # a section this parser does not know
                continue
            row = _card_row(text, card_section, start, end)
            if row is not None:
                result.card_rows.append(row)
            elif _MONEY_END_RE.search(text) or _CARD_START_RE.match(text):
                result.card_unread.append({"page": ln.page, "line": ln.no, "text": text})
            continue
        if mode == "sweep":
            if text.startswith("NET ACTIVITY FOR PERIOD"):
                mode = None
            continue
        if mode == "cash":
            net = _NET_CREDITS_RE.match(text)
            if net:
                raw = net.group("value")
                result.net_credits = 0.0 if raw in _ZERO_CELL else _amount(raw)
                mode, last = None, None
                continue
            if _COLUMN_HEADER_RE.match(text) or _FOOTER_CODE_RE.match(text):
                continue
            dated = _DATED_RE.match(text)
            if dated:
                row = _cash_flow_row(ln, dated, start, end)
                if row is None:
                    result.unread.append({"page": ln.page, "line": ln.no, "text": text})
                    last = None
                else:
                    result.rows.append(row)
                    last, continued = row, 0
                continue
            if last is not None and continued < 3 and _is_continuation(text):
                last["description"] = f"{last['description']} {text}"
                continued += 1
                continue
            if _MONEY_END_RE.search(text) or _DATED_START_RE.match(text):
                result.unread.append({"page": ln.page, "line": ln.no, "text": text})
            continue
        if mode == "corporate":
            if _COLUMN_HEADER_RE.match(text) or _FOOTER_CODE_RE.match(text):
                continue
            total = _SECURITY_TRANSFERS_TOTAL_RE.match(text)
            if total:
                raw = total.group("value")
                result.security_transfers_total = 0.0 if raw in _ZERO_CELL else _amount(raw)
                last = None
                continue
            if text.startswith("TOTAL "):
                last = None
                continue
            dated = _DATED_RE.match(text)
            if dated:
                row = _corporate_row(dated, start, end)
                if row is None:
                    result.corporate_unread.append({"page": ln.page, "line": ln.no, "text": text})
                    last = None
                else:
                    result.corporate.append(row)
                    last, continued = row, 0
                continue
            following = lines[index + 1].text if index + 1 < len(lines) else ""
            if _heading(text) and not re.search(r"[a-z]", text):
                if _COLUMN_HEADER_RE.match(following):
                    last = None  # a sub-table: SECURITY TRANSFERS, OPTIONS ...
                    continue
                if _corporate_table_continues(lines, index + 1):
                    # A comment under the row above ("STOCK PLAN RELEASE";
                    # "TRANSFER TO" / account / "SPECIFIC TAX LOT" /
                    # "SELECTED"), or a sub-table's own heading: rows of
                    # the table follow, so it has not ended.
                    if last is not None and continued < _CORPORATE_COMMENT_LINES:
                        last["description"] = f"{last['description']} {text}"
                        continued += 1
                    continue
                # A heading followed by prose: the next section (MESSAGES).
                mode, last = "corporate_after", None
                continue
            if last is not None and continued < 3 and _is_continuation(text) and not re.search(r"[a-z]{3,}", text):
                last["description"] = f"{last['description']} {text}"
                continued += 1
                continue
            if _DATED_START_RE.match(text) or (_MONEY_END_RE.search(text) and not re.search(r"[a-z]{3,}", text)):
                result.corporate_unread.append({"page": ln.page, "line": ln.no, "text": text})
                continue
            if _is_prose(text):
                mode, last = "corporate_after", None  # prose: the table has ended
            continue
        if mode == "corporate_after":
            # The table was taken to have ended at a heading or prose that
            # no known section name confirms. A row of it found after that
            # is reported, never dropped, and its total is still read.
            total = _SECURITY_TRANSFERS_TOTAL_RE.match(text)
            if total and result.security_transfers_total is None:
                raw = total.group("value")
                result.security_transfers_total = 0.0 if raw in _ZERO_CELL else _amount(raw)
                continue
            dated = _DATED_RE.match(text)
            if dated and _corporate_row(dated, start, end) is not None:
                result.corporate_unread.append({"page": ln.page, "line": ln.no, "text": text})
            continue
    return result


_CORPORATE_COMMENT_LINES = 4


def _is_prose(text: str) -> bool:
    return bool(re.search(r"[a-z]{3,}", text)) and len(text) > 40


def _corporate_table_continues(lines: list[_Line], start: int) -> bool:
    """Whether the TRANSFERS, CORPORATE ACTIONS table goes on after an
    upper-case line: the next line that decides it is a row, a total, a
    column header or a known section (the line was a comment or a
    sub-table heading), not words in lower case (it was the heading of
    what follows, e.g. MESSAGES). Further upper-case lines, figures-only
    lines and footer codes do not decide it."""
    for ln in lines[start:start + 8]:
        text = ln.text
        if (
            _DATED_START_RE.match(text)
            or text.startswith("TOTAL ")
            or _COLUMN_HEADER_RE.match(text)
            or _SKIPPED_SECTION_RE.match(text)
            or text.startswith(("CASH FLOW ACTIVITY BY DATE", "TRANSFERS, CORPORATE ACTIONS", "MONEY MARKET FUND (MMF)"))
        ):
            return True
        if re.search(r"[a-z]{3,}", text):
            return False
    return len(lines) - start < 8  # the account's lines ended undecided


# "TO 123-456790-012" / "FROM 123-456789-012": the account on the other side
# of a transfer, on the row's first line or a comment line under it.
_OTHER_ACCOUNT_RE = re.compile(r"\b(?:TO|FROM)\s+(?:ACCOUNT\s+|ACCT\.?\s+)?#?\s*(?P<account>\d[\dXx*-]{4,}[\dXx*\d])(?=\s|$)")


def _package_transfer(description: str, own: str, package: frozenset[str]) -> bool:
    """Whether a row's description names another account of the same
    statement package as the other side of the transfer."""
    return any(
        found.group("account") in package and found.group("account") != own
        for found in _OTHER_ACCOUNT_RE.finditer(description)
    )


def _finish_transactions(activity: _Activity, holdings: list[dict],
                         account: _Account,
                         package: frozenset[str] = frozenset()) -> tuple[list[dict], list[dict], list[dict]]:
    """Output rows: (cash-flow rows, card/check rows, then transfers and
    corporate actions). package holds every account id the statement
    covers: money moved between two of them is an internal transfer on
    both legs, never a deposit and a withdrawal."""
    names = {
        _normalize_label(row["description"]): row["symbol"]
        for row in holdings
        if row.get("type") not in ("Cash", "Options") and row.get("symbol") not in ("", "CASH")
        and row.get("security_id_type") != "CUSIP"
    }
    cusips = {
        _normalize_label(row["description"]): row["security_id"]
        for row in holdings
        if row.get("security_id_type") == "CUSIP"
    }
    tickers = set(names.values())
    common_fields = {
        "account": account.account,
        "accountType": account.account_type,
        "provider_account_id": account.provider_id,
    }
    side: dict[str, str] = {}  # OCC symbol -> "long" or "short"

    def security(row: dict, out: dict, printed_symbol: bool = False) -> None:
        cusip = _CUSIP_RE.search(row["description"])
        if cusip:
            # A bond names itself by CUSIP; it has no ticker to look up.
            out["security_id"] = cusip.group("cusip")
            out["security_id_type"] = "CUSIP"
            return
        base = row.get("_base") or ""
        symbol = _option_symbol_from_text(base, names)
        if not symbol and _looks_like_option(base):
            # A contract whose OCC code cannot be built (an adjusted root,
            # an unmatched underlying name) gets no symbol, never the
            # underlying stock's ticker.
            return
        if not symbol and printed_symbol:
            # The transfers table's "Security (Symbol)" column.
            for paren in reversed(_PAREN_RE.findall(base)):
                symbol = _ticker(paren) or ""
                if symbol:
                    break
        if not symbol:
            symbol = _symbol_for(base, names, tickers)
        if symbol:
            out["symbol"] = symbol
            return
        # A bond the holdings name by CUSIP only: the CUSIP is its identifier,
        # never its symbol (CONTRACT.md, "Symbols").
        cusip_by_name = _symbol_for(base, cusips, set())
        if cusip_by_name:
            out["security_id"] = cusip_by_name
            out["security_id_type"] = "CUSIP"

    cash_out: list[dict] = []
    for row in activity.rows:
        out = {
            "date": row["date"],
            "description": re.sub(r"\s+", " ", row["description"]).strip(),
            "amount": row["amount"],
            "action": row["action"],
            "transaction_type": row["transaction_type"],
        }
        if row["transaction_type"] in {"buy", "sell", "redemption", "dividend", "capital_gain", "tax", "other",
                                        "income", "interest"}:
            if row["transaction_type"] == "interest":
                # Interest is from the bank deposit program or a bond: only
                # a bond's CUSIP names a security.
                cusip = _CUSIP_RE.search(row["description"])
                if cusip:
                    out["security_id"] = cusip.group("cusip")
                    out["security_id_type"] = "CUSIP"
            else:
                security(row, out)
        if row["quantity"] is not None:
            out["quantity"] = row["quantity"]
        if row["price"] is not None:
            out["price"] = row["price"]
        if row.get("amount_missing"):
            out["amount_missing"] = True
        if (
            out["transaction_type"] in {"deposit", "withdrawal"}
            and row["_bucket"] == "cash"
            and _package_transfer(out["description"], account.provider_id, package)
        ):
            out["transaction_type"] = "internal_transfer"
        out.update(common_fields)
        cash_out.append(out)
        symbol = out.get("symbol", "")
        if parser_common.OCC_SYMBOL.match(symbol) and row["transaction_type"] in {"buy", "sell"}:
            # Which side of the contract the account held: a buy to open or
            # a sell to close means it was long, a sell to open or a buy to
            # close that it was written.
            if re.search(r"\bOPENING\b", out["description"]):
                side[symbol] = "long" if row["transaction_type"] == "buy" else "short"
            elif re.search(r"\bCLOSING\b", out["description"]):
                side.setdefault(symbol, "long" if row["transaction_type"] == "sell" else "short")

    card_out = [{**row, **common_fields} for row in activity.card_rows]

    corporate_out: list[dict] = []
    for index, row in enumerate(activity.corporate):
        event = row["_event"]
        quantity = row["_quantity"]
        out = {
            "date": row["date"],
            "description": re.sub(r"\s+", " ", row["description"]).strip(),
            "action": row["action"],
        }
        security(row, out, printed_symbol=True)
        if event in {"transfer_in", "transfer_out"}:
            amount = row["_amount"]
            out["transaction_type"] = event
            out["subtype"] = "In" if event == "transfer_in" else "Out"
            if amount is None:
                out["amount"] = 0.0
                out["amount_missing"] = True
            else:
                out["amount"] = abs(amount) if event == "transfer_in" else -abs(amount)
            if quantity is not None:
                out["quantity"] = abs(quantity) if event == "transfer_in" else -abs(quantity)
            activity.transfer_rows.append(len(corporate_out))
        else:
            out["transaction_type"] = "corporate_action"
            out["amount"] = 0.0
            symbol = out.get("symbol", "")
            if event in {"expired", "assigned", "exercised"}:
                out["subtype"] = "Out"
                if quantity is not None and quantity > 0:
                    # The position change. Contracts print unsigned: an
                    # assignment closes a written contract (+), an exercise a
                    # held one (-). An expiry closes whichever side this
                    # statement's trades in the contract show (a buy to open
                    # or a sell to close: held, -). With none it stays as
                    # printed (+), the written side: a call sold to open
                    # late in a month expires in the next statement, which
                    # has no trade in it.
                    if event == "exercised" or side.get(symbol) == "long":
                        quantity = -quantity
            elif event == "in":
                out["subtype"] = "In"
                quantity = abs(quantity) if quantity is not None else None
            elif event == "out":
                out["subtype"] = "Out"
                quantity = -abs(quantity) if quantity is not None else None
            else:
                out["subtype"] = "Out" if quantity is not None and quantity < 0 else "In"
            if quantity is not None:
                out["quantity"] = quantity
            out["corporate_event"] = _corporate_event(row["action"], event, out["subtype"])
        out.update(common_fields)
        corporate_out.append(out)
    return cash_out, card_out, corporate_out


# --- checks -------------------------------------------------------------------

# Charges the CHANGE IN VALUE summary counts in Debits, beside money moved
# in and out: account service fees (the statement guide: "Other Debits")
# and advisory fees ("Net Credits / Debits include investment advisory
# fees"). Any other fee or tax word (margin interest, commission, ADR fee,
# tax withheld) may be counted there or not, so with one present the check
# is not made: a guess either way would hold a clean import, and could
# offer to leave a correct row out.
_CREDITS_DEBITS_CHARGES = frozenset({
    "Service Fee", "Account Fee", "Annual Fee", "Annual Account Fee", "Maintenance Fee",
    "Advisory Fee", "Management Fee", "Wire Fee", "Transfer Fee",
})
_CREDITS_DEBITS_UNKNOWN_TYPES = frozenset({"fee", "tax"})
_INVESTMENT_TAXES = frozenset({
    "Foreign Tax Withheld", "Foreign Tax Paid", "Foreign Tax", "Foreign Withholding", "Foreign Tax Refund",
})


def _credits_debits_rows(cash_rows: list[dict], meta: list[dict]) -> list[int] | None:
    """The cash-flow rows the summary's Credits + Debits count: money moved
    in or out, and account charges. None when a row's word may or may not
    be counted there (a commission, an ADR fee, a tax withheld)."""
    rows: list[int] = []
    for index, (row, info) in enumerate(zip(cash_rows, meta)):
        ttype = row.get("transaction_type")
        if ttype in parser_common.FLOW_TRANSACTION_TYPES or info["_word"] in _CREDITS_DEBITS_CHARGES:
            rows.append(index)
        elif ttype in _CREDITS_DEBITS_UNKNOWN_TYPES and info["_word"] not in _INVESTMENT_TAXES:
            return None
    return rows


def _outside_gap(activity: _Activity, cash_flow: dict[str, float]) -> float | None:
    """Cash that moved outside CASH FLOW ACTIVITY BY DATE: CLOSING CASH less
    OPENING CASH (and a prior month's unsettled trades) less NET
    CREDITS/(DEBITS). None when one of them is not printed."""
    if activity.net_credits is None or "opening" not in cash_flow or "closing" not in cash_flow:
        return None
    return round(cash_flow["closing"] - cash_flow["opening"] - cash_flow.get("unsettled", 0.0)
                 - activity.net_credits, 2)


def _checks(activity: _Activity, cash_flow: dict[str, float], summary: dict[str, float],
            cash_rows: list[dict], card_count: int, gap: float | None, suffix: str) -> list[dict]:
    """The statement's arithmetic over the rows (CONTRACT.md, "Checks").
    Rows are numbered cash-flow rows, then card/check rows (card_count of
    them), then transfers and corporate actions.

    An answer that adds a line the parser did not read adds it to one check
    only (statement_checks apply_adjustments), so a not-read line must be
    claimed by one total only, or the other would stay failing after the
    user answered. In order:

      Credits/Debits             money moved in and out (and account
                                 charges) = the summary's Credits + Debits;
                                 a money movement read under another word
                                 would otherwise count as investment gain.
                                 Made only when every dated line of the
                                 sections it covers was read: its rows are
                                 also in the totals below.
      CASH FLOW ACTIVITY BY DATE every cash-flow row = NET CREDITS/(DEBITS),
                                 or, when that is not printed, opening cash
                                 plus the rows (card/check rows too) =
                                 closing cash
      (unread, same label)       dated lines there that were not read
      <card/check sections>      debit card, check and bill payment rows =
                                 the cash that moved outside the table above
                                 (_outside_gap), when the statement shows
                                 card or check activity (gap is None
                                 otherwise) and that is not zero; with no
                                 such section, a total over no rows, so
                                 spending never imports as investment loss
      (unread, same label)       dated lines there that were not read
      <transfers section>        security transfers = TOTAL SECURITY
                                 TRANSFERS, or the summary's figure
      (unread, same label)       dated lines there that were not read

    An unread line's suggested row takes its sign from the first total
    with the same label, so each unread check shares its section's label.
    The CASH FLOW summary's category lines are not checks: sums over
    subsets of the same rows could only offer to leave a correct row out.
    """
    checks: list[dict] = []
    table = "brokerage_transactions"
    indices = list(range(len(cash_rows)))
    card_indices = list(range(len(cash_rows), len(cash_rows) + card_count))
    corporate_offset = len(cash_rows) + card_count
    label = f"CASH FLOW ACTIVITY BY DATE{suffix}"
    card_label = f"{' / '.join(activity.card_labels) or 'Total Card/Check Activity'}{suffix}"
    flows = _credits_debits_rows(cash_rows, activity.meta)
    moved = round(summary["credits"] + summary["debits"], 2)
    all_read = not activity.unread and not activity.card_unread
    if flows is not None and all_read and (activity.present or card_indices or abs(moved) > 0.005):
        checks.append({"kind": "sum", "label": f"Credits/Debits{suffix}", "table": table,
                       "rows": flows + card_indices, "expected": moved})
    card_unread_label = card_label
    if activity.present and activity.net_credits is not None:
        checks.append({"kind": "sum", "label": label, "table": table, "rows": indices,
                       "expected": round(activity.net_credits, 2)})
    elif "opening" in cash_flow and "closing" in cash_flow:
        checks.append({
            "kind": "balance",
            "label": label,
            "table": table,
            "rows": indices + card_indices,
            "opening": round(cash_flow["opening"] + cash_flow.get("unsettled", 0.0), 2),
            "closing": round(cash_flow["closing"], 2),
        })
        card_unread_label = label
    if activity.present:
        lines = list(activity.unread)
        if card_unread_label == label:
            lines += activity.card_unread  # counted in the same total
        checks.append({"kind": "unread", "label": label, "lines": lines})
    if gap is not None and abs(gap) > 0.005:
        checks.append({"kind": "sum", "label": card_label, "table": table, "rows": card_indices,
                       "expected": gap})
    elif gap is None and card_indices and card_unread_label == card_label and activity.card_totals \
            and len(activity.card_totals) >= len(activity.card_labels):
        # No CASH FLOW summary to go by: the sections' own TOTAL lines.
        checks.append({"kind": "sum", "label": card_label, "table": table, "rows": card_indices,
                       "expected": round(sum(activity.card_totals), 2)})
    if activity.card_labels and (gap is None or abs(gap) > 0.005) and not (
            activity.present and card_unread_label == label):
        checks.append({"kind": "unread", "label": card_unread_label, "lines": list(activity.card_unread)})
    corporate_label = f"{activity.corporate_label}{suffix}" if activity.corporate_label else ""
    transfers = [corporate_offset + i for i in activity.transfer_rows]
    printed_transfers = activity.security_transfers_total
    if printed_transfers is None and (transfers or abs(summary.get("security_transfers", 0.0)) > 0.005):
        printed_transfers = summary.get("security_transfers", 0.0)
    if printed_transfers is not None and (transfers or abs(printed_transfers) > 0.005):
        checks.append({"kind": "sum", "label": corporate_label or f"Security Transfers{suffix}",
                       "table": table, "rows": transfers, "expected": round(printed_transfers, 2)})
    if corporate_label:
        checks.append({"kind": "unread", "label": corporate_label, "lines": list(activity.corporate_unread)})
    return checks


def _offset_checks(checks: list[dict], offset: int) -> list[dict]:
    for check in checks:
        if "rows" in check:
            check["rows"] = [row + offset for row in check["rows"]]
    return checks


# --- the Client Statement ---------------------------------------------------

def _parse_at_work(pages_text: list[str]) -> dict:
    text = "\n".join(pages_text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    context = diagnostic_helpers.diagnostic_context(
        pages_text,
        section_markers=("CLIENT STATEMENT", "Account Summary", "CASH FLOW", "HOLDINGS"),
        known_labels=tuple(label for label, _ in _AT_WORK_SUMMARY_LABELS.values())
        + ("MORGAN STANLEY BANK N.A.", "MORGAN STANLEY PRIVATE BANK NA", "TOTAL VALUE"),
        extra_counts={
            "summaryComponents": sum(
                1
                for label, _ in _AT_WORK_SUMMARY_LABELS.values()
                if any(_first_period_cell(line, label) is not None for line in lines)
            ),
        },
    )
    counts = context["counts"]
    counts["holdingsParsed"] = 0
    counts["transactionsParsed"] = 0
    holdings_out: list[dict] = []
    transactions_out: list[dict] = []
    checks_out: list[dict] = []
    try:
        start, end = _period(text)
        accounts = _accounts(pages_text)
        multiple = len(accounts) > 1
        package = frozenset(account.provider_id for account in accounts if account.provider_id)
        for account in accounts:
            summary = _summary([line.text for line in account.lines])
            cash_flow = _cash_flow_summary(account.lines)
            holdings, holdings_total, reader = _holdings(account.lines, account, end.isoformat(), summary["ending"])
            counts["holdingsParsed"] += len(holdings)
            core._require_close(
                "E*TRADE at Work ending holdings",
                holdings_total,
                summary["ending"],
                "holdings",
            )
            activity = _activity(account.lines, start, end)
            activity.meta = [{"_bucket": row["_bucket"], "_certain": row["_certain"], "_word": row["_word"]}
                             for row in activity.rows]
            # Card, check and bill payment activity, when the statement shows
            # any: its sections, or the CASH FLOW summary's Total Card/Check
            # Activity.
            gap = None
            if activity.card_labels or abs(cash_flow.get("card_total", 0.0)) > 0.005:
                gap = _outside_gap(activity, cash_flow)
                if gap is not None and abs(gap) <= 0.005:
                    # CASH FLOW ACTIVITY BY DATE lists all the cash that
                    # moved: a card or check section only repeats its rows.
                    activity.card_rows, activity.card_unread = [], []
            counts["unreadActivityLines"] = counts.get("unreadActivityLines", 0) + len(activity.unread) + len(
                activity.corporate_unread
            ) + len(activity.card_unread)
            cash_rows, card_rows, corporate_rows = _finish_transactions(activity, holdings, account, package)
            counts["transactionsParsed"] += len(cash_rows) + len(card_rows) + len(corporate_rows)

            moved = (
                abs(summary["credits"]) > 0.005
                or abs(summary["debits"]) > 0.005
                or ("opening" in cash_flow and "closing" in cash_flow
                    and abs(cash_flow["opening"] + cash_flow.get("unsettled", 0.0) - cash_flow["closing"]) > 0.005)
                or (activity.net_credits is not None and abs(activity.net_credits) > 0.005)
            )
            if moved and not cash_rows and not card_rows and not activity.unread and not activity.card_unread:
                raise parser_common.ParserDiagnosticError(
                    "E*TRADE at Work cash activity rows not found",
                    code="PARSER_ACTIVITY_ROWS_NOT_FOUND",
                    stage="activity",
                )

            suffix = f" ({account.provider_id or account.account})" if multiple else ""
            offset = len(transactions_out)
            checks = _checks(activity, cash_flow, summary, cash_rows, len(card_rows), gap, suffix)
            checks_out.extend(_offset_checks(checks, offset))
            holdings_out.extend(holdings)
            transactions_out.extend(cash_rows)
            transactions_out.extend(card_rows)
            transactions_out.extend(corporate_rows)
    except ValueError as error:
        raise parser_common.enrich_parser_error(error, **context) from error

    parser_common.set_directions(transactions_out)
    return {
        "institution": INSTITUTION,
        "statementDate": end.isoformat(),
        "tables": {
            "brokerage_holdings": holdings_out,
            "brokerage_transactions": transactions_out,
        },
        "checks": checks_out,
    }


def parse(pages_text: list[str], pdf_path: str) -> dict:
    text = "\n".join(pages_text)
    if _looks_like_at_work(text):
        return _parse_at_work(pages_text)
    return core.parse_profile(pages_text, pdf_path, PROFILE_KEY)
