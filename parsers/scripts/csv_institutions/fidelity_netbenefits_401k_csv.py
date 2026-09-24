"""Fidelity NetBenefits (workplace 401(k) plan) "Transaction History"
activity export.

Real export layout (a preamble ABOVE the real column-header row, unlike
most bundled CSV parsers):

    Plan name:,<EMPLOYER NAME>
    Date Range,<mm/dd/yyyy> - <mm/dd/yyyy>,,,,

    Date,Investment,Transaction Type,Amount,Shares/Unit
    07/31/2026,FID WORLDWIDE,REVENUE CREDIT,"16.29","0.389"
    06/25/2026,DODGE &amp; COX STOCK X,Dividend,"1,928.69","115.076"
    ...

csv_statement.py's generic preamble-skipper
(parser_common.grid_header_and_rows / looks_like_header_row) can't land
on the real header here: "Plan name:,<EMPLOYER NAME>" has two non-empty
cells, neither a bare date/number, so it reads as a plausible header
itself and wins first - "Date Range,<range>,,,," is data after
that, and the true "Date,Investment,Transaction Type,Amount,Shares/Unit"
row three lines further down is never reached. detect() below works
around that using the two mis-detected rows it's actually handed (which
are still a distinctive, stable fingerprint of this export), and
parse() ignores its `rows` argument entirely and re-reads `csv_path`
itself to find the real header row - exactly the "multi-row header /
preamble before the real header row" case csv_statement.py's module
docstring calls out `csv_path` for.

No account number is ever printed (a workplace-plan export - the
provider ties the account to the plan/employee, not a bank-account-style
number), so `account` is left "" on every row, same as Vanguard's
"Custom Activity Report" (see vanguard_brokerage.py's own detect() /
csv_statement.py's "leaves account blank" note) - the file itself was
named for a specific plan/institution combination (e.g. an "Oracle
Corporation" plan) by whoever exported it, but that's identifying detail
that doesn't belong hardcoded into a bundled parser.

One table only (brokerage_transactions) - this export has no holdings
snapshot, just the activity history. "Investment" is a fund's own short
display name, not a ticker (e.g. "FID WORLDWIDE", "DODGE & COX STOCK
X") - there's no separate symbol column, so it's used as-is; it is at
least stable and unique per fund within one plan, which is what
cross-row/holdings joins need.

Transaction Type maps to `transaction_type` (and, for Exchange/Revenue
Credit, `action`/`subtype` too) per scripts/transaction_vocabulary.json's
closed vocabulary - kept in step with institutions/fidelity_401k_brokerage_pdf.py,
the PDF sibling of this same NetBenefits platform, so the same kind of
event classifies identically regardless of which export produced it
(itemized CSV history vs. the PDF's aggregate activity totals):

  - "Contributions"          -> transaction_type contribution (money
    added, external; the PDF sibling never itemizes contributions per
    row at all, so there's no existing convention to match here)
  - "Dividend"                -> transaction_type dividend, subtype
    interest (action left as the raw "Dividend" - free text is fine once
    transaction_type is set)
  - "Exchange In"/"Exchange Out" -> action "Transfer In"/"Transfer Out",
    transaction_type internal_transfer, subtype transfer - moving
    between funds within the same plan account, external: false, so it
    correctly nets to zero rather than counting as a contribution
    (matches _TOTAL_LABELS in the PDF sibling exactly)
  - "Change In Market Value"  -> transaction_type other (a mark-to-market
    line tied to a multi-day Exchange, share count always 0 - not a real
    money movement; the PDF sibling only surfaces this as a diagnostic
    total, never a transaction row, so "other" here is this parser's own
    call, not a match to an existing convention)
  - "Balance Forward"         -> transaction_type other (the opening
    snapshot at the start of this export's history, not a movement this
    period)
  - "REVENUE CREDIT"          -> action "Revenue Credit", transaction_type
    income, subtype other_income (matches the PDF sibling exactly; raw
    text here is all-caps, so the action is normalized to title case)

Amounts already print in OrbySystems' own sign convention (money in positive,
money out negative, e.g. an Exchange Out row is negative) - no
negation step needed, same as Vanguard's Custom Activity Report.
"""

import csv
import html
import re

from institutions import common

KIND = "brokerage"

_INSTITUTION = "Fidelity NetBenefits"

_REAL_HEADER = ["Date", "Investment", "Transaction Type", "Amount", "Shares/Unit"]

_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

# raw Transaction Type (lowercased) -> (action override or None,
# transaction_type, subtype or None). Kept in step with the _TOTAL_LABELS
# table in institutions/fidelity_401k_brokerage_pdf.py - see the module
# docstring above for why.
_TRANSACTION_TYPE_MAP = {
    "contributions": (None, "contribution", None),
    "dividend": (None, "dividend", "interest"),
    "exchange in": ("Transfer In", "internal_transfer", "transfer"),
    "exchange out": ("Transfer Out", "internal_transfer", "transfer"),
    "change in market value": (None, "other", None),
    "balance forward": (None, "other", None),
    "revenue credit": ("Revenue Credit", "income", "other_income"),
}


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    if not header or header[0].strip().rstrip(":").lower() != "plan name":
        return False, "first header cell is not 'Plan name:'"
    if len(header) < 2 or not header[1].strip():
        return False, "'Plan name:' row has no plan name value"
    if not sample_rows or not sample_rows[0] or sample_rows[0][0].strip() != "Date Range":
        return False, "row after 'Plan name:' is not 'Date Range'"
    if not any([c.strip() for c in r] == _REAL_HEADER for r in sample_rows):
        return False, "did not find the 'Date,Investment,Transaction Type,Amount,Shares/Unit' header row"
    return True, "Fidelity NetBenefits activity export header matched (Plan name: / Date Range / activity header)"


def _to_iso(raw: str) -> str:
    m = _DATE_RE.match(raw.strip())
    if not m:
        raise ValueError(f"fidelity_netbenefits_401k_csv: unrecognized date {raw!r}")
    month, day, year = m.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _read_grid(path: str) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [list(row) for row in csv.reader(f)]


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    grid = _read_grid(csv_path)
    header_idx = next(
        (i for i, r in enumerate(grid) if [c.strip() for c in r] == _REAL_HEADER),
        None,
    )
    if header_idx is None:
        raise ValueError(
            "fidelity_netbenefits_401k_csv: could not find the "
            "'Date,Investment,Transaction Type,Amount,Shares/Unit' header row"
        )

    transactions = []
    for r in grid[header_idx + 1 :]:
        cells = [c.strip() for c in r]
        if not any(cells) or len(cells) < 5:
            continue
        date_raw, investment_raw, txn_type, amount_raw, shares_raw = cells[:5]
        if not date_raw:
            continue

        investment = html.unescape(investment_raw)
        classification = _TRANSACTION_TYPE_MAP.get(txn_type.strip().lower())
        action_override = classification[0] if classification else None
        txn = {
            "date": _to_iso(date_raw),
            "description": f"{txn_type} - {investment}" if investment else txn_type,
            "amount": common.parse_amount(amount_raw) if amount_raw else 0.0,
            "action": action_override or txn_type,
            "symbol": investment,
        }

        shares_raw = shares_raw.strip()
        if shares_raw:
            txn["quantity"] = common.parse_amount(shares_raw)

        if classification:
            _, transaction_type, subtype = classification
            txn["transaction_type"] = transaction_type
            if subtype:
                txn["subtype"] = subtype

        transactions.append(txn)

    common.tag_account(transactions, "", "401(k)")

    return {
        "institution": _INSTITUTION,
        "statementDate": "",
        "tables": {"brokerage_transactions": transactions},
    }
