from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import validate_schema
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.component_port import build_assembly_interface, prepare_exit_observation_inputs


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
)
DESIGN_PROFILE_IDS = tuple(f"octupole_{mode_id}" for mode_id in MODE_IDS)


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


class CurrentDesignConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = load("variants/octupole/config/requests/mechanical_base.json")
        cls.catalog = load("variants/octupole/config/design_variables.json")
        cls.envelope = load("variants/octupole/config/optimization_envelope.json")
        cls.modes = load("config/operating_modes.json")
        cls.profiles = load("config/design_profiles.json")
        cls.resolved = {
            mode_id: resolve_design_profile(
                REPO_ROOT,
                "rf_multipole_ion_optics",
                ('octupole_' + mode_id),
            )["resolved_design"]
            for mode_id in MODE_IDS
        }

    def test_single_governed_base_catalog_envelope_and_mode_registry(self) -> None:
        validate_schema(self.base, "multipole_design_request.schema.json")
        validate_schema(self.catalog, "design_variable_catalog.schema.json")
        validate_schema(self.envelope, "optimization_envelope.schema.json")
        validate_schema(self.modes, "multipole_operating_modes.schema.json")
        validate_schema(self.profiles, "design_profiles.schema.json")
        self.assertEqual(self.modes["terminal_reference_V"], 0.0)
        self.assertEqual(
            [
                (
                    item["rod_entrance_relative_to_terminal_V"],
                    item["rod_exit_relative_to_terminal_V"],
                )
                for item in self.modes["modes"]
            ],
            [(0.0, 0.0), (3.0, 0.0)],
        )
        profile_items = [item for item in self.profiles["profiles"]
                         if item["structural_variant_id"] == "octupole"]
        canonical_profiles = [
            item for item in profile_items if item["design_profile_id"] in DESIGN_PROFILE_IDS
        ]
        self.assertEqual(
            [item["design_profile_id"] for item in canonical_profiles],
            list(DESIGN_PROFILE_IDS),
        )
        mechanical_variants = [item for item in profile_items if item["design_profile_id"] not in DESIGN_PROFILE_IDS]
        self.assertEqual([item["design_profile_id"] for item in mechanical_variants],
                         ["octupole_grounded_shell_no_acceleration"])
        self.assertEqual({item["mode_id"] for item in mechanical_variants}, {MODE_IDS[0]})
        self.assertEqual(
            {item["design_request"] for item in canonical_profiles},
            {"variants/octupole/config/requests/mechanical_base.json"},
        )
        self.assertEqual(
            {item["design_variables"] for item in profile_items},
            {"variants/octupole/config/design_variables.json"},
        )
        self.assertEqual(
            {item["optimization_envelope"] for item in canonical_profiles},
            {"variants/octupole/config/optimization_envelope.json"},
        )
        base_path = PROJECT_ROOT / "variants/octupole/config/requests/mechanical_base.json"
        self.assertEqual(
            self.envelope["reference"]["design_request_sha256"],
            repository_text_sha256(base_path),
        )

    def test_profile_source_hashes_use_canonical_repository_text(self) -> None:
        current = self.profiles["profiles"]
        for field in ("design_request", "design_variables", "optimization_envelope"):
            for item in current:
                path = PROJECT_ROOT / item[field]
                self.assertEqual(
                    repository_text_sha256(path),
                    item["sha256"][field],
                )



    def test_catalog_matches_project_and_execution_capability(self) -> None:
        catalog_ids = {
            item["variable_id"] for item in self.catalog["variables"]
        }
        project = load("config/project.json")
        capability = next(
            item
            for item in project["capabilities"]
            if item["capability_id"] == "octupole_finite_3d_transport"
        )
        execution = load("config/execution_profiles.json")
        execution_profile = next(
            item
            for item in execution["profiles"]
            if item["capability_id"] == "octupole_finite_3d_transport"
        )
        self.assertEqual(set(capability["design_variables"]), catalog_ids)
        self.assertEqual(
            set(execution_profile["supported_design_variables"]),
            catalog_ids,
        )



    def test_current_shell_candidate_has_explicit_space_for_exit_observation(self):
        selected = resolve_design_profile(REPO_ROOT, "rf_multipole_ion_optics", "octupole_grounded_shell_no_acceleration")
        resolved = selected["resolved_design"]
        geometry = resolved["geometry_mm"]
        self.assertEqual(geometry["enclosure"]["z_max_mm"], 82.1)
        self.assertEqual(geometry["observations"]["handoff_plane_z_mm"], 80.6)
        self.assertEqual(geometry["observations"]["census_plane_z_mm"], 81.1)
        self.assertEqual(geometry["numerical_domain"]["z_max_mm"], 82.9)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "inputs").mkdir()
            plan = prepare_exit_observation_inputs(run, resolved, design_profile_id=selected["profile"]["design_profile_id"], cell_z_mm=.4)
        self.assertEqual(plan["mechanical_exit_z_mm"], 82.1)
        self.assertEqual(plan["numerical_guard_z_mm"], 82.5)
        self.assertEqual(plan["numerical_domain_end_z_mm"], 82.9)

    def test_bare_default_and_shell_candidate_have_explicit_frozen_mechanics(self):
        for mode in MODE_IDS:
            resolved = self.resolved[mode]
            self.assertEqual(resolved["geometry_mm"]["enclosure"], {"model":"bare"})
            self.assertEqual(resolved["geometry_mm"]["enclosure_layout"]["bodies"], [])
            self.assertNotIn("interfaces_mm",resolved)
            interface = build_assembly_interface(resolved,geometry_profile_id="octupole_"+mode)
            self.assertEqual(interface["ports"]["mechanical_exit"]["center_mm"][2],resolved["geometry_mm"]["rod_z_max"])
        selected = resolve_design_profile(REPO_ROOT,"rf_multipole_ion_optics","octupole_grounded_shell_no_acceleration")
        self.assertEqual(selected["resolved_design"]["geometry_mm"]["enclosure"]["model"],"cylindrical_grounded_shell")
        self.assertEqual(selected["resolved_design"]["geometry_mm"]["observations"],self.resolved[MODE_IDS[0]]["geometry_mm"]["observations"])


if __name__ == "__main__":
    unittest.main()
