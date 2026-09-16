from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from common.contracts.solver_review_retirement import (
    RetirementError, apply_retirement, plan_retirement, verify_retirement,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class SolverReviewRetirementTest(unittest.TestCase):
    compatibility_roles = (
        "candidate_contract", "resolved_prototype_contract", "analyzer_pa0",
        "accelerator_pa0", "detector_pa", "three_instance_seed",
    )
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.artifacts = self.root / "artifacts"
        self.repo.mkdir()
        self.runs = self.artifacts / "projects" / "p" / "runs"
        self.target = self._run("20260101_000000__build__simion__old", "2026-01-01T00:00:00Z")
        self.replacement = self._run("20260102_000000__build__simion__new", "2026-01-02T00:00:00Z")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, run_id: str, recorded: str) -> Path:
        run = self.runs / run_id
        simion = run / "simion"
        simion.mkdir(parents=True)
        roles = {
            "candidate_contract": run / "candidate.json",
            "resolved_prototype_contract": run / "resolved.json",
            "analyzer_pa0": simion / "analyzer.pa0",
            "accelerator_pa0": simion / "accelerator.pa0",
            "detector_pa": simion / "detector.pa#",
            "three_instance_seed": simion / "seed.iob",
        }
        for name, path in roles.items():
            path.write_bytes(b"native" if path.suffix.lower().startswith(".pa") else name.encode())
        config = {"schema_version": 2, "run_id": run_id, "project": "p", "mode": "three_component_candidate_iob_assembly",
                  "inputs": {name: str(path) for name, path in roles.items()}, "formal_gate_passed": False,
                  "artifact_retention": {"policy_version": 1, "class": "solver_review", "reason": "GUI review"}}
        summary = {"run_id": run_id, "status": "success"}
        for name, value in (("run_config.json", config), ("summary.json", summary)):
            (run / name).write_text(json.dumps(value), encoding="utf-8")
        inputs = {name: {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)} for name, path in roles.items()}
        manifest = {"schema_version": 2, "run_id": run_id, "project": "p", "mode": config["mode"], "status": "success",
                    "recorded_at_utc": recorded, "run_config": {"path": str(run / 'run_config.json'), "exists": True,
                    "bytes": (run / 'run_config.json').stat().st_size, "sha256": _sha(run / 'run_config.json')},
                    "inputs": inputs, "outputs": [{"path": str(run / 'summary.json'), "exists": True,
                    "bytes": (run / 'summary.json').stat().st_size, "sha256": _sha(run / 'summary.json'), "retention_role": "required_evidence"}],
                    "formal_eligible": False, "artifact_retention": config["artifact_retention"]}
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_plan_apply_and_retired_verification(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "new successful GUI package supersedes old", self.compatibility_roles,
        )
        self.assertGreater(plan["bytes_to_release"], 0)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["lifecycle_status"], "superseded_payload_retired")
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertTrue((self.target / "run_manifest.json").is_file())
        self.assertTrue((self.target / "simion" / "seed.iob").is_file())
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=["docs/x.md"])
    def test_document_reference_fails_closed(self, _scan: mock.Mock) -> None:
        with self.assertRaises(RetirementError):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "compatible", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_declared_compatibility_role_must_exist_at_both_ends(self, _scan: mock.Mock) -> None:
        with self.assertRaisesRegex(RetirementError, "identity roles missing"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "compatible", (*self.compatibility_roles, "project_specific_missing_role"),
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_requires_host_lease(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RetirementError):
            apply_retirement(plan)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_pending_receipt_resumes_only_recorded_partial_removal(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        first = plan["removed_files"][0]
        (self.target / first["path"]).unlink()
        pending = {
            **plan,
            "role": "solver_review_retirement_receipt",
            "lifecycle_status": "retirement_pending",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps(pending), encoding="utf-8")
        resumed = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        self.assertTrue(any(item.get("already_removed_before_resume") for item in resumed["removed_files"]))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
