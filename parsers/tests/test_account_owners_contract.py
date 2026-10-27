"""Named account registrations on bank and brokerage parser results."""

import pytest

import parser_common


def _result(brokerage=False):
    result = {"institution": "Example Bank", "statementDate": "2026-01-31"}
    if brokerage:
        result["tables"] = {}
    else:
        result["transactions"] = []
    return result


@pytest.mark.parametrize("brokerage", [False, True])
def test_account_owners_are_optional_and_validated(brokerage):
    validate = (parser_common.validate_multi_table_parse_result if brokerage
                else parser_common.validate_parse_result)
    result = _result(brokerage)
    validate(result, "example")
    result["accountOwners"] = [{"account": "1234", "ownerName": "Alex Rivera"},
                               {"institution": "Other Bank", "account": "5678", "ownerName": "The Rivera Trust"}]
    validate(result, "example")


@pytest.mark.parametrize("owners", [
    {"account": "1234", "ownerName": "Alex Rivera"},
    [{"account": "12345678", "ownerName": "Alex Rivera"}],
    [{"account": "1234", "ownerName": ""}],
    [{"account": "1234", "ownerName": "Alex Rivera", "unexpected": "x"}],
    [{"account": "1234", "ownerName": "Alex Rivera"},
     {"account": "1234", "ownerName": "Jordan Rivera"}],
])
def test_invalid_account_owners_are_rejected(owners):
    result = _result()
    result["accountOwners"] = owners
    with pytest.raises(ValueError, match="accountOwners"):
        parser_common.validate_parse_result(result, "example")


def test_explicit_single_account_owner_is_inferred_without_address_guessing():
    result = _result()
    result["transactions"] = [{"account": "1234"}]
    parser_common.infer_explicit_account_owner(
        result, ["123 Main Street\nAccount holder: Alex Rivera\nAccount # 1234"])
    assert result["accountOwners"] == [{"account": "1234", "ownerName": "Alex Rivera"}]

    ambiguous = _result()
    ambiguous["transactions"] = [{"account": "1234"}, {"account": "5678"}]
    parser_common.infer_explicit_account_owner(ambiguous, ["Account holder: Alex Rivera"])
    assert "accountOwners" not in ambiguous

    same_last_four = _result()
    same_last_four["transactions"] = [{"account": "1234"},
                                      {"account": "1234", "institution": "Other Bank"}]
    parser_common.infer_explicit_account_owner(same_last_four, ["Account holder: Alex Rivera"])
    assert "accountOwners" not in same_last_four


def test_csv_owner_column_is_inferred_for_one_account():
    result = _result()
    result["transactions"] = [{"account": "1234"}]
    parser_common.infer_csv_account_owner(result, [
        {"Account Holder": "Alex Rivera", "Account Name": "Checking"},
    ])
    assert result["accountOwners"] == [{"account": "1234", "ownerName": "Alex Rivera"}]


@pytest.mark.parametrize("printed, want", [
    ("JODABORU K DICIRIDO", "JODABORU DICIRIDO"),
    ("MARILYN JAMES MOSBY", "MARILYN MOSBY"),
    ("Alex Rivera", "Alex Rivera"),
    ("RIVERA, ALEX Q", "ALEX RIVERA"),
    ("ALEX Q RIVERA JR", "ALEX RIVERA"),
    ("ALEX Q RIVERA & JORDAN T RIVERA", "ALEX RIVERA & JORDAN RIVERA"),
    ("THE RIVERA FAMILY REVOCABLE TRUST", "THE RIVERA FAMILY REVOCABLE TRUST"),
    ("Cher", "Cher"),
    ("JAMES T. KIRK TRUST U/A 12/02/22", "JAMES T. KIRK TRUST"),
    ("JAMES T KIRK TRUST UAD 12-02-2022", "JAMES T KIRK TRUST"),
    ("JAMES T KIRK REVOCABLE TRUST DTD 12/02/22", "JAMES T KIRK REVOCABLE TRUST"),
    ("JAMES T KIRK TRUST 12/02/22", "JAMES T KIRK TRUST"),
])
def test_owner_names_keep_first_and_last_only(printed, want):
    assert parser_common.normalize_owner_name(printed) == want


def test_dispatcher_normalizes_parser_supplied_owners():
    result = _result()
    result["accountOwners"] = [{"account": "1234", "ownerName": "ALEX Q RIVERA"}]
    parser_common.normalize_account_owners(result)
    assert result["accountOwners"][0]["ownerName"] == "ALEX RIVERA"


def test_bofa_card_and_legacy_headers_name_the_holder():
    from institutions import bofa_checking
    card = "ALEX Q RIVERA ! Account # 1111 2222 3333 4444 ! July 6 - August 5, 2022"
    assert bofa_checking.header_owners(card, "4444") == [{"account": "4444", "ownerName": "ALEX Q RIVERA"}]
    assert bofa_checking.header_owners(card, "9999") == []
    legacy = "Statement Period\nALEX Q RIVERA 11-07-15 through 12-06-15\n"
    assert [o["account"] for o in bofa_checking.legacy_header_owners(legacy, ["1111", "2222", "1111"])] == ["1111", "2222"]
    assert bofa_checking.legacy_header_owners("XXXXXXXX X XXXXXXXX 11-07-15 through 12-06-15", ["1111"]) == []


def test_bofa_combined_checking_owner_comes_from_each_accounts_page_header():
    from institutions import bofa_checking_combined
    text = ("ALEX Q RIVERA ! Account # 1111 2222 3333 ! July 10, 2019 to August 8, 2019\n"
            "ALEX Q RIVERA ! Account # 5555 6666 7777 ! July 10, 2019 to August 8, 2019\n")
    accounts = [{"account": "3333"}, {"account": "7777"}, {"account": "7777"}]
    assert bofa_checking_combined._owners(text, accounts) == [
        {"account": "3333", "ownerName": "ALEX Q RIVERA"}, {"account": "7777", "ownerName": "ALEX Q RIVERA"}]


def test_bofa_joint_holders_are_read_from_summary_line_and_mailing_block():
    from institutions import bofa_checking
    modern = ("ALEX Q RIVERA ! Account # 1111 2222 3333 ! July 28, 2026 to August 25, 2026\n"
              "ALEX Q RIVERA JORDAN T RIVERA\nALEX Q RIVERA En Español: 1.800.688.6086\n")
    assert bofa_checking.header_owners(modern, "3333") == [
        {"account": "3333", "ownerName": "ALEX Q RIVERA & JORDAN T RIVERA"}]
    legacy = ("Platinum Privileges\n26318 001 SCM999 I1 0\nALEX Q RIVERA\nJORDAN T RIVERA\n"
              "255 S MAIN ST APT 27\nSPRINGFIELD, CA 94040\n")
    assert bofa_checking.legacy_header_owners(legacy, ["3333"]) == [
        {"account": "3333", "ownerName": "ALEX Q RIVERA & JORDAN T RIVERA"}]
    # The name above the street line must agree with the page header's.
    mismatch = legacy + "OTHER NAME 11-07-15 through 12-06-15\n"
    assert bofa_checking.legacy_header_owners(mismatch, ["3333"]) == [
        {"account": "3333", "ownerName": "OTHER NAME"}]


def test_bofa_pod_beneficiary_is_not_a_joint_holder():
    from institutions import bofa_checking
    modern = ("ALEX Q RIVERA ! Account # 1111 2222 3333 ! July 10, 2026 to August 7, 2026\n"
              "ALEX Q RIVERA POD JORDAN T RIVERA\n")
    assert bofa_checking.header_owners(modern, "3333") == [{"account": "3333", "ownerName": "ALEX Q RIVERA"}]
    legacy = "ALEX Q RIVERA\nPOD JORDAN T RIVERA\n255 S MAIN ST\n"
    assert bofa_checking._address_block_names(legacy) == ["ALEX Q RIVERA"]


def test_combined_checking_savings_without_its_own_header_takes_the_name_under_its_heading():
    from institutions import bofa_checking_combined

    # The running page header carries the first account's number only; the
    # savings account is named under its own heading, with a beneficiary.
    lines = [
        "Account number: 0000 0000 6756", "Your Adv Relationship Banking", "Rewards Honors",
        "SYNTH Q PERSON POD OTHER NAME", "Account summary",
        "Account number: 0000 0000 1790", "Your Regular Savings", "",
        "SYNTH Q PERSON POD OTHER NAME", "Account summary",
        "Account number: 0000 0000 2468", "Your Other Savings", "",
        "ALEX R SAMPLE", "Account summary",
    ]
    text = "SYNTH Q PERSON ! Account # 0000 0000 6756 ! September 9, 2026 to October 7, 2026\n" + "\n".join(lines)
    starts = [i for i, l in enumerate(lines) if l.startswith("Account number")] + [len(lines)]
    accounts = [{"account": lines[a].split()[-1], "holder": bofa_checking_combined._section_holder(lines[a:b])}
                for a, b in zip(starts, starts[1:])]
    assert [a["holder"] for a in accounts] == ["SYNTH Q PERSON", "SYNTH Q PERSON", "ALEX R SAMPLE"]
    assert bofa_checking_combined._owners(text, accounts) == [
        {"account": "6756", "ownerName": "SYNTH Q PERSON"},
        {"account": "1790", "ownerName": "SYNTH Q PERSON"},
        {"account": "2468", "ownerName": "ALEX R SAMPLE"},
    ]
