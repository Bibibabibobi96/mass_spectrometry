from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.multipole.axial_acceleration import (
    AxialAccelerationError,
    resolve_axial_acceleration,
    segment_rod_array,
)


def contract() -> dict:
    return {
        "schema_version": 2,
        "role": "multipole_axial_acceleration_contract",
        "project_id": "example",
        "model_id": "multipole.segmented_rod_common_mode_staircase.v2",
        "segmentation": {
            "strategy": "uniform",
            "segment_count": 4,
            "intersegment_gap_mm": 0.4,
            "entrance_common_mode_V": 0.0,
            "exit_common_mode_V": -3.0,
        },
        "output_reference_V": -3.0,
        "functional_acceptance": {
            "minimum_transmission": 0.8,
            "minimum_mean_energy_gain_eV": 2.5,
            "maximum_mean_output_energy_error_eV": 0.5,
        },
        "claim_limit": "functional only",
    }


class AxialAccelerationTest(unittest.TestCase):
    def test_positive_ion_gains_three_ev_across_four_segments(self) -> None:
        result = resolve_axial_acceleration(
            contract(), rod_z_min_mm=0, rod_z_max_mm=79.6, source_kinetic_energy_ev=2, charge_state=1
        )
        self.assertEqual(result["derived"]["segmentation_strategy"], "uniform")
        self.assertAlmostEqual(result["derived"]["segments"][0]["z_max_mm"], 19.6)
        self.assertEqual(
            [segment["common_mode_V"] for segment in result["derived"]["segments"]],
            [0.0, -1.0, -2.0, -3.0],
        )
        self.assertEqual(result["derived"]["predicted_output_energy_eV"], 5.0)

    def test_segmented_array_preserves_rf_groups(self) -> None:
        resolved = resolve_axial_acceleration(
            contract(), rod_z_min_mm=0, rod_z_max_mm=79.6, source_kinetic_energy_ev=2, charge_state=1
        )
        array = {"rods": [
            {"rod_id": 1, "electrode_group": 1, "z_min_mm": 0, "z_max_mm": 79.6},
            {"rod_id": 2, "electrode_group": 2, "z_min_mm": 0, "z_max_mm": 79.6},
        ]}
        segmented = segment_rod_array(array, resolved)
        self.assertEqual(len(segmented["electrodes"]), 8)
        self.assertEqual([item["electrode_id"] for item in segmented["electrodes"]], list(range(1, 9)))
        self.assertEqual([item["electrode_group"] for item in segmented["electrodes"]], [1, 2] * 4)

    def test_output_reference_must_preserve_net_energy_gain(self) -> None:
        invalid = contract()
        invalid["output_reference_V"] = 0.0
        with self.assertRaises(AxialAccelerationError):
            resolve_axial_acceleration(
                invalid, rod_z_min_mm=0, rod_z_max_mm=79.6, source_kinetic_energy_ev=2, charge_state=1
            )

    def test_explicit_strategy_supports_independent_lengths_gaps_and_voltages(self) -> None:
        explicit = contract()
        explicit["segmentation"] = {
            "strategy": "explicit",
            "segments": [
                {"length_mm": 10.0, "gap_after_mm": 0.2, "common_mode_V": 0.0},
                {"length_mm": 20.0, "gap_after_mm": 0.8, "common_mode_V": -2.0},
                {"length_mm": 49.0, "common_mode_V": -3.0},
            ],
        }
        result = resolve_axial_acceleration(
            explicit, rod_z_min_mm=5, rod_z_max_mm=85, source_kinetic_energy_ev=2, charge_state=1
        )
        self.assertEqual(result["derived"]["segmentation_strategy"], "explicit")
        self.assertEqual(
            [(item["z_min_mm"], item["z_max_mm"], item["common_mode_V"]) for item in result["derived"]["segments"]],
            [(5.0, 15.0, 0.0), (15.2, 35.2, -2.0), (36.0, 85.0, -3.0)],
        )

    def test_explicit_strategy_allows_nonmonotonic_internal_voltage(self) -> None:
        explicit = contract()
        explicit["segmentation"] = {
            "strategy": "explicit",
            "segments": [
                {"length_mm": 20.0, "common_mode_V": 0.0},
                {"length_mm": 20.0, "common_mode_V": 1.0},
                {"length_mm": 20.0, "common_mode_V": -3.0},
            ],
        }
        result = resolve_axial_acceleration(
            explicit, rod_z_min_mm=0, rod_z_max_mm=60, source_kinetic_energy_ev=2, charge_state=1
        )
        self.assertEqual(result["derived"]["predicted_energy_gain_eV"], 3.0)
        self.assertFalse(result["derived"]["voltage_profile_monotonic"])

    def test_explicit_strategy_rejects_length_mismatch(self) -> None:
        explicit = contract()
        explicit["segmentation"] = {
            "strategy": "explicit",
            "segments": [
                {"length_mm": 20.0, "gap_after_mm": 1.0, "common_mode_V": 0.0},
                {"length_mm": 20.0, "common_mode_V": -3.0},
            ],
        }
        with self.assertRaisesRegex(AxialAccelerationError, "conserve"):
            resolve_axial_acceleration(
                explicit, rod_z_min_mm=0, rod_z_max_mm=50, source_kinetic_energy_ev=2, charge_state=1
            )

    def test_explicit_strategy_rejects_nonfinite_and_final_gap(self) -> None:
        for invalid_segment in (
            {"length_mm": float("nan"), "common_mode_V": 0.0},
            {"length_mm": 20.0, "gap_after_mm": -1.0, "common_mode_V": 0.0},
        ):
            explicit = contract()
            explicit["segmentation"] = {
                "strategy": "explicit",
                "segments": [invalid_segment, {"length_mm": 20.0, "common_mode_V": -3.0}],
            }
            with self.assertRaises(AxialAccelerationError):
                resolve_axial_acceleration(
                    explicit, rod_z_min_mm=0, rod_z_max_mm=40, source_kinetic_energy_ev=2, charge_state=1
                )
        explicit = contract()
        explicit["segmentation"] = {
            "strategy": "explicit",
            "segments": [
                {"length_mm": 20.0, "common_mode_V": 0.0},
                {"length_mm": 19.0, "gap_after_mm": 1.0, "common_mode_V": -3.0},
            ],
        }
        with self.assertRaisesRegex(AxialAccelerationError, "final"):
            resolve_axial_acceleration(
                explicit, rod_z_min_mm=0, rod_z_max_mm=40, source_kinetic_energy_ev=2, charge_state=1
            )

    def test_projects_do_not_reimplement_segmentation_strategies(self) -> None:
        root = Path(__file__).resolve().parents[2]
        projects = (
            "rf_quadrupole_collision_cooling",
            "rf_hexapole_ion_guide",
            "rf_octupole_ion_guide",
        )
        forbidden = ("strategy == \"uniform\"", "strategy == \"explicit\"", "_resolve_uniform", "_resolve_explicit")
        for project in projects:
            for path in (root / "projects" / project).rglob("*"):
                if path.suffix.lower() not in {".py", ".m", ".lua", ".ps1"}:
                    continue
                source = path.read_text(encoding="utf-8-sig")
                for marker in forbidden:
                    self.assertNotIn(marker, source, f"{path} duplicates shared segmentation strategy {marker}")

    def test_all_solver_wrappers_expose_one_shared_custom_contract_binding(self) -> None:
        root = Path(__file__).resolve().parents[2]
        projects = (
            "rf_quadrupole_collision_cooling",
            "rf_hexapole_ion_guide",
            "rf_octupole_ion_guide",
        )
        for project in projects:
            for name in ("run_finite_3d_transport.ps1", "run_simion_finite_3d_transport.ps1"):
                source = (root / "projects" / project / "analysis" / name).read_text(encoding="utf-8-sig")
                self.assertIn("AxialAccelerationContractPath", source)
                self.assertIn("common\\multipole", source)

    def test_versioned_explicit_solver_regression_contract_resolves(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = (
            root
            / "projects/rf_quadrupole_collision_cooling/config/modes"
            / "axial_acceleration_explicit_functional_test.json"
        )
        result = resolve_axial_acceleration(
            json.loads(path.read_text(encoding="utf-8")),
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
            source_kinetic_energy_ev=2.0,
            charge_state=1,
        )
        self.assertEqual(result["derived"]["segmentation_strategy"], "explicit")
        self.assertAlmostEqual(result["derived"]["segments"][-1]["z_max_mm"], 85.4)


if __name__ == "__main__":
    unittest.main()
