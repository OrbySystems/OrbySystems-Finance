"""Shared dispatcher machinery for py/bank_statement.py and
py/csv_statement.py: both are "read a small amount of the document,
ask an ordered list of per-institution modules which one recognizes it,
then hand the whole document to that module's parse()" dispatchers,
built on the exact same result/transaction dict contract (see
_validate_parse_result). The only thing that differs between them is
*how* detect()/parse() are called (bank_statement.py passes PDF text,
csv_statement.py passes spreadsheet rows) - not this shared machinery.

csv_statement.py handles both plain CSV and .xlsx workbooks: a .csv is
just a one-sheet spreadsheet, so both are flattened to the same row
grid and the same csv_institutions/ parser (detect(header, sample_rows)
/ parse(rows, path)) handles either - see looks_like_header_row /
grid_header_and_rows below for the header/footer detection that shared
path relies on.

Because bank_statement.py's --extra-parsers-dir and csv_statement.py's
--extra-parsers-dir point at the very same <orbySystemsDir>/ingest/parsers
directory (see pyruntime.go and CLAUDE.md's "Adding a parser without
touching this repo"), a dropped .py file of either shape gets loaded
successfully by _load_extra_parsers under *both* dispatchers (it only
checks hasattr(module, "detect")/hasattr(module, "parse"), true for
either shape) - but _detect calling module.detect(...) with the wrong
number of positional arguments for that file's shape raises a plain
TypeError, which _detect already treats like any other non-match. So a
CSV-shaped module simply never matches under bank_statement.py (and
vice versa) without either dispatcher needing to know which shape a
given file is - see _detect's docstring.
"""

import contextlib
import dataclasses
import glob
import importlib
import importlib.util
import io
import json
import os
import pkgutil
import re
import traceback

import statement_checks

# --- spreadsheet header/footer detection, shared by csv_statement.py's
# CSV *and* .xlsx paths. A real export often brackets its table with a
# preamble ("Custom report created on: ...") and/or a trailing
# disclosures block, so "the first non-empty row is the header" is wrong
# for those files - looks_like_header_row / grid_header_and_rows find the
# real table instead. Ported from looksLikeHeaderRow in
# pkg/ingest/csv_redact.go (kept behaviourally in sync). ---
_HEADER_DATE_RES = [
    re.compile(r"^\s*\d{4}-\d{1,2}-\d{1,2}\s*$"),
    re.compile(r"^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$"),
    re.compile(r"^\s*\d{4}[/-]\d{1,2}[/-]\d{1,2}\s*$"),
]
_HEADER_NUMBER_RE = re.compile(r"^\s*[(+\-]?\s*[$€£¥]?\s*\d[\d,]*(?:\.\d+)?\s*[%)]?\s*$")


def _cell_is_date_or_number(cell: str) -> bool:
    c = cell.strip()
    if not c:
        return False
    if _HEADER_NUMBER_RE.match(c):
        return True
    return any(rx.match(c) for rx in _HEADER_DATE_RES)


def looks_like_header_row(row: list[str]) -> bool:
    """True when row reads like a table header: at least two non-empty
    cells, none of which parses as a bare date or number. Used to skip a
    preamble and land on the real column-header row.
    """
    non_empty = [c for c in row if c and c.strip()]
    if len(non_empty) < 2:
        return False
    return not any(_cell_is_date_or_number(c) for c in non_empty)


def grid_header_and_rows(grid: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Given a spreadsheet's full row grid, return (header, data_rows):
    the first row that looks_like_header_row (skipping any leading
    preamble), the rows after it, minus a trailing run of rows that have
    at most one non-empty cell (a disclosures / footer block). Blank rows
    anywhere are dropped.
    """
    rows = [r for r in grid if any(c and c.strip() for c in r)]
    header_idx = next((i for i, r in enumerate(rows) if looks_like_header_row(r)), None)
    if header_idx is None:
        return (rows[0] if rows else []), (rows[1:] if len(rows) > 1 else [])
    header = rows[header_idx]
    data = rows[header_idx + 1 :]
    while data and sum(1 for c in data[-1] if c and c.strip()) <= 1:
        data.pop()
    return header, data

# --- parse() IO contract, shared by both dispatchers - see each
# dispatcher's own module docstring for the human-readable version.
# account/accountType are NOT top-level result keys: a statement/export
# can cover more than one account (e.g. a combined checking+savings
# statement, or a multi-account CSV export), so they're only ever
# meaningful per transaction - see _REQUIRED_TXN_KEYS below. ---
# checks (optional, both kinds): the statement's own arithmetic, for the
# dispatcher to evaluate - see statement_checks.py and CONTRACT.md.
_RESULT_KEYS = {"institution", "statementDate", "transactions", "needsVisionOcr", "checks"}
_REQUIRED_RESULT_KEYS = _RESULT_KEYS - {"needsVisionOcr", "checks"}
# account/accountType are required per transaction (every transaction
# belongs to some account, even if the parser couldn't determine its
# number/type - in which case use ""); reference is optional - the
# issuer's own transaction reference number, only printed by some
# statement/export types; institution is optional - set only when a
# transaction's institution differs from the statement's primary one
# (e.g. a combined multi-institution export); provider_account_id is
# optional - the fullest account identifier the source disclosed, for
# telling accounts apart when the trailing digits in "account" are not
# enough (several accounts at one institution can share them, and a
# redacted statement may leave none at all). Matches Transaction's json
# tags on the Go side (see statement.go).
_REQUIRED_TXN_KEYS = {"date", "description", "amount", "balance", "account", "accountType"}
_OPTIONAL_TXN_KEYS = {"reference", "institution", "provider_account_id"}
_TXN_KEYS = _REQUIRED_TXN_KEYS | _OPTIONAL_TXN_KEYS
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --- kind tagging, shared by bank_statement.py's combined institutions/
# list - see module_kind's docstring. ---
KIND_BANK = "bank"
KIND_BROKERAGE = "brokerage"

# Support tier: how far a parser's format has been confirmed on real
# statements. It decides what OrbySystems offers when a statement does not
# read cleanly - a verified or provisional parser's failure asks the user and
# reports what went wrong; an untested one's offers the Statement Scrambler,
# so a scrambled copy can be sent to build it properly. Every bundled parser
# declares one (tests/test_support_tiers.py), and OrbySystems keeps the same
# table in Go (orby-core pkg/parsercatalog), checked against these lines.
# How a parser earns each tier is in orby-core's README_addparser.md.
SUPPORT_TIER_VERIFIED = "verified"        # at least one clean import of a real statement
SUPPORT_TIER_PROVISIONAL = "provisional"  # built from a real statement's layout, awaiting its first clean import
SUPPORT_TIER_UNTESTED = "untested"        # built from public samples or invented data; never seen a real statement
SUPPORT_TIER_DEMO = "demo"                # an invented institution, for the demo household and tests
_SUPPORT_TIERS = {
    SUPPORT_TIER_VERIFIED,
    SUPPORT_TIER_PROVISIONAL,
    SUPPORT_TIER_UNTESTED,
    SUPPORT_TIER_DEMO,
}

_DIAGNOSTIC_CODES = {
    "PARSER_ACTIVITY_ROWS_NOT_FOUND",
    "PARSER_FAILED",
    "PARSER_OUTPUT_INVALID",
    "PARSER_RECONCILIATION_FAILED",
    "PARSER_REQUIRED_DATA_MISSING",
    "PARSER_STATEMENT_DATE_INVALID",
    "PARSER_UNCLASSIFIED_ROW",
}
_DIAGNOSTIC_STAGES = {
    "activity",
    "holdings",
    "metadata",
    "output_validation",
    "parsing",
    "realized_gains",
    "summary",
    "validation",
}
_DIAGNOSTIC_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
_RECONCILIATION_DIRECTIONS = {
    "printedEndingAboveParsedEquation",
    "printedEndingBelowParsedEquation",
}


class ParserDiagnosticError(ValueError):
    """A parser failure with privacy-safe, machine-readable context.

    ``message`` remains internal and may contain exact values for local logs.
    Only the fixed code/stage, module-allowlisted identifiers/booleans/counts,
    and a fixed reconciliation-direction enum can cross the dispatcher
    boundary. Parsers should use this for failures where a report needs more
    precision than can safely be inferred from exception text.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: str,
        missing_fields: tuple[str, ...] | list[str] = (),
        signals: dict[str, bool] | None = None,
        counts: dict[str, int] | None = None,
        unclassified_terms: tuple[str, ...] | list[str] = (),
        reconciliation_direction: str = "",
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code if code in _DIAGNOSTIC_CODES else "PARSER_FAILED"
        self.diagnostic_stage = stage if stage in _DIAGNOSTIC_STAGES else "parsing"
        self.missing_fields = tuple(missing_fields)
        self.diagnostic_signals = dict(signals or {})
        self.diagnostic_counts = dict(counts or {})
        self.unclassified_terms = tuple(unclassified_terms)
        self.reconciliation_direction = reconciliation_direction


def enrich_parser_error(
    error: Exception,
    *,
    signals: dict[str, bool] | None = None,
    counts: dict[str, int] | None = None,
    unclassified_terms: tuple[str, ...] | list[str] = (),
) -> ParserDiagnosticError:
    """Attach privacy-safe structural context to an existing parse failure.

    This is the reusable bridge for older strict parsers: they can retain
    their detailed internal ``ValueError`` messages while publishing only the
    stable code/stage and parser-declared booleans, counts, and vocabulary.
    Existing ``ParserDiagnosticError`` metadata wins when keys overlap.
    """
    supplied_signals = dict(signals or {})
    supplied_counts = dict(counts or {})
    supplied_terms = list(unclassified_terms)
    if isinstance(error, ParserDiagnosticError):
        supplied_signals.update(error.diagnostic_signals)
        supplied_counts.update(error.diagnostic_counts)
        supplied_terms.extend(error.unclassified_terms)
        return ParserDiagnosticError(
            str(error),
            code=error.diagnostic_code,
            stage=error.diagnostic_stage,
            missing_fields=error.missing_fields,
            signals=supplied_signals,
            counts=supplied_counts,
            unclassified_terms=tuple(dict.fromkeys(supplied_terms)),
            reconciliation_direction=error.reconciliation_direction,
        )

    code, stage = _classify_parser_error(error)
    return ParserDiagnosticError(
        str(error),
        code=code,
        stage=stage,
        signals=supplied_signals,
        counts=supplied_counts,
        unclassified_terms=tuple(dict.fromkeys(supplied_terms)),
    )


def module_support_tier(module) -> str:
    """Return a parser's declared support tier. A parser that declares none,
    or an unknown one - a dropped-in parser, say - is untested: nothing says
    its format was ever confirmed on a real statement.
    """
    tier = getattr(module, "SUPPORT_TIER", SUPPORT_TIER_UNTESTED)
    return tier if tier in _SUPPORT_TIERS else SUPPORT_TIER_UNTESTED


def _safe_label(value, fallback: str, limit: int = 80) -> str:
    """Keep only publisher-controlled label characters in diagnostics.

    A parser module is executable code and may be user-supplied. Diagnostic
    metadata must never become a route for arbitrary statement text, paths,
    or control characters to reach a report.
    """
    if not isinstance(value, str):
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9 .&'()_+/-]", "", value).strip()
    return cleaned[:limit] or fallback


def _classify_parser_error(error: Exception) -> tuple[str, str]:
    """Map internal exception text to a stable, content-free code/stage.

    Parser exceptions historically include exact rejected rows and monetary
    values. Only this classification crosses the process/API boundary; the
    exception text itself intentionally does not.
    """
    if isinstance(error, ParserDiagnosticError):
        return error.diagnostic_code, error.diagnostic_stage

    message = str(error).lower()
    # Contract failures often mention row types, dates, or missing fields, so
    # recognize the validator's own shape before the content-oriented rules.
    if ".parse():" in message or (".parse()" in message and "key" in message) or "tables[" in message:
        return "PARSER_OUTPUT_INVALID", "output_validation"
    if "period" in message or "statement date" in message or "activity date" in message:
        return "PARSER_STATEMENT_DATE_INVALID", "metadata"
    if "unclassified" in message or "unrecognized" in message:
        return "PARSER_UNCLASSIFIED_ROW", "activity"
    if "no " in message and ("row" in message or "transaction" in message or "activity" in message):
        return "PARSER_ACTIVITY_ROWS_NOT_FOUND", "activity"
    if "reconcile" in message or "did not match" in message:
        if "holding" in message or "position" in message:
            return "PARSER_RECONCILIATION_FAILED", "holdings"
        if "realized" in message or "gain" in message:
            return "PARSER_RECONCILIATION_FAILED", "realized_gains"
        return "PARSER_RECONCILIATION_FAILED", "validation"
    if "holding" in message or "position" in message:
        return "PARSER_REQUIRED_DATA_MISSING", "holdings"
    if "activity" in message or "transaction" in message:
        return "PARSER_REQUIRED_DATA_MISSING", "activity"
    if "summary" in message or "control total" in message:
        return "PARSER_REQUIRED_DATA_MISSING", "summary"
    if "date" in message:
        return "PARSER_STATEMENT_DATE_INVALID", "metadata"
    return "PARSER_FAILED", "parsing"


def _diagnostic_sections(module, text: str | None) -> dict[str, bool]:
    """Return presence flags for a parser's public, static section markers.

    Only sanitized marker *names* and booleans are returned. Marker text and
    document text are never placed in the diagnostic.
    """
    # Extra parsers are renamed to a bare filename by load_extra_parsers.
    # Their metadata is user-authored rather than reviewed repository data, so
    # do not make any part of it reportable.
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return {}
    markers = getattr(module, "DIAGNOSTIC_MARKERS", None)
    if not text or not isinstance(markers, dict):
        return {}
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    found: dict[str, bool] = {}
    for raw_name, raw_marker in list(markers.items())[:16]:
        name = _safe_label(raw_name, "", 40).lower().replace(" ", "_")
        if not name or not isinstance(raw_marker, str) or not raw_marker:
            continue
        marker = raw_marker.strip().lower()
        found[name] = any(marker in line for line in lines)
    return found


def _diagnostic_missing_fields(module, error: Exception) -> list[str]:
    """Return only trusted, module-allowlisted field identifiers.

    A raw missing label can include statement content, so exception strings
    are never parsed for this data. Bundled parsers must raise
    ``ParserDiagnosticError`` and publish the complete set of allowed stable
    identifiers in ``DIAGNOSTIC_FIELDS``. External parsers cannot add fields
    to a report.
    """
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return []
    if not isinstance(error, ParserDiagnosticError):
        return []
    declared = getattr(module, "DIAGNOSTIC_FIELDS", ())
    if not isinstance(declared, (dict, tuple, list, set, frozenset)):
        return []
    declared_fields = declared.keys() if isinstance(declared, dict) else declared
    allowed = {
        field for field in declared_fields
        if isinstance(field, str) and _DIAGNOSTIC_FIELD_RE.fullmatch(field)
    }
    missing = []
    for field in error.missing_fields:
        if field in allowed and field not in missing:
            missing.append(field)
        if len(missing) >= 16:
            break
    return missing


def _diagnostic_field_presence(module, text: str | None) -> dict[str, bool]:
    """Return presence flags for trusted, static field-label markers."""
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return {}
    fields = getattr(module, "DIAGNOSTIC_FIELDS", None)
    if not text or not isinstance(fields, dict):
        return {}
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    found: dict[str, bool] = {}
    for raw_name, raw_marker in list(fields.items())[:24]:
        if (
            not isinstance(raw_name, str)
            or not _DIAGNOSTIC_FIELD_RE.fullmatch(raw_name)
            or not isinstance(raw_marker, str)
            or not raw_marker
        ):
            continue
        marker = raw_marker.strip().lower()
        found[raw_name] = any(marker in line for line in lines)
    return found


def _diagnostic_error_signals(module, error: Exception) -> dict[str, bool]:
    """Filter parser-supplied booleans through a bundled-module allowlist."""
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return {}
    if not isinstance(error, ParserDiagnosticError):
        return {}
    declared = getattr(module, "DIAGNOSTIC_SIGNALS", ())
    if not isinstance(declared, (tuple, list, set, frozenset)):
        return {}
    allowed = {
        key for key in declared
        if isinstance(key, str) and _DIAGNOSTIC_FIELD_RE.fullmatch(key)
    }
    signals: dict[str, bool] = {}
    for key, value in list(error.diagnostic_signals.items())[:48]:
        if key in allowed and isinstance(value, bool):
            signals[key] = value
    return signals


def _diagnostic_error_counts(module, error: Exception) -> dict[str, int]:
    """Filter non-sensitive structural counts through a module allowlist."""
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return {}
    if not isinstance(error, ParserDiagnosticError):
        return {}
    declared = getattr(module, "DIAGNOSTIC_COUNTS", ())
    if not isinstance(declared, (tuple, list, set, frozenset)):
        return {}
    allowed = {
        key for key in declared
        if isinstance(key, str) and _DIAGNOSTIC_FIELD_RE.fullmatch(key)
    }
    counts: dict[str, int] = {}
    for key, value in list(error.diagnostic_counts.items())[:16]:
        if (
            key in allowed
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 1_000_000
        ):
            counts[key] = value
    return counts


def _diagnostic_unclassified_terms(module, error: Exception) -> list[str]:
    """Return only fixed financial vocabulary terms from unknown labels.

    The raw label is never included. The module's allowlist deliberately omits
    arbitrary words, so a person's, employer's, plan's, or security's name
    cannot become reportable through this field.
    """
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return []
    if not isinstance(error, ParserDiagnosticError):
        return []
    declared = getattr(module, "DIAGNOSTIC_TERMS", ())
    if not isinstance(declared, (tuple, list, set, frozenset)):
        return []
    allowed = {
        term for term in declared
        if isinstance(term, str) and re.fullmatch(r"[a-z][a-z0-9]{0,31}", term)
    }
    terms = []
    for term in error.unclassified_terms:
        if term in allowed and term not in terms:
            terms.append(term)
        if len(terms) >= 32:
            break
    return terms


def _diagnostic_reconciliation_direction(module, error: Exception) -> str:
    """Return a fixed enum describing the sign of a reconciliation gap."""
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return ""
    if not isinstance(error, ParserDiagnosticError):
        return ""
    direction = error.reconciliation_direction
    return direction if direction in _RECONCILIATION_DIRECTIONS else ""


def _parser_revision(module) -> int | None:
    """Return a small bundled-parser revision useful when OrbySystems is a dev build."""
    if not module.__name__.startswith(("institutions.", "csv_institutions.")):
        return None
    revision = getattr(module, "PARSER_REVISION", None)
    if isinstance(revision, int) and not isinstance(revision, bool) and 1 <= revision <= 1_000_000:
        return revision
    return None


def parser_failure(module, error: Exception, input_format: str, input_stats: dict,
                   text: str | None = None) -> tuple[str, dict]:
    """Build the user-facing message and privacy-safe diagnostic for a
    parser that matched a document but failed while parsing it.

    The returned dict is safe to preview/copy/report: it contains no raw
    exception, document text, file name/path, dates, account identifiers,
    securities, or monetary values.
    """
    qualified_name = module.__name__
    bundled = qualified_name.startswith(("institutions.", "csv_institutions."))
    parser_id = (
        _safe_label(qualified_name.rsplit(".", 1)[-1], "unknown_parser", 80)
        if bundled else "external_parser"
    )
    institution = (
        _safe_label(
            getattr(module, "INSTITUTION", getattr(module, "_INSTITUTION", "")),
            "Recognized institution",
            80,
        )
        if bundled else "External parser"
    )
    tier = module_support_tier(module)
    code, stage = _classify_parser_error(error)
    reference = f"{parser_id.replace('_', '-').upper()}-{code.removeprefix('PARSER_')}"
    if not bundled:
        # The dispatcher names its file beside this, under
        # "failedExtraParsers" (failed_extra_parsers), never in it: the
        # message is part of the diagnostic, which may be reported.
        message = (
            f"A parser in your parsers folder claimed this statement but could not read it. "
            f"No data was imported. Error reference: {reference}."
        )
    elif tier == SUPPORT_TIER_UNTESTED:
        message = (
            f"OrbySystems recognized this as {institution}, but that format has not been "
            f"confirmed on real statements yet, and this one did not read cleanly. No data was "
            f"imported. A scrambled copy sent to OrbySystems lets us support it. "
            f"Error reference: {reference}."
        )
    elif tier == SUPPORT_TIER_PROVISIONAL:
        message = (
            f"OrbySystems recognized this as a provisional {institution} format, but this "
            f"statement layout is not covered yet. No data was imported. "
            f"Error reference: {reference}."
        )
    else:
        message = (
            f"OrbySystems recognized this as {institution}, but could not parse the "
            f"{stage.replace('_', ' ')} section. No data was imported. "
            f"Error reference: {reference}."
        )
    diagnostic = {
        "schemaVersion": 4,
        "reference": reference,
        "code": code,
        "parserId": parser_id,
        "institution": institution,
        "supportTier": tier,
        "inputFormat": _safe_label(input_format, "unknown", 16).lower(),
        "stage": stage,
    }
    for key in ("pageCount", "textPageCount", "rowCount", "columnCount"):
        value = input_stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            diagnostic[key] = value
    sections = _diagnostic_sections(module, text)
    if sections:
        diagnostic["sections"] = sections
    field_presence = _diagnostic_field_presence(module, text)
    if field_presence:
        diagnostic["fieldPresence"] = field_presence
    missing_fields = _diagnostic_missing_fields(module, error)
    if missing_fields:
        diagnostic["missingFields"] = missing_fields
    signals = _diagnostic_error_signals(module, error)
    if signals:
        diagnostic["signals"] = signals
    counts = _diagnostic_error_counts(module, error)
    if counts:
        diagnostic["counts"] = counts
    unclassified_terms = _diagnostic_unclassified_terms(module, error)
    if unclassified_terms:
        diagnostic["unclassifiedLabelTerms"] = unclassified_terms
    reconciliation_direction = _diagnostic_reconciliation_direction(module, error)
    if reconciliation_direction:
        diagnostic["reconciliationDirection"] = reconciliation_direction
    parser_revision = _parser_revision(module)
    if parser_revision is not None:
        diagnostic["parserRevision"] = parser_revision
    return message, diagnostic


# What tells a statement no parser recognized from any other document: the
# balances it opens and closes with, and the kinds of money it lists. With
# them the app can offer to have a parser made, before it files the PDF as a
# plain document. Booleans and counts only.
_STATEMENT_SHAPE_SIGNALS = (
    "beginningBalance",
    "endingBalance",
    "deposits",
    "withdrawals",
    "dividendsInterest",
    "fees",
    "holdingsTotal",
)
_STATEMENT_SHAPE_COUNTS = ("financialLabelRows", "datedActivityRows")


def unsupported_format_diagnostic(input_format: str, input_stats: dict, head_text: list[str] | None = None) -> dict:
    """Privacy-safe diagnostic for a statement import where no parser
    matched. Per-parser miss reasons are intentionally excluded. Given the
    pages detection read, it also says whether they read like a statement
    (_STATEMENT_SHAPE_SIGNALS): which signals hold, and how many rows carry
    an amount or start with a date - never a label or an amount.
    """
    diagnostic = {
        "schemaVersion": 4,
        "reference": "PARSER-NOT-FOUND",
        "code": "PARSER_NOT_FOUND",
        "parserId": "",
        "institution": "",
        "supportTier": "unsupported",
        "inputFormat": _safe_label(input_format, "unknown", 16).lower(),
        "stage": "detection",
    }
    for key in ("pageCount", "textPageCount", "rowCount", "columnCount"):
        value = input_stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            diagnostic[key] = value
    if head_text:
        from institutions import diagnostic_helpers  # imports this module

        context = diagnostic_helpers.diagnostic_context(head_text)
        signals = {name: True for name in _STATEMENT_SHAPE_SIGNALS if context["signals"].get(name)}
        if signals:
            diagnostic["signals"] = signals
        diagnostic["counts"] = {name: context["counts"][name] for name in _STATEMENT_SHAPE_COUNTS}
    return diagnostic


def module_kind(module) -> str:
    """Returns module's KIND attribute (KIND_BANK or KIND_BROKERAGE), or
    KIND_BANK if it doesn't define one - the large majority of
    institutions/ modules (every bundled bank/credit-card parser, and
    any externally-dropped plugin written before brokerage support
    existed) return the flat institution["transactions"] shape
    validate_parse_result checks, so that's the default a module need
    not opt into explicitly. A brokerage parser sets `KIND =
    parser_common.KIND_BROKERAGE` at module scope instead, and returns
    the "tables" shape validate_multi_table_parse_result checks - see
    bank_statement.py's module docstring for how the dispatcher uses
    this to decide which parse()/validate contract a matched module
    gets called with.
    """
    return getattr(module, "KIND", KIND_BANK)


# Default sort key for a discovered parser that doesn't set its own
# PRIORITY - see discover_parsers.
DEFAULT_PRIORITY = 100


def parser_name_key(name: str) -> str:
    """Normalizes a parser module name for identity comparison: drops any
    package prefix (institutions.foo -> foo), any trailing .py, and
    treats '-' and '_' as equivalent.

    This is what lets a locally-built parser file (dash-named by
    pkg/project/financeparser, e.g. fidelity-401k-brokerage-pdf.py) and
    the same parser once it has been merged upstream and now ships
    bundled (dash->underscore normalized by pkg/parsersubmit, e.g.
    fidelity_401k_brokerage_pdf) be recognized as the same parser - by
    merge_parsers (so the local copy keeps overriding the bundled one)
    and by bundled_shadow_of / check_expected_parser.
    """
    return name.rsplit(".", 1)[-1].replace("-", "_")


def discover_parsers(package):
    """Imports every submodule of `package` (a parser package like
    `institutions` or `csv_institutions`) that exposes a detect()/parse()
    pair, and returns them as a dispatcher's ordered try-list - so adding
    a parser is just dropping a new file in that package's directory, with
    no _PARSERS list (and no import block) in the dispatcher to edit.

    Order (first match wins in `detect`) is `(PRIORITY, module name)`: a
    module may set a module-scope `PRIORITY` int (default
    DEFAULT_PRIORITY) to sort ahead of / behind its alphabetical
    neighbours when two modules' detect() could both match the same
    document and precedence matters (e.g. institutions/bofa_checking_combined,
    whose header regex is a superset of bofa_checking's). Most modules
    need no PRIORITY - alphabetical order is fine when detect()s are
    mutually exclusive.

    A submodule that doesn't define both detect() and parse() (helper
    modules like institutions/common.py, institutions/check_ocr.py) is
    skipped, as is a private `_`-prefixed one. An import error is NOT
    swallowed here - a bundled module that won't import is a build bug and
    should fail loudly (unlike an externally-dropped plugin, whose import
    errors load_extra_parsers folds into the detect diagnostic).
    """
    modules = []
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        if hasattr(module, "detect") and hasattr(module, "parse"):
            modules.append(module)
    modules.sort(key=lambda m: (getattr(m, "PRIORITY", DEFAULT_PRIORITY), m.__name__.rsplit(".", 1)[-1]))
    return modules


# --- tables-dict parse() contract, used by KIND_BROKERAGE modules (a
# brokerage statement commonly has more than one section worth
# structured data - see bank_statement.py's module docstring for the
# full picture). Table row schemas mirror pkg/ingest/statement.go's
# Transaction/BrokerageTransaction/BrokerageHolding JSON tags exactly -
# see CLAUDE.md's brokerage-statement section for the human-readable
# version of this contract. Like the
# KIND_BANK contract above, account/accountType are NOT top-level result
# keys here either - a brokerage statement/export just as commonly
# covers more than one account (e.g. IRA + taxable in one download), so
# they're required per row in every table instead - see
# _BROKERAGE_TXN_REQUIRED_KEYS/_BROKERAGE_HOLDING_REQUIRED_KEYS. ---
_MULTI_RESULT_KEYS = {"institution", "statementDate", "tables"}

_BROKERAGE_TXN_REQUIRED_KEYS = {"date", "description", "amount", "account", "accountType"}
_BROKERAGE_TXN_OPTIONAL_KEYS = {
    "action", "transaction_type", "subtype", "symbol", "security_id",
    "security_id_type", "quantity", "price", "commission_and_fees",
    # What a corporate_action row IS, from a closed vocabulary
    # (transaction_vocabulary.json's corporate_events). transaction_type
    # says the row is a corporate action; this says which kind.
    "corporate_event",
    "amount_missing", "currency_code", "transaction_time", "status", "reference",
    "cancel_reference", "provider_account_id", "institution",
    # What a sale actually realized, which the statement prints per row
    # and nothing else in this schema records - the input to any
    # tax-year gain/loss question. Signed: a gain is positive, a loss
    # negative. realized_gain_term is "Short-term"/"Long-term"/"" for a
    # row that reports both.
    "realized_gain", "realized_gain_term",
    # The *other* security in a corporate action, as the issuer's own
    # identifier for it: on a merger's outgoing row the security the
    # position was exchanged for, on the incoming row the one it came
    # from. Nothing else in this schema can express "this holding became
    # that one", which is the only record of why a share count changed
    # with no trade behind it - see the securities table's
    # successor_symbol, which is built from these.
    "related_security_id",
}
_BROKERAGE_TXN_KEYS = _BROKERAGE_TXN_REQUIRED_KEYS | _BROKERAGE_TXN_OPTIONAL_KEYS

_BROKERAGE_HOLDING_REQUIRED_KEYS = {"symbol", "account", "accountType"}
_BROKERAGE_HOLDING_OPTIONAL_KEYS = {
    # What the position is expected to pay out over the next twelve
    # months, and that as a share of its value. Statements print both per
    # holding; without them a forward-income question has to be guessed
    # at from past dividends.
    "estimated_annual_income", "estimated_yield",
    "description", "quantity", "price", "current_value", "cost_basis_total",
    "average_cost_basis", "percent_of_account", "type",
    "subtype", "security_id", "security_id_type", "cusip", "isin", "sedol",
    "figi", "currency_code", "price_as_of", "price_time", "vested_quantity",
    "vested_value", "position_type", "market_identifier_code", "sector",
    "industry", "is_cash_equivalent", "tax_lots_json", "provider_account_id",
    "institution",
}
_BROKERAGE_HOLDING_KEYS = _BROKERAGE_HOLDING_REQUIRED_KEYS | _BROKERAGE_HOLDING_OPTIONAL_KEYS

# Per-table (required keys, all allowed keys, numeric keys, nullable
# numeric keys) - cash_transactions reuses the exact same schema
# bank_statement.py's own KIND_BANK parsers use for a "transactions"
# row, so a cash-shaped row means the same thing regardless of which
# kind of parser produced it.
_TABLE_SCHEMAS = {
    "cash_transactions": (_REQUIRED_TXN_KEYS, _TXN_KEYS, {"amount", "balance"}, {"balance"}),
    "brokerage_transactions": (
        _BROKERAGE_TXN_REQUIRED_KEYS, _BROKERAGE_TXN_KEYS,
        {"amount", "quantity", "price", "commission_and_fees", "realized_gain"},
        {"quantity", "price", "commission_and_fees", "realized_gain"},
    ),
    "brokerage_holdings": (
        _BROKERAGE_HOLDING_REQUIRED_KEYS, _BROKERAGE_HOLDING_KEYS,
        {"quantity", "price", "current_value", "cost_basis_total", "average_cost_basis", "percent_of_account", "vested_quantity", "vested_value", "estimated_annual_income", "estimated_yield"},
        {"quantity", "price", "current_value", "cost_basis_total", "average_cost_basis", "percent_of_account", "vested_quantity", "vested_value", "estimated_annual_income", "estimated_yield"},
    ),
}
_STRING_ROW_KEYS = {
    "action", "transaction_type", "subtype", "symbol", "description",
    "security_id", "security_id_type", "currency_code", "transaction_time",
    "status", "reference", "cancel_reference", "provider_account_id",
    "institution", "account", "accountType", "type", "cusip", "isin",
    "sedol", "figi", "price_as_of", "price_time", "position_type",
    "market_identifier_code", "sector", "industry", "tax_lots_json",
    "realized_gain_term", "related_security_id", "corporate_event",
}
_BOOL_ROW_KEYS = {"amount_missing", "is_cash_equivalent"}


# --- the classification vocabulary, loaded from transaction_vocabulary.json
# so there is exactly one copy of it. OrbySystems' Go side reads the same file out
# of the embedded scripts tree (pkg/ingest/flow.go) to build the SQL that
# decides what counts as money moving in or out, and
# tests/test_transaction_vocabulary.py fails CI when a bundled parser emits a
# word that is in neither list.
#
# The point of governing these VALUES is the same as the point of governing
# field NAMES above. A typo'd "amout" key used to become Amount: 0 for every
# row; a contribution labelled "Rollover" instead of "Deposit" used to become
# investment gain for the whole account - same silence, larger number. ---

_VOCABULARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "transaction_vocabulary.json")

with open(_VOCABULARY_PATH, encoding="utf-8") as _f:
    VOCABULARY = json.load(_f)

#: Closed set. A brokerage_transactions row may omit transaction_type, but
#: if it sets one it must be from here - see validate_multi_table_parse_result.
TRANSACTION_TYPES = frozenset(VOCABULARY["transaction_types"])

#: The transaction_type values that mean money entered or left the account.
FLOW_TRANSACTION_TYPES = frozenset(f["transaction_type"] for f in VOCABULARY["flows"])

#: Issuer words that mean the same, honoured on rows carrying no
#: transaction_type. A convenience, not the guarantee - see the JSON's _doc.
FLOW_ACTIONS = frozenset(a for f in VOCABULARY["flows"] for a in f["actions"])

#: Unclassified words already examined and found not to be money movement.
NON_FLOW_ACTIONS = frozenset(VOCABULARY["non_flow_actions"])

#: Every action a row may carry without a transaction_type to explain it.
KNOWN_ACTIONS = FLOW_ACTIONS | NON_FLOW_ACTIONS


def classifies_as_flow(row: dict) -> bool:
    """True when this brokerage_transactions row is recognisable as money
    entering or leaving the account. Mirrors the SQL in pkg/ingest/flow.go."""
    if row.get("transaction_type") in FLOW_TRANSACTION_TYPES:
        return True
    return row.get("action") in FLOW_ACTIONS


#: Issuer word -> the transaction_type it means, for a row that sets none:
#: every flows[].actions word under its flow class, every
#: non_flow_classes[].actions word under its class.
ACTION_CLASSES = {
    **{a: f["transaction_type"] for f in VOCABULARY["flows"] for a in f["actions"]},
    **{a: c["transaction_type"] for c in VOCABULARY["non_flow_classes"] for a in c["actions"]},
}

#: Corporate-action event -> the lower-case words in an action label that name it.
CORPORATE_ACTION_EVENTS = {e["event"]: frozenset(e["words"]) for e in VOCABULARY["corporate_action_events"]}

#: Closed set of corporate_event values - see the vocabulary's
#: _corporate_events_doc. A corporate_action row sets one; parse() rejects
#: anything else by name.
CORPORATE_EVENTS = frozenset(VOCABULARY["corporate_events"])

#: Direction (subtype In / Out) each corporate_event implies, where it has one.
CORPORATE_EVENT_DIRECTIONS = dict(VOCABULARY["corporate_event_directions"])

#: Lower-case label words that name a stated event, first match wins.
_CORPORATE_EVENT_LABELS = [(e["event"], frozenset(e["words"])) for e in VOCABULARY["corporate_event_labels"]]


#: Label events whose kind needs the row's direction: merger -> merger_in/out.
_DIRECTED_EVENTS = frozenset({"merger", "conversion"})


def label_event(label: str, direction: str = "") -> str:
    """The stated corporate event an issuer's action label names, else "".
    direction ("In" / "Out", the row's subtype) turns a bare merger into
    merger_in or merger_out. For a parser that lifts the issuer's label;
    a label that names nothing is the parser's call (other, or an observed
    kind such as share_distribution), never a guess made here."""
    words = set(re.split(r"[^a-z]+", (label or "").lower()))
    for event, names in _CORPORATE_EVENT_LABELS:
        if words & names:
            if event in _DIRECTED_EVENTS:
                d = (direction or "").lower()
                return f"{event}_in" if d == "in" else f"{event}_out" if d == "out" else ""
            return event
    return ""


#: The option kinds a statement can show for a contract, alongside call/put.
OPTION_KINDS = ("call", "put", "expired", "assigned", "exercised")


def _not_applicable_terms() -> dict[str, tuple[str, ...]]:
    """Every term a parser may declare not applicable, by field. A term is
    "<field>:<value>", or "<field>:*" for all of the field's values."""
    return {
        "transaction_type": tuple(sorted(TRANSACTION_TYPES)),
        "corporate_event": tuple(sorted(CORPORATE_EVENTS)),
        "option": OPTION_KINDS,
    }


def expand_not_applicable(declared: dict) -> tuple[dict[str, str], list[str]]:
    """Expands a module's NOT_APPLICABLE ({term: reason}) into one entry per
    value, returning (terms, errors). A term names a vocabulary field and a
    value in it (or *): "option:call", "corporate_event:*". An unknown field
    or value, or a missing reason, is an error and the term is dropped - a
    mistyped declaration must never hide a gap it did not mean to."""
    fields = _not_applicable_terms()
    out: dict[str, str] = {}
    errors: list[str] = []
    for term, reason in (declared or {}).items():
        field, _, value = str(term).partition(":")
        if field not in fields or (value != "*" and value not in fields[field]):
            errors.append(f"{term!r} is not a vocabulary term")
            continue
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{term!r} needs a reason, in words a user can read")
            continue
        for v in (fields[field] if value == "*" else (value,)):
            out[f"{field}:{v}"] = reason.strip()
    return out, errors


def module_not_applicable(module) -> dict[str, str]:
    """The vocabulary terms this parser's module declares cannot occur in the
    statements it reads, each with the reason. Declared only where the format
    cannot contain the thing (a 401(k) plan holds no option contracts) - never
    for something the parser merely does not read, which is a gap, not a
    fact about the institution."""
    terms, _ = expand_not_applicable(getattr(module, "NOT_APPLICABLE", None) or {})
    return terms


#: Rows that move a security (or cash) in or out and so have a direction.
DIRECTIONAL_TYPES = frozenset({"transfer_in", "transfer_out", "internal_transfer", "corporate_action"})
_TYPE_DIRECTION = {"transfer_in": "In", "transfer_out": "Out"}


def set_directions(rows: list[dict]) -> None:
    """Applies the direction rule to brokerage_transactions rows: every
    transfer_in / transfer_out / internal_transfer / corporate_action row says
    which way it went in subtype ("In" / "Out"), and quantity is never signed.

    A row's direction is what the parser set, else what its type or
    corporate_event implies, else the sign of its amount, else the sign of its
    quantity as the statement printed it - and only then is quantity made
    positive. Call it last, after set_corporate_events. A parser that knows
    the direction sets subtype itself; this fills the rest and unsigns."""
    for row in rows:
        if row.get("transaction_type") in DIRECTIONAL_TYPES:
            direction = row.get("subtype") if row.get("subtype") in ("In", "Out") else ""
            direction = (
                direction
                or _TYPE_DIRECTION.get(row["transaction_type"], "")
                or CORPORATE_EVENT_DIRECTIONS.get(row.get("corporate_event") or "", "")
            )
            if not direction:
                for value in (row.get("amount"), row.get("quantity")):
                    if value:
                        direction = "In" if value > 0 else "Out"
                        break
            if direction:
                row["subtype"] = direction
        if isinstance(row.get("quantity"), (int, float)) and row["quantity"] < 0:
            row["quantity"] = -row["quantity"]


def set_corporate_events(rows: list[dict]) -> None:
    """Sets corporate_event on every corporate_action row that has none, from
    what its label states (label_event), else "other". For a parser whose
    statements name an event in the issuer's own words and nothing more; a
    parser that can tell more (a named parent, a printed ratio) sets the
    field itself, and an unexplained share arrival is share_distribution."""
    for row in rows:
        if row.get("transaction_type") == "corporate_action" and not row.get("corporate_event"):
            row["corporate_event"] = label_event(row.get("action", ""), row.get("subtype", "")) or "other"


#: An option contract as the symbol column must carry it - "AVGO260918C420"
#: is a September 2026 $420 call on AVGO. OrbySystems recognises an option
#: by this shape alone (pkg/ingest/securities.go's occSymbolRe).
OCC_SYMBOL = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])([\d.]+)$")

# An option's expiry as statements print it: "JUL 17 26", "Jan 17, 2026",
# "01/17/2026", "17JAN26". Mirrors flow_guard.go's optionExpiryPattern.
_OPTION_EXPIRY = re.compile(
    r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*\.? \d{1,2},? '?\d{2}(\d{2})?\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2}(\d{2})?\b"
    r"|\b\d{1,2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b",
    re.IGNORECASE)
_OPTION_RIGHT = re.compile(r"\b(CALL|PUT)S?\b", re.IGNORECASE)


def transaction_class(row: dict) -> str:
    """The transaction_type this brokerage_transactions row resolves to: its
    own when it sets one from the vocabulary, else the class its action word
    is listed under, else "". Mirrors pkg/ingest/flow.go's classExpr, which
    every income, tax-lot, option and performance figure reads."""
    ttype = row.get("transaction_type") or ""
    if ttype in TRANSACTION_TYPES:
        return ttype
    return ACTION_CLASSES.get(row.get("action") or "", "")


def corporate_event(row: dict) -> str:
    """The event a corporate-action row's label names ("expired",
    "assigned"), else "". Only a corporate_action row, or one that carries no
    transaction_type at all, can be one. Mirrors flow.go's corporateEventExpr."""
    if (row.get("transaction_type") or "") not in ("", "corporate_action"):
        return ""
    words = set(re.split(r"[^a-z]+", (row.get("action") or "").lower()))
    for event, names in CORPORATE_ACTION_EVENTS.items():
        if words & names:
            return event
    return ""


def looks_like_option_contract(row: dict) -> bool:
    """True when a row's description reads as an option contract - a CALL or
    PUT with an expiry date. Such a row needs an OCC_SYMBOL in symbol, or
    every option analysis leaves it out. Mirrors flow_guard.go's check."""
    desc = row.get("description") or ""
    return bool(_OPTION_RIGHT.search(desc) and _OPTION_EXPIRY.search(desc))


def unclassified_action(row: dict) -> str:
    """The row's action if nothing in the vocabulary explains it, else "".

    A row that sets transaction_type is classified and its action is free
    prose - a corporate action's label is lifted verbatim out of the
    statement, so checking it would be wrong. Only a row relying on its
    action alone has to use a word we know.
    """
    if row.get("transaction_type"):
        return ""
    action = (row.get("action") or "").strip()
    if not action or action in KNOWN_ACTIONS:
        return ""
    return action


def validate_parse_result(result: dict, module_name: str) -> None:
    """Raises ValueError with a specific, plugin-author-facing message if
    result doesn't exactly match the parse() contract documented at the
    top of bank_statement.py/csv_statement.py. Applied uniformly to
    every parser's output (bundled and externally-loaded, PDF and CSV
    alike) so a schema regression is caught here, at the one place all
    of them funnel through, rather than surfacing later as silently-
    wrong transaction data in the database (e.g. a typo'd "amout" key
    would otherwise silently become Amount: 0 for every transaction on
    the Go side).
    """
    if not isinstance(result, dict):
        raise ValueError(f"{module_name}.parse() must return a dict, got {type(result).__name__}")
    extra = set(result) - _RESULT_KEYS
    if extra:
        raise ValueError(f"{module_name}.parse() returned unexpected top-level key(s): {sorted(extra)}")
    missing = _REQUIRED_RESULT_KEYS - set(result)
    if missing:
        raise ValueError(f"{module_name}.parse() is missing required key(s): {sorted(missing)}")
    for key in ("institution", "statementDate"):
        if not isinstance(result[key], str):
            raise ValueError(f"{module_name}.parse(): {key!r} must be a str")
    if result["statementDate"] and not _DATE_RE.match(result["statementDate"]):
        raise ValueError(f"{module_name}.parse(): statementDate must be YYYY-MM-DD or '', got {result['statementDate']!r}")
    if "needsVisionOcr" in result and not isinstance(result["needsVisionOcr"], bool):
        raise ValueError(f"{module_name}.parse(): needsVisionOcr must be a bool")
    txns = result["transactions"]
    if not isinstance(txns, list):
        raise ValueError(f"{module_name}.parse(): 'transactions' must be a list")
    for i, t in enumerate(txns):
        if not isinstance(t, dict):
            raise ValueError(f"{module_name}.parse(): transactions[{i}] must be a dict")
        extra = set(t) - _TXN_KEYS
        if extra:
            raise ValueError(f"{module_name}.parse(): transactions[{i}] has unexpected key(s): {sorted(extra)}")
        missing = _REQUIRED_TXN_KEYS - set(t)
        if missing:
            raise ValueError(f"{module_name}.parse(): transactions[{i}] is missing key(s): {sorted(missing)}")
        if not isinstance(t["date"], str) or not _DATE_RE.match(t["date"]):
            raise ValueError(f"{module_name}.parse(): transactions[{i}]['date'] must be YYYY-MM-DD, got {t['date']!r}")
        if not isinstance(t["description"], str) or not t["description"].strip():
            raise ValueError(f"{module_name}.parse(): transactions[{i}]['description'] must be a non-empty str")
        if isinstance(t["amount"], bool) or not isinstance(t["amount"], (int, float)):
            raise ValueError(f"{module_name}.parse(): transactions[{i}]['amount'] must be a number")
        if t["balance"] is not None and (isinstance(t["balance"], bool) or not isinstance(t["balance"], (int, float))):
            raise ValueError(f"{module_name}.parse(): transactions[{i}]['balance'] must be a number or null")
        for key in ("reference", "institution", "account", "accountType"):
            if key in t and not isinstance(t[key], str):
                raise ValueError(f"{module_name}.parse(): transactions[{i}][{key!r}] must be a str")
    if "checks" in result:
        statement_checks.validate_checks(result["checks"], {"cash_transactions": txns}, module_name)


#: Backwards-compatible mode. The rules added with corporate_event and the
#: unsigned-quantity / In-Out direction contract (see CONTRACT.md) are
#: enforced strictly while a parser is being written or tested, and only
#: reported as warnings when a statement is ingested, so a parser written
#: before them (a user's own) keeps working. The dispatchers' --strict flag
#: selects the first; the default is the second.
_STRICT = False
_RULE_BREACHES: dict[str, list] = {}


def set_strict(strict: bool) -> None:
    """Turns backwards-compatible mode off (strict) or on, and forgets any
    warnings collected so far."""
    global _STRICT
    _STRICT = bool(strict)
    reset_rule_warnings()


def reset_rule_warnings() -> None:
    _RULE_BREACHES.clear()


def take_rule_warnings() -> list[str]:
    """The contract rules the parser broke, one line per rule with how many
    rows broke it, then forgotten. Empty in strict mode, which raises instead."""
    out = []
    for first, count in _RULE_BREACHES.values():
        out.append(first if count == 1 else f"{first} (and {count - 1} more row{'s' if count > 2 else ''})")
    _RULE_BREACHES.clear()
    return out


def _breach(rule: str, message: str, strict: bool | None = None) -> bool:
    """Reports a broken contract rule: raises in strict mode, otherwise
    collects a warning (once per rule, counting rows). True when only warned,
    so a caller can drop a value that must not reach the importer."""
    if _STRICT if strict is None else strict:
        raise ValueError(message)
    entry = _RULE_BREACHES.setdefault(rule, [message + " This is accepted so older parsers keep working; "
                                            "the parser test run (strict) rejects it.", 0])
    entry[1] += 1
    return True


def _check_transaction_rules(row: dict, module_name: str, table_name: str, i: int, strict: bool | None = None) -> None:
    """The contract rules that arrived after parsers were first written, for
    one brokerage_transactions row: corporate_event (closed list, only on a
    corporate action, required there), direction in subtype (In / Out, agreeing
    with the type, the event and the sign of the amount, required on a
    transfer or corporate action) and unsigned quantity."""
    where = f"{module_name}.parse(): tables[{table_name!r}][{i}]"
    ttype = row.get("transaction_type")
    event = row.get("corporate_event")
    subtype = row.get("subtype")

    if event and event not in CORPORATE_EVENTS:
        if _breach("event-vocabulary", f"{where}['corporate_event'] is {event!r}, which is not in the vocabulary. "
                   f"Valid values: {sorted(CORPORATE_EVENTS)}. If the statement does not say which event it "
                   f"is, use an observed kind (share_distribution, share_exchange_in/out) or 'other'.", strict):
            row.pop("corporate_event")  # the importer derives it instead
            event = None
    if event and ttype != "corporate_action":
        if _breach("event-on-other-row", f"{where}['corporate_event'] is set on a row whose transaction_type is "
                   f"{ttype!r}; only a corporate_action row has one.", strict):
            row.pop("corporate_event")
            event = None
    if ttype == "corporate_action" and not event:
        _breach("event-missing", f"{where} is a corporate_action with no corporate_event. Set one of "
                f"{sorted(CORPORATE_EVENTS)}; if the statement does not say what it was, share_distribution "
                f"(shares arriving, no cause) or 'other'.", strict)

    if ttype in DIRECTIONAL_TYPES and subtype not in ("In", "Out"):
        _breach("direction-missing", f"{where} is a {ttype} with subtype {subtype!r}; its direction goes in "
                f"subtype, 'In' or 'Out' (parser_common.set_directions fills it in).", strict)
    if subtype in ("In", "Out"):
        implied = _TYPE_DIRECTION.get(ttype)
        if implied and implied != subtype:
            _breach("direction-type", f"{where} is {ttype!r} but has subtype {subtype!r}; a {ttype} is always "
                    f"{implied!r}.", strict)
        by_event = CORPORATE_EVENT_DIRECTIONS.get(event or "")
        if by_event and by_event != subtype:
            _breach("direction-event", f"{where} has corporate_event {event!r}, which is always {by_event!r}, "
                    f"but subtype {subtype!r}. The event is authoritative; fix whichever one is wrong.", strict)
        amount = row.get("amount")
        if ttype in ("transfer_in", "transfer_out", "internal_transfer") and isinstance(amount, (int, float)) \
                and amount and (amount > 0) != (subtype == "In"):
            _breach("direction-amount", f"{where} is a {ttype} with subtype {subtype!r} but amount {amount}: "
                    f"cash moving in is positive and cash moving out is negative.", strict)

    quantity = row.get("quantity")
    if isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and quantity < 0:
        _breach("quantity-signed", f"{where} has quantity {quantity}. A transaction's quantity is never signed; "
                f"the type, or subtype In/Out on a transfer or corporate action, says which way it went.", strict)


def validate_multi_table_parse_result(result: dict, module_name: str) -> None:
    """The KIND_BROKERAGE sibling of validate_parse_result: raises
    ValueError with a specific, plugin-author-facing message if result
    doesn't exactly match the tables-dict parse() contract documented at
    the top of bank_statement.py and in _TABLE_SCHEMAS above. Applied to
    every KIND_BROKERAGE module's output (bundled and externally-loaded
    alike) before bank_statement.py normalizes/prints it, for the same
    reason validate_parse_result exists for KIND_BANK modules - catching
    a schema regression here rather than letting silently-wrong data
    reach the database.
    """
    if not isinstance(result, dict):
        raise ValueError(f"{module_name}.parse() must return a dict, got {type(result).__name__}")
    extra = set(result) - _MULTI_RESULT_KEYS - {"checks"}
    if extra:
        raise ValueError(f"{module_name}.parse() returned unexpected top-level key(s): {sorted(extra)}")
    missing = _MULTI_RESULT_KEYS - set(result)
    if missing:
        raise ValueError(f"{module_name}.parse() is missing required key(s): {sorted(missing)}")
    for key in ("institution", "statementDate"):
        if not isinstance(result[key], str):
            raise ValueError(f"{module_name}.parse(): {key!r} must be a str")
    if result["statementDate"] and not _DATE_RE.match(result["statementDate"]):
        raise ValueError(f"{module_name}.parse(): statementDate must be YYYY-MM-DD or '', got {result['statementDate']!r}")
    tables = result["tables"]
    if not isinstance(tables, dict):
        raise ValueError(f"{module_name}.parse(): 'tables' must be a dict")
    extra_tables = set(tables) - set(_TABLE_SCHEMAS)
    if extra_tables:
        raise ValueError(f"{module_name}.parse(): unrecognized table name(s) in 'tables': {sorted(extra_tables)}")
    for table_name, rows in tables.items():
        required_keys, all_keys, numeric_keys, nullable_numeric_keys = _TABLE_SCHEMAS[table_name]
        if not isinstance(rows, list):
            raise ValueError(f"{module_name}.parse(): tables[{table_name!r}] must be a list")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}] must be a dict")
            extra_keys = set(row) - all_keys
            if extra_keys:
                raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}] has unexpected key(s): {sorted(extra_keys)}")
            missing_keys = required_keys - set(row)
            if missing_keys:
                raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}] is missing key(s): {sorted(missing_keys)}")
            if "date" in row and (not isinstance(row["date"], str) or not _DATE_RE.match(row["date"])):
                raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}]['date'] must be YYYY-MM-DD, got {row['date']!r}")
            if "description" in required_keys and (not isinstance(row["description"], str) or not row["description"].strip()):
                raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}]['description'] must be a non-empty str")
            if "symbol" in required_keys and (not isinstance(row["symbol"], str) or not row["symbol"].strip()):
                raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}]['symbol'] must be a non-empty str")
            for key in numeric_keys:
                if key not in row:
                    continue
                val = row[key]
                if val is None:
                    if key in nullable_numeric_keys:
                        continue
                    raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}][{key!r}] must be a number")
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    suffix = " or null" if key in nullable_numeric_keys else ""
                    raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}][{key!r}] must be a number{suffix}")
            for key in _STRING_ROW_KEYS:
                if key in row and not isinstance(row[key], str):
                    raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}][{key!r}] must be a str")
            for key in _BOOL_ROW_KEYS:
                if key in row and not isinstance(row[key], bool):
                    raise ValueError(f"{module_name}.parse(): tables[{table_name!r}][{i}][{key!r}] must be a bool")
            # transaction_type is the classification axis and it is closed:
            # an unrecognized value here would be silently ignored by every
            # consumer, which for a money-movement class means the row stops
            # counting as a contribution and starts counting as gain. Fail
            # by name, the same way an unknown key does.
            if table_name == "brokerage_transactions":
                _check_transaction_rules(row, module_name, table_name, i)
            ttype = row.get("transaction_type")
            if ttype and ttype not in TRANSACTION_TYPES:
                raise ValueError(
                    f"{module_name}.parse(): tables[{table_name!r}][{i}]['transaction_type'] "
                    f"is {ttype!r}, which is not in the vocabulary. Valid values: "
                    f"{sorted(TRANSACTION_TYPES)}. Add it to "
                    f"scripts/transaction_vocabulary.json if the class is genuinely new."
                )
    if "checks" in result:
        statement_checks.validate_checks(result["checks"], tables, module_name)


def finish_parse(result: dict, module, adjust: dict | None = None) -> dict:
    """The last step of every successful parse, shared by both dispatchers,
    on a result already validated and normalized to the tables envelope:

      * applies the user's answers to the rows (adjust - see
        statement_checks.apply_adjustments), then validates the rows again;
      * evaluates the parser's checks against them into checkResults, which
        decide whether the import is clean or held for the user's review;
      * says which parser read the statement and how far its format is
        confirmed (parser: id, tier, bundled), which decides what the user
        is offered and lets a provisional parser's first clean import be
        recorded.
    """
    checks = result.pop("checks", [])
    if adjust:
        statement_checks.apply_adjustments(result["tables"], checks, adjust)
        validate_multi_table_parse_result(
            {"institution": result["institution"], "statementDate": result["statementDate"],
             "tables": result["tables"], "checks": checks},
            module.__name__,
        )
    result["checkResults"] = statement_checks.evaluate(checks, result["tables"], result.get("statementDate", ""))
    # Contract rules a parser written before them breaks (backwards-compatible
    # mode only; strict mode raised already). The importer shows them.
    rule_warnings = take_rule_warnings()
    if rule_warnings:
        result.setdefault("warnings", []).extend(rule_warnings)
    bundled = module.__name__.startswith(("institutions.", "csv_institutions."))
    result["parser"] = {
        "id": module.__name__.rsplit(".", 1)[-1],
        "tier": module_support_tier(module),
        "bundled": bundled,
    }
    # Terms the parser says cannot occur here, so a coverage report says
    # "not applicable" rather than "not seen". Left out when there are none.
    not_applicable = module_not_applicable(module)
    if not_applicable:
        result["parser"]["notApplicable"] = not_applicable
    return result


def parse_adjust_flag(raw: str | None) -> dict | None:
    """The --adjust value both dispatchers take: the user's answers to a
    statement's failed checks, as JSON (see statement_checks)."""
    if not raw:
        return None
    adjust = json.loads(raw)
    statement_checks.validate_adjustments(adjust)
    return adjust


def load_extra_parsers(extra_parsers_dir: str | None, loader_tag: str, only_name: str | None = None,
                       unloaded: list | None = None):
    """Dynamically loads *.py files in extra_parsers_dir (sorted for
    determinism), or only only_name when provided, as dispatcher-style
    parser modules, so a user can add
    support for a new statement/export format by dropping a file in
    there - no code change or recompile needed (see bank_statement.py/
    csv_statement.py's module docstrings and CLAUDE.md). Each file must
    expose a detect()/parse() pair (of whichever shape the calling
    dispatcher expects - see this module's own docstring for how a
    mismatched shape degrades harmlessly); one that doesn't, or that
    fails to import, is skipped rather than crashing dispatch for every
    other statement/export - its failure is folded into the same
    per-parser "reason" diagnostic detect() already produces for an
    ordinary non-match, so a bad plugin file is visible in the same
    place a legitimate rejection reason would be, not a silent no-op or
    an opaque crash.

    loader_tag namespaces the synthetic module name (e.g. "pdf" or
    "csv") so bank_statement.py and csv_statement.py loading the same
    directory in the same process (as tests do) never collide in
    sys.modules.

    A loaded module can do `from institutions import common` (or
    `from institutions.common import parse_amount, ...`) exactly like a
    bundled module: the dispatcher script's own directory (which
    contains the institutions/ package alongside it - see pyruntime.go's
    writeScripts) is already on sys.path[0] as the running script's
    directory.

    unloaded, when given, collects (file name, path, exception) for each
    file that failed to load, for unloaded_extra_parsers to report and
    expected_parser_not_loaded to answer with: a file that doesn't load is
    otherwise passed over without a word, and a same-named bundled parser
    goes on reading statements in its place.
    """
    modules = []
    misses = []
    if not extra_parsers_dir:
        return modules, misses
    if only_name:
        if os.path.basename(only_name) != only_name or not only_name.endswith(".py"):
            return modules, [f"{only_name}: --only-extra-parser must be a .py filename, not a path"]
        paths = [os.path.join(extra_parsers_dir, only_name)]
        if not os.path.isfile(paths[0]):
            return modules, [f"{only_name}: not found in extra parsers directory"]
    else:
        paths = sorted(glob.glob(os.path.join(extra_parsers_dir, "*.py")))
    for path in paths:
        name = os.path.basename(path)
        if name == "__init__.py":
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_extra_parser_{loader_tag}_{name[:-3]}", path)
            if spec is None or spec.loader is None:
                raise ImportError("could not create module spec")
            module = importlib.util.module_from_spec(spec)
            # A dropped-in module can contain temporary top-level print()
            # calls. Keep those from violating the dispatchers' JSON-only
            # stdout contract or exposing statement-related debug text.
            with contextlib.redirect_stdout(io.StringIO()):
                spec.loader.exec_module(module)
            if not (hasattr(module, "detect") and hasattr(module, "parse")):
                raise _NoDetectParse("module must define detect(...) and parse(...)")
        except Exception as e:  # noqa: BLE001
            misses.append(f"{name}: failed to load: {e}")
            if unloaded is not None:
                unloaded.append((name, path, e))
            continue
        module.__name__ = name[:-3]  # so _detect's misses list reports the filename (minus .py), not the synthetic loader name
        modules.append(module)
    return modules, misses


class _NoDetectParse(AttributeError):
    """A file in the parsers folder that loads but has no detect()/parse()
    pair to dispatch to."""


# How a file in the parsers folder failed to load, as a dispatcher reports it
# under "unloadedExtraParsers" (CONTRACT.md).
LOAD_SYNTAX = "PARSER_LOAD_SYNTAX"
LOAD_RELATIVE_IMPORT = "PARSER_LOAD_RELATIVE_IMPORT"
LOAD_MISSING_MODULE = "PARSER_LOAD_MISSING_MODULE"
LOAD_IMPORT = "PARSER_LOAD_IMPORT"
LOAD_DATACLASS = "PARSER_LOAD_DATACLASS"
LOAD_NO_DETECT_PARSE = "PARSER_LOAD_NO_DETECT_PARSE"
LOAD_ERROR = "PARSER_LOAD_ERROR"

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$")


def _classify_load_error(error: Exception, path: str) -> tuple[str, dict]:
    """The code for how the file at path failed to load, and what else is
    safe to say about it: the line in that file where it failed, the
    module it could not import, or the exception's class. Never the
    exception's text, which can quote the file."""
    same_file = os.path.abspath(path)
    extra = {}
    frames = traceback.extract_tb(error.__traceback__)
    in_file = [f for f in frames if os.path.abspath(f.filename) == same_file]
    if in_file:
        extra["line"] = in_file[-1].lineno
    if isinstance(error, _NoDetectParse):
        return LOAD_NO_DETECT_PARSE, {}
    if isinstance(error, SyntaxError):
        # Compiling the file fails before any of it runs: the line is the
        # error's own, when the error is in this file and not one it imports.
        line = {}
        if error.lineno and os.path.abspath(error.filename or path) == same_file:
            line["line"] = error.lineno
        return LOAD_SYNTAX, line
    if isinstance(error, ImportError) and "relative import" in str(error):
        return LOAD_RELATIVE_IMPORT, extra
    if isinstance(error, ModuleNotFoundError):
        if error.name and _MODULE_NAME.match(error.name):
            extra["module"] = error.name
        return LOAD_MISSING_MODULE, extra
    if isinstance(error, ImportError):
        return LOAD_IMPORT, extra
    if any(os.path.basename(f.filename) == "dataclasses.py" for f in frames):
        # A drop-in is loaded without a sys.modules entry, and the dataclass
        # machinery looks its module up there.
        return LOAD_DATACLASS, extra
    extra["error"] = type(error).__name__
    return LOAD_ERROR, extra


def unloaded_extra_parsers(unloaded: list, bundled: list) -> list[dict]:
    """The files in the parsers folder that failed to load
    (load_extra_parsers' unloaded), as a dispatcher reports them under
    "unloadedExtraParsers": each file's name, a code for how it failed
    (_classify_load_error) at stage "load", and for a file named like a
    bundled parser, that parser's name under "replaces" - it is the one
    still reading statements in the file's place. Without this a file that
    doesn't load is passed over silently, and its user never learns that
    their fix, or their new parser, isn't running. Like
    failedExtraParsers, it never quotes the exception, and the file name is
    the user's own: the app shows it to them and reports it nowhere."""
    bundled_names = {parser_name_key(m.__name__): m.__name__.rsplit(".", 1)[-1] for m in bundled}
    out = []
    for name, path, error in unloaded:
        code, extra = _classify_load_error(error, path)
        entry = {"file": name, "code": code, "stage": "load", **extra}
        replaces = bundled_names.get(parser_name_key(name[:-3]))
        if replaces:
            entry["replaces"] = replaces
        out.append(entry)
    return out


def expected_parser_not_loaded(expected_parser: str | None, unloaded: list,
                               input_format: str) -> tuple[str, dict] | None:
    """When the parser --expected-parser names is a file in the parsers
    folder that failed to load: the failure a dispatcher reports instead of
    reading anything. Matching by name alone (check_expected_parser), the
    bundled parser of that name would read the statement and pass for the
    file, and with no such parser the answer would be "nothing matched",
    saying nothing of why. The message carries the exception's text, for
    whoever is building or trying the file (Build Transactions Extractor's
    Verify step, a trial) and must fix it; the diagnostic, which may be
    reported, does not."""
    if not expected_parser:
        return None
    expected = parser_name_key(expected_parser[:-3] if expected_parser.endswith(".py") else expected_parser)
    for name, path, error in unloaded:
        if parser_name_key(name[:-3]) != expected:
            continue
        code, _ = _classify_load_error(error, path)
        message = f"expected parser {expected_parser} doesn't load, so it was never tried: {error}"
        diagnostic = {
            "schemaVersion": 4,
            "reference": f"EXTERNAL-PARSER-{code.removeprefix('PARSER_')}",
            "code": code,
            "parserId": "external_parser",
            "institution": "External parser",
            "supportTier": SUPPORT_TIER_UNTESTED,
            "inputFormat": _safe_label(input_format, "unknown", 16).lower(),
            "stage": "load",
        }
        return message, diagnostic
    return None


def merge_parsers(bundled: list, extra: list) -> list:
    """Combines bundled (a dispatcher's own _PARSERS) with extra (from
    load_extra_parsers) into the final try-in-order list: an extra
    module whose filename (module.__name__, already stripped of .py by
    load_extra_parsers) matches a bundled module's own name replaces
    that bundled module in place, keeping its original position in the
    try order - this is how a user fixes a bug in a bundled parser
    (e.g. bofa_checking.py) without a code change/recompile, by
    dropping a same-named, edited copy into extra_parsers_dir (see
    bank_statement.py's module docstring). An extra module with no
    matching bundled name is a new parser, appended after every bundled
    one, same as before this override behavior existed.

    Name matching is '-'/'_' insensitive (parser_name_key): a parser
    built locally as `foo-bar-pdf.py` still overrides its own bundled
    copy `foo_bar_pdf.py` once that has been merged upstream, so a user
    can keep editing the local file after contributing it without the
    bundled version silently winning (see bundled_shadow_of, which turns
    that same collision into a warning rather than an error).
    """
    merged = list(bundled)
    unmatched = []
    for module in extra:
        module_key = parser_name_key(module.__name__)
        for i, bundled_module in enumerate(merged):
            if parser_name_key(bundled_module.__name__) == module_key:
                merged[i] = module
                break
        else:
            unmatched.append(module)
    return merged + unmatched


def _find_shadowed_bundled(bundled: list, module):
    """Returns the bundled module `module` shadows (same parser_name_key,
    different actual filename), or None - the shared lookup behind
    bundled_shadow_of / bundled_shadow_identical."""
    if module is None:
        return None
    module_leaf = module.__name__.rsplit(".", 1)[-1]
    module_key = parser_name_key(module_leaf)
    for b in bundled:
        b_leaf = b.__name__.rsplit(".", 1)[-1]
        if b_leaf != module_leaf and parser_name_key(b_leaf) == module_key:
            return b
    return None


def bundled_shadow_of(bundled: list, module) -> str | None:
    """If `module` (the parser a dispatcher's detect() matched) shadows a
    differently-spelled but equivalent bundled parser - same
    parser_name_key, different actual filename, i.e. a locally-built
    `foo-bar-pdf.py` sitting in the bundled `foo_bar_pdf.py`'s slot
    after being merged upstream - returns that bundled parser's
    filename, else None.

    `bundled` is the dispatcher's own unmodified _PARSERS list (not the
    merge_parsers output). An exact-name override (the documented "fix a
    bundled parser in place" workflow, e.g. dropping `bofa_checking.py`)
    is deliberately NOT reported - that has always been silent and
    intentional; only the dash/underscore-differing case, which means
    "this is your own contributed parser, now also bundled", is.
    """
    b = _find_shadowed_bundled(bundled, module)
    if b is None:
        return None
    return b.__name__.rsplit(".", 1)[-1] + ".py"


def _normalized_parser_source(path: str) -> str | None:
    """Reads a parser file and normalizes it for an "is this the same
    parser?" comparison: drops leading blank lines and a leading SPDX
    license header (pkg/parsersubmit prepends one when contributing
    upstream, so the bundled copy carries it and the local drop-in copy
    usually doesn't), and trims trailing whitespace. Returns None if the
    file can't be read."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and (lines[0].strip() == "" or lines[0].lstrip().startswith("# SPDX-License-Identifier:")):
        lines.pop(0)
    return "\n".join(lines).rstrip() + "\n"


def bundled_shadow_identical(bundled: list, module) -> bool:
    """True when `module` shadows a bundled parser (see bundled_shadow_of)
    AND the two source files are identical apart from a leading SPDX
    header and trailing whitespace - i.e. the local drop-in copy carries
    no edits over what is already bundled and can simply be removed."""
    b = _find_shadowed_bundled(bundled, module)
    if b is None:
        return False
    local = _normalized_parser_source(getattr(module, "__file__", "") or "")
    upstream = _normalized_parser_source(getattr(b, "__file__", "") or "")
    return local is not None and local == upstream


def check_expected_parser(module, reason: str, expected_parser: str | None) -> str | None:
    """Returns a plugin-author-facing error message if expected_parser is
    set and module (the result of a dispatcher's own detect(), None if
    nothing matched) isn't the one it names, else None. Used by
    bank_statement.py/csv_statement.py's --expected-parser flag - see
    each dispatcher's module docstring - which lets a caller (Build
    Transactions Extractor's Verify step, pkg/project/financeparser.
    runExtractor) assert that a specific drafted parser is the one that
    actually recognizes its sample file, rather than some other,
    already-installed parser claiming it first and running its parse()
    instead - possibly crashing on data it doesn't expect - with nothing
    telling the caller the intended parser was never reached. reason is
    whatever detect() already produced (its own per-parser miss
    diagnostics when module is None), folded into the message so a
    "nothing matched" case is still actionable.
    """
    if not expected_parser:
        return None
    expected_name = expected_parser[:-3] if expected_parser.endswith(".py") else expected_parser
    if module is not None:
        matched_name = module.__name__.rsplit(".", 1)[-1]
        # '-'/'_' insensitive: the caller's expected filename is dash-spelled
        # (pkg/project/financeparser), but the same parser once merged
        # upstream is bundled dash->underscore normalized - a match on
        # either spelling is the intended parser, not a different one.
        if matched_name == expected_name or parser_name_key(matched_name) == parser_name_key(expected_name):
            return None
        return f"expected parser {expected_parser} to match, but {matched_name}.py matched first instead"
    if reason:
        return f"expected parser {expected_parser} to match, but nothing matched instead: {reason}"
    return f"expected parser {expected_parser} to match, but nothing matched instead"


def detect(call_detect, parsers):
    """Returns (module, reason) for the first parser in parsers whose
    detect() (invoked via call_detect(module), a small closure the
    caller supplies - e.g. `lambda m: m.detect(head_text)` for
    bank_statement.py, `lambda m: m.detect(header, sample_rows)` for
    csv_statement.py) reports a match, or (None, reason) where reason
    explains why every parser rejected the input - one line per parser
    tried, e.g. "bofa_checking: 'bank of america' not found;
    bofa_credit_card: 'bank of america' not found". A parser whose
    detect() raises (including a TypeError from being called with the
    wrong shape's arguments - see this module's own docstring), or
    doesn't return (bool, str), is treated the same as an ordinary
    non-match rather than crashing dispatch for every other parser -
    this applies to bundled and externally-loaded parsers alike, and is
    exactly how a CSV-shaped parser module is silently skipped when
    tried under bank_statement.py, and vice versa.
    """
    misses = []
    for module in parsers:
        try:
            result = call_detect(module)
        except Exception as e:  # noqa: BLE001
            misses.append(f"{module.__name__}: detect() raised: {e}")
            continue
        if not (isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool) and isinstance(result[1], str)):
            misses.append(f"{module.__name__}: detect() must return (bool, str), got {result!r}")
            continue
        matched, reason = result
        if matched:
            return module, reason
        misses.append(f"{module.__name__.rsplit('.', 1)[-1]}: {reason}")
    return None, "; ".join(misses)


# --- reading a claimed document, past a broken drop-in. The first parser
# whose detect() claims a document reads it. An extra parser - a file the
# user dropped in, or a build installed there - that claims it and then
# fails is passed over: the document is read as if that file weren't
# installed. Without this, one half-written drop-in claiming a statement
# stopped it importing although another parser read it (orby-core's
# checklist C6a). A bundled parser that fails still ends the read. ---


def is_bundled(module) -> bool:
    """Whether module is one of this repository's own parsers rather than
    an extra parser from the parsers directory (load_extra_parsers)."""
    return module.__name__.startswith(("institutions.", "csv_institutions."))


def replaced_bundled(bundled: list, module):
    """The bundled parser that module, an extra parser, took the place of
    in merge_parsers (the same parser_name_key), or None."""
    if module is None or is_bundled(module):
        return None
    key = parser_name_key(module.__name__)
    for b in bundled:
        if parser_name_key(b.__name__) == key:
            return b
    return None


def after_failed_extra(parsers: list, module, bundled: list) -> list:
    """The try list after module, an extra parser that claimed the document
    and failed reading it: the rest of parsers as if module weren't
    installed - the bundled parser it took the place of back in its slot,
    then the parsers after it."""
    rest = parsers[parsers.index(module) + 1:]
    replaced = replaced_bundled(bundled, module)
    if replaced is not None and replaced not in rest:
        rest = [replaced] + rest
    return rest


@dataclasses.dataclass
class Read:
    """What read_claimed came to. module and result are the parser that read
    the document and what it read; or module and error are the parser whose
    failure ended the read. failed lists each extra parser that claimed the
    document and failed, as (module, error), including the one the read
    ended on, when it was one."""

    module: object
    result: dict | None = None
    error: Exception | None = None
    failed: list = dataclasses.field(default_factory=list)


def read_claimed(module, call_parse, call_detect, parsers: list, bundled: list, fall_through: bool = True) -> Read:
    """Reads the document with module - the first parser in parsers whose
    detect() claimed it (see detect) - via call_parse(module), which parses
    and validates.

    An extra parser that fails is passed over when fall_through is set: the
    rest of the try list is read as if that file weren't installed
    (after_failed_extra), so the bundled parser it took the place of claims
    the document in its slot, then the parsers after it, the first to claim
    it reading it. When none does, the read ends on that extra parser's
    failure. A bundled parser that fails ends the read either way: the
    parsers after it in the try order (PRIORITY, then name) are less
    specific readings - bofa_checking's detect() also claims a BofA combined
    statement, and would read every account as one.

    A dispatcher turns fall_through off when it is asked for one parser
    (--expected-parser, --only-extra-parser): that parser's failure is the
    answer.
    """
    failed = []
    while True:
        try:
            reset_rule_warnings()
            return Read(module=module, result=call_parse(module), failed=failed)
        except Exception as e:  # noqa: BLE001
            if not fall_through or is_bundled(module):
                return Read(module=module, error=e, failed=failed)
            failed.append((module, e))
            parsers = after_failed_extra(parsers, module, bundled)
            following, _ = detect(call_detect, parsers)
            if following is None:
                return Read(module=module, error=e, failed=failed)
            module = following


def failed_extra_parsers(failed: list) -> list[dict]:
    """The extra parsers a read passed over (Read.failed), as a dispatcher
    reports them under "failedExtraParsers": each one's file name in the
    parsers directory, and the code and stage of its failure
    (_classify_parser_error), never its exception. The file name is the
    user's own, so it is kept out of every diagnostic, and the app keeps it
    on the user's computer."""
    out = []
    for module, error in failed:
        code, stage = _classify_parser_error(error)
        out.append({"file": module.__name__.rsplit(".", 1)[-1] + ".py", "code": code, "stage": stage})
    return out
