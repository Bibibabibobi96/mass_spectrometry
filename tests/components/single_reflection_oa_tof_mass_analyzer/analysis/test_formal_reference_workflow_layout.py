from __future__ import annotations

import unittest
import base64
import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4] / "src/msplatform/components/single_reflection_oa_tof"


class FormalReferenceWorkflowLayoutTests(unittest.TestCase):
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





    def test_single_formal_cli_has_explicit_phases_and_serializes_solvers(self):
        runner = (
            PROJECT_ROOT.parents[1] / "workflows/resources" / "run_formal_validation.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('Validate','Publish','Recover','Verify')]",
            runner,
        )
        self.assertIn("--recover", runner)
        self.assertIn("--verify-hashes", runner)
        self.assertIn("--project single_reflection_oa_tof_mass_analyzer", runner)
        self.assertIn(
            "-WorkspaceRoot $workspaceRoot -ArtifactRootPath $artifactRootPath "
            "-ScienceRoot $projectRoot -PythonExe $python",
            runner,
        )
        self.assertIn(
            "msplatform.workflows.oa_formal."
            "publish_formal_release",
            runner,
        )
        self.assertIn("Copy-VerifiedRunInput", runner)
        self.assertIn("Complete-FailedRun", runner)
        self.assertIn("-RetentionClass qualification", runner)
        self.assertIn("-CapacityLedgerLifecycleEnabled", runner)
        self.assertLess(
            runner.index("$runRecordComplete = $false"),
            runner.index("New-RunPackage"),
        )
        self.assertIn("$candidateManifestSource --require-status success", runner)
        self.assertIn("$candidateDiffPath", runner)
        self.assertIn("$candidateMphSource", runner)
        self.assertIn("$candidateSimionSource -Recurse -File", runner)
        self.assertIn("$candidateMph = Copy-VerifiedRunInput", runner)
        self.assertIn("$ion = Join-Path $candidateSimion", runner)
        self.assertIn("$iob = Join-Path $candidateSimion", runner)
        self.assertLess(
            runner.index("backends\\comsol\\launcher\\run_comsol_r2025b.ps1"),
            runner.index("Start-Process -FilePath $SimionExe"),
        )
        self.assertLess(
            runner.index("Start-Process -FilePath $SimionExe"),
            runner.index("oa_candidate.reference_analysis compare"),
        )
        for retired in (
            "run_formal_vnext_validation.ps1",
            "run_oatof_formal_cad_sync.m",
        ):
            self.assertFalse(
                (
                    PROJECT_ROOT
                    / "workflows"
                    / "formal_reference"
                    / retired
                ).exists()
            )
        self.assertFalse(
            (PROJECT_ROOT.parents[1] / "workflows/oa_tof_design" / "publish_formal_validation.py").exists()
        )
        self.assertFalse(
            (PROJECT_ROOT.parents[1] / "workflows/oa_tof_design" / "promote_formal_vnext.py").exists()
        )
        self.assertFalse(
            (
                PROJECT_ROOT.parents[1] / "workflows/resources" / "run_coupled_baseline_validation.ps1"
            ).exists()
        )
        self.assertTrue(
            (PROJECT_ROOT.parents[1] / "workflows/oa_formal" / "publish_formal_release.py").is_file()
        )

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
