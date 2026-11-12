"""common.classify_account_type's table, for account names statements print.

Run:  make test  (or  .venv/bin/python -m pytest tests/test_account_types.py)
"""

import pytest

from institutions import common


# Bank of America's Advantage accounts are checking accounts whose names
# never say so, in full or as a statement shortens them, and so was
# SafeBalance Banking before it joined the family: a statement's "Adv Plus
# Banking" came out unclassified (11 Nov 2026). The Go side's table
# (account_type.go) reads them the same way.
@pytest.mark.parametrize("name", [
    "Adv Plus Banking", "ADV PLUS BANKING", "Adv. Plus Banking", "Advantage Plus Banking",
    "Bank of America Advantage Plus Banking®",
    "Adv SafeBalance Banking", "Advantage SafeBalance Banking", "Advantage Safe Balance Banking",
    "SafeBalance Banking",
    "Adv Relationship Banking", "Advantage Relationship Banking",
])
def test_bank_of_america_advantage_accounts_are_checking(name):
    assert common.classify_account_type(name, name) == "Checking"


# The family's savings account stays savings.
@pytest.mark.parametrize("name", ["Advantage Savings", "Bank of America Advantage Savings"])
def test_bank_of_america_advantage_savings_stays_savings(name):
    assert common.classify_account_type(name, name) == "Savings"
