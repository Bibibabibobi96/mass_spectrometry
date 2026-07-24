from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class FailedRunManifestTest(unittest.TestCase):
    def test_new_run_package_emits_only_the_package_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_root = Path(directory) / "artifacts"
            support = ROOT / "common/contracts/run_artifact_support.ps1"
            python = Path(sys.executable)
            command = (
                f". '{support}'; "
                f"$package=New-RunPackage -Python '{python}' "
                f"-RepoRoot '{ROOT}' -ArtifactRoot '{artifact_root}' "
                "-RunId '20260723_120000__test__python__package-output' "
                "-Project 'fixture' -Mode 'package_output' -Software @('Python 3.11'); "
                "Write-Output $package.run_dir"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
                timeout=30,
            )
            output_lines = [line for line in result.stdout.splitlines() if line.strip()]
            expected_run = (
                artifact_root
                / "runs"
                / "20260723_120000__test__python__package-output"
            )
            self.assertEqual(output_lines, [str(expected_run)])

    def test_failure_finalization_keeps_all_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "runs" / "20260723_120000__sim__simion__partial-evidence"
            for relative in ("inputs/code", "results", "logs", "simion"):
                (run / relative).mkdir(parents=True)
            (run / "inputs/request.json").write_text("{}\n", encoding="utf-8")
            (run / "inputs/code/solver.lua").write_text("-- frozen\n", encoding="utf-8")
            (run / "results/metrics.json").write_text('{"status":"FAIL"}\n', encoding="utf-8")
            (run / "logs/native.txt").write_text("physical failure\n", encoding="utf-8")
            (run / "simion/model.pa0").write_bytes(b"partial-pa")
            config = run / "run_config.json"
            summary = run / "summary.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run.name,
                        "project": "fixture",
                        "mode": "resolved_design_transport",
                        "project_root": str(run),
                        "inputs": {"request": str(run / "inputs/request.json")},
                        "formal_gate_passed": False,
                    }
                ),
                encoding="utf-8",
            )
            support = ROOT / "common/contracts/run_artifact_support.ps1"
            python = Path(sys.executable)
            command = (
                f". '{support}'; Complete-FailedRun -Python '{python}' "
                f"-RepoRoot '{ROOT}' -RunConfig '{config}' -Summary '{summary}' "
                "-SummaryRole 'fixture_summary' -Reason 'physical gate failed' "
                "-Software @('Python 3.11')"
            )
            subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
                timeout=30,
            )
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
            output_paths = {Path(item["path"]).name for item in manifest["outputs"]}
            self.assertEqual(manifest["status"], "failed")
            self.assertTrue({"metrics.json", "native.txt", "model.pa0", "summary.json"} <= output_paths)
            self.assertTrue(
                any(item["path"].endswith("solver.lua") for item in manifest["inputs"].values())
            )


if __name__ == "__main__":
    unittest.main()
