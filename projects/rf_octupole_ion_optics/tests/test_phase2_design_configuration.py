from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


class ThreeModeDesignConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = load("config/requests/mechanical_base.json")
        cls.catalog = load("config/design_variables.json")
        cls.envelope = load("config/optimization_envelope.json")
        cls.modes = load("config/operating_modes.json")
        cls.profiles = load("config/design_profiles.json")
        cls.resolved = {
            mode_id: resolve_design_profile(
                REPO_ROOT,
                "rf_octupole_ion_optics",
                mode_id,
            )["resolved_design"]
            for mode_id in MODE_IDS
        }

    def test_single_governed_base_catalog_envelope_and_mode_registry(self) -> None:
        validate_schema(self.base, "multipole_design_request.schema.json")
        validate_schema(self.catalog, "design_variable_catalog.schema.json")
        validate_schema(self.envelope, "optimization_envelope.schema.json")
        validate_schema(self.modes, "multipole_operating_modes.schema.json")
        validate_schema(self.profiles, "design_profiles.schema.json")
        profile_items = self.profiles["profiles"]
        canonical_profiles = [
            item for item in profile_items if item["design_profile_id"] in MODE_IDS
        ]
        self.assertEqual(
            [item["design_profile_id"] for item in canonical_profiles],
            list(MODE_IDS),
        )
        aliases = {
            item["design_profile_id"]: item["mode_id"]
            for item in profile_items
            if item["design_profile_id"] not in MODE_IDS
        }
        self.assertEqual(
            aliases,
            {
                "baseline_finite_3d": "segmented_rod_axial_acceleration",
                "exit_aperture_plate_acceleration_reference":
                    "exit_aperture_plate_acceleration",
            },
        )
        self.assertEqual(
            {item["design_request"] for item in profile_items},
            {"config/requests/mechanical_base.json"},
        )
        self.assertEqual(
            {item["design_variables"] for item in profile_items},
            {"config/design_variables.json"},
        )
        self.assertEqual(
            {item["optimization_envelope"] for item in profile_items},
            {"config/optimization_envelope.json"},
        )
        base_path = PROJECT_ROOT / "config/requests/mechanical_base.json"
        self.assertEqual(
            self.envelope["reference"]["design_request_sha256"],
            hashlib.sha256(base_path.read_bytes()).hexdigest().upper(),
        )

    def test_profile_source_hashes_use_repository_lf_bytes(self) -> None:
        current = [
            item
            for item in self.profiles["profiles"]
            if item["design_profile_id"] in MODE_IDS
        ]
        for field in ("design_request", "design_variables", "optimization_envelope"):
            for item in current:
                path = PROJECT_ROOT / item[field]
                content = path.read_bytes()
                self.assertNotIn(b"\r", content, item[field])
                self.assertEqual(
                    hashlib.sha256(content).hexdigest().upper(),
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

    def test_strict_mechanical_baseline_and_interfaces(self) -> None:
        geometry = self.base["geometry_mm"]
        self.assertEqual(
            (
                geometry["rod_z_min"],
                geometry["rod_z_max"],
                geometry["inscribed_radius_r0"],
                geometry["rod_radius_ratio"],
            ),
            (0.0, 79.6, 4.0, 0.5),
        )
        reference = self.resolved[MODE_IDS[0]]
        self.assertEqual(
            reference["interfaces_mm"]["entrance"],
            {
                "aperture_radius_mm": 3.6,
                "aperture_plate_upstream_face_z_mm": -1.0,
                "aperture_plate_downstream_face_z_mm": -0.5,
                "connector_length_mm": 0.0,
                "connector_upstream_face_z_mm": -1.0,
                "connector_downstream_face_z_mm": -1.0,
                "release_plane_z_mm": -1.5,
                "connector_shape": "cylindrical_bore",
            },
        )
        self.assertEqual(
            reference["interfaces_mm"]["exit"],
            {
                "aperture_radius_mm": 3.6,
                "aperture_plate_upstream_face_z_mm": 80.1,
                "aperture_plate_downstream_face_z_mm": 80.6,
                "aperture_crossing_plane_z_mm": 80.6,
                "connector_length_mm": 0.0,
                "connector_upstream_face_z_mm": 80.6,
                "connector_downstream_face_z_mm": 80.6,
                "handoff_plane_z_mm": 80.6,
                "census_plane_z_mm": 81.1,
                "connector_shape": "cylindrical_bore",
            },
        )
        segments = reference["segmentation"]["axial_acceleration"]["derived"][
            "segments"
        ]
        for item, expected in zip(
            segments,
            [(0.0, 19.6), (20.0, 39.6), (40.0, 59.6), (60.0, 79.6)],
            strict=True,
        ):
            self.assertAlmostEqual(item["z_min_mm"], expected[0])
            self.assertAlmostEqual(item["z_max_mm"], expected[1])
            self.assertAlmostEqual(item["z_max_mm"] - item["z_min_mm"], 19.6)
        self.assertEqual(reference["geometry_mm"]["rod_array"]["rod_radius"], 2.0)

    def test_modes_preserve_geometry_and_differ_only_electrically(self) -> None:
        reference = self.resolved[MODE_IDS[0]]
        for resolved in self.resolved.values():
            self.assertEqual(resolved["geometry_mm"], reference["geometry_mm"])
            self.assertEqual(resolved["interfaces_mm"], reference["interfaces_mm"])
            self.assertEqual(resolved["drive"], reference["drive"])
            self.assertEqual(resolved["particle_source"], reference["particle_source"])
            physical_electrodes = [
                {key: value for key, value in item.items() if key != "common_mode_V"}
                for item in resolved["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            reference_electrodes = [
                {key: value for key, value in item.items() if key != "common_mode_V"}
                for item in reference["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            self.assertEqual(physical_electrodes, reference_electrodes)
        expected = {
            "no_acceleration_full_length": ([0.0, 0.0, 0.0, 0.0], 0.0),
            "segmented_rod_axial_acceleration": ([0.0, -1.0, -2.0, -3.0], -3.0),
            "exit_aperture_plate_acceleration": ([0.0, 0.0, 0.0, 0.0], -3.0),
        }
        for mode_id, (rod_voltages, plate_voltage) in expected.items():
            resolved = self.resolved[mode_id]
            segments = resolved["segmentation"]["axial_acceleration"]["derived"][
                "segments"
            ]
            self.assertEqual(
                [item["common_mode_V"] for item in segments],
                rod_voltages,
            )
            self.assertEqual(
                resolved["static_electrodes_V"][
                    "exit_outer_endcap_aperture_plate_connector_V"
                ],
                plate_voltage,
            )


if __name__ == "__main__":
    unittest.main()
