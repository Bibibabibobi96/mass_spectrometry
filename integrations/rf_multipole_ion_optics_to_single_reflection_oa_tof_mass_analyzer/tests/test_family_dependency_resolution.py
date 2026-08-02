from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SUPPORT = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
RUN_ARTIFACT_SUPPORT = INTEGRATION_ROOT / "runtime" / "run_artifacts.ps1"
BASE = INTEGRATION_ROOT / "config" / "family_dependencies_base.json"
OVERLAY = (
    INTEGRATION_ROOT
    / "config"
    / "family_quadrupole_dependencies_overlay.json"
)


class FamilyDependencyResolutionTests(unittest.TestCase):
    def _run_merge(
        self,
        base: dict[str, object],
        overlay: dict[str, object],
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            base_path = temporary / "base.json"
            overlay_path = temporary / "overlay.json"
            base_path.write_text(json.dumps(base), encoding="utf-8")
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_OATOF_RUNTIME": str(RUNTIME_SUPPORT),
                    "RF_OATOF_REPO": str(REPO_ROOT),
                    "RF_OATOF_BASE": str(base_path),
                    "RF_OATOF_OVERLAY": str(overlay_path),
                }
            )
            return subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-Command",
                    ". $env:RF_OATOF_RUNTIME; "
                    "$d=Merge-RfOatofDependencyContracts "
                    "-RepoRoot $env:RF_OATOF_REPO "
                    "-BasePath $env:RF_OATOF_BASE "
                    "-OverlayPath $env:RF_OATOF_OVERLAY "
                    "-ExpectedUpstreamProjectId rf_quadrupole_ion_optics; "
                    "@($d.dependencies.id)|ConvertTo-Json -Compress",
                ],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

    def setUp(self) -> None:
        self.base = json.loads(BASE.read_text(encoding="utf-8"))
        self.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))

    def test_resolves_exact_stable_52_item_inventory(self) -> None:
        first = self._run_merge(self.base, self.overlay)
        second = self._run_merge(self.base, self.overlay)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_ids = json.loads(first.stdout)
        self.assertEqual(first_ids, json.loads(second.stdout))
        self.assertEqual(len(first_ids), 52)
        self.assertEqual(
            first_ids[-2:],
            ["rf_resolved_design", "rf_project_descriptor"],
        )

    def test_rejects_missing_base_dependency(self) -> None:
        base = copy.deepcopy(self.base)
        base["dependencies"].pop()
        result = self._run_merge(base, self.overlay)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("base set or stable order differs", result.stderr)

    def test_rejects_duplicate_overlay_identity(self) -> None:
        overlay = copy.deepcopy(self.overlay)
        overlay["dependencies"].append(copy.deepcopy(overlay["dependencies"][0]))
        result = self._run_merge(self.base, overlay)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only the two project authorities", result.stderr)

    def test_rejects_overlay_override_of_common_dependency(self) -> None:
        overlay = copy.deepcopy(self.overlay)
        overlay["dependencies"][0]["id"] = "oatof_baseline"
        result = self._run_merge(self.base, overlay)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only the two project authorities", result.stderr)

    def test_rejects_repository_path_escape(self) -> None:
        overlay = copy.deepcopy(self.overlay)
        overlay["dependencies"][0]["source_repo_path"] = "../outside.json"
        result = self._run_merge(self.base, overlay)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes the repository", result.stderr)

    def test_bound_file_rejects_stale_sha256(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "RF_OATOF_RUNTIME": str(RUNTIME_SUPPORT),
                "RF_OATOF_REPO": str(REPO_ROOT),
            }
        )
        command = (
            ". $env:RF_OATOF_RUNTIME; "
            "$r=[pscustomobject]@{path='README.md';sha256=('0'*64)}; "
            "Resolve-RfOatofBoundFile -Root $env:RF_OATOF_REPO "
            "-Record $r -Role stale-test"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 differs", result.stderr)

    def test_publishes_separate_authorities_and_52_item_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_OATOF_RUNTIME": str(RUNTIME_SUPPORT),
                    "RF_OATOF_ARTIFACTS": str(RUN_ARTIFACT_SUPPORT),
                    "RF_OATOF_REPO": str(REPO_ROOT),
                    "RF_OATOF_BASE": str(BASE),
                    "RF_OATOF_OVERLAY": str(OVERLAY),
                    "RF_OATOF_INPUT": temporary_directory,
                }
            )
            command = (
                ". $env:RF_OATOF_ARTIFACTS; . $env:RF_OATOF_RUNTIME; "
                "$d=Merge-RfOatofDependencyContracts "
                "-RepoRoot $env:RF_OATOF_REPO -BasePath $env:RF_OATOF_BASE "
                "-OverlayPath $env:RF_OATOF_OVERLAY "
                "-ExpectedUpstreamProjectId rf_quadrupole_ion_optics; "
                "$r=[pscustomobject]@{binding=[pscustomobject]@{contracts="
                "[pscustomobject]@{dependency_contract=[pscustomobject]@{"
                "base=[pscustomobject]@{path='integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "config/family_dependencies_base.json'};overlay=[pscustomobject]@{"
                "path='integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "config/family_quadrupole_dependencies_overlay.json'}}}};"
                "contracts=[pscustomobject]@{dependency_contract_base=$env:RF_OATOF_BASE;"
                "dependency_contract_overlay=$env:RF_OATOF_OVERLAY};"
                "dependency_contract=$d}; "
                "$p=Publish-RfOatofDependencyInventory -Runtime $r "
                "-RepoRoot $env:RF_OATOF_REPO -InputDir $env:RF_OATOF_INPUT "
                "-Role test; $i=Get-Content -LiteralPath $p.code_inventory_path "
                "-Raw|ConvertFrom-Json; [pscustomobject]@{count=@($i.dependencies).Count;"
                "base=(Test-Path -LiteralPath $p.base_path);"
                "overlay=(Test-Path -LiteralPath $p.overlay_path);"
                "base_sha=$i.authority.base.sha256;overlay_sha=$i.authority.overlay.sha256}"
                "|ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        publication = json.loads(result.stdout)
        self.assertEqual(publication["count"], 52)
        self.assertTrue(publication["base"])
        self.assertTrue(publication["overlay"])
        self.assertEqual(len(publication["base_sha"]), 64)
        self.assertEqual(len(publication["overlay_sha"]), 64)


if __name__ == "__main__":
    unittest.main()
