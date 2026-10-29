import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts import artifact_retention as retention_owner

from common.contracts.artifact_retention import (
    apply_retention,
    classify_file,
    load_failed_recovery_exemptions,
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

    def test_resume_retention_uses_original_plan_after_unrecorded_unlink(self) -> None:
        self.write_config("compact", None)
        first, second = self.run / "first.pa0", self.run / "second.pa0"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        proof = self.run / "completion.json"
        proof.write_text('{"writers":"stopped"}', encoding="utf-8")
        writer = retention_owner.write_json_atomic

        def fail_progress(path, value):
            if value.get("status") == "pending" and value.get("removed_file_count") == 1:
                raise OSError("fixture retention progress publication failed")
            writer(path, value)

        with mock.patch.object(retention_owner, "write_json_atomic", fail_progress):
            with self.assertRaisesRegex(OSError, "progress publication"):
                apply_retention(self.config, recovery_inputs=[proof])
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        receipt = self.run / "retention_actions.json"
        prior = json.loads(receipt.read_text())
        self.assertEqual(prior["removed_file_count"], 0)
        apply_retention(self.config, recovery_inputs=[proof], resume=True)
        self.assertFalse(second.exists())
        done = receipt.read_bytes()
        action = json.loads(done)
        self.assertEqual(action["removed"], prior["removed"])
        self.assertEqual((action["removed_file_count"], action["removed_bytes"]), (2, 11))
        apply_retention(self.config, recovery_inputs=[proof], resume=True)
        self.assertEqual(receipt.read_bytes(), done)

    def test_resume_retention_rejects_changed_proof_or_extra_removal_before_mutation(self) -> None:
        self.write_config("compact", None)
        payload = self.run / "field.pa0"
        payload.write_bytes(b"field")
        proof = self.run / "completion.json"
        proof.write_text("original", encoding="utf-8")
        with mock.patch.object(retention_owner, "remove_recorded_files", side_effect=OSError("fixture before unlink")):
            with self.assertRaises(OSError):
                apply_retention(self.config, recovery_inputs=[proof])
        receipt = self.run / "retention_actions.json"
        original = receipt.read_bytes()
        proof.write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "recovery input"):
            apply_retention(self.config, recovery_inputs=[proof], resume=True)
        proof.write_text("original", encoding="utf-8")
        new_payload = self.run / "unplanned.pa0"
        new_payload.write_bytes(b"new")
        with self.assertRaisesRegex(ValueError, "outside.*plan"):
            apply_retention(self.config, recovery_inputs=[proof], resume=True)
        self.assertEqual(receipt.read_bytes(), original)
        self.assertEqual(payload.read_bytes(), b"field")
        self.assertEqual(new_payload.read_bytes(), b"new")

    def test_resume_retention_rejects_corrupt_plan_progress_and_terminal_mutation(self) -> None:
        self.write_config("compact", None)
        payload = self.run / "field.pa0"
        payload.write_bytes(b"field")
        proof = self.run / "completion.json"
        proof.write_text("original", encoding="utf-8")
        with mock.patch.object(retention_owner, "remove_recorded_files", side_effect=OSError("before unlink")):
            with self.assertRaises(OSError):
                apply_retention(self.config, recovery_inputs=[proof])
        receipt = self.run / "retention_actions.json"
        original = json.loads(receipt.read_text())
        for label in ("duplicate", "escape", "counter", "preflight", "terminal"):
            with self.subTest(label=label):
                changed = json.loads(json.dumps(original))
                if label == "duplicate": changed["removed"] *= 2
                elif label == "escape": changed["removed"][0]["path"] = "../field.pa0"
                elif label == "counter": changed["removed_file_count"] = 1
                elif label == "preflight": changed["status"] = "preflight_pending"
                else: (self.run / "run_manifest.json").write_text('{"status":"success"}', encoding="utf-8")
                receipt.write_text(json.dumps(changed), encoding="utf-8")
                before = receipt.read_bytes()
                with self.assertRaises(ValueError):
                    apply_retention(self.config, recovery_inputs=[proof], resume=True)
                self.assertEqual(receipt.read_bytes(), before)
                self.assertEqual(payload.read_bytes(), b"field")

    def test_retention_atomic_json_respects_aggregate_run_byte_ceiling(self) -> None:
        self.write_config("compact", None)
        payload = self.run / "field.pa0"
        payload.write_bytes(b"field")
        proof = self.run / "completion.json"
        proof.write_text("original", encoding="utf-8")
        baseline = sum(path.stat().st_size for path in self.run.iterdir())
        with self.assertRaisesRegex(ValueError, "admitted run byte ceiling"):
            apply_retention(self.config, recovery_inputs=[proof], maximum_run_bytes=baseline)
        self.assertFalse((self.run / "retention_actions.json").exists())
        self.assertEqual(payload.read_bytes(), b"field")

    def test_frozen_iob_template_survives_compact_but_solved_pa_does_not(self) -> None:
        self.write_config("compact", None)
        seeds = [self.run / f"inputs/runtime_snapshot/common/simion/assets/iob_instance_seeds/iob_seed_placeholder_{slot:02d}.pa0"
                 for slot in range(1, 6)]
        solved = self.run / "simion/processor.pa0"
        lookalike = self.run / "simion/iob_seed_placeholder_02.pa0"
        for path in (*seeds, solved, lookalike):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        for seed in seeds:
            self.assertEqual(classify_file(seed), "required_evidence")
        self.assertEqual(classify_file(solved), "solver_native_binary")
        self.assertEqual(classify_file(lookalike), "solver_native_binary")
        apply_retention(self.config)
        self.assertTrue(all(seed.is_file() for seed in seeds))
        self.assertFalse(solved.exists())
        self.assertFalse(lookalike.exists())

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

    def test_apply_compact_removes_read_only_run_local_pa_copy(self) -> None:
        self.write_config("compact", None)
        pa = self.run / "simion" / "copied_response.pa1"
        pa.parent.mkdir()
        pa.write_bytes(b"response")
        pa.chmod(stat.S_IREAD)

        action_path = apply_retention(self.config)

        self.assertFalse(pa.exists())
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 1)
        self.assertEqual(action["removed"][0]["retention_role"], "solver_native_binary")

    def test_compact_keeps_small_gui_workbench_without_pa_payloads(self) -> None:
        self.write_config("compact", None)
        workbench = self.run / "simion" / "gui_workbench"
        workbench.mkdir(parents=True)
        iob = workbench / "candidate.iob"
        fly2 = workbench / "candidate.fly2"
        lua = workbench / "candidate.lua"
        pa = workbench / "candidate.pa0"
        iob.write_bytes(b"small workbench\n")
        fly2.write_text("particles { }\n", encoding="utf-8")
        lua.write_text("return {}\n", encoding="utf-8")
        pa.write_bytes(b"rebuildable field payload")

        action_path = apply_retention(self.config)

        self.assertTrue(iob.exists())
        self.assertTrue(fly2.exists())
        self.assertTrue(lua.exists())
        self.assertFalse(pa.exists())
        self.assertEqual(classify_file(iob), "lightweight_optional")
        self.assertEqual(classify_file(fly2), "lightweight_optional")
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 1)
        self.assertEqual(action["removed"][0]["path"], "simion/gui_workbench/candidate.pa0")
        self.assertEqual(action["removed"][0]["retention_role"], "solver_native_binary")

    def test_compact_removes_rebuildable_simion_trj_cache(self) -> None:
        self.write_config("compact", None)
        simion = self.run / "simion"
        simion.mkdir()
        trajectory_cache = simion / "trj7.tmp"
        trajectory_cache.write_bytes(b"rebuildable trajectory cache")

        action_path = apply_retention(self.config)

        self.assertFalse(trajectory_cache.exists())
        self.assertEqual(classify_file(trajectory_cache), "dense_trajectory")
        action = json.loads(action_path.read_text(encoding="utf-8"))
        self.assertEqual(action["removed_file_count"], 1)
        self.assertEqual(action["removed"][0]["path"], "simion/trj7.tmp")
        self.assertEqual(action["removed"][0]["retention_role"], "dense_trajectory")

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
        self.assertEqual(classify_file(trace), "dense_trajectory")
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

    def test_malformed_recovery_stdout_fails_before_any_deletion_or_receipt(self) -> None:
        self.write_config("compact", None)
        stdout = self.run / "logs/simion__batch01.stdout.log"
        stdout.parent.mkdir()
        pa = self.run / "simion/field.pa0"
        pa.parent.mkdir()
        pa.write_bytes(b"existing rebuildable field")
        for line in ("status,Fly completed.", "status,Fly completed. invalid",
                     "status,Fly completed. 1 splats trailing", "status,Fly completed. 1 splats, nan seconds"):
            with self.subTest(line=line):
                stdout.write_text(line + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "completed SIMION batch log"):
                    apply_retention(self.config, preserve_paths=[stdout], failed_run=True)
                self.assertEqual(pa.read_bytes(), b"existing rebuildable field")
                self.assertTrue(stdout.is_file())
                self.assertFalse((self.run / "retention_actions.json").exists())

    def test_failed_cleanup_discards_unselected_batch_logs_but_keeps_other_diagnostics(self) -> None:
        self.write_config("compact", None)
        logs = self.run / "logs"
        logs.mkdir()
        trace = logs / "simion__batch01.trace.log"
        trace.write_text("status,Fly completed.\n", encoding="utf-8")
        stdout = logs / "simion__batch02.stdout.log"
        stdout.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
        diagnostic = logs / "builder.stderr.log"
        diagnostic.write_text("original diagnostic\n", encoding="utf-8")
        apply_retention(self.config, preserve_paths=[trace], failed_run=True)
        self.assertTrue(trace.is_file())
        self.assertFalse(stdout.exists())
        self.assertEqual(diagnostic.read_text(encoding="utf-8"), "original diagnostic\n")

    def test_recovery_receipt_readback_uses_the_same_strict_native_parser(self) -> None:
        self.write_config("compact", None)
        stdout = self.run / "logs/simion__batch01.stdout.log"
        stdout.parent.mkdir()
        stdout.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
        action_path = apply_retention(self.config, preserve_paths=[stdout])
        stdout.write_text("status,Fly completed. invalid\n", encoding="utf-8")
        action = json.loads(action_path.read_text(encoding="utf-8"))
        action["preserved"][0]["bytes"] = stdout.stat().st_size
        action_path.write_text(json.dumps(action), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "recovery TRACE differs"):
            load_failed_recovery_exemptions(self.run, validate_retention({
                "policy_version": 1, "class": "compact", "reason": None,
            }))

    def test_retention_cli_supports_bare_file_and_root_bound_module_entrypoints(self) -> None:
        for module in (False, True):
            with self.subTest(module=module):
                environment = dict(os.environ, PYTHONNOUSERSITE="1")
                environment.pop("PYTHONPATH", None)
                if module:
                    environment["PYTHONPATH"] = str(REPO_ROOT)
                run = self.run.parent / f"cli_{module}"
                logs = run / "logs"
                logs.mkdir(parents=True)
                self.write_config("compact", None)
                config = run / "run_config.json"
                config.write_bytes(self.config.read_bytes())
                stdout = logs / "simion__batch01.stdout.log"
                stdout.write_text("status,Fly completed. 1 splats\n", encoding="utf-8")
                entry = (["-m", "common.contracts.artifact_retention"] if module else
                         [str(REPO_ROOT / "common/contracts/artifact_retention.py")])
                result = subprocess.run(
                    [sys.executable, *entry, "apply", "--run-config", str(config),
                     "--failed-run", "--preserve-path", str(stdout)],
                    cwd=self.temporary.name, env=environment, capture_output=True,
                    text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(stdout.is_file())
                self.assertTrue((run / "retention_actions.json").is_file())

    def test_direct_file_missing_fixed_adapter_fails_without_deleting_payload(self) -> None:
        self.write_config("compact", None)
        copy = Path(self.temporary.name) / "frozen/common/contracts"
        copy.mkdir(parents=True)
        for name in ("artifact_retention.py", "artifact_retention.json", "recorded_file_removal.py", "file_identity.py"):
            shutil.copyfile(REPO_ROOT / "common/contracts" / name, copy / name)
        payload = self.run / "field.pa0"
        payload.write_bytes(b"original field")
        environment = dict(os.environ, PYTHONNOUSERSITE="1")
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, str(copy / "artifact_retention.py"), "apply",
             "--run-config", str(self.config), "--failed-run"],
            cwd=self.temporary.name, env=environment, capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("native_completion.py", result.stderr)
        self.assertEqual(payload.read_bytes(), b"original field")
        self.assertFalse((self.run / "retention_actions.json").exists())

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
        self.assertIn("dense_trajectory", writer.stderr)

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

    def test_capacity_gate_has_no_retired_baseline_or_raw_budget_compatibility(self) -> None:
        support = (Path(__file__).with_name("run_artifact_support.ps1")).read_text(
            encoding="utf-8-sig"
        )
        for retired in (
            "KnownMeasuredBytes", "MaximumNewArtifactBytes",
            "CapacityBaselineReceipt", "RequiredHeadroomBytes",
            "legacy-gate-adapter", "BudgetMode",
        ):
            self.assertNotIn(retired, support)
        self.assertIn(
            "[ValidateSet('startup','maintenance')][string]$ExecutionMode='startup'",
            support,
        )
        self.assertIn("'--execution-mode',$ExecutionMode", support)

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
        self.assertIn("[IO.FileOptions]::WriteThrough", support)
        self.assertIn("$writeStream.Flush($true)", support)

    def test_multipole_solver_runners_apply_frozen_retention_before_manifest(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (
                REPO_ROOT / "projects" / "rf_multipole_ion_optics" / "runtime" / name
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

    def test_every_production_new_run_package_caller_enables_capacity_lifecycle(self) -> None:
        callers: dict[str, str] = {}
        for root in ("common", "projects", "integrations"):
            for path in (REPO_ROOT / root).rglob("*.ps1"):
                source = path.read_text(encoding="utf-8-sig")
                if (
                    "New-RunPackage" in source
                    and path.name != "run_artifact_support.ps1"
                    and not path.name.startswith("test_")
                ):
                    callers[path.relative_to(REPO_ROOT).as_posix()] = source
        self.assertTrue(callers)
        for relative, source in callers.items():
            with self.subTest(caller=relative):
                self.assertIn("-RetentionContractEnabled", source)
                self.assertIn("-CapacityLedgerLifecycleEnabled", source)


if __name__ == "__main__":
    unittest.main()
