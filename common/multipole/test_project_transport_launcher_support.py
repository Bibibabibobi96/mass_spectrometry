from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SUPPORT_PATH = (
    REPO_ROOT / "common/multipole/project_transport_launcher_support.ps1"
)
PROJECTS = (
    ("rf_hexapole_ion_optics", "segmented_rod_axial_acceleration"),
    ("rf_octupole_ion_optics", "no_acceleration_full_length"),
)


class ProjectTransportLauncherSupportTests(unittest.TestCase):
    def test_one_internal_support_resolves_and_delegates_both_solvers(self) -> None:
        source = SUPPORT_PATH.read_text(encoding="utf-8-sig")
        self.assertEqual(
            source.count("-m common.multipole.runtime_profile"),
            1,
        )
        self.assertEqual(
            source.count("common\\multipole\\run_finite_3d_transport.ps1"),
            1,
        )
        self.assertEqual(
            source.count("common\\multipole\\run_simion_finite_3d_transport.ps1"),
            1,
        )
        self.assertIn("$arguments.StopStage = 'mesh_build'", source)
        self.assertIn("solver_numerics.$Solver.values", source)

    def test_public_wrappers_keep_identity_defaults_and_no_profile_catalog(self) -> None:
        for project_id, default_profile_id in PROJECTS:
            analysis = REPO_ROOT / "projects" / project_id / "analysis"
            for name, solver in (
                ("run_finite_3d_transport.ps1", "comsol"),
                ("run_simion_finite_3d_transport.ps1", "simion"),
            ):
                source = (analysis / name).read_text(encoding="utf-8-sig")
                self.assertIn(
                    f"[string]$RuntimeProfileId = '{default_profile_id}'",
                    source,
                )
                self.assertIn(f"-ProjectId '{project_id}'", source)
                self.assertIn(f"-Solver {solver}", source)
                self.assertIn(
                    "project_transport_launcher_support.ps1",
                    source,
                )
                self.assertNotIn("ValidateSet(", source)
                self.assertNotIn("ParticleSourcePath", source)
                self.assertNotIn("EngineeringBudgetPath", source)


if __name__ == "__main__":
    unittest.main()
