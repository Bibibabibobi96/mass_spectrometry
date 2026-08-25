from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_stage_evidence import (
    StageEvidence,
    publish_stage_evidence,
)


class Paper1StageEvidenceTest(unittest.TestCase):
    def test_publishes_all_required_stage_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "C0"
            published = publish_stage_evidence(target, StageEvidence(
                stage_id="C0", conclusion="PASS_CONTINUE", claim_limit="theory only",
                inputs={"source": "none"}, metrics={"symbols_checked": 5},
                claims_supported=("theory internally consistent",),
                claims_prohibited=("physical resolution floor",), failures=(),
            ))
            self.assertEqual(published, target)
            self.assertEqual(
                {item.name for item in target.iterdir()},
                {"stage_contract.md", "stage_manifest.json", "stage_report.md", "stage_report.json", "stage_conclusion.md"},
            )

    def test_rejects_unrecognized_conclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid"):
                publish_stage_evidence(Path(directory) / "C0", StageEvidence(
                    stage_id="C0", conclusion="PASS", claim_limit="theory only",
                    inputs={}, metrics={}, claims_supported=(), claims_prohibited=(), failures=(),
                ))


if __name__ == "__main__":
    unittest.main()
