"""Shared privacy-safe diagnostics for investment-statement parsers."""

from __future__ import annotations

from functools import wraps
import re
from typing import Callable

import parser_common


_MONEY_RE = re.compile(r"(?:\(\s*\$?[\d,]+\.\d{2}\s*\)|-?\$?-?[\d,]+\.\d{2})")
_DATED_ROW_RE = re.compile(r"^(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+){1,2}")

_SIGNAL_PATTERNS = {
    "beginningBalance": re.compile(r"\b(?:beginning|starting|opening)\b.*\b(?:balance|value|cash|net asset value)\b", re.I),
    "endingBalance": re.compile(r"\b(?:ending|closing)\b.*\b(?:balance|value|cash|net asset value)\b", re.I),
    "deposits": re.compile(r"\b(?:deposits?|assets added|additions)\b", re.I),
    "withdrawals": re.compile(r"\b(?:withdrawals?|assets withdrawn|subtractions)\b", re.I),
    "transferIn": re.compile(r"\b(?:transfers?|securities)\s+(?:received|in)\b", re.I),
    "transferOut": re.compile(r"\b(?:transfers?|securities)\s+(?:delivered|out)\b", re.I),
    "income": re.compile(r"\bincome\b", re.I),
    "dividendsInterest": re.compile(r"\b(?:dividends?|interest)\b", re.I),
    "fees": re.compile(r"\b(?:fees?|expenses?|commissions?|charges?)\b", re.I),
    "marketChange": re.compile(r"\b(?:market|investment|mark-to-market)\b.*\b(?:change|gain|loss)\b|\bchange in value\b", re.I),
    "purchases": re.compile(r"\b(?:buy|buys|bought|purchases?)\b", re.I),
    "sales": re.compile(r"\b(?:sell|sells|sold|sales?|redemptions?)\b", re.I),
    "reinvestments": re.compile(r"\breinvest(?:ment|ed|ments)?\b", re.I),
    "exchanges": re.compile(r"\bexchanges?\b", re.I),
    "contributions": re.compile(r"\bcontributions?\b", re.I),
    "distributions": re.compile(r"\bdistributions?\b", re.I),
    "credits": re.compile(r"\bcredits?\b", re.I),
    "debits": re.compile(r"\bdebits?\b", re.I),
    "holdingsTotal": re.compile(r"\btotal\b.*\b(?:holdings|portfolio|positions|investments|assets|account value)\b", re.I),
    "realizedGains": re.compile(r"\brealized\b.*\b(?:gain|loss)\b", re.I),
    "cashSweep": re.compile(r"\b(?:cash|bank) sweep\b|\bcore fund activity\b", re.I),
    "corporateActions": re.compile(r"\b(?:corporate action|merger|spinoff|reorganization)\b", re.I),
    "adjustments": re.compile(r"\badjustments?\b", re.I),
}

DIAGNOSTIC_SIGNALS = tuple(_SIGNAL_PATTERNS) + (
    "activityMatrix",
    "leadingMinusAmounts",
    "parenthesizedNegativeAmounts",
)
DIAGNOSTIC_COUNTS = (
    "financialLabelRows",
    "recognizedFinancialRows",
    "unclassifiedFinancialRows",
    "datedActivityRows",
    "recognizedActivityRows",
    "holdingLikeRows",
    "maxAmountsPerRow",
    "negativeRows",
    "zeroTotalRows",
    "sectionMarkersPresent",
    "summaryComponents",
    "activityControlComponents",
    "holdingsParsed",
    "transactionsParsed",
    "realizedRows",
)

_SAFE_TERM_PATTERNS = {
    "adjustment": re.compile(r"\badjustments?\b", re.I),
    "allocation": re.compile(r"\ballocations?\b", re.I),
    "cash": re.compile(r"\bcash\b", re.I),
    "charge": re.compile(r"\bcharges?\b", re.I),
    "contribution": re.compile(r"\bcontributions?\b", re.I),
    "conversion": re.compile(r"\bconversions?\b", re.I),
    "credit": re.compile(r"\bcredits?\b", re.I),
    "debit": re.compile(r"\bdebits?\b", re.I),
    "deposit": re.compile(r"\bdeposits?\b", re.I),
    "distribution": re.compile(r"\bdistributions?\b", re.I),
    "dividend": re.compile(r"\bdividends?\b", re.I),
    "exchange": re.compile(r"\bexchanges?\b", re.I),
    "fee": re.compile(r"\bfees?\b", re.I),
    "income": re.compile(r"\bincome\b", re.I),
    "interest": re.compile(r"\binterest\b", re.I),
    "loan": re.compile(r"\bloans?\b", re.I),
    "market": re.compile(r"\bmarket\b", re.I),
    "purchase": re.compile(r"\b(?:purchases?|buy|bought)\b", re.I),
    "rebalance": re.compile(r"\brebalanc(?:e|ed|es|ing)\b", re.I),
    "redemption": re.compile(r"\bredemptions?\b", re.I),
    "reinvestment": re.compile(r"\breinvest(?:ment|ed|ments)?\b", re.I),
    "rollover": re.compile(r"\brollovers?\b", re.I),
    "sale": re.compile(r"\b(?:sales?|sell|sold)\b", re.I),
    "transfer": re.compile(r"\btransfers?\b", re.I),
    "withdrawal": re.compile(r"\bwithdrawals?\b", re.I),
}
DIAGNOSTIC_TERMS = tuple(_SAFE_TERM_PATTERNS)


def diagnostic_context(
    pages_text: list[str],
    *,
    section_markers: tuple[str, ...] = (),
    known_labels: tuple[str, ...] = (),
    extra_counts: dict[str, int] | None = None,
) -> dict:
    """Return only allowlist-friendly booleans, counts, and vocabulary."""
    lines = [re.sub(r"\s+", " ", line.strip()) for page in pages_text for line in page.splitlines()]
    lines = [line for line in lines if line]
    signals = {name: False for name in DIAGNOSTIC_SIGNALS}
    counts = {
        "financialLabelRows": 0,
        "recognizedFinancialRows": 0,
        "unclassifiedFinancialRows": 0,
        "datedActivityRows": 0,
        "recognizedActivityRows": 0,
        "holdingLikeRows": 0,
        "maxAmountsPerRow": 0,
        "negativeRows": 0,
        "zeroTotalRows": 0,
        "sectionMarkersPresent": sum(
            1 for marker in section_markers if any(marker.casefold() in line.casefold() for line in lines)
        ),
    }
    terms: set[str] = set()
    normalized_labels = tuple(label.casefold() for label in known_labels if label)

    for line in lines:
        amounts = list(_MONEY_RE.finditer(line))
        if not amounts:
            continue
        counts["financialLabelRows"] += 1
        counts["maxAmountsPerRow"] = max(counts["maxAmountsPerRow"], len(amounts))
        if len(amounts) > 1:
            signals["activityMatrix"] = True
        if "-$" in line or "$-" in line:
            signals["leadingMinusAmounts"] = True
            counts["negativeRows"] += 1
        elif re.search(r"\(\s*\$?[\d,]+\.\d{2}\s*\)", line):
            signals["parenthesizedNegativeAmounts"] = True
            counts["negativeRows"] += 1

        label = line[: amounts[0].start()].strip(" :-")
        matched = False
        for name, pattern in _SIGNAL_PATTERNS.items():
            if pattern.search(label):
                signals[name] = True
                matched = True
        if normalized_labels and any(label.casefold().startswith(item) for item in normalized_labels):
            matched = True
        if matched:
            counts["recognizedFinancialRows"] += 1
        else:
            counts["unclassifiedFinancialRows"] += 1
            for term, pattern in _SAFE_TERM_PATTERNS.items():
                if pattern.search(label):
                    terms.add(term)

        dated = bool(_DATED_ROW_RE.match(line))
        if dated:
            counts["datedActivityRows"] += 1
            if matched:
                counts["recognizedActivityRows"] += 1
        elif len(amounts) >= 3 and re.match(r"^[A-Z0-9./-]{1,16}\s+", line):
            counts["holdingLikeRows"] += 1

        raw_total = amounts[-1].group().replace("$", "").replace(",", "").replace(" ", "")
        negative = raw_total.startswith("(") and raw_total.endswith(")")
        raw_total = raw_total.strip("()")
        try:
            total = float(raw_total)
        except ValueError:
            total = 1.0
        if negative:
            total = -total
        if abs(total) < 0.005:
            counts["zeroTotalRows"] += 1

    if extra_counts:
        counts.update(extra_counts)
    return {"signals": signals, "counts": counts, "unclassified_terms": sorted(terms)}


def repair_grade(
    *, section_markers: tuple[str, ...] = (), known_labels: tuple[str, ...] = ()
) -> Callable:
    """Decorator that enriches a strict parser's ``ValueError`` failures."""

    def decorate(func: Callable) -> Callable:
        @wraps(func)
        def wrapped(pages_text: list[str], pdf_path: str):
            try:
                return func(pages_text, pdf_path)
            except ValueError as error:
                context = diagnostic_context(
                    pages_text,
                    section_markers=section_markers,
                    known_labels=known_labels,
                )
                raise parser_common.enrich_parser_error(error, **context) from error

        return wrapped

    return decorate


def reconciliation_error(message: str, parsed: float, printed: float, stage: str) -> ParserDiagnosticError:
    direction = (
        "printedEndingAboveParsedEquation"
        if printed > parsed
        else "printedEndingBelowParsedEquation"
    )
    return parser_common.ParserDiagnosticError(
        message,
        code="PARSER_RECONCILIATION_FAILED",
        stage=stage,
        reconciliation_direction=direction,
    )
