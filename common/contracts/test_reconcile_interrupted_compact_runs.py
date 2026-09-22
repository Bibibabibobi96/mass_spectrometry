import json
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.contracts.capacity_ledger import initialize_capacity_ledger
from common.contracts import reconcile_interrupted_compact_runs as reconciliation
from common.contracts.reconcile_interrupted_compact_runs import reconcile, summarize
from common.contracts.capacity_protection import create_capacity_protection_lease


class InterruptedCompactReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.artifact_root = Path(self.temporary.name) / "artifacts"
        self.runs = self.artifact_root / "projects" / "fixture_project" / "runs"
        self.run = self.runs / "20260828_190000__test__simion__interrupted-compact"
        self.run.mkdir(parents=True)
        initialize_capacity_ledger(self.artifact_root, objects=[])
        config = {"schema_version": 2, "run_id": self.run.name, "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None}}
        (self.run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        (self.run / "summary.json").write_text('{"status":"interrupted"}\n', encoding="utf-8")
        def record(path: Path) -> dict[str, object]:
            return {"path": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        manifest = {"status": "interrupted", "run_config": record(self.run / "run_config.json"), "inputs": {}, "outputs": [record(self.run / "summary.json")]}
        (self.run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_consumer(self, name: str, source: Path, *, status: str = "checkpoint") -> Path:
        consumer = self.runs / name
        consumer.mkdir()
        (consumer / "run_config.json").write_text(
            json.dumps({"run_id": consumer.name, "source_file": str(source)}),
            encoding="utf-8",
        )
        (consumer / "run_manifest.json").write_text(
            json.dumps({"run_id": consumer.name, "status": status}),
            encoding="utf-8",
        )
        return consumer

    def test_plan_and_apply_remove_only_unrecorded_heavy_payload(self) -> None:
        pa = self.run / "field.pa0"
        pa.write_bytes(b"solver")
        trajectory = self.run / "trajectory_samples.csv"
        trajectory.write_text("x,y\n", encoding="utf-8")
        plan = reconcile(self.runs, apply=False)[0]
        self.assertTrue(plan["eligible"])
        self.assertEqual(plan["removable_file_count"], 2)
        self.assertTrue(pa.exists())
        # This temporary fixture has no solver; do not observe unrelated host jobs.
        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
        ):
            result = reconcile(self.runs, apply=True)[0]
        self.assertTrue(result["applied"])
        self.assertFalse(pa.exists())
        self.assertFalse(trajectory.exists())
        self.assertTrue((self.run / "summary.json").exists())
        self.assertTrue((self.run / "retention_actions.json").exists())

    def test_active_capacity_lease_blocks_reconciliation(self) -> None:
        payload = self.run / "field.pa0"
        payload.write_bytes(b"solver")
        create_capacity_protection_lease(
            self.artifact_root, lease_id="retention-test", owner="unit test",
            ttl_seconds=3600, protected_paths=[self.run],
        )
        report = reconcile(self.runs, apply=False)[0]
        self.assertFalse(report["eligible"])
        self.assertIn("capacity protection lease", report["reason"])
        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
            self.assertRaisesRegex(ValueError, "capacity protection lease"),
        ):
            reconciliation.apply_run(self.run)
        self.assertTrue(payload.exists())

    def test_apply_rechecks_newly_recorded_payload(self) -> None:
        payload = self.run / "field.pa0"
        payload.write_bytes(b"solver")
        self.assertTrue(reconcile(self.runs, apply=False)[0]["eligible"])
        path = self.run / "run_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["outputs"].append({"path": payload.name, "bytes": 6, "sha256": file_sha256(payload)})
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
            self.assertRaisesRegex(ValueError, "manifest-recorded"),
        ):
            reconciliation.apply_run(self.run)
        self.assertTrue(payload.exists())

    def test_refuses_success_manifest(self) -> None:
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "success"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertFalse(reconcile(self.runs, apply=False)[0]["eligible"])

    def test_accepts_terminal_failed_compact_run(self) -> None:
        summary_path = self.run / "summary.json"
        summary_path.write_text('{"status":"failed"}\n', encoding="utf-8")
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "failed"
        manifest["outputs"] = [{
            "path": "summary.json",
            "bytes": summary_path.stat().st_size,
            "sha256": file_sha256(summary_path),
        }]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.run / "failed_field.pa0").write_bytes(b"solver")

        report = reconciliation.inspect_run(self.run)

        self.assertTrue(report["eligible"])
        self.assertEqual(report["terminal_status"], "failed")

    def test_checkpoint_requires_normal_terminalization(self) -> None:
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "checkpoint"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        report = reconcile(self.runs, apply=False)[0]

        self.assertFalse(report["eligible"])
        self.assertIn("normal terminalization", report["reason"])

        with (
            patch.object(
                sys, "argv", ["reconcile", "--run-dir", str(self.run), "--apply"]
            ),
            self.assertRaisesRegex(ValueError, "normal terminalization"),
        ):
            reconciliation.main()

    def test_apply_run_requires_shared_host_lease_before_scanning(self) -> None:
        (self.run / "field.pa0").write_bytes(b"solver")
        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: ""}),
            patch.object(reconciliation, "inspect_run") as inspect,
            self.assertRaisesRegex(RuntimeError, "shared HostExecutionLease"),
        ):
            reconciliation.apply_run(self.run)
        inspect.assert_not_called()

    def test_refuses_noncompact_or_noninterrupted_summary(self) -> None:
        config_path = self.run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["artifact_retention"]["class"] = "qualification"
        config["artifact_retention"]["reason"] = "test noncompact class"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"] = {
            "path": "run_config.json",
            "bytes": config_path.stat().st_size,
            "sha256": file_sha256(config_path),
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        noncompact = reconcile(self.runs, apply=False)[0]
        self.assertFalse(noncompact["eligible"])
        self.assertIn("only compact runs", noncompact["reason"])

        config["artifact_retention"]["class"] = "compact"
        config["artifact_retention"]["reason"] = None
        config_path.write_text(json.dumps(config), encoding="utf-8")
        (self.run / "summary.json").write_text('{"status":"running"}\n', encoding="utf-8")
        noninterrupted_summary = reconcile(self.runs, apply=False)[0]
        self.assertFalse(noninterrupted_summary["eligible"])
        self.assertIn("summary status must match", noninterrupted_summary["reason"])

    def test_manifest_drift_requires_explicit_opt_in(self) -> None:
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pa = self.run / "field.pa0"
        pa.write_bytes(b"solver")
        self.assertFalse(reconcile(self.runs, apply=False)[0]["eligible"])
        report = reconcile(self.runs, apply=False, permit_manifest_drift=True)[0]
        self.assertTrue(report["eligible"])
        self.assertEqual(report["manifest_integrity"], "degraded_manifest_drift")

    def test_apply_limit_leaves_later_eligible_run_untouched(self) -> None:
        second = self.runs / "20260828_190001__test__simion__interrupted-compact"
        second.mkdir()
        for name in ("run_config.json", "summary.json", "run_manifest.json"):
            (second / name).write_bytes((self.run / name).read_bytes())
        # Make the second directory a self-consistent copy with its own ID.
        config = json.loads((second / "run_config.json").read_text(encoding="utf-8")); config["run_id"] = second.name
        (second / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        def record(path: Path) -> dict[str, object]: return {"path": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        (second / "run_manifest.json").write_text(json.dumps({"status":"interrupted","run_config":record(second / "run_config.json"),"inputs":{},"outputs":[record(second / "summary.json")]}), encoding="utf-8")
        (self.run / "first.pa0").write_bytes(b"a")
        (second / "second.pa0").write_bytes(b"b")
        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
        ):
            reconcile(self.runs, apply=True, max_apply_runs=1)
        self.assertEqual(sum(path.exists() for path in (self.run / "first.pa0", second / "second.pa0")), 1)

    def test_summary_does_not_include_per_run_payload(self) -> None:
        (self.run / "field.pa0").write_bytes(b"solver")
        receipt = summarize(reconcile(self.runs, apply=False), apply=False)
        self.assertEqual(receipt["scanned_run_count"], 1)
        self.assertEqual(receipt["eligible_runs"], 1)
        self.assertEqual(receipt["removable_bytes"], len(b"solver"))
        self.assertNotIn("runs", receipt)

    def test_scan_does_not_read_large_payload_contents(self) -> None:
        payload = self.run / "large_payload.pa0"
        payload.write_bytes(b"x" * (1024 * 1024))
        original_read_text = Path.read_text

        def reject_payload_read(path: Path, *args: object, **kwargs: object) -> str:
            if path == payload:
                self.fail("startup scan must not read payload contents")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=reject_payload_read):
            report = reconcile(self.runs, apply=False)[0]
        self.assertTrue(report["eligible"])
        self.assertEqual(report["removable_file_count"], 1)

    def test_active_direct_file_reference_skips_only_that_heavy_payload(self) -> None:
        occupied = self.run / "occupied.pa0"
        removable = self.run / "unreferenced.pa0"
        occupied.write_bytes(b"occupied")
        removable.write_bytes(b"removable")
        self._write_consumer(
            "20260828_200000__test__python__active-consumer", occupied
        )

        report = reconciliation.inspect_run(self.run, verify_manifest_records=False)

        self.assertEqual(
            [item["path"] for item in report["occupied"]], ["occupied.pa0"]
        )
        self.assertEqual(
            [item["path"] for item in report["removable"]], ["unreferenced.pa0"]
        )
        self.assertEqual(report["removable_bytes"], len(b"removable"))

    def test_active_light_file_reference_does_not_pin_unrelated_heavy_payload(self) -> None:
        heavy = self.run / "field.pa0"
        heavy.write_bytes(b"solver")
        self._write_consumer(
            "20260828_200001__test__python__light-consumer",
            self.run / "summary.json",
        )

        report = reconciliation.inspect_run(self.run, verify_manifest_records=False)

        self.assertEqual(report["occupied"], [])
        self.assertEqual([item["path"] for item in report["removable"]], ["field.pa0"])

    def test_terminal_direct_file_reference_is_audit_not_occupancy(self) -> None:
        heavy = self.run / "field.pa0"
        heavy.write_bytes(b"solver")
        self._write_consumer(
            "20260828_200002__test__python__historical-consumer",
            heavy,
            status="success",
        )

        report = reconciliation.inspect_run(self.run, verify_manifest_records=False)

        self.assertEqual(report["occupied"], [])
        self.assertEqual(len(report["historical_references"]), 1)

    def test_external_manifest_input_is_verified_read_only_and_never_removed(self) -> None:
        external = Path(self.temporary.name) / "frozen-parent.json"
        external.write_text('{"parent":true}\n', encoding="utf-8")
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"]["parent"] = {
            "path": str(external),
            "bytes": external.stat().st_size,
            "sha256": file_sha256(external),
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        heavy = self.run / "field.pa0"
        heavy.write_bytes(b"solver")

        report = reconciliation.inspect_run(self.run)

        self.assertEqual([item["path"] for item in report["removable"]], ["field.pa0"])
        self.assertTrue(external.is_file())

    def test_unrelated_active_simion_is_not_a_global_apply_blocker(self) -> None:
        payload = self.run / "field.pa0"
        payload.write_bytes(b"solver")
        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
        ):
            result = reconcile(self.runs, apply=True)[0]
        self.assertTrue(result["applied"])
        self.assertFalse(payload.exists())

    def test_apply_preserves_light_files_triad_and_writes_receipt(self) -> None:
        heavy = self.run / "field.pa0"
        light = self.run / "notes.json"
        log = self.run / "logs" / "stdout.log"
        heavy.write_bytes(b"solver")
        light.write_text('{"note":"retain"}\n', encoding="utf-8")
        log.parent.mkdir()
        log.write_text("diagnostic\n", encoding="utf-8")

        with (
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
        ):
            reconciliation.apply_run(self.run)

        self.assertFalse(heavy.exists())
        for path in (
            light, log, self.run / "run_config.json", self.run / "summary.json",
            self.run / "run_manifest.json", self.run / "retention_actions.json",
        ):
            self.assertTrue(path.exists(), path)

    def test_run_dir_cli_plans_and_applies_only_the_exact_top_level_run(self) -> None:
        sibling = self.runs / "20260828_190001__test__simion__interrupted-compact"
        sibling.mkdir()
        (self.run / "selected.pa0").write_bytes(b"selected")
        (sibling / "unrelated.pa0").write_bytes(b"unrelated")
        stdout = io.StringIO()

        with (
            patch.object(sys, "argv", ["reconcile", "--run-dir", str(self.run)]),
            patch("sys.stdout", stdout),
        ):
            reconciliation.main()

        receipt = json.loads(stdout.getvalue())
        self.assertEqual(receipt["scanned_run_count"], 1)
        self.assertEqual(receipt["runs"][0]["run_dir"], str(self.run.resolve()))
        self.assertNotIn(str(sibling), json.dumps(receipt))

        stdout = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["reconcile", "--run-dir", str(self.run), "--apply"]
            ),
            patch("sys.stdout", stdout),
            patch.dict(os.environ, {reconciliation.HOST_LEASE_OWNER_ENV: "123"}),
        ):
            reconciliation.main()
        applied = json.loads(stdout.getvalue())
        self.assertEqual(applied["applied_runs"], 1)
        self.assertFalse((self.run / "selected.pa0").exists())
        self.assertTrue((sibling / "unrelated.pa0").exists())

    def test_run_dir_rejects_non_project_top_level_shape(self) -> None:
        invalid = Path(self.temporary.name) / "runs" / self.run.name
        invalid.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "top-level projects"):
            reconciliation.inspect_run(invalid)

    def test_cli_summary_only_emits_aggregate_receipt(self) -> None:
        (self.run / "field.pa0").write_bytes(b"solver")
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["reconcile", "--run-root", str(self.runs), "--summary-only"]), patch("sys.stdout", stdout):
            reconciliation.main()
        receipt = json.loads(stdout.getvalue())
        self.assertFalse(receipt["apply"])
        self.assertEqual(receipt["scanned_run_count"], 1)
        self.assertEqual(receipt["eligible_runs"], 1)
        self.assertNotIn("runs", receipt)

    def test_cli_rejects_summary_only_apply_limit_without_apply(self) -> None:
        with patch.object(sys, "argv", ["reconcile", "--run-root", str(self.runs), "--summary-only", "--max-apply-runs", "1"]):
            with self.assertRaises(SystemExit) as error:
                reconciliation.main()
        self.assertEqual(error.exception.code, 2)
