from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    compile_design_request,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
REQUEST_PATH = PROJECT_ROOT / "config" / "requests" / "mechanical_base.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pointer_value(document: dict, pointer: str):
    value = document
    for token in pointer.lstrip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


class Phase2DesignConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.request = load(REQUEST_PATH)
        cls.catalog = load(PROJECT_ROOT / "config" / "design_variables.json")
        cls.envelope = load(PROJECT_ROOT / "config" / "optimization_envelope.json")
        cls.published = load(
            PROJECT_ROOT / "config" / "resolved_design_no_acceleration_full_length.json"
        )
        cls.screen = load(PROJECT_ROOT / "config" / "round_rod_field_screen.json")
        cls.comsol_numerics = load(
            PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
        )
        cls.runtime_profiles = load(
            PROJECT_ROOT / "config" / "runtime_profiles.json"
        )
        cls.identity = {
            "project_id": "rf_hexapole_ion_optics",
            "family_id": "rf_multipole_ion_optics",
            "radial_order_n": 3,
            "electrode_count": 6,
        }

    def test_contracts_are_schema_valid_and_identity_is_locked(self) -> None:
        validate_schema(self.request, "multipole_design_request.schema.json")
        validate_schema(self.catalog, "design_variable_catalog.schema.json")
        validate_schema(self.envelope, "optimization_envelope.schema.json")
        self.assertEqual(self.request["identity"], self.identity)
        changed = copy.deepcopy(self.request)
        changed["identity"]["electrode_count"] = 8
        with self.assertRaisesRegex(MultipoleDesignCompileError, "identity"):
            compile_design_request(changed, expected_identity=self.identity)

    def test_request_compiles_to_current_rods_interfaces_drive_and_segmentation(self) -> None:
        compiled = compile_design_request(self.request, expected_identity=self.identity)
        geometry = self.request["geometry_mm"]
        self.assertEqual(len(compiled["geometry_mm"]["rod_array"]["rods"]), 6)
        self.assertEqual(geometry["inscribed_radius_r0"], self.published["geometry_mm"]["inscribed_radius_r0"])
        self.assertEqual(geometry["rod_radius_ratio"], 0.5)
        self.assertIn(geometry["rod_radius_ratio"], self.screen["geometry_mm"]["rod_radius_ratio_sweep"])
        self.assertEqual(geometry["rod_z_min"], 0.0)
        self.assertEqual(geometry["rod_z_max"], self.published["geometry_mm"]["rod_length"])
        self.assertEqual(compiled["geometry_mm"]["enclosure"], geometry["enclosure"])
        self.assertEqual(
            geometry["enclosure"],
            {
                "model": "cylindrical_grounded_shield_v1",
                "role": "full_length_grounded_shield",
                "working_region_radius_mm": 3.6,
                "vacuum_z_min_mm": -2.5,
                "vacuum_z_max_mm": 82.1,
                "shield_inner_radius_mm": 20.0,
                "shield_outer_radius_mm": 21.0,
                "entrance_outer_endcap_upstream_face_z_mm": -2.5,
                "entrance_outer_endcap_downstream_face_z_mm": -2.0,
                "exit_outer_endcap_upstream_face_z_mm": 81.6,
                "exit_outer_endcap_downstream_face_z_mm": 82.1,
            },
        )
        for side in ("entrance_interface", "exit_interface"):
            self.assertEqual(geometry[side]["aperture_radius_mm"], 3.6)
            self.assertEqual(geometry[side]["plate_thickness_mm"], 0.5)
            self.assertEqual(geometry[side]["rod_clearance_mm"], 0.5)
            self.assertEqual(geometry[side]["connector_length_mm"], 0.0)
            self.assertEqual(geometry[side]["connector_shape"], "cylindrical_bore")
        self.assertEqual(self.request["drive"], self.published["drive"])
        self.assertEqual(
            self.request["segmentation"],
            {
                "strategy": "uniform",
                "segment_count": 4,
                "intersegment_gap_mm": 0.4,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": 0.0,
                "output_reference_V": 0.0,
            },
        )
        self.assertEqual(
            compiled["segmentation"]["axial_acceleration"]["segmentation"]["segment_count"],
            4,
        )

    def test_envelope_has_complete_bounded_unit_coverage(self) -> None:
        variables = self.catalog["variables"]
        pointers = {item["json_pointer"] for item in variables}
        self.assertEqual(len(pointers), len(variables))
        for variable in variables:
            current = pointer_value(self.request, variable["json_pointer"])
            self.assertLess(variable["minimum"], variable["maximum"])
            self.assertLessEqual(variable["minimum"], current)
            self.assertLessEqual(current, variable["maximum"])
            self.assertIn(variable["unit"], {"mm", "ratio", "V", "Hz", "rad", "count"})
        bounded = next(item for item in self.envelope["constraints"] if item["kind"] == "bounded_variable")
        self.assertEqual(set(bounded["request_json_pointers"]), pointers)
        self.assertEqual(
            self.envelope["reference"]["design_request_sha256"],
            hashlib.sha256(REQUEST_PATH.read_bytes()).hexdigest().upper(),
        )
        self.assertIn("connector_shape_supported", self.catalog["invariants"])

    def test_comsol_baseline_freezes_verified_working_region_mesh_limit(self) -> None:
        profiles = self.comsol_numerics["profiles"]
        self.assertEqual(
            profiles["baseline_finite_3d"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.5,
        )
        self.assertEqual(
            profiles["n100_spatial_refined"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.35,
        )
        self.assertEqual(
            profiles["n100_temporal_refined"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.35,
        )
        self.assertEqual(
            profiles["n100_temporal_refined"]["trajectory"]["rf_steps_per_period"],
            160,
        )


if __name__ == "__main__":
    unittest.main()
