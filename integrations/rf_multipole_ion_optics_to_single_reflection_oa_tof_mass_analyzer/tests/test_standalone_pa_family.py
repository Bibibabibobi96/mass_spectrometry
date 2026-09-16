from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.standalone_pa_family import (
    parse_response_ids,
    response_exports,
    write_mode_map,
)


class StandalonePaFamilyTests(unittest.TestCase):
    def test_response_namespace_and_names_are_deterministic(self) -> None:
        self.assertEqual(parse_response_ids("36,37,43"), (36, 37, 43))
        exports = response_exports("accelerator_main", (36, 37))
        self.assertEqual(exports[0].source_name, "accelerator_main.pa36")
        self.assertEqual(
            exports[1].standalone_name, "accelerator_main.response_37.pa"
        )

    def test_invalid_response_namespaces_and_prefixes_fail_closed(self) -> None:
        for value in ("", "37,36", "36,36", "-1", "x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_response_ids(value)
        for prefix in ("", "nested/name", "field.pa"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                response_exports(prefix, (36,))

    def test_mode_map_is_absolute_and_has_strict_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            response = root / "field.response_36.pa"
            response.write_bytes(b"pa")
            destination = root / "mode-map.tsv"
            write_mode_map(
                destination,
                [
                    {
                        "response_id": 36,
                        "path": str(response),
                        "bytes": response.stat().st_size,
                        "sha256": file_sha256(response),
                    }
                ],
            )
            self.assertEqual(
                destination.read_text().splitlines(),
                ["standalone_pa_mode_map_v1", f"36\t{response.resolve()}"],
            )


if __name__ == "__main__":
    unittest.main()
