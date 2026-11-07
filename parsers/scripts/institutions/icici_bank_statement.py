"""ICICI Bank account statement parser.

Format: the PDF statement ICICI Bank (India) sends for a customer's savings
and current accounts, every account of the customer in one statement,
password-protected (orby-core docs/password-protected-pdfs.md). Page 1:

    Summary of Accounts held under Cust ID: 123456789 as on November 07, 2026
    ACCOUNT TYPE A/c BALANCE(A) FIXED DEPOSITS ... TOTAL BALANCE(A+B) NOMINATION
    Savings - NRE A/c 001101234567 52,410.00 0.00 52,410.00 Registered
    ...
    Statement of Transactions in Savings Account Number: 001101234567 in INR for the period August 07, 2026 - November 07, 2026
    DATE MODE** PARTICULARS DEPOSITS WITHDRAWALS BALANCE
    07-08-2026 B/F 52,000.00
    30-09-2026 001101234567:Int.Pd:30-06-2026 to 29-09-2026 410.00 52,410.00
    TOTAL 410.00 0.00 52,410.00

Each account's transactions follow a "Statement of Transactions in ...
Account Number: N" heading: the balance brought forward, then one line per
transaction - its date (DD-MM-YYYY), its mode and particulars, its amount,
and the balance after it - then the account's TOTAL of deposits and
withdrawals and its closing balance. A transaction's particulars may run on
to the lines below it. Deposits and withdrawals share one place in the text,
so each amount's direction is read from the balance it leaves: the
balance after it is the one before plus a deposit, or less a withdrawal.

Amounts are in the account's currency, named in its heading ("in INR"), which
every row carries as currency_code. The particulars repeat the account's own
number, which is masked to its last four digits. The statement's own
arithmetic is reported as checks, for each account: every row's balance
follows from the one before it, the deposits and the withdrawals add up to
their TOTALs, the brought-forward balance plus every row is the closing
balance, and that is the balance the account summary shows. A dated line in
a transactions section that could not be read is listed as unread.

Built from a scrambled sample of a real statement (README_addparser.md);
detect() is anchored on words the scrambler keeps.
"""

import re
from datetime import datetime

import parser_common
from institutions import common

SUPPORT_TIER = parser_common.SUPPORT_TIER_PROVISIONAL
PARSER_REVISION = 1

INSTITUTION = "ICICI Bank"

# The currencies an ICICI account is kept in: rupees, and the foreign-currency
# (FCNR) deposit currencies.
_CURRENCIES = {"INR", "USD", "GBP", "EUR", "AUD", "CAD", "SGD", "AED", "JPY", "CHF", "HKD", "NZD"}

_AMOUNT = r"-?\d{1,3}(?:,\d{2,3})*\.\d{2}|-?\d+\.\d{2}"
_DATE = r"\d{2}-\d{2}-\d{4}"
_LONG_DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"

_SECTION_RE = re.compile(
    r"^Statement of Transactions in (.+?) Account Number:\s*(\d{6,20})\s+in\s+([A-Z]{3})\b"
    r"(?:.*?for the period\s+(" + _LONG_DATE + r")\s*-\s*(" + _LONG_DATE + r"))?", re.I)
_HEADER_RE = re.compile(r"^DATE\s+\S+\s+\S+\s+DEPOSITS\s+WITHDRAWALS\s+BALANCE$", re.I)
# A transaction: its date, mode and particulars, its amount, the balance after.
_ROW_RE = re.compile(r"^(" + _DATE + r")\s+(.*?)\s*(" + _AMOUNT + r")\s+(" + _AMOUNT + r")$")
# The balance brought forward: a date, a short mark ("B/F"), one amount.
_BROUGHT_RE = re.compile(r"^(" + _DATE + r")\s+(\S{1,4})\s+(" + _AMOUNT + r")$")
_TOTAL_RE = re.compile(r"^TOTAL\s+(" + _AMOUNT + r")\s+(" + _AMOUNT + r")\s+(" + _AMOUNT + r")$")
_DATED_RE = re.compile(r"^" + _DATE + r"\b")
_PAGE_RE = re.compile(r"^Page \d+ of \d+$", re.I)
# The account summary's line for an account: "Savings - NRE A/c 001101234567 52,410.00 ...".
_SUMMARY_RE = re.compile(r"\bA/[a-z]\s+(\d{6,20})\s+(" + _AMOUNT + r")(?!\d)", re.I)
_AS_ON_RE = re.compile(r"\bas on\s+(" + _LONG_DATE + r")", re.I)


def detect(head_text: str) -> tuple[bool, str]:
    missing = [name for name, found in (
        ("ICICI", "ICICI" in head_text),
        ("Statement of Transactions in ... Account Number", re.search(r"Statement of Transactions in .+? Account Number", head_text, re.I)),
        ("DATE ... DEPOSITS WITHDRAWALS BALANCE", re.search(r"DEPOSITS\s+WITHDRAWALS\s+BALANCE", head_text)),
    ) if not found]
    if missing:
        return False, "ICICI Bank statement marker(s) not found: " + ", ".join(missing)
    return True, "matched ICICI Bank statement (ICICI, Statement of Transactions, DEPOSITS WITHDRAWALS BALANCE)"


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def _iso(raw: str) -> str:
    return datetime.strptime(raw, "%d-%m-%Y").strftime("%Y-%m-%d")


def _long_iso(raw: str) -> str:
    return datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")


def _mask(text: str, numbers: set[str]) -> str:
    """The customer's own account numbers, wherever particulars repeat them,
    down to their last four digits."""
    for number in sorted(numbers, key=len, reverse=True):
        text = text.replace(number, "*" * (len(number) - 4) + number[-4:])
    return text


class _Account:
    def __init__(self, kind: str, number: str, currency: str, heading: dict):
        self.kind, self.number, self.currency = kind, number, currency
        self.heading = heading  # where its transactions start: {page, line, text}
        self.opening = None  # the balance brought forward
        self.rows: list[dict] = []
        self.total = None  # (deposits, withdrawals, closing), as printed


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:  # noqa: ARG001 - pdf_path/vision unused, see bank_statement.py contract
    pages = [_lines(t) for t in pages_text]
    combined = "\n".join(pages_text)

    accounts: dict[str, _Account] = {}
    order: list[_Account] = []
    unread: list[dict] = []
    statement_date = ""
    account = None  # the account whose transactions are being read
    row = None  # the last transaction read, which a wrapped line carries on
    for p, lines in enumerate(pages, 1):
        for n, s in enumerate(lines, 1):
            if not s or _PAGE_RE.match(s) or _HEADER_RE.match(s):
                continue
            section = _SECTION_RE.match(s)
            if section:
                kind, number, currency = section.group(1), section.group(2), section.group(3).upper()
                if section.group(5):
                    statement_date = max(statement_date, _long_iso(section.group(5)))
                account = accounts.get(number)
                if account is None:
                    account = _Account(kind, number, currency if currency in _CURRENCIES else "INR",
                                       {"page": p, "line": n, "text": s})
                    accounts[number] = account
                    order.append(account)
                row = None
                continue
            if account is None:
                # A transaction outside every account's section: reported, not dropped.
                if _ROW_RE.match(s):
                    unread.append({"page": p, "line": n, "text": s})
                continue
            total = _TOTAL_RE.match(s)
            if total:
                account.total = tuple(common.parse_amount(x) for x in total.groups())
                account, row = None, None
                continue
            brought = _BROUGHT_RE.match(s)
            if brought and account.opening is None and not account.rows:
                account.opening = common.parse_amount(brought.group(3))
                row = None
                continue
            r = _ROW_RE.match(s)
            if r:
                try:
                    day = _iso(r.group(1))
                except ValueError:
                    unread.append({"page": p, "line": n, "text": s})
                    row = None
                    continue
                figure, balance = common.parse_amount(r.group(3)), common.parse_amount(r.group(4))
                before = account.rows[-1]["balance"] if account.rows else account.opening
                # The direction the balance moved: a deposit or a withdrawal.
                if before is not None and abs(before - figure - balance) < 0.005 and abs(before + figure - balance) >= 0.005:
                    amount = -figure
                elif before is not None and abs(before + figure - balance) < 0.005:
                    amount = figure
                else:
                    # The balance doesn't follow: signed by which way it went,
                    # and the running check says so.
                    amount = -figure if before is not None and balance < before else figure
                row = {"date": day, "description": r.group(2) or "Transaction", "amount": amount, "balance": balance}
                account.rows.append(row)
                continue
            if _DATED_RE.match(s):
                unread.append({"page": p, "line": n, "text": s})
                row = None
                continue
            if row is not None:
                row["description"] += " " + s  # particulars run on to the next line

    if not order:
        raise parser_common.ParserDiagnosticError(
            "no 'Statement of Transactions in ... Account Number: N' section found",
            code="PARSER_REQUIRED_DATA_MISSING", stage="summary", missing_fields=("transactions",))
    if not statement_date:
        m = _AS_ON_RE.search(combined)
        statement_date = _long_iso(m.group(1)) if m else max((t["date"] for a in order for t in a.rows), default="")

    summary_balance = {}
    for s in (line for lines in pages for line in lines):
        m = _SUMMARY_RE.search(s)
        if m and m.group(1) in accounts:
            summary_balance[m.group(1)] = common.parse_amount(m.group(2))

    numbers = set(accounts)
    transactions: list[dict] = []
    checks: list[dict] = []
    for a in order:
        first = len(transactions)
        account_type = common.classify_account_type(a.kind, "Savings")
        for t in a.rows:
            transactions.append({
                "date": t["date"], "description": _mask(t["description"], numbers), "amount": t["amount"],
                "balance": t["balance"], "account": common.last4_digits(a.number), "accountType": account_type,
                "currency_code": a.currency,
            })
        rows = list(range(first, len(transactions)))
        label = f"{a.kind} account {common.last4_digits(a.number)}"
        if a.opening is not None:
            checks.append({"kind": "running", "label": label, "table": "cash_transactions", "rows": rows, "opening": a.opening})
        if a.total is not None:
            deposits, withdrawals, closing = a.total
            checks.append({"kind": "sum", "label": label + " deposits", "table": "cash_transactions",
                           "rows": [i for i in rows if transactions[i]["amount"] > 0], "expected": deposits})
            checks.append({"kind": "sum", "label": label + " withdrawals", "table": "cash_transactions",
                           "rows": [i for i in rows if transactions[i]["amount"] < 0], "expected": -withdrawals})
            if a.opening is not None:
                checks.append({"kind": "balance", "label": label, "table": "cash_transactions", "rows": rows,
                               "opening": a.opening, "closing": closing})
        if a.opening is not None and a.number in summary_balance:
            checks.append({"kind": "balance", "label": "Summary of Accounts, " + label, "table": "cash_transactions",
                           "rows": rows, "opening": a.opening, "closing": summary_balance[a.number]})
        if a.opening is None or a.total is None:
            # Its brought-forward balance or its TOTAL wasn't found: the
            # section's heading is listed, so the gap shows.
            unread.append(a.heading)
    if unread:
        unread.sort(key=lambda u: (u["page"], u["line"]))
        checks.append({"kind": "unread", "label": "Statement of Transactions", "lines": unread})

    keys = ["date", "description", "amount", "balance", "account", "accountType"]
    if hasattr(parser_common, "normalize_currency_codes"):
        keys.append("currency_code")
    return {
        "institution": INSTITUTION,
        "statementDate": statement_date,
        "transactions": [{k: t[k] for k in keys} for t in transactions],
        "checks": checks,
    }
