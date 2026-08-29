import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.contracts import reconcile_interrupted_compact_runs as reconciliation
from common.contracts.reconcile_interrupted_compact_runs import reconcile, summarize


class InterruptedCompactReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.runs = Path(self.temporary.name) / "runs"
        self.run = self.runs / "20260828_190000__test__simion__interrupted-compact"
        self.run.mkdir(parents=True)
        config = {"schema_version": 2, "run_id": self.run.name, "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None}}
        (self.run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        (self.run / "summary.json").write_text('{"status":"interrupted"}\n', encoding="utf-8")
        def record(path: Path) -> dict[str, object]:
            return {"path": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        manifest = {"status": "interrupted", "run_config": record(self.run / "run_config.json"), "inputs": {}, "outputs": [record(self.run / "summary.json")]}
        (self.run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_and_apply_remove_only_unrecorded_heavy_payload(self) -> None:
        pa = self.run / "field.pa0"
        pa.write_bytes(b"solver")
        trajectory = self.run / "trajectory_samples.csv"
        trajectory.write_text("x,y\n", encoding="utf-8")
        plan = reconcile(self.runs, apply=False)[0]
        self.assertTrue(plan["eligible"])
        self.assertEqual(plan["removable_file_count"], 2)
        self.assertTrue(pa.exists())
        result = reconcile(self.runs, apply=True)[0]
        self.assertTrue(result["applied"])
        self.assertFalse(pa.exists())
        self.assertFalse(trajectory.exists())
        self.assertTrue((self.run / "summary.json").exists())
        self.assertTrue((self.run / "retention_actions.json").exists())

    def test_refuses_non_interrupted_or_manifest_recorded_payload(self) -> None:
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "success"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertFalse(reconcile(self.runs, apply=False)[0]["eligible"])

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
        self.assertIn("summary status must be interrupted", noninterrupted_summary["reason"])

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

    def test_active_simion_blocks_apply_before_any_run_scan(self) -> None:
        with (
            patch.object(reconciliation, "assert_no_active_simion", side_effect=RuntimeError("SIMION active")),
            patch.object(reconciliation, "inspect_run") as inspect,
        ):
            with self.assertRaisesRegex(RuntimeError, "SIMION active"):
                reconcile(self.runs, apply=True)
        inspect.assert_not_called()

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
