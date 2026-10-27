"""Bank of America checking/savings statement parser.

Format: monthly checking/savings statements with "Deposits and other
additions" / "Withdrawals and other subtractions" / "Service fees" /
"Checks" sections, and transaction dates as MM/DD/YY.
"""

import parser_common
import re
from datetime import datetime

import pdfplumber

from institutions import check_ocr, common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED

_SECTIONS = {
    "deposits and other additions": "credit",
    "withdrawals and other subtractions": "debit",
    "service fees": "debit",
}

# Matches "Account number: 1234 5678 9012", "Account # 1234 5678 9012",
# "Account #: 9041", etc. The captured run can include spaces (some
# statements print the number in space-separated groups), so the caller
# strips non-digits and keeps the last 4 rather than slicing this
# capture directly.
_ACCOUNT_NUMBER_RE = re.compile(
    r"account\s*(?:number|#)\s*:?\s*\n*\s*([\dXx*\s]{2,25})", re.IGNORECASE
)
# The continuation-page header names the holder; pdfplumber reads its
# separator as "|" in some layouts and "!" in others.
_OWNER_HEADER_RE = re.compile(r"^([A-Z][A-Z .,'&-]+?)\s*[|!]\s*Account\s*#\s*([\dXx*\s]+?)\s*[|!]", re.M)

# The older statement layout has no account number in its page header; the
# name sits in front of the statement period instead.
_LEGACY_OWNER_HEADER_RE = re.compile(r"^([A-Z][A-Z .,'&-]+?)\s+\d{2}-\d{2}-\d{2}\s+through\s+\d{2}-\d{2}-\d{2}\s*$", re.M)


def _printed_name(name: str) -> bool:
    # Scrambled or redacted statements print X's where the name was.
    name = name.strip()
    return len(name.split()) >= 2 and any(set(word) - {"X"} for word in name.split())


_NAME_LINE_RE = re.compile(r"[A-Z][A-Z.'-]*(?: [A-Z][A-Z.'-]*)+")
# A name after one of these is a beneficiary ("POD" is payable on death, "ITF"
# in trust for), not a holder: the account is not joint.
_BENEFICIARY_RE = re.compile(r"(?:POD|TOD|ITF|PAYABLE ON DEATH TO|TRANSFER ON DEATH TO)\b", re.I)


def _joint_holder(text: str, first: str) -> str:
    """A second holder printed after the first on the summary line.

    A joint account's page header names only the first holder, but the
    summary names both on one line ("FIRST LAST SECOND OTHER"). Running
    text, phone numbers and web addresses after the name are not capitals
    only, so they are not taken.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(first + " "):
            rest = line[len(first) + 1:]
            if (_NAME_LINE_RE.fullmatch(rest) and len(rest.split()) <= 4
                    and not _BENEFICIARY_RE.match(rest)):
                return rest
    return ""


def header_owners(text: str, account: str) -> list[dict]:
    """The holder (or holders) named in the page header of one account's statement."""
    if not account:
        return []
    for m in _OWNER_HEADER_RE.finditer(text):
        if common.last4_digits(m.group(2)) == account and _printed_name(m.group(1)):
            name = m.group(1).strip()
            second = _joint_holder(text, name)
            return [{"account": account, "ownerName": f"{name} & {second}" if second else name}]
    return []


def _address_block_names(text: str) -> list[str]:
    """Holder names printed just above the street line of the mailing block."""
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if not re.match(r"\d+\s+[A-Z0-9]", line):
            continue
        names = []
        j = i - 1
        while j >= 0 and len(names) < 2 and _NAME_LINE_RE.fullmatch(lines[j]):
            if not _BENEFICIARY_RE.match(lines[j]):
                names.insert(0, lines[j])
            j -= 1
        if names and all(_printed_name(n) for n in names):
            return names
    return []


def legacy_header_owners(text: str, accounts: list[str]) -> list[dict]:
    """The holder(s) named in the older layout, for each account listed.

    The mailing block names every holder, one per line; the page header,
    when there is one, names the first only and has to agree with it.
    """
    header = next((m.group(1).strip() for m in _LEGACY_OWNER_HEADER_RE.finditer(text) if _printed_name(m.group(1))), "")
    names = _address_block_names(text)
    if names and header and names[0] != header:
        names = []
    name = " & ".join(names) or header
    return [{"account": a, "ownerName": name} for a in dict.fromkeys(accounts) if a] if name else []


# Matches e.g. "Beginning balance on April 14, 2016 $1,607.04". No
# per-transaction balance column is printed, so this is the seed for a
# running balance we compute ourselves (see common.apply_running_balance).
_BEGINNING_BALANCE_RE = re.compile(
    r"Beginning balance on\s+\w+ \d{1,2},\s*\d{4}\s+\$?(-?[\d,]+\.\d{2})", re.IGNORECASE
)

# Matches the statement header block, e.g.:
#   Your BofA Core Checking
#   for April 14, 2016 to May 12, 2016 Account number: 9041
# Up to a few lines (e.g. a Preferred Rewards tier line) can appear
# between the account name and the "for ... to ..." period line, so
# that gap is matched non-greedily rather than assuming they're
# adjacent.
_STATEMENT_HEADER_RE = re.compile(
    r"^Your\s+(.+?)\s*\n(?:.*\n){0,3}?\s*for\s+(\w+ \d{1,2}, \d{4})\s+to\s+(\w+ \d{1,2}, \d{4})",
    re.IGNORECASE | re.MULTILINE,
)


def detect(head_text: str) -> tuple[bool, str]:
    if "bank of america" not in head_text.lower():
        return False, "'bank of america' not found"
    if not _STATEMENT_HEADER_RE.search(head_text):
        return False, "'bank of america' found, but no 'Your ... for DATE to DATE' checking/savings header"
    return True, "matched Bank of America checking/savings header"


def _extract_account_number(combined_text: str) -> str:
    m = _ACCOUNT_NUMBER_RE.search(combined_text)
    if not m:
        return ""
    return common.last4_digits(m.group(1))


def _extract_statement_meta(combined_text: str) -> tuple[str, str]:
    """Returns (account_type, statement_date) parsed from the statement's
    header block, e.g. ("Checking", "2016-05-12"). statement_date is the
    period's closing date. Either may be "" if the header isn't found or
    doesn't match the expected format.
    """
    m = _STATEMENT_HEADER_RE.search(combined_text)
    if not m:
        return "", ""

    raw_type = m.group(1).strip()
    lower = raw_type.lower()
    if "checking" in lower or "chkg" in lower:
        account_type = "Checking"
    elif "savings" in lower or "svgs" in lower:
        account_type = "Savings"
    else:
        account_type = raw_type

    try:
        statement_date = datetime.strptime(m.group(3), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        statement_date = ""

    return account_type, statement_date


def _expand_year_yy(date_yy: str) -> str:
    """Convert MM/DD/YY to YYYY-MM-DD."""
    mm, dd, yy = date_yy.split("/")
    return f"20{yy}-{mm}-{dd}"


def _parse_transactions(pages_text: list[str]) -> list[dict]:
    transactions = []
    checks = []
    section_type = None  # "credit", "debit", or "check"
    pending_txn = None

    txn_re = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+" r"(.+?)\s+" r"(-?[\d,]+\.\d{2})\s*$")
    check_entry_re = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(\d+\*?)\s+(-[\d,]+\.\d{2})")

    def flush(txn):
        if txn:
            transactions.append(txn)

    for text in pages_text:
        # A transaction description may wrap onto following lines, but it
        # cannot continue through a physical page boundary.  Flushing here
        # also keeps the repeated "Account # ..." page header from being
        # mistaken for another description line.
        flush(pending_txn)
        pending_txn = None
        for line in text.split("\n"):
            s = line.strip()

            if re.match(r"^(Page \d+ of \d+|PULL:|This page intentionally)", s):
                continue
            if re.match(r"^MARILYN .* Account #", s):
                continue

            s_lower = s.lower()
            s_lower_base = re.sub(r"\s*-\s*continued.*$", "", s_lower).strip()

            matched_section = None
            for sec, stype in _SECTIONS.items():
                if s_lower_base == sec or s_lower_base.startswith(sec):
                    matched_section = stype
                    break

            if matched_section:
                flush(pending_txn)
                pending_txn = None
                section_type = matched_section
                continue

            if re.match(r"^Checks?\b", s, re.IGNORECASE) and not re.match(
                r"^Checks?\s+-\s+continued", s, re.IGNORECASE
            ):
                flush(pending_txn)
                pending_txn = None
                if re.match(r"^Checks?\s*$", s, re.IGNORECASE):
                    section_type = "check"
                elif re.match(r"^Total checks", s, re.IGNORECASE):
                    section_type = None
                continue

            if re.match(
                r"^(Total deposits|Total withdrawals|Total other subtractions|Total service fees|Total #|Note your|To help you|Service fees)",
                s,
                re.IGNORECASE,
            ):
                flush(pending_txn)
                pending_txn = None
                if re.match(r"^Service fees", s, re.IGNORECASE):
                    section_type = "debit"
                else:
                    section_type = None
                continue

            if section_type is None:
                continue

            # BofA can place a promotional block after this marker on the
            # same page.  It is outside the transaction table, so finish the
            # pending row and wait for the continued section heading on the
            # next page before accepting more rows.
            if re.match(r"^continued on(?: the)? next page\b", s, re.IGNORECASE):
                flush(pending_txn)
                pending_txn = None
                section_type = None
                continue

            if re.match(
                r"^Date\s+(Description|Check #|Transaction description)\s+Amount", s
            ):
                continue

            if section_type == "check":
                for m in check_entry_re.finditer(s):
                    date = _expand_year_yy(m.group(1))
                    num = m.group(2).rstrip("*")
                    amount = common.parse_amount(m.group(3).lstrip("-"))
                    checks.append(
                        {
                            "date": date,
                            "description": f"CHECK #{num}",
                            # Checks are always withdrawals.
                            "amount": -amount,
                            "balance": None,
                        }
                    )
                continue

            m = txn_re.match(s)
            if m:
                flush(pending_txn)
                date = _expand_year_yy(m.group(1))
                description = m.group(2).strip()
                amount = common.parse_amount(m.group(3).lstrip("-"))
                # A single signed amount column: debits (withdrawals/fees)
                # are negative, credits (deposits) are positive.
                signed_amount = amount if section_type == "credit" else -amount
                pending_txn = {
                    "date": date,
                    "description": description,
                    "amount": signed_amount,
                    "balance": None,
                }
            elif pending_txn and s and not re.match(r"^\d{2}/\d{2}/\d{2}\b", s):
                if re.match(
                    r"^(Total |Page |\* There|Your checking|Your savings)",
                    s,
                    re.IGNORECASE,
                ):
                    continue
                pending_txn["description"] += " " + s
            else:
                flush(pending_txn)
                pending_txn = None

    flush(pending_txn)

    all_txns = transactions + checks
    all_txns.sort(key=lambda t: (t["date"], t["description"]))
    return all_txns


def _extract_starting_balance(combined_text: str) -> float | None:
    m = _BEGINNING_BALANCE_RE.search(combined_text)
    if not m:
        return None
    return common.parse_amount(m.group(1))


def parse(pages_text: list[str], pdf_path: str, vision: dict | None = None) -> dict:
    combined = "\n".join(pages_text)
    account_type, statement_date = _extract_statement_meta(combined)
    account = _extract_account_number(combined)
    transactions = _parse_transactions(pages_text)
    common.apply_running_balance(transactions, _extract_starting_balance(combined))
    common.tag_account(transactions, account, account_type)

    # Check images (payee/memo) are the one thing this parser needs the
    # actual PDF object for - everything else above works from pages_text
    # alone. See check_ocr.py/README_bankcheck_ocr.md.
    needs_vision_ocr = False
    if pdf_path:
        with pdfplumber.open(pdf_path) as pdf:
            if check_ocr.find_check_image_pages(pdf):
                if vision:
                    check_ocr.enrich_checks(transactions, pdf, vision)
                else:
                    needs_vision_ocr = True

    return {
        "institution": "Bank of America",
        "statementDate": statement_date,
        "transactions": transactions,
        "needsVisionOcr": needs_vision_ocr,
        "accountOwners": header_owners(combined, account),
    }
