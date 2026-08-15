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
CURRENT_BASELINE_CAMPAIGN = (
    INTEGRATION / "config/pulse_resolution_direct_baseline_successor_r09_campaign.json"
)
CURRENT_CANDIDATE_CAMPAIGN = (
    INTEGRATION / "config/pulse_resolution_direct_candidate_successor_r03_campaign.json"
)


class FamilySourceClosureLegacyAttributionMigrationTests(unittest.TestCase):
    def test_terminal_campaign_dispositions_bind_immutable_bytes_and_status(self) -> None:
        contract = json.loads(MIGRATION.read_text(encoding="utf-8"))
        historical = {
            Path(row["path"]).name: row for row in contract["historical_campaigns"]
        }
        failed_names = {
            "pulse_resolution_direct_baseline_successor_campaign.json",
            *{
                f"pulse_resolution_direct_baseline_successor_r{revision:02d}_campaign.json"
                for revision in range(2, 8)
            },
            "pulse_resolution_direct_candidate_successor_r01_campaign.json",
            "pulse_resolution_direct_candidate_successor_r02_campaign.json",
        }
        self.assertEqual(
            {
                name
                for name, row in historical.items()
                if row.get("external_status") == "failed"
            }
            & failed_names,
            failed_names,
        )
        current = {
            Path(row["path"]).name: row
            for row in contract["current_evidence_campaigns"]
        }
        self.assertEqual(
            {
                name: (row["external_status"], row["disposition"])
                for name, row in current.items()
            },
            {
                CURRENT_BASELINE_CAMPAIGN.name: (
                    "published_evidence", "non_executable_published_evidence"
                ),
                CURRENT_CANDIDATE_CAMPAIGN.name: (
                    "completed", "non_executable_completed_evidence"
                ),
            },
        )
        for row in (*contract["historical_campaigns"], *current.values()):
            campaign = REPO_ROOT / row["path"]
            self.assertEqual(
                hashlib.sha256(campaign.read_bytes()).hexdigest(),
                row["content_sha256"],
            )
        historical_head = contract["historical_campaigns"][0]
        head_blob = subprocess.run(
            ["git", "rev-parse", f"HEAD:{historical_head['path']}"],
            cwd=REPO_ROOT, text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()
        self.assertEqual(head_blob, historical_head["head_blob_sha1"])

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
                        self.assertIn("registered non-executable evidence", output)
                        self.assertNotIn("CAMPAIGN_SOURCE_BINDINGS", output)
                self.assertEqual(
                    campaign_sha256_before,
                    hashlib.sha256(historical_campaign.read_bytes()).hexdigest(),
                )
            self.assertFalse(prepare_output.exists())
        self.assertEqual(scratch_before, children(artifact_root / "scratch"))
        self.assertEqual(runs_before, children(artifact_root / "runs"))

    def test_all_terminal_authorized_campaigns_are_non_executable(self) -> None:
        contract = json.loads(MIGRATION.read_text(encoding="utf-8"))
        execute = INTEGRATION / "workflows/family_source_closure/execute.ps1"
        rows = [
            row
            for row in (
                *contract["historical_campaigns"],
                *contract["current_evidence_campaigns"],
            )
            if json.loads((REPO_ROOT / row["path"]).read_text(encoding="utf-8"))[
                "status"
            ] == "authorized"
        ]
        for row in rows:
            campaign_path = REPO_ROOT / row["path"]
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
            completed = subprocess.run(
                [
                    "pwsh", "-NoProfile", "-File", str(execute),
                    "-Campaign", row["path"],
                    "-ExperimentId", campaign["experiments"][0]["experiment_id"],
                    "-SolverAuthorized",
                ],
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            self.assertNotEqual(completed.returncode, 0, row["path"])
            self.assertIn("registered non-executable evidence", output)
            self.assertNotIn("CAMPAIGN_SOURCE_BINDINGS", output)

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
