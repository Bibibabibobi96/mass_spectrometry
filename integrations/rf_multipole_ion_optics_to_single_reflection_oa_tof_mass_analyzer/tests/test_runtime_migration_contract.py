from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = INTEGRATION_ROOT / "runtime"
STAGES_ROOT = INTEGRATION_ROOT / "stages"
POWERSHELL = shutil.which("pwsh")
DEPENDENCY_CONTRACT = (
    REPO_ROOT
    / "projects"
    / "rf_quadrupole_ion_optics"
    / "config"
    / "rf_to_oatof_pre_pulse_dependencies.json"
)
LEGACY_COMPATIBILITY_PHASES = (
    REPO_ROOT
    / "projects"
    / "rf_quadrupole_ion_optics"
    / "config"
    / "rf_to_oatof_transfer_phases.json"
)
FAMILY_PHASES = INTEGRATION_ROOT / "config" / "family_transfer_phases.json"
FAMILY_DEPENDENCY_CONTRACTS = tuple(
    INTEGRATION_ROOT / "config" / f"family_{multipole}_dependencies.json"
    for multipole in ("quadrupole", "hexapole", "octupole")
)
STAGE_CONSUMERS = {
    STAGES_ROOT / "comsol" / "run_pre_pulse_interface_transport.ps1": (
        "pre_pulse_interface_transport"
    ),
    STAGES_ROOT / "comsol" / "run_pulse_capture.ps1": "pulse_capture",
    STAGES_ROOT / "cross_solver" / "run_analyzer_transport.ps1": (
        "analyzer_transport"
    ),
}
DEPENDENCY_REFERENCE = re.compile(
    r"\$dependency(?:Snapshot|Compatibility)?Paths\['([^']+)'\]"
    r"|\$dependencyPaths\['([^']+)'\]"
)
IMPLEMENTATION_PATHS = {
    "run_artifact_support": "runtime/run_artifacts.ps1",
    "runtime_binding_support": "runtime/runtime_binding.ps1",
    "transfer_runner": "runtime/run_transfer.ps1",
    "pre_pulse_runner": "stages/comsol/run_pre_pulse_interface_transport.ps1",
    "pre_pulse_builder": "stages/comsol/build_pre_pulse_interface_transport_model.m",
    "pre_pulse_field_preparer": (
        "stages/comsol/prepare_pre_pulse_interface_transport_field_model.m"
    ),
    "pre_pulse_field_solver": (
        "stages/comsol/solve_pre_pulse_interface_transport_field.m"
    ),
    "pulse_capture_runner": "stages/comsol/run_pulse_capture.ps1",
    "pulse_capture_solver": "stages/comsol/solve_pulse_capture.m",
    "analyzer_transport_runner": (
        "stages/cross_solver/run_analyzer_transport.ps1"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def repo_record(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(REPO_ROOT).as_posix(), "sha256": sha256(path)}


def workspace_record(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(WORKSPACE_ROOT).as_posix(),
        "sha256": sha256(path),
    }


class RuntimeDependencyContractTests(unittest.TestCase):
    def test_current_public_and_phase_entrypoints_exist(self) -> None:
        retired_entrypoint_fragments = (
            (
                "projects/rf_quadrupole_ion_optics/"
                "workflows/rf_to_oatof_integration/"
            ),
            "workflows/rf_to_oatof_integration/",
        )
        phase_contracts = (
            (
                LEGACY_COMPATIBILITY_PHASES,
                REPO_ROOT,
                (
                    "integrations/"
                    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                    "execute_integration.ps1"
                ),
            ),
            (
                FAMILY_PHASES,
                INTEGRATION_ROOT,
                "workflows/family_source_closure/execute.ps1",
            ),
        )
        for contract_path, entrypoint_root, expected_public_entrypoint in phase_contracts:
            with self.subTest(contract=contract_path.name):
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    contract["active_entrypoint"],
                    expected_public_entrypoint,
                )
                entrypoints = [
                    contract["active_entrypoint"],
                    *(phase["entrypoint"] for phase in contract["phases"]),
                ]
                for entrypoint in entrypoints:
                    self.assertFalse(
                        any(
                            fragment in entrypoint
                            for fragment in retired_entrypoint_fragments
                        ),
                        entrypoint,
                    )
                    self.assertTrue(
                        (entrypoint_root / entrypoint).is_file(),
                        entrypoint,
                    )

    def test_stage_dependency_references_are_consumer_authorized(self) -> None:
        document = json.loads(DEPENDENCY_CONTRACT.read_text(encoding="utf-8"))
        records = {item["id"]: item for item in document["dependencies"]}
        self.assertEqual(len(records), len(document["dependencies"]))
        dependency_documents = [
            document,
            *[
                json.loads(path.read_text(encoding="utf-8"))
                for path in FAMILY_DEPENDENCY_CONTRACTS
            ],
        ]

        for stage, consumer in STAGE_CONSUMERS.items():
            references = {
                first or second
                for first, second in DEPENDENCY_REFERENCE.findall(
                    stage.read_text(encoding="utf-8")
                )
            }
            authorized = {
                item["id"]
                for dependency_document in dependency_documents
                for item in dependency_document["dependencies"]
                if consumer in item["consumers"]
            }
            self.assertTrue(references, stage)
            self.assertLessEqual(references, authorized, stage)

        expected = {
            "rf_oatof_handoff_builder": {
                "path": (
                    "projects/rf_quadrupole_ion_optics/analysis/"
                    "build_oatof_handoff.py"
                ),
                "consumers": {
                    "pre_pulse_interface_transport",
                    "analyzer_transport",
                },
            },
            "common_create_multipole_round_rods": {
                "path": "common/comsol/create_multipole_round_rods.m",
                "consumers": {
                    "pre_pulse_interface_transport",
                    "pulse_capture",
                },
            },
        }
        for dependency_id, identity in expected.items():
            record = records[dependency_id]
            source = REPO_ROOT / identity["path"]
            self.assertEqual(record["source_repo_path"], identity["path"])
            self.assertEqual(set(record["consumers"]), identity["consumers"])
            self.assertTrue(source.is_file(), source)
            self.assertEqual(record["sha256"], sha256(source))


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required")
class RuntimeMigrationContractTests(unittest.TestCase):
    def run_powershell(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    @unittest.skipUnless(POWERSHELL, "PowerShell 7 is required")
    def test_integration_scoped_dependency_is_frozen(self) -> None:
        dependency_contract = (
            INTEGRATION_ROOT
            / "config"
            / "family_quadrupole_dependencies.json"
        )
        temporary_root = REPO_ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            input_dir = Path(directory) / "inputs"
            input_dir.mkdir()
            command = (
                f". '{RUNTIME_ROOT / 'run_artifacts.ps1'}';"
                f"$d=Get-Content -LiteralPath '{dependency_contract}' -Raw|"
                "ConvertFrom-Json;"
                "$x=@($d.dependencies|Where-Object "
                "{$_.id -eq 'rf_interface_stage_plan'})[0];"
                f"$r1=Copy-RfFrozenDependency -RepoRoot '{REPO_ROOT}' "
                f"-InputDir '{input_dir}' -Dependency $x;"
                "$s=@($d.dependencies|Where-Object "
                "{$_.id -eq 'rf_dependency_contract_snapshot'})[0];"
                f"$sp=Join-Path '{input_dir}' $s.frozen_filename;"
                "$null=New-Item -ItemType Directory -Force "
                "-Path (Split-Path -Parent $sp);"
                f"Copy-Item -LiteralPath '{dependency_contract}' "
                "-Destination $sp;"
                f"$h=(Get-FileHash -LiteralPath '{dependency_contract}' "
                "-Algorithm SHA256).Hash;"
                f"$r2=Confirm-RfFrozenDependencyIdentity -RepoRoot "
                f"'{REPO_ROOT}' -InputDir '{input_dir}' -Dependency $s "
                f"-ExpectedSourcePath '{dependency_contract}' "
                "-ExistingSnapshotPath $sp -ExpectedSha256 $h;"
                "@($r1,$r2)|Select-Object id,provider_scope,snapshot_path|"
                "ConvertTo-Json -Compress"
            )
            result = self.run_powershell(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(
                [item["id"] for item in value],
                [
                    "rf_interface_stage_plan",
                    "rf_dependency_contract_snapshot",
                ],
            )
            self.assertEqual(
                {item["provider_scope"] for item in value},
                {"integration"},
            )
            self.assertTrue(
                all(Path(item["snapshot_path"]).is_file() for item in value)
            )

    def test_moved_runtime_has_no_quadrupole_or_legacy_source_authority(self) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [*RUNTIME_ROOT.rglob("*.ps1"), *STAGES_ROOT.rglob("*.ps1")]
        )
        self.assertNotIn("rf_quadrupole_ion_optics", sources)
        self.assertNotIn("Resolve-RfDeclaredLegacyRunDirectory", sources)
        self.assertNotIn("projects.rf_quadrupole_ion_optics", sources)
        self.assertIn("$runtime.source_manifest", sources)
        self.assertIn("$runtime.source_state", sources)
        self.assertIn("$runtime.source_adapter", sources)
        self.assertIn("project = $upstreamProjectId", sources)

    def test_old_project_runtime_entrypoints_are_absent(self) -> None:
        old_root = (
            REPO_ROOT
            / "projects"
            / "rf_quadrupole_ion_optics"
            / "workflows"
            / "rf_to_oatof_integration"
        )
        self.assertFalse(old_root.exists() and any(old_root.rglob("*.*")))
        self.assertFalse(
            (
                REPO_ROOT
                / "projects"
                / "rf_quadrupole_ion_optics"
                / "runtime"
                / "run_artifacts.ps1"
            ).exists()
        )

    def test_fixed_runtime_has_one_binding_and_no_solver_selector(self) -> None:
        adapter = (INTEGRATION_ROOT / "adapter.ps1").read_text(encoding="utf-8")
        runtime = (RUNTIME_ROOT / "run_transfer.ps1").read_text(encoding="utf-8")
        self.assertIn("'runtime_binding_path'", adapter)
        self.assertIn("'runtime_binding_sha256'", adapter)
        self.assertNotIn("workflow_entrypoint", adapter)
        self.assertIn(
            "$workflowEntrypoint = $implementation.transfer_runner",
            adapter,
        )
        self.assertIn("$fixedTransferRunner", adapter)
        self.assertIn("$workflowEntrypoint.Equals(", adapter)
        self.assertIn(
            "Frozen transfer runner differs from the sole integration entrypoint.",
            adapter,
        )
        self.assertIn("[Parameter(Mandatory)][string]$RuntimeBinding", runtime)
        self.assertNotIn("$Solver", runtime)

    def test_resolved_rod_array_drives_common_geometry_builder(self) -> None:
        builder = (
            STAGES_ROOT / "comsol" / "build_pre_pulse_interface_transport_model.m"
        ).read_text(encoding="utf-8")
        field = (
            STAGES_ROOT
            / "comsol"
            / "prepare_pre_pulse_interface_transport_field_model.m"
        ).read_text(encoding="utf-8")
        self.assertIn("create_multipole_round_rods", builder)
        self.assertIn("g.rod_array", builder)
        self.assertNotIn("1:4", builder)
        self.assertIn("electrode_group", field)

    def test_stage_budget_freezes_positive_compact_no_retry_limits(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            root = Path(directory)
            budget = root / "resolved_budget.json"
            inputs = root / "inputs"
            inputs.mkdir()
            write_json(
                budget,
                {
                    "schema_version": 1,
                    "role": "integration_resolved_engineering_budget",
                    "integration_id": INTEGRATION_ROOT.name,
                    "connection_profile_id": "fixture_profile",
                    "particle_count": 100,
                    "retention_class": "compact",
                    "source_identity": {"sha256": "A" * 64},
                    "stage_limits": {
                        "pre_pulse_interface_transport": {
                            "solver": "comsol",
                            "wall_clock_seconds": 1,
                            "transient_run_directory_bytes": 2,
                            "process_tree_working_set_bytes": 3,
                            "minimum_system_available_memory_bytes": 4,
                            "compact_final_retained_bytes": 5,
                            "automatic_retry_count": 0,
                        }
                    },
                },
            )
            command = (
                f". '{RUNTIME_ROOT / 'run_artifacts.ps1'}';"
                f"$r=Initialize-RfIntegrationStageBudget -ResolvedBudget '{budget}' "
                f"-InputDir '{inputs}' -ExpectedIntegrationId '{INTEGRATION_ROOT.name}' "
                "-ExpectedConnectionProfileId 'fixture_profile' "
                "-StageId 'pre_pulse_interface_transport' -Solver comsol;"
                "$r|ConvertTo-Json -Compress"
            )
            result = self.run_powershell(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["resolved_budget_sha256"], sha256(budget))
            self.assertEqual(
                value["stage_budget_sha256"], sha256(Path(value["stage_budget"]))
            )

    def test_runtime_binding_proves_manifest_state_source_and_count(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as directory:
            root = Path(directory)
            contracts = root / "contracts"
            artifacts = root / "artifacts"
            contracts.mkdir()
            artifacts.mkdir()
            dummy_contracts: dict[str, Path] = {}
            for name in (
                "dependency_contract",
                "pre_pulse_contract",
                "pulse_capture_contract",
                "pulse_timing_contract",
                "handoff_contract",
            ):
                path = contracts / f"{name}.json"
                write_json(path, {"schema_version": 1, "role": name})
                dummy_contracts[name] = path
            resolved_design = contracts / "resolved_design.json"
            write_json(resolved_design, {"schema_version": 1, "role": "resolved_design"})
            adapter = contracts / "adapter.py"
            adapter.write_text("# frozen publish_handoff fixture\n", encoding="utf-8")
            particle_source = artifacts / "particle_source.csv"
            particle_source.write_text("particle_id\n1\n", encoding="utf-8")
            state = artifacts / "particle_state.csv"
            with state.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("particle_id", "event", "status"))
                writer.writeheader()
                for index in range(100):
                    writer.writerow(
                        {
                            "particle_id": index + 1,
                            "event": "handoff",
                            "status": "transmitted",
                        }
                    )
            manifest = artifacts / "run_manifest.json"
            write_json(
                manifest,
                {
                    "role": "simulation_run_manifest",
                    "status": "success",
                    "project": "rf_hexapole_collision_cooling",
                    "run_id": "fixture_run",
                    "inputs": {
                        "particle_table": {
                            "path": str(particle_source.resolve()),
                            "exists": True,
                            "sha256": sha256(particle_source),
                        }
                    },
                    "outputs": [
                        {
                            "path": str(state.resolve()),
                            "exists": True,
                            "sha256": sha256(state),
                        }
                    ],
                },
            )
            source_contract = contracts / "source_contract.json"
            write_json(
                source_contract,
                {
                    "schema_version": 1,
                    "role": "rf_multipole_oatof_source_contract",
                    "upstream_project_id": "rf_hexapole_ion_optics",
                    "recorded_project_id": "rf_hexapole_collision_cooling",
                    "selector": {"event": "handoff", "status": "transmitted"},
                    "adapter": {
                        **repo_record(adapter),
                        "callable": "publish_handoff",
                        "output_schema": "component_particle_state_v1",
                    },
                    "canonical_state": {
                        "frame_id": "oatof_global",
                        "clock_epoch_id": "instrument_clock",
                        "lineage_policy": "preserve_root_birth_time_and_component_elapsed_time",
                        "species_policy": "frozen_particle_source_mass_and_charge",
                    },
                    "source": {
                        "run_id": "fixture_run",
                        "particle_count": 100,
                        "particle_source_manifest_input_role": "particle_table",
                        "manifest": workspace_record(manifest),
                        "state": workspace_record(state),
                        "particle_source": workspace_record(particle_source),
                    },
                },
            )
            profile_id = "fixture_profile"
            resolved = root / "resolved_connection.json"
            write_json(
                resolved,
                {
                    "role": "resolved_connection_do_not_edit",
                    "compatibility": {"status": "pass"},
                    "selection": {
                        "connection_profile_id": profile_id,
                        "upstream_project_id": "rf_hexapole_ion_optics",
                    },
                    "sources": {"upstream_authority": repo_record(resolved_design)},
                    "port_geometry": {
                        "downstream": {
                            "coordinate_frame": {"frame_id": "oatof_global"},
                            "clock": {"origin_id": "instrument_clock"},
                        }
                    },
                },
            )
            binding = root / "runtime_binding.json"
            contract_records = {
                name: repo_record(path) for name, path in dummy_contracts.items()
            }
            contract_records.update(
                {
                    "source_contract": repo_record(source_contract),
                    "upstream_resolved_design": repo_record(resolved_design),
                }
            )
            write_json(
                binding,
                {
                    "schema_version": 1,
                    "role": "rf_multipole_oatof_runtime_binding",
                    "integration_id": INTEGRATION_ROOT.name,
                    "connection_profile_id": profile_id,
                    "upstream_project_id": "rf_hexapole_ion_optics",
                    "contracts": contract_records,
                    "implementation": {
                        name: repo_record(INTEGRATION_ROOT / relative)
                        for name, relative in IMPLEMENTATION_PATHS.items()
                    },
                },
            )
            command = (
                f". '{RUNTIME_ROOT / 'runtime_binding.ps1'}';"
                f"$r=Resolve-RfOatofRuntimeBinding -RepoRoot '{REPO_ROOT}' "
                f"-ResolvedConnection '{resolved}' -RuntimeBinding '{binding}' "
                f"-ExpectedConnectionProfileId '{profile_id}';"
                "$r|Select-Object upstream_project_id,recorded_project_id,"
                "source_manifest,source_state,"
                "source_particle_source,source_adapter,"
                "implementation|ConvertTo-Json -Compress"
            )
            result = self.run_powershell(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["upstream_project_id"], "rf_hexapole_ion_optics")
            self.assertEqual(
                value["recorded_project_id"],
                "rf_hexapole_collision_cooling",
            )
            self.assertEqual(Path(value["source_state"]), state.resolve())
            self.assertEqual(Path(value["source_particle_source"]), particle_source.resolve())
            self.assertEqual(
                set(value["implementation"]),
                set(IMPLEMENTATION_PATHS),
            )
            for name, relative in IMPLEMENTATION_PATHS.items():
                self.assertEqual(
                    Path(value["implementation"][name]),
                    (INTEGRATION_ROOT / relative).resolve(),
                )


if __name__ == "__main__":
    unittest.main()
