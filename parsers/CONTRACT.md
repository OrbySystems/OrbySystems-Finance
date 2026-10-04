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
change in `quantity`, `subtype` `"Out"` for the security leaving or
`"In"` for the one arriving, and — when the statement names the security
on the other side — its identifier in `related_security_id`.

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
`HSA`, …), or a default you pass. Import from a `csv_institutions/` module
too with `from institutions import common`.
