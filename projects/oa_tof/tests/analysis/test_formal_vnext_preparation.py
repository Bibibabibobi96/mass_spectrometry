"""Fast contract coverage for Formal vNext preparation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import sha256
from projects.oa_tof.workflows.formal_reference.prepare_formal_vnext import prepare_formal_vnext


class FormalVnextPreparationTest(unittest.TestCase):
    def _write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _candidate(self, root: Path, *, formal_path: bool = False) -> Path:
        candidate = root / "runs" / "20260726_120000__test__cross__candidate-source__n100"
        inputs = candidate / "inputs"
        for relative in (
            "candidate_baseline.json", "candidate_resolved_geometry.json", "candidate_solver_numerics.json",
            "simion_template/layout.iob", "simion_template/layout.con",
            "prepared_consumers/simion/oatof_resolved.lua",
            "prepared_consumers/simion/oatof_ideal_grounded.lua",
            "prepared_consumers/simion/oatof_ideal_grounded.fly2",
            "code/placeholder.txt",
        ):
            path = inputs / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        evidence_paths = {
            "model": candidate / "comsol/model.mph",
            "iob": candidate / "simion/layout.iob",
            "ion_n100": candidate / "simion/n100.ion",
            "transport_summary": candidate / "results/transport.json",
            "cad_report": candidate / "cad/report.json",
            "acceptance": candidate / "results/candidate_acceptance.json",
        }
        for path in evidence_paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("evidence", encoding="utf-8")
        self._write_json(evidence_paths["acceptance"], {
            "role": "oa_tof_candidate_acceptance", "status": "success",
            "formal_modified": False, "promotion_authorized": False,
        })
        stages = [
            {"stage_id": "comsol_candidate", "status": "success", "evidence": {"model": str(evidence_paths["model"])}},
            {"stage_id": "simion_candidate", "status": "success", "evidence": {
                "iob": str(evidence_paths["iob"]), "ion_n100": str(evidence_paths["ion_n100"]),
                "transport_summary": str(evidence_paths["transport_summary"]),
            }},
            {"stage_id": "cad_candidate", "status": "success", "evidence": {"cad_report": str(evidence_paths["cad_report"])}},
            {"stage_id": "cross_solver_acceptance", "status": "success", "evidence": {"acceptance": str(evidence_paths["acceptance"])}},
        ]
        self._write_json(candidate / "run_config.json", {
            "role": "oa_tof_candidate_run_config", "project": "oa_tof", "mode": "design_candidate",
            "formal_gate_passed": False, "promotion_authorized": False,
            "run_instance": {"particle_source_seed": 20260713},
        })
        self._write_json(candidate / "summary.json", {
            "role": "oa_tof_candidate_run_summary", "status": "success",
            "candidate_decision": "candidate_accepted_not_promoted", "formal_modified": False,
            "promotion_authorized": False, "stages": stages,
        })
        self._write_json(candidate / "run_manifest.json", {
            "status": "success", "project": "oa_tof", "mode": "design_candidate",
            "formal_eligible": False, "promotion_authorized": False,
        })
        closure = {
            "schema_version": 2, "role": "oa_tof_candidate_execution_source_closure",
            "code_root": str(inputs / "code"),
            "runtime": {"python_executable": str(Path(__import__("sys").executable)), "python_sha256": sha256(Path(__import__("sys").executable))},
            "sources": [{"source_id": "placeholder.txt", "sha256": sha256(inputs / "code/placeholder.txt"), "bytes": (inputs / "code/placeholder.txt").stat().st_size}],
        }
        self._write_json(candidate / "candidate_workflow_plan.json", {
            "formal_root": {"mutation_allowed": False}, "promotion": {"included": False},
            "execution_source_closure": closure,
        })
        if formal_path:
            return root / "formal" / candidate.name
        return candidate

    def test_prepares_nonexecuting_n1000_plan_from_successful_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "oa_tof"
            candidate = self._candidate(root)
            result = prepare_formal_vnext(
                candidate, "20260726_130000__sim__cross__formal-vnext__n1000", root
            )
            plan = root / "scratch" / next((root / "scratch").iterdir()).name / "formal_vnext_plan.json"
            self.assertTrue(plan.is_file())
            self.assertEqual(result["status"], "prepared_not_executed")
            self.assertEqual(result["run_instance"]["particle_count"], 1000)
            self.assertFalse(result["formal_asset_read_allowed"])
            self.assertFalse(result["promotion"]["authorized"])
            self.assertFalse((root / "runs" / "20260726_130000__sim__cross__formal-vnext__n1000").exists())

    def test_rejects_formal_candidate_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "oa_tof"
            candidate = self._candidate(root)
            forbidden = root / "formal" / candidate.name
            forbidden.parent.mkdir(parents=True)
            candidate.rename(forbidden)
            with self.assertRaisesRegex(ValueError, "artifacts/runs"):
                prepare_formal_vnext(forbidden, "20260726_130000__sim__cross__formal-vnext__n1000", root)
