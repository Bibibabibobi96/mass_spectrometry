"""Typed rod operating modes retain one explicit potential reference."""

from __future__ import annotations

import unittest

from projects.rf_multipole_ion_optics.core.compile_design_request import (
    MultipoleDesignCompileError,
    apply_typed_operating_mode,
    compile_design_request,
)
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request

PROJECT_ID = "rf_multipole_ion_optics"


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
        ],
    }


def compile_mode(mode_id: str) -> dict:
    base = design_request("hexapole",
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
    def test_rod_modes_derive_absolute_entity_potentials_from_reference(self) -> None:
        expected = {
            "no_acceleration_full_length": [0.0, 0.0, 0.0, 0.0],
            "segmented_rod_axial_acceleration": [3.0, 2.0, 1.0, 0.0],
        }
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

    def test_relative_mode_topology_mismatches_fail_closed(self) -> None:
        base = design_request("hexapole",
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


if __name__ == "__main__":
    unittest.main()
