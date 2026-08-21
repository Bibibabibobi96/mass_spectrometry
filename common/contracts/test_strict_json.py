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
