"""Acceptance tests for the synthetic fixture, separate from product tests."""

import unittest

from invoice import total_cents


class InvoiceAcceptanceTests(unittest.TestCase):
    def assert_rejected(self, amounts):
        violations = []
        for amount in amounts:
            try:
                total_cents([amount])
            except ValueError:
                continue
            except Exception as error:
                violations.append((repr(amount), type(error).__name__))
            else:
                violations.append((repr(amount), "accepted"))
        self.assertEqual(violations, [], "Every invalid amount must raise ValueError")

    def test_empty_invoice_is_zero(self):
        self.assertEqual(total_cents([]), 0)

    def test_basic_valid_amounts(self):
        self.assertEqual(total_cents(["2", "12.3", "0.10", "0.20"]), 1460)

    def test_small_values_preserve_every_cent(self):
        self.assertEqual(total_cents(["0.29", "1.15"]), 144)

    def test_large_value_preserves_every_cent(self):
        self.assertEqual(total_cents(["90071992547409.93"]), 9007199254740993)

    def test_missing_amounts_are_rejected(self):
        self.assert_rejected([None, ""])

    def test_non_string_amounts_are_rejected(self):
        self.assert_rejected([0, 1, True, 0.5])

    def test_unsupported_text_is_rejected(self):
        self.assert_rejected([
            "-1", "+1", "1.005", "1e2", " 1", "1 ", "01", "1.", ".5",
            "NaN", "Infinity", "١.٠٠", "1,00",
        ])

    def test_missing_row_does_not_silently_reduce_total(self):
        with self.assertRaises(ValueError):
            total_cents(["1.00", None, "2.00"])

    def test_input_list_is_preserved(self):
        amounts = ["0.10", "0.20"]
        self.assertEqual(total_cents(amounts), 30)
        self.assertEqual(amounts, ["0.10", "0.20"])


if __name__ == "__main__":
    unittest.main()
