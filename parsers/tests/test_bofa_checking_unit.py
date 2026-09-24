import unittest
import sys
import types

sys.modules.setdefault("pdfplumber", types.SimpleNamespace(open=None))
from institutions import bofa_checking


class BofaCheckingTest(unittest.TestCase):
    def test_page_end_promotion_and_header_do_not_extend_description(self):
        pages = [
            "\n".join(
                [
                    "Withdrawals and other subtractions",
                    "Other subtractions",
                    "Date Description Amount",
                    "06/01/26 Online Scheduled Payment to ACCT# 4533 Confirmation# 2105647625 -9,916.98",
                    "continued on the next page",
                    "Available in English and Spanish",
                    "Make bank transfers in the Mobile Banking app",
                    "Page 3 of 6",
                ]
            ),
            "\n".join(
                [
                    "00000000 00000000 ! Account # 0000 0000 8086 ! May 21, 2026 to June 22, 2026",
                    "Withdrawals and other subtractions - continued",
                    "Other subtractions - continued",
                    "Date Description Amount",
                    "06/01/26 PAYPAL DES:INST XFER ID:EXAMPLE -130.00",
                    "ID:PAYPALSI77 WEB",
                    "Total other subtractions -$10,046.98",
                ]
            ),
        ]

        transactions = bofa_checking._parse_transactions(pages)

        self.assertEqual(
            [transaction["description"] for transaction in transactions],
            [
                "Online Scheduled Payment to ACCT# 4533 Confirmation# 2105647625",
                "PAYPAL DES:INST XFER ID:EXAMPLE ID:PAYPALSI77 WEB",
            ],
        )

    def test_important_messages_do_not_extend_transaction_or_account_type(self):
        pages = [
            "\n".join(
                [
                    "Please see the Important Messages - Please Read section of your statement for important details that could impact you.",
                    "Your Adv Tiered Interest Chkg",
                    "for February 7, 2026 to March 11, 2026 Account number: 0000 0000 7777",
                    "Beginning balance on February 7, 2026 $34,550.37",
                    "Ending balance on March 11, 2026 $31,446.65",
                ]
            ),
            "\n".join(
                [
                    "Deposits and other additions",
                    "Date Description Amount",
                    "03/11/26 Interest Earned 12.52",
                    "Total deposits and other additions $12.52",
                    "Withdrawals and other subtractions",
                    "Other subtractions",
                    "Date Description Amount",
                    "03/10/26 Stone Valley DTAC DES:StoneValley ID:3333006666 INDN:xxxxxxxx xxxxxxxx CO ID:0000077111 -3,116.24",
                    "WEB",
                    "Total other subtractions -$3,116.24",
                    "Braille and Large Print Request - You can request a copy of this statement in Braille or Large Print by calling 800.234.1000.",
                ]
            ),
            "\n".join(
                [
                    "Important Messages - Please Read",
                    "We are changing one of the ways to avoid the monthly maintenance fee on our consumer checking and savings",
                    "accounts.",
                ]
            ),
        ]

        stmt = bofa_checking.parse(pages, "", None)

        self.assertEqual(stmt["statementDate"], "2026-03-11")
        self.assertEqual(len(stmt["transactions"]), 2)
        self.assertEqual(
            [(t["description"], t["accountType"]) for t in stmt["transactions"]],
            [
                (
                    "Stone Valley DTAC DES:StoneValley ID:3333006666 INDN:xxxxxxxx xxxxxxxx CO ID:0000077111 WEB",
                    "Checking",
                ),
                ("Interest Earned", "Checking"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
