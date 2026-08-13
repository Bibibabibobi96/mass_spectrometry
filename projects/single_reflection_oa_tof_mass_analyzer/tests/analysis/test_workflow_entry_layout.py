from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class WorkflowEntryLayoutTests(unittest.TestCase):
    def test_active_entries_have_one_role_appropriate_location(self):
        expected = {
            "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1",
            "comsol/run_fixed_particle_retrace.m",
            "comsol/verify_oatof_comsol_sync.m",
            "simion/workbench/verify_formal_runtime.lua",
            "simion/workbench/verify_iob_runtime_contract.lua",
            "simion/workbench/verify_iob_runtime_contract.ps1",
            "simion/workbench/run_parameterized_geometry_smoke.ps1",
            "workflows/design_candidate/prepare_candidate_consumers.py",
            "workflows/design_candidate/run_candidate.py",
            "workflows/design_candidate/run_candidate_workflow.py",
            "workflows/experiment_campaign/run_campaign.py",
            "workflows/design_candidate/run_candidate_contract_build.m",
            "workflows/design_candidate/run_candidate_cad_sync.m",
            "workflows/accelerator_transverse_field_uniformity/run_accelerator_transverse_field_uniformity.ps1",
            "workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1",
            "workflows/cross_solver_diagnostics/comsol/export_accelerator_vector_field_samples.m",
            "workflows/cross_solver_diagnostics/comsol/export_axis_field_profiles.m",
            "workflows/cross_solver_diagnostics/comsol/export_selected_particle_trajectories.m",
            "workflows/cross_solver_diagnostics/simion/export_accelerator_vector_field_samples.lua",
            "workflows/cross_solver_diagnostics/simion/export_axis_field_profiles.lua",
            "comsol/export_accelerator_transverse_field_uniformity.m",
            "tests/comsol/test_support/run_oatof_matlab_unit_tests.m",
            "tests/comsol/test_support/run_oatof_formal_write_contract_tests.m",
            "tests/simion/test_support/export_accelerator_grid_phase_field.lua",
        }
        for relative in expected:
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)

        removed = {
            "tests/cross_solver/run_mass_spectrum_candidate.ps1",
            "tests/comsol/test_accelerator_mesh_particle_candidate.m",
            "tests/comsol/verify_oatof_comsol_sync.m",
            "tests/simion/verify_formal_runtime.lua",
            "tests/simion/verify_iob_runtime_contract.lua",
            "tests/simion/verify_iob_runtime_contract.ps1",
            "tests/simion/test_parameterized_geometry_build.ps1",
            "analysis/prepare_candidate_consumers.py",
            "analysis/run_candidate_workflow.py",
            "tests/comsol/run_candidate_contract_build.m",
            "tests/cad/run_candidate_cad_sync.m",
            "tests/comsol/run_accelerator_transverse_field_uniformity.ps1",
            "tests/comsol/export_accelerator_transverse_field_uniformity.m",
            "tests/comsol/run_oatof_matlab_unit_tests.m",
            "tests/comsol/run_oatof_formal_write_contract_tests.m",
            "tests/simion/export_accelerator_grid_phase_field.lua",
            "tests/comsol/compare_oatof_particle_exports.ps1",
            "tests/comsol/export_accelerator_vector_field_samples.m",
            "tests/comsol/export_axis_field_profiles.m",
            "tests/comsol/export_selected_particle_trajectories.m",
            "tests/simion/export_accelerator_vector_field_samples.lua",
            "tests/simion/export_axis_field_profiles.lua",
            "tests/simion/export_axis_field_profiles.ps1",
        }
        for relative in removed:
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)

    def test_profiles_and_candidate_closure_reference_canonical_entries(self):
        profiles = json.loads(
            (PROJECT_ROOT / "config" / "execution_profiles.json").read_text(encoding="utf-8")
        )
        entries = {
            step["entrypoint"]
            for profile in profiles["profiles"]
            for step in profile["steps"]
        }
        self.assertIn(
            "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1", entries
        )
        self.assertIn(
            "workflows/design_candidate/run_candidate.py", entries
        )
        self.assertIn(
            "workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1",
            entries,
        )
        campaign_entry = (
            PROJECT_ROOT / "workflows" / "experiment_campaign" / "run_campaign.py"
        )
        self.assertTrue(campaign_entry.is_file())
        self.assertIn(
            "workflows.experiment_campaign.run_campaign",
            (PROJECT_ROOT / "README.md").read_text(encoding="utf-8"),
        )

        closure = (PROJECT_ROOT / "analysis" / "candidate_source_closure.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflows/design_candidate/run_candidate.py", closure)
        self.assertIn("workflows/design_candidate/run_candidate_contract_build.m", closure)
        self.assertIn("workflows/design_candidate/run_candidate_cad_sync.m", closure)
        self.assertIn("comsol/verify_oatof_comsol_sync.m", closure)
        self.assertIn("simion/workbench/verify_iob_runtime_contract.lua", closure)
        self.assertIn("simion/workbench/verify_iob_runtime_contract.ps1", closure)
        self.assertNotIn("tests/comsol/run_candidate_contract_build.m", closure)
        self.assertNotIn("tests/cad/run_candidate_cad_sync.m", closure)
        self.assertNotIn("tests/comsol/verify_oatof_comsol_sync.m", closure)
        self.assertNotIn("tests/simion/verify_iob_runtime_contract", closure)

        core = (
            PROJECT_ROOT
            / "workflows"
            / "design_candidate"
            / "run_candidate_workflow.py"
        ).read_text(encoding="utf-8")
        lifecycle = (
            PROJECT_ROOT / "analysis" / "candidate_run_lifecycle.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("native_receipts", core)
        self.assertNotIn("def main(", core)
        self.assertNotIn("def main(", lifecycle)

    def test_candidate_gate_uses_production_parameterized_geometry_runner(self):
        gate = (PROJECT_ROOT / "verify_project.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "simion\\workbench\\run_parameterized_geometry_smoke.ps1",
            gate,
        )
        self.assertNotIn(
            "tests\\simion\\test_parameterized_geometry_build.ps1",
            gate,
        )

    def test_candidate_simion_runner_governs_native_ideal_grid_receipts(self):
        runner = (
            PROJECT_ROOT / "simion" / "workbench" / "run_parameterized_geometry_smoke.ps1"
        ).read_text(encoding="utf-8")
        program = (
            PROJECT_ROOT / "simion" / "workbench" / "formal" / "oatof_ideal_grounded.lua"
        ).read_text(encoding="utf-8")
        inspector = (
            PROJECT_ROOT
            / "tests"
            / "simion"
            / "test_support"
            / "inspect_native_ideal_grid_rows.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("native_ideal_grid_raw_pa_receipt.json", runner)
        self.assertIn("native_ideal_grid_crossing_receipt.json", runner)
        self.assertIn("schema_version=2", runner)
        self.assertIn("'entgrid:return'=1", runner)
        self.assertIn("'midgrid:return'=1", runner)
        self.assertIn("TRACE: native_grid_crossing", program)
        self.assertIn("simion.pas:open", inspector)
        self.assertIn("pa:point(x,y,z)", inspector)
        self.assertIn("count==1", inspector)
        self.assertIn("$acceleratorBuild.cell_xy_mm, $acceleratorBuild.cell_z_mm", runner)
        self.assertIn("$reflectronBuild.cell_axial_mm, $reflectronBuild.cell_radial_mm", runner)
        self.assertIn("$acceleratorBuild.max_gib", runner)
        self.assertIn("$reflectronBuild.max_gib", runner)
        self.assertIn("authority_sha256=$numericsSha256", runner)
        self.assertIn("estimated_gib=$acceleratorEstimatedGib", runner)
        self.assertNotIn("$geometry.accelerator_shield_wall, 0, 0.1", runner)
        self.assertIn("native_ideal_grid_stage_timing_receipt.json", runner)
        self.assertIn("native_ideal_grid_geometry_alignment_receipt.json", runner)
        self.assertIn("analysis\\validate_simion_pa_family.py", runner)
        self.assertIn("post_build_family_validation", runner)
        self.assertIn("Highest=$expectedAcceleratorElectrodes", runner)
        self.assertIn("Highest=$expectedReflectronElectrodes", runner)
        self.assertIn("BUILD_TIMING: stage=%s event=complete", (
            PROJECT_ROOT / "simion" / "accelerator" / "build_accelerator_variant.lua"
        ).read_text(encoding="utf-8"))
        self.assertIn("Complete-FailedRun", runner)
        self.assertIn("FailureStage $failureStage", runner)
        self.assertIn("ThresholdResultEligible $false", runner)
        self.assertLess(runner.index("Write-RunJson -Value $runConfig"), runner.index("Invoke-Builder"))

    def test_native_grid_builders_hard_fail_grids_and_warn_for_ordinary_edges(self):
        accelerator = (
            PROJECT_ROOT / "simion" / "accelerator" / "build_accelerator_variant.lua"
        ).read_text(encoding="utf-8")
        reflectron = (
            PROJECT_ROOT / "simion" / "reflectron" / "build_reflectron_variant.lua"
        ).read_text(encoding="utf-8")

        for required in (
            "grid1 zero-width sheet must lie on a raw PA row",
            "grid2 zero-width sheet must lie on a raw PA row",
        ):
            self.assertIn(required, accelerator)
        self.assertLess(
            accelerator.index("grid1 zero-width sheet"),
            accelerator.index("timed_stage('gem2pa'"),
        )
        self.assertIn("accelerator_geometry_edge_not_on_grid_node", accelerator)
        self.assertIn("surface=none action=continue", accelerator)
        for required in (
            "entrance-grid zero-width sheet must lie on a raw PA row",
            "midgrid zero-width sheet must lie on a raw PA row",
        ):
            self.assertIn(required, reflectron)
        self.assertIn("reflectron_geometry_edge_not_on_grid_node", reflectron)
        self.assertIn("surface=none action=continue", reflectron)
        self.assertNotIn("fractional_surface=enabled", reflectron)

    def test_simion_accelerator_uses_native_one_row_ideal_grids(self):
        gem = (
            PROJECT_ROOT / "simion" / "accelerator" / "oatof_accelerator_3d.gem"
        ).read_text(encoding="utf-8")
        program = (
            PROJECT_ROOT / "simion" / "workbench" / "formal" / "oatof_ideal_grounded.lua"
        ).read_text(encoding="utf-8")
        numerics = json.loads(
            (PROJECT_ROOT / "config" / "formal_solver_numerics.json").read_text(
                encoding="utf-8"
            )
        )["simion"]

        self.assertIn("$(electrode_width/2),$(electrode_width/2),$(stage1_length))", gem)
        self.assertIn("$(shield_inner_width/2),$(shield_inner_width/2),$(stage1_length+stage2_length))", gem)
        self.assertIn("surface=none", gem)
        self.assertNotIn("surface=fractional", gem)
        self.assertNotIn(
            "$(electrode_width),$(electrode_width),$(mmgu_z))",
            gem,
        )
        self.assertNotIn(
            "$(shield_inner_width),$(shield_inner_width),$(mmgu_z))",
            gem,
        )
        for retired in (
            "ideal_grid_epsilon_mm",
            "accelerator_grid_epsilon_mm",
            "reflectron_grid_epsilon_mm",
            "grid_planes",
            "inside_grid",
            "grid_jump",
            "jumped",
            "ion_pz_mm=post",
        ):
            self.assertNotIn(retired, program)
        self.assertEqual(
            numerics["ideal_grid_model"],
            "simion_one_row_zero_width_native_transmission",
        )
        self.assertNotIn("accelerator_grid_epsilon_mm", numerics)
        self.assertNotIn("reflectron_grid_epsilon_mm", numerics)

    def test_cross_solver_diagnostics_uses_current_formal_instance_roles(self):
        workflow = (
            PROJECT_ROOT
            / "workflows"
            / "cross_solver_diagnostics"
            / "run_cross_solver_diagnostics.ps1"
        ).read_text(encoding="utf-8")
        for dependency in (
            "export_axis_field_profiles.m",
            "export_selected_particle_trajectories.m",
            "export_accelerator_vector_field_samples.m",
            "export_axis_field_profiles.lua",
            "export_accelerator_vector_field_samples.lua",
            "compare_field_profiles.py",
            "compare_particle_trajectories.py",
            "compare_vector_field_samples.py",
        ):
            self.assertIn(dependency, workflow)
        axis_adapter = (
            PROJECT_ROOT
            / "workflows"
            / "cross_solver_diagnostics"
            / "simion"
            / "export_axis_field_profiles.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("local reflectron_instance = 2", axis_adapter)
        self.assertIn("local accelerator_instance = 3", axis_adapter)
        self.assertIn("math.floor((z_end-z_start)/z_step+1e-9)+1", axis_adapter)
        self.assertNotIn("sample('accelerator_source',2,", axis_adapter)
        self.assertNotIn("sample('reflectron',1,", axis_adapter)
        vector_adapter = (
            PROJECT_ROOT
            / "workflows"
            / "cross_solver_diagnostics"
            / "simion"
            / "export_accelerator_vector_field_samples.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("local inside_pa =", vector_adapter)
        self.assertIn("SKIPPED_OUTSIDE_PA", vector_adapter)


if __name__ == "__main__":
    unittest.main()
