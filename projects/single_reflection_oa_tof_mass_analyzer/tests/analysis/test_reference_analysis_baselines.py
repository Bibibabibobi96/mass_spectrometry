from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    reference_analysis_core,
)


class ReferenceAnalysisBaselineLifecycleTests(unittest.TestCase):
    def test_gate_checks_current_formal_before_retired_history(self):
        gate = (
            reference_analysis_core.PROJECT_DIR
            / "analysis"
            / "verify_reference_analysis.ps1"
        ).read_text(encoding="utf-8")
        self.assertLess(
            gate.index("verify_formal_validation.py"),
            gate.index("'verify-baselines'"),
        )

    def _verify_missing_entry(
        self,
        lifecycle_status: str,
        missing_artifact_policy: str,
    ) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo_root = root / "repository"
            config_dir = repo_root / "project" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "analysis_contract.json").write_text(
                "{}\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 2,
                "analysis_contract": "analysis_contract.json",
                "artifact_project_relative": "projects/example",
                "canonical_tolerance": {"relative": 1e-6, "absolute": 1e-12},
                "entries": [
                    {
                        "id": "missing",
                        "lifecycle_status": lifecycle_status,
                        "missing_artifact_policy": missing_artifact_policy,
                        "relative_path": "archive/missing.csv",
                        "bytes": 1,
                        "rows": 1,
                        "sha256": "0" * 64,
                        "nominal_mass_Da": 524.0,
                        "canonical_reference": {},
                    }
                ],
                "comparisons": [],
            }
            manifest_path = config_dir / "analysis_baselines.json"
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with mock.patch.object(
                reference_analysis_core, "REPO_ROOT", repo_root
            ):
                return reference_analysis_core.verify_baselines(
                    manifest_path, root / "output"
                )

    def test_retired_missing_artifact_is_reported_without_blocking_formal(self):
        result = self._verify_missing_entry(
            "retired_historical_record", "retired_record_only"
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["entries"][0]["status"],
            "RETIRED_ARTIFACT_UNAVAILABLE",
        )

    def test_active_missing_artifact_still_fails(self):
        result = self._verify_missing_entry("active", "fail")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["entries"][0]["status"], "FAIL")

    def test_retired_entry_rejects_a_permissive_uncontrolled_policy(self):
        with self.assertRaisesRegex(
            ValueError, "missing_artifact_policy"
        ):
            self._verify_missing_entry(
                "retired_historical_record", "ignore_if_missing"
            )


if __name__ == "__main__":
    unittest.main()
