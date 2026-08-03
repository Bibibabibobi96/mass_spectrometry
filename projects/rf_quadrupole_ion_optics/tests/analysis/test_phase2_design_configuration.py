from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from common.contracts.file_identity import repository_text_sha256
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
        cls.official_oracle = load(
            PROJECT_ROOT / "config" / "resolved_design_official.json"
        )
        cls.identity = {
            "project_id": "rf_quadrupole_ion_optics",
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
        self.assertEqual(len(compiled["geometry_mm"]["rod_array"]["rods"]), 4)
        self.assertEqual(
            [geometry["inscribed_radius_r0"], geometry["rod_radius_ratio"], geometry["rod_z_min"], geometry["rod_z_max"]],
            [4.0, 0.5, 0.0, 79.6],
        )
        self.assertEqual(compiled["geometry_mm"]["enclosure"], geometry["enclosure"])
        self.assertEqual(
            (
                compiled["interfaces_mm"]["entrance"]["release_plane_z_mm"],
                compiled["interfaces_mm"]["entrance"][
                    "aperture_plate_upstream_face_z_mm"
                ],
                compiled["interfaces_mm"]["entrance"][
                    "aperture_plate_downstream_face_z_mm"
                ],
                compiled["interfaces_mm"]["exit"][
                    "aperture_plate_upstream_face_z_mm"
                ],
                compiled["interfaces_mm"]["exit"][
                    "aperture_plate_downstream_face_z_mm"
                ],
                compiled["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
                compiled["interfaces_mm"]["exit"]["census_plane_z_mm"],
            ),
            (-1.5, -1.0, -0.5, 80.1, 80.6, 80.6, 81.1),
        )
        self.assertEqual(
            self.request["drive"]["waveform"],
            "cosine",
        )
        segments = compiled["segmentation"]["axial_acceleration"]["derived"]["segments"]
        self.assertEqual([item["common_mode_V"] for item in segments], [0.0, -1.0, -2.0, -3.0])
        for item in segments:
            self.assertAlmostEqual(item["z_max_mm"] - item["z_min_mm"], 19.6)

    def test_rectangular_oatof_oracle_is_not_the_family_mechanical_base(self) -> None:
        self.assertEqual(
            self.official_oracle["geometry_mm"]["enclosure"]["model"],
            "rectangular_reference_enclosure_v1",
        )
        self.assertEqual(
            self.request["geometry_mm"]["enclosure"]["model"],
            "cylindrical_grounded_shield_v1",
        )
        self.assertNotEqual(
            self.official_oracle["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
            80.6,
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
            repository_text_sha256(REQUEST_PATH),
        )
        self.assertIn("connector_shape_supported", self.catalog["invariants"])


if __name__ == "__main__":
    unittest.main()
