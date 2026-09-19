# orby-parsers

Bank, brokerage, and CSV/spreadsheet statement parsers for
[Orby](https://github.com/edgexr/orby)'s transaction ingest. This repo
lets users contribute parsers for their own institutions for others to
use, and runs standalone — no Orby checkout needed.

## Layout

```
scripts/
  bank_statement.py        PDF dispatcher (bank / credit-card / brokerage)
  csv_statement.py         CSV + .xlsx dispatcher
  parser_common.py         dispatch machinery + parse() IO-contract validation
  vision_client.py         OpenAI-compatible vision client (check-image OCR)
  institutions/            PDF parser modules + common.py + check_ocr.py
  csv_institutions/        CSV/.xlsx parser modules
tests/                     standalone pytest suite + committed synthetic fixtures + generators
CONTRACT.md                the detect() / parse() IO contract
CLAUDE.md                  how to add a parser
```

## Investment statement coverage

The table below tracks the initial U.S. investment-institution coverage set.
“Broad” means the parser has coverage for multiple known statement variants.
“Partial” means only the named statement family is covered. “Provisional” means
the parser and synthetic regression statement are present, but the parser still
needs validation against a safely redacted production statement before it
should be considered production-hardened.

| Institution / statement family | Status | Current scope |
|---|---|---|
| Fidelity Investments / NetBenefits | **Broad** | Brokerage PDF, combined household and year-end variants, NetBenefits 401(k) PDF (including omitted zero-value rows, signed zero-net Exchange rows, and both dividend reconciliation conventions), and positions CSV |
| Charles Schwab | **Partial + provisional** | Retirement Plan Services quarterly 401(k) PDF validated against a production statement; retail brokerage PDF remains provisional |
| Vanguard | **Broad** | Voyager and Personal Investor brokerage PDFs plus Custom Activity CSV/XLSX |
| Merrill / Merrill Edge | **Partial + provisional** | Existing CMA coverage plus provisional Wealth Management coverage; Trust remains unsupported |
| J.P. Morgan Wealth Management / Self-Directed Investing | **Provisional** | Investment statement family, distinct from Chase banking and credit-card statements |
| Morgan Stanley Wealth Management | **Provisional** | Wealth Management client statement, distinct from E*TRADE |
| E*TRADE from Morgan Stanley | **Provisional** | Self-directed brokerage statement |
| Wells Fargo Advisors / WellsTrade | **Provisional** | Investment statement family, distinct from Wells Fargo checking statements |
| Edward Jones | **Provisional** | Retail brokerage statement |
| Raymond James | **Provisional** | Comprehensive statement; Executive Overview remains unsupported |
| Ameriprise | **Provisional** | Consolidated brokerage statement |
| UBS Financial Services | **Provisional** | Resource Management Account statement |
| LPL Financial | **Provisional** | Quarterly investment statement |
| BNY Pershing / NetXInvestor | **Provisional** | Core clearing statement; introducing-firm skins need validation |
| Interactive Brokers | **Provisional** | Activity Statement PDF; Flex Query exports remain separate future work |
| Robinhood | **Provisional** | Brokerage statement; retirement and activity CSV variants need validation |
| Empower Retirement / Empower Brokerage | **Provisional** | Brokerage/IRA statement; employer-plan variants need examples |
| T. Rowe Price Brokerage / Funds | **Provisional** | Pershing-cleared brokerage statement; direct-fund statements remain separate |
| Principal retirement / investments | **Provisional** | Retirement-plan statement; plan-specific variants need examples |
| Apex Clearing statement family | **Provisional** | Core clearing statement; introducing-broker skins need validation |

Coverage summary as of 2026-09-18: all 20 target families have an initial
parser, Fidelity and Vanguard have broad coverage, Schwab and Merrill have
partial plus provisional coverage, and the remaining families are provisional. Provisional
parsers intentionally use narrow detection and should be hardened when the
first real statement for each layout becomes available.

### Privacy-safe failure reports

Provisional parser modules declare `SUPPORT_TIER = "provisional"`. When a
parser recognizes a statement but cannot parse its layout, the dispatcher
returns a stable error code and a structured diagnostic instead of exposing
the parser's raw exception. Orby's Add Source dialog lets the user inspect the
complete diagnostic before copying it or opening a GitHub issue; nothing is
sent automatically.

All 20 primary investment-statement PDF families in the table above now
declare the repair-grade diagnostic contract. The sixteen provisional profile
parsers share one diagnostic collector; Fidelity Investment Report, Fidelity
NetBenefits, Schwab retail, Schwab Retirement Plan Services, Vanguard
brokerage, and Edward Jones add their own format-specific fields where needed.
Contract tests intentionally break every
primary family and verify that the resulting report contains structural
signals and counts without statement values. Legacy sibling formats and CSV/
XLSX exports retain the baseline diagnostic envelope unless their own module
declares the repair-grade fields.

Reportable diagnostics may contain the parser/institution identifier, support
tier, failure stage, page/row counts, public section-presence flags, stable
module-allowlisted field-presence flags and missing-field identifiers, and Orby runtime version. A parser can
also attach allowlisted category signals, structural row counts, a parser
revision, and the direction (but never the amount) of a reconciliation gap.
This is enough to distinguish common missing flows such as contributions,
withdrawals, transfers, loans, fees, or distributions while keeping raw row
labels private. Schema 3 can additionally report only allowlisted financial
vocabulary found in an otherwise unclassified label, plus positive/negative/
zero label counts; all other words are discarded. Parsers
that can identify a missing control should raise `ParserDiagnosticError` and
declare every reportable identifier and static public label in
`DIAGNOSTIC_FIELDS`, `DIAGNOSTIC_SIGNALS`, `DIAGNOSTIC_COUNTS`, and
`DIAGNOSTIC_TERMS`; raw exception text
is never inspected to populate `missingFields`. Reports must never contain the statement or extracted text,
filename/path, names, account identifiers, dates, balances or amounts,
security identifiers, raw PDF metadata, document hashes, or raw exception
messages. Several parsers intentionally include exact rejected rows and
control totals in their internal exceptions, so callers must report only the
dispatcher-provided `diagnostic` object.

## Running the tests

```
make test          # provisions .venv (pdfplumber, openpyxl, pytest, pillow), runs pytest
make regen-fixtures  # rebuild every committed synthetic fixture from its generator
```

Committed fixtures are wholly synthetic. Tests over redacted real
statements skip themselves when the (gitignored) files aren't present.

## Trying a parser by hand

```
python scripts/bank_statement.py <statement.pdf>            # parse -> JSON
python scripts/bank_statement.py <statement.pdf> --dump-text  # raw extracted text
python scripts/csv_statement.py  <export.csv|.xlsx> --dump-rows
```

## How Orby uses this repo

Orby vendors this as a git submodule at `submodules/parsers` and
`//go:embed`s `scripts/` + `tests/` through a small Go shim (`embed.go`).
At runtime Orby writes the tree out and runs the dispatchers in a
sandbox. Users can also drop extra parser `.py` files into
`~/.orby/ingest/parsers/` without touching either repo — see `CLAUDE.md`.
