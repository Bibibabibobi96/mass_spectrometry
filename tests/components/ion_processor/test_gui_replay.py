"""Fail-closed GUI replay entry checks; never launch SIMION or allocate a run."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[3] / "src/msplatform/components/ion_processor"
SCRIPT = PROJECT.parents[3] / "src/msplatform/backends/simion/resources/ip_prepare_gui_replay.ps1"


class GuiReplayEntrypointTests(unittest.TestCase):
    """Reject missing evidence and foreign/checkpoint sources before mutation."""

    def setUp(self) -> None:
        self.powershell = shutil.which("pwsh")
        if not self.powershell:
            self.skipTest("PowerShell 7 unavailable")
        self.temporary = tempfile.TemporaryDirectory(prefix="ion_processor_gui_gate_test_")
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)

    def invoke(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(SCRIPT),
             "-RunId", "20261015_010000__test__simion__gui-source-rejection",
             "-BaselineRun", str(self.source),
             "-RepositoryRoot", str(PROJECT.parents[3]),
             "-PythonExe", sys.executable],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            cwd=self.source,
            env={**os.environ, "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(self.source / "host_resources.sqlite3")},
        )

    def test_missing_manifest_rejected_without_new_files(self) -> None:
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Explicit baseline manifest is missing", result.stdout + result.stderr)
        self.assertEqual(list(self.source.iterdir()), [])

    def test_finalize_missing_plan_rejected_before_allocation(self) -> None:
        script = PROJECT.parents[3] / "src/msplatform/backends/simion/resources/ip_finalize_gui_replay.ps1"
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(script),
             "-RunPath", str(self.source),
             "-RepositoryRoot", str(PROJECT.parents[3]),
             "-PythonExe", sys.executable],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            check=False, cwd=self.source,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GUI replay plan is missing; finalize refused before allocation", result.stdout + result.stderr)
        self.assertEqual(list(self.source.iterdir()), [])

    def test_python_consumers_use_explicit_run_root_context(self) -> None:
        for name in ("ip_prepare_gui_replay.ps1", "ip_finalize_gui_replay.ps1"):
            with self.subTest(script=name):
                text = (SCRIPT.parent / name).read_text(encoding="utf-8")
                self.assertIn("Invoke-RunToolRootContext -RepoRoot $repoRoot", text)
                self.assertNotIn("$env:PYTHONPATH", text)

    def test_foreign_or_incomplete_manifest_rejected_without_new_files(self) -> None:
        manifest = self.source / "run_manifest.json"
        for project, status in (("another_project", "success"),
                                ("ion_processor", "checkpoint")):
            with self.subTest(project=project, status=status):
                original = json.dumps({"project": project, "status": status})
                manifest.write_text(original, encoding="utf-8")
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("GUI replay requires a terminal run of this project", result.stdout + result.stderr)
                self.assertEqual(manifest.read_text(encoding="utf-8"), original)
                self.assertEqual(list(self.source.iterdir()), [manifest])


if __name__ == "__main__":
    unittest.main()
