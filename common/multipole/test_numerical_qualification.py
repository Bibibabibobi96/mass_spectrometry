from __future__ import annotations

import copy
import csv
import tempfile
import unittest
from pathlib import Path

from common.multipole.numerical_qualification import (
    evaluate,
    mean_source_energy_from_particle_input,
    primary_state_filename,
    validate_identity,
)


def sample(solver: str = "COMSOL") -> dict:
    numerics = {
        "schema_version": 1,
        "role": f"multipole_{solver.lower()}_solver_numerics",
        "trajectory": {"rf_steps_per_period": 80, "maximum_global_time_us": 80},
    }
    if solver == "COMSOL":
        numerics["mesh"] = {
            "global_auto_level": 6,
            "working_region_maximum_element_size_mm": 0.5,
        }
    else:
        numerics.update({"cell_mm": 0.4, "trajectory_quality": 10})
    return {
        "run_id": "run-a",
        "project": "rf_hexapole_ion_optics",
        "solver": solver,
        "config": {
            "mode": "resolved_design_transport",
            "parameters": {
                "model_level": "L3",
                "design_profile_id": "exit_aperture_plate_acceleration",
                "operating_mode_id": "exit_aperture_plate_acceleration",
                "operating_point_id": None,
            },
        },
        "resolved_design_sha256": "D",
        "physical_resolved_design_sha256": "PD",
        "particle_source_sha256": "P",
        "numerics": numerics,
        "handoff_particle_ids": [1, 2],
        "_handoff": {
            1: {
                "transverse_x_mm": "0.1", "transverse_y_mm": "0.2",
                "velocity_x_m_s": "1", "velocity_y_m_s": "2",
                "elapsed_time_us": "40", "kinetic_energy_eV": "2",
            },
            2: {
                "transverse_x_mm": "0.2", "transverse_y_mm": "0.1",
                "velocity_x_m_s": "2", "velocity_y_m_s": "1",
                "elapsed_time_us": "40", "kinetic_energy_eV": "2",
            },
        },
        "scales": {
            "exit_aperture_radius_mm": 3.6,
            "handoff_to_census_distance_mm": 0.5,
            "rf_period_us": 0.9,
            "mean_source_energy_eV": 2.0,
        },
        "observables": {
            "transmission": 1.0,
            "transmitted_particle_count": 2,
            "mean_tof": 40.0,
            "rms_radius": 0.4,
            "rms_divergence": 3.0,
            "mean_energy": 2.0,
            "maximum_rod_radius": 0.5,
            "minimum_working_radius_margin_fraction": 0.8,
            "rms_radius_exit_aperture_fraction": 0.4 / 3.6,
            "projected_divergence_exit_aperture_fraction": 0.007,
            "mean_tof_rf_periods": 40 / 0.9,
            "mean_energy_source_fraction": 1.0,
        },
    }


CONTRACT = {
    "same_solver_acceptance": {
        "maximum": {
            "transmitted_particle_count_difference": 1,
            "rms_radius_exit_aperture_fraction_difference": 0.01,
            "projected_divergence_exit_aperture_fraction_difference": 0.01,
            "mean_tof_rf_period_difference": 0.1,
            "mean_energy_source_fraction_difference": 0.01,
        },
        "handoff_particle_id_sets": "exact_match",
        "minimum_each_run": {"transmission": 0.8},
        "positive_each_run": ["minimum_working_radius_margin_fraction"],
    },
    "cross_solver_acceptance": {
        "maximum": {
            "transmitted_particle_count_difference": 5,
            "rms_radius_exit_aperture_fraction_difference": 0.02,
            "projected_divergence_exit_aperture_fraction_difference": 0.02,
            "mean_tof_rf_period_difference": 0.5,
            "mean_energy_source_fraction_difference": 0.02,
        },
        "handoff_particle_id_sets": "exact_match",
        "minimum_each_run": {"transmission": 0.8},
        "positive_each_run": ["minimum_working_radius_margin_fraction"],
    },
    "claim_limit": "candidate",
}


def mesh_strategy_contract() -> dict:
    contract = copy.deepcopy(CONTRACT)
    del contract["cross_solver_acceptance"]
    contract["claim_profile"] = "mesh_strategy_functional_screen"
    contract["same_solver_acceptance"]["maximum"] = {
        "transmitted_particle_count_difference": 0
    }
    contract["same_solver_acceptance"]["minimum_each_run"]["transmission"] = 1.0
    contract["claim_limit"] = (
        "Functional mesh-strategy screen only; continuous numerical agreement "
        "remains INCONCLUSIVE."
    )
    return contract


class NumericalQualificationTests(unittest.TestCase):
    def test_simion_primary_state_follows_explicit_case_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics = Path(temp_dir) / "paired_metrics.json"
            metrics.write_text(
                '{"primary_case_id":"axial_acceleration_rf_on"}',
                encoding="utf-8",
            )
            manifest = {"outputs": [{"path": str(metrics)}]}
            self.assertEqual(
                primary_state_filename(manifest, "SIMION"),
                "particle_states__axial_acceleration_rf_on.csv",
            )
            self.assertEqual(
                primary_state_filename(manifest, "COMSOL"),
                "particle_state__primary.csv",
            )

    def test_source_energy_normalization_uses_frozen_particle_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "particle_source.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "particle_id",
                        "mass_amu",
                        "vx_m_s",
                        "vy_m_s",
                        "vz_m_s",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "particle_id": 1,
                        "mass_amu": 100,
                        "vx_m_s": 100,
                        "vy_m_s": -50,
                        "vz_m_s": 1900,
                    }
                )
            first = mean_source_energy_from_particle_input(source)
            second = mean_source_energy_from_particle_input(source)
            self.assertEqual(first, second)

    def test_method_only_contract_cannot_qualify(self) -> None:
        with self.assertRaisesRegex(ValueError, "method-only contract"):
            evaluate(sample(), sample(), "temporal", {"claim_limit": "method"})

    def test_spatial_pair_passes_when_only_hmax_is_refined(self) -> None:
        coarse = sample()
        fine = copy.deepcopy(coarse)
        fine["run_id"] = "run-b"
        fine["numerics"]["mesh"]["working_region_maximum_element_size_mm"] = 0.4
        self.assertEqual(evaluate(coarse, fine, "spatial", CONTRACT)["status"], "PASS")

    def test_temporal_pair_rejects_mesh_drift(self) -> None:
        coarse = sample()
        fine = copy.deepcopy(coarse)
        fine["numerics"]["trajectory"]["rf_steps_per_period"] = 160
        fine["numerics"]["mesh"]["global_auto_level"] = 5
        self.assertIn("non-temporal solver numerics differ", validate_identity(coarse, fine, "temporal"))

    def test_mesh_strategy_pair_separates_functional_and_continuous_results(
        self,
    ) -> None:
        full_tetra = sample()
        hybrid = copy.deepcopy(full_tetra)
        hybrid["run_id"] = "run-b"
        hybrid["numerics"]["mesh"] = {
            "strategy": "physical_segment_hybrid_swept_tetra_v1",
            "radial_core_and_rod_hmax_mm": 0.5,
            "axial_layers_per_segment": 10,
        }

        result = evaluate(
            full_tetra,
            hybrid,
            "mesh_strategy",
            mesh_strategy_contract(),
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["functional_status"], "PASS")
        self.assertEqual(
            result["continuous_status"],
            "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET",
        )
        self.assertIn("rms_radius_relative_difference", result["differences"])
        self.assertNotIn(
            "rms_radius_exit_aperture_fraction_difference",
            result["checks"],
        )

    def test_mesh_strategy_pair_rejects_non_mesh_numerics_drift(self) -> None:
        full_tetra = sample()
        hybrid = copy.deepcopy(full_tetra)
        hybrid["numerics"]["mesh"]["strategy"] = (
            "physical_segment_hybrid_swept_tetra_v1"
        )
        hybrid["numerics"]["trajectory"]["rf_steps_per_period"] = 160

        self.assertIn(
            "non-mesh solver numerics differ",
            validate_identity(full_tetra, hybrid, "mesh_strategy"),
        )

    def test_mesh_strategy_pair_rejects_physics_identity_drift(self) -> None:
        full_tetra = sample()
        hybrid = copy.deepcopy(full_tetra)
        hybrid["numerics"]["mesh"]["strategy"] = (
            "physical_segment_hybrid_swept_tetra_v1"
        )
        hybrid["config"]["parameters"]["operating_mode_id"] = (
            "segmented_rod_axial_acceleration"
        )

        self.assertIn(
            "physics identity differs",
            validate_identity(full_tetra, hybrid, "mesh_strategy"),
        )

    def test_mesh_strategy_uses_physical_resolved_identity(self) -> None:
        full_tetra = sample()
        hybrid = copy.deepcopy(full_tetra)
        hybrid["resolved_design_sha256"] = "NEW_PROVENANCE_HASH"
        hybrid["numerics"]["mesh"]["strategy"] = (
            "physical_segment_hybrid_swept_tetra_v1"
        )
        self.assertNotIn(
            "resolved_design_sha256 differs",
            validate_identity(full_tetra, hybrid, "mesh_strategy"),
        )
        hybrid["physical_resolved_design_sha256"] = "DIFFERENT_PHYSICS"
        self.assertIn(
            "physical_resolved_design_sha256 differs",
            validate_identity(full_tetra, hybrid, "mesh_strategy"),
        )

    def test_mesh_strategy_pair_requires_distinct_strategies(self) -> None:
        baseline = sample()
        peer = copy.deepcopy(baseline)
        peer["numerics"]["mesh"]["working_region_maximum_element_size_mm"] = 0.4

        self.assertIn(
            "mesh strategies do not differ",
            validate_identity(baseline, peer, "mesh_strategy"),
        )

    def test_mesh_strategy_contract_rejects_continuous_limits(self) -> None:
        full_tetra = sample()
        hybrid = copy.deepcopy(full_tetra)
        hybrid["numerics"]["mesh"]["strategy"] = (
            "physical_segment_hybrid_swept_tetra_v1"
        )

        contract = mesh_strategy_contract()
        contract["same_solver_acceptance"]["maximum"][
            "rms_radius_exit_aperture_fraction_difference"
        ] = 0.1
        with self.assertRaisesRegex(
            ValueError,
            "cannot apply continuous difference limits",
        ):
            evaluate(full_tetra, hybrid, "mesh_strategy", contract)

    def test_cross_solver_requires_exact_handoff_ids(self) -> None:
        comsol = sample()
        simion = sample("SIMION")
        simion["handoff_particle_ids"] = [1]
        result = evaluate(comsol, simion, "cross_solver", CONTRACT)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["handoff_particle_id_sets"])


if __name__ == "__main__":
    unittest.main()
