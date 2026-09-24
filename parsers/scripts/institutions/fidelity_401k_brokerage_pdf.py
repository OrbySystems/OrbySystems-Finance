# SPDX-License-Identifier: Apache-2.0
"""Fidelity NetBenefits 401(k) retirement savings statement PDF.

This format is exported from the NetBenefits "Statement Details" page,
not Fidelity's ordinary monthly brokerage "INVESTMENT REPORT". It prints
an ending holdings snapshot and aggregate activity TOTALS for the
statement period (Exchange In/Out, Revenue Credit, Dividends & Interest,
Change In Market Value) - it does not print itemized transactions, even
though the page includes a "Detailed Transaction History" heading. An
earlier revision of this parser reconstructed synthetic per-fund
"transaction" rows from those aggregate totals, but a total is not a
transaction: it cannot say which of several same-day, same-fund dividend
or exchange events it represents, so those synthesized rows silently
misrepresented the account's real activity.

detect() still recognizes this exact format - it checks every marker it
always has - but then deliberately returns (False, ...) with a reason
pointing at csv_institutions/fidelity_netbenefits_401k_csv.py, the
NetBenefits "Transaction History" CSV export, which is genuinely
itemized (one row per real transaction) and covers the same account.
Rejecting in detect() rather than raising from parse() is deliberate:
detect()'s reason string is shown to the caller verbatim (bank_statement.py's
"not detected" output, `go run . extract-statement`'s CLI output, Build
Transactions Extractor's Verify step) - a parse()-time
ParserDiagnosticError is not, its message is privacy-redacted down to a
generic template plus a machine-readable code before it ever reaches a
caller (see parser_common.parser_failure), which would silently swallow
this guidance. parse() is kept only so this module still exposes both
detect()/parse() (parser_common.discover_parsers skips a module that
doesn't) and raises the same error if it is ever somehow reached
directly.
"""

import re

import parser_common

KIND = parser_common.KIND_BROKERAGE
SUPPORT_TIER = parser_common.SUPPORT_TIER_BROAD
PARSER_REVISION = 6

_INSTITUTION = "Fidelity NetBenefits"

_PERIOD_RE = re.compile(
    r"Statement Period:\s*(\d{2})/(\d{2})/(\d{4})\s+to\s+(\d{2})/(\d{2})/(\d{4})"
)

_REJECTION_MESSAGE = (
    "Fidelity NetBenefits 401(k) PDF statements only print aggregate activity "
    "totals per fund (Exchange In/Out, Revenue Credit, Dividends & Interest, "
    "Change In Market Value), not itemized transactions, so this format "
    "cannot be extracted reliably. Download the CSV formatted statement from "
    "Transaction History instead (NetBenefits > this plan > Transaction "
    "History > Download)."
)


def detect(head_text: str) -> tuple[bool, str]:
    lower = head_text.lower()
    if "fidelity netbenefits" not in lower:
        return False, "'fidelity netbenefits' not found"
    if "retirement savings statement" not in lower:
        return False, "'retirement savings statement' not found"
    if not _PERIOD_RE.search(head_text):
        return False, "no NetBenefits statement period found"
    return False, _REJECTION_MESSAGE


def parse(pages_text: list[str], pdf_path: str) -> dict:
    raise parser_common.ParserDiagnosticError(
        _REJECTION_MESSAGE,
        code="PARSER_REQUIRED_DATA_MISSING",
        stage="parsing",
    )
