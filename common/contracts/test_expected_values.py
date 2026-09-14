"""Reference vectors for partial structured CLI expectations."""

from __future__ import annotations

import unittest

from common.contracts.expected_values import assert_expected_values


class ExpectedValuesTests(unittest.TestCase):
    def test_partial_nested_mapping_and_numeric_tolerances(self) -> None:
        assert_expected_values(
            {"rows": [{"x": 1000.5, "unused": None}, 0.0001], "extra": True},
            {"rows": [{"x": 1000.0}, 0.0]},
            "reference", abs_tol=0.001, rel_tol=0.001,
        )

    def test_first_mismatch_preserves_path_and_message(self) -> None:
        vectors = [
            ([], {}, "actual is not a mapping"),
            ({}, {"x": 1}, "x: missing actual key"),
            ("ab", ["a", "b"], "actual is not a sequence"),
            ([1], [1, 2], "sequence length differs"),
            ({"x": [3]}, {"x": [4]}, "x[0]: actual=3 expected=4"),
            ("wrong", "right", "actual='wrong' expected='right'"),
            (False, True, "actual=False expected=True"),
        ]
        for actual, expected, suffix in vectors:
            with self.subTest(expected=expected):
                with self.assertRaises(SystemExit) as caught:
                    assert_expected_values(actual, expected, "reference", abs_tol=0, rel_tol=0)
                message = str(caught.exception)
                self.assertTrue(message.startswith("MISMATCH reference"))
                self.assertTrue(message.endswith(suffix), message)

    def test_length_presentation_propagates_through_nested_tree(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            assert_expected_values(
                {"rows": [[1]]}, {"rows": [[1, 2]]}, "reference",
                abs_tol=0, rel_tol=0,
                sequence_length_message="actual length={actual} expected={expected}",
            )
        self.assertEqual(
            str(caught.exception),
            "MISMATCH reference.rows[0]: actual length=1 expected=2",
        )

    def test_nonfinite_and_outside_tolerance_do_not_pass(self) -> None:
        for actual in (float("nan"), float("inf"), 1.01):
            with self.subTest(actual=actual), self.assertRaises(SystemExit):
                assert_expected_values(actual, 1.0, "x", abs_tol=0.001, rel_tol=0)


if __name__ == "__main__":
    unittest.main()
