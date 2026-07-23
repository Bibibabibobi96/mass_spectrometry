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
REQUEST_PATH = PROJECT_ROOT / "config" / "requests" / "baseline.json"


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
        cls.baseline = load(PROJECT_ROOT / "config" / "baseline.json")
        cls.finite = load(PROJECT_ROOT / "config" / "finite_3d_transport.json")
        cls.screen = load(PROJECT_ROOT / "config" / "round_rod_field_screen.json")
        cls.axial = load(PROJECT_ROOT / "config" / "modes" / "axial_acceleration_reference.json")
        cls.identity = {
            "project_id": "rf_octupole_ion_guide",
            "family_id": "rf_multipole_ion_optics",
            "radial_order_n": 4,
            "electrode_count": 8,
        }

    def test_contracts_are_schema_valid_and_identity_is_locked(self) -> None:
        validate_schema(self.request, "multipole_design_request.schema.json")
        validate_schema(self.catalog, "design_variable_catalog.schema.json")
        validate_schema(self.envelope, "optimization_envelope.schema.json")
        self.assertEqual(self.request["identity"], self.identity)
        changed = copy.deepcopy(self.request)
        changed["identity"]["electrode_count"] = 6
        with self.assertRaisesRegex(MultipoleDesignCompileError, "identity"):
            compile_design_request(changed, expected_identity=self.identity)

    def test_request_compiles_to_current_rods_interfaces_drive_and_segmentation(self) -> None:
        compiled = compile_design_request(self.request, expected_identity=self.identity)
        geometry = self.request["geometry_mm"]
        self.assertEqual(len(compiled["geometry_mm"]["rod_array"]["rods"]), 8)
        self.assertEqual(geometry["inscribed_radius_r0"], self.baseline["geometry_mm"]["inscribed_radius_r0"])
        self.assertEqual(geometry["rod_radius_ratio"], 1 / 3)
        self.assertIn(geometry["rod_radius_ratio"], self.screen["geometry_mm"]["rod_radius_ratio_sweep"])
        self.assertEqual(geometry["rod_z_min"], self.finite["geometry_mm"]["rod_z_min"])
        self.assertEqual(geometry["rod_z_max"], self.baseline["geometry_mm"]["effective_length"])
        self.assertEqual(compiled["geometry_mm"]["enclosure"], geometry["enclosure"])
        self.assertEqual(
            geometry["enclosure"],
            {
                "model": "cylindrical_grounded_shield_v1",
                "role": "full_length_grounded_shield",
                "working_region_radius_mm": self.finite["geometry_mm"]["working_region_radius"],
                "vacuum_z_min_mm": -2.5,
                "vacuum_z_max_mm": 82.1,
                "shield_inner_radius_mm": self.finite["geometry_mm"]["grounded_shield_inner_radius"],
                "shield_outer_radius_mm": 21.0,
                "entrance_endcap_z_min_mm": -2.5,
                "entrance_endcap_z_max_mm": -2.0,
                "exit_endcap_z_min_mm": 81.6,
                "exit_endcap_z_max_mm": 82.1,
            },
        )
        for side in ("entrance_interface", "exit_interface"):
            self.assertEqual(
                geometry[side],
                {
                    key: value
                    for key, value in self.finite["geometry_mm"][side].items()
                    if key != "outer_ground_clearance_mm"
                },
            )
        rf = self.baseline["rf"]
        self.assertEqual(
            self.request["drive"],
            {
                "waveform": rf["waveform"],
                "rf_amplitude_V_zero_to_peak_per_group": rf["amplitude_V_peak"],
                "dc_amplitude_V_per_group": 0.0,
                "common_mode_offset_V": rf["common_mode_offset_V"],
                "frequency_Hz": rf["frequency_Hz"],
                "phase_rad": rf["phase_rad"],
            },
        )
        expected_segmentation = dict(self.axial["segmentation"])
        expected_segmentation["output_reference_V"] = self.axial["output_reference_V"]
        self.assertEqual(self.request["segmentation"], expected_segmentation)
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


if __name__ == "__main__":
    unittest.main()
