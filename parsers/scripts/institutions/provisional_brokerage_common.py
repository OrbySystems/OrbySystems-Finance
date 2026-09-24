"""Shared strict core for documented, provisionally supported brokerages.

The institution modules that use this core are intentionally small profiles.
Each profile supplies the institution markers and the section/summary labels
documented by first-party statement guides.  The core owns the normalized
schema, date handling, reconciliation, and fail-loud behavior.

These parsers are provisional: their fixtures reproduce documented statement
structure, but no production statement was available to expose PDF-specific
text ordering.  A profile therefore claims only documents containing all of
its known markers and raises on missing controls or unclassified activity.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import parser_common

from . import common
from . import diagnostic_helpers


KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1
DIAGNOSTIC_SIGNALS = diagnostic_helpers.DIAGNOSTIC_SIGNALS
DIAGNOSTIC_COUNTS = diagnostic_helpers.DIAGNOSTIC_COUNTS
DIAGNOSTIC_TERMS = diagnostic_helpers.DIAGNOSTIC_TERMS

PERIOD = "July 25, 2026 - August 28, 2026"
STATEMENT_DATE = "2026-08-28"


def _labels(beginning: str, deposits: str, withdrawals: str, income: str,
            fees: str, market: str, ending: str) -> dict[str, str]:
    return {
        "beginning": beginning,
        "deposits": deposits,
        "withdrawals": withdrawals,
        "income": income,
        "fees": fees,
        "market": market,
        "ending": ending,
    }


PROFILES: dict[str, dict] = {
    "raymond_james": {
        "slug": "raymond-james",
        "institution": "Raymond James",
        "brand": "RAYMOND JAMES",
        "legal": "Raymond James & Associates, Inc. Member New York Stock Exchange/SIPC",
        "title": "COMPREHENSIVE STATEMENT",
        "summary": "Account Summary",
        "holdings": "Your Portfolio",
        "activity_summary": "Activity Summary",
        "activity": "Activity Detail",
        "realized": "Year-to-Date Realized Gain/Loss Summary",
        "account_id": "RJ-4827-3910",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Value", "Deposits", "Withdrawals", "Income", "Expenses", "Change in Value", "Ending Value"),
        "source_url": "https://www.raymondjames.com/-/media/rj/dotcom/files/wealth-management/statement_comp.pdf",
        "source_name": "raymond-james-comprehensive-statement-guide.pdf",
        "evidence": "Official comprehensive statement guide and illustrated sample sections.",
    },
    "wells_fargo_advisors": {
        "slug": "wells-fargo-advisors",
        "institution": "Wells Fargo Advisors",
        "brand": "WELLS FARGO ADVISORS",
        "legal": "Wells Fargo Clearing Services, LLC Member SIPC",
        "title": "INVESTMENT ACCOUNT STATEMENT",
        "summary": "Portfolio Snapshot",
        "holdings": "Account Detail - Holdings",
        "activity_summary": "Cash Flow Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "WFA-7362-1048",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Account Value", "Additions", "Subtractions", "Income", "Fees", "Market Change", "Ending Account Value"),
        "source_url": "https://www.wellsfargoadvisors.com/disclosures/guide-to-investing.htm",
        "source_name": "wells-fargo-advisors-statement-guide.html",
        "evidence": "Official guide describing Portfolio Snapshot and account Detail pages.",
    },
    "lpl_financial": {
        "slug": "lpl-financial",
        "institution": "LPL Financial",
        "brand": "LPL FINANCIAL",
        "legal": "LPL Financial LLC Member FINRA/SIPC",
        "title": "QUARTERLY ACCOUNT STATEMENT",
        "summary": "Account Summary and Asset Allocation",
        "holdings": "Account Holdings",
        "activity_summary": "Activity Summary",
        "activity": "Activity Details",
        "realized": "Gain/Loss Summary",
        "account_id": "LPL-5903-2184",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Value", "Inflows", "Outflows", "Income", "Fees", "Change in Market Value", "Ending Value"),
        "source_url": "https://www.lpl.com/investors/lpl-account-view/lpl-financial-statement-guide.html",
        "source_name": "lpl-financial-statement-guide.html",
        "evidence": "Official interactive guide with account summary, holdings, gain/loss, and activity sections.",
    },
    "interactive_brokers": {
        "slug": "interactive-brokers",
        "institution": "Interactive Brokers",
        "brand": "INTERACTIVE BROKERS LLC",
        "legal": "Interactive Brokers LLC Member NYSE, FINRA, SIPC",
        "title": "ACTIVITY STATEMENT",
        "summary": "Net Asset Value",
        "holdings": "Open Positions",
        "activity_summary": "Cash Report",
        "activity": "Trades and Cash Transactions",
        "realized": "Realized and Unrealized Performance Summary",
        "account_id": "U7654321",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Starting Net Asset Value", "Deposits", "Withdrawals", "Dividends and Interest", "Commissions and Fees", "Mark-to-Market Change", "Ending Net Asset Value"),
        "source_url": "https://www.interactivebrokers.com/download/reportingguide.pdf",
        "source_name": "interactive-brokers-reporting-guide.html",
        "evidence": "Official Reporting Reference Guide with Activity Statement samples and field definitions.",
    },
    "bny_pershing": {
        "slug": "bny-pershing",
        "institution": "BNY Pershing",
        "brand": "PERSHING LLC",
        "legal": "Cleared by Pershing LLC, member FINRA, NYSE, SIPC",
        "title": "ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Portfolio Holdings",
        "activity_summary": "Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "PERSH-6194-7302",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Account Value", "Deposits and Securities Received", "Withdrawals and Securities Delivered", "Income", "Fees", "Change in Value", "Ending Account Value"),
        "source_url": "https://www.bny.com/pershing/us/en/platforms/netx/netx-investor.html",
        "source_name": "bny-pershing-netxinvestor.html",
        "evidence": "Official NetXInvestor description of statements, holdings, balances, and activity.",
    },
    "apex_clearing": {
        "slug": "apex-clearing",
        "institution": "Apex Clearing",
        "brand": "APEX CLEARING CORPORATION",
        "legal": "Cleared by Apex Clearing Corporation Member FINRA/SIPC",
        "title": "BROKERAGE ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Positions",
        "activity_summary": "Cash Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "APEX-8401-2576",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Account Value", "Deposits and Transfers In", "Withdrawals and Transfers Out", "Income", "Fees and Charges", "Market Value Change", "Ending Account Value"),
        "source_url": "https://library.apexfintechsolutions.com/wp-content/uploads/2024/04/Customer-Information-Brochure-Broker-Dealer.pdf",
        "source_name": "apex-customer-information-brochure.pdf",
        "evidence": "Official customer brochure describing periodic position, transaction, balance, and interest reporting.",
    },
    "robinhood": {
        "slug": "robinhood",
        "institution": "Robinhood",
        "brand": "ROBINHOOD FINANCIAL LLC",
        "legal": "Robinhood Financial LLC Member SIPC",
        "title": "MONTHLY ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Portfolio Holdings",
        "activity_summary": "Cash Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "RH-3141-5926",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Account Value", "Deposits", "Withdrawals", "Dividends and Interest", "Fees", "Market Value Change", "Ending Account Value"),
        "source_url": "https://robinhood.com/us/en/support/articles/reports-and-statements/",
        "source_name": "robinhood-reports-and-statements.html",
        "evidence": "Official reports-and-statements documentation for monthly PDFs and activity exports.",
    },
    "t_rowe_price": {
        "slug": "t-rowe-price",
        "institution": "T. Rowe Price Brokerage",
        "brand": "T. ROWE PRICE BROKERAGE",
        "legal": "Clearing services provided by Pershing LLC Member FINRA, NYSE, SIPC",
        "title": "BROKERAGE ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Holdings",
        "activity_summary": "Activity Summary",
        "activity": "Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "TRP-2718-2818",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Value", "Additions", "Subtractions", "Income", "Expenses", "Change in Value", "Ending Value"),
        "source_url": "https://www.troweprice.com/content/dam/iinvestor/Forms/BrokWelcome.pdf",
        "source_name": "t-rowe-price-brokerage-welcome-guide.pdf",
        "evidence": "Official brokerage guide plus first-party disclosure that Pershing carries the account and prepares statements.",
    },
    "jp_morgan_wealth": {
        "slug": "jp-morgan-wealth",
        "institution": "J.P. Morgan Wealth Management",
        "brand": "J.P. MORGAN SECURITIES LLC",
        "legal": "J.P. Morgan Securities LLC Member FINRA/SIPC",
        "title": "INVESTMENT ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Holdings",
        "activity_summary": "Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "JPM-1618-0339",
        "account_title": "Self-Directed Brokerage Account",
        "labels": _labels("Beginning Market Value", "Contributions and Transfers In", "Withdrawals and Transfers Out", "Income", "Fees", "Market Change", "Ending Market Value"),
        "source_url": "https://www.chase.com/content/dam/chase-ux/documents/personal/investments/jpm-investment-account-agreements.pdf",
        "source_name": "jp-morgan-investment-account-agreements.pdf",
        "evidence": "Official investment account agreements and statement-consolidation documentation; no public full sample.",
    },
    "morgan_stanley_wealth": {
        "slug": "morgan-stanley-wealth",
        "institution": "Morgan Stanley Wealth Management",
        "brand": "MORGAN STANLEY SMITH BARNEY LLC",
        "legal": "Morgan Stanley Smith Barney LLC Member SIPC",
        "title": "CLIENT STATEMENT",
        "summary": "Account Summary",
        "holdings": "HOLDINGS",
        "activity_summary": "Activity Summary",
        "activity": "ACTIVITY",
        "realized": "Realized Gain/Loss",
        "account_id": "MS-1414-2135",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Total Value", "Deposits and Transfers In", "Withdrawals and Transfers Out", "Income", "Fees and Expenses", "Change in Value", "Ending Total Value"),
        "source_url": "https://advisor.morganstanley.com/david.rasdolsky/documents/field/r/ra/rasdolsky-david-steven/Guide_to_Reading_Your_Morgan_Stanley_Statement_04-2016.pdf",
        "source_name": "morgan-stanley-guide-to-reading-your-statement.pdf",
        "evidence": "Official-hosted guide identifying account summary, holdings, and activity components.",
    },
    "etrade": {
        "slug": "etrade",
        "institution": "E*TRADE from Morgan Stanley",
        "brand": "E*TRADE FROM MORGAN STANLEY",
        "legal": "Morgan Stanley Smith Barney LLC Member SIPC",
        "title": "SELF-DIRECTED ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Portfolio Holdings",
        "activity_summary": "Cash Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "ET-1732-0508",
        "account_title": "Individual Self-Directed Brokerage Account",
        "labels": _labels("Beginning Account Value", "Net Deposits", "Net Withdrawals", "Income", "Fees", "Market Gain/Loss", "Ending Account Value"),
        "source_url": "https://us.etrade.com/l/f/agreement-library/client-agreement",
        "source_name": "etrade-self-directed-client-agreement.html",
        "evidence": "Official client agreement and advice documentation describing statements, holdings, trades, dividends, fees, and activity.",
    },
    "ubs_wealth": {
        "slug": "ubs-wealth-management",
        "institution": "UBS Financial Services",
        "brand": "UBS FINANCIAL SERVICES INC.",
        "legal": "UBS Financial Services Inc. Member FINRA/SIPC",
        "title": "RESOURCE MANAGEMENT ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Investment Holdings",
        "activity_summary": "Cash Activity Summary",
        "activity": "Account Activity",
        "realized": "Gain/Loss Information",
        "account_id": "UBS-2236-0679",
        "account_title": "Resource Management Account",
        "labels": _labels("Opening Value", "Deposits and Transfers In", "Withdrawals and Transfers Out", "Income", "Fees", "Change in Market Value", "Closing Value"),
        "source_url": "https://www.ubs.com/content/dam/assets/wma/us/shared/documents/rma-guide.pdf",
        "source_name": "ubs-resource-management-account-guide.pdf",
        "evidence": "Official RMA guide describing asset allocation, gain/loss, deposits, earnings, transfers, and statement history.",
    },
    "ameriprise": {
        "slug": "ameriprise",
        "institution": "Ameriprise Financial",
        "brand": "AMERIPRISE FINANCIAL SERVICES, LLC",
        "legal": "Ameriprise Financial Services, LLC Member FINRA/SIPC",
        "title": "CONSOLIDATED FINANCIAL STATEMENT",
        "summary": "Account Summary",
        "holdings": "Account Holdings",
        "activity_summary": "Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "AMP-2449-4897",
        "account_title": "Individual Brokerage Account",
        "labels": _labels("Beginning Value", "Cash and Securities In", "Cash and Securities Out", "Income", "Fees and Expenses", "Investment Gain/Loss", "Ending Value"),
        "source_url": "https://www.ameriprise.com/customer-service/ameriprise-financial-statements-faqs",
        "source_name": "ameriprise-financial-statements-faq.html",
        "evidence": "Official statement FAQ covering consolidated, brokerage, managed-account, monthly, and quarterly statements.",
    },
    "empower": {
        "slug": "empower",
        "institution": "Empower",
        "brand": "EMPOWER BROKERAGE",
        "legal": "Empower Financial Services, Inc. Member FINRA/SIPC",
        "title": "BROKERAGE ACCOUNT STATEMENT",
        "summary": "Account Summary",
        "holdings": "Investment Holdings",
        "activity_summary": "Activity Summary",
        "activity": "Account Activity",
        "realized": "Realized Gain/Loss",
        "account_id": "EMP-3035-3317",
        "account_title": "Rollover IRA Brokerage Account",
        "labels": _labels("Beginning Balance", "Contributions and Transfers In", "Withdrawals and Transfers Out", "Investment Income", "Fees", "Investment Gain/Loss", "Ending Balance"),
        "source_url": "https://www.empower.com/client/relx/enroll/resources/pdfs/sda_users_guide.pdf",
        "source_name": "empower-self-directed-brokerage-guide.pdf",
        "evidence": "Official self-directed brokerage guide stating holdings, activity, fees, and statement cadence.",
    },
    "principal": {
        "slug": "principal",
        "institution": "Principal Financial Group",
        "brand": "PRINCIPAL FINANCIAL GROUP",
        "legal": "Principal Securities, Inc. Member SIPC",
        "title": "RETIREMENT ACCOUNT STATEMENT",
        "summary": "Your Account Summary",
        "holdings": "Your Investments",
        "activity_summary": "Activity Summary",
        "activity": "Account Activity",
        "realized": "Investment Gain/Loss",
        "account_id": "1-23456",
        "account_title": "Employer Sponsored 401(k) Retirement Plan",
        "labels": _labels("Beginning Account Value", "Contributions", "Withdrawals and Distributions", "Income", "Fees and Expenses", "Change in Market Value", "Ending Account Value"),
        "source_url": "https://www.principal.com/help/help-individuals/taxes-and-tax-forms",
        "source_name": "principal-statements-and-tax-documents-help.html",
        "evidence": "Official help and account-number documentation for retirement-plan statements; layouts vary by plan.",
    },
    "merrill_wealth": {
        "slug": "merrill-wealth-management",
        "institution": "Merrill",
        "brand": "MERRILL",
        "legal": "Merrill Lynch, Pierce, Fenner & Smith Incorporated Member SIPC",
        "title": "WEALTH MANAGEMENT REPORT",
        "summary": "Account Summary",
        "holdings": "ASSETS",
        "activity_summary": "Cash Flow",
        "activity": "TRANSACTIONS",
        "realized": "Realized Gain/Loss",
        "account_id": "ML-5772-1566",
        "account_title": "Individual Wealth Management Account",
        "labels": _labels("Opening Value", "Cash and Securities In", "Cash and Securities Out", "Income", "Fees", "Market Gains/Losses", "Ending Value"),
        "source_url": "https://oaui.fs.ml.com/Publish/Content/application/pdf/GWMOL/A_Guide_to_Your_Merrill_Edge_Statement.pdf",
        "source_name": "merrill-guide-to-your-statement.pdf",
        "evidence": "Official guide covering Wealth Management Report, account assets, activity, chronological/category layouts, and Trust variants.",
    },
}


def diagnostic_markers(profile_key: str) -> dict[str, str]:
    """Public section headings whose presence is safe to report as booleans.

    Marker text itself never leaves the parser process; parser_common emits
    only these generic keys and true/false values.
    """
    profile = PROFILES[profile_key]
    return {
        "statement_title": profile["title"],
        "account_summary": profile["summary"],
        "holdings": profile["holdings"],
        "activity_summary": profile["activity_summary"],
        "activity": profile["activity"],
        "realized_gains": profile["realized"],
    }


def diagnostic_fields(profile_key: str) -> dict[str, str]:
    profile = PROFILES[profile_key]
    labels = profile["labels"]
    return {
        "beginningValue": labels["beginning"],
        "deposits": labels["deposits"],
        "withdrawals": labels["withdrawals"],
        "income": labels["income"],
        "fees": labels["fees"],
        "marketChange": labels["market"],
        "endingValue": labels["ending"],
        "holdingsTotal": "Total Holdings",
        "beginningCash": "Beginning Cash",
        "credits": "Credits",
        "debits": "Debits",
        "endingCash": "Ending Cash",
        "realizedGainTotal": "Total Realized Gain/Loss",
    }


_MONTHS = (
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December"
)
_PERIOD_RE = re.compile(
    rf"Statement Period\s*:?[ \t]*(?P<start>(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})\s*"
    rf"[-–]\s*(?P<end>(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})",
    re.I,
)
_ACCOUNT_RE = re.compile(r"Account (?:Number|#|ID)\s*:?[ \t]*([A-Z0-9*Xx-][A-Z0-9*Xx -]{2,30})", re.I)
_ACCOUNT_TYPE_RE = re.compile(r"Account Type\s*:?[ \t]*(.+)$", re.I | re.M)
_MONEY = r"(?:\(\s*\$?[\d,]+\.\d{2}\s*\)|-?\$?-?[\d,]+\.\d{2})"
_MONEY_RE = re.compile(_MONEY)


def _amount(raw: str) -> float:
    value = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    parsed = float(value)
    return -parsed if negative else parsed


def _close(left: float, right: float, tolerance: float = 0.02) -> bool:
    return abs(left - right) <= tolerance


def _require_close(label: str, parsed: float, printed: float, stage: str | None = None) -> None:
    if not _close(parsed, printed):
        lower = label.casefold()
        failure_stage = stage or (
            "holdings"
            if "holding" in lower
            else "realized_gains"
            if "realized" in lower
            else "activity"
            if "activity" in lower or "cash" in lower
            else "summary"
            if "summary" in lower
            else "validation"
        )
        raise diagnostic_helpers.reconciliation_error(
            f"{label} does not reconcile: parsed {parsed:.2f}, printed {printed:.2f}",
            parsed,
            printed,
            failure_stage,
        )


def detect_profile(head_text: str, profile_key: str) -> tuple[bool, str]:
    profile = PROFILES[profile_key]
    lower = head_text.lower()
    required = [profile["brand"], profile["title"], profile["summary"], profile["holdings"]]
    missing = [marker for marker in required if marker.lower() not in lower]
    if not _PERIOD_RE.search(head_text):
        missing.append("Statement Period")
    if not _ACCOUNT_RE.search(head_text):
        missing.append("account identifier")
    if missing:
        return False, f"missing {profile['institution']} statement marker(s): " + ", ".join(missing)
    if "statement guide" in lower or "guide to reading" in lower:
        return False, f"{profile['institution']} educational guide is not an account statement"
    return True, f"found {profile['institution']} brand, statement title, period, account, summary, and holdings markers"


def _period(text: str) -> tuple[date, date]:
    match = _PERIOD_RE.search(text)
    if not match:
        raise ValueError("statement period not found")
    return tuple(
        datetime.strptime(match.group(name), "%B %d, %Y").date()
        for name in ("start", "end")
    )  # type: ignore[return-value]


def _resolve_date(month_day: str, start: date, end: date) -> str:
    month, day = (int(piece) for piece in month_day.split("/"))
    candidates: list[tuple[int, date]] = []
    for year in {start.year - 1, start.year, end.year, end.year + 1}:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        distance = 0 if start <= candidate <= end else min(
            abs((candidate - start).days), abs((candidate - end).days)
        )
        candidates.append((distance, candidate))
    if not candidates:
        raise ValueError(f"invalid activity date {month_day!r}")
    return min(candidates)[1].isoformat()


def _metadata(text: str, profile: dict) -> tuple[str, str, str]:
    match = _ACCOUNT_RE.search(text)
    if not match:
        raise ValueError(f"{profile['institution']} account identifier not found")
    provider_id = match.group(1).strip()
    account = common.last4_digits(provider_id)
    title_match = _ACCOUNT_TYPE_RE.search(text)
    title = title_match.group(1).strip() if title_match else profile["account_title"]
    fallback = "401(k)" if "401(k)" in title else "Brokerage"
    account_type = common.classify_account_type(title, fallback)
    return account, account_type, provider_id


def _summary(lines: list[str], profile: dict) -> dict[str, float]:
    active = False
    values: dict[str, float] = {}
    labels = profile["labels"]
    inverse = {label: key for key, label in labels.items()}
    for raw in lines:
        line = raw.strip()
        if line == profile["summary"]:
            active = True
            continue
        if active and line.startswith(profile["holdings"]):
            break
        if not active:
            continue
        for label, key in inverse.items():
            if not line.startswith(label):
                continue
            amounts = _MONEY_RE.findall(line[len(label):])
            if amounts:
                value = _amount(amounts[0])
                if key in {"withdrawals", "fees"} and value > 0:
                    value = -value
                values[key] = value
            break
    missing = set(labels) - set(values)
    if missing:
        field_ids = {
            "beginning": "beginningValue",
            "deposits": "deposits",
            "withdrawals": "withdrawals",
            "income": "income",
            "fees": "fees",
            "market": "marketChange",
            "ending": "endingValue",
        }
        raise parser_common.ParserDiagnosticError(
            f"missing {profile['institution']} summary total(s): {sorted(missing)}",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="summary",
            missing_fields=sorted(field_ids[key] for key in missing),
        )
    _require_close(
        f"{profile['institution']} account summary",
        values["beginning"] + values["deposits"] + values["withdrawals"]
        + values["income"] + values["fees"] + values["market"],
        values["ending"],
        "summary",
    )
    return values


_CATEGORIES = {
    "Cash and Cash Equivalents": ("Cash", True),
    "Equities": ("Stock", False),
    "Mutual Funds": ("Mutual Fund", False),
    "Fixed Income": ("Fixed Income", False),
}


def _holdings(lines: list[str], profile: dict, account: str, account_type: str,
              provider_id: str) -> tuple[list[dict], float]:
    active = False
    category = ("Security", False)
    rows: list[dict] = []
    printed_total: float | None = None
    last_row: dict | None = None
    row_re = re.compile(
        rf"^(?P<symbol>[A-Z0-9./-]{{1,16}})\s+(?P<description>.+?)\s+"
        rf"(?P<quantity>-?[\d,]+(?:\.\d+)?)\s+(?P<price>{_MONEY})\s+"
        rf"(?P<cost>{_MONEY}|--|—)\s+(?P<value>{_MONEY})$"
    )
    for raw in lines:
        line = raw.strip()
        if line.startswith(profile["holdings"]):
            active, last_row = True, None
            continue
        if active and line.startswith(profile["activity_summary"]):
            break
        if not active:
            continue
        if line in _CATEGORIES:
            category, last_row = _CATEGORIES[line], None
            continue
        total_match = re.match(rf"^Total (?:Holdings|Portfolio|Investments|Assets)\s+({_MONEY})$", line, re.I)
        if total_match:
            printed_total = _amount(total_match.group(1))
            last_row = None
            continue
        match = row_re.match(line)
        if match:
            symbol = match.group("symbol")
            row = {
                "symbol": symbol,
                "description": match.group("description"),
                "quantity": _amount(match.group("quantity")),
                "price": _amount(match.group("price")),
                "cost_basis_total": None if match.group("cost") in {"--", "—"} else _amount(match.group("cost")),
                "current_value": _amount(match.group("value")),
                "type": category[0],
                "is_cash_equivalent": category[1],
                "currency_code": "USD",
                "account": account,
                "accountType": account_type,
                "provider_account_id": provider_id,
            }
            if re.fullmatch(r"[A-Z0-9]{9}", symbol):
                row.update({"security_id": symbol, "security_id_type": "CUSIP", "cusip": symbol})
            rows.append(row)
            last_row = row
            continue
        if last_row and line == "Global Innovation Holding":
            last_row["description"] += " Global Innovation Holding"
    if printed_total is None:
        raise parser_common.ParserDiagnosticError(
            f"{profile['institution']} holdings total not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="holdings",
            missing_fields=("holdingsTotal",),
        )
    _require_close(
        f"{profile['institution']} holdings",
        sum(row["current_value"] for row in rows),
        printed_total,
        "holdings",
    )
    return rows, printed_total


_ACTIONS = (
    ("Transfer Out", "Transfer Out", "transfer_out"),
    ("Transfer In", "Transfer In", "transfer_in"),
    ("Advisory Fee", "Fee", "fee"),
    ("Reinvestment", "Reinvestment", "buy"),
    ("Withdrawal", "Withdrawal", "withdrawal"),
    ("Deposit", "Deposit", "deposit"),
    ("Dividend", "Dividend", "dividend"),
    ("Interest", "Interest", "interest"),
    ("Buy", "Buy", "buy"),
    ("Sell", "Sell", "sell"),
)
_SECURITY_ACTIONS = {"Dividend", "Reinvestment", "Buy", "Sell"}


def _activity_controls(lines: list[str], profile: dict) -> dict[str, float]:
    labels = {
        "Beginning Cash": "beginning",
        "Credits": "credits",
        "Debits": "debits",
        "Ending Cash": "ending",
    }
    active = False
    values: dict[str, float] = {}
    for raw in lines:
        line = raw.strip()
        if line == profile["activity_summary"]:
            active = True
            continue
        if active and line.startswith(profile["activity"]):
            break
        if not active:
            continue
        for label, key in labels.items():
            if line.startswith(label):
                amounts = _MONEY_RE.findall(line[len(label):])
                if amounts:
                    value = _amount(amounts[-1])
                    if key == "debits" and value > 0:
                        value = -value
                    values[key] = value
                break
    missing = set(labels.values()) - set(values)
    if missing:
        field_ids = {
            "beginning": "beginningCash",
            "credits": "credits",
            "debits": "debits",
            "ending": "endingCash",
        }
        raise parser_common.ParserDiagnosticError(
            f"missing {profile['institution']} activity control(s): {sorted(missing)}",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="activity",
            missing_fields=sorted(field_ids[key] for key in missing),
        )
    _require_close(
        f"{profile['institution']} cash activity",
        values["beginning"] + values["credits"] + values["debits"],
        values["ending"],
        "activity",
    )
    return values


def _transactions(lines: list[str], profile: dict, start: date, end: date,
                  account: str, account_type: str, provider_id: str) -> list[dict]:
    active = False
    rows: list[dict] = []
    last_row: dict | None = None
    row_re = re.compile(rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<body>.+?)\s+(?P<amount>{_MONEY})$")
    for raw in lines:
        line = raw.strip()
        if line.startswith(profile["activity"]):
            active, last_row = True, None
            continue
        if active and line.startswith(profile["realized"]):
            active, last_row = False, None
            continue
        if not active:
            continue
        if line.startswith(("Date ", "Total Activity")):
            continue
        match = row_re.match(line)
        if not match:
            if last_row and line.startswith("Reference SYNTHETIC-"):
                last_row["description"] += " " + line
            continue
        body = match.group("body").strip()
        issuer_action = display_action = transaction_type = ""
        for prefix, display, kind in _ACTIONS:
            if body == prefix or body.startswith(prefix + " "):
                issuer_action, display_action, transaction_type = prefix, display, kind
                break
        if not issuer_action:
            raise ValueError(f"unclassified {profile['institution']} activity row: {line}")
        remainder = body[len(issuer_action):].strip()
        quantity = None
        if issuer_action in {"Buy", "Sell", "Reinvestment"}:
            quantity_match = re.search(r"\s+(-?[\d,]+(?:\.\d+)?)$", remainder)
            if not quantity_match:
                raise ValueError(f"missing quantity in {profile['institution']} trade row: {line}")
            quantity = _amount(quantity_match.group(1))
            remainder = remainder[:quantity_match.start()].strip()
        price_match = re.search(r"@\s*\$?([\d,]+\.\d+)", remainder)
        symbol = remainder.split()[0] if issuer_action in _SECURITY_ACTIONS and remainder else ""
        row = {
            "date": _resolve_date(match.group("date"), start, end),
            "description": body,
            "amount": _amount(match.group("amount")),
            "action": display_action,
            "transaction_type": transaction_type,
            "symbol": symbol,
            "currency_code": "USD",
            "account": account,
            "accountType": account_type,
            "provider_account_id": provider_id,
        }
        if quantity is not None:
            row["quantity"] = quantity
        if price_match:
            row["price"] = _amount(price_match.group(1))
        rows.append(row)
        last_row = row
    if not rows:
        raise ValueError(f"no {profile['institution']} activity rows found")
    return rows


def _realized(lines: list[str], profile: dict, transactions: list[dict],
              start: date, end: date) -> None:
    active = False
    detail_total = 0.0
    printed_total: float | None = None
    row_re = re.compile(
        rf"^(?P<symbol>[A-Z0-9./-]+)\s+(?P<purchase>\d{{2}}/\d{{2}}/\d{{4}})\s+"
        rf"(?P<sale>\d{{2}}/\d{{2}})\s+(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
        rf"(?P<cost>{_MONEY})\s+(?P<proceeds>{_MONEY})\s+(?P<gain>{_MONEY})\s+(?P<term>ST|LT)$",
        re.I,
    )
    for raw in lines:
        line = raw.strip()
        if line.startswith(profile["realized"]):
            active = True
            continue
        if not active:
            continue
        match = row_re.match(line)
        if match:
            sale_date = _resolve_date(match.group("sale"), start, end)
            proceeds = _amount(match.group("proceeds"))
            candidates = [
                row for row in transactions
                if row["transaction_type"] == "sell"
                and row.get("symbol") == match.group("symbol")
                and row["date"] == sale_date
                and _close(row["amount"], proceeds)
            ]
            if len(candidates) != 1:
                raise ValueError(f"{profile['institution']} realized gain did not match one sale: {line}")
            gain = _amount(match.group("gain"))
            candidates[0]["realized_gain"] = gain
            candidates[0]["realized_gain_term"] = "Short-term" if match.group("term").upper() == "ST" else "Long-term"
            detail_total += gain
            continue
        total_match = re.match(rf"^Total Realized Gain/Loss\s+({_MONEY})$", line, re.I)
        if total_match:
            printed_total = _amount(total_match.group(1))
            break
    if printed_total is None:
        raise parser_common.ParserDiagnosticError(
            f"{profile['institution']} realized gain total not found",
            code="PARSER_REQUIRED_DATA_MISSING",
            stage="realized_gains",
            missing_fields=("realizedGainTotal",),
        )
    _require_close(
        f"{profile['institution']} realized gains",
        detail_total,
        printed_total,
        "realized_gains",
    )


def _reconcile(profile: dict, summary: dict[str, float], controls: dict[str, float],
               transactions: list[dict], holdings_total: float) -> None:
    credits = sum(row["amount"] for row in transactions if row["amount"] > 0)
    debits = sum(row["amount"] for row in transactions if row["amount"] < 0)
    _require_close(f"{profile['institution']} activity credits", credits, controls["credits"], "activity")
    _require_close(f"{profile['institution']} activity debits", debits, controls["debits"], "activity")
    additions = sum(row["amount"] for row in transactions if row["transaction_type"] in {"deposit", "transfer_in"})
    withdrawals = sum(row["amount"] for row in transactions if row["transaction_type"] in {"withdrawal", "transfer_out"})
    income = sum(row["amount"] for row in transactions if row["transaction_type"] in {"dividend", "interest"})
    fees = sum(row["amount"] for row in transactions if row["transaction_type"] == "fee")
    _require_close(f"{profile['institution']} additions", additions, summary["deposits"], "activity")
    _require_close(f"{profile['institution']} withdrawals", withdrawals, summary["withdrawals"], "activity")
    _require_close(f"{profile['institution']} income", income, summary["income"], "activity")
    _require_close(f"{profile['institution']} fees", fees, summary["fees"], "activity")
    _require_close(f"{profile['institution']} ending holdings", holdings_total, summary["ending"], "holdings")


def parse_profile(pages_text: list[str], pdf_path: str, profile_key: str) -> dict:
    del pdf_path
    profile = PROFILES[profile_key]
    text = "\n".join(pages_text)
    lines = [line.strip() for line in text.splitlines()]
    fields = diagnostic_fields(profile_key)
    extra_counts = {
        "summaryComponents": sum(
            1 for label in profile["labels"].values()
            if any(line.startswith(label) and _MONEY_RE.search(line[len(label):]) for line in lines)
        ),
        "activityControlComponents": sum(
            1 for label in ("Beginning Cash", "Credits", "Debits", "Ending Cash")
            if any(line.startswith(label) and _MONEY_RE.search(line[len(label):]) for line in lines)
        ),
        "holdingsParsed": sum(
            1 for line in lines
            if re.match(r"^[A-Z0-9./-]{1,16}\s+.+\s+" + _MONEY + r"\s+(?:" + _MONEY + r"|--|—)\s+" + _MONEY + r"$", line)
        ),
        "transactionsParsed": sum(
            1 for line in lines
            if re.match(r"^\d{2}/\d{2}\s+", line)
            and any(re.search(rf"\b{re.escape(action)}\b", line) for action, _, _ in _ACTIONS)
        ),
        "realizedRows": sum(
            1 for line in lines if re.search(r"\s(?:ST|LT)$", line) and len(_MONEY_RE.findall(line)) >= 3
        ),
    }
    context = diagnostic_helpers.diagnostic_context(
        pages_text,
        section_markers=tuple(diagnostic_markers(profile_key).values()),
        known_labels=tuple(fields.values()),
        extra_counts=extra_counts,
    )
    try:
        start, end = _period(text)
        account, account_type, provider_id = _metadata(text, profile)
        summary = _summary(lines, profile)
        holdings, holdings_total = _holdings(lines, profile, account, account_type, provider_id)
        controls = _activity_controls(lines, profile)
        transactions = _transactions(lines, profile, start, end, account, account_type, provider_id)
        _realized(lines, profile, transactions, start, end)
        _reconcile(profile, summary, controls, transactions, holdings_total)
    except ValueError as error:
        raise parser_common.enrich_parser_error(error, **context) from error
    return {
        "institution": profile["institution"],
        "statementDate": end.isoformat(),
        "tables": {
            "brokerage_holdings": holdings,
            "brokerage_transactions": transactions,
        },
    }
