"""Focused tests for shared fail-closed JSON representation checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts.strict_json import (
    StrictJsonError,
    load_json_object,
    require_bool,
    require_exact_keys,
    require_number,
    require_positive_integer,
)


class StrictJsonTests(unittest.TestCase):
    """Keep generic JSON checks independent of project physics."""

    def test_exact_keys_reports_missing_and_unknown(self) -> None:
        with self.assertRaisesRegex(
            StrictJsonError, r"missing=\['required'\], unknown=\['extra'\]"
        ):
            require_exact_keys({"extra": 1}, {"required"}, "contract")

    def test_number_rejects_boolean_nonfinite_and_out_of_range(self) -> None:
        for value, message in ((True, "numeric"), (float("nan"), "finite")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(StrictJsonError, message):
                    require_number(value, "value")
        with self.assertRaisesRegex(StrictJsonError, "<= 2.0"):
            require_number(3, "value", maximum=2.0)
        with self.assertRaisesRegex(StrictJsonError, "> 1.0"):
            require_number(1, "value", minimum=1.0, strict_minimum=True)

    def test_boolean_and_positive_integer_do_not_accept_lookalikes(self) -> None:
        with self.assertRaisesRegex(StrictJsonError, "boolean"):
            require_bool(1, "flag")
        with self.assertRaisesRegex(StrictJsonError, "positive integer"):
            require_positive_integer(True, "count")

    def test_number_preserves_signed_values_and_rejects_nonnumeric_or_overflow(self) -> None:
        for value in (0, -2, 3.5):
            self.assertEqual(require_number(value, "value"), float(value))
        for value in (False, "1.5", None, 1+2j, float("inf"), -float("inf"), 10**1000):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(StrictJsonError):
                require_number(value, "value")
        self.assertEqual(require_number(0, "value", minimum=0), 0.)
        with self.assertRaises(StrictJsonError):
            require_number(0, "value", minimum=0, strict_minimum=True)

    def test_loader_preserves_json_types_unicode_and_optional_utf8_bom(self) -> None:
        text = '{"label":"脉冲", "n":3, "v":-2.5, "enabled":true, "values":[null,0,1e2]}'
        expected = {"label": "脉冲", "n": 3, "v": -2.5, "enabled": True, "values": [None, 0, 100.]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            for encoding in ("utf-8", "utf-8-sig"):
                path.write_text(text, encoding=encoding)
                actual = load_json_object(path)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual["n"]), int)
                self.assertIs(type(actual["enabled"]), bool)

    def test_loader_rejects_duplicate_keys_in_any_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            for text in ('{"x":1,"x":1}', '{"x":1,"x":2}',
                         '{"nested":{"x":1,"x":2}}', '{"rows":[{"x":1,"x":2}]}'):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(StrictJsonError, "duplicate JSON key 'x'"):
                        load_json_object(path)

    def test_loader_rejects_nonfinite_literals_and_float_overflow_at_any_depth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            for token in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
                with self.subTest(token=token):
                    path.write_text('{"nested":[{"value":' + token + '}]}', encoding="utf-8")
                    with self.assertRaisesRegex(StrictJsonError, "non-finite JSON number"):
                        load_json_object(path)

    def test_loader_rejects_nonstandard_constants_and_non_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(StrictJsonError, "non-finite JSON number NaN"):
                load_json_object(path)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(StrictJsonError, "must be an object"):
                load_json_object(path)


if __name__ == "__main__":
    unittest.main()
