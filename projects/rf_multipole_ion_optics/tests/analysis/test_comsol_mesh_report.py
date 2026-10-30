"""Actual mesh-report parser and finite strategy handoff; no native process."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / "projects/rf_multipole_ion_optics"
PWSH = shutil.which("pwsh")
SELECTED = "selected_region_free_tetrahedral"
HYBRID = "physical_segment_hybrid_swept_tetra_v1"


def report(strategy=SELECTED):
    facts = dict(STOP_STAGE="mesh_build", FIELD_PHYSICS_CREATED=0,
                 FIELD_STUDIES_CREATED=0, FIELD_SOLUTIONS_CREATED=0,
                 PARTICLE_PHYSICS_CREATED=0, PARTICLE_STUDIES_CREATED=0,
                 MESH_STRATEGY=strategy, MESH_GLOBAL_EMPTY=0, MESH_GLOBAL_COMPLETE=1,
                 MESH_GLOBAL_HAS_PROBLEMS=0, MESH_VACUUM_EMPTY=0, MESH_VACUUM_COMPLETE=1,
                 MESH_VACUUM_HAS_PROBLEMS=0, MESH_GLOBAL_ELEMENTS=100,
                 MESH_VACUUM_ELEMENTS=80, MESH_VACUUM_SELECTION_ENTITY_COUNT=2,
                 MESH_VACUUM_VOLUME_STATUS="MEASURED", MESH_VACUUM_VOLUME_MM3=10,
                 MESH_GLOBAL_MIN_QUALITY=.1, MESH_VACUUM_MIN_QUALITY=.1,
                 MESH_BUILD_DIAGNOSTIC="PASS", STATUS="PASS")
    if strategy == HYBRID:
        facts.update(MESH_FEATURE_ROD_BOUNDARY_SIZE_PRESENT=1,
                     MESH_SWEPT_TETRAHEDRAL_OVERLAP_DOMAIN_COUNT=0,
                     MESH_VACUUM_UNCOVERED_DOMAIN_COUNT=0,
                     MESH_NONVACUUM_PARTITION_DOMAIN_COUNT=0)
    return facts


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class ComsolMeshReportTests(unittest.TestCase):
    def assert_matrix(self, cases):
        """One real PowerShell process; every case still has an independent report."""
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            inputs = []
            for index, case in enumerate(cases):
                path = folder / f"mesh_{index}.txt"
                path.write_text("".join(f"{key}={value}\n" for key, value in case["facts"].items())
                                + case.get("extra", ""), encoding="utf-8", newline="\n")
                inputs.append(dict(case_id=index, report=str(path),
                                   expected=case.get("expected", SELECTED),
                                   maximum=case.get("maximum"), frozen_mesh=case.get("frozen_mesh")))
            input_path = folder / "cases.json"
            input_path.write_text(json.dumps(inputs), encoding="utf-8", newline="\n")
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            source = (PROJECT / "runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
            start = source.index("      $expectedMeshStrategy=")
            end = source.index("\n", source.index("$meshCells=Assert-MultipoleMeshBuildReport", start))
            call_path = folder / "actual_finite_call.ps1"
            call_path.write_text(source[start:end], encoding="utf-8", newline="\n")
            script = r"""
$ErrorActionPreference='Stop'
. @@PREFLIGHT@@
$cases=Get-Content -LiteralPath @@CASES@@ -Raw -Encoding UTF8|ConvertFrom-Json
$results=[Collections.Generic.List[object]]::new()
foreach($case in $cases){
  $meshCells=$null
  try{
    $report=[string]$case.report
    if($null-ne$case.frozen_mesh){
      $solverNumericsDocument=[pscustomobject]@{mesh=$case.frozen_mesh}
      . @@ACTUAL_CALL@@
    }else{
      $arguments=@{Path=$report;ExpectedMeshStrategy=[string]$case.expected}
      if($null-ne$case.maximum){$arguments.MaximumMeshCells=$case.maximum}
      $meshCells=Assert-MultipoleMeshBuildReport @arguments
    }
    $results.Add(@{case_id=$case.case_id;accepted=$true;cells=$meshCells;error='';error_id=''})
  }catch{
    $results.Add(@{case_id=$case.case_id;accepted=$false;cells=$null;
      error=$_.Exception.Message;error_id=$_.FullyQualifiedErrorId})
  }
}
ConvertTo-Json -InputObject ($results.ToArray()) -Depth 10 -Compress
"""
            script = script.replace("@@PREFLIGHT@@", quote(PROJECT / "runtime/finite_3d_transport_preflight.ps1"))
            script = script.replace("@@CASES@@", quote(input_path)).replace("@@ACTUAL_CALL@@", quote(call_path))
            result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = json.loads(result.stdout)
            self.assertIsInstance(rows, list)
            self.assertEqual([row["case_id"] for row in rows], list(range(len(cases))))
            for case, row in zip(cases, rows, strict=True):
                with self.subTest(case=case["name"]):
                    if "reason" in case:
                        self.assertFalse(row["accepted"], row)
                        self.assertIn(case["reason"], row["error"])
                    else:
                        self.assertTrue(row["accepted"], row)
                        if "cells" in case:
                            self.assertEqual(row["cells"], case["cells"])

    def test_selected_has_no_hybrid_shape_requirement_and_duplicate_pass_is_legal(self):
        self.assert_matrix([dict(name="selected", facts=report(), extra="STATUS=PASS\n",
                                 maximum=100, cells=100)])

    def test_hybrid_keeps_every_original_partition_requirement(self):
        cases = [dict(name="complete_hybrid", facts=report(HYBRID), expected=HYBRID)]
        for name in ("MESH_FEATURE_ROD_BOUNDARY_SIZE_PRESENT",
                     "MESH_SWEPT_TETRAHEDRAL_OVERLAP_DOMAIN_COUNT",
                     "MESH_VACUUM_UNCOVERED_DOMAIN_COUNT", "MESH_NONVACUUM_PARTITION_DOMAIN_COUNT"):
            facts = report(HYBRID)
            del facts[name]
            cases.append(dict(name=name, facts=facts, expected=HYBRID, reason="required terminal token"))
        self.assert_matrix(cases)

    def test_complete_and_global_quality_preserve_actual_strategy_acceptance(self):
        hybrid = report(HYBRID)
        hybrid.update(MESH_GLOBAL_COMPLETE=0, MESH_VACUUM_COMPLETE=0, MESH_GLOBAL_MIN_QUALITY=0)
        incomplete = report()
        incomplete["MESH_GLOBAL_COMPLETE"] = 0
        diagnostic_only = report()
        diagnostic_only.update(MESH_VACUUM_COMPLETE=0, MESH_GLOBAL_MIN_QUALITY="NaN")
        self.assert_matrix([
            dict(name="hybrid_original_acceptance", facts=hybrid, expected=HYBRID),
            dict(name="selected_incomplete", facts=incomplete, reason="required terminal token"),
            dict(name="selected_diagnostic_only", facts=diagnostic_only),
        ])

    def test_strategy_missing_unknown_duplicate_and_mismatch_reject(self):
        cases = []
        for kind in ("missing", "unknown", "duplicate", "mismatch"):
            facts = report()
            extra = ""
            expected = SELECTED
            if kind == "missing":
                del facts["MESH_STRATEGY"]
            elif kind == "unknown":
                facts["MESH_STRATEGY"] = "unknown_strategy"
            elif kind == "duplicate":
                extra = "MESH_STRATEGY=" + SELECTED + "\n"
            else:
                expected = HYBRID
            cases.append(dict(name=kind, facts=facts, expected=expected, extra=extra, reason="report strategy"))
        self.assert_matrix(cases)

    def test_common_mesh_and_no_solve_facts_fail_closed(self):
        cases = []
        for name in ("MESH_GLOBAL_EMPTY", "MESH_GLOBAL_COMPLETE", "MESH_GLOBAL_HAS_PROBLEMS",
                     "MESH_VACUUM_EMPTY", "MESH_VACUUM_HAS_PROBLEMS",
                     "FIELD_PHYSICS_CREATED", "FIELD_STUDIES_CREATED", "FIELD_SOLUTIONS_CREATED",
                     "PARTICLE_PHYSICS_CREATED", "PARTICLE_STUDIES_CREATED"):
            facts = report()
            facts[name] = 1 - facts[name]
            cases.append(dict(name=name, facts=facts, reason="required terminal token"))
        facts = report()
        del facts["MESH_GLOBAL_COMPLETE"]
        cases.append(dict(name="missing_complete", facts=facts, reason="required terminal token"))
        self.assert_matrix(cases)

    def test_positive_finite_measurements_and_integer_counts_are_required(self):
        cases = []
        for name, value in (("MESH_GLOBAL_ELEMENTS", "1.5"), ("MESH_VACUUM_ELEMENTS", 0),
                            ("MESH_VACUUM_VOLUME_MM3", "NaN"), ("MESH_VACUUM_MIN_QUALITY", 0)):
            facts = report()
            facts[name] = value
            cases.append(dict(name=name, facts=facts, reason="invalid positive"))
        cases.append(dict(name="budget", facts=report(), maximum=99, reason="cell budget exceeded"))
        self.assert_matrix(cases)

    def test_conflicting_common_fact_or_terminal_failure_rejects(self):
        self.assert_matrix([
            dict(name="conflicting_fact", facts=report(), extra="MESH_GLOBAL_EMPTY=1\n", reason="required terminal token"),
            dict(name="terminal_fail", facts=report(), extra="STATUS=FAIL\n", reason="non-PASS status"),
        ])

    def test_real_finite_call_derives_strategy_from_frozen_numerics(self):
        cases = []
        for strategy in (SELECTED, HYBRID):
            mesh = dict(global_auto_level=9, working_region_maximum_element_size_mm=2.0)
            if strategy == HYBRID:
                mesh["strategy"] = HYBRID
            cases.append(dict(name=strategy, facts=report(strategy), frozen_mesh=mesh))
        cases.append(dict(name="frozen_mismatch", facts=report(), frozen_mesh=dict(strategy=HYBRID),
                          reason="report strategy"))
        self.assert_matrix(cases)


if __name__ == "__main__":
    unittest.main()
