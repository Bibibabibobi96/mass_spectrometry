import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class S2GeometryBuildContractTests(unittest.TestCase):
    def test_comsol_task_is_build_only(self):
        task = (
            PROJECT_ROOT
            / "tests"
            / "comsol"
            / "build_s2_passive_connector_geometry.m"
        ).read_text(encoding="utf-8")
        forbidden = ("runAll", "mesh.create", "physics.create", "mphsave", "model.save")
        for token in forbidden:
            self.assertNotIn(token, task)
        self.assertIn("build_s2_passive_connector_model", task)

        builder = (
            PROJECT_ROOT / "tests" / "comsol" / "build_s2_passive_connector_model.m"
        ).read_text(encoding="utf-8")
        self.assertIn("REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY", builder)
        self.assertIn("s1.local_domain.rf_shield_inner_radius_mm", builder)
        self.assertIn("s1.local_domain.oatof_downstream_buffer_after_grid2_mm", builder)
        self.assertNotIn("shieldInnerRadius = 19.776", builder)
        for token in forbidden:
            self.assertNotIn(token, builder)

    def test_runner_uses_common_comsol_launcher(self):
        runner = (
            PROJECT_ROOT
            / "tests"
            / "comsol"
            / "run_s2_passive_connector_geometry.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("common\\comsol\\run_comsol_r2025b.ps1", runner)
        self.assertIn("field_solve = $false", runner)
        self.assertIn("particle_tracking = $false", runner)
        self.assertIn("Copy-RfFrozenDependency", runner)
        self.assertIn("dependency_identities = $dependencyIdentities", runner)

    def test_project_local_run_support_owns_artifact_lifecycle(self):
        support = (
            PROJECT_ROOT
            / "tests"
            / "support"
            / "rf_run_artifact_support.ps1"
        ).read_text(encoding="utf-8")
        for function_name in (
            "New-RfRunPackage",
            "Write-RfRunManifest",
            "Save-RfEnvironment",
            "Restore-RfEnvironment",
            "Copy-RfFrozenDependency",
            "Complete-RfFailedRun",
        ):
            self.assertIn(f"function {function_name}", support)
        self.assertIn("Get-FileHash -LiteralPath $source -Algorithm SHA256", support)

    def test_runner_and_contract_freeze_one_millimeter_gap(self):
        contract = json.loads(
            (PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(contract["nominal_registration"]["connector_gap_mm"], 1.0)
        self.assertTrue(contract["permissions"]["geometry_builder_implementation_allowed"])
        self.assertTrue(contract["permissions"]["field_solve_allowed"])
        self.assertFalse(contract["permissions"]["particle_runtime_allowed"])

    def test_no_pulse_field_runner_is_fail_closed(self):
        task = (
            PROJECT_ROOT / "tests" / "comsol" / "solve_s2_passive_connector_field.m"
        ).read_text(encoding="utf-8")
        runner = (
            PROJECT_ROOT / "tests" / "comsol" / "run_s2_passive_connector_field.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("build_s2_passive_connector_model", task)
        self.assertIn("physics.create('es_static'", task)
        self.assertIn("physics.create('es_rf'", task)
        self.assertIn("solution.runAll", task)
        self.assertNotIn("ChargedParticleTracing", task)
        self.assertNotIn("model.save", task)
        self.assertIn("{'geom1_connvac_dom','geom1_portvac_dom'}", task)
        self.assertNotIn("selection.named('geom1_univacgrid_dom')", task)
        self.assertIn("particle_runtime_allowed", runner)
        self.assertIn("Complete-RfFailedRun", runner)
        self.assertIn("dependency_identities = $dependencyIdentities", runner)
        self.assertIn("mesh_convergence_claimed = $false", runner)


if __name__ == "__main__":
    unittest.main()
