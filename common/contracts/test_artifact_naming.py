from __future__ import annotations

import unittest

from artifact_naming import (
    validate_archive_id,
    validate_formal_asset_name,
    validate_run_id,
    validate_task_id,
)


class ArtifactNamingTests(unittest.TestCase):
    def test_descriptive_run_id(self) -> None:
        parsed = validate_run_id(
            "20260719_143522__sim__cross__mass-spectrum__n1000-mz10-2000"
        )
        self.assertEqual(parsed["activity"], "sim")

    def test_retry_is_explicit(self) -> None:
        validate_run_id("20260719_143522__test__comsol__particle-count__n29__r02")

    def test_archive_reason_is_controlled(self) -> None:
        validate_archive_id(
            "20260719_200000__migration-snapshot__simion__pre-layout-workspace"
        )

    def test_rejects_ambiguous_names(self) -> None:
        for value in ("final2", "test3", "20260719_mass_spectrum", "20260719_143522__run__simion__x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_run_id(value)

    def test_rejects_invalid_archive_reason(self) -> None:
        with self.assertRaises(ValueError):
            validate_archive_id("20260719_200000__old__simion__workspace")

    def test_project_qualified_formal_binary(self) -> None:
        self.assertEqual(
            validate_formal_asset_name("oa_tof__model.mph", "oa_tof")["role"], "model"
        )
        validate_formal_asset_name("oa_tof__assembly.SLDASM", "oa_tof")
        with self.assertRaises(ValueError):
            validate_formal_asset_name("main.mph", "oa_tof")

    def test_short_scratch_task_id(self) -> None:
        validate_task_id("20260719_213000__simion__iob-relink")
        with self.assertRaises(ValueError):
            validate_task_id("scratch_simion")


if __name__ == "__main__":
    unittest.main()
