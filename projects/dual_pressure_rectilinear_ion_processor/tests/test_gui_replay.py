"""Fail-closed GUI replay entry checks; never launch SIMION or allocate a run."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "simion/prepare_gui_replay.ps1"


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
             "-BaselineRun", str(self.source)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            cwd=self.source,
        )

    def test_missing_manifest_rejected_without_new_files(self) -> None:
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Explicit baseline manifest is missing", result.stdout + result.stderr)
        self.assertEqual(list(self.source.iterdir()), [])

    def test_finalize_missing_plan_rejected_before_allocation(self) -> None:
        script = PROJECT / "simion/finalize_gui_replay.ps1"
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(script),
             "-RunPath", str(self.source)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            check=False, cwd=self.source,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GUI replay plan is missing; finalize refused before allocation", result.stdout + result.stderr)
        self.assertEqual(list(self.source.iterdir()), [])

    def test_foreign_or_incomplete_manifest_rejected_without_new_files(self) -> None:
        manifest = self.source / "run_manifest.json"
        for project, status in (("another_project", "success"),
                                ("dual_pressure_rectilinear_ion_processor", "checkpoint")):
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
