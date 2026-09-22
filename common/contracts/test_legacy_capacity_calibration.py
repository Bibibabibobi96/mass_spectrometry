from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.legacy_capacity_calibration import (
    CalibrationError,
    build_calibration_inventory,
    initialize_from_inventory,
    load_existing_calibration_report,
    main,
)


KEY = "A" * 64
GENERATION = "B" * 64


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_common_cache(root: Path) -> None:
    key = root / "common" / "simion" / "pa_family_cache" / KEY
    generation = key / "generations" / GENERATION
    generation.mkdir(parents=True)
    payload = generation / "field.pa0"
    payload.write_bytes(b"field")
    _write_json(key / "current_generation.json", {
        "schema_version": 1,
        "cache_key": KEY,
        "generation_sha256": GENERATION,
        "generation_relative_path": f"generations/{GENERATION}",
    })
    _write_json(generation / "cache_manifest.json", {
        "schema_version": 2,
        "role": "simion_pa_family_cache",
        "cache_key": KEY,
        "generation_sha256": GENERATION,
        "files": [{"name": payload.name, "bytes": 5, "sha256": "C" * 64}],
    })


def _write_compact_run(root: Path, *, heavy: bool = False) -> Path:
    run = root / "projects" / "instrument" / "runs" / "20260920_120000__test__python__fixture"
    retention = {"policy_version": 1, "class": "compact", "reason": None}
    _write_json(run / "run_config.json", {
        "schema_version": 2, "artifact_retention": retention,
    })
    _write_json(run / "summary.json", {"schema_version": 1, "status": "success"})
    _write_json(run / "run_manifest.json", {
        "schema_version": 2, "status": "success", "artifact_retention": retention,
    })
    if heavy:
        (run / "simion").mkdir()
        (run / "simion" / "field.pa0").write_bytes(b"large-by-contract")
    return run


def _write_basis_cache(root: Path) -> Path:
    key = root / "projects" / "instrument" / "cache" / "simion_pa_basis" / KEY
    key.mkdir(parents=True)
    payload = key / "basis.pa0"
    payload.write_bytes(b"basis")
    _write_json(key / "manifest.json", {
        "schema_version": 1,
        "role": "multipole_simion_pa_basis_cache",
        "fingerprint_sha256": KEY,
        "files": [{"name": payload.name, "bytes": 5, "sha256": "C" * 64}],
    })
    return key


def _write_direct_integration_cache(root: Path) -> Path:
    key = root / "projects" / "instrument" / "cache" / "verified_pulse" / KEY
    key.mkdir(parents=True)
    _write_json(key / "verified_pulse_timing_receipt.json", {
        "schema_version": 1,
        "role": "rf_oatof_verified_pulse_timing_receipt",
        "status": "success",
        "reusable_verified_pulse": True,
        "content_key": KEY,
    })
    return key


def _write_frozen_input_cache(root: Path) -> Path:
    key = (
        root / "projects" / "instrument" / "cache"
        / "native_corridor_frozen_inputs" / KEY
    )
    key.mkdir(parents=True)
    payload = key / "plan.json"
    payload.write_bytes(b"plan")
    _write_json(key / "native_corridor_freeze_manifest.json", {
        "schema_version": 1,
        "role": "mrtof_native_corridor_frozen_inputs",
        "status": "frozen",
        "pa_family_cache_key": KEY,
        "files": [{"name": payload.name, "bytes": 4, "sha256": "C" * 64}],
    })
    return key


class LegacyCapacityCalibrationTests(unittest.TestCase):
    def test_existing_external_report_initialization_uses_no_scan_or_payload_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            workspace = parent / "workspace"
            (workspace / "scratch").mkdir(parents=True)
            (workspace / "generated").mkdir()
            (workspace / "scratch" / "checkpoint.bin").write_bytes(b"scratch")
            report = parent / "completed-capacity-report.json"
            inventory = build_calibration_inventory(
                root, workspace_root=workspace, review_deadline="2026-09-29",
            )
            _write_json(report, inventory)
            stdout, stderr = io.StringIO(), io.StringIO()
            arguments = [
                "legacy_capacity_calibration",
                "--artifact-root", str(root),
                "--workspace-root", str(workspace),
                "--review-deadline", "2026-09-29",
                "--initialize-from-report", str(report),
            ]
            with (
                mock.patch(
                    "common.contracts.legacy_capacity_calibration.build_calibration_inventory",
                    side_effect=AssertionError("existing report initialization must not scan"),
                ),
                mock.patch(
                    "common.contracts.legacy_capacity_calibration.initialize_from_inventory",
                    return_value={},
                ) as initialize,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                mock.patch.object(sys, "argv", arguments),
            ):
                main()
            initialize.assert_called_once()
            self.assertFalse((root / "common" / "capacity_ledger.json").exists())
            events = [json.loads(line)["event"] for line in stderr.getvalue().splitlines()]
            self.assertEqual(events, [
                "existing_calibration_report_initialization_started",
                "ledger_initialized_from_existing_report",
            ])
            self.assertEqual(json.loads(stdout.getvalue())["status"], "ready_to_initialize")

    def test_existing_report_rejects_identity_scope_and_metadata_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            workspace = parent / "workspace"
            workspace.mkdir()
            inventory = build_calibration_inventory(
                root, workspace_root=workspace, review_deadline="2026-09-29",
            )
            report = parent / "completed-capacity-report.json"
            _write_json(report, inventory)
            with self.subTest("accepted"):
                loaded = load_existing_calibration_report(
                    report, artifact_root=root, workspace_root=workspace,
                    review_deadline="2026-09-29",
                )
                self.assertEqual(loaded, inventory)
            cases = {
                "schema": {"schema_version": 2},
                "role": {"role": "wrong"},
                "status": {"status": "calibration_pending"},
                "root": {"artifact_root": str(parent / "other-artifacts")},
                "deadline": {"review_deadline": "2026-09-30"},
                "not_metadata_only": {"metadata_only": False},
                "hashed": {"payload_hashes_computed": True},
            }
            for name, change in cases.items():
                with self.subTest(name):
                    candidate = {**inventory, **change}
                    _write_json(report, candidate)
                    with self.assertRaises(CalibrationError):
                        load_existing_calibration_report(
                            report, artifact_root=root, workspace_root=workspace,
                            review_deadline="2026-09-29",
                        )
            with self.subTest("workspace_scope"):
                candidate = {**inventory, "external_scopes": [
                    {**inventory["external_scopes"][0], "path": str(parent / "wrong")},
                    inventory["external_scopes"][1],
                ]}
                _write_json(report, candidate)
                with self.assertRaisesRegex(CalibrationError, "external scopes"):
                    load_existing_calibration_report(
                        report, artifact_root=root, workspace_root=workspace,
                        review_deadline="2026-09-29",
                    )
            with self.subTest("in_root"):
                in_root = root / "common" / "capacity_calibration" / "report.json"
                _write_json(in_root, inventory)
                with self.assertRaisesRegex(CalibrationError, "external calibration report"):
                    load_existing_calibration_report(
                        in_root, artifact_root=root, workspace_root=workspace,
                        review_deadline="2026-09-29",
                    )

    def test_existing_report_preserves_initialization_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            workspace = parent / "workspace"
            workspace.mkdir()
            inventory = build_calibration_inventory(
                root, workspace_root=workspace, review_deadline="2026-09-29",
            )
            inventory["initialization_blocker_count"] = 1
            inventory["initialization_blockers"] = [{"reason": "fixture"}]
            report = parent / "blocked-capacity-report.json"
            _write_json(report, inventory)
            loaded = load_existing_calibration_report(
                report, artifact_root=root, workspace_root=workspace,
                review_deadline="2026-09-29",
            )
            with self.assertRaisesRegex(CalibrationError, "initialization_blocker_count=1"):
                initialize_from_inventory(loaded)

    def test_metadata_inventory_can_initialize_only_when_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            _write_common_cache(root)
            run = _write_compact_run(root)
            basis = _write_basis_cache(root)
            direct_cache = _write_direct_integration_cache(root)
            frozen_cache = _write_frozen_input_cache(root)
            (root / "projects" / "instrument" / "00_README.txt").write_text("navigation")
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27",
            )
            self.assertEqual(inventory["status"], "ready_to_initialize")
            self.assertEqual(inventory["unresolved_count"], 0)
            by_path = {item["path"]: item for item in inventory["objects"]}
            cache_path = f"common/simion/pa_family_cache/{KEY}"
            self.assertEqual(by_path[cache_path]["class"], "published_cache")
            self.assertEqual(by_path[cache_path]["identity"], GENERATION)
            self.assertEqual(by_path[cache_path]["status"], "writing")
            self.assertEqual(by_path[cache_path]["owner"], "common.simion.pa_family_cache")
            self.assertEqual(
                by_path[cache_path]["recovery_reason"],
                "legacy_pa_cache_missing_owner_transaction",
            )
            self.assertEqual(
                by_path[run.relative_to(root).as_posix()]["class"], "light_evidence",
            )
            self.assertFalse(by_path[run.relative_to(root).as_posix()]["pin"])
            self.assertEqual(
                by_path[basis.relative_to(root).as_posix()]["class"], "published_cache",
            )
            self.assertEqual(
                by_path[direct_cache.relative_to(root).as_posix()]["class"],
                "published_cache",
            )
            self.assertEqual(
                by_path[frozen_cache.relative_to(root).as_posix()]["class"],
                "published_cache",
            )
            ledger = initialize_from_inventory(inventory)
            self.assertTrue(ledger["complete"])
            self.assertEqual(ledger["resident_bytes"], inventory["resident_bytes"])

    def test_mixed_compact_run_is_split_into_disjoint_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run = _write_compact_run(root, heavy=True)
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27",
            )
            self.assertEqual(inventory["status"], "ready_to_initialize")
            self.assertEqual(inventory["unresolved_count"], 0)
            by_path = {item["path"]: item for item in inventory["objects"]}
            heavy = (run / "simion" / "field.pa0").relative_to(root).as_posix()
            self.assertEqual(by_path[heavy]["class"], "rebuildable_payload")
            config = (run / "run_config.json").relative_to(root).as_posix()
            self.assertEqual(by_path[config]["class"], "light_evidence")

    def test_heavy_solver_review_is_split_without_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run = _write_compact_run(root, heavy=True)
            retention = {
                "policy_version": 1,
                "class": "solver_review",
                "reason": "GUI review fixture",
            }
            config_path = run / "run_config.json"
            manifest_path = run / "run_manifest.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            config["artifact_retention"] = retention
            manifest["artifact_retention"] = retention
            _write_json(config_path, config)
            _write_json(manifest_path, manifest)
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27",
            )
            self.assertEqual(inventory["unresolved_count"], 0)
            heavy = next(
                item for item in inventory["objects"]
                if item["path"].endswith("field.pa0")
            )
            self.assertEqual(heavy["class"], "rebuildable_payload")
            self.assertFalse(heavy["pin"])

    def test_heavy_qualification_run_is_explicitly_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run = _write_compact_run(root, heavy=True)
            retention = {
                "policy_version": 1,
                "class": "qualification",
                "reason": "frozen convergence reference",
            }
            for name in ("run_config.json", "run_manifest.json"):
                path = run / name
                document = json.loads(path.read_text(encoding="utf-8"))
                document["artifact_retention"] = retention
                _write_json(path, document)
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27",
            )
            self.assertEqual(inventory["object_count"], 1)
            self.assertTrue(inventory["objects"][0]["pin"])
            self.assertEqual(inventory["objects"][0]["class"], "light_evidence")

    def test_unproven_review_and_stale_ledger_temp_remain_actionable_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            common = root / "common"
            common.mkdir(parents=True)
            (common / "capacity_ledger.json").write_text("{}", encoding="utf-8")
            (common / ".capacity_ledger.json.fixture").write_bytes(b"stale")
            for project in ("orthogonal_accelerator", "parallel_mirror_dual_stripe_mr_tof"):
                review = root / "projects" / project / "reviews" / "current"
                review.mkdir(parents=True)
                _write_json(review / "inspection_receipt.json", {
                    "role": "readonly_inspection", "status": "ready",
                })
                (review / "copied.pa0").write_bytes(b"payload")
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            pending = {item["path"]: item for item in inventory["unresolved"]}
            temp = pending["common/.capacity_ledger.json.fixture"]
            self.assertEqual(temp["owner_hint"], "common.capacity_ledger")
            self.assertEqual(temp["reason"], "stale_capacity_ledger_atomic_temp_requires_recovery")
            self.assertIn("atomic publication lineage", temp["recovery_task"])
            for project in ("orthogonal_accelerator", "parallel_mirror_dual_stripe_mr_tof"):
                item = pending[f"projects/{project}/reviews"]
                self.assertEqual(item["owner_hint"], project)
                self.assertEqual(item["reason"], "review_package_lacks_sealed_owner_disposition_manifest")
                self.assertIn("sealed review-package manifest", item["recovery_task"])

    def test_invalid_frozen_input_cache_remains_actionable_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            key = "A" * 64
            cache = root / "projects" / "instrument" / "cache" / "native_corridor_frozen_inputs" / key
            cache.mkdir(parents=True)
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            self.assertEqual(inventory["object_count"], 0)
            self.assertEqual(inventory["unresolved_count"], 1)
            item = inventory["unresolved"][0]
            self.assertEqual(item["reason"], "frozen_input_cache_manifest_or_member_metadata_differs")
            self.assertEqual(item["owner_hint"], "instrument")
            self.assertIn("restore the frozen-input manifest", item["recovery_task"])

    def test_pa_runtime_roots_are_accounted_with_explicit_recovery_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            transactions = root / "common" / "simion" / "pa_family_cache" / ".transactions"
            locks = root / "common" / "simion" / "pa_family_cache" / ".locks"
            transactions.mkdir(parents=True)
            locks.mkdir()
            (transactions / "partial.pa0").write_bytes(b"transaction")
            (locks / "builder.lock").write_bytes(b"lock")
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            by_path = {item["path"]: item for item in inventory["objects"]}
            for name in (
                "common/simion/pa_family_cache/.transactions",
                "common/simion/pa_family_cache/.locks",
            ):
                self.assertEqual(by_path[name]["status"], "writing")
                self.assertEqual(by_path[name]["owner_hint"], "common.simion.pa_family_cache")
                self.assertEqual(by_path[name]["class"], "rebuildable_payload")
            self.assertEqual(inventory["unresolved_count"], 0)

    def test_workspace_scratch_and_generated_are_external_ledger_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            workspace = parent / "simulation_repo"
            (workspace / "scratch").mkdir(parents=True)
            (workspace / "generated").mkdir()
            (workspace / "scratch" / "checkpoint.bin").write_bytes(b"scratch")
            (workspace / "generated" / "derived.pa0").write_bytes(b"generated")
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27", workspace_root=workspace,
            )
            self.assertEqual(inventory["external_scope_bytes"], len(b"scratchgenerated"))
            self.assertEqual(
                {item["role"] for item in inventory["external_scopes"]},
                {"repository_scratch", "repository_generated"},
            )
            ledger = initialize_from_inventory(inventory)
            self.assertEqual(ledger["resident_bytes"], len(b"scratchgenerated"))
            self.assertEqual(ledger["external_scopes"], inventory["external_scopes"])

    def test_top_level_scratch_and_generated_are_counted_as_recoverable_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            scratch = root / "scratch"
            generated = root / "generated"
            scratch.mkdir(parents=True)
            generated.mkdir()
            (scratch / "interrupted.pa0").write_bytes(b"scratch")
            (generated / "response.pa0").write_bytes(b"generated")
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            by_path = {item["path"]: item for item in inventory["objects"]}
            for name in ("scratch", "generated"):
                self.assertEqual(by_path[name]["class"], "rebuildable_payload")
                self.assertEqual(by_path[name]["status"], "writing")
                self.assertEqual(by_path[name]["owner_hint"], "artifact_root_maintainer")
            self.assertEqual(inventory["unresolved_count"], 0)
            self.assertEqual(inventory["resident_bytes"], len(b"scratchgenerated"))

    def test_scratch_and_unknown_cache_provider_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            scratch = root / "projects" / "instrument" / "scratch" / "task"
            scratch.mkdir(parents=True)
            (scratch / "state.bin").write_bytes(b"data")
            (scratch / "field.pa0").write_bytes(b"field")
            (scratch / "runtime.lua").write_text("return {}")
            _write_json(scratch / "root_cause.json", {
                "schema_version": 1,
                "role": "fixture_root_cause",
            })
            unknown = root / "projects" / "instrument" / "cache" / "unknown" / KEY
            unknown.mkdir(parents=True)
            (unknown / "payload.bin").write_bytes(b"cache")
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27",
            )
            reasons = {item["reason"] for item in inventory["unresolved"]}
            self.assertEqual(inventory["unresolved_count"], 1)
            self.assertIn("project_cache_provider_or_layout_unrecognized", reasons)
            for item in inventory["unresolved"]:
                self.assertTrue(item["path"])
                self.assertGreater(item["bytes"], 0)
                self.assertTrue(item["owner_hint"])
                self.assertEqual(item["review_deadline"], "2026-09-27")
            scratch_heavy = next(
                item for item in inventory["objects"]
                if item["path"].endswith("field.pa0")
            )
            self.assertEqual(scratch_heavy["class"], "rebuildable_payload")
            self.assertEqual(scratch_heavy["status"], "ready")
            runtime = next(
                item for item in inventory["objects"]
                if item["path"].endswith("runtime.lua")
            )
            evidence = next(
                item for item in inventory["objects"]
                if item["path"].endswith("root_cause.json")
            )
            self.assertEqual(runtime["class"], "rebuildable_payload")
            self.assertEqual(evidence["class"], "light_evidence")
            self.assertEqual(inventory["initialization_blocker_count"], 0)

    def test_manifest_member_size_mismatch_is_unresolved_without_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            _write_common_cache(root)
            manifest_path = (
                root / "common" / "simion" / "pa_family_cache" / KEY
                / "generations" / GENERATION / "cache_manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["bytes"] = 999
            _write_json(manifest_path, manifest)
            with mock.patch(
                "common.contracts.file_identity.file_sha256",
                side_effect=AssertionError("payload hashing is forbidden"),
            ):
                inventory = build_calibration_inventory(
                    root, review_deadline="2026-09-27",
                )
            self.assertEqual(inventory["unresolved_count"], 1)
            self.assertEqual(
                inventory["unresolved"][0]["reason"],
                "common_pa_cache_identity_chain_incomplete",
            )

    def test_known_scratch_engineering_source_is_pinned_for_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            source = (
                root / "projects" / "parallel_mirror_dual_stripe_mr_tof"
                / "scratch" / "20260902__ion-foil-recovery" / "foil.SLDPRT"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"engineering source")
            inventory = build_calibration_inventory(
                root, review_deadline="2026-09-27",
            )
            record = inventory["objects"][0]
            self.assertEqual(record["class"], "light_evidence")
            self.assertTrue(record["pin"])
            self.assertIn("pending promotion", record["pin_reason"])

    def test_overdue_pending_inventory_reports_count_and_blocks_initialize(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            unknown = root / "projects" / "instrument" / "cache" / "unknown" / KEY
            unknown.mkdir(parents=True)
            (unknown / "payload.bin").write_bytes(b"cache")
            inventory = build_calibration_inventory(
                root, review_deadline="2000-01-01",
            )
            self.assertEqual(inventory["status"], "calibration_review_overdue")
            self.assertEqual(inventory["expired_unresolved_count"], 1)
            with self.assertRaisesRegex(
                CalibrationError, "expired_unresolved_count=1",
            ):
                initialize_from_inventory(inventory)

    def test_legacy_and_incomplete_runs_are_split_with_safe_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            legacy = _write_compact_run(root, heavy=True)
            config_path = legacy / "run_config.json"
            manifest_path = legacy / "run_manifest.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            config["schema_version"] = 1
            config.pop("artifact_retention")
            manifest["schema_version"] = 1
            manifest.pop("artifact_retention")
            _write_json(config_path, config)
            _write_json(manifest_path, manifest)
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            self.assertEqual(inventory["unresolved_count"], 0)
            heavy = next(
                item for item in inventory["objects"]
                if item["path"].endswith("field.pa0")
            )
            self.assertEqual(heavy["class"], "rebuildable_payload")
            self.assertEqual(heavy["status"], "ready")

            (legacy / "summary.json").unlink()
            incomplete = build_calibration_inventory(root, review_deadline="2026-09-27")
            self.assertEqual(incomplete["unresolved_count"], 0)
            self.assertTrue(incomplete["complete"])
            self.assertEqual(incomplete["status"], "ready_to_initialize")
            self.assertEqual(incomplete["initialization_blocker_count"], 0)
            self.assertTrue(incomplete["objects"])
            self.assertTrue(all(item["status"] == "writing" for item in incomplete["objects"]))
            ledger = initialize_from_inventory(incomplete)
            self.assertTrue(all(item["owner"] for item in ledger["objects"]))
            self.assertTrue(all(item["recovery_reason"] for item in ledger["objects"]))
            self.assertTrue(all(
                item["review_deadline"] == "2026-09-27"
                for item in ledger["objects"]
            ))

    def test_invalid_archive_and_known_legacy_evidence_are_pinned_for_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            project = root / "projects" / "instrument"
            archive = project / "archive" / "legacy"
            archive.mkdir(parents=True)
            (archive / "evidence.txt").write_text("evidence")
            evidence = project / "paper1_stage_evidence"
            evidence.mkdir()
            (evidence / "report.json").write_text("{}")
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            self.assertEqual(inventory["unresolved_count"], 0)
            self.assertEqual(inventory["object_count"], 2)
            self.assertTrue(all(item["pin"] for item in inventory["objects"]))
            self.assertTrue(all("2026-09-27" in item["pin_reason"] for item in inventory["objects"]))

    def test_active_structured_reference_keeps_terminal_payload_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            source = _write_compact_run(root, heavy=True)
            retention = {
                "policy_version": 1,
                "class": "solver_review",
                "reason": "GUI review fixture",
            }
            for name in ("run_config.json", "run_manifest.json"):
                path = source / name
                document = json.loads(path.read_text(encoding="utf-8"))
                document["artifact_retention"] = retention
                _write_json(path, document)
            active = source.parent / "20260920_130000__test__python__consumer"
            heavy = source / "simion" / "field.pa0"
            _write_json(active / "run_config.json", {
                "schema_version": 1,
                "source_pa": str(heavy),
            })
            _write_json(active / "summary.json", {"status": "checkpoint"})
            _write_json(active / "run_manifest.json", {
                "schema_version": 1,
                "status": "checkpoint",
            })
            inventory = build_calibration_inventory(root, review_deadline="2026-09-27")
            record = next(
                item for item in inventory["objects"]
                if item["path"] == heavy.relative_to(root).as_posix()
            )
            self.assertEqual(record["status"], "writing")
            self.assertEqual(
                record["active_protection"],
                "structured_nonterminal_run_reference",
            )
            self.assertEqual(
                record["active_consumers"],
                [active.relative_to(root).as_posix()],
            )
            self.assertEqual(record["owner"], record["owner_hint"])
            self.assertEqual(record["review_deadline"], "2026-09-27")
            self.assertTrue(record["recovery_reason"])
            self.assertEqual(inventory["active_reference_protected_object_count"], 1)
            self.assertEqual(inventory["recovery_required_count"], 2)
            self.assertTrue(inventory["complete"])
            self.assertEqual(inventory["status"], "ready_to_initialize")
            self.assertEqual(inventory["initialization_blocker_count"], 0)
            ledger = initialize_from_inventory(inventory)
            ledger_record = next(
                item for item in ledger["objects"] if item["path"] == record["path"]
            )
            self.assertEqual(
                ledger_record["consumers"], [active.relative_to(root).as_posix()],
            )

    def test_overdue_writing_recovery_blocks_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run = _write_compact_run(root, heavy=True)
            (run / "summary.json").unlink()
            inventory = build_calibration_inventory(
                root, review_deadline="2000-01-01",
            )
            self.assertFalse(inventory["complete"])
            self.assertEqual(inventory["status"], "calibration_review_overdue")
            self.assertGreater(inventory["expired_initialization_blocker_count"], 0)
            with self.assertRaisesRegex(
                CalibrationError, "invalid_or_overdue_writing_count",
            ):
                initialize_from_inventory(inventory)

    def test_cli_writes_pending_report_before_rejecting_ledger_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            workspace = parent / "workspace"
            report = parent / "capacity-report.json"
            unknown = root / "projects" / "instrument" / "cache" / "unknown" / KEY
            unknown.mkdir(parents=True)
            (unknown / "payload.bin").write_bytes(b"cache")
            workspace.mkdir()
            stdout, stderr = io.StringIO(), io.StringIO()
            arguments = [
                "legacy_capacity_calibration",
                "--artifact-root", str(root),
                "--workspace-root", str(workspace),
                "--review-deadline", "2026-09-29",
                "--report", str(report),
                "--initialize-ledger",
            ]
            with (
                mock.patch.object(sys, "argv", arguments),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as exited,
            ):
                main()
            self.assertEqual(exited.exception.code, 2)
            self.assertTrue(report.is_file())
            inventory = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(inventory["unresolved_count"], 1)
            events = [json.loads(line)["event"] for line in stderr.getvalue().splitlines()]
            self.assertEqual(events[0], "calibration_started")
            self.assertIn("scan_artifact_root_entry", events)
            self.assertIn("calibration_report_written", events)
            self.assertEqual(events[-1], "ledger_initialization_rejected")
            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse((root / "common" / "capacity_ledger.json").exists())


if __name__ == "__main__":
    unittest.main()
