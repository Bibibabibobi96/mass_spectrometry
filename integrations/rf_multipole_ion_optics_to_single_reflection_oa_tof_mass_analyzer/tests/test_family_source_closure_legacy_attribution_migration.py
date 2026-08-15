from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


INTEGRATION = Path(__file__).resolve().parents[1]
REPO_ROOT = INTEGRATION.parents[1]
MIGRATION = INTEGRATION / "config/family_source_closure_legacy_attribution_migration.json"
HISTORICAL_CAMPAIGN = INTEGRATION / "config/pulse_resolution_optimization_campaign.json"
FAILED_DIRECT_CAMPAIGN = INTEGRATION / "config/pulse_resolution_direct_campaign.json"
FAILED_R01_CAMPAIGN = INTEGRATION / "config/pulse_resolution_direct_baseline_successor_campaign.json"


class FamilySourceClosureLegacyAttributionMigrationTests(unittest.TestCase):
    def test_published_historical_campaign_has_immutable_non_executable_disposition(
        self,
    ) -> None:
        contract = json.loads(MIGRATION.read_text(encoding="utf-8"))
        self.assertEqual(
            contract["historical_campaigns"][0],
            {
                "path": (
                    "integrations/"
                    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                    "config/pulse_resolution_optimization_campaign.json"
                ),
                "head_blob_sha1": "4a5f167f21e16a5c1c0cc658015ac588280427bf",
                "content_sha256": (
                    "2a8fa4fef8ff1fd53a2991862edaca36ce23ff3e0812d5cd8a8907697e61e524"
                ),
                "disposition": "non_executable_historical_evidence",
            },
        )
        self.assertEqual(
            hashlib.sha256(HISTORICAL_CAMPAIGN.read_bytes()).hexdigest(),
            contract["historical_campaigns"][0]["content_sha256"],
        )
        head_blob = subprocess.run(
            ["git", "rev-parse", f"HEAD:{HISTORICAL_CAMPAIGN.relative_to(REPO_ROOT).as_posix()}"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(head_blob, contract["historical_campaigns"][0]["head_blob_sha1"])
        failed = contract["historical_campaigns"][1]
        self.assertEqual(
            failed,
            {
                "path": (
                    "integrations/"
                    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                    "config/pulse_resolution_direct_campaign.json"
                ),
                "content_sha256": (
                    "e4ac9275b4970721088797ad67dac979d84d4bdf7fce52003dd554daa78ad47b"
                ),
                "disposition": "non_executable_historical_evidence",
                "failed_run_id": (
                    "20260815_160000__sim__cross__pulse-direct-real-rr__n100"
                ),
                "failed_run_manifest_sha256": (
                    "477a8ba8822256ac585f9db64f443d51b3c525660904d95738896d928c8bf994"
                ),
                "failure_stage": "governed_child_execution_or_publication",
            },
        )
        self.assertEqual(
            hashlib.sha256(FAILED_DIRECT_CAMPAIGN.read_bytes()).hexdigest(),
            failed["content_sha256"],
        )
        failed_r01 = contract["historical_campaigns"][2]
        self.assertEqual(
            failed_r01,
            {
                "path": (
                    "integrations/"
                    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                    "config/pulse_resolution_direct_baseline_successor_campaign.json"
                ),
                "content_sha256": (
                    "d9f66c43a702dc52ff113a5c5a87e97cf391d6183a9b0915a053ff4993728904"
                ),
                "disposition": "non_executable_historical_evidence",
                "failed_run_id": (
                    "20260815_160000__sim__cross__pulse-direct-real-rr__n100__r01"
                ),
                "failed_run_manifest_sha256": (
                    "6860d9d13ac0a65ea6d9476277ea9f5f4289fd359792d8861364518b4f1804a5"
                ),
                "failure_stage": "governed_child_execution_or_publication",
                "failure_reason_stage": "frontend_pa_cache_miss_required_existing",
            },
        )
        self.assertEqual(
            hashlib.sha256(FAILED_R01_CAMPAIGN.read_bytes()).hexdigest(),
            failed_r01["content_sha256"],
        )

    def test_public_execute_rejects_historical_campaign_in_all_modes_without_output(
        self,
    ) -> None:
        execute = INTEGRATION / "workflows/family_source_closure/execute.ps1"
        historical_campaigns = (
            HISTORICAL_CAMPAIGN,
            FAILED_DIRECT_CAMPAIGN,
            FAILED_R01_CAMPAIGN,
        )
        artifact_root = REPO_ROOT.parent / "artifacts" / "projects" / (
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        )

        def children(path: Path) -> set[str]:
            return {item.name for item in path.iterdir()} if path.is_dir() else set()

        scratch_before = children(artifact_root / "scratch")
        runs_before = children(artifact_root / "runs")
        with tempfile.TemporaryDirectory() as directory:
            prepare_output = Path(directory) / "historical_prepare_must_not_exist"
            for historical_campaign in historical_campaigns:
                campaign = json.loads(historical_campaign.read_text(encoding="utf-8"))
                experiment_id = campaign["experiments"][0]["experiment_id"]
                campaign_sha256_before = hashlib.sha256(historical_campaign.read_bytes()).hexdigest()
                invocations = (
                    ["-ValidateOnly"],
                    ["-PrepareOnly", "-OutputDirectory", str(prepare_output)],
                    ["-SolverAuthorized"],
                )
                for mode_arguments in invocations:
                    with self.subTest(campaign=historical_campaign.name, mode=mode_arguments[0]):
                        completed = subprocess.run(
                            [
                                "pwsh", "-NoProfile", "-File", str(execute),
                                "-Campaign", str(historical_campaign.relative_to(REPO_ROOT)),
                                "-ExperimentId", experiment_id,
                                *mode_arguments,
                            ],
                            cwd=REPO_ROOT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            capture_output=True,
                            check=False,
                        )
                        output = completed.stdout + completed.stderr
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn("non-executable historical evidence", output)
                        self.assertNotIn("CAMPAIGN_SOURCE_BINDINGS", output)
                self.assertEqual(
                    campaign_sha256_before,
                    hashlib.sha256(historical_campaign.read_bytes()).hexdigest(),
                )
            self.assertFalse(prepare_output.exists())
        self.assertEqual(scratch_before, children(artifact_root / "scratch"))
        self.assertEqual(runs_before, children(artifact_root / "runs"))

    def test_all_legacy_arms_have_one_explicit_disposition(self) -> None:
        contract = json.loads(MIGRATION.read_text(encoding="utf-8"))
        self.assertEqual(
            contract["role"],
            "rf_oatof_family_source_closure_legacy_attribution_migration",
        )
        self.assertEqual(
            contract["active_workflow"],
            "workflows/family_source_closure/execute.ps1",
        )
        self.assertEqual(
            contract["active_adapter"],
            "workflows/family_source_closure/adapter.ps1",
        )
        arms = contract["legacy_arms"]
        self.assertEqual(
            [arm["arm_id"] for arm in arms],
            [
                "observed_restart_control", "ideal_acceleration_position",
                "ideal_transverse_positions", "ideal_multipole_axis_position",
                "remove_acceleration_covariance", "monoenergetic",
                "current_layout_ideal_source", "current_layout_ideal_1mm_vz0",
                "current_layout_ideal_1mm_linear_z_vz",
                "current_layout_ideal_finite_interval_linear_z_vz",
                "current_layout_ideal_finite_interval_axis_linear_z_vz",
                "current_layout_ideal_axis_2p2mm_linear_z_vz",
                "formal_ideal_source", "formal_positions_observed_velocities",
                "observed_positions_formal_kinematics",
                "observed_positions_axialized_velocities",
                "observed_positions_formal_energy_observed_directions",
                "ideal_acceleration_position_remove_covariance",
                "collapse_acceleration_velocity_residual",
                "ideal_acceleration_position_preserve_observed_linear_slope",
                "delay_pulse_one_eighth_rf_period",
                "delay_pulse_one_quarter_rf_period",
                "collapsed_acceleration_phase_space_upper_bound",
            ],
        )
        self.assertEqual(
            {arm["disposition"] for arm in arms},
            {"supported_by_family_contract", "retired_synthetic_transform"},
        )
        for arm in arms:
            if arm["disposition"] == "supported_by_family_contract":
                self.assertTrue(
                    "successor_authority" in arm or "successor_profile_id" in arm
                )
                if "successor_profile_id" in arm:
                    registry = json.loads(
                        (INTEGRATION / arm["successor_profile_registry"]).read_text(
                            encoding="utf-8"
                        )
                    )
                    profiles = {
                        profile["profile_id"]: profile
                        for profile in registry["source_materialization_profiles"]
                    }
                    profile = profiles[arm["successor_profile_id"]]
                    self.assertEqual(
                        profile["materialization_mode"],
                        "resolved_layout_pulse_ideal_linear_z_vz",
                    )
                    self.assertEqual(profile["kinetic_energy_eV"], 10.0)
                    expected_width = (
                        1.0 if "1mm" in arm["successor_profile_id"] else 2.2
                    )
                    self.assertEqual(profile["source_full_width_mm"], expected_width)
                    if "zero_vz" in arm["successor_profile_id"]:
                        self.assertEqual(profile["mean_velocity_z_m_per_s"], 0.0)
                        self.assertEqual(
                            profile["velocity_z_slope_m_per_s_per_mm"], 0.0
                        )
                        self.assertEqual(
                            profile["phase_space_authority"],
                            "source_condition:canonical_zero_mean_zero_slope_v1",
                        )
                    else:
                        self.assertEqual(
                            profile["phase_space_authority"],
                            "config/accelerator_phase_space_match.json",
                        )
            else:
                self.assertFalse(any(key.startswith("successor_") for key in arm))

    def test_second_runner_and_synthetic_implementation_are_absent(self) -> None:
        for relative in (
            "workflows/resolution_attribution/execute.ps1",
            "analysis/resolution_attribution_counterfactual.py",
            "config/resolution_attribution_counterfactual.json",
            "tests/test_resolution_attribution_counterfactual.py",
        ):
            self.assertFalse((INTEGRATION / relative).exists(), relative)

    def test_formal_teleport_negative_gate_remains(self) -> None:
        gate = (
            INTEGRATION.parents[1]
            / "projects/single_reflection_oa_tof_mass_analyzer/workflows/"
            "formal_reference/verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Assert-NotContains", gate)
        self.assertIn("teleport", gate.lower())


if __name__ == "__main__":
    unittest.main()
