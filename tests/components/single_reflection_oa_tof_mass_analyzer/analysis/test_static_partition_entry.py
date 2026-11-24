"""Thin actual SFI PowerShell entry tests; public scheduling faults live in common."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[4] / "src/msplatform/components/single_reflection_oa_tof"
MODULE = "tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_fixture"


class StaticPartitionEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sfi_partition_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "src/msplatform/components/single_reflection_oa_tof"
        (self.project / "config").mkdir(parents=True)
        (self.root / "common").mkdir()
        self.workflow_resources = self.root / "src/msplatform/workflows/resources"
        self.workflow_resources.mkdir(parents=True)
        shutil.copyfile(
            PROJECT.parents[1] / "workflows/resources/oatof_verify.ps1",
            self.workflow_resources / "oatof_verify.ps1",
        )
        (self.project / "config/project.json").write_text(json.dumps({"lifecycle_status": "formal_revalidation_pending"}))
        (self.workflow_resources / "oatof_lifecycle_preflight.ps1").write_text("# Original preflight's domain fixture boundary.\n")
        resources = self.root / "src/msplatform/execution/resources"
        resources.mkdir(parents=True)
        (resources / "workspace_paths.ps1").write_text(
            "function Resolve-PlatformArtifactPath { param($ArtifactRoot,$RelativePath,$Python) "
            "return (Join-Path $ArtifactRoot (@('platform')+@($RelativePath)-join'/')) }\n"
            "function Resolve-RunArtifactRoot { param($ArtifactRoot,$OwnerKind,$OwnerId,$Python) "
            "return (Join-Path $ArtifactRoot \"components/$OwnerId\") }\n"
        )
        (resources / "host_execution_lease.ps1").write_text(
            "function Enter-HostExecutionLease { param($Role,$Stage) return @{inherited=$false} }\n"
            "function Exit-HostExecutionLease { param($Lease) }\n")
        (resources / "host_resource_policy.json").write_text("{}\n")
        self.python = self.root / "python_fixture.ps1"
        self.python.write_text(r"""
Add-Content -LiteralPath $env:SFI_CALLS -Value ($args -join ' ')
$global:LASTEXITCODE=0
if (($env:SFI_FAIL -eq 'preflight' -and ($args -join ' ') -match 'oa_tof_design.resolve_geometry') -or
    ($env:SFI_FAIL -eq 'tests' -and ($args -join ' ') -match 'tools.repository.gate_unittest')) {
 $global:LASTEXITCODE=19
}
""")
        fixture = self.root / "tests/components/single_reflection_oa_tof_mass_analyzer/analysis/test_fixture.py"
        fixture.parent.mkdir(parents=True)
        fixture.write_text("# Chosen fixture module; Python body not run by this PS wiring test.\n")
        self.index = 0

    def invoke(self, options="", fail=""):
        self.index += 1
        calls = self.root / f"calls_{self.index}.txt"
        env = dict(os.environ, SFI_CALLS=str(calls), SFI_FAIL=fail)
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = f"& {quote(self.workflow_resources / 'oatof_verify.ps1')} -PythonExe {quote(self.python)} {options}"
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=self.root,
                                env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        recorded = calls.read_text(encoding="utf-8-sig").splitlines() if calls.exists() else []
        return result, recorded

    def test_actual_entry_preflight_once_and_selected_boundary(self):
        direct, calls = self.invoke(f"-SelectedTestModules @('{MODULE}')")
        self.assertEqual(direct.returncode, 0, direct.stdout + direct.stderr)
        self.assertEqual(sum('oa_tof_design.resolve_geometry' in x for x in calls), 1)
        self.assertEqual(sum('tools.repository.gate_unittest' in x for x in calls), 1)
        self.assertIn(MODULE, calls[-1])
        self.assertIn('FULL_PROJECT_GATE=False', direct.stdout)
        parent, parent_calls = self.invoke('-PreflightOnly')
        self.assertEqual(parent.returncode, 0, parent.stdout + parent.stderr)
        self.assertEqual(sum('oa_tof_design.resolve_geometry' in x for x in parent_calls), 1)
        self.assertFalse(any('tools.repository.gate_unittest' in x for x in parent_calls))
        selected, selected_calls = self.invoke(f"-PreflightValidated -SelectedTestModules @('{MODULE}')")
        self.assertEqual(selected.returncode, 0, selected.stdout + selected.stderr)
        self.assertEqual(selected_calls, [f'-m tools.repository.gate_unittest {MODULE}'])

    def test_preflight_and_selected_failure_propagate(self):
        result, calls = self.invoke(f"-SelectedTestModules @('{MODULE}')", fail='preflight')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Resolved-geometry gate failed', result.stderr)
        self.assertFalse(any('tools.repository.gate_unittest' in x for x in calls))
        result, calls = self.invoke(f"-PreflightValidated -SelectedTestModules @('{MODULE}')", fail='tests')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python analysis tests failed', result.stderr)
        self.assertEqual(len(calls), 1)

    def test_qualification_and_invalid_modules_fail_before_any_work(self):
        for options in (
            '-Level Candidate -PreflightOnly', '-Level Formal -PreflightOnly',
            '-Level Candidate -PreflightValidated:$false', '-Level Formal -PreflightOnly:$false',
            f"-SelectedTestModules @('{MODULE}','{MODULE}')",
            "-SelectedTestModules @('common.contracts.test_fixture')",
            "-SelectedTestModules @('tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_missing')",
            '-PreflightValidated',
        ):
            with self.subTest(options=options):
                result, calls = self.invoke(options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
