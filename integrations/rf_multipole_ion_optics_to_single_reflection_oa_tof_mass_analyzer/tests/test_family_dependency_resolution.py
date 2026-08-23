from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import validate_schema


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = INTEGRATION_ROOT / "config"
INVENTORY = CONFIG_ROOT / "family_runtime_dependencies.json"
FAMILIES = ("quadrupole", "hexapole", "octupole")


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class FamilyDependencyResolutionTests(unittest.TestCase):
    def test_powershell_resolver_and_publisher_use_manifest_authority(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        binding_path = CONFIG_ROOT / "family_octupole_direct_mating_gap_0mm_runtime_binding.json"
        run_artifacts = INTEGRATION_ROOT / "runtime" / "run_artifacts.ps1"
        runtime_binding = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            script = f"""
$OutputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. '{run_artifacts}'
. '{runtime_binding}'
$runtimeBinding = Get-Content -LiteralPath '{binding_path}' -Raw | ConvertFrom-Json
$binding = Get-Content -LiteralPath '{INVENTORY}' -Raw | ConvertFrom-Json
$resolved = Resolve-RfOatofDependencyContract -RepoRoot '{REPO_ROOT}' -ContractPath '{INVENTORY}'
$runtime = [pscustomobject]@{{
  binding = $runtimeBinding
  contracts = [pscustomobject]@{{ dependency_contract = '{INVENTORY}' }}
  dependency_contract = $resolved
}}
$publication = Publish-RfOatofDependencyInventory -Runtime $runtime -RepoRoot '{REPO_ROOT}' -InputDir '{output}' -Role 'test'
$inventory = Get-Content -LiteralPath $publication.code_inventory_path -Raw | ConvertFrom-Json
if (@($inventory.dependencies | Where-Object {{ $_.id -eq 'common_multipole_simion_geometry' }}).Count -ne 1) {{ throw 'common renderer dependency differs' }}
if (@($inventory.dependencies | Where-Object {{ $_.id -eq 'rf_single_flight_electrode_contract' }}).Count -ne 1) {{ throw 'electrode contract dependency differs' }}
if ([string]::Join("`n", @($resolved.dependencies.id)) -ne [string]::Join("`n", @($binding.dependencies.id))) {{ throw 'resolved dependency order differs' }}
if ([string]::Join("`n", @($inventory.dependencies.id)) -ne [string]::Join("`n", @($binding.dependencies.id))) {{ throw 'published dependency order differs' }}
"RESOLVE_COUNT=$(@($resolved.dependencies).Count) PUBLISH_COUNT=$(@($inventory.dependencies).Count)"
"""
            result = subprocess.run(
                [pwsh, "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=300,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected_count = len(load(INVENTORY)["dependencies"])
        self.assertIn(
            f"RESOLVE_COUNT={expected_count} PUBLISH_COUNT={expected_count}",
            result.stdout,
        )

    def test_single_stable_unique_inventory(self) -> None:
        inventory = load(INVENTORY)
        dependencies = inventory["dependencies"]
        ids = [item["id"] for item in dependencies]
        run_inputs = [item["run_input_name"] for item in dependencies]
        self.assertGreater(len(dependencies), 0)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(run_inputs), len(set(run_inputs)))
        self.assertIn("oatof_finite_interval_design_compiler", ids)
        self.assertIn("common_multipole_simion_geometry", ids)
        self.assertIn("rf_single_flight_electrode_contract", ids)
        by_id = {item["id"]: item for item in dependencies}
        handoff_adapter = by_id["rf_oatof_handoff_adapter"]
        self.assertEqual(handoff_adapter["provider_scope"], "integration")
        self.assertEqual(
            handoff_adapter["source_repo_path"],
            "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runtime/rf_handoff_adapter.py",
        )
        self.assertEqual(
            handoff_adapter["consumers"],
            [
                "pre_pulse_interface_transport",
                "analyzer_transport",
                "single_flight_transport",
            ],
        )
        self.assertEqual(
            by_id["rf_analyzer_transport_simion_input_adapter"]["consumers"],
            ["analyzer_transport"],
        )
        self.assertFalse(
            (
                REPO_ROOT
                / "projects/single_reflection_oa_tof_mass_analyzer/analysis/"
                "rf_handoff_adapter.py"
            ).exists()
        )
        for successor in (
            "oatof_analyzer_component",
            "rf_single_flight_pulse_hook",
            "rf_single_flight_frontend_hook",
            "rf_single_flight_pure_boundary_validator",
            "common_multipole_simion_rf_drive_kernel",
        ):
            self.assertEqual(
                by_id[successor]["consumers"],
                ["single_flight_transport"],
            )
        for staged_legacy in (
            "oatof_formal_lua",
            "oatof_handoff_pulse_extension_lua",
        ):
            self.assertEqual(
                by_id[staged_legacy]["consumers"],
                ["analyzer_transport"],
            )
        self.assertEqual(
            inventory["consumer_scope"],
            "rf_multipole_registered_handoff_family",
        )
        for removed in (
            "rf_resolved_design",
            "rf_project_descriptor",
            "rf_family_source_bundle_publisher",
        ):
            self.assertNotIn(removed, ids)

    def test_inventory_paths_are_explicit_repository_files(self) -> None:
        inventory = load(INVENTORY)
        for dependency in inventory["dependencies"]:
            with self.subTest(dependency=dependency["id"]):
                relative = Path(dependency["source_repo_path"])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertTrue((REPO_ROOT / relative).is_file())

    def test_obsolete_base_and_overlays_are_absent(self) -> None:
        self.assertFalse((CONFIG_ROOT / "family_dependencies_base.json").exists())
        for family in FAMILIES:
            self.assertFalse(
                (CONFIG_ROOT / f"family_{family}_dependencies_overlay.json").exists()
            )

    def test_active_bindings_use_one_inventory_authority(self) -> None:
        expected_path = INVENTORY.relative_to(REPO_ROOT).as_posix()
        expected_sha256 = repository_text_sha256(INVENTORY)
        for family in FAMILIES:
            binding = load(
                CONFIG_ROOT
                / f"family_{family}_direct_mating_gap_0mm_runtime_binding.json"
            )
            validate_schema(binding, "rf_multipole_oatof_runtime_binding.schema.json")
            self.assertEqual(
                binding["contracts"]["dependency_contract"],
                {"path": expected_path, "sha256": expected_sha256},
            )

    def test_phase_contracts_use_run_local_source_and_design(self) -> None:
        expected = {
            "source_contract": "run_input:resolved_source_contract",
            "rf_resolved_geometry": "run_input:upstream_resolved_design",
        }
        for name in (
            "family_pre_pulse_interface_transport.json",
            "family_pulse_capture.json",
            "family_shared_physical_port_joint_geometry.json",
        ):
            contract = load(CONFIG_ROOT / name)
            inputs = contract.get("inputs", contract.get("authoritative_inputs"))
            with self.subTest(contract=name):
                for key, value in expected.items():
                    self.assertEqual(inputs[key], value)
        handoff = load(CONFIG_ROOT / "family_handoff.json")["source_component"]
        self.assertEqual(
            handoff["profile"],
            "run_input:upstream_resolved_design:/design_profile_id",
        )
        self.assertEqual(
            handoff["event"],
            "run_input:resolved_source_contract:/selector/event",
        )
        self.assertEqual(
            handoff["required_status"],
            "run_input:resolved_source_contract:/selector/status",
        )


if __name__ == "__main__":
    unittest.main()
