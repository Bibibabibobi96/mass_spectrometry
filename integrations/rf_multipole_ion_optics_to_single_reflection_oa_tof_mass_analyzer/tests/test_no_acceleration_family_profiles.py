"""Current family profiles use run-local source and design authorities."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.refresh_family_repository_bindings import (
    compile_publications,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = INTEGRATION_ROOT / "config"
PROFILE_REGISTRY_PATH = CONFIG_ROOT / "connection_profiles.json"
FAMILIES = ("quadrupole", "hexapole", "octupole")
PROFILE_IDS = {
    f"rf_{family}_oatof_shield_terminal_direct_mating_gap_0mm"
    for family in FAMILIES
}
PROFILE_IDS.add(
    "rf_octupole_oatof_shield_terminal_aperture_050x050_direct_mating_gap_0mm"
)
PROFILE_IDS.add(
    "rf_octupole_oatof_shield_terminal_aperture_050x020_direct_mating_gap_0mm"
)


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class NoAccelerationFamilyProfileTests(unittest.TestCase):
    def test_static_profiles_are_mode_neutral_run_local_templates(self) -> None:
        registry = load_connection_profile_registry(PROFILE_REGISTRY_PATH)
        profiles = {
            profile["connection_profile_id"]: profile
            for profile in registry["profiles"]
        }
        self.assertEqual(set(profiles), PROFILE_IDS)
        for profile_id, profile in profiles.items():
            with self.subTest(profile_id=profile_id):
                self.assertEqual(
                    profile["upstream"].get("port_binding"),
                    "source_run_resolved_design",
                )
                self.assertNotIn("port_contract", profile["upstream"])
                self.assertIn("port_contract", profile["downstream"])
                with self.assertRaisesRegex(ContractError, "binding is unresolved"):
                    resolve_connection_profile(
                        registry,
                        profile_id,
                        repo_root=REPO_ROOT,
                    )

    def test_run_local_design_and_port_materialize_one_profile(self) -> None:
        artifacts_projects = WORKSPACE_ROOT / "artifacts" / "projects"
        artifacts_projects.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts_projects) as directory:
            run_inputs = Path(directory) / "runs" / "fixture" / "inputs"
            design_source = (
                REPO_ROOT
                / "projects"
                / "rf_quadrupole_ion_optics"
                / "config"
                / "resolved_design_no_acceleration_full_length.json"
            )
            port_source = (
                REPO_ROOT
                / "projects"
                / "rf_quadrupole_ion_optics"
                / "config"
                / "interfaces"
                / "provided"
                / "rf_multipole_exit_no_acceleration_full_length.json"
            )
            design_path = run_inputs / "upstream_resolved_design.json"
            port_path = run_inputs / "resolved_upstream_port.json"
            design_path.parent.mkdir(parents=True, exist_ok=True)
            design_path.write_bytes(design_source.read_bytes())
            port = load(port_source)
            port["authority"]["source_contract"] = design_path.relative_to(
                WORKSPACE_ROOT
            ).as_posix()
            port["authority"]["source_sha256"] = file_sha256(design_path)
            write(port_path, port)

            registry = load(PROFILE_REGISTRY_PATH)
            profile_id = (
                "rf_quadrupole_oatof_shield_terminal_direct_mating_gap_0mm"
            )
            profile = next(
                item
                for item in registry["profiles"]
                if item["connection_profile_id"] == profile_id
            )
            registry["profiles"] = [profile]
            upstream = profile["upstream"]
            self.assertEqual(
                upstream.pop("port_binding"),
                "source_run_resolved_design",
            )
            upstream["port_contract"] = port_path.relative_to(
                WORKSPACE_ROOT
            ).as_posix()
            resolved = resolve_connection_profile(
                registry,
                profile_id,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(resolved["compatibility"]["status"], "pass")
            self.assertEqual(
                resolved["sources"]["upstream_authority"]["path"],
                design_path.relative_to(WORKSPACE_ROOT).as_posix(),
            )

    def test_retired_static_source_and_revision_publications_are_absent(self) -> None:
        retired = [
            "family_source_closure_budget.json",
            "family_source_closure_preregistration.json",
            "family_source_revision_registry.json",
        ]
        retired.extend(
            f"family_{family}_n100_source_contract.json" for family in FAMILIES
        )
        retired.extend(
            f"family_{family}_hybrid_reference_n100_source_contract.json"
            for family in FAMILIES
        )
        retired.extend(
            f"family_{family}_hybrid_reference_direct_mating_gap_0mm_"
            "runtime_binding.json"
            for family in FAMILIES
        )
        for name in retired:
            with self.subTest(name=name):
                self.assertFalse((CONFIG_ROOT / name).exists())

    def test_active_publication_closure_has_no_retired_names(self) -> None:
        paths = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in compile_publications(REPO_ROOT)
        }
        for forbidden in (
            "_n100_source_contract.json",
            "hybrid_reference",
            "source_revision",
            "family_dependencies_base.json",
            "dependencies_overlay.json",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(any(forbidden in path for path in paths))


if __name__ == "__main__":
    unittest.main()
