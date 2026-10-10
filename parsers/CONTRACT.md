# Parser IO contract

Every parser under `scripts/institutions/` (PDF) and
`scripts/csv_institutions/` (CSV / `.xlsx`) exposes a `detect()` / `parse()`
pair. The dispatchers (`scripts/bank_statement.py`,
`scripts/csv_statement.py`) auto-discover every parser file in their
directory and try each one's `detect()` in `(PRIORITY, filename)` order,
first match wins, then call that parser's `parse()`. The result is
strictly validated by `scripts/parser_common.py`
(`validate_parse_result` / `validate_multi_table_parse_result`) before it
is printed as JSON — an extra, missing, or wrong-typed key fails loudly
with a message naming the parser and field, never silently as zeroed
data. OrbySystems re-checks the same shape on the Go side
(`json.Decoder.DisallowUnknownFields`).

Every parser also declares its **support tier** on a line of its own,
`SUPPORT_TIER = parser_common.SUPPORT_TIER_<TIER>`: `verified` (at least
one clean import of a real statement), `provisional` (built from a real
statement's layout, awaiting that import), `untested` (public samples or
invented data only) or `demo` (an invented institution). The dispatcher
reports it with every failure, and OrbySystems decides from it what to
offer the user. A parser that declares none is treated as untested.

A bundled parser may also declare `PARSER_REVISION`, an integer from 1
raised whenever the parser changes. A failure's diagnostic reports it as
`parserRevision`, so a report says which revision ran. A dropped-in
parser's revision is not reported.

**A dropped-in parser that claims a document and then fails is passed
over** (`parser_common.read_claimed`). The document is read as if that file
weren't installed: the bundled parser it replaced, if any, claims it in its
slot, then the parsers after it, and the first match reads it. The
dispatcher lists every drop-in it passed over under `failedExtraParsers`,
beside the diagnostic and never inside it:
`[{"file": "<name>.py", "code": ..., "stage": ...}]`. The list appears on a
successful read and on a failure, and the file name is the user's own. When
nothing after the drop-in claims the document, the failure is the drop-in's.

A bundled parser that fails still ends the read, because the parsers after
it are less specific readings. For example, `bofa_checking`'s `detect()`
also claims the combined statements `bofa_checking_combined` reads.
Nothing is passed over when one parser is asked for, with
`--expected-parser` or `--only-extra-parser`.

**A dropped-in file that doesn't load is named too.** A syntax error, a
relative import, a module the sandbox doesn't have, `@dataclass`, or no
`detect()`/`parse()` pair: the file is skipped, and a bundled parser of its
name goes on reading in its place. Every read lists such files - on a
match, on a failure and when nothing was detected - under
`unloadedExtraParsers`, beside the diagnostic and never inside it:
`[{"file": "<name>.py", "code": "PARSER_LOAD_...", "stage": "load", ...}]`.
`code` is `PARSER_LOAD_SYNTAX`, `PARSER_LOAD_RELATIVE_IMPORT`,
`PARSER_LOAD_MISSING_MODULE`, `PARSER_LOAD_IMPORT`, `PARSER_LOAD_DATACLASS`,
`PARSER_LOAD_NO_DETECT_PARSE` or `PARSER_LOAD_ERROR`. Where known, `line`
is the line in the file, `module` the module it could not import, `error`
the exception's class, and `replaces` the bundled parser reading in its
place. The exception's text is never in it.

`bank_statement.py --check-extra-parsers --extra-parsers-dir <dir>` prints
just that list for the whole folder, and reads nothing. When the parser
`--expected-parser` or `--only-extra-parser` names is one that doesn't
load, the read fails at once, before anything is detected: the diagnostic
has `stage: "load"` and `parserId: "external_parser"`, and the message,
for whoever is building or trying the file, quotes the error.

## `detect()`

| dispatcher | signature |
|---|---|
| `bank_statement.py` (PDF) | `detect(head_text: str) -> tuple[bool, str]` |
| `csv_statement.py` (CSV/xlsx) | `detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]` |

Returns `(matched, reason)`. `reason` is a short diagnostic — on a match
what was found, on a non-match why (which marker/column was missing) — so
a rejected document's output can explain why nothing recognized it. A
`detect()` that raises is treated as an ordinary non-match.

## `parse()` — `KIND_BANK` (the default)

Checking / savings / credit-card statements and CSV exports. A module
does **not** opt in; this is the default.

```python
def parse(pages_text: list[str], pdf_path: str, vision: dict | None) -> dict   # PDF
def parse(rows: list[dict[str, str]], path: str) -> dict                        # CSV
```

Result — **exactly** these keys:

| key | type | notes |
|---|---|---|
| `institution` | `str` | may be `""` |
| `statementDate` | `str` | `""` or `YYYY-MM-DD` |
| `transactions` | `list[dict]` | may be empty |
| `needsVisionOcr` | `bool` | optional, default `False`; PDF only — check images could be OCR'd but no `vision` was supplied |
| `checks` | `list[dict]` | optional — the statement's own arithmetic; see "Checks" below |

There is **no** top-level `account` / `accountType` — one statement can
cover several accounts, so they live per transaction.

Each `transactions[]` entry — **exactly**:

| key | type | notes |
|---|---|---|
| `date` | `str` | `YYYY-MM-DD` |
| `description` | `str` | non-empty after `.strip()` |
| `amount` | `int`/`float` | signed — see below |
| `balance` | `int`/`float`/`None` | key required, value may be `null` |
| `account` | `str` | last 3–4 digits, or `""` |
| `accountType` | `str` | e.g. `Checking` / `Savings` / `Credit Card`, or `""` |
| `reference` | `str` | optional — the issuer's own reference number |
| `institution` | `str` | optional — only if it differs from the statement's primary |
| `provider_account_id` | `str` | optional — fullest account identifier disclosed |

`vision`, when not `None`, is `{"endpoint", "model", "api_key"}` for an
OpenAI-compatible vision-capable chat endpoint (`check_ocr.py` uses it to
read embedded check images). `pdf_path` is the original file for a parser
that must re-open the PDF itself. Most parsers ignore both.

## `parse()` — `KIND_BROKERAGE`

A brokerage statement commonly has several sections worth structured
data. The module sets `KIND = parser_common.KIND_BROKERAGE` at module
scope and returns a `tables` dict instead of `transactions`:

```python
KIND = parser_common.KIND_BROKERAGE
def parse(pages_text: list[str], pdf_path: str) -> dict   # no vision / needsVisionOcr
```

Result — **exactly** `institution` (`str`), `statementDate` (`str`),
`tables` (`dict[str, list[dict]]`), and optionally `checks` (see "Checks"
below). `tables` keys must be a subset of:

- **`cash_transactions`** — identical row shape to a `KIND_BANK`
  `transactions[]` row.
- **`brokerage_transactions`** — required: `date`, `description`,
  `amount`, `account`, `accountType`. Optional: `action`,
  `transaction_type`, `subtype`, `symbol`, `security_id`,
  `security_id_type`, `quantity`, `price`, `commission_and_fees`,
  `realized_gain`, `realized_gain_term`, `related_security_id`,
  `currency_code`, `transaction_time`, `status`, `reference`,
  `cancel_reference`, `provider_account_id`, `institution`,
  `amount_missing`. `amount_missing` (`bool`) marks a row whose statement
  printed no cash value — a dash rather than `0.00`: set `amount` to `0.0`
  and `amount_missing` to `true`, and OrbySystems flags the row for the
  user to value.
- **`brokerage_holdings`** — required: `symbol`, `account`,
  `accountType`. Optional: `description`, `quantity`, `price`,
  `current_value`, `cost_basis_total`, `average_cost_basis`,
  `percent_of_account`, `estimated_annual_income`, `estimated_yield`,
  `type`, `subtype`, `security_id`, `security_id_type`, `cusip`, `isin`,
  `sedol`, `figi`, `currency_code`, `price_as_of`, `price_time`,
  `vested_quantity`, `vested_value`, `position_type`,
  `market_identifier_code`, `sector`, `industry`, `is_cash_equivalent`,
  `tax_lots_json`, `provider_account_id`, `institution`.

Any of the three tables may be omitted or empty.

A share movement with no cash behind it (merger, assignment, expiry,
share-lending adjustment) is a `brokerage_transactions` row with
`transaction_type = "corporate_action"`, `amount` `0.00`, the share
change in `quantity` (its sign is not authoritative; see "Sign of `quantity`"),
`corporate_event` saying which kind (below), `subtype` `"Out"` for the security
leaving or `"In"` for the one arriving, and — when the statement names the
security on the other side — its identifier in `related_security_id`.

**Every `corporate_action` row sets `corporate_event`**, from a closed list in
`scripts/transaction_vocabulary.json` (`corporate_events`); `parse()` rejects
any other value, and rejects the field on a row that is not a corporate
action. It says what the *statement shows*, never a guessed cause:

| kind | values |
|---|---|
| stated | `split`, `reverse_split`, `spinoff`, `merger_in`, `merger_out`, `conversion_in`, `conversion_out`, `expired`, `assigned`, `exercised`, `cash_in_lieu` |
| observed (shape only) | `share_distribution` (shares arrive, no cash, no stated reason), `share_exchange_in`, `share_exchange_out` |
| other | `other` |

The issuer's word stays in `action` for display; nothing downstream matches
on it, because the same word means different things at different
institutions (Fidelity prints a split as a bare `Distribution`; a cash
`Distribution` is `transaction_type: distribution`, a different field). When
a statement does not say what a share movement was, use the observed kind:
OrbySystems resolves it after import from the surrounding data (adjacent
holdings snapshots) or asks the user, and keeps that answer apart from this
field so a re-parse never overwrites it. `parser_common.label_event(label,
direction)` reads a stated event out of an issuer's label for a parser that
only has the label; `parser_common.set_corporate_events(rows)` applies it to
every row that has none (else `other`).

A parser that predates the field (a user's own) still works: OrbySystems
derives the value from the row and warns at import. A bundled parser is held
to it by `tests/test_transaction_vocabulary.py`.

**A transfer's direction is the sign of the row**: its `amount`, else its
`quantity` when no cash moves (positive in, negative out). That is the one
source; no field repeats it. `transfer_in` / `transfer_out` also name the
direction in the type, and `tests/test_transaction_vocabulary.py` fails a
bundled parser whose type disagrees with the sign. `internal_transfer` is the
*scope* (both sides are the user's own accounts, which the linker and the
performance figures rely on) and carries no direction of its own.

**Sign of `quantity`.** On a trade or income row (`buy`, `sell`, `redemption`,
`dividend`, ...) `quantity` is unsigned (a sale's quantity is positive): the
type and the signed `amount` say which way it went. On a share movement that is not a trade it is signed,
positive arriving and negative leaving, because there may be no cash for
`amount` to carry the direction: `transfer_in` / `transfer_out`, and an
`internal_transfer` with no cash. On a `corporate_action` the sign is not
authoritative, since contracts and some issuers print it unsigned (a parser
that does print the two legs of a merger signed lets OrbySystems pair them by
their cancelling quantities); the direction is `corporate_event` (a `_in` / `_out` event, or one that implies it
— `share_distribution` and `spinoff` arrive, `expired`, `assigned` and
`exercised` leave, `corporate_event_directions` in the vocabulary) and
`subtype`. `parse()` rejects a `subtype` of `"In"` / `"Out"` that contradicts
its event; the event is authoritative and `subtype` is a display hint.

### Strict mode and backwards-compatible mode

The rules added with `corporate_event` and the direction / unsigned-quantity
contract (a `corporate_action` sets `corporate_event`; a transfer or corporate
action says `In` / `Out` in `subtype`, agreeing with its type, event and amount;
`quantity` is never negative) are enforced in two ways:

| mode | when | a broken rule is |
|---|---|---|
| **strict** (`--strict`) | writing and testing a parser: the test suite, a build's trial (`TrialParseCandidate`) | an error that fails `parse()`, naming the row |
| **backwards compatible** (the default) | importing a statement | a warning on the import, one line per rule with the row count; a `corporate_event` that is invalid or on the wrong row is dropped so the importer derives it |

So a parser written before these rules (a user's own) keeps importing, and the
import shows what to fix. `tests/conftest.py`'s `run_statement` passes
`--strict`, and `tests/test_transaction_vocabulary.py` fails if any bundled
parser draws a warning in the default mode. Rules that existed before - an
unknown `transaction_type`, a wrong-typed field - are errors in both.

### Declaring what a format cannot contain: `NOT_APPLICABLE`

A module may declare vocabulary terms that **cannot occur** in the statements it
reads, each with a reason in words a user can read:

```python
NOT_APPLICABLE = {
    "option:*": "A 401(k) plan holds no option contracts.",
    "corporate_event:split": "...",
}
```

A term is `<field>:<value>` or `<field>:*`, where field is `transaction_type`,
`corporate_event` or `option` (`call`, `put`, `expired`, `assigned`,
`exercised`). Data Metrics then says **not applicable** (with the reason)
instead of **not seen**. Declare only what the *format* cannot hold; never
something the parser merely does not read - that is a gap, and "not seen" is
how it gets noticed. A term is not applicable to an institution only when every
parser that has read that institution declares it. An unknown term is dropped,
and `tests/test_transaction_vocabulary.py` fails a bundled module that declares
one.

### `action` and `transaction_type` are not the same kind of field

| field | what it is | governed? |
|---|---|---|
| `action` | the **issuer's own word**, for display. A CSV parser passing the export's column through verbatim is legitimate. | free text |
| `transaction_type` | the **machine-readable classification**. | closed vocabulary — `parse()` rejects anything else by name |

The vocabulary lives in `scripts/transaction_vocabulary.json`, which is the
single copy: `parser_common.py` validates against it and OrbySystems reads the same
file out of the embedded scripts tree to build the SQL that decides what
counts as money moving.

**This matters most for money entering or leaving an account**, because every
growth figure OrbySystems reports is computed net of it. A contribution that nothing
recognises as a contribution is not an error and not a gap — it is reported
as *investment gain*, and the account appears to have earned its own
deposits. Detection used to be two words (`action IN ('Deposit',
'Withdrawal')`) plus one convention that four parsers happened to follow, so
a parser calling it `Contribution`, `Rollover`, `Journal` or `Direct Deposit`
produced exactly that, silently.

So: **if a row moves money in or out, set `transaction_type`.** The flow
classes are `deposit`, `withdrawal`, `contribution`, `distribution`,
`transfer_in`, `transfer_out`, `internal_transfer`, `rollover_in`,
`rollover_out`. Use `internal_transfer` when the two sides are both the
user's own accounts — those net to zero across a portfolio and must not
count as contributions to it.

The vocabulary also lists issuer words per class, honoured on a row that
carries no `transaction_type`. That list is a safety net, not the guarantee.
What actually closes the hole is that an **unrecognised word is reported**:

- a row that sets `transaction_type` is classified, and its `action` is never
  checked — a corporate action's label is lifted verbatim out of the
  statement, so checking it would be wrong;
- a row that sets none is classified by `action` alone, so that word must
  appear somewhere in the vocabulary. For a bundled parser,
  `tests/test_transaction_vocabulary.py` fails CI. For a user's own parser,
  OrbySystems warns at import that those rows are not being counted as money moving.

Adding a word is one line of JSON — in `flows[].actions` if it means money
moved, in `non_flow_actions` if it does not (and under `non_flow_classes`
if any figure should count it). Setting `transaction_type` is better,
because then the question never arises.

### What OrbySystems reads besides money movement

**Set `transaction_type` on every row, not only on flows.** OrbySystems
resolves each row to one `transaction_types` value: the row's own
`transaction_type`, else the class its `action` is listed under
(`flows[]` or `non_flow_classes` in the vocabulary), else nothing. Every
figure reads that resolved class, never the `action` word:

| figure | reads |
|---|---|
| income by security, the income view | `dividend`, `interest` |
| tax lots | `buy` (a reinvestment is a `buy`), `sell` |
| performance charges (`v_period_return`) | `fee` (margin interest is a `fee`) |
| contributions and withdrawals | the flow classes above |

So "Qualified Dividend" with `transaction_type: "dividend"` is a dividend.
An unclassified "Qualified Dividend" is in none of these figures.

**Symbols.**
- `symbol` is the ticker whenever the statement prints one for that
  security anywhere, holdings included.
- When it prints none, leave `symbol` empty and put the CUSIP in
  `security_id` with `security_id_type: "CUSIP"`. OrbySystems resolves it to
  a ticker by name where it can, and keys it by CUSIP until then. Don't
  put a CUSIP in `symbol`.
- An option contract's `symbol` is its OCC code: the underlying's ticker,
  the expiry as `YYMMDD`, `C` or `P`, then the strike, e.g.
  `AVGO260918C420`. OrbySystems recognises an option by that shape alone. A
  contract row carrying anything else is left out of every option figure,
  and OrbySystems warns at import.

**Option expiries and assignments** are corporate actions:
- `transaction_type: "corporate_action"`, `subtype: "Out"`, `amount` `0.00`;
- `symbol` is the contract's OCC code;
- `action` names the event. Any label containing the word *expired*,
  *expiration* or *expiry*, or *assigned* or *assignment*, in any case,
  will do ("Expired Out", "Option Expiration"); see
  `corporate_action_events` in the vocabulary.

The option figures use those rows to find where a contract ended.

**Charges reported only in the summary.** Some statements report the
period's charges as a summary line rather than as rows (Fidelity's
"Transaction Costs, Fees & Charges"). Emit them as one row:
`transaction_type: "fee"`, `action: "Fee"`, dated the statement's closing
date. Performance books fee rows as charges, which is what makes a
period's investment gain agree with the statement's own change in
investment value.

**Realised gains.** When the statement prints a gain or loss per
disposal, put it in `realized_gain`, signed (a loss is negative), and set
`realized_gain_term` to `"Short-term"` or `"Long-term"`.

`bank_statement.py` normalizes a `KIND_BANK` match into the same envelope
(`tables = {"cash_transactions": transactions}`) before printing, so
consumers see one output shape regardless of which kind matched.

## Checks: the statement's own arithmetic

A statement prints figures about itself — a section's total, the opening
and closing balance, a running balance down the rows. **Report them as
`checks`, and do not raise when they disagree with the rows you read.**
`checks` is an optional top-level key, for both kinds, alongside
`transactions` or `tables`:

| Check | Keys | Holds when |
|---|---|---|
| `sum` | `label`, `table`, `rows`, `expected` | the rows' amounts add up to `expected` |
| `balance` | `label`, `table`, `rows`, `opening`, `closing` | `opening` + the rows' amounts = `closing` |
| `running` | `label`, `table`, `rows`, `opening` (optional) | each row's `balance` = the previous row's (or `opening`) + its `amount` |
| `unread` | `label`, `lines` (`[{page, line, text}]`) | there are no lines: a line inside a transaction section that looked like a row but could not be read |

`table` names the output table (`cash_transactions` for a `KIND_BANK`
parser) and `rows` index its rows. Every figure is in the output's own sign
convention (below): whatever a credit-card parser negates, it negates in
its checks too. `label` is the statement's own name for the section;
it is shown to the user on their own machine and never leaves it.

The dispatcher evaluates the checks against the rows (`scripts/statement_checks.py`)
and prints `checkResults`. When every check holds, the import is clean,
and one clean import of a real statement is what makes a provisional
parser verified. A failed check does not fail the parse. OrbySystems holds
the import and asks the user, using an explanation worked out from the
numbers: a section read with its sign reversed, one row with its sign
reversed, a row that should not count, lines that were not read, or
nothing found. The answers come back as `--adjust`, the parse runs again
with them, and the checks are evaluated again. `chase_credit_card.py` is
the worked example. Older parsers that still raise on a mismatch work
as before: the import fails with a diagnostic, and no questions are
asked.

The dispatcher also prints `parser` (`id`, `tier`, `bundled`): which
parser read the statement and its support tier.

## Amount sign convention

`amount` is signed by how the transaction affects the money the account
holder actually has, the same way across every account type — **not** by
how the issuing statement's own balance figure moves.

- **Negative** = poorer: withdrawals, fees, credit-card
  purchases/charges.
- **Positive** = richer: deposits, credit-card payments/credits.

For a credit-card parser, parse in the statement's own printed sign
(charges positive, payments negative), then negate every `amount` and
`balance` as the final step (`common.negate_amounts_and_balances`), and
report `Previous Balance + sum == New Balance` as a `balance` check in the
negated convention.

## Shared helpers (`scripts/institutions/common.py`)

`parse_amount`, `last4_digits`, `apply_running_balance`,
`negate_amounts_and_balances`; `tag_account`, which fills in `account` and
`accountType` on every row that has none (the usual single-account
statement); and `classify_account_type`, which turns an account title or
product name into the label OrbySystems uses (`Checking`, `Roth IRA`,
`HSA`, …), or a default you pass. Import it as `from institutions import
common`, from a `csv_institutions/` module too — never `from . import
common`, which fails when the module is loaded from the user's parsers
folder (CLAUDE.md).
