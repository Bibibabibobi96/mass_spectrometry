from __future__ import annotations

import unittest
import base64
import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FormalReferenceWorkflowLayoutTests(unittest.TestCase):
    def _detector_source_gate(self, comsol: str) -> subprocess.CompletedProcess:
        """Execute the actual PowerShell source-binding checks, without native tools."""
        gate = (PROJECT_ROOT / "workflows/formal_reference/verify_geometry_contract.ps1").read_text(encoding="utf-8")
        helpers = "\n".join(re.findall(r"(?ms)^function Assert-(?:Not)?Contains\([^\n]*\n.*?^\}", gate))
        start = gate.index("# COMSOL detector source authority:")
        stop = gate.index("Assert-Contains $comsol 'contract = load_oatof_contract", start)
        payload = base64.b64encode(comsol.encode("utf-8")).decode("ascii")
        script = "$ErrorActionPreference='Stop'\n" + helpers + "\n" + (
            "$comsol=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'))\n"
        ) + gate[start:stop] + "\n'COMSOL_DETECTOR_SOURCE_AUTHORITY=PASS'\n"
        return subprocess.run(
            ["pwsh", "-NoProfile", "-Command", "$ErrorActionPreference='Stop'; & ([scriptblock]::Create([Console]::In.ReadToEnd()))"],
            input=script, cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_detector_source_gate_accepts_direct_resolved_authority(self):
        core = (PROJECT_ROOT / "comsol/oatof_build_model_core.m").read_text(encoding="utf-8")
        result = self._detector_source_gate(core)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COMSOL_DETECTOR_SOURCE_AUTHORITY=PASS", result.stdout)

    def test_detector_source_gate_rejects_mirrored_x_and_focus_z_drift(self):
        core = (PROJECT_ROOT / "comsol/oatof_build_model_core.m").read_text(encoding="utf-8")
        replacements = (
            ("sprintf('%.17g[mm]', contract.coordinate_convention.detector_x)", "'-x_accel_center'"),
            ("sprintf('%.17g[mm]', geometryMm.detector_z)", "'z_accel_grid2+accel_focus_drift'"),
        )
        for direct, stale in replacements:
            with self.subTest(stale=stale):
                self.assertIn(direct, core)
                result = self._detector_source_gate(core.replace(direct, stale))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("COMSOL_DETECTOR_SOURCE_AUTHORITY=PASS", result.stdout)

    def test_detector_source_gate_rejects_legacy_override_after_direct_assignment(self):
        core = (PROJECT_ROOT / "comsol/oatof_build_model_core.m").read_text(encoding="utf-8")
        for override in ("p.set('detector_x', '-x_accel_center');", "p.set('detector_z', 'z_accel_grid2+accel_focus_drift');"):
            with self.subTest(override=override):
                result = self._detector_source_gate(core + "\n" + override)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("COMSOL_DETECTOR_SOURCE_AUTHORITY=PASS", result.stdout)

    def test_single_formal_cli_has_explicit_phases_and_serializes_solvers(self):
        runner = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "run_formal_validation.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('Validate','Publish','Recover','Verify')]",
            runner,
        )
        self.assertIn("--recover", runner)
        self.assertIn("--verify-hashes", runner)
        self.assertIn("--project single_reflection_oa_tof_mass_analyzer", runner)
        self.assertIn(
            "projects.single_reflection_oa_tof_mass_analyzer.analysis."
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
            runner.index("common\\comsol\\run_comsol_r2025b.ps1"),
            runner.index("Start-Process -FilePath $SimionExe"),
        )
        self.assertLess(
            runner.index("Start-Process -FilePath $SimionExe"),
            runner.index("analysis.reference_analysis compare"),
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
            (PROJECT_ROOT / "analysis" / "publish_formal_validation.py").exists()
        )
        self.assertFalse(
            (PROJECT_ROOT / "analysis" / "promote_formal_vnext.py").exists()
        )
        self.assertFalse(
            (
                PROJECT_ROOT
                / "workflows"
                / "formal_reference"
                / "run_coupled_baseline_validation.ps1"
            ).exists()
        )
        self.assertTrue(
            (PROJECT_ROOT / "analysis" / "publish_formal_release.py").is_file()
        )

    def test_formal_runtime_accepts_governed_result_generations(self):
        gate = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "verify_geometry_contract.ps1"
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

    def test_formal_runtime_uses_immutable_simion_manifests_not_git_source_hashes(self):
        gate = (
            PROJECT_ROOT
            / "workflows"
            / "formal_reference"
            / "verify_geometry_contract.ps1"
        ).read_text(encoding="utf-8")
        stable_gate = (
            PROJECT_ROOT / "workflows" / "formal_reference" / "verify_stable_entry.ps1"
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
