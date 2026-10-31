"""Unphased old native facts cannot authorize the changed current field stage."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_candidate_workflow import postprocess_source_fixture
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate import run_candidate_workflow as workflow

class CandidateLegacyBoundaryTests(unittest.TestCase):
    def test_unphased_parent_requires_native_evidence_and_keeps_csv_reanalysis_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            _,parent,_,_=postprocess_source_fixture(Path(temporary))
            before={path:path.read_bytes() for path in parent.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError,"necessary new native stage.*--postprocess-from"):
                workflow._comsol_phase_sources(parent)
            self.assertEqual(before,{path:path.read_bytes() for path in before})

if __name__ == "__main__":
    unittest.main()
