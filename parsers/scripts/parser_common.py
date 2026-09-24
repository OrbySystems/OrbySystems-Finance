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
--extra-parsers-dir point at the very same <orbyDir>/ingest/parsers
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

import glob
import importlib
import importlib.util
import json
import os
import pkgutil
import re

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
_RESULT_KEYS = {"institution", "statementDate", "transactions", "needsVisionOcr"}
_REQUIRED_RESULT_KEYS = _RESULT_KEYS - {"needsVisionOcr"}
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

# Runtime support metadata. Parsers that have only been exercised against
# public documentation and synthetic fixtures opt into PROVISIONAL. Existing
# parsers default to SUPPORTED so third-party drop-ins written before this
# metadata existed keep working unchanged.
SUPPORT_TIER_SUPPORTED = "supported"
SUPPORT_TIER_BROAD = "broad"
SUPPORT_TIER_PARTIAL = "partial"
SUPPORT_TIER_PROVISIONAL = "provisional"
_SUPPORT_TIERS = {
    SUPPORT_TIER_SUPPORTED,
    SUPPORT_TIER_BROAD,
    SUPPORT_TIER_PARTIAL,
    SUPPORT_TIER_PROVISIONAL,
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
    """Return a parser's declared support tier, safely defaulting old or
    malformed parser modules to ``supported``.
    """
    tier = getattr(module, "SUPPORT_TIER", SUPPORT_TIER_SUPPORTED)
    return tier if tier in _SUPPORT_TIERS else SUPPORT_TIER_SUPPORTED


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
    """Return a small bundled-parser revision useful when Orby is a dev build."""
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
    if tier == SUPPORT_TIER_PROVISIONAL:
        message = (
            f"Orby recognized this as a provisional {institution} format, but this "
            f"statement layout is not covered yet. No data was imported. "
            f"Error reference: {reference}."
        )
    else:
        message = (
            f"Orby recognized this as {institution}, but could not parse the "
            f"{stage.replace('_', ' ')} section. No data was imported. "
            f"Error reference: {reference}."
        )
    diagnostic = {
        "schemaVersion": 3,
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


def unsupported_format_diagnostic(input_format: str, input_stats: dict) -> dict:
    """Privacy-safe diagnostic for a forced statement import where no
    parser matched. Per-parser miss reasons are intentionally excluded.
    """
    diagnostic = {
        "schemaVersion": 3,
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
    "currency_code", "transaction_time", "status", "reference",
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
    "realized_gain_term", "related_security_id",
}
_BOOL_ROW_KEYS = {"is_cash_equivalent"}


# --- the classification vocabulary, loaded from transaction_vocabulary.json
# so there is exactly one copy of it. Orby's Go side reads the same file out
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
    extra = set(result) - _MULTI_RESULT_KEYS
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
            ttype = row.get("transaction_type")
            if ttype and ttype not in TRANSACTION_TYPES:
                raise ValueError(
                    f"{module_name}.parse(): tables[{table_name!r}][{i}]['transaction_type'] "
                    f"is {ttype!r}, which is not in the vocabulary. Valid values: "
                    f"{sorted(TRANSACTION_TYPES)}. Add it to "
                    f"scripts/transaction_vocabulary.json if the class is genuinely new."
                )


def load_extra_parsers(extra_parsers_dir: str | None, loader_tag: str, only_name: str | None = None):
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
            spec.loader.exec_module(module)
            if not (hasattr(module, "detect") and hasattr(module, "parse")):
                raise AttributeError("module must define detect(...) and parse(...)")
        except Exception as e:  # noqa: BLE001
            misses.append(f"{name}: failed to load: {e}")
            continue
        module.__name__ = name[:-3]  # so _detect's misses list reports the filename (minus .py), not the synthetic loader name
        modules.append(module)
    return modules, misses


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
