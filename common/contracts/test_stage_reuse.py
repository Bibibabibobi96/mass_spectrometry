from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.file_identity import file_sha256, guarded_file_identity
from common.contracts import file_identity, stage_reuse
from common.contracts.stage_reuse import (
    StageReuseError,
    validate_and_write_stage_reuse,
    write_stage_receipt,
)


PARENT_ID = "20260727_120000__test__cross__stage-reuse-parent"
CHILD_ID = "20260727_130000__test__cross__stage-reuse-child"
PROJECT = "test_project"
STAGE = "comsol_candidate"


def manifest_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


class StageReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.parent = self.workspace / "runs" / PARENT_ID
        self.child = self.workspace / "runs" / CHILD_ID
        self.parent.mkdir(parents=True)
        self.child.mkdir(parents=True)
        self.parent_config = self.parent / "run_config.json"
        self.child_config = self.child / "run_config.json"
        self._write_json(
            self.parent_config,
            {"schema_version": 1, "run_id": PARENT_ID, "project": PROJECT},
        )
        self.summary = self.parent / "summary.json"
        self._write_summary("failed", "success")
        self.parent_context: dict[str, dict[str, Path]] = {}
        self.child_context: dict[str, dict[str, Path]] = {}
        for category in ("inputs", "source", "solver"):
            parent_file = self.parent / category / f"{category}_identity.json"
            child_file = self.child / category / f"{category}_identity.json"
            parent_file.parent.mkdir()
            child_file.parent.mkdir()
            parent_file.write_text(f"{category}\n", encoding="utf-8")
            child_file.write_bytes(parent_file.read_bytes())
            self.parent_context[category] = {f"{category}_identity": parent_file}
            self.child_context[category] = {f"{category}_identity": child_file}
        self._write_child_config()
        self.output = self.parent / "comsol" / "model.mph"
        self.output.parent.mkdir()
        self.output.write_bytes(b"solver-output")
        self.receipt = write_stage_receipt(
            self.parent,
            project=PROJECT,
            stage_id=STAGE,
            context=self.parent_context,
            outputs={"model": self.output},
        )
        self._write_manifest("failed")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def _write_summary(self, overall_status: str, stage_status: str) -> None:
        self._write_json(
            self.summary,
            {
                "schema_version": 1,
                "role": "test_summary",
                "status": overall_status,
                "stages": [{"stage_id": STAGE, "status": stage_status}],
            },
        )

    def _write_child_config(self, *, run_id: str = CHILD_ID) -> None:
        inputs = {
            name: str(path)
            for category in self.child_context.values()
            for name, path in category.items()
        }
        inputs["stage_reuse_provenance"] = str(
            self.child / "inputs" / "stage_reuse_provenance.json"
        )
        self._write_json(
            self.child_config,
            {
                "schema_version": 1,
                "run_id": run_id,
                "project": PROJECT,
                "inputs": inputs,
            },
        )

    def _all_outputs(self) -> list[Path]:
        return [
            self.summary,
            self.receipt,
            self.output,
            *[
                path
                for category in self.parent_context.values()
                for path in category.values()
            ],
        ]

    def _write_manifest(
        self,
        status: str,
        *,
        outputs: list[Path] | None = None,
    ) -> None:
        self._write_json(
            self.parent / "run_manifest.json",
            {
                "schema_version": 1,
                "role": "simulation_run_manifest",
                "run_id": PARENT_ID,
                "project": PROJECT,
                "status": status,
                "run_config": manifest_record(self.parent_config),
                "inputs": {},
                "outputs": [
                    manifest_record(path)
                    for path in (self._all_outputs() if outputs is None else outputs)
                ],
            },
        )

    def _validate(self) -> Path:
        return validate_and_write_stage_reuse(
            self.child,
            parent_run_root=self.parent,
            project=PROJECT,
            stage_contexts={STAGE: self.child_context},
        )

    @unittest.skipUnless(os.name == "nt", "requires Windows sustained identity guard")
    def test_owned_model_identity_spans_two_receipt_writes_and_reuse_without_rehash(self) -> None:
        native_stage = "comsol_native"
        (self.parent / "run_manifest.json").unlink()
        self._write_json(self.summary, {"status": "failed", "stages": [
            {"stage_id": native_stage, "status": "success"}, {"stage_id": STAGE, "status": "success"}]})
        with mock.patch.object(file_identity, "file_sha256", wraps=file_sha256) as establish:
            with guarded_file_identity(self.output) as guard:
                guards = {self.output.resolve(): guard}
                with mock.patch.object(stage_reuse, "file_sha256", wraps=file_sha256) as stage_hash:
                    receipts = [write_stage_receipt(self.parent, project=PROJECT, stage_id=stage,
                        context=self.parent_context, outputs={"model": self.output}, identity_guards=guards)
                        for stage in (native_stage, STAGE)]
                    model = {"path": str(self.output.resolve()), "bytes": guard.bytes_count, "sha256": guard.sha256}
                    self._write_json(self.parent / "run_manifest.json", {
                        "schema_version": 1, "role": "simulation_run_manifest", "run_id": PARENT_ID,
                        "project": PROJECT, "status": "failed", "run_config": manifest_record(self.parent_config),
                        "inputs": {}, "outputs": [model, manifest_record(self.summary),
                            *(manifest_record(path) for path in receipts),
                            *(manifest_record(path) for category in self.parent_context.values() for path in category.values())]})
                    provenance = validate_and_write_stage_reuse(self.child, parent_run_root=self.parent,
                        project=PROJECT, stage_contexts={native_stage: self.child_context, STAGE: self.child_context},
                        identity_guards=guards)
                    self.assertEqual({item["stage_id"] for item in json.loads(provenance.read_text())["reused_stages"]},
                                     {native_stage, STAGE})
                    self.assertEqual(sum(Path(call.args[0]).resolve() == self.output.resolve()
                        for call in stage_hash.call_args_list), 0)
                    for receipt in receipts:
                        actual = json.loads(receipt.read_text())["outputs"]["model"]
                        self.assertEqual((actual["bytes"], actual["sha256"]), (guard.bytes_count, guard.sha256))
            self.assertEqual(establish.call_count, 1)

    @unittest.skipUnless(os.name == "nt", "requires Windows sustained identity guard")
    def test_receipt_guard_rejects_expired_impostor_and_wrong_path_without_writing(self) -> None:
        before = self.receipt.read_bytes()
        def publish(guards):
            return write_stage_receipt(self.parent, project=PROJECT, stage_id=STAGE,
                context=self.parent_context, outputs={"model": self.output}, identity_guards=guards)
        with self.assertRaisesRegex(StageReuseError, "real FileIdentityGuard"):
            publish({self.output.resolve(): {"sha256": "0" * 64}})
        with guarded_file_identity(self.output) as guard:
            different = next(iter(self.parent_context["inputs"].values()))
            with self.assertRaisesRegex(StageReuseError, "guarded identity"):
                publish({different.resolve(): guard})
        with self.assertRaisesRegex(StageReuseError, "guarded identity"):
            publish({self.output.resolve(): guard})
        self.assertEqual(self.receipt.read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "requires Windows sustained identity guard")
    def test_guarded_output_hashes_once_and_unlisted_paths_keep_existing_checks(self) -> None:
        record = manifest_record(self.output)
        with mock.patch.object(file_identity, "file_sha256", wraps=file_sha256) as initial_hash:
            with guarded_file_identity(self.output, expected_bytes=record["bytes"], expected_sha256=record["sha256"]) as guard:
                with mock.patch.object(stage_reuse, "file_sha256", wraps=file_sha256) as stage_hash:
                    destination = validate_and_write_stage_reuse(
                        self.child, parent_run_root=self.parent, project=PROJECT,
                        stage_contexts={STAGE: self.child_context}, identity_guards={self.output.resolve(): guard},
                    )
                    self.assertTrue(destination.is_file())
                    for _ in range(3):
                        guard.assert_matches(self.output, expected_bytes=record["bytes"], expected_sha256=record["sha256"])
                    self.assertNotIn(self.output.resolve(), [Path(call.args[0]).resolve() for call in stage_hash.call_args_list])
                    self.assertIn(self.summary.resolve(), [Path(call.args[0]).resolve() for call in stage_hash.call_args_list])
            self.assertEqual(initial_hash.call_count, 1)
        # The old API still performs its own payload validation, not a global cache.
        with mock.patch.object(stage_reuse, "file_sha256", wraps=file_sha256) as stage_hash:
            self._validate()
            self.assertEqual(sum(Path(call.args[0]).resolve() == self.output.resolve() for call in stage_hash.call_args_list), 1)

    @unittest.skipUnless(os.name == "nt", "requires Windows sustained identity guard")
    def test_guard_mapping_rejects_impostors_expired_and_wrong_expected_identity(self) -> None:
        record = manifest_record(self.output)
        def validate(guards):
            return validate_and_write_stage_reuse(
                self.child, parent_run_root=self.parent, project=PROJECT,
                stage_contexts={STAGE: self.child_context}, identity_guards=guards,
            )
        for fake in ({"sha256": record["sha256"]}, lambda *args, **kwargs: None, None):
            with self.subTest(fake=type(fake).__name__):
                with self.assertRaises(StageReuseError):
                    validate({self.output.resolve(): fake})
        with guarded_file_identity(self.output, expected_bytes=record["bytes"], expected_sha256=record["sha256"]) as guard:
            with self.assertRaises(StageReuseError):
                validate({str(self.output.resolve()): guard})
            receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
            receipt["outputs"]["model"]["sha256"] = "0" * 64
            self._write_json(self.receipt, receipt)
            self._write_manifest("failed")
            with self.assertRaisesRegex(StageReuseError, "guarded identity"):
                validate({self.output.resolve(): guard})
        with self.assertRaisesRegex(StageReuseError, "guarded identity"):
            validate({self.output.resolve(): guard})
        self.assertFalse((self.child / "inputs/stage_reuse_provenance.json").exists())

    @unittest.skipUnless(os.name == "nt", "requires Windows sustained identity guard")
    def test_guard_does_not_replace_parent_manifest_binding(self) -> None:
        record = manifest_record(self.output)
        self._write_manifest("failed", outputs=[path for path in self._all_outputs() if path != self.output])
        with guarded_file_identity(self.output, expected_bytes=record["bytes"], expected_sha256=record["sha256"]) as guard:
            with self.assertRaisesRegex(StageReuseError, "not manifest-bound"):
                validate_and_write_stage_reuse(
                    self.child, parent_run_root=self.parent, project=PROJECT,
                    stage_contexts={STAGE: self.child_context}, identity_guards={self.output.resolve(): guard},
                )
        self.assertFalse((self.child / "inputs/stage_reuse_provenance.json").exists())

    def test_named_proofs_for_two_stages_do_not_overwrite_each_other(self) -> None:
        second_stage = "simion_candidate"
        (self.parent / "run_manifest.json").unlink()
        summary = json.loads(self.summary.read_text(encoding="utf-8"))
        summary["stages"].append({"stage_id": second_stage, "status": "success"})
        self._write_json(self.summary, summary)
        second_receipt = write_stage_receipt(
            self.parent, project=PROJECT, stage_id=second_stage,
            context=self.parent_context, outputs={"model": self.output},
        )
        self._write_manifest("failed", outputs=[*self._all_outputs(), second_receipt])
        config = json.loads(self.child_config.read_text(encoding="utf-8"))
        names = {stage: f"stage_reuse_{stage}_provenance" for stage in (STAGE, second_stage)}
        destinations = {stage: self.child / "inputs/stage_contexts" / stage / "reuse_provenance.json" for stage in names}
        config["inputs"].update({names[stage]: str(path) for stage, path in destinations.items()})
        self._write_json(self.child_config, config)
        first_bytes = None
        for stage in (STAGE, second_stage):
            actual = validate_and_write_stage_reuse(
                self.child, parent_run_root=self.parent, project=PROJECT,
                stage_contexts={stage: self.child_context}, provenance_input_name=names[stage],
            )
            self.assertEqual(actual, destinations[stage])
            proof = json.loads(actual.read_text(encoding="utf-8"))
            self.assertEqual([entry["stage_id"] for entry in proof["reused_stages"]], [stage])
            if stage == STAGE:
                first_bytes = actual.read_bytes()
        self.assertEqual(destinations[STAGE].read_bytes(), first_bytes)
        self.assertFalse((self.child / "inputs/stage_reuse_provenance.json").exists())

    def test_named_provenance_rejects_invalid_undeclared_escaped_and_duplicate_paths(self) -> None:
        original = json.loads(self.child_config.read_text(encoding="utf-8"))
        name = "stage_reuse_comsol_candidate_provenance"
        target = self.child / "inputs/named/proof.json"
        for scenario in ("invalid_name", "undeclared", "outside", "inputs_directory", "duplicate", "changed_default"):
            with self.subTest(scenario=scenario):
                config = json.loads(json.dumps(original))
                selected_name = name
                config["inputs"][name] = str(target)
                if scenario == "invalid_name":
                    selected_name = "invalid-name"
                elif scenario == "undeclared":
                    config["inputs"].pop(name)
                elif scenario == "outside":
                    config["inputs"][name] = str(self.workspace / "outside.json")
                elif scenario == "inputs_directory":
                    config["inputs"][name] = str(self.child / "inputs")
                elif scenario == "duplicate":
                    config["inputs"]["another_name"] = str(target)
                else:
                    selected_name = "stage_reuse_provenance"
                    config["inputs"][selected_name] = str(target)
                self._write_json(self.child_config, config)
                with self.assertRaises(StageReuseError):
                    validate_and_write_stage_reuse(
                        self.child, parent_run_root=self.parent, project=PROJECT,
                        stage_contexts={STAGE: self.child_context}, provenance_input_name=selected_name,
                    )
                self.assertFalse(target.exists())
                self.assertFalse((self.workspace / "outside.json").exists())

    def test_failed_named_stage_validation_does_not_create_proof_directory(self) -> None:
        name = "stage_reuse_comsol_candidate_provenance"
        target = self.child / "inputs/stage_contexts/comsol/reuse_provenance.json"
        config = json.loads(self.child_config.read_text(encoding="utf-8"))
        config["inputs"][name] = str(target)
        self._write_json(self.child_config, config)
        self.output.write_bytes(b"changed output")
        with self.assertRaises(StageReuseError):
            validate_and_write_stage_reuse(
                self.child, parent_run_root=self.parent, project=PROJECT,
                stage_contexts={STAGE: self.child_context}, provenance_input_name=name,
            )
        self.assertFalse(target.parent.exists())

    def test_failed_parent_with_successful_stage_writes_child_provenance(self) -> None:
        destination = self._validate()
        document = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(document["parent_run_id"], PARENT_ID)
        self.assertEqual(document["parent_run_status"], "failed")
        self.assertEqual(
            document["parent_manifest"]["sha256"],
            file_sha256(self.parent / "run_manifest.json"),
        )
        current_record = document["reused_stages"][0]["context"]["solver"][
            "solver_identity"
        ]["current"]
        self.assertEqual(current_record["path"], "solver/solver_identity.json")

    def test_success_parent_is_reusable(self) -> None:
        self._write_summary("success", "success")
        self._write_manifest("success")
        document = json.loads(self._validate().read_text(encoding="utf-8"))
        self.assertEqual(document["parent_run_status"], "success")

    def test_v2_parent_retention_and_completed_terminal_contract(self) -> None:
        for scenario in ("valid", "missing_retention", "different_retention", "wrong_config_schema", "pending_journal", "provisional", "wrong_output_role"):
            with self.subTest(scenario=scenario):
                retention = {"policy_version": 1, "class": "solver_review", "reason": "explicit stage reuse fixture"}
                config = json.loads(self.parent_config.read_text(encoding="utf-8"))
                config.update(schema_version=2, artifact_retention=retention)
                if scenario == "missing_retention":
                    del config["artifact_retention"]
                if scenario == "wrong_config_schema":
                    config["schema_version"] = 1
                self._write_json(self.parent_config, config)
                self._write_manifest("failed")
                manifest_path = self.parent / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.update(schema_version=2, artifact_retention=dict(retention))
                from common.contracts.artifact_retention import classify_file
                for record in manifest["outputs"]:
                    record["retention_role"] = classify_file(Path(record["path"]), bytes_count=record["bytes"])
                if scenario == "wrong_output_role":
                    manifest["outputs"][0]["retention_role"] = "invalid"
                if scenario == "different_retention":
                    manifest["artifact_retention"]["reason"] = "another reason"
                if scenario == "provisional":
                    manifest["status"] = "interrupted"
                    manifest["lifecycle_state"] = "provisional"
                self._write_json(manifest_path, manifest)
                journal = self.parent / ".run_terminal_publication.json"
                if scenario == "pending_journal":
                    self._write_json(journal, {})
                try:
                    if scenario == "valid":
                        result = self._validate()
                        self.assertEqual(json.loads(result.read_text(encoding="utf-8"))["parent_run_status"], "failed")
                        result.unlink()
                    else:
                        with self.assertRaises(StageReuseError):
                            self._validate()
                finally:
                    journal.unlink(missing_ok=True)

    def test_receipt_cannot_be_retroactively_added_to_finalized_run(self) -> None:
        with self.assertRaisesRegex(StageReuseError, "after the final run manifest"):
            write_stage_receipt(
                self.parent,
                project=PROJECT,
                stage_id=STAGE,
                context=self.parent_context,
                outputs={"model": self.output},
            )
        with self.assertRaisesRegex(StageReuseError, "not a live provisional"):
            write_stage_receipt(
                self.parent,
                project=PROJECT,
                stage_id=STAGE,
                context=self.parent_context,
                outputs={"model": self.output},
                allow_provisional_manifest=True,
            )

    def test_terminal_interrupted_manifest_is_not_live_provisional(self) -> None:
        self._write_summary("interrupted", "success")
        self._write_manifest("interrupted")
        manifest_path = self.parent / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["lifecycle_state"] = "terminal"
        self._write_json(manifest_path, manifest)
        with self.assertRaisesRegex(StageReuseError, "not a live provisional"):
            write_stage_receipt(
                self.parent,
                project=PROJECT,
                stage_id=STAGE,
                context=self.parent_context,
                outputs={"model": self.output},
                allow_provisional_manifest=True,
            )

    def test_v2_live_receipt_preserves_the_existing_retention_contract(self) -> None:
        from common.contracts.write_run_manifest import build_run_manifest

        retention = {"policy_version": 1, "class": "solver_review", "reason": "software stage receipt fixture"}
        config = {"schema_version": 2, "run_id": PARENT_ID, "project": PROJECT,
                  "inputs": {}, "artifact_retention": retention}
        self._write_json(self.parent_config, config)
        self._write_summary("running", "success")
        manifest = build_run_manifest(self.parent_config, "interrupted", output_paths=self._all_outputs(),
                                      extra_fields={"lifecycle_state": "provisional"})
        self.assertEqual(manifest["schema_version"], 2)
        self._write_json(self.parent / "run_manifest.json", manifest)
        receipt = write_stage_receipt(self.parent, project=PROJECT, stage_id=STAGE,
            context=self.parent_context, outputs={"model": self.output}, allow_provisional_manifest=True)
        self.assertEqual(receipt, self.receipt)
        for field, value in (("schema_version", 3), ("status", "success"), ("lifecycle_state", "terminal"),
                             ("artifact_retention", {**retention, "reason": "different"})):
            invalid = {**manifest, field: value}
            self._write_json(self.parent / "run_manifest.json", invalid)
            with self.subTest(field=field), self.assertRaises(StageReuseError):
                write_stage_receipt(self.parent, project=PROJECT, stage_id=STAGE,
                    context=self.parent_context, outputs={"model": self.output}, allow_provisional_manifest=True)
        self._write_json(self.parent / "run_manifest.json", manifest)
        for invalid_retention in ({}, {**retention, "class": "not-a-retention-class"}):
            self._write_json(self.parent_config, {**config, "artifact_retention": invalid_retention})
            with self.subTest(retention=invalid_retention), self.assertRaisesRegex(StageReuseError, "retention contract is invalid"):
                write_stage_receipt(self.parent, project=PROJECT, stage_id=STAGE,
                    context=self.parent_context, outputs={"model": self.output}, allow_provisional_manifest=True)

    def test_summary_and_manifest_status_must_match_and_be_terminal(self) -> None:
        for summary_status, manifest_status in (
            ("failed", "success"),
            ("interrupted", "interrupted"),
            ("superseded", "superseded"),
        ):
            with self.subTest(
                summary_status=summary_status,
                manifest_status=manifest_status,
            ):
                self._write_summary(summary_status, "success")
                self._write_manifest(manifest_status)
                with self.assertRaisesRegex(StageReuseError, "share a reusable terminal status"):
                    self._validate()

    def test_parent_summary_must_explicitly_mark_stage_success(self) -> None:
        self._write_summary("failed", "failed")
        self.receipt = self.parent / "stage_receipts" / f"{STAGE}.json"
        self._write_manifest("failed")
        with self.assertRaisesRegex(StageReuseError, "stage as success"):
            self._validate()

    def test_receipt_summary_context_and_outputs_must_be_manifest_bound(self) -> None:
        cases = (
            self.receipt,
            self.summary,
            self.parent_context["source"]["source_identity"],
            self.output,
        )
        for excluded in cases:
            with self.subTest(excluded=excluded.name):
                self._write_manifest(
                    "failed",
                    outputs=[path for path in self._all_outputs() if path != excluded],
                )
                with self.assertRaisesRegex(StageReuseError, "(bound|manifest-bound)"):
                    self._validate()

    def test_each_current_context_category_must_match_parent_content(self) -> None:
        for category in ("inputs", "source", "solver"):
            with self.subTest(category=category):
                path = next(iter(self.child_context[category].values()))
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(StageReuseError, f"{category} identity"):
                    self._validate()
                path.write_bytes(original)

    def test_current_context_must_be_frozen_inside_child_run(self) -> None:
        outside = self.child.parent / "outside.json"
        outside.write_text("inputs\n", encoding="utf-8")
        self.child_context["inputs"]["inputs_identity"] = outside
        self._write_child_config()
        with self.assertRaisesRegex(StageReuseError, "inside run root"):
            self._validate()

    def test_current_context_and_provenance_must_be_declared_as_inputs(self) -> None:
        config = json.loads(self.child_config.read_text(encoding="utf-8"))
        for missing in ("solver_identity", "stage_reuse_provenance"):
            with self.subTest(missing=missing):
                changed = json.loads(json.dumps(config))
                del changed["inputs"][missing]
                self._write_json(self.child_config, changed)
                with self.assertRaisesRegex(StageReuseError, "run_config.inputs"):
                    self._validate()
        self._write_json(self.child_config, config)

    def test_child_and_parent_identity_must_be_distinct_and_unfinalized(self) -> None:
        with self.assertRaisesRegex(StageReuseError, "roots must be different"):
            validate_and_write_stage_reuse(
                self.parent,
                parent_run_root=self.parent,
                project=PROJECT,
                stage_contexts={STAGE: self.parent_context},
            )

        same_id_root = self.workspace / "other" / PARENT_ID
        same_id_root.mkdir(parents=True)
        self._write_json(
            same_id_root / "run_config.json",
            {
                "schema_version": 1,
                "run_id": PARENT_ID,
                "project": PROJECT,
                "inputs": {},
            },
        )
        with self.assertRaisesRegex(StageReuseError, "run IDs must be different"):
            validate_and_write_stage_reuse(
                same_id_root,
                parent_run_root=self.parent,
                project=PROJECT,
                stage_contexts={STAGE: self.child_context},
            )

        (self.child / "run_manifest.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(StageReuseError, "already finalized"):
            self._validate()

    def test_changed_parent_output_is_rejected(self) -> None:
        self.output.write_bytes(b"changed-output")
        with self.assertRaisesRegex(StageReuseError, "parent output"):
            self._validate()

    def test_existing_provenance_cannot_be_overwritten_with_different_identity(self) -> None:
        destination = self._validate()
        destination.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(StageReuseError, "already exists"):
            self._validate()


if __name__ == "__main__":
    unittest.main()
