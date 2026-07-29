"""Regression tests for immutable legacy run inputs used by RF-to-oaTOF."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "projects" / "rf_quadrupole_ion_optics"
SUPPORT = PROJECT_ROOT / "runtime" / "run_artifacts.ps1"
RUNNER = (
    PROJECT_ROOT
    / "workflows"
    / "rf_to_oatof_integration"
    / "comsol"
    / "run_pre_pulse_interface_transport.ps1"
)
WORKFLOW_ROOT = PROJECT_ROOT / "workflows" / "rf_to_oatof_integration"
STAGE_RUNNERS = (
    WORKFLOW_ROOT / "comsol" / "run_pre_pulse_interface_transport.ps1",
    WORKFLOW_ROOT / "comsol" / "run_pulse_capture.ps1",
    WORKFLOW_ROOT / "cross_solver" / "run_analyzer_transport.ps1",
)
DEPENDENCIES = (
    PROJECT_ROOT / "config" / "rf_to_oatof_pre_pulse_dependencies.json"
)
CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_pre_pulse_passive_connector.json"


class LegacySourceArtifactBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pwsh = shutil.which("pwsh")
        if self.pwsh is None:
            self.skipTest("pwsh is unavailable")

    def _fixture(self, root: Path, *, manifest_project: str) -> tuple[Path, str]:
        workspace = root / "workspace"
        run_id = "20260722_193000__sim__comsol__source__n100"
        run = (
            workspace
            / "artifacts"
            / "projects"
            / "retired_rf_project"
            / "runs"
            / run_id
        )
        run.mkdir(parents=True)
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "simulation_run_manifest",
                    "run_id": run_id,
                    "project": manifest_project,
                    "status": "success",
                }
            ),
            encoding="utf-8",
        )
        descriptor = root / "project.json"
        descriptor.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": "current_rf_project",
                    "legacy_identities": [
                        {
                            "mapping_id": "rename_v1",
                            "project_id": "retired_rf_project",
                            "artifact_root": "artifacts/projects/retired_rf_project",
                            "artifact_access": "read_only",
                            "new_runs_allowed": False,
                            "verification_identity": "recorded_project_id",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return descriptor, run_id

    def _resolve(
        self, workspace: Path, descriptor: Path, run_id: str
    ) -> subprocess.CompletedProcess[str]:
        command = (
            f". '{SUPPORT}'; "
            f"$r=Resolve-RfDeclaredLegacyRunDirectory -WorkspaceRoot '{workspace}' "
            f"-ProjectDescriptor '{descriptor}' -MappingId rename_v1 "
            f"-RecordedProjectId retired_rf_project -RunId '{run_id}'; "
            "$r | ConvertTo-Json -Compress"
        )
        return subprocess.run(
            [self.pwsh, "-NoProfile", "-Command", command],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )

    def test_declared_read_only_mapping_resolves_one_success_run(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            root = Path(directory)
            descriptor, run_id = self._fixture(
                root, manifest_project="retired_rf_project"
            )
            completed = self._resolve(root / "workspace", descriptor, run_id)
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            result = json.loads(completed.stdout)
            self.assertEqual(result["mapping_id"], "rename_v1")
            self.assertEqual(result["recorded_project_id"], "retired_rf_project")
            self.assertEqual(
                result["artifact_root"], "artifacts/projects/retired_rf_project"
            )

    def test_manifest_recorded_project_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            root = Path(directory)
            descriptor, run_id = self._fixture(
                root, manifest_project="current_rf_project"
            )
            completed = self._resolve(root / "workspace", descriptor, run_id)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "manifest identity or status differs",
                completed.stdout + completed.stderr,
            )

    def test_active_runner_consumes_the_frozen_binding(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        binding = contract["particle_runtime"]["source_artifact_binding"]
        self.assertEqual(binding["project_descriptor_dependency_id"], "rf_project_descriptor")
        self.assertEqual(binding["legacy_mapping_id"], "rf_quad_rename_20260728")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Resolve-RfDeclaredLegacyRunDirectory", runner)
        self.assertNotIn(
            "$resolvedConnection = Join-Path",
            runner,
            "PowerShell parameter names are case-insensitive",
        )
        self.assertNotIn(
            "$sourceRun = Join-Path (Join-Path $artifactRoot 'runs')",
            runner,
        )

    def test_all_solver_stages_share_compact_retention_and_runtime_budgets(
        self,
    ) -> None:
        for runner_path in STAGE_RUNNERS:
            with self.subTest(runner=runner_path.name):
                runner = runner_path.read_text(encoding="utf-8")
                self.assertIn(
                    "[Parameter(Mandatory)][string]$ResolvedEngineeringBudget",
                    runner,
                )
                self.assertIn("-RetentionContractEnabled", runner)
                self.assertIn("Apply-RunArtifactRetention", runner)
                self.assertIn("Invoke-ResourceBudgetedProcess", runner)
                self.assertIn("Complete-ResourceUsage", runner)
                self.assertLess(
                    runner.index("Apply-RunArtifactRetention"),
                    runner.index("Complete-ResourceUsage"),
                )

    def test_dependency_snapshot_contains_one_common_budget_and_retention_stack(
        self,
    ) -> None:
        dependencies = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
        identifiers = [item["id"] for item in dependencies["dependencies"]]
        for expected in (
            "common_artifact_retention",
            "common_artifact_retention_policy",
            "common_resource_budget_support",
        ):
            self.assertEqual(identifiers.count(expected), 1)

    def test_analyzer_uses_the_shared_run_package_only(self) -> None:
        analyzer = STAGE_RUNNERS[-1].read_text(encoding="utf-8")
        self.assertEqual(analyzer.count("New-RfRunPackage"), 1)
        self.assertNotIn("Start-Process -FilePath $SimionExe", analyzer)

    def test_resolved_stage_budget_is_frozen_and_narrowed(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            root = Path(directory)
            budget = root / "resolved.json"
            input_dir = root / "inputs"
            input_dir.mkdir()
            budget.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "integration_resolved_engineering_budget",
                        "integration_id": "integration_v1",
                        "connection_profile_id": "profile_v1",
                        "particle_count": 100,
                        "retention_class": "compact",
                        "source_identity": {"run_id": "source_v1"},
                        "stage_limits": {
                            "pulse_capture": {
                                "solver": "comsol",
                                "wall_clock_seconds": 10,
                                "transient_run_directory_bytes": 20,
                                "process_tree_working_set_bytes": 30,
                                "minimum_system_available_memory_bytes": 40,
                                "compact_final_retained_bytes": 50,
                                "automatic_retry_count": 0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            command = (
                f". '{SUPPORT}'; "
                f"$r=Initialize-RfIntegrationStageBudget -ResolvedBudget '{budget}' "
                f"-InputDir '{input_dir}' -ExpectedIntegrationId integration_v1 "
                "-ExpectedConnectionProfileId profile_v1 -StageId pulse_capture "
                "-Solver comsol; $r | ConvertTo-Json -Compress"
            )
            completed = subprocess.run(
                [self.pwsh, "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            stage = json.loads(
                (input_dir / "resolved_resource_budget__pulse_capture.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            self.assertEqual(stage["limits"]["wall_clock_seconds"], 10)
            self.assertEqual(stage["limits"]["automatic_retry_count"], 0)


if __name__ == "__main__":
    unittest.main()
