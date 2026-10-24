"""OrbySystems' import CSV for investment accounts: somebody's own records
of their trades and income, or of what they held, converted to OrbySystems'
format (IMPORT-CSV.md, import_csv_schema.json's "investment_transactions"
and "holdings"). One file is one of the two, told apart by its header.

The file is the person's records, not an institution's statement, so it
says so (RECORDS): where an account's statements or its institution's
exports cover the same days, theirs are the rows that count, and these fill
the rest (CONTRACT.md, "Where files overlap"). Every value is read exactly
as the schema gives it; one that isn't stops the read, naming the row.
"""

import import_csv
import parser_common

SUPPORT_TIER = parser_common.SUPPORT_TIER_VERIFIED

KIND = parser_common.KIND_BROKERAGE

RECORDS = True

# Recognised by its exact header, before any parser that might take a
# trades file for its own.
PRIORITY = 10

NOT_APPLICABLE = {
    "transaction_type:corporate_action": "The import CSV has no corporate actions; a split or merger is written as the trades it amounts to.",
}


def _which(header: list[str]) -> tuple[str, str]:
    """Which of the two files header is, or "" and why it is neither."""
    reasons = []
    for kind in ("investment_transactions", "holdings"):
        ok, reason = import_csv.matches(kind, header)
        if ok:
            return kind, reason
        reasons.append(reason)
    return "", "; ".join(reasons)


def detect(header: list[str], sample_rows: list[list[str]]) -> tuple[bool, str]:
    kind, reason = _which(header)
    return kind != "", reason


def parse(rows: list[dict[str, str]], csv_path: str) -> dict:
    kind, reason = _which(list(rows[0].keys()) if rows else [])
    if not kind:
        raise ValueError(reason or "the file has no rows")
    if kind == "holdings":
        holdings = [_holding(r) for r in import_csv.rows(kind, rows)]
        # Each holding is dated by its own as_of: a statement date would
        # override it, so the file has none.
        return {"institution": import_csv.statement_institution(holdings), "statementDate": "",
                "tables": {"brokerage_holdings": holdings}}
    trades = [_trade(r) for r in import_csv.rows(kind, rows)]
    parser_common.set_directions(trades)
    return {"institution": import_csv.statement_institution(trades), "statementDate": "",
            "tables": {"brokerage_transactions": trades}}


def _trade(r) -> dict:
    row = {
        "date": r.date("date"),
        "description": r.text("description"),
        "amount": r.number("amount"),
        "transaction_type": r.choice("transaction_type"),
        # The person's own word for it is the type itself: nothing else
        # says what the row was.
        "action": r.values["transaction_type"].replace("_", " ").capitalize(),
    }
    if symbol := (r.text("symbol") if "symbol" in r.values else ""):
        row["symbol"] = symbol.upper()
    for column, key in (("quantity", "quantity"), ("price", "price"), ("fees", "commission_and_fees")):
        if column in r.values:
            value = r.number(column)
            if value is not None:
                row[key] = value
    if row.get("commission_and_fees") is not None and row["commission_and_fees"] < 0:
        r._fail("fees", "is negative; write fees as a positive number")
    if row.get("quantity") is not None and row["quantity"] < 0 and row["transaction_type"] not in parser_common.DIRECTIONAL_TYPES:
        r._fail("quantity", f"is negative on a {row['transaction_type']}; only shares moving with no cash are signed")
    row.update(import_csv.account_fields(r))
    return row


def _holding(r) -> dict:
    symbol = r.text("symbol").upper()
    row = {
        "symbol": symbol,
        "quantity": r.number("quantity"),
        "price_as_of": r.date("as_of"),
    }
    for column, key in (("description", "description"),):
        if value := r.values.get(column, ""):
            row[key] = value
    for column, key in (("price", "price"), ("market_value", "current_value"), ("cost_basis", "cost_basis_total")):
        if column in r.values:
            value = r.number(column)
            if value is not None:
                row[key] = value
    if symbol == "CASH":
        # Cash held in the account, as the statement parsers write it.
        row["is_cash_equivalent"] = True
        row.setdefault("current_value", row["quantity"])
        row.setdefault("price", 1.0)
    row.update(import_csv.account_fields(r))
    return row
