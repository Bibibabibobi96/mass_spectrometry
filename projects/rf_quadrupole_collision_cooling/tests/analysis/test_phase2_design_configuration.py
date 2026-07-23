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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
        cls.resolved = load(
            PROJECT_ROOT / "config" / "resolved_design_official.json"
        )
        cls.mode = load(PROJECT_ROOT / "config" / "modes" / "transport_no_collision.json")
        cls.axial = load(PROJECT_ROOT / "config" / "modes" / "axial_acceleration_reference.json")
        cls.identity = {
            "project_id": "rf_quadrupole_collision_cooling",
            "family_id": "rf_multipole_ion_optics",
            "radial_order_n": 2,
            "electrode_count": 4,
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
        current = self.resolved["geometry_mm"]
        self.assertEqual(len(compiled["geometry_mm"]["rod_array"]["rods"]), 4)
        self.assertEqual(
            [geometry["inscribed_radius_r0"], geometry["rod_radius_ratio"], geometry["rod_z_min"], geometry["rod_z_max"]],
            [current["inscribed_radius_r0"], current["rod_radius_ratio"], current["rod_z_min"], current["rod_z_max"]],
        )
        self.assertEqual(compiled["geometry_mm"]["enclosure"], geometry["enclosure"])
        self.assertEqual(geometry["enclosure"], current["enclosure"])
        for side in ("entrance", "exit"):
            for key, value in self.resolved["interfaces_mm"][side].items():
                if key != "connector_shape":
                    self.assertAlmostEqual(compiled["interfaces_mm"][side][key], value)
        self.assertEqual(
            self.request["drive"],
            {
                "waveform": "sine",
                "rf_amplitude_V_zero_to_peak_per_group": self.mode["rf"]["amplitude_V_peak"],
                "dc_amplitude_V_per_group": 0.0,
                "common_mode_offset_V": self.mode["rf"]["axis_offset_V"],
                "frequency_Hz": self.mode["rf"]["frequency_Hz"],
                "phase_rad": self.mode["rf"]["phase_rad"],
            },
        )
        expected_segmentation = dict(self.axial["segmentation"])
        expected_segmentation["output_reference_V"] = self.axial["output_reference_V"]
        self.assertEqual(self.request["segmentation"], expected_segmentation)
        self.assertEqual(
            compiled["segmentation"]["axial_acceleration"]["segmentation"]["segment_count"],
            expected_segmentation["segment_count"],
        )

    def test_envelope_covers_every_numeric_pointer_with_units_and_bounds(self) -> None:
        variables = self.catalog["variables"]
        pointers = {item["json_pointer"] for item in variables}
        self.assertEqual(len(pointers), len(variables))
        for variable in variables:
            current = pointer_value(self.request, variable["json_pointer"])
            self.assertIsInstance(current, (int, float))
            self.assertLess(variable["minimum"], variable["maximum"])
            self.assertLessEqual(variable["minimum"], current)
            self.assertLessEqual(current, variable["maximum"])
            self.assertIn(variable["unit"], {"mm", "ratio", "V", "Hz", "rad", "count"})
        bounded = next(
            item for item in self.envelope["constraints"]
            if item["kind"] == "bounded_variable"
        )
        self.assertEqual(set(bounded["request_json_pointers"]), pointers)
        self.assertEqual(
            self.envelope["reference"]["design_request_sha256"],
            hashlib.sha256(REQUEST_PATH.read_bytes()).hexdigest().upper(),
        )
        self.assertIn("connector_shape_supported", self.catalog["invariants"])


if __name__ == "__main__":
    unittest.main()
