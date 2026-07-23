from __future__ import annotations

from pathlib import Path
import unittest

from projects.rf_quadrupole_collision_cooling.analysis import (
    validate_spatial_registration_migration as migration,
)


class SpatialRegistrationMigrationRatchetTests(unittest.TestCase):
    def test_active_sources_have_no_legacy_exceptions(self) -> None:
        migration.validate()

    def test_new_manual_matrix_primitive_is_rejected(self) -> None:
        violations = migration.scan_python(
            Path("new_adapter.py"),
            "def matvec(matrix, vector):\n"
            "    return [sum(a*b for a,b in zip(row, vector)) for row in matrix]\n",
        )
        self.assertTrue(
            any(item.startswith("no_local_matrix_primitives:") for item in violations)
        )

    def test_second_canonical_producer_is_rejected(self) -> None:
        violations = migration.scan_python(
            Path("duplicate.py"),
            "release = {'role': 'resolved_spatial_registration_do_not_edit'}\n",
        )
        self.assertTrue(
            any(item.startswith("no_second_resolved_authority:") for item in violations)
        )

    def test_new_matlab_fixed_pose_is_rejected(self) -> None:
        violations = migration.scan_matlab(
            Path("builder.m"),
            "registrationPath=getenv('RF_OATOF_SPATIAL_REGISTRATION');\n"
            "rotation = [0 0 1; 1 0 0; 0 1 0];\n",
        )
        self.assertTrue(
            any(item.endswith(":hardcoded_pose") for item in violations)
        )


if __name__ == "__main__":
    unittest.main()
