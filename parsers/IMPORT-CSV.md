# OrbySystems import CSV

The format to convert your own financial records to, so OrbySystems can read
them into a spending or investment project: a spreadsheet you keep, a
database of an app OrbySystems has no parser for, anything that holds your
transactions or holdings.

OrbySystems' Records Converter (Tools) writes a prompt for the AI model you
use, from a description of your file that holds none of its values: the
model writes a script that converts your file to this format, and
OrbySystems runs the script with no network, on your machine, and checks
what it made before anything is imported. You can also write the file by
hand or with your own script.

`scripts/import_csv_schema.json` is the same format, for programs; this page
is its human-readable copy. The parsers that read it are
`scripts/csv_institutions/orbysystems_transactions_csv.py` and
`orbysystems_investments_csv.py`.

## The rules for every file

- Comma-separated, UTF-8, one header row, then one row per record.
- The header names the columns exactly as below: every required column, any
  of the optional ones, in any order, and no others. A file with another
  column is not read as the import CSV.
- Dates are `YYYY-MM-DD`.
- Numbers are plain: a minus sign for a negative, a dot for decimals, no
  currency symbol, no thousands separators (`-1234.56`).
- An amount is **negative when you are poorer**: money leaving the account.
  On a credit card a purchase is negative and a payment to the card
  positive.
- An account is its institution and the last four digits of its number
  (`account_last4`). Use the same institution name and digits your
  statements show, so your records join the account its statements fill.
  For an account with no number (cash), choose any four digits and keep them.
- A value out of form stops the import, naming its row and column; nothing
  is guessed.

Your records reach back before your statements, and the two overlap. For
each account, OrbySystems keeps only your rows dated before its first
statement: the statements cover the rest.

## `orbysystems-transactions.csv`: bank and card accounts

Every transaction of bank, credit-card and similar accounts.

| Column | Required | What |
|---|---|---|
| `date` | yes | The day of the transaction, `YYYY-MM-DD`. |
| `description` | yes | The payee or memo, as your records have it. Never empty. |
| `amount` | yes | Negative when money left the account, positive when it came in. |
| `account_type` | yes | One of `Checking`, `Savings`, `Money Market`, `CD`, `Credit Card`, `Loan`. |
| `institution` | yes | The bank or card issuer, e.g. `Chase`. |
| `account_last4` | yes | The account number's last four digits. |
| `account_name` | no | Your own name for the account, e.g. `Joint checking`. |
| `balance` | no | The account's balance after the transaction. |
| `currency` | no | The account's currency as a three-letter code, e.g. `EUR`. Empty for US dollars. |

```csv
date,description,amount,account_type,institution,account_last4,account_name
2019-01-05,Whole Foods,-84.20,Checking,Chase,4417,Joint checking
2019-01-15,Payroll,3200.00,Checking,Chase,4417,Joint checking
2019-01-07,Shell,-45.00,Credit Card,Citi,9921,
```

## `orbysystems-investment-transactions.csv`: investment accounts

Every transaction of brokerage, retirement and similar accounts.

| Column | Required | What |
|---|---|---|
| `date` | yes | The trade or settlement day, `YYYY-MM-DD`. |
| `description` | yes | What happened, e.g. `Bought 10 VTI`. Never empty. |
| `transaction_type` | yes | One of `buy`, `sell`, `dividend`, `interest`, `capital_gain`, `fee`, `tax`, `deposit`, `withdrawal`, `contribution`, `distribution`, `transfer_in`, `transfer_out`, `internal_transfer`, `rollover_in`, `rollover_out`, `other`. A reinvested dividend is two rows: the dividend, then a buy. `internal_transfer` is money or shares moving between two of your own accounts. |
| `amount` | yes | The cash it moved in the account: negative when cash left (a buy, a fee, a withdrawal), positive when cash came in (a sale, a dividend, a deposit), `0` when no cash moved. |
| `symbol` | no | The ticker, e.g. `VTI`. Empty for a cash-only row. |
| `quantity` | no | Shares or units: never negative on a buy, a sale or income. For shares moving with no cash (`transfer_in`, `transfer_out`, `internal_transfer`), negative when they left. |
| `price` | no | Price per share or unit. |
| `fees` | no | Commissions and fees on the transaction, as a positive number. |
| `account_type` | yes | One of `Brokerage`, `Traditional IRA`, `Roth IRA`, `Rollover IRA`, `SEP IRA`, `SIMPLE IRA`, `Inherited IRA`, `401(k)`, `Roth 401(k)`, `403(b)`, `457(b)`, `HSA`, `529`, `Trust`. |
| `institution` | yes | The broker or plan provider, e.g. `Fidelity`. |
| `account_last4` | yes | The account number's last four digits. |
| `account_name` | no | Your own name for the account. |
| `currency` | no | Three-letter code; empty for US dollars. |

```csv
date,description,transaction_type,amount,symbol,quantity,price,account_type,institution,account_last4
2020-01-02,Contribution,contribution,6000.00,,,,Roth IRA,Fidelity,3301
2020-01-02,Bought 10 VTI,buy,-1600.00,VTI,10,160.00,Roth IRA,Fidelity,3301
2020-03-31,VTI dividend,dividend,12.30,VTI,,,Roth IRA,Fidelity,3301
```

## `orbysystems-holdings.csv`: what investment accounts held

One row per security, per account, per day: one day or many.

| Column | Required | What |
|---|---|---|
| `as_of` | yes | The day the holding is as of, `YYYY-MM-DD`. |
| `symbol` | yes | The ticker; `CASH` for cash held in the account. |
| `quantity` | yes | Shares or units held; for `CASH`, the amount of cash. |
| `description` | no | The security's name. |
| `price` | no | Price per share or unit that day. |
| `market_value` | no | What the holding was worth that day. |
| `cost_basis` | no | What the holding cost in all. |
| `account_type`, `institution`, `account_last4`, `account_name`, `currency` | as above | |

```csv
as_of,symbol,quantity,price,market_value,account_type,institution,account_last4
2024-12-31,VTI,120,210.50,25260.00,Brokerage,Vanguard,7788
2024-12-31,CASH,1500.25,,,Brokerage,Vanguard,7788
```

## What the format leaves out

Your own categories, tags and notes: OrbySystems categorizes transactions
itself. Corporate actions (splits, mergers): write them as the trades they
amount to. Balances over time that aren't holdings, budgets and monthly
totals: they don't fit an account's transactions. Add such a file to a
General project instead, where Orby answers questions from it as it is.
