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

    def test_contract_keeps_current_one_millimeter_candidate_and_supports_zero_gap(self):
        contract = json.loads(
            (PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(contract["nominal_registration"]["connector_gap_mm"], 1.0)
        self.assertTrue(contract["passive_connector_geometry"]["zero_gap_supported"])
        self.assertEqual(
            contract["passive_connector_geometry"]["cavity"]["creation_condition"],
            "connector_gap_mm > 0",
        )
        self.assertTrue(contract["permissions"]["geometry_builder_implementation_allowed"])
        self.assertTrue(contract["permissions"]["field_solve_allowed"])
        self.assertTrue(contract["permissions"]["particle_runtime_allowed"])

    def test_no_pulse_field_runner_is_fail_closed(self):
        task = (
            PROJECT_ROOT / "tests" / "comsol" / "solve_s2_passive_connector_field.m"
        ).read_text(encoding="utf-8")
        runner = (
            PROJECT_ROOT / "tests" / "comsol" / "run_s2_passive_connector_field.ps1"
        ).read_text(encoding="utf-8")
        field_builder = (
            PROJECT_ROOT / "tests" / "comsol" / "prepare_s2_joint_field_model.m"
        ).read_text(encoding="utf-8")
        self.assertIn("prepare_s2_joint_field_model", task)
        self.assertIn("build_s2_passive_connector_model", field_builder)
        self.assertIn("physics.create('es_static'", field_builder)
        self.assertIn("physics.create('es_rf'", field_builder)
        self.assertIn("solution.runAll", field_builder)
        self.assertIn("ChargedParticleTracing", task)
        self.assertIn("particleEnabled = ~isempty(particleInputPath)", task)
        self.assertIn("oa_extraction_pulse_included", task)
        self.assertIn("insideAperture = crossed &&", task)
        self.assertIn("outside_rectangular_oatof_entry", task)
        self.assertNotIn("model.save", task)
        self.assertIn("connector_gap_mm > 0", field_builder)
        self.assertIn("{'geom1_connvac_dom','geom1_portvac_dom'}", field_builder)
        self.assertNotIn("selection.named('geom1_univacgrid_dom')", task)
        self.assertIn("particle_runtime_allowed", runner)
        self.assertIn("Complete-RfFailedRun", runner)
        self.assertIn("dependency_identities = $dependencyIdentities", runner)
        self.assertIn("mesh_convergence_claimed = $false", runner)
        self.assertIn("[switch]$Particles", runner)
        self.assertIn("verify_run_manifest.py", runner)
        self.assertIn("--target-origin-mm $sourceCenter", runner)
        self.assertIn("RF_HANDOFF_PROJECT_ROOT", runner)
        self.assertIn("handoff_project_snapshot", runner)
        self.assertIn("$env:RF_HANDOFF_PROJECT_ROOT = $handoffProjectRoot", runner)
        self.assertNotIn("$env:RF_HANDOFF_PROJECT_ROOT = $projectRoot", runner)
        self.assertIn("Copy-Item -LiteralPath $energyMatchContractSource -Destination $energyMatchContract", runner)
        self.assertIn("Copy-Item -LiteralPath $sourceInterfaceContractSource -Destination $sourceInterfaceContract", runner)
        self.assertIn("source_particle_identity", runner)
        self.assertNotIn("Get-Command py", runner)

    def test_s2_solver_scripts_consume_contracts_without_physical_fallbacks(self):
        scripts = [
            (PROJECT_ROOT / "tests" / "comsol" / name).read_text(encoding="utf-8")
            for name in (
                "build_s2_passive_connector_model.m",
                "prepare_s2_joint_field_model.m",
                "solve_s2_passive_connector_field.m",
            )
        ]
        combined = "\n".join(scripts)
        for required_source in (
            "contract.nominal_registration",
            "contract.passive_connector_geometry",
            "contract.no_pulse_field_candidate.mesh",
            "s1.field_basis.rf_unit.rod_differential_pattern_V",
            "oa.electrodes_V",
            "rf.geometry_mm",
        ):
            self.assertIn(required_source, combined)
        for forbidden_literal in (
            "shieldInnerRadius = 19.776",
            "gapMm = 1.0",
            "portWidth = 1.0",
            "portHeight = 0.9",
            "offset = 0.001",
            "100*(-1)",
        ):
            self.assertNotIn(forbidden_literal, combined)

    def test_shared_geometry_branches_on_zero_gap_without_a_second_builder(self):
        builder = (
            PROJECT_ROOT / "tests" / "comsol" / "build_s2_passive_connector_model.m"
        ).read_text(encoding="utf-8")
        self.assertIn("connectorPresent = gapMm > 0", builder)
        self.assertIn("if connectorPresent", builder)
        self.assertIn("connectorDomains = []", builder)
        self.assertNotIn("add_cylinder(geom, 'connvac', connector.cavity.inner_radius_mm, 0", builder)


if __name__ == "__main__":
    unittest.main()
