import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.artifact_retention import (
    apply_retention,
    classify_file,
    load_policy,
    validate_retained_files,
    validate_retention,
)

REPO_ROOT = Path(__file__).parents[2]
WRITER = Path(__file__).with_name("write_run_manifest.py")
VERIFIER = Path(__file__).with_name("verify_run_manifest.py")


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.run_id = "20260728_150000__test__repo__artifact-retention"
        self.run = Path(self.temporary.name) / "runs" / self.run_id
        self.run.mkdir(parents=True)
        self.config = self.run / "run_config.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(self, class_id: str, reason: str | None) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_id": self.run_id,
                    "artifact_retention": {
                        "policy_version": 1,
                        "class": class_id,
                        "reason": reason,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_default_class_is_compact(self) -> None:
        self.assertEqual(load_policy()["default_class"], "compact")

    def test_noncompact_class_requires_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a reason"):
            validate_retention(
                {"policy_version": 1, "class": "qualification", "reason": None}
            )

    def test_compact_rejects_solver_binary_and_dense_trajectory(self) -> None:
        retained = validate_retention(
            {"policy_version": 1, "class": "compact", "reason": None}
        )
        model = self.run / "model.mph"
        model.write_bytes(b"model")
        trajectory = self.run / "trajectory_samples.csv"
        trajectory.write_text("x,y\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "solver_native_binary"):
            validate_retained_files(retained, [model, trajectory])

    def test_apply_compact_removes_only_rebuildable_heavy_outputs(self) -> None:
        self.write_config("compact", None)
        model = self.run / "model.mph"
        model.write_bytes(b"model")
        pa = self.run / "array.pa0"
        pa.write_bytes(b"pa")
        trajectory = self.run / "trajectory_samples__primary.csv"
        trajectory.write_text("x,y\n", encoding="utf-8")
        metrics = self.run / "transport_metrics.json"
        metrics.write_text("{}\n", encoding="utf-8")

        action_path = apply_retention(self.config)

        self.assertFalse(model.exists())
        self.assertFalse(pa.exists())
        self.assertFalse(trajectory.exists())
        self.assertTrue(metrics.exists())
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 3)
        self.assertEqual(
            {item["retention_role"] for item in action["removed"]},
            {"solver_native_binary", "dense_trajectory"},
        )

    def test_failed_compact_can_retain_only_explicit_completed_native_trace(self) -> None:
        self.write_config("compact", None)
        logs = self.run / "logs"
        logs.mkdir()
        trace = logs / "simion__batch01.trace.log"
        with trace.open("wb") as stream:
            stream.seek(101 * 1024 * 1024)
            stream.write(b"\nstatus,Fly completed.\n")
        pa = self.run / "simion" / "frontend.pa0"
        pa.parent.mkdir()
        pa.write_bytes(b"pa")
        summary = self.run / "summary.json"
        summary.write_text("{}\n", encoding="utf-8")

        action_path = apply_retention(self.config, preserve_paths=[trace])

        self.assertTrue(trace.exists())
        self.assertFalse(pa.exists())
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["preserved"][0]["path"], "logs/simion__batch01.trace.log")
        self.assertEqual(classify_file(trace), "large_optional")
        writer = subprocess.run(
            [
                sys.executable, str(WRITER), "--run-config", str(self.config),
                "--status", "failed", "--output", str(summary),
            ], cwd=REPO_ROOT, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(writer.returncode, 0, writer.stderr)
        verifier = subprocess.run(
            [sys.executable, str(VERIFIER), str(self.run / "run_manifest.json"),
             "--require-status", "failed"],
            cwd=REPO_ROOT, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(verifier.returncode, 0, verifier.stderr)

    def test_success_manifest_does_not_accept_failed_recovery_exemption(self) -> None:
        self.write_config("compact", None)
        trace = self.run / "logs" / "simion__batch01.trace.log"
        trace.parent.mkdir()
        with trace.open("wb") as stream:
            stream.seek(101 * 1024 * 1024)
            stream.write(b"\nstatus,Fly completed.\n")
        apply_retention(self.config, preserve_paths=[trace])
        writer = subprocess.run(
            [
                sys.executable, str(WRITER), "--run-config", str(self.config),
                "--status", "success",
            ], cwd=REPO_ROOT, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertNotEqual(writer.returncode, 0)
        self.assertIn("large_optional", writer.stderr)

    def test_failed_compact_can_retain_completed_full_flight_stdout(self) -> None:
        self.write_config("compact", None)
        stdout = self.run / "logs" / "simion__batch01.stdout.log"
        stdout.parent.mkdir()
        with stdout.open("wb") as stream:
            stream.seek(101 * 1024 * 1024)
            stream.write(b"\nstatus,Fly completed. 500 splats, 10 seconds\n")
        summary = self.run / "summary.json"
        summary.write_text("{}\n", encoding="utf-8")
        action_path = apply_retention(self.config, preserve_paths=[stdout])
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertTrue(stdout.exists())
        self.assertEqual(
            action["preserved"][0]["action"],
            "retained_completed_simion_batch_log_for_recovery",
        )
        writer = subprocess.run(
            [sys.executable, str(WRITER), "--run-config", str(self.config),
             "--status", "failed", "--output", str(summary)],
            cwd=REPO_ROOT, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(writer.returncode, 0, writer.stderr)
        verifier = subprocess.run(
            [sys.executable, str(VERIFIER), str(self.run / "run_manifest.json"),
             "--require-status", "failed"],
            cwd=REPO_ROOT, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(verifier.returncode, 0, verifier.stderr)

    def test_failed_recovery_exemption_does_not_admit_other_large_file(self) -> None:
        self.write_config("compact", None)
        trace = self.run / "logs" / "simion__batch01.trace.log"
        trace.parent.mkdir()
        with trace.open("wb") as stream:
            stream.seek(101 * 1024 * 1024)
            stream.write(b"\nstatus,Fly completed.\n")
        apply_retention(self.config, preserve_paths=[trace])
        unrelated = self.run / "unrelated.bin"
        with unrelated.open("wb") as stream:
            stream.seek(101 * 1024 * 1024)
            stream.write(b"x")
        writer = subprocess.run(
            [
                sys.executable, str(WRITER), "--run-config", str(self.config),
                "--status", "failed",
            ], cwd=REPO_ROOT, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertNotEqual(writer.returncode, 0)
        self.assertIn("unrelated.bin (large_optional)", writer.stderr)

    def test_compact_rejects_unlisted_or_non_native_trace_preservation(self) -> None:
        self.write_config("compact", None)
        trace = self.run / "logs" / "trace.log"
        trace.parent.mkdir()
        trace.write_text("status,Fly completed.\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "native TRACE"):
            apply_retention(self.config, preserve_paths=[trace])

    def test_qualification_retains_heavy_outputs(self) -> None:
        self.write_config("qualification", "Frozen convergence review evidence.")
        model = self.run / "model.mph"
        model.write_bytes(b"model")
        trajectory = self.run / "trajectory_samples.csv"
        trajectory.write_text("x,y\n", encoding="utf-8")

        action_path = apply_retention(self.config)

        self.assertTrue(model.exists())
        self.assertTrue(trajectory.exists())
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 0)
        self.assertEqual(classify_file(model), "solver_native_binary")

    def test_pre_pulse_state_table_is_required_compact_handoff_evidence(self) -> None:
        self.write_config("compact", None)
        states = self.run / "pre_pulse_time_series_states.csv"
        states.write_bytes(b"0" * (101 * 1024 * 1024))

        action_path = apply_retention(self.config)

        self.assertTrue(states.exists())
        self.assertEqual(classify_file(states), "required_evidence")
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 0)

    def test_compressed_pre_pulse_state_table_is_required_compact_handoff_evidence(self) -> None:
        self.write_config("compact", None)
        states = self.run / "pre_pulse_time_series_states.csv.gz"
        states.write_bytes(b"0" * (101 * 1024 * 1024))

        action_path = apply_retention(self.config)

        self.assertTrue(states.exists())
        self.assertEqual(classify_file(states), "required_evidence")
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 0)

    def test_large_detector_blind_candidate_receipt_is_required_evidence(self) -> None:
        self.write_config("compact", None)
        receipt = self.run / "detector_blind_pulse_timing_candidate_receipt.json"
        receipt.write_bytes(b"0" * (101 * 1024 * 1024))

        action_path = apply_retention(self.config)

        self.assertTrue(receipt.exists())
        self.assertEqual(classify_file(receipt), "required_evidence")
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 0)

    def test_terminal_manifest_blocks_retention_mutation(self) -> None:
        self.write_config("compact", None)
        (self.run / "run_manifest.json").write_text(
            json.dumps({"status": "success"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "terminal manifest"):
            apply_retention(self.config)

    def test_v2_manifest_records_and_verifies_retention_role(self) -> None:
        self.write_config("compact", None)
        summary = self.run / "summary.json"
        summary.write_text("{}\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(WRITER),
                "--run-config",
                str(self.config),
                "--status",
                "success",
                "--output",
                str(summary),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.run / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["artifact_retention"]["class"], "compact")
        self.assertEqual(manifest["outputs"][0]["retention_role"], "required_evidence")
        verification = subprocess.run(
            [sys.executable, str(VERIFIER), str(self.run / "run_manifest.json")],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(verification.returncode, 0, verification.stderr)

    def test_v2_writer_rejects_unlisted_heavy_file(self) -> None:
        self.write_config("compact", None)
        (self.run / "unlisted.mph").write_bytes(b"model")
        result = subprocess.run(
            [
                sys.executable,
                str(WRITER),
                "--run-config",
                str(self.config),
                "--status",
                "success",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("solver_native_binary", result.stderr)

    def test_shared_run_lifecycle_exposes_opt_in_compact_v2(self) -> None:
        support = (Path(__file__).with_name("run_artifact_support.ps1")).read_text(
            encoding="utf-8-sig"
        )
        self.assertIn(
            "[ValidateSet('compact','qualification','solver_review')]"
            "[string]$RetentionClass='compact'",
            support.replace("\n", "").replace("\r", "").replace(" ", ""),
        )
        self.assertIn("[switch]$RetentionContractEnabled", support)
        self.assertIn("if($RetentionContractEnabled){2}else{1}", support)
        self.assertIn("Apply-RunArtifactRetention", support)

    def test_verified_input_copy_can_retry_but_requires_three_way_hash_identity(self) -> None:
        support = (Path(__file__).with_name("run_artifact_support.ps1")).read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("[ValidateRange(1,5)][int]$VerificationAttempts=1", support)
        self.assertIn("$sourceHashBefore", support)
        self.assertIn("$sourceHashAfter", support)
        self.assertIn("$destinationHash", support)
        self.assertIn("$sourceHashBefore-ceq$sourceHashAfter", support)
        self.assertIn("$sourceHashAfter-ceq$destinationHash", support)

    def test_multipole_solver_runners_apply_frozen_retention_before_manifest(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (
                Path(__file__).parents[1] / "multipole" / name
            ).read_text(encoding="utf-8-sig")
            compact = source.replace(" ", "")
            self.assertIn(
                "[ValidateSet('compact','qualification','solver_review')]"
                "[string]$RetentionClass='compact'",
                compact,
            )
            self.assertIn("artifact_retention=", source)
            self.assertIn("-RetentionContractEnabled", source)
            self.assertLess(
                source.index("Apply-RunArtifactRetention"),
                source.index("Write-VerifiedRunManifest", source.index("try{")),
            )

    def test_new_run_package_callers_are_explicitly_migrated_or_baselined(self) -> None:
        migrated = {
            "common/multipole/run_finite_3d_transport.ps1",
            "common/multipole/run_simion_finite_3d_transport.ps1",
            "common/multipole/run_simion_transport_campaign.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_three_component_candidate.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_three_component_center_flight.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_three_component_first_prism_flight.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_bounded_step.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_central_difference.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_voltage_definition.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_dual_stripe_operating_seed.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_dual_stripe_shape_diagnostic.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_mirror_exact_k_operating_point.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_mirror_l0_l1_candidate.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_two_prism_operating_point.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_accelerator_focus_flight.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_analyzer_local_center_flight.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_analyzer_local_interface_convergence.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_analyzer_local_pa_family.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_analyzer_local_portal_interface_convergence.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_analyzer_local_workbench.ps1",
            "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_two_prism_trial.ps1",
        }
        legacy = {
            "projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/run_n100_candidate_functional.ps1",
            "projects/single_reflection_oa_tof_mass_analyzer/tests/simion/run_n100_source_build_and_track.ps1",
            "projects/rf_quadrupole_ion_optics/runtime/cross_solver_analysis_lifecycle.ps1",
            "projects/rf_quadrupole_ion_optics/workflows/interface_readiness/run_comsol.ps1",
            "projects/rf_quadrupole_ion_optics/workflows/interface_readiness/run_simion.ps1",
            "projects/rf_quadrupole_ion_optics/workflows/mass_filter_reference/compare_responses.ps1",
            "projects/rf_quadrupole_ion_optics/workflows/mass_filter_reference/run_comsol.ps1",
            "projects/rf_quadrupole_ion_optics/workflows/mass_filter_reference/run_simion.ps1",
            "projects/rf_quadrupole_ion_optics/workflows/same_solver_convergence/run_comparison.ps1",
            "projects/transverse_helical_filament_wehnelt_electron_gun/run_build_only_smoke.ps1",
        }
        callers: dict[str, str] = {}
        for root in ("common", "projects"):
            for path in (REPO_ROOT / root).rglob("*.ps1"):
                source = path.read_text(encoding="utf-8-sig")
                if (
                    "New-RunPackage" in source
                    and path.name != "run_artifact_support.ps1"
                    and not path.name.startswith("test_")
                ):
                    callers[path.relative_to(REPO_ROOT).as_posix()] = source
        self.assertEqual(set(callers), migrated | legacy)
        for relative in migrated:
            self.assertIn("-RetentionContractEnabled", callers[relative])
        for relative in legacy:
            self.assertNotIn("-RetentionContractEnabled", callers[relative])


if __name__ == "__main__":
    unittest.main()
