# Parsers

Bank, brokerage, and CSV/spreadsheet statement parsers for OrbySystems' transaction
ingest. This directory
lets users contribute parsers for their own institutions for others to
use, and runs standalone — no OrbySystems checkout needed.

## Layout

```
scripts/
  bank_statement.py        PDF dispatcher (bank / credit-card / brokerage)
  csv_statement.py         CSV + .xlsx dispatcher
  parser_common.py         dispatch machinery + parse() IO-contract validation
  import_csv.py            reading OrbySystems' import CSV (and checking a file in it)
  import_csv_schema.json   the import CSV's columns, the one copy (IMPORT-CSV.md)
  app_export.py            reading a money app's export (amounts, dates, account names)
  vision_client.py         OpenAI-compatible vision client (check-image OCR)
  institutions/            PDF parser modules + common.py + check_ocr.py
  csv_institutions/        CSV/.xlsx parser modules
tests/                     standalone pytest suite + committed synthetic fixtures + generators
CONTRACT.md                the detect() / parse() IO contract
IMPORT-CSV.md              OrbySystems' import CSV: the format to convert your own records to
CLAUDE.md                  how to add a parser
```

## Investment statement coverage

The table below tracks the initial U.S. investment-institution coverage set.
Status is the parser's support tier (its `SUPPORT_TIER` line; see CONTRACT.md):
**verified** means at least one clean import of a real statement,
**provisional** means built from a real statement's layout and awaiting that
import, and **untested** means built from public samples or invented data
only. When an untested parser cannot read a statement, OrbySystems offers the
user its Statement Scrambler, so a scrambled copy can be sent to rebuild the
parser from a real layout. Tiers as of 2026-10-27; orby-core's
README_addparser.md has every parser's tier, generated from its Go catalog.

| Institution / statement family | Status | Current scope |
|---|---|---|
| Fidelity Investments / NetBenefits | **Verified** | Brokerage PDF, combined household and year-end variants, NetBenefits 401(k) Statement Details PDF (holdings only: names wrapped over two lines, each fund's class heading and label carried as `subtype` and `sector`, the company-stock fund typed `Stock`, stable-value funds without shares, sold-out funds dropped, checked against Account Totals; transactions come from the NetBenefits Transaction History CSV), and positions CSV |
| Charles Schwab | **Verified** | Retirement Plan Services quarterly 401(k) PDF validated against a production statement; retail brokerage PDF remains provisional |
| Vanguard | **Provisional** | Voyager and Personal Investor brokerage PDFs plus Custom Activity CSV/XLSX |
| Fidelity Rewards Visa (Elan Financial Services) | **Verified** | Monthly credit card statement, built from a scrambled real statement and confirmed by a clean import of a real one: account payments and fees, then each card's purchases, credits and fees, every card read as the one account; detail lines folded into the row above; statement checks for every section total, the Activity Summary's payments and credits and its purchases, fees and interest, Previous Balance + activity = New Balance, and lines not read. Demo statement: `fidelity-credit-card-synthetic-sample.pdf` |
| Citi credit cards | **Verified** | Monthly card statements, rebuilt from a scrambled real statement and confirmed by a clean import of a real one: the layout of Citi's own cards (a "Trans. date / Post date" table, a year-to-date block) and the Costco Anywhere Visa's, with credit balances, including the November 2025 layout whose labels pdfminer measures at a quarter of a point (`parser_common.page_text` reads them at the size of the values on their line; real microprint, narrow for its size, is left as it is) and whose rows, section headings and totals and table header can run into the rewards column beside them: words and figures that are not money (a year, a count, a percentage), or a line of its ledger with its own "+$" or "-$" figure; a heading in Citi's title case takes any column text after it. A row's amount is never taken from that column: a row level with any other figure is read by its own amount, the first on its line, and a charge printed in capitals with no date in Fees Charged or Interest Charged by its own, these tentative readings kept only when each is in one of the statement's checks and every check over them holds, and otherwise held for review. Two cards, the primary cardholder's and an authorized user's, are read as one account. A row outside the table is reported as not read; statement checks for the Account Summary's payments and credits and its other figures, the printed fee and interest totals, Previous balance + activity = New balance, and lines not read. Also Citi annual account summaries. Other Citi card layouts are claimed by `citi_credit_card_family` (untested), so their failure offers the Statement Scrambler. Demo statement: `citi-card-synthetic-sample.pdf` |
| Apple Card (Goldman Sachs Bank USA) | **Verified** | Monthly credit card statement, built from a scrambled real statement and confirmed by a clean import of a real one: the Payments table, the Transactions table with its Daily Cash column (a percentage and an amount before each row's amount; Daily Cash is not a row), returns printed negative, and the Interest Charged table, its interest added as a row dated on the closing date only when no row of its own carries it and the Total Balance is short by exactly that amount. The statement prints no card number, so every row's account is blank and the app asks which account it is. Statement checks for each table's total, Previous Total Balance + activity = Total Balance, and lines not read. Demo statement: `apple-card-synthetic-sample.pdf` |
| Sparkasse (any of the German Sparkassen) | **Verified** | Girokonto Kontoauszug (PDF), built from a scrambled real statement and confirmed by a clean import of a real one: the bookings between the opening "Kontostand am …, Auszug Nr." line and the closing "Kontostand am … um … Uhr" line, carrying on across pages under the repeated page header, each booking's description lines folded into it; German amounts and dates (`common.parse_german_amount`, `parse_german_date`); the account's last four digits from the IBAN; a running balance derived from the opening Kontostand; `currency_code` from the column header ("Betrag EUR", else EUR), left out on an app that predates the key. The fee and interest attachments are not read: their totals are bookings already. Statement checks for opening Kontostand + bookings = closing Kontostand, and every dated line that looks like a booking but was not read. Demo statement: `sparkasse-checking-synthetic-sample.pdf` |
| Star One Credit Union | **Provisional** | Member statement (PDF), built from a scrambled real statement: every savings and checking account under its "ACCT#" heading, carrying on across pages; each row's Deposit or Withdrawal column recovered from its balances (the first row's from the Beginning Balance, a row they can't place from the account's totals); a description's continuation lines folded into it; month-and-day dates ("SEP30") given the Period Ending's year; the account's last four digits from the member number and suffix. A loan or card account is reported, not read. Statement checks per account for Deposits/Credits, Withdrawals/Debits, Beginning Balance + activity = Ending Balance, and every dated line not read. Demo statement: `star-one-credit-union-synthetic-sample.pdf` |
| Technology Credit Union | **Provisional** | Member statement (PDF), built from a scrambled real statement that kept no word naming the credit union, so it is known by its layout ("Member Number:", "Starting Balance", "Ending Balance for") or the techcu domain: every savings and checking account between its Starting Balance and Ending Balance lines; each amount signed by its balance; a description's continuation lines folded into it; the account's last four digits. A loan or card account is reported, not read. Statement checks per account for Starting Balance + activity = Ending Balance, the Summary line's deposits and withdrawals, and every dated line not read. Demo statement: `technology-credit-union-synthetic-sample.pdf` |
| KeyPoint Credit Union | **Verified** | Statement of Account (PDF), built from a scrambled real statement and confirmed by a clean import of a real one (27 Oct 2026), known by its layout ("Statement of Account", the summary's labels over its figures, the "Post Date ... Withdrawal Deposit Balance" header) and KeyPoint's name or its web address (kpcu.com), which may be all a statement prints of it, each label read with or without the spaces between its words: every share and checking account under its "Account No." heading, carrying on across pages; each amount signed by its balance; the opening balance line, which moves no money, not a row; the account's type from its name, or the name as printed when it gives none; the account's last four digits. A loan or card account is reported, not read. Statement checks per account for Beginning Balance + activity = Ending Balance, deposits against Deposits + Dividend Paid, withdrawals against Withdrawals + Service Charges, and every dated line not read. Demo statement: `keypoint-credit-union-synthetic-sample.pdf` |
| Chase checking and savings (JPMorgan Chase Bank, N.A.) | **Verified** | Deposit statement (PDF), built from a scrambled real statement and confirmed by a clean import of a real one (27 Oct 2026), known by the bank's name or its web site (Chase.com) and its layout (an account's "CHECKING SUMMARY", "SAVINGS SUMMARY" or "MONEY MARKET SUMMARY", "TRANSACTION DETAIL", "DATE DESCRIPTION AMOUNT BALANCE"), each label read with or without the spaces between its words: every checking, savings and money market account, its transaction detail carrying on across pages; each amount signed as printed; an outgoing transfer's own date dropped from its description, and the lines under a row folded into it; a line with one of Chase's tiny markers run into it ("*end*transaction detail") read without it; the account's number from its holder line or, where that prints none, from the balance summary's row with its balances and a number no other account printed, else left for the app to ask. An account whose summary heading or summary does not read has its rows reported, never joined to another's. Statement checks per account for money in against the summary's positive lines, money out against its negative ones, Beginning Balance + activity = Ending Balance, the running balance, and every dated line, or line ending in a row's two figures, not read. The card statement is `chase_credit_card`'s. Demo statements: `chase-checking-synthetic-sample.pdf`, `chase-checking-marker-run-in-synthetic-sample.pdf` |
| Merrill / Merrill Edge | **Untested** | Existing CMA coverage plus provisional Wealth Management coverage; Trust remains unsupported |
| J.P. Morgan Wealth Management / Self-Directed Investing | **Provisional** | Investment Statement (PDF), rebuilt from a scrambled real statement; distinct from Chase banking and credit-card statements |
| Morgan Stanley Global Stock Plan Services | **Untested** | Participant share purchase quarterly statement with releases, sales, and proceeds disbursements; validated against one 2021 statement |
| Morgan Stanley Wealth Management | **Untested** | Wealth Management client statement, distinct from E*TRADE |
| E*TRADE from Morgan Stanley | **Provisional** | CLIENT STATEMENT layout (E*TRADE and Morgan Stanley at Work accounts, one or several per statement), rebuilt from a scrambled real statement: cash and bank deposit program, common stocks, options (short calls with OCC codes), ETFs and closed-end funds, with mutual-fund, fixed-income and preferred sections read by shape; cash-flow activity including option sells to open and option expirations/assignments as corporate actions, security transfers and card/check rows; statement checks for credits/debits, the cash-flow table, card/check rows and security transfers. Demo statement: `etrade-client-statement-synthetic-202607.pdf` |
| Wells Fargo Advisors / WellsTrade | **Untested** | Investment statement family, distinct from Wells Fargo checking statements |
| Edward Jones | **Untested** | Retail brokerage statement |
| Raymond James | **Untested** | Comprehensive statement; Executive Overview remains unsupported |
| Ameriprise | **Untested** | Consolidated brokerage statement |
| UBS Financial Services | **Untested** | Resource Management Account statement |
| LPL Financial | **Untested** | Quarterly investment statement |
| BNY Pershing / NetXInvestor | **Untested** | Core clearing statement; introducing-firm skins need validation |
| Interactive Brokers | **Untested** | Activity Statement PDF; Flex Query exports remain separate future work |
| Robinhood | **Untested** | Brokerage statement; retirement and activity CSV variants need validation |
| Empower Retirement / Empower Brokerage | **Untested** | Brokerage/IRA statement; employer-plan variants need examples |
| T. Rowe Price Brokerage / Funds | **Untested** | Pershing-cleared brokerage statement; direct-fund statements remain separate |
| Principal retirement / investments | **Untested** | Retirement-plan statement; plan-specific variants need examples |
| Apex Clearing statement family | **Untested** | Core clearing statement; introducing-broker skins need validation |

Coverage summary as of 2026-09-18: all 20 target families have an initial
parser, Fidelity and Vanguard have broad coverage, Schwab and Merrill have
partial plus provisional coverage, and the remaining families are provisional. Provisional
parsers intentionally use narrow detection and should be hardened when the
first real statement for each layout becomes available.

## Card and bank CSV exports

An institution's own CSV download, read as a statement is. All built from
published descriptions of the layout and **untested** until a real export
imports cleanly.

| Export | Current scope |
|---|---|
| American Express (`amex_csv`) | The US card activity download with "additional transaction details": charges negated to negative, every card's rows filed under the card the payments arrive on (one billing account), the issuer's Reference kept. The plain three-column download, and another country's (Town/City, Postcode), are not claimed. Demo files: `amex-*synthetic-sample.csv` |
| Capital One card (`capital_one_card_csv`) | Debit and Credit columns, Card No. as the account. Demo file: `capital-one-card-synthetic-sample.csv` |
| Capital One 360 (`capital_one_360_csv`) | Checking and savings activity, signed by Transaction Type, with the running Balance; the account type is asked. Its header is remembered rather than confirmed. Demo file: `capital-one-360-synthetic-sample.csv` |
| Discover card (`discover_card_csv`) | Purchases negated to negative; the file names no card, so the import asks. Demo file: `discover-card-synthetic-sample.csv` |
| Chase card (`chase_card_csv`) | Signed already; the card's four digits from the download's name (`Chase1234_Activity…`), else asked. Chase checking is `chase_checking_csv` (verified). Demo file: `Chase9921_Activity…CSV` |
| Citi card (`citi_card_csv`) | Debit a charge, Credit (written negative) a payment; pending rows left out; the card is asked. Demo file: `citi-card-synthetic-sample.csv` |
| Bank of America checking and savings (`bofa_checking_csv`) | The summary block above the transactions read past, the beginning-balance row left out, the running balance kept; the account and its type asked. Demo file: `bofa-checking-synthetic-sample.csv` |
| Bank of America card (`bofa_card_csv`) | The sign read from the rows (a payment says which way, `app_export.card_sign`); the card's digits from the download's name (`May2024_1234.csv`), else asked. Its header is remembered rather than confirmed. Demo file: `May2024_9921.csv` |
| Wells Fargo (`wells_fargo_csv`) | The headerless five-column download, every row read; the account type from the download's name (`Checking1.csv`, `CreditCard1.csv`); a card's sign read from its rows; the account asked. Demo files: `Checking1.csv`, `CreditCard1.csv` |

Each names its institution as that bank's PDF statement parser does, so a
CSV and a statement of one account file under the same account, and where
both cover the same days, the statement's rows count (CONTRACT.md, "Where
files overlap").

Fixtures: `tests/generators/gen-card-csv-samples.py` and `gen-bank-csv-samples.py`.

## Your own records: the import CSV and money apps' exports

These parsers read somebody's records rather than an institution's statement,
and say so (`RECORDS = True`, CONTRACT.md "Records"): where an account's
statements or its institution's exports cover the same days, theirs are the
rows that count, and the records fill the rest.

| Format | Status | Current scope |
|---|---|---|
| OrbySystems import CSV | **Verified** | The format in IMPORT-CSV.md: transactions (`orbysystems_transactions_csv`), and investment transactions or holdings (`orbysystems_investments_csv`), read exactly; a value out of form stops the read, naming its row and column. Demo files: `orbysystems-*-synthetic-sample.csv` |
| Tiller | **Untested** | Transactions sheet: rows filed by `Account #` and `Institution`; one with neither is asked about by its account's name |
| Mint | **Untested** | `transactions.csv` (unsigned amounts, debit/credit in Transaction Type) |
| YNAB | **Untested** | Register export, current and YNAB 4 (Outflow/Inflow, the plan's date and number format); starting balances and tracking accounts' adjustments left out |
| Monarch Money | **Untested** | Transactions export (signed amounts) |
| Quicken Simplifi | **Untested** | Transactions export (Date, Account, Status, Payee, Category, Tags, Notes, Amount) |
| Empower (Personal Capital) | **Untested** | Transactions export (Date, Account, Description, Category, Tags, Amount); investment accounts' rows are cash only |

Mint, YNAB, Monarch, Simplifi and Empower name each account but give no
number or bank for it: every row carries `account_name`, and OrbySystems asks
which account each name is. Demo files: `*-synthetic-sample.csv` from
`tests/generators/gen-records-samples.py`.

### Privacy-safe failure reports

Every parser module declares its support tier. When a parser recognizes a
statement but cannot parse its layout, the dispatcher returns a stable error
code and a structured diagnostic, carrying that tier, instead of exposing the
parser's raw exception. An untested parser's message also points the user to
a scrambled copy. OrbySystems' Add Source dialog lets the user inspect the
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
module-allowlisted field-presence flags and missing-field identifiers, and OrbySystems runtime version. A parser can
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
is never inspected to populate `missingFields`. A failure's message names the
fields in `missingFields` by their `DIAGNOSTIC_FIELDS` labels ("It could not
read the statement's Billing Period.").

Schema 5 says why a bundled parser missed a field without needing a copy of
the statement. `fieldLines` gives, for each `DIAGNOSTIC_FIELDS` label (or,
for a parser that declares none, the generic statement period, opening and
closing balance and account number), how the label was found (`exact`,
`normalized` once a no-break space or ligature is read as plain text,
`letters` with the spacing and doubled letters of some PDFs ignored, `split`
across two lines, or `missing`), its page in the PDF and its line, and that
line and the next as shapes: every amount, currency symbol and all, written
`<amount>`, so not even its size shows (a bare whole number, "9000", can't
be told from a year or a count, and keeps its digit count); every other
letter, mark and digit, of any script, masked; a private-use or unassigned
code point `<pua>`; and every other character but printable ASCII, and a
dollar sign, written as its code point
(`parser_common.line_shape`: `Billing Period: 10/15/25-11/14/25` becomes
`Aaaaaaa Aaaaaa: 99/99/99-99/99/99`, `New balance $1,234.56` becomes
`Aaa aaaaaaa <amount>`). A label far along its line is shaped from just
before it (`column`). The missing fields' lines come first in a budget that
keeps a report small; one still too long for a GitHub issue's URL is copied,
and the issue asks for it to be pasted.
`declinedParsers` names the bundled parsers for the same institution that
were tried first and did not claim the statement; `textStats` counts lines,
characters per page, unmapped `(cid:N)` glyphs, letters, marks and digits
outside ASCII (compatibility forms such as ligatures apart) and private-use
or unassigned code points;
and `unusualChars` counts, by code point, the characters outside printable
ASCII that are neither letters nor digits. A letter or digit is never named.
OrbySystems drops any field line that is not a shape, and caps each of
these, before a report can carry them. Reports must never contain the statement or extracted text,
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

## How OrbySystems uses these parsers

OrbySystems vendors this repository as a git submodule and imports its
`parsers` Go package. The package `//go:embed`s `scripts/`, `tests/`, and
`demo/` through `embed.go`.
At runtime OrbySystems writes the tree out and runs the dispatchers in a
sandbox. Users can also drop extra parser `.py` files into
`~/.orby/ingest/parsers/` without touching either repo — see `CLAUDE.md`.
