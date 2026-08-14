from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.finite_interval_design_compiler import (
    FINITE_INTERVAL_COMPILER_POLICY,
    compile_finite_interval_oatof_design,
)


PROJECT = Path(__file__).resolve().parents[2]


def base_geometry() -> dict[str, object]:
    return json.loads((PROJECT / "config/resolved_geometry.json").read_text())


def request() -> dict[str, object]:
    return {
        "phase_space_input": {
            "mass_to_charge_Th": 100.0,
            "release_position_mm": 1.498375640839315,
            "mean_initial_velocity_m_per_s": 0.0,
            "velocity_slope_m_per_s_per_mm": 0.0,
        },
        "accelerator_stage1_length_mm": 3.0,
        "source_full_width_mm": 2.2,
    }


class FiniteIntervalDesignCompilerTests(unittest.TestCase):
    def test_public_api_atomically_closes_geometry_voltage_and_rebuild_plan(self) -> None:
        geometry, compilation = compile_finite_interval_oatof_design(
            base_geometry(),
            request(),
            prior_rebuild_plan={
                "frontend_pa": False,
                "flight_tube_pa": False,
                "reflectron_pa": False,
            },
        )
        accelerator = geometry["geometry_derivation"]["accelerator"]
        coupled = accelerator["finite_interval_theory"]["coupled_reflectron"]
        self.assertAlmostEqual(geometry["electrodes_V"]["repeller"], 2158.41, places=1)
        self.assertAlmostEqual(geometry["electrodes_V"]["grid1"], 1841.25, places=1)
        self.assertAlmostEqual(geometry["electrodes_V"]["midgrid"], 1603.02, places=1)
        self.assertAlmostEqual(
            accelerator["canonical_grid2_z_mm"]
            + accelerator["focus_drift_after_grid2_mm"],
            0.0,
            places=12,
        )
        self.assertLess(
            coupled["required_stage2_depth_mm"], geometry["geometry_mm"]["L_stage2"]
        )
        self.assertEqual(
            compilation["simion_rebuild_plan"],
            {"frontend_pa": True, "flight_tube_pa": True, "reflectron_pa": False},
        )

    def test_public_api_rejects_integration_provenance(self) -> None:
        for field, value in (
            ("profile_path", "integration/profile.json"),
            ("run_id", "run"),
            ("checkpoint", "event"),
            ("cohort", "all"),
            ("particle_count", 1000),
        ):
            with self.subTest(field=field):
                invalid = request()
                invalid[field] = value
                with self.assertRaisesRegex(ValueError, "request fields differ"):
                    compile_finite_interval_oatof_design(
                        base_geometry(), invalid,
                        prior_rebuild_plan={"reflectron_pa": False},
                    )

    def test_public_api_rejects_phase_space_provenance(self) -> None:
        invalid = request()
        invalid["phase_space_input"] = copy.deepcopy(invalid["phase_space_input"])
        invalid["phase_space_input"]["run_id"] = "run"
        with self.assertRaisesRegex(ValueError, "phase_space_input fields differ"):
            compile_finite_interval_oatof_design(
                base_geometry(), invalid, prior_rebuild_plan={"reflectron_pa": False}
            )

    def test_numerical_policy_is_project_owned_and_named(self) -> None:
        self.assertEqual(
            FINITE_INTERVAL_COMPILER_POLICY,
            {
                "policy_id": "finite_interval_uniform_two_field_theory_v1",
                "voltage_drop_bounds_V": (100.0, 1200.0),
                "sample_count": 1001,
                "voltage_tolerance_V": 1e-8,
            },
        )


if __name__ == "__main__":
    unittest.main()
