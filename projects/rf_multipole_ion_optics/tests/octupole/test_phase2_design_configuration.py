from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import validate_schema
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.component_port import build_assembly_interface


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)
DESIGN_PROFILE_IDS = tuple(f"octupole_{mode_id}" for mode_id in MODE_IDS)


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


class ThreeModeDesignConfigurationTests(unittest.TestCase):
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
            [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0)],
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
                         ["octupole_through_exit_no_acceleration", "octupole_through_entrance_exit_no_acceleration"])
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

    def test_through_exit_is_a_separate_mechanical_authority_with_the_same_typed_no_acceleration(self) -> None:
        selected = resolve_design_profile(REPO_ROOT, "rf_multipole_ion_optics", 'octupole_through_exit_no_acceleration')
        profile, resolved = selected["profile"], selected["resolved_design"]
        self.assertEqual(profile["mode_id"], MODE_IDS[0])
        self.assertEqual(profile["design_request"], "variants/octupole/config/requests/through_exit.json")
        self.assertEqual(profile["optimization_envelope"], "variants/octupole/config/through_exit_optimization_envelope.json")
        request = load(profile["design_request"])
        envelope = load(profile["optimization_envelope"])
        validate_schema(request, "multipole_design_request.schema.json")
        validate_schema(envelope, "optimization_envelope.schema.json")
        self.assertEqual(envelope["reference"], dict(design_request=profile["design_request"],
            design_request_sha256=repository_text_sha256(selected["paths"]["design_request"])))
        self.assertNotEqual(request["request_id"], self.base["request_id"])
        enclosure = request["geometry_mm"]["enclosure"]
        self.assertEqual(enclosure["model"], "cylindrical_grounded_shield_through_exit_v1")
        self.assertEqual(enclosure["vacuum_z_max_mm"], 82.7)
        self.assertEqual(enclosure["exit_outer_endcap_downstream_face_z_mm"], 82.1)
        # The new topology/domain are explicit author changes; source and
        # every other physical input remain the original no-acceleration case.
        baseline_shape = json.loads(json.dumps(request))
        baseline_shape["request_id"] = self.base["request_id"]
        for key in ("model", "vacuum_z_max_mm"):
            baseline_shape["geometry_mm"]["enclosure"][key] = self.base["geometry_mm"]["enclosure"][key]
        self.assertEqual(baseline_shape, self.base)
        original = self.resolved[MODE_IDS[0]]
        for key in ("drive", "particle_source", "static_electrodes_V", "segmentation"):
            self.assertEqual(resolved[key], original[key])
        self.assertNotEqual(resolved["geometry_mm"], original["geometry_mm"])

    def test_dual_through_profile_changes_only_enclosure_and_exposes_both_real_faces(self) -> None:
        single = resolve_design_profile(REPO_ROOT, "rf_multipole_ion_optics", 'octupole_through_exit_no_acceleration')
        dual = resolve_design_profile(REPO_ROOT, "rf_multipole_ion_optics", 'octupole_through_entrance_exit_no_acceleration')
        model = "cylindrical_grounded_shield_through_entrance_exit_v1"
        self.assertEqual(dual["paths"], single["paths"])
        self.assertEqual(dual["profile"]["mode_id"], MODE_IDS[0])
        self.assertEqual(dual["profile"]["enclosure_model"], model)
        resolved = dual["resolved_design"]
        self.assertEqual(resolved["governance"]["enclosure_model"], model)
        expected_geometry = json.loads(json.dumps(single["resolved_design"]["geometry_mm"]))
        expected_geometry["enclosure"]["model"] = model
        self.assertEqual(resolved["geometry_mm"], expected_geometry)
        for key in ("interfaces_mm", "drive", "axial_drive", "particle_source", "static_electrodes_V", "segmentation"):
            self.assertEqual(resolved[key], single["resolved_design"][key], key)
        interface = build_assembly_interface(resolved, geometry_profile_id=dual["profile"]["design_profile_id"])
        self.assertEqual(set(interface["ports"]), {"mechanical_entrance", "mechanical_exit"})
        for name, z_mm, normal, source in (
                ("mechanical_entrance", -2.5, [0, 0, -1], "entrance"),
                ("mechanical_exit", 82.1, [0, 0, 1], "exit")):
            with self.subTest(port=name):
                port = interface["ports"][name]
                self.assertEqual(port["center_mm"], [0., 0., z_mm])
                self.assertEqual(port["outward_normal"], normal)
                self.assertEqual(port["wall_thickness_mm"], .5)
                self.assertEqual(port["cross_section"], dict(shape="circle",
                    radius_mm=resolved["interfaces_mm"][source]["aperture_radius_mm"]))

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
            self.assertEqual(
                {
                    key: value
                    for key, value in resolved["drive"].items()
                    if key != "common_mode_offset_V"
                },
                {
                    key: value
                    for key, value in reference["drive"].items()
                    if key != "common_mode_offset_V"
                },
            )
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
            "segmented_rod_axial_acceleration": ([3.0, 2.0, 1.0, 0.0], 0.0),
            "exit_aperture_plate_acceleration": ([3.0, 3.0, 3.0, 3.0], 0.0),
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
