"""Regression tests for the integration-owned legacy source binding."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
WORKSPACE_ROOT = REPO_ROOT.parent
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
SUPPORT = INTEGRATION_ROOT / "runtime" / "run_artifacts.ps1"
BINDING_HELPER = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
RUNTIME_BINDING = (
    INTEGRATION_ROOT
    / "config"
    / "legacy_quadrupole_direct_mating_gap_0mm_runtime_binding.json"
)
SOURCE_CONTRACT = (
    INTEGRATION_ROOT / "config" / "legacy_quadrupole_n100_source_contract.json"
)
RUNNER = (
    INTEGRATION_ROOT
    / "stages"
    / "comsol"
    / "run_pre_pulse_interface_transport.ps1"
)
STAGE_RUNNERS = (
    RUNNER,
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pulse_capture.ps1",
    INTEGRATION_ROOT / "stages" / "cross_solver" / "run_analyzer_transport.ps1",
)
DEPENDENCIES = (
    REPO_ROOT
    / "projects"
    / "rf_quadrupole_ion_optics"
    / "config"
    / "rf_to_oatof_pre_pulse_dependencies.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def source_path(record: dict[str, str]) -> Path:
    return (WORKSPACE_ROOT / record["path"]).resolve()


class LegacySourceArtifactBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pwsh = shutil.which("pwsh")
        if self.pwsh is None:
            self.skipTest("pwsh is unavailable")
        self.binding = json.loads(RUNTIME_BINDING.read_text(encoding="utf-8"))
        self.source_contract = json.loads(
            SOURCE_CONTRACT.read_text(encoding="utf-8")
        )

    def run_powershell(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.pwsh,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )

    def write_minimal_resolved_connection(self, path: Path) -> None:
        canonical = self.source_contract["canonical_state"]
        path.write_text(
            json.dumps(
                {
                    "role": "resolved_connection_do_not_edit",
                    "compatibility": {"status": "pass"},
                    "selection": {
                        "connection_profile_id": self.binding[
                            "connection_profile_id"
                        ],
                        "upstream_project_id": self.binding[
                            "upstream_project_id"
                        ],
                    },
                    "sources": {
                        "upstream_authority": self.binding["contracts"][
                            "upstream_resolved_design"
                        ]
                    },
                    "port_geometry": {
                        "downstream": {
                            "coordinate_frame": {
                                "frame_id": canonical["frame_id"]
                            },
                            "clock": {"origin_id": canonical["clock_epoch_id"]},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def resolve_binding(
        self, resolved: Path, binding: Path = RUNTIME_BINDING
    ) -> subprocess.CompletedProcess[str]:
        command = (
            f". '{BINDING_HELPER}';"
            f"$r=Resolve-RfOatofRuntimeBinding -RepoRoot '{REPO_ROOT}' "
            f"-ResolvedConnection '{resolved}' -RuntimeBinding '{binding}' "
            f"-ExpectedConnectionProfileId '{self.binding['connection_profile_id']}';"
            "$r|Select-Object upstream_project_id,recorded_project_id,"
            "source_manifest,source_state,source_particle_source,"
            "source_adapter|ConvertTo-Json -Compress"
        )
        return self.run_powershell(command)

    def test_current_contract_resolves_recorded_legacy_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            resolved = Path(directory) / "resolved_connection.json"
            self.write_minimal_resolved_connection(resolved)
            completed = self.resolve_binding(resolved)
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            result = json.loads(completed.stdout)
            self.assertEqual(
                result["upstream_project_id"], "rf_quadrupole_ion_optics"
            )
            self.assertEqual(
                result["recorded_project_id"],
                "rf_quadrupole_collision_cooling",
            )
            self.assertEqual(
                Path(result["source_state"]),
                source_path(self.source_contract["source"]["state"]),
            )

    def test_recorded_project_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            root = Path(directory)
            resolved = root / "resolved_connection.json"
            self.write_minimal_resolved_connection(resolved)
            changed_contract = {
                **self.source_contract,
                "recorded_project_id": "rf_quadrupole_ion_optics",
            }
            contract_path = root / "source_contract.json"
            contract_path.write_text(
                json.dumps(changed_contract), encoding="utf-8"
            )
            changed_binding = json.loads(json.dumps(self.binding))
            changed_binding["contracts"]["source_contract"] = {
                "path": contract_path.relative_to(REPO_ROOT).as_posix(),
                "sha256": sha256(contract_path),
            }
            binding_path = root / "runtime_binding.json"
            binding_path.write_text(
                json.dumps(changed_binding), encoding="utf-8"
            )
            completed = self.resolve_binding(resolved, binding_path)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "source manifest does not prove",
                completed.stdout + completed.stderr,
            )

    def test_source_contract_freezes_manifest_state_and_particle_source(
        self,
    ) -> None:
        contract = self.source_contract
        self.assertEqual(contract["role"], "rf_multipole_oatof_source_contract")
        self.assertEqual(
            contract["recorded_project_id"],
            "rf_quadrupole_collision_cooling",
        )
        self.assertEqual(
            contract["source"]["particle_source_manifest_input_role"],
            "particle_table",
        )
        manifest_path = source_path(contract["source"]["manifest"])
        state_path = source_path(contract["source"]["state"])
        particle_source_path = source_path(contract["source"]["particle_source"])
        for role, path in (
            ("manifest", manifest_path),
            ("state", state_path),
            ("particle_source", particle_source_path),
        ):
            self.assertEqual(
                sha256(path), contract["source"][role]["sha256"]
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["project"], contract["recorded_project_id"])
        self.assertEqual(manifest["run_id"], contract["source"]["run_id"])
        particle_record = manifest["inputs"]["particle_table"]
        self.assertEqual(Path(particle_record["path"]), particle_source_path)
        self.assertEqual(
            particle_record["sha256"],
            contract["source"]["particle_source"]["sha256"],
        )
        state_records = [
            record
            for record in manifest["outputs"]
            if Path(record["path"]) == state_path
        ]
        self.assertEqual(len(state_records), 1)
        self.assertEqual(
            state_records[0]["sha256"], contract["source"]["state"]["sha256"]
        )
        with state_path.open(encoding="utf-8-sig", newline="") as handle:
            selected = [
                row
                for row in csv.DictReader(handle)
                if row["event"] == contract["selector"]["event"]
                and row["status"] == contract["selector"]["status"]
            ]
        self.assertEqual(len(selected), contract["source"]["particle_count"])

    def test_active_runner_consumes_runtime_binding_not_project_mapping(
        self,
    ) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        for required in (
            "$runtime.recorded_project_id",
            "$runtime.source_manifest",
            "$runtime.source_state",
            "$runtime.source_adapter",
        ):
            self.assertIn(required, runner)
        for retired in (
            "Resolve-RfDeclaredLegacyRunDirectory",
            "source_artifact_binding",
            "legacy_mapping_id",
        ):
            self.assertNotIn(retired, runner)

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
                f". '{SUPPORT}';"
                f"$r=Initialize-RfIntegrationStageBudget -ResolvedBudget '{budget}' "
                f"-InputDir '{input_dir}' -ExpectedIntegrationId integration_v1 "
                "-ExpectedConnectionProfileId profile_v1 -StageId pulse_capture "
                "-Solver comsol;$r|ConvertTo-Json -Compress"
            )
            completed = self.run_powershell(command)
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            result = json.loads(completed.stdout)
            stage = json.loads(
                (input_dir / "resolved_resource_budget__pulse_capture.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            self.assertEqual(stage["limits"]["wall_clock_seconds"], 10)
            self.assertEqual(stage["limits"]["automatic_retry_count"], 0)
            self.assertEqual(
                result["stage_budget_sha256"],
                sha256(input_dir / "resolved_resource_budget__pulse_capture.json"),
            )


if __name__ == "__main__":
    unittest.main()
