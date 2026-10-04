"""The statement's own arithmetic, checked against what a parser read.

A statement prints figures about itself: a section's total, the opening and
closing balance, a running balance down the rows. A parser reports those as
checks in its parse() output (CONTRACT.md, "Checks") instead of raising
when they disagree with the rows it read, and the dispatcher evaluates them
here. Every check passing is what makes an import clean. A failed check does
not fail the parse: OrbySystems holds the import and asks the user, and the
failure's explanation - computed here from the numbers themselves - is what
the questions are built from:

  sign          the section's rows add up to the printed figure with their
                sign reversed - money in read as money out, or the reverse
  row-sign      one row's sign is reversed
  extra-row     one row should not count (a subtotal read as a transaction)
  missing-lines lines the parser did not read account for the difference
  none          nothing found that explains it

The user's answers come back as adjustments (apply_adjustments): flip a
check's rows, leave a row out, add a not-read line as a row, or set a
not-read line aside as not a transaction. The parse is run again with them,
so the checks are evaluated against the adjusted rows the same way.

Nothing here leaves the machine except what diagnostic_summary() returns,
which carries no text, dates or amounts.

Check shapes (keys are required unless marked optional):

  {"kind": "sum", "label": str, "table": str, "rows": [int], "expected": number}
      the rows' amounts add up to a figure the statement prints
  {"kind": "balance", "label": str, "table": str, "rows": [int],
   "opening": number, "closing": number}
      the opening balance plus the rows' amounts is the closing balance
  {"kind": "running", "label": str, "table": str, "rows": [int],
   "opening": number | None (optional)}
      each row's balance is the one before it (or opening) plus its amount
  {"kind": "unread", "label": str, "lines": [{"page": int, "line": int, "text": str}]}
      lines inside a transaction section that the parser did not read as rows

Figures are in the output's own sign convention (CONTRACT.md): what a
parser negates for a credit card, it negates in its checks too. rows index
the output table named by table ("cash_transactions" for a bank parser).
"""

from __future__ import annotations

import itertools
import re

KINDS = ("sum", "balance", "running", "unread")
# Half a cent, per row: printed figures are rounded to the cent.
TOLERANCE = 0.005

_EXPLANATIONS = ("sign", "row-sign", "extra-row", "missing-lines", "none")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_checks(checks, tables: dict, module_name: str) -> None:
    """Raises ValueError, naming the parser and the check, when checks is not
    a list of well-formed checks over rows that exist."""
    if not isinstance(checks, list):
        raise ValueError(f"{module_name}.parse(): 'checks' must be a list")
    for i, c in enumerate(checks):
        where = f"{module_name}.parse(): checks[{i}]"
        if not isinstance(c, dict):
            raise ValueError(f"{where} must be a dict")
        kind = c.get("kind")
        if kind not in KINDS:
            raise ValueError(f"{where}['kind'] must be one of {list(KINDS)}, got {kind!r}")
        if not isinstance(c.get("label"), str) or not c["label"].strip():
            raise ValueError(f"{where}['label'] must be a non-empty str")
        allowed = {
            "sum": {"kind", "label", "table", "rows", "expected"},
            "balance": {"kind", "label", "table", "rows", "opening", "closing"},
            "running": {"kind", "label", "table", "rows", "opening"},
            "unread": {"kind", "label", "lines"},
        }[kind]
        required = allowed - {"opening"} if kind == "running" else allowed
        extra, missing = set(c) - allowed, required - set(c)
        if extra:
            raise ValueError(f"{where} has unexpected key(s): {sorted(extra)}")
        if missing:
            raise ValueError(f"{where} is missing key(s): {sorted(missing)}")
        if kind == "unread":
            if not isinstance(c["lines"], list):
                raise ValueError(f"{where}['lines'] must be a list")
            for j, line in enumerate(c["lines"]):
                if (not isinstance(line, dict) or set(line) != {"page", "line", "text"}
                        or not all(isinstance(line[k], int) and not isinstance(line[k], bool) for k in ("page", "line"))
                        or not isinstance(line["text"], str)):
                    raise ValueError(f"{where}['lines'][{j}] must be {{'page': int, 'line': int, 'text': str}}")
            continue
        table = c["table"]
        if table not in tables:
            raise ValueError(f"{where}['table'] names {table!r}, which the parse did not return")
        rows = c["rows"]
        if not isinstance(rows, list) or not all(isinstance(r, int) and not isinstance(r, bool) for r in rows):
            raise ValueError(f"{where}['rows'] must be a list of row indices")
        if any(r < 0 or r >= len(tables[table]) for r in rows) or len(set(rows)) != len(rows):
            raise ValueError(f"{where}['rows'] must index {table!r}'s rows, each once")
        for key in ("expected", "opening", "closing"):
            if key in c and not (_is_number(c[key]) or (key == "opening" and kind == "running" and c[key] is None)):
                raise ValueError(f"{where}[{key!r}] must be a number")


# --- reading an unread line -------------------------------------------------

_LEAD_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_TAIL_AMOUNT = re.compile(
    r"(?P<neg1>-)?\$?(?P<paren>\()?\$?(?P<num>\d[\d,]*\.\d{2})\)?(?P<neg2>-)?(?:\s*(?P<mark>CR|DR))?\s*$", re.I)


def suggest_row(text: str, statement_date: str, sign: int, template: dict | None = None) -> dict | None:
    """A transaction row read generically from a line the parser skipped:
    a date at its start, an amount at its end, the words between. sign (+1
    or -1) is the sign the section's other rows carry, which the line
    itself rarely prints. None when the line has no date or no amount."""
    d, a = _LEAD_DATE.match(text), _TAIL_AMOUNT.search(text)
    if not d or not a:
        return None
    month, day = int(d.group(1)), int(d.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = d.group(3)
    if year:
        year = int(year) + (2000 if len(year) == 2 else 0)
    else:
        year = int(statement_date[:4]) if re.match(r"^\d{4}", statement_date or "") else 0
        # A December row on a January statement belongs to the year before.
        if year and statement_date[5:7] == "01" and month == 12:
            year -= 1
    if not year:
        return None
    description = re.sub(r"\s+", " ", text[d.end():a.start()]).strip()
    if not description:
        return None
    amount = float(a.group("num").replace(",", ""))
    printed_negative = bool(a.group("neg1") or a.group("neg2") or a.group("paren")
                            or (a.group("mark") or "").upper() == "CR")
    amount = -amount if (sign < 0) != printed_negative else amount
    row = {"date": f"{year:04d}-{month:02d}-{day:02d}", "description": description,
           "amount": round(amount, 2), "balance": None, "account": "", "accountType": ""}
    for key in ("account", "accountType", "institution"):
        if template and key in template:
            row[key] = template[key]
    return row


def _section_sign(rows: list[dict]) -> int:
    amounts = [r.get("amount") for r in rows if _is_number(r.get("amount")) and r.get("amount")]
    if not amounts:
        return -1
    return -1 if sum(1 for a in amounts if a < 0) >= len(amounts) / 2 else 1


# --- evaluating -------------------------------------------------------------

def _close(a: float, b: float, n: int = 1) -> bool:
    return abs(a - b) <= TOLERANCE * max(1, n) + 1e-9


def _explain(gap: float, amounts: list[float], indices: list[int], unread: list[dict]) -> dict:
    """What accounts for gap (printed minus parsed) - see the module
    docstring's list."""
    n = len(amounts)
    total = sum(amounts)
    if n and _close(gap, -2 * total, n):
        return {"kind": "sign", "rows": list(indices), "lines": []}
    for idx, a in zip(indices, amounts):
        if _close(gap, -2 * a, n):
            return {"kind": "row-sign", "rows": [idx], "lines": []}
    for idx, a in zip(indices, amounts):
        if _close(gap, -a, n):
            return {"kind": "extra-row", "rows": [idx], "lines": []}
    candidates = [line for line in unread if line.get("suggested")]
    for size in range(1, min(3, len(candidates)) + 1):
        for combo in itertools.combinations(candidates, size):
            if _close(gap, sum(line["suggested"]["amount"] for line in combo), n + size):
                return {"kind": "missing-lines", "rows": [], "lines": [line["at"] for line in combo]}
    if len(candidates) > 3 and _close(gap, sum(line["suggested"]["amount"] for line in candidates), n + len(candidates)):
        return {"kind": "missing-lines", "rows": [], "lines": [line["at"] for line in candidates]}
    return {"kind": "none", "rows": [], "lines": []}


def evaluate(checks: list[dict], tables: dict, statement_date: str = "") -> list[dict]:
    """One result per check: whether it holds and, when it does not, what
    explains it. parsed and expected are the two sides of the comparison
    (or, for a running check, the first row where the chain breaks); they
    stay on this machine - diagnostic_summary() leaves them out."""
    # Every not-read line, read generically, so a gap can be matched to it.
    unread: list[dict] = []
    for ci, c in enumerate(checks):
        if c["kind"] != "unread":
            continue
        for li, line in enumerate(c["lines"]):
            unread.append({"at": {"check": ci, "line": li}, "label": c["label"], "text": line["text"],
                           "page": line["page"], "lineNo": line["line"]})

    def section_rows(c):
        return [tables[c["table"]][r] for r in c["rows"]]

    # Suggested rows take the sign of the section they belong to: the
    # first sum/balance check with the same label, else money out.
    signs = {}
    for c in checks:
        if c["kind"] in ("sum", "balance") and c["label"] not in signs:
            signs[c["label"]] = (_section_sign(section_rows(c)), section_rows(c)[0] if c["rows"] else None)
    tables_of = {c["label"]: c["table"] for c in checks if c["kind"] != "unread"}
    for line in unread:
        sign, template = signs.get(line["label"], (-1, None))
        row = suggest_row(line["text"], statement_date, sign, template)
        if row is not None and tables_of.get(line["label"], "cash_transactions") != "cash_transactions":
            row.pop("balance", None)  # only cash rows carry a running balance
        line["suggested"] = row

    results = []
    for ci, c in enumerate(checks):
        base = {"index": ci, "kind": c["kind"], "label": c["label"], "table": c.get("table", "")}
        if c["kind"] == "unread":
            mine = [line for line in unread if line["at"]["check"] == ci]
            results.append({**base, "ok": not mine, "rowCount": 0, "parsed": None, "expected": None,
                            "explanation": {"kind": "none" if not mine else "missing-lines", "rows": [],
                                            "lines": [line["at"] for line in mine]},
                            "lines": [{"page": line["page"], "line": line["lineNo"], "text": line["text"],
                                       "suggested": line["suggested"]} for line in mine]})
            continue
        rows = section_rows(c)
        amounts = [float(r.get("amount") or 0) for r in rows]
        if c["kind"] in ("sum", "balance"):
            if c["kind"] == "sum":
                parsed, expected = round(sum(amounts), 2), round(c["expected"], 2)
            else:
                parsed, expected = round(c["opening"] + sum(amounts), 2), round(c["closing"], 2)
            ok = _close(parsed, expected, len(amounts))
            explanation = ({"kind": "none", "rows": [], "lines": []} if ok
                           else _explain(expected - parsed, amounts, list(c["rows"]), unread))
            results.append({**base, "ok": ok, "rowCount": len(rows), "parsed": parsed, "expected": expected,
                            "explanation": explanation})
            continue
        # running
        prev, ok, parsed, expected, bad = c.get("opening"), True, None, None, []
        for idx, r in zip(c["rows"], rows):
            bal = r.get("balance")
            if prev is not None and _is_number(bal):
                want = round(prev + float(r.get("amount") or 0), 2)
                if not _close(want, bal):
                    ok, parsed, expected = False, want, round(bal, 2)
                    flipped = round(prev - float(r.get("amount") or 0), 2)
                    bad = [idx]
                    explanation = {"kind": "row-sign" if _close(flipped, bal) else "none", "rows": bad, "lines": []}
                    break
            prev = bal if _is_number(bal) else None
        results.append({**base, "ok": ok, "rowCount": len(rows), "parsed": parsed, "expected": expected,
                        "explanation": explanation if not ok else {"kind": "none", "rows": [], "lines": []}})
    return results


# --- the user's answers -----------------------------------------------------

_ADJUSTMENTS = ("flip", "exclude", "include", "dismiss")


def validate_adjustments(adjust) -> None:
    if not isinstance(adjust, dict) or set(adjust) - set(_ADJUSTMENTS):
        raise ValueError(f"adjustments must be a dict of {', '.join(_ADJUSTMENTS)}")
    for key in _ADJUSTMENTS:
        if not isinstance(adjust.get(key, []), list):
            raise ValueError(f"adjustments[{key!r}] must be a list")


def apply_adjustments(tables: dict, checks: list[dict], adjust: dict) -> None:
    """Applies the user's answers to a parse, in place:

      flip:    [{"table": str, "rows": [int]}]   reverse those rows' signs
      exclude: [{"table": str, "row": int}]      leave a row out
      include: [{"table": str, "check": int, "row": dict,
                 "line": {"check": int, "line": int} (optional)}]
               add a row - a not-read line, as suggest_row read it - and
               count it in that check; line names the not-read line it
               came from, which is then read
      dismiss: [{"check": int, "line": int}]
               a not-read line that is not a transaction

    Row indices refer to the parse before any adjustment; checks' rows
    are renumbered to match what is left."""
    validate_adjustments(adjust)
    for f in adjust.get("flip", []):
        rows = tables.get(f.get("table"), [])
        for r in f.get("rows", []):
            if 0 <= r < len(rows) and _is_number(rows[r].get("amount")):
                rows[r]["amount"] = -rows[r]["amount"]
    excluded = {}
    for e in adjust.get("exclude", []):
        excluded.setdefault(e.get("table"), set()).add(e.get("row"))
    for table, gone in excluded.items():
        rows = tables.get(table)
        if rows is None:
            continue
        remap, kept = {}, []
        for i, row in enumerate(rows):
            if i in gone:
                continue
            remap[i] = len(kept)
            kept.append(row)
        tables[table] = kept
        for c in checks:
            if c.get("table") == table:
                c["rows"] = [remap[r] for r in c["rows"] if r in remap]
    settled = set()  # not-read lines now read, or set aside
    for inc in adjust.get("include", []):
        table, row = inc.get("table"), inc.get("row")
        if table not in tables or not isinstance(row, dict):
            continue
        tables[table].append(row)
        ci = inc.get("check")
        if isinstance(ci, int) and 0 <= ci < len(checks) and checks[ci].get("table") == table:
            checks[ci]["rows"].append(len(tables[table]) - 1)
        if isinstance(inc.get("line"), dict):
            settled.add((inc["line"].get("check"), inc["line"].get("line")))
    for ref in adjust.get("dismiss", []):
        if isinstance(ref, dict):
            settled.add((ref.get("check"), ref.get("line")))
    for ci, c in enumerate(checks):
        if c.get("kind") == "unread":
            c["lines"] = [line for li, line in enumerate(c["lines"]) if (ci, li) not in settled]


# --- what may leave the machine --------------------------------------------

def shape(text: str) -> str:
    """A line with every letter and digit masked - its layout, not its words
    or numbers: "01/15 COFFEE 4.50" -> "99/99 AAAAAA 9.99"."""
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", text)))


def diagnostic_summary(results: list[dict]) -> list[dict]:
    """The checks as a privacy-safe diagnostic can carry them: kind, whether
    each held, what explained a failure, and how many rows and lines were
    involved - with each not-read line as a shape and its position. No
    labels (a section's label can be the account holder's words), texts,
    dates or amounts."""
    out = []
    for r in results:
        item = {"kind": r["kind"], "ok": bool(r["ok"]), "rowCount": int(r.get("rowCount") or 0),
                "explanation": r["explanation"]["kind"] if r["explanation"]["kind"] in _EXPLANATIONS else "none"}
        if r.get("lines"):
            item["lines"] = [{"page": line["page"], "line": line["line"], "shape": shape(line["text"])[:120]}
                             for line in r["lines"]]
        out.append(item)
    return out
