from __future__ import annotations

import unittest
import base64
import re
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4] / "src/msplatform/components/single_reflection_oa_tof"


class FormalReferenceWorkflowLayoutTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
    def test_stable_gate_uses_explicit_science_root_from_external_cwd(self):
        source = PROJECT_ROOT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'installed/msplatform'
            for relative in ('workflows/resources/verify_stable_entry.ps1',
                             'workflows/resources/oatof_lifecycle_preflight.ps1',
                             'execution/resources/workspace_paths.ps1'):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, target)
            science = root / 'science'
            (science / 'config').mkdir(parents=True)
            (science / 'config/simion_stable_entry.json').write_text(
                '{"schema_version":0,"frozen_on":"x","role":"x",'
                '"artifact_workspace_relative":"formal","entries":[]}', encoding='utf-8')
            result = subprocess.run([
                'pwsh', '-NoProfile', '-NonInteractive', '-File',
                str(package / 'workflows/resources/verify_stable_entry.ps1'),
                '-WorkspaceRoot', str(root), '-ArtifactRootPath', str(root / 'artifacts'),
                '-ScienceRoot', str(science), '-PythonExe', sys.executable, '-SkipRuntime',
            ], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SIMION stable-entry identity differs', result.stderr)
            self.assertFalse((root / 'artifacts').exists())

    def test_geometry_gate_resolves_artifact_root_before_formal_paths(self):
        gate = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        self.assertLess(
            gate.index("$artifactRoot = Resolve-RunArtifactRoot"),
            gate.index("$formalReleaseManifestPath = Join-Path $artifactRoot"),
        )
        self.assertNotIn("Join-Path $repoRoot '.venv", gate)

    def test_managed_builder_source_gate_requires_deferred_stage_summary(self):
        gate = (PROJECT_ROOT.parents[1] / "workflows/resources" / "verify_geometry_contract.ps1").read_text(encoding="utf-8")
        builder = (PROJECT_ROOT.parents[1] / "backends/simion/resources" / "build_formal_delivery.ps1").read_text(encoding="utf-8")
        helpers = "\n".join(re.findall(r"(?ms)^function Assert-(?:Not)?Contains\([^\n]*\n.*?^\}", gate))
        checks = "\n".join(line for line in gate.splitlines() if line.startswith("Assert-Contains $deliveryBuilder"))
        guard = "if (-not $candidateMode -or -not $DeferRunFinalization)"
        for kind, source in (("current", builder), ("false_summary", builder.replace("run_finalization_deferred=$true", "run_finalization_deferred=$false")),
                             ("missing_guard", builder.replace(guard, "if ($false)"))):
            with self.subTest(kind=kind):
                payload = base64.b64encode(source.encode("utf-8")).decode("ascii")
                script = "$ErrorActionPreference='Stop'\n" + helpers + "\n" + (
                    "$deliveryBuilder=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'))\n"
                ) + checks
                result = subprocess.run(["pwsh", "-NoProfile", "-Command",
                    "$ErrorActionPreference='Stop'; & ([scriptblock]::Create([Console]::In.ReadToEnd()))"],
                    input=script, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
                if kind == "current":
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)





    def test_project_formal_gate_forwards_explicit_reference_context(self):
        gate = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "oatof_verify.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "$packageRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)",
            gate,
        )
        self.assertIn("$artifactRootPath = Join-Path $workspaceRoot 'artifacts'", gate)
        self.assertIn(
            "& (Join-Path $packageRoot 'workflows/resources/verify_reference_analysis.ps1')",
            gate,
        )
        self.assertIn(
            "-WorkspaceRoot $workspaceRoot -ArtifactRootPath $artifactRootPath "
            "-ScienceRoot $projectRoot -PythonExe $python",
            gate,
        )
        self.assertNotIn(
            "& (Join-Path $repoRoot "
            "'src/msplatform/workflows/resources/verify_reference_analysis.ps1')",
            gate,
        )

    def test_formal_runtime_accepts_governed_result_generations(self):
        gate = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'formal_n1000_coupled_longitudinal'", gate)
        self.assertIn("'formal_vnext_zero_physics_change_n1000'", gate)
        self.assertIn(
            "$allowedFormalResultStatuses -cnotcontains "
            "[string]$formalAssets.results.status",
            gate,
        )
        self.assertNotIn(
            "$formalAssets.results.status -ne 'formal_n1000_coupled_longitudinal'",
            gate,
        )

    def test_stable_runtime_uses_selected_python_and_component_artifact_root(self):
        gate = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "verify_stable_entry.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$artifactRoot = Resolve-RunArtifactRoot", gate)
        self.assertIn("$formalRoot = Join-Path $artifactRoot", gate)
        self.assertIn("-ArtifactRoot $artifactRoot -PythonExe $python", gate)
        self.assertNotIn("Join-Path $repoRoot '.venv", gate)

    def test_formal_runtime_uses_immutable_simion_manifests_not_git_source_hashes(self):
        gate = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        stable_gate = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "verify_stable_entry.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$formalAssets.simion_manifest", gate)
        self.assertIn("verify_stable_entry.ps1", gate)
        self.assertIn("artifact_workspace_relative -ne 'formal'", stable_gate)
        self.assertIn("$entry.manifests.formal_asset_manifest", stable_gate)
        self.assertIn("$entry.manifests.simion_delivery_manifest", stable_gate)
        self.assertIn("program = 'simion_program'", stable_gate)
        self.assertIn("fly2 = 'simion_fly2'", stable_gate)
        self.assertNotIn(
            "Get-FileHash -LiteralPath $simionLua", gate
        )
        self.assertNotIn(
            "Get-FileHash -LiteralPath $simionFly2", gate
        )


if __name__ == "__main__":
    unittest.main()
