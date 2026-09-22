from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.ion_release.cylinder import (
    GAUSSIAN_STRATEGY,
    HALTON_STRATEGY,
    ROLE,
    generate_center_first_halton_cylinder_phase_space,
    generate_cylinder_release_states,
    validate_cylinder_release_spec,
)
from common.ion_release.release import (
    generate_release_states,
    materialize_release_from_file,
    validate_materialized_release,
    validate_release_spec,
)


def halton_spec(count: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "role": ROLE,
        "frame_id": "test.local.cartesian.v1",
        "particle_count": count,
        "mother_particle_count": 1000,
        "common_time_of_birth_s": 0.0,
        "geometry": {"shape": "cylinder", "center_mm": [1.0, 2.0, 3.0], "axis": "z", "radius_mm": 1.0, "height_mm": 1.0},
        "species": {"mass_amu": 524.0, "charge_state": 1},
        "sampling": {
            "strategy": HALTON_STRATEGY,
            "kinetic_energy": {"center_ev": 5.0, "full_width_ev": 0.2},
            "nominal_direction": [0.0, 1.0, 0.0],
            "angular_full_width_deg": 0.4,
        },
    }


def gaussian_spec() -> dict[str, object]:
    spec = halton_spec(100)
    spec["geometry"] = {"shape": "cylinder", "center_mm": [3.0, -2.0, 7.0], "axis": "x", "radius_mm": 2.0, "height_mm": 4.0}
    spec["sampling"] = {
        "strategy": GAUSSIAN_STRATEGY,
        "seed": 37,
        "velocity_distribution": {"mean_m_s": [120.0, 0.0, 0.0], "sigma_m_s": [3.0, 2.0, 1.0], "minimum_axis_m_s": 100.0},
    }
    return spec


class CylinderReleaseTests(unittest.TestCase):
    def test_halton_full_volume_is_deterministic_and_prefix_stable(self) -> None:
        small = generate_release_states(halton_spec(100))
        large = generate_release_states(halton_spec(1000))
        self.assertEqual(small, large[:100])
        self.assertEqual(large[0]["x_mm"], 1.0)
        self.assertEqual(large[0]["y_mm"], 2.0)
        self.assertEqual(large[0]["z_mm"], 3.0)
        self.assertGreater(large[0]["vy_m_s"], 0.0)
        self.assertGreater(large[0]["vy_m_s"], 0.0)
        for state in large:
            self.assertLessEqual((state["x_mm"] - 1.0) ** 2 + (state["y_mm"] - 2.0) ** 2, 1.0 + 1e-12)
            self.assertGreaterEqual(state["z_mm"], 2.5)
            self.assertLessEqual(state["z_mm"], 3.5)

    def test_phase_space_sampler_preserves_axis_order_and_prefix(self) -> None:
        arguments = {
            "center_mm": [1.0, 2.0, 3.0], "transverse_axes": (1, 0), "axis": 2,
            "radius_mm": 1.0, "height_mm": 1.0,
            "kinetic_energy_center_ev": 5.0, "kinetic_energy_full_width_ev": 0.2,
            "nominal_direction": [0.0, 1.0, 0.0], "angular_full_width_deg": 0.4,
        }
        small = generate_center_first_halton_cylinder_phase_space(
            particle_count=100, **arguments,
        )
        large = generate_center_first_halton_cylinder_phase_space(
            particle_count=1000, **arguments,
        )
        self.assertEqual(small, large[:100])
        self.assertEqual(small[0], {
            "particle_id": 1, "position_mm": [1.0, 2.0, 3.0],
            "kinetic_energy_ev": 5.0, "direction": [0.0, 1.0, 0.0],
        })
        self.assertNotEqual(small[1]["position_mm"][0], 1.0)
        self.assertNotEqual(small[1]["position_mm"][1], 2.0)

    def test_gaussian_strategy_obeys_axis_and_volume_bounds(self) -> None:
        states = generate_cylinder_release_states(gaussian_spec())
        self.assertEqual(states, generate_cylinder_release_states(gaussian_spec()))
        for state in states:
            self.assertGreaterEqual(state["vx_m_s"], 100.0)
            self.assertLessEqual((state["y_mm"] + 2.0) ** 2 + (state["z_mm"] - 7.0) ** 2, 4.0 + 1e-12)
            self.assertGreaterEqual(state["x_mm"], 1.0)
            self.assertLessEqual(state["x_mm"], 5.0)

    def test_receipt_rebuilds_and_rejects_table_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "source.json"
            spec_path.write_text(json.dumps(halton_spec(100)), encoding="utf-8")
            receipt = materialize_release_from_file(spec_path, root / "source.csv", root / "receipt.json")
            self.assertEqual(validate_materialized_release(root / "receipt.json"), receipt)
            table = root / "source.csv"
            table.write_text(table.read_text(encoding="utf-8").replace(",1,", ",2,", 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity changed"):
                validate_materialized_release(root / "receipt.json")

    def test_receipt_binds_the_frozen_spec_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "source.json"
            spec_path.write_text(json.dumps(halton_spec(100)), encoding="utf-8")
            materialize_release_from_file(spec_path, root / "source.csv", root / "receipt.json")
            spec_path.write_text(json.dumps(halton_spec(100), indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source specification identity changed"):
                validate_materialized_release(root / "receipt.json")

    def test_invalid_spec_fails_closed(self) -> None:
        invalid = halton_spec(100)
        invalid["geometry"] = {"shape": "cylinder", "center_mm": [0.0, 0.0, 0.0], "axis": "bad", "radius_mm": 1.0, "height_mm": 1.0}
        with self.assertRaisesRegex(ValueError, "axis"):
            validate_cylinder_release_spec(invalid)

    def test_unregistered_shape_fails_closed(self) -> None:
        invalid = halton_spec(100)
        invalid["geometry"] = {"shape": "plane", "center_mm": [0.0, 0.0, 0.0], "axis": "z", "radius_mm": 1.0, "height_mm": 1.0}
        with self.assertRaisesRegex(ValueError, "unsupported release shape"):
            validate_release_spec(invalid)


if __name__ == "__main__":
    unittest.main()
