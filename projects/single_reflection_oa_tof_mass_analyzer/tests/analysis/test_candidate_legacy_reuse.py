from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from common.contracts.machine_contracts import load_json
from common.contracts import write_run_manifest as terminal_publication
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as candidate_workflow
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import run_candidate_workflow

from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.candidate_fixtures import (
    CandidateFixtures,
)


class CandidateDesignTests(CandidateFixtures, unittest.TestCase):
    def test_legacy_inline_owner_projects_into_child_without_native_or_parent_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self.legacy_inline_parent(root)
            before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
            _, child_plan = self.native_workflow_plan(root, "20260727_190200")
            observed = []
            child, summary = run_candidate_workflow(child_plan, sys.executable, stage_executor=self.native_fake_executor(observed),
                reuse_parent=parent, reuse_through="comsol_candidate")
            self.assertEqual(observed, ["static_inputs", "simion_candidate", "cad_candidate", "structural_acceptance"])
            self.assertEqual(summary["status"], "success")
            proof = load_json(child / "inputs/stage_contexts/legacy_projection/projection.json")
            self.assertIn("not executed", proof["source_witness_semantics"])
            self.assertIn("comsol_candidate", proof["actual_modern_contexts"])
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            _, full_plan = self.native_workflow_plan(root, "20260727_190300")
            observed = []
            full, full_summary = run_candidate_workflow(full_plan, sys.executable, stage_executor=self.native_fake_executor(observed),
                reuse_parent=parent, reuse_through="cad_candidate")
            self.assertEqual(observed, ["static_inputs", "structural_acceptance"])
            self.assertEqual([stage["stage_id"] for stage in full_summary["stages"] if stage["execution"] == "reused"],
                ["comsol_candidate", "simion_candidate", "cad_candidate"])
            self.assertEqual(before, {p: p.read_bytes() for p in before})


    def test_legacy_bound_cache_uses_real_embedded_plan_derivation_and_rejects_damage(self):
        import py_compile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self.legacy_inline_parent(root)
            old_plan = load_json(parent / "candidate_workflow_plan.json")
            source = Path(old_plan["execution_source_closure"]["code_root"]) / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py"
            cache = Path(py_compile.compile(str(source), doraise=True))
            manifest_path = parent / "run_manifest.json"
            manifest = load_json(manifest_path)
            manifest["outputs"].append(terminal_publication.file_record(cache))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            _, plan = self.native_workflow_plan(root, "20260727_191200")
            observed = []
            child, summary = run_candidate_workflow(plan, sys.executable, stage_executor=self.native_fake_executor(observed),
                reuse_parent=parent, reuse_through="comsol_candidate")
            self.assertEqual(summary["status"], "success")
            self.assertNotIn("comsol_candidate", observed)
            projection = load_json(child / "inputs/stage_contexts/legacy_projection/projection.json")
            derivation = load_json(Path(projection["source_derivation"]["path"]))
            self.assertEqual(derivation["derivation"]["parent_closure_field"], "execution_source_closure")
            self.assertEqual(Path(derivation["derivation"]["parent_closure"]["path"]), parent / "candidate_workflow_plan.json")
            self.assertEqual(len(derivation["derivation"]["validated_bytecode"]), 1)
            self.assertFalse(list(Path(derivation["closure"]["code_root"]).rglob("*.pyc")))
            self.assertEqual(before, {path: path.read_bytes() for path in before})
            cache.write_bytes(b"bad!" + cache.read_bytes()[4:])
            manifest["outputs"][-1] = terminal_publication.file_record(cache)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            damaged = {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            _, bad_plan = self.native_workflow_plan(root, "20260727_191300")
            with self.assertRaisesRegex(candidate_workflow.CandidateWorkflowError, "unsupported parent bytecode header"):
                run_candidate_workflow(bad_plan, sys.executable, stage_executor=self.native_fake_executor([]),
                    reuse_parent=parent, reuse_through="comsol_candidate")
            self.assertEqual(damaged, {path: path.read_bytes() for path in damaged})


    def test_legacy_projection_rejects_missing_dispatch_writer_source_and_scientific_drift(self):
        self.assert_legacy_rejections(("missing_request", "unknown_writer", "unbound_completion", "pending_journal",
            "stage_environment", "scientific_drift", "request_context", "incomplete_stage_outputs"))


    def test_legacy_projection_rejects_old_freeze_missing_required_scientific_source(self):
        self.assert_legacy_rejections(("missing_scientific_source",))



if __name__ == "__main__":
    unittest.main()
