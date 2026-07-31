from __future__ import annotations

import copy
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    apply_typed_operating_mode,
    compile_design_request,
    resolved_design_sha256,
)
from common.multipole.downstream_terminal import (
    DownstreamTerminalError,
    compose_downstream_terminal,
    select_downstream_terminal_profile,
)
from common.multipole.test_compile_design_request import design_request


PROJECT_ID = "rf_hexapole_ion_optics"


def relative_modes() -> dict:
    return {
        "schema_version": 2,
        "role": "multipole_typed_operating_mode_registry",
        "project_id": PROJECT_ID,
        "family_id": "rf_multipole_ion_optics",
        "terminal_reference_V": 0.0,
        "modes": [
            {
                "mode_id": "no_acceleration_full_length",
                "axial_drive_topology": "none",
                "rod_entrance_relative_to_terminal_V": 0.0,
                "rod_exit_relative_to_terminal_V": 0.0,
            },
            {
                "mode_id": "segmented_rod_axial_acceleration",
                "axial_drive_topology": "segmented_rod_axial_acceleration",
                "rod_entrance_relative_to_terminal_V": 3.0,
                "rod_exit_relative_to_terminal_V": 0.0,
            },
            {
                "mode_id": "exit_aperture_plate_acceleration",
                "axial_drive_topology": "exit_aperture_plate_potential_step",
                "rod_entrance_relative_to_terminal_V": 3.0,
                "rod_exit_relative_to_terminal_V": 3.0,
            },
        ],
    }


def terminal_registry() -> dict:
    return {
        "schema_version": 1,
        "role": "multipole_downstream_terminal_profile_registry",
        "integration_id": "rf_multipole_to_single_reflection_oatof",
        "compatible_upstream_family_id": "rf_multipole_ion_optics",
        "allowed_upstream_project_ids": [PROJECT_ID],
        "profiles": [
            {
                "terminal_profile_id": "oatof_shield_entry_gap1mm",
                "owner": "downstream",
                "surface_role": "aperture_outer_tangent_plane",
                "rod_end_clearance_mm": 1.0,
                "upstream_enclosure_end_plane_binding": (
                    "interfaces_mm.exit.aperture_plate_upstream_face_z_mm"
                ),
                "electrode_thickness_mm": 4.0,
                "outer_envelope": {
                    "shape": "rectangular",
                    "width_mm": 38.0,
                    "height_mm": 38.0,
                },
                "aperture": {
                    "shape": "rectangular",
                    "width_mm": 1.0,
                    "height_mm": 0.9,
                    "width_axis": "multipole_x",
                    "height_axis": "multipole_y",
                },
                "terminal_potential_V": 0.0,
            }
        ],
    }


def compile_mode(mode_id: str) -> dict:
    base = design_request(
        PROJECT_ID,
        segmentation={
            "strategy": "uniform",
            "segment_count": 4,
            "intersegment_gap_mm": 0.4,
            "entrance_common_mode_V": 0.0,
            "exit_common_mode_V": 0.0,
            "output_reference_V": 0.0,
        },
    )
    request = apply_typed_operating_mode(base, relative_modes(), mode_id)
    return compile_design_request(request, expected_identity=request["identity"])


class RelativeOperatingModeTest(unittest.TestCase):
    def test_three_modes_derive_absolute_entity_potentials_from_terminal(self) -> None:
        expected = {
            "no_acceleration_full_length": [0.0, 0.0, 0.0, 0.0],
            "segmented_rod_axial_acceleration": [3.0, 2.0, 1.0, 0.0],
            "exit_aperture_plate_acceleration": [3.0, 3.0, 3.0, 3.0],
        }
        profile = terminal_registry()["profiles"][0]
        for mode_id, voltages in expected.items():
            with self.subTest(mode_id=mode_id):
                resolved = compile_mode(mode_id)
                segments = resolved["segmentation"]["axial_acceleration"]["derived"]["segments"]
                self.assertEqual(
                    [round(segment["common_mode_V"], 12) for segment in segments],
                    voltages,
                )
                self.assertEqual(resolved["segmentation"]["axial_acceleration"]["output_reference_V"], voltages[-1])
                self.assertEqual(resolved["axial_drive"]["output_reference_V"], 0.0)
                composed = compose_downstream_terminal(resolved, profile)
                self.assertEqual(
                    composed["downstream_terminal"]["surface_plane_z_mm"],
                    resolved["geometry_mm"]["rod_z_max"] + 1.0,
                )
                self.assertEqual(
                    composed["downstream_terminal"]["upstream_enclosure_end_plane_z_mm"],
                    resolved["interfaces_mm"]["exit"]["aperture_plate_upstream_face_z_mm"],
                )
                self.assertAlmostEqual(composed["downstream_terminal"]["upstream_enclosure_to_terminal_clearance_mm"], 0.5)
                self.assertFalse(composed["downstream_terminal"]["upstream_terminal_electrode_present"])
                self.assertEqual(
                    [item["potential_V"] for item in composed["axial_dc"]["rod_electrodes"]][::2],
                    voltages,
                )
                self.assertEqual(composed["axial_dc"]["terminal_electrode_potential_V"], 0.0)
                self.assertEqual(composed["resolved_sha256"], resolved_design_sha256(composed))

    def test_relative_mode_topology_mismatches_fail_closed(self) -> None:
        base = design_request(
            PROJECT_ID,
            segmentation={
                "strategy": "uniform", "segment_count": 4,
                "intersegment_gap_mm": 0.4, "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": 0.0, "output_reference_V": 0.0,
            },
        )
        invalid = relative_modes()
        invalid["modes"][0]["rod_exit_relative_to_terminal_V"] = 1.0
        with self.assertRaisesRegex(MultipoleDesignCompileError, "zero rod potentials"):
            apply_typed_operating_mode(base, invalid, "no_acceleration_full_length")
        invalid = relative_modes()
        invalid["modes"][1]["rod_exit_relative_to_terminal_V"] = 1.0
        with self.assertRaisesRegex(MultipoleDesignCompileError, "must end"):
            apply_typed_operating_mode(base, invalid, "segmented_rod_axial_acceleration")
        invalid = relative_modes()
        del invalid["terminal_reference_V"]
        with self.assertRaises(MultipoleDesignCompileError):
            apply_typed_operating_mode(base, invalid, "no_acceleration_full_length")


class DownstreamTerminalCompositionTest(unittest.TestCase):
    def test_registry_is_integration_owned_and_project_scoped(self) -> None:
        registry = terminal_registry()
        validate_schema(registry, "multipole_downstream_terminal_profiles.schema.json")
        selected = select_downstream_terminal_profile(
            registry,
            "oatof_shield_entry_gap1mm",
            upstream_project_id=PROJECT_ID,
        )
        self.assertEqual(selected["owner"], "downstream")
        with self.assertRaisesRegex(DownstreamTerminalError, "does not allow"):
            select_downstream_terminal_profile(
                registry,
                "oatof_shield_entry_gap1mm",
                upstream_project_id="rf_octupole_ion_optics",
            )

    def test_composition_rejects_duplicate_terminal_voltage_and_geometry_conflicts(self) -> None:
        resolved = compile_mode("segmented_rod_axial_acceleration")
        profile = terminal_registry()["profiles"][0]
        composed = compose_downstream_terminal(resolved, profile)
        with self.assertRaisesRegex(DownstreamTerminalError, "already has"):
            compose_downstream_terminal(composed, profile)
        wrong_voltage = copy.deepcopy(profile)
        wrong_voltage["terminal_potential_V"] = -3.0
        with self.assertRaisesRegex(DownstreamTerminalError, "output reference differs"):
            compose_downstream_terminal(resolved, wrong_voltage)
        intersecting = copy.deepcopy(resolved)
        intersecting["interfaces_mm"]["exit"]["aperture_plate_upstream_face_z_mm"] = 81.0
        intersecting["resolved_sha256"] = resolved_design_sha256(intersecting)
        with self.assertRaisesRegex(DownstreamTerminalError, "intersects"):
            compose_downstream_terminal(intersecting, profile)

    def test_registry_rejects_missing_axes_and_unknown_fields(self) -> None:
        invalid = terminal_registry()
        del invalid["profiles"][0]["aperture"]["width_axis"]
        with self.assertRaises(ContractError):
            validate_schema(invalid, "multipole_downstream_terminal_profiles.schema.json")
        invalid = terminal_registry()
        invalid["profiles"][0]["upstream_terminal_electrode_present"] = True
        with self.assertRaises(ContractError):
            validate_schema(invalid, "multipole_downstream_terminal_profiles.schema.json")


if __name__ == "__main__":
    unittest.main()
