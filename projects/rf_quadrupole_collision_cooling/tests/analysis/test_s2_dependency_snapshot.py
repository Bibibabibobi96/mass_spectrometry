from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path, PurePosixPath
from unittest import mock

from projects.rf_quadrupole_collision_cooling.analysis import (
    validate_s2_passive_connector as validator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
DEPENDENCY_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_s2_dependencies.json"
SUPPORT = PROJECT_ROOT / "tests" / "support" / "rf_run_artifact_support.ps1"
S2_RUNNER = PROJECT_ROOT / "tests" / "comsol" / "run_s2_passive_connector_field.ps1"
S2_LOCAL_PYTHON_SOURCES = {
    "projects/rf_quadrupole_collision_cooling/analysis/resolve_s2_connector_case.py",
    "projects/rf_quadrupole_collision_cooling/analysis/validate_s2_passive_connector.py",
    "projects/rf_quadrupole_collision_cooling/analysis/build_oatof_handoff.py",
    "projects/rf_quadrupole_collision_cooling/analysis/resolve_spatial_registration.py",
}


EXPECTED_PATHS = {
    "s2_passive_connector": {
        "projects/oa_tof/config/baseline.json",
        "projects/oa_tof/comsol/oatof_build_accelerator_geometry.m",
        "projects/oa_tof/analysis/rf_handoff_adapter.py",
        "projects/rf_quadrupole_collision_cooling/analysis/migrate_legacy_component_particle_state.py",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_interface_stages.json",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_shared_physical_port_joint_geometry.json",
        "projects/rf_quadrupole_collision_cooling/config/resolved_design_official.json",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_s2_dependencies.json",
        "common/contracts/rigid_transform.py",
        "common/contracts/particle_physics.py",
        "common/contracts/component_particle_state.py",
        "common/contracts/schemas/component_particle_state.schema.json",
        "common/contracts/file_identity.py",
        "common/contracts/spatial_registration.py",
        "common/contracts/verify_run_manifest.py",
        "common/contracts/artifact_naming.py",
        "common/contracts/write_run_manifest.py",
        "common/contracts/run_artifact_support.ps1",
        "common/require_powershell7.ps1",
        "common/comsol/run_comsol_r2025b.ps1",
        "common/comsol/resolve_comsol_64.ps1",
        "common/comsol/livelink_failure_classification.ps1",
        "common/comsol/livelink_environment.ps1",
        "common/comsol/livelink_r2025b/comsolstartup.m",
    },
    "s3_pulse_capture": {
        "projects/oa_tof/config/baseline.json",
        "projects/oa_tof/comsol/oatof_build_accelerator_geometry.m",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_interface_stages.json",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_shared_physical_port_joint_geometry.json",
        "projects/rf_quadrupole_collision_cooling/config/resolved_design_official.json",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_s2_dependencies.json",
        "projects/rf_quadrupole_collision_cooling/analysis/derive_shared_centroid_pulse_time.py",
        "projects/rf_quadrupole_collision_cooling/analysis/plot_shared_pulse_geometry_snapshot.py",
        "projects/rf_quadrupole_collision_cooling/analysis/audit_s3_pulse_chain.py",
        "projects/rf_quadrupole_collision_cooling/analysis/build_s3_local_exit_component_state.py",
        "common/contracts/rigid_transform.py",
        "common/contracts/particle_physics.py",
        "common/contracts/component_particle_state.py",
        "common/contracts/schemas/component_particle_state.schema.json",
        "common/contracts/file_identity.py",
        "common/contracts/verify_run_manifest.py",
        "common/contracts/artifact_naming.py",
        "common/contracts/write_run_manifest.py",
        "common/contracts/run_artifact_support.ps1",
        "common/require_powershell7.ps1",
        "common/comsol/run_comsol_r2025b.ps1",
        "common/comsol/resolve_comsol_64.ps1",
        "common/comsol/livelink_failure_classification.ps1",
        "common/comsol/livelink_environment.ps1",
        "common/comsol/livelink_r2025b/comsolstartup.m",
    },
    "s3_end_to_end": {
        "projects/oa_tof/analysis/rf_handoff_adapter.py",
        "projects/oa_tof/config/resolved_geometry.json",
        "projects/oa_tof/analysis/build_handoff_pulse_program.py",
        "projects/oa_tof/simion/workbench/formal/oatof_ideal_grounded.lua",
        "projects/oa_tof/simion/workbench/candidates/oatof_handoff_pulse.lua",
        "projects/oa_tof/simion/workbench/analyze_ideal_field_log.ps1",
        "projects/oa_tof/analysis/solver_diagnostics.py",
        "projects/rf_quadrupole_collision_cooling/analysis/migrate_legacy_component_particle_state.py",
        "projects/rf_quadrupole_collision_cooling/config/rf_to_oatof_s2_dependencies.json",
        "projects/rf_quadrupole_collision_cooling/analysis/build_simion_input_from_canonical.py",
        "projects/rf_quadrupole_collision_cooling/analysis/analyze_s3_end_to_end.py",
        "projects/rf_quadrupole_collision_cooling/analysis/build_oatof_handoff.py",
        "common/contracts/rigid_transform.py",
        "common/contracts/particle_physics.py",
        "common/contracts/component_particle_state.py",
        "common/contracts/schemas/component_particle_state.schema.json",
        "common/contracts/file_identity.py",
        "common/contracts/verify_run_manifest.py",
        "common/contracts/artifact_naming.py",
        "common/contracts/write_run_manifest.py",
        "common/contracts/run_artifact_support.ps1",
        "common/require_powershell7.ps1",
    },
}


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


class DependencyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(DEPENDENCY_CONTRACT.read_text(encoding="utf-8"))

    def test_consumer_scoped_closures_are_explicit_and_complete(self) -> None:
        dependencies = self.contract["dependencies"]
        for consumer, expected in EXPECTED_PATHS.items():
            actual = {
                item["source_repo_path"]
                for item in dependencies
                if consumer in item["consumers"]
            }
            self.assertEqual(actual, expected, consumer)

    def test_sources_and_nested_snapshot_destinations_are_unique(self) -> None:
        dependencies = self.contract["dependencies"]
        for key in ("id", "source_repo_path", "run_input_name", "frozen_filename"):
            values = [item[key] for item in dependencies]
            self.assertEqual(len(values), len(set(values)), key)
        for item in dependencies:
            source = PurePosixPath(item["source_repo_path"])
            provider = PurePosixPath(item["provider_repo_path"])
            frozen = PurePosixPath(item["frozen_filename"])
            self.assertEqual(source.parts[: len(provider.parts)], provider.parts)
            self.assertEqual(frozen, PurePosixPath("runtime_snapshot") / source)
            self.assertTrue(REPO_ROOT.joinpath(*source.parts).is_file(), source)

    def test_s2_dependency_contract_is_frozen_before_consumer_parse(self) -> None:
        runner = S2_RUNNER.read_text(encoding="utf-8")
        freeze = runner.index(
            "$dependencyContractIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot"
        )
        parse = runner.index(
            "$dependencyDocument = Get-Content -LiteralPath $dependencyContract",
            freeze,
        )
        select = runner.index("$selectedDependencies = @(", parse)
        confirm = runner.index("Confirm-RfFrozenDependencyIdentity", select)
        self.assertLess(freeze, parse)
        self.assertLess(parse, select)
        self.assertLess(select, confirm)
        self.assertNotIn(
            "Get-Content -LiteralPath $dependencyContractSource", runner[freeze:select]
        )

    def test_frozen_self_contract_survives_live_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            inputs = root / "inputs"
            relative = Path(
                "projects/rf_quadrupole_collision_cooling/config/"
                "rf_to_oatof_s2_dependencies.json"
            )
            source = repo / relative
            snapshot = inputs / "runtime_snapshot" / relative
            source.parent.mkdir(parents=True)
            dependency = {
                "id": "rf_dependency_contract_snapshot",
                "provider_scope": "project",
                "provider_project": "rf_quadrupole_collision_cooling",
                "provider_repo_path": "projects/rf_quadrupole_collision_cooling",
                "source_repo_path": relative.as_posix(),
                "frozen_filename": f"runtime_snapshot/{relative.as_posix()}",
                "run_input_name": "dependency_contract",
                "consumers": ["s2_passive_connector", "s3_pulse_capture"],
            }
            source.write_text(
                json.dumps({"dependencies": [dependency]}), encoding="utf-8"
            )
            script = (
                f". '{_ps_literal(SUPPORT)}';"
                "$identity=Copy-RfStableFile "
                f"-SourceRunRoot '{_ps_literal(repo)}' "
                f"-SourcePath '{_ps_literal(source)}' "
                f"-Destination '{_ps_literal(snapshot)}' "
                "-Role 'dependency contract';"
                f"Set-Content -LiteralPath '{_ps_literal(source)}' "
                "-Value '{\"dependencies\":[]}';"
                f"$document=Get-Content -LiteralPath '{_ps_literal(snapshot)}' "
                "-Raw -Encoding UTF8|ConvertFrom-Json;"
                "Confirm-RfFrozenDependencyIdentity "
                f"-RepoRoot '{_ps_literal(repo)}' -InputDir '{_ps_literal(inputs)}' "
                "-Dependency $document.dependencies[0] "
                f"-ExpectedSourcePath '{_ps_literal(source)}' "
                f"-ExistingSnapshotPath '{_ps_literal(snapshot)}' "
                "-ExpectedSha256 $identity.sha256|Out-Null;"
                "exit 0"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                result.returncode, 0, script + "\n" + result.stdout + result.stderr
            )

    def test_comsol_wrapper_adjacent_closure_matches_s2_consumer_contract(self) -> None:
        consumer_sources = {
            item["source_repo_path"]
            for item in self.contract["dependencies"]
            if "s2_passive_connector" in item["consumers"]
        }
        wrapper_relative = "common/comsol/run_comsol_r2025b.ps1"
        wrapper = (REPO_ROOT / wrapper_relative).read_text(encoding="utf-8")
        adjacent_references = set(
            re.findall(r"Join-Path\s+\$PSScriptRoot\s+'([^']+)'", wrapper)
        )
        statically_required = {
            f"common/comsol/{reference.replace(chr(92), '/')}"
            for reference in adjacent_references
            if reference.endswith(".ps1")
        }
        if "livelink_r2025b" in adjacent_references:
            statically_required.add(
                "common/comsol/livelink_r2025b/comsolstartup.m"
            )
        declared_adjacent = {
            path
            for path in consumer_sources
            if path.startswith("common/comsol/") and path != wrapper_relative
        }
        self.assertEqual(declared_adjacent, statically_required)

    def _validate_with(self, dependency_contract: dict) -> None:
        original = validator._load_relative

        def load_relative(path: str, reference_root: Path = validator.PROJECT_ROOT) -> dict:
            if path == "config/rf_to_oatof_s2_dependencies.json":
                return dependency_contract
            return original(path, reference_root)

        with mock.patch.object(validator, "_load_relative", side_effect=load_relative):
            validator.validate_contract()

    def test_validator_selects_s2_subset_without_requiring_other_consumers(self) -> None:
        contract = deepcopy(self.contract)
        contract["dependencies"] = [
            item for item in contract["dependencies"]
            if item["id"] != "oatof_resolved_geometry"
        ]
        self._validate_with(contract)

    def test_validator_rejects_missing_s2_consumer_dependency(self) -> None:
        contract = deepcopy(self.contract)
        contract["dependencies"] = [
            item for item in contract["dependencies"]
            if item["id"] != "common_rigid_transform"
        ]
        with self.assertRaisesRegex(ValueError, "S2 consumer dependency subset"):
            self._validate_with(contract)

    def test_snapshot_requires_only_selected_consumer_sources_to_exist(self) -> None:
        e2e_only = deepcopy(self.contract)
        e2e_dependency = next(
            item for item in e2e_only["dependencies"]
            if item["id"] == "oatof_resolved_geometry"
        )
        e2e_dependency["source_repo_path"] = "projects/oa_tof/config/not_frozen.json"
        e2e_dependency["frozen_filename"] = (
            "runtime_snapshot/projects/oa_tof/config/not_frozen.json"
        )
        self._validate_with(e2e_only)

        s2_selected = deepcopy(self.contract)
        s2_dependency = next(
            item for item in s2_selected["dependencies"]
            if item["id"] == "common_rigid_transform"
        )
        s2_dependency["source_repo_path"] = "common/contracts/not_frozen.py"
        s2_dependency["frozen_filename"] = "runtime_snapshot/common/contracts/not_frozen.py"
        with self.assertRaisesRegex(ValueError, "source is missing"):
            self._validate_with(s2_selected)


class FrozenDependencyHelperTests(unittest.TestCase):
    def _invoke(self, repo: Path, inputs: Path, dependency: dict) -> subprocess.CompletedProcess[str]:
        dependency_path = repo / "dependency.json"
        dependency_path.write_text(json.dumps(dependency), encoding="utf-8")
        command = (
            f". '{_ps_literal(SUPPORT)}'; "
            f"$dependency = Get-Content -LiteralPath '{_ps_literal(dependency_path)}' "
            "-Raw -Encoding UTF8 | ConvertFrom-Json; "
            f"Copy-RfFrozenDependency -RepoRoot '{_ps_literal(repo)}' "
            f"-InputDir '{_ps_literal(inputs)}' -Dependency $dependency | ConvertTo-Json -Compress"
        )
        return subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=30,
        )

    @staticmethod
    def _dependency(**changes: object) -> dict:
        dependency = {
            "id": "provider_data",
            "provider_scope": "project",
            "provider_project": "provider",
            "provider_repo_path": "projects/provider",
            "source_repo_path": "projects/provider/data/source.txt",
            "frozen_filename": "runtime_snapshot/projects/provider/data/source.txt",
            "run_input_name": "provider_data",
            "consumers": ["s2_passive_connector"],
        }
        dependency.update(changes)
        return dependency

    def test_nested_snapshot_copy_preserves_sha_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            source = repo / "projects" / "provider" / "data" / "source.txt"
            source.parent.mkdir(parents=True)
            source.write_text("frozen dependency\n", encoding="utf-8")
            inputs = root / "inputs"
            inputs.mkdir()
            result = self._invoke(repo, inputs, self._dependency())
            self.assertEqual(result.returncode, 0, result.stderr)
            identity = json.loads(result.stdout)
            frozen = inputs / "runtime_snapshot" / "projects" / "provider" / "data" / "source.txt"
            self.assertEqual(frozen.read_bytes(), source.read_bytes())
            self.assertTrue(Path(identity["frozen_path"]).samefile(frozen))
            self.assertEqual(identity["provider_repo_path"], "projects/provider")
            self.assertEqual(identity["consumers"], ["s2_passive_connector"])
            self.assertRegex(identity["sha256"], r"^[0-9A-F]{64}$")

    def test_repository_common_scope_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            source = repo / "common" / "contracts" / "authority.py"
            source.parent.mkdir(parents=True)
            source.write_text("VALUE = 1\n", encoding="utf-8")
            inputs = root / "inputs"
            inputs.mkdir()
            dependency = self._dependency(
                provider_scope="repository_common",
                provider_project="common",
                provider_repo_path="common",
                source_repo_path="common/contracts/authority.py",
                frozen_filename="runtime_snapshot/common/contracts/authority.py",
            )
            result = self._invoke(repo, inputs, dependency)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((inputs / "runtime_snapshot/common/contracts/authority.py").is_file())

    def test_legacy_runner_alias_is_explicit_and_hash_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            source = repo / "projects" / "provider" / "data" / "source.txt"
            source.parent.mkdir(parents=True)
            source.write_text("compatibility copy\n", encoding="utf-8")
            inputs = root / "inputs"
            inputs.mkdir()
            dependency = self._dependency(compatibility_frozen_filename="source.txt")
            result = self._invoke(repo, inputs, dependency)
            self.assertEqual(result.returncode, 0, result.stderr)
            identity = json.loads(result.stdout)
            snapshot = inputs / "runtime_snapshot/projects/provider/data/source.txt"
            compatibility = inputs / "source.txt"
            self.assertEqual(source.read_bytes(), snapshot.read_bytes())
            self.assertEqual(source.read_bytes(), compatibility.read_bytes())
            self.assertTrue(Path(identity["snapshot_path"]).samefile(snapshot))
            self.assertTrue(Path(identity["frozen_path"]).samefile(compatibility))

    def test_provider_and_destination_escapes_are_rejected(self) -> None:
        cases = (
            self._dependency(source_repo_path="projects/other/source.txt"),
            self._dependency(frozen_filename="../escaped.txt"),
            self._dependency(provider_repo_path="projects/other"),
        )
        for dependency in cases:
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repo = root / "repo"
                for source in (
                    repo / "projects/provider/data/source.txt",
                    repo / "projects/other/source.txt",
                ):
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text("data\n", encoding="utf-8")
                inputs = root / "inputs"
                inputs.mkdir()
                result = self._invoke(repo, inputs, dependency)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "escaped.txt").exists())


class S2SnapshotRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = S2_RUNNER.read_text(encoding="utf-8")
        cls.support = SUPPORT.read_text(encoding="utf-8")

    def test_freeze_precedes_every_snapshot_python_consumer(self) -> None:
        freeze_index = self.runner.index("foreach ($dependency in $selectedDependencies)")
        local_freeze_index = self.runner.index(
            "$identity = Copy-S2LocalSnapshotInput", freeze_index
        )
        resolver_index = self.runner.index(
            "'projects.rf_quadrupole_collision_cooling.analysis.resolve_s2_connector_case'"
        )
        spatial_index = self.runner.index(
            "'projects.rf_quadrupole_collision_cooling.analysis.resolve_spatial_registration'"
        )
        validator_index = self.runner.index(
            "'projects.rf_quadrupole_collision_cooling.analysis.validate_s2_passive_connector'"
        )
        handoff_index = self.runner.index(
            "'projects.rf_quadrupole_collision_cooling.analysis.build_oatof_handoff'"
        )
        self.assertLess(freeze_index, resolver_index)
        self.assertLess(local_freeze_index, resolver_index)
        self.assertLess(resolver_index, spatial_index)
        self.assertLess(spatial_index, validator_index)
        self.assertLess(validator_index, handoff_index)
        self.assertIn("$dependencyConsumer = 's2_passive_connector'", self.runner)
        self.assertIn("Get-FileHash -LiteralPath $identity.snapshot_path", self.runner)
        self.assertIn("--reference-root',$snapshotRfProject", self.runner)

    def test_post_freeze_execution_has_no_live_repo_tool_path(self) -> None:
        for forbidden in (
            "$env:PYTHONPATH = $repoRoot",
            "Push-Location $repoRoot",
            "Join-Path $repoRoot 'common\\contracts\\verify_run_manifest.py'",
            "Join-Path $repoRoot 'common\\comsol\\run_comsol_r2025b.ps1'",
            "& $python $handoffBuilder",
            "& $python $connectorValidator",
        ):
            self.assertNotIn(forbidden, self.runner)
        for required in (
            "$manifestToolRoot = $snapshotRoot",
            "$frozenManifestVerifier = $dependencySnapshotPaths['common_verify_run_manifest']",
            "$frozenComsolRunner = $dependencySnapshotPaths['common_comsol_runner']",
            "& $frozenComsolRunner",
            "Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot",
            "Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $manifestToolRoot",
            "$env:PYTHONPATH = $SnapshotRoot",
            "$env:PYTHONNOUSERSITE = '1'",
        ):
            self.assertIn(required, self.runner)
        for required in (
            "function Write-RfFrozenRunManifest",
            "function Complete-RfFrozenFailedRun",
            "$env:PYTHONPATH = $FrozenRepoRoot",
            "$env:PYTHONNOUSERSITE = '1'",
            "Push-Location -LiteralPath $FrozenRepoRoot",
        ):
            self.assertIn(required, self.support)

    def test_manifest_writer_and_failed_recovery_reject_live_python_poison(self) -> None:
        frozen_sources = (
            "common/contracts/write_run_manifest.py",
            "common/contracts/verify_run_manifest.py",
            "common/contracts/artifact_naming.py",
            "common/contracts/file_identity.py",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            poison = root / "poison"
            for relative in frozen_sources:
                source = REPO_ROOT.joinpath(*PurePosixPath(relative).parts)
                destination = snapshot.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            poison_contracts = poison / "common" / "contracts"
            poison_contracts.mkdir(parents=True)
            for name in ("artifact_naming.py", "file_identity.py"):
                (poison_contracts / name).write_text(
                    "raise RuntimeError('poisoned live manifest dependency imported')\n",
                    encoding="utf-8",
                )

            run_dir = root / "20260724_160000__test__repo__s2-manifest-snapshot"
            input_dir = run_dir / "inputs"
            input_dir.mkdir(parents=True)
            primary_input = input_dir / "primary.txt"
            primary_input.write_text("primary\n", encoding="utf-8")
            recovered_input = input_dir / "post_freeze.txt"
            recovered_input.write_text("recover me\n", encoding="utf-8")
            run_config = run_dir / "run_config.json"
            summary = run_dir / "summary.json"
            run_config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run_dir.name,
                        "project": "rf_quadrupole_collision_cooling",
                        "mode": "s2_manifest_snapshot_test",
                        "inputs": {"primary": str(primary_input)},
                        "formal_gate_passed": False,
                    }
                ),
                encoding="utf-8",
            )
            command = (
                f". '{_ps_literal(SUPPORT)}'; "
                f"$env:PYTHONPATH = '{_ps_literal(poison)}'; "
                f"Push-Location -LiteralPath '{_ps_literal(poison)}'; "
                "try { "
                f"Write-RfFrozenRunManifest -Python '{_ps_literal(Path(sys.executable))}' "
                f"-FrozenRepoRoot '{_ps_literal(snapshot)}' "
                f"-RunConfig '{_ps_literal(run_config)}' -Status interrupted "
                "-Software @('Python 3.11'); "
                f"Complete-RfFrozenFailedRun -Python '{_ps_literal(Path(sys.executable))}' "
                f"-FrozenRepoRoot '{_ps_literal(snapshot)}' "
                f"-RunConfig '{_ps_literal(run_config)}' -Summary '{_ps_literal(summary)}' "
                "-SummaryRole 's2_manifest_snapshot_test' -Reason 'controlled failure' "
                "-Software @('Python 3.11') "
                "} finally { Pop-Location }; "
                f"if ($env:PYTHONPATH -ne '{_ps_literal(poison)}') {{ "
                "throw 'Frozen manifest wrapper did not restore PYTHONPATH.' }"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=poison,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
            recovered = json.loads(run_config.read_text(encoding="utf-8"))
            self.assertIn(str(recovered_input.resolve()), recovered["inputs"].values())

    def test_snapshot_imports_survive_poisoned_provider_tree(self) -> None:
        contract = json.loads(DEPENDENCY_CONTRACT.read_text(encoding="utf-8"))
        dependency_sources = {
            item["source_repo_path"] for item in contract["dependencies"]
            if "s2_passive_connector" in item["consumers"]
        }
        sources = dependency_sources | S2_LOCAL_PYTHON_SOURCES
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            poisoned_provider = root / "provider"
            for relative in sources:
                source = REPO_ROOT.joinpath(*PurePosixPath(relative).parts)
                for destination_root in (snapshot, poisoned_provider):
                    destination = destination_root.joinpath(*PurePosixPath(relative).parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                if relative.endswith(".py"):
                    poisoned_provider.joinpath(*PurePosixPath(relative).parts).write_text(
                        "raise RuntimeError('poisoned live provider imported')\n",
                        encoding="utf-8",
                    )
            modules = (
                "projects.rf_quadrupole_collision_cooling.analysis.resolve_s2_connector_case",
                "projects.rf_quadrupole_collision_cooling.analysis.resolve_spatial_registration",
                "projects.rf_quadrupole_collision_cooling.analysis.validate_s2_passive_connector",
                "projects.rf_quadrupole_collision_cooling.analysis.build_oatof_handoff",
                "projects.oa_tof.analysis.rf_handoff_adapter",
                "common.contracts.component_particle_state",
                "common.contracts.spatial_registration",
            )
            code = (
                "import importlib,json; "
                f"names={modules!r}; "
                "print(json.dumps([importlib.import_module(name).__file__ for name in names]))"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join((str(snapshot), str(poisoned_provider)))
            environment["PYTHONNOUSERSITE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=snapshot,
                env=environment,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for imported in json.loads(result.stdout):
                self.assertTrue(
                    Path(imported).resolve().is_relative_to(snapshot.resolve()), imported
                )
            validation = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "projects.rf_quadrupole_collision_cooling.analysis.validate_s2_passive_connector",
                    "--contract",
                    str(PROJECT_ROOT / "config/rf_to_oatof_s2_passive_connector.json"),
                    "--reference-root",
                    str(snapshot / "projects/rf_quadrupole_collision_cooling"),
                    "--resolved-registration",
                    str(
                        PROJECT_ROOT
                        / "config/resolved_rf_to_oatof_s2_spatial_registration.json"
                    ),
                ],
                cwd=snapshot,
                env=environment,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)
            self.assertIn("S2_PASSIVE_CONNECTOR=PASS", validation.stdout)


if __name__ == "__main__":
    unittest.main()
