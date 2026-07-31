from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from common.multipole.numerical_qualification import (
    compose_engineering_progression_contract,
    evaluate,
    handoff_observables,
    load_engineering_progression_contract,
    mean_source_energy_from_particle_input,
    observable_differences,
    primary_state_filename,
    standalone_candidate_envelope,
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
    result = {
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
                "velocity_axial_m_s": "100",
                "elapsed_time_us": "40", "kinetic_energy_eV": "2",
            },
            2: {
                "transverse_x_mm": "0.2", "transverse_y_mm": "0.1",
                "velocity_x_m_s": "2", "velocity_y_m_s": "1",
                "velocity_axial_m_s": "100",
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
    derived = handoff_observables(list(result["_handoff"].values()))
    for name in (
        "transverse_centroid_x_mm",
        "transverse_centroid_y_mm",
        "centered_spatial_rms_spread_mm",
        "mean_beam_direction_unit_x",
        "mean_beam_direction_unit_y",
        "mean_beam_direction_unit_z",
        "centered_angular_rms_spread_deg",
        "centered_rms_energy_spread_eV",
    ):
        result["observables"][name] = derived[name]
    return result


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


FUNCTIONAL_SHA256 = "A" * 64


def engineering_policy(*, active: bool = False) -> dict:
    status = (
        "ACTIVE_ENGINEERING_PROGRESSION_POLICY"
        if active
        else "DRAFT_PENDING_ENERGY_THRESHOLDS"
    )
    continuous = {
        "spatial_observables": {
            "centroid_position_difference_mm": {"maximum": 0.2},
            "centered_spatial_spread_difference_mm": {"maximum": 0.2},
        },
        "angular_observables": {
            "mean_direction_difference_deg": {"maximum": 1.0},
            "centered_angular_spread_difference_deg": {"maximum": 1.0},
        },
        "energy_observables": {
            "mean_energy_difference_eV": {
                "maximum": None,
                "status": "PENDING_DOWNSTREAM_ACCEPTANCE",
            },
            "centered_energy_spread_difference_eV": {
                "maximum": None,
                "status": "PENDING_DOWNSTREAM_ACCEPTANCE",
            },
        },
        "comparison_operator": "absolute_difference_less_than_or_equal",
        "all_approved_thresholds_required": True,
        "energy_thresholds_required_before_activation": True,
        "missing_metric_result": "NOT_EVALUATED_DO_NOT_PROGRESS",
    }
    if active:
        continuous["energy_observables"]["mean_energy_difference_eV"] = {
            "maximum": 0.5,
            "status": "APPROVED",
        }
        continuous["energy_observables"][
            "centered_energy_spread_difference_eV"
        ] = {"maximum": 0.25, "status": "APPROVED"}
    return {
        "role": "multipole_engineering_progression_acceptance_contract",
        "contract_id": "test-engineering-progression",
        "status": status,
        "scope": {
            "comparison_kinds": [
                "same_solver_discretization",
                "cross_solver",
            ]
        },
        "functional_acceptance": {
            "required_result": "PASS",
            "sha256": FUNCTIONAL_SHA256,
        },
        "continuous_engineering_acceptance": continuous,
        "claim_limit": (
            "Engineering progression only; this is not numerical convergence, "
            "solver equivalence, or Formal qualification."
        ),
    }


def engineering_contract(*, active: bool = False) -> dict:
    functional = copy.deepcopy(CONTRACT)
    functional["claim_profile"] = "functional_transport"
    return compose_engineering_progression_contract(
        engineering_policy(active=active),
        functional,
        functional_contract_sha256=FUNCTIONAL_SHA256,
    )


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
    def test_candidate_envelope_unions_solver_numerical_intervals(self) -> None:
        comsol = sample()
        comsol_spatial = copy.deepcopy(comsol)
        comsol_spatial["run_id"] = "comsol-spatial"
        comsol_spatial["numerics"]["mesh"][
            "working_region_maximum_element_size_mm"
        ] = 0.4
        comsol_spatial["_handoff"][1]["transverse_x_mm"] = "0.11"
        comsol_spatial["observables"]["rms_radius"] = 0.41
        comsol_temporal = copy.deepcopy(comsol)
        comsol_temporal["run_id"] = "comsol-temporal"
        comsol_temporal["numerics"]["trajectory"]["rf_steps_per_period"] = 160
        comsol_temporal["_handoff"][1]["transverse_x_mm"] = "0.08"
        comsol_temporal["observables"]["rms_radius"] = 0.38

        simion = sample("SIMION")
        simion["run_id"] = "simion"
        simion["_handoff"][1]["transverse_x_mm"] = "0.13"
        simion["observables"]["rms_radius"] = 0.45
        simion_spatial = copy.deepcopy(simion)
        simion_spatial["run_id"] = "simion-spatial"
        simion_spatial["numerics"]["cell_mm"] = 0.3
        simion_spatial["_handoff"][1]["transverse_x_mm"] = "0.14"
        simion_spatial["observables"]["rms_radius"] = 0.46
        simion_temporal = copy.deepcopy(simion)
        simion_temporal["run_id"] = "simion-temporal"
        simion_temporal["numerics"]["trajectory"]["rf_steps_per_period"] = 160
        simion_temporal["_handoff"][1]["transverse_x_mm"] = "0.11"
        simion_temporal["observables"]["rms_radius"] = 0.43

        result = standalone_candidate_envelope(
            {
                "COMSOL": {
                    "nominal": comsol,
                    "spatial_refined": comsol_spatial,
                    "temporal_refined": comsol_temporal,
                },
                "SIMION": {
                    "nominal": simion,
                    "spatial_refined": simion_spatial,
                    "temporal_refined": simion_temporal,
                },
            }
        )

        self.assertEqual(result["status"], "PASS")
        self.assertAlmostEqual(
            result["per_solver"]["COMSOL"]["particle_intervals"]["1"][
                "transverse_x_mm"
            ]["numerical_half_width"],
            0.02,
        )
        particle_interval = result["union"]["particle_intervals"]["1"]["fields"][
            "transverse_x_mm"
        ]
        self.assertAlmostEqual(particle_interval[0], 0.08)
        self.assertAlmostEqual(particle_interval[1], 0.15)
        observable_interval = result["union"]["observable_intervals"]["rms_radius"]
        self.assertAlmostEqual(observable_interval[0], 0.38)
        self.assertAlmostEqual(observable_interval[1], 0.47)

    def test_candidate_envelope_rejects_particle_id_drift(self) -> None:
        runs = {}
        for solver in ("COMSOL", "SIMION"):
            nominal = sample(solver)
            spatial = copy.deepcopy(nominal)
            temporal = copy.deepcopy(nominal)
            if solver == "COMSOL":
                spatial["numerics"]["mesh"][
                    "working_region_maximum_element_size_mm"
                ] = 0.4
            else:
                spatial["numerics"]["cell_mm"] = 0.3
            temporal["numerics"]["trajectory"]["rf_steps_per_period"] = 160
            runs[solver] = {
                "nominal": nominal,
                "spatial_refined": spatial,
                "temporal_refined": temporal,
            }
        runs["SIMION"]["temporal_refined"]["handoff_particle_ids"] = [1]

        result = standalone_candidate_envelope(runs)

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["exact_handoff_particle_ids"])

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

    def test_legacy_simion_scalar_spatial_pair_remains_isotropic(self) -> None:
        coarse = sample("SIMION")
        fine = copy.deepcopy(coarse)
        fine["numerics"]["cell_mm"] = 0.3
        self.assertEqual(validate_identity(coarse, fine, "spatial"), [])

    def test_simion_radial_spatial_pair_refines_x_and_y_only(self) -> None:
        coarse = sample("SIMION")
        coarse["numerics"].pop("cell_mm")
        coarse["numerics"]["cell_mm_xyz"] = {"x": 0.4, "y": 0.4, "z": 0.6}
        fine = copy.deepcopy(coarse)
        fine["numerics"]["cell_mm_xyz"] = {"x": 0.3, "y": 0.3, "z": 0.6}
        self.assertEqual(validate_identity(coarse, fine, "spatial_radial"), [])
        fine["numerics"]["cell_mm_xyz"]["z"] = 0.5
        self.assertIn(
            "non-target SIMION z-cell spacing differs",
            validate_identity(coarse, fine, "spatial_radial"),
        )

    def test_simion_axial_spatial_pair_refines_z_only(self) -> None:
        coarse = sample("SIMION")
        coarse["numerics"].pop("cell_mm")
        coarse["numerics"]["cell_mm_xyz"] = {"x": 0.4, "y": 0.5, "z": 0.6}
        fine = copy.deepcopy(coarse)
        fine["numerics"]["cell_mm_xyz"]["z"] = 0.3
        self.assertEqual(validate_identity(coarse, fine, "spatial_axial"), [])
        fine["numerics"]["cell_mm_xyz"]["x"] = 0.3
        self.assertIn(
            "non-target SIMION x-cell spacing differs",
            validate_identity(coarse, fine, "spatial_axial"),
        )

    def test_simion_isotropic_spatial_pair_refines_all_axes(self) -> None:
        coarse = sample("SIMION")
        coarse["numerics"].pop("cell_mm")
        coarse["numerics"]["cell_mm_xyz"] = {"x": 0.4, "y": 0.4, "z": 0.4}
        fine = copy.deepcopy(coarse)
        fine["numerics"]["cell_mm_xyz"] = {"x": 0.3, "y": 0.3, "z": 0.3}
        self.assertEqual(validate_identity(coarse, fine, "spatial_isotropic"), [])
        fine["numerics"]["cell_mm_xyz"]["y"] = 0.4
        self.assertIn(
            "refined SIMION y-cell spacing is not smaller",
            validate_identity(coarse, fine, "spatial_isotropic"),
        )

    def test_spatial_pair_accepts_only_local_sensitive_size_refinement(
        self,
    ) -> None:
        coarse = sample()
        coarse["numerics"]["mesh"] = {
            "strategy": "physical_segment_hybrid_swept_tetra_v1",
            "hybrid": {
                "radial_core_and_rod_hmax_mm": 0.5,
                "sensitive_region": {
                    "particle_corridor_radius_mm": 3.6,
                    "maximum_element_size_mm": 0.5,
                },
            },
        }
        fine = copy.deepcopy(coarse)
        fine["run_id"] = "run-b"
        fine["numerics"]["mesh"]["hybrid"]["sensitive_region"][
            "maximum_element_size_mm"
        ] = 0.4

        self.assertNotIn(
            "non-spatial solver numerics differ",
            validate_identity(coarse, fine, "spatial"),
        )

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

    def test_spatial_pair_supports_exit_interface_refinement_axis(self) -> None:
        coarse = sample()
        coarse["numerics"]["mesh"] = {
            "strategy": "physical_segment_hybrid_swept_tetra_v1",
            "global_auto_level": 6,
            "working_region_maximum_element_size_mm": None,
            "hybrid": {
                "sensitive_region": {
                    "maximum_element_size_mm": 0.4,
                    "exit_interface_refinement": {
                        "maximum_element_size_mm": 0.25
                    },
                }
            },
        }
        fine = copy.deepcopy(coarse)
        fine["numerics"]["mesh"]["hybrid"]["sensitive_region"][
            "exit_interface_refinement"
        ]["maximum_element_size_mm"] = 0.2

        self.assertEqual(validate_identity(coarse, fine, "spatial"), [])

    def test_spatial_pair_rejects_multiple_changed_mesh_size_axes(self) -> None:
        coarse = sample()
        coarse["numerics"]["mesh"] = {
            "strategy": "physical_segment_hybrid_swept_tetra_v1",
            "global_auto_level": 6,
            "working_region_maximum_element_size_mm": None,
            "hybrid": {
                "sensitive_region": {
                    "maximum_element_size_mm": 0.5,
                    "exit_interface_refinement": {
                        "maximum_element_size_mm": 0.25
                    },
                }
            },
        }
        fine = copy.deepcopy(coarse)
        fine["numerics"]["mesh"]["hybrid"]["sensitive_region"][
            "maximum_element_size_mm"
        ] = 0.4
        fine["numerics"]["mesh"]["hybrid"]["sensitive_region"][
            "exit_interface_refinement"
        ]["maximum_element_size_mm"] = 0.2

        self.assertIn(
            "COMSOL spatial comparison must change exactly one supported mesh-size axis",
            validate_identity(coarse, fine, "spatial"),
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

    def test_handoff_observables_use_primitives_and_center_each_beam(self) -> None:
        values = [
            {
                "transverse_x_mm": "1",
                "transverse_y_mm": "0",
                "velocity_x_m_s": "0",
                "velocity_y_m_s": "0",
                "velocity_axial_m_s": "2",
                "elapsed_time_us": "4",
                "kinetic_energy_eV": "2",
                "radial_position_mm": "999",
                "divergence_angle_deg": "999",
            },
            {
                "transverse_x_mm": "3",
                "transverse_y_mm": "0",
                "velocity_x_m_s": "2",
                "velocity_y_m_s": "0",
                "velocity_axial_m_s": "2",
                "elapsed_time_us": "6",
                "kinetic_energy_eV": "4",
                "radial_position_mm": "999",
                "divergence_angle_deg": "999",
            },
        ]

        result = handoff_observables(values)

        self.assertEqual(result["transverse_centroid_x_mm"], 2.0)
        self.assertEqual(result["centered_spatial_rms_spread_mm"], 1.0)
        self.assertEqual(result["rms_radius"], math.sqrt(5))
        self.assertEqual(result["mean_energy"], 3.0)
        self.assertEqual(result["centered_rms_energy_spread_eV"], 1.0)
        self.assertGreater(result["centered_angular_rms_spread_deg"], 0)
        self.assertLess(result["centered_angular_rms_spread_deg"], 45)

    def test_handoff_observables_reject_nonfinite_canonical_primitive(self) -> None:
        values = [
            {
                "transverse_x_mm": "nan",
                "transverse_y_mm": "0",
                "velocity_x_m_s": "0",
                "velocity_y_m_s": "0",
                "velocity_axial_m_s": "1",
                "elapsed_time_us": "1",
                "kinetic_energy_eV": "1",
            }
        ]
        with self.assertRaisesRegex(ValueError, "non-finite transverse_x_mm"):
            handoff_observables(values)

    def test_decomposed_engineering_differences_are_centered(self) -> None:
        baseline = sample()
        peer = copy.deepcopy(baseline)
        peer_observables = peer["observables"]
        peer_observables["transverse_centroid_x_mm"] += 0.3
        peer_observables["transverse_centroid_y_mm"] += 0.4
        peer_observables["centered_spatial_rms_spread_mm"] += 0.2
        angle = math.radians(2.0)
        peer_observables["mean_beam_direction_unit_x"] = math.sin(angle)
        peer_observables["mean_beam_direction_unit_y"] = 0.0
        peer_observables["mean_beam_direction_unit_z"] = math.cos(angle)
        baseline["observables"]["mean_beam_direction_unit_x"] = 0.0
        baseline["observables"]["mean_beam_direction_unit_y"] = 0.0
        baseline["observables"]["mean_beam_direction_unit_z"] = 1.0
        peer_observables["centered_angular_rms_spread_deg"] += 0.75
        peer_observables["mean_energy"] += 0.4
        peer_observables["centered_rms_energy_spread_eV"] += 0.1

        differences = observable_differences(baseline, peer)

        self.assertAlmostEqual(
            differences["transverse_centroid_vector_difference_mm"], 0.5
        )
        self.assertAlmostEqual(
            differences[
                "centered_spatial_rms_spread_absolute_difference_mm"
            ],
            0.2,
        )
        self.assertAlmostEqual(
            differences["mean_beam_direction_separation_deg"], 2.0
        )
        self.assertAlmostEqual(
            differences[
                "centered_angular_rms_spread_absolute_difference_deg"
            ],
            0.75,
        )
        self.assertAlmostEqual(
            differences["mean_energy_absolute_difference_eV"], 0.4
        )
        self.assertAlmostEqual(
            differences[
                "centered_rms_energy_spread_absolute_difference_eV"
            ],
            0.1,
        )

    def test_draft_contract_exposes_capability_but_cannot_pass(self) -> None:
        contract = engineering_contract()
        maximum = contract["same_solver_acceptance"]["maximum"]
        self.assertIn("transverse_centroid_vector_difference_mm", maximum)
        self.assertIn(
            "centered_spatial_rms_spread_absolute_difference_mm", maximum
        )
        self.assertIn("mean_beam_direction_separation_deg", maximum)
        self.assertIn(
            "centered_angular_rms_spread_absolute_difference_deg", maximum
        )
        self.assertNotIn("rms_radius_absolute_difference_mm", maximum)
        self.assertNotIn("rms_divergence_absolute_difference_deg", maximum)
        self.assertNotIn("mean_energy_absolute_difference_eV", maximum)
        self.assertEqual(
            set(contract["pending_required_threshold_metrics"]),
            {
                "mean_energy_absolute_difference_eV",
                "centered_rms_energy_spread_absolute_difference_eV",
            },
        )

        baseline = sample()
        refined = copy.deepcopy(baseline)
        refined["numerics"]["trajectory"]["rf_steps_per_period"] = 160
        result = evaluate(baseline, refined, "temporal", contract)
        self.assertEqual(result["status"], "NOT_EVALUATED_DO_NOT_PROGRESS")
        self.assertEqual(
            result["numerical_convergence_status"], "DEFERRED_NOT_WAIVED"
        )

    def test_active_engineering_contract_passes_all_six_metrics(self) -> None:
        baseline = sample()
        peer = sample("SIMION")
        peer_observables = peer["observables"]
        peer_observables["transverse_centroid_x_mm"] += 0.2
        peer_observables["centered_spatial_rms_spread_mm"] += 0.2
        peer_observables["centered_angular_rms_spread_deg"] += 1.0
        peer_observables["mean_energy"] += 0.5
        peer_observables["centered_rms_energy_spread_eV"] += 0.25

        result = evaluate(
            baseline, peer, "cross_solver", engineering_contract(active=True)
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["engineering_progression_status"], "PASS")
        self.assertIn("not numerical convergence", result["claim_limit"])
        self.assertIn("solver equivalence", result["claim_limit"])
        self.assertIn("Formal qualification", result["claim_limit"])

    def test_active_engineering_contract_blocks_one_exceeded_metric(self) -> None:
        baseline = sample()
        peer = sample("SIMION")
        peer["observables"]["centered_spatial_rms_spread_mm"] += 0.2001

        result = evaluate(
            baseline, peer, "cross_solver", engineering_contract(active=True)
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(
            result["checks"][
                "centered_spatial_rms_spread_absolute_difference_mm"
            ]
        )

    def test_active_engineering_contract_missing_metric_does_not_progress(
        self,
    ) -> None:
        baseline = sample()
        peer = sample("SIMION")
        peer["observables"]["centered_angular_rms_spread_deg"] = math.nan

        result = evaluate(
            baseline, peer, "cross_solver", engineering_contract(active=True)
        )

        self.assertEqual(result["status"], "NOT_EVALUATED_DO_NOT_PROGRESS")
        self.assertEqual(
            result["missing_required_metrics"],
            ["centered_angular_rms_spread_absolute_difference_deg"],
        )

    def test_engineering_contract_functional_or_identity_failure_blocks(
        self,
    ) -> None:
        baseline = sample()
        peer = sample("SIMION")
        peer["observables"]["transmission"] = 0.79
        functional_failure = evaluate(
            baseline, peer, "cross_solver", engineering_contract(active=True)
        )
        self.assertEqual(functional_failure["status"], "FAIL")

        peer = sample("SIMION")
        peer["particle_source_sha256"] = "different"
        identity_failure = evaluate(
            baseline, peer, "cross_solver", engineering_contract(active=True)
        )
        self.assertEqual(identity_failure["status"], "FAIL")
        self.assertIn(
            "particle_source_sha256 differs",
            identity_failure["identity_errors"],
        )

    def test_engineering_contract_rejects_stale_binding_or_active_gap(
        self,
    ) -> None:
        functional = copy.deepcopy(CONTRACT)
        functional["claim_profile"] = "functional_transport"
        with self.assertRaisesRegex(ValueError, "binding is stale"):
            compose_engineering_progression_contract(
                engineering_policy(),
                functional,
                functional_contract_sha256="B" * 64,
            )
        with self.assertRaisesRegex(ValueError, "lacks required energy"):
            compose_engineering_progression_contract(
                {
                    **engineering_policy(),
                    "status": "ACTIVE_ENGINEERING_PROGRESSION_POLICY",
                },
                functional,
                functional_contract_sha256=FUNCTIONAL_SHA256,
            )

    def test_trusted_engineering_loader_hashes_and_binds_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory) / "common" / "multipole"
            common.mkdir(parents=True)
            functional_path = common / "functional_transport_acceptance.json"
            policy_path = common / "engineering_progression_acceptance.json"
            functional = copy.deepcopy(CONTRACT)
            functional.update(
                {
                    "contract_id": "functional-test",
                    "claim_profile": "functional_transport",
                }
            )
            functional_path.write_text(
                json.dumps(functional) + "\n", encoding="utf-8"
            )
            functional_sha = hashlib.sha256(
                functional_path.read_bytes()
            ).hexdigest().upper()
            policy = engineering_policy()
            policy["functional_acceptance"].update(
                {
                    "path": "common/multipole/"
                    "functional_transport_acceptance.json",
                    "sha256": functional_sha,
                }
            )
            policy_path.write_text(json.dumps(policy) + "\n", encoding="utf-8")

            contract, provenance = load_engineering_progression_contract(
                policy_path, functional_path
            )

            self.assertEqual(contract["claim_profile"], "engineering_progression")
            self.assertEqual(
                provenance["functional_contract"]["sha256"], functional_sha
            )
            self.assertEqual(
                provenance["policy"]["status"],
                "DRAFT_PENDING_ENERGY_THRESHOLDS",
            )

    def test_trusted_engineering_loader_rejects_path_or_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            functional_path = root / "functional.json"
            policy_path = root / "policy.json"
            functional = copy.deepcopy(CONTRACT)
            functional.update(
                {
                    "contract_id": "functional-test",
                    "claim_profile": "functional_transport",
                }
            )
            functional_path.write_text(json.dumps(functional), encoding="utf-8")
            policy = engineering_policy()
            policy["functional_acceptance"]["path"] = "other/functional.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "path differs"):
                load_engineering_progression_contract(
                    policy_path, functional_path
                )

            policy["functional_acceptance"]["path"] = "functional.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "binding is stale"):
                load_engineering_progression_contract(
                    policy_path, functional_path
                )

    def test_engineering_contract_preserves_mesh_strategy_prohibition(
        self,
    ) -> None:
        full_tetra = sample()
        hybrid = copy.deepcopy(full_tetra)
        hybrid["numerics"]["mesh"]["strategy"] = "hybrid"
        with self.assertRaisesRegex(
            ValueError, "cannot apply continuous difference limits"
        ):
            evaluate(
                full_tetra,
                hybrid,
                "mesh_strategy",
                engineering_contract(active=True),
            )


if __name__ == "__main__":
    unittest.main()
