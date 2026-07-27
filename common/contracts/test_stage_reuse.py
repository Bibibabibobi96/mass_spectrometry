from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
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

    def test_receipt_cannot_be_retroactively_added_to_finalized_run(self) -> None:
        with self.assertRaisesRegex(StageReuseError, "after the final run manifest"):
            write_stage_receipt(
                self.parent,
                project=PROJECT,
                stage_id=STAGE,
                context=self.parent_context,
                outputs={"model": self.output},
            )

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
