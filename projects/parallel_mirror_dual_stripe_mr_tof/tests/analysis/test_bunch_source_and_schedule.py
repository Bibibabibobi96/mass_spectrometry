from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path

from common.contracts.particle_count_policy import validate_prefix_particle_sources
from common.ion_release.cylinder import generate_center_first_halton_cylinder_phase_space
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    bunch_identity,
    derive_bunch_pulse_schedule,
    deterministic_ideal_bunch_states,
    freeze_bunch_pulse_schedule_from_files,
    load_verified_bunch_source_receipt,
    materialize_bunch_source,
    materialize_bunch_source_from_definition,
    render_bunch_fly2,
    resolve_bunch_source_interval,
    solver_problem_identity_from_trial_receipt,
    source_cohort_identity,
    validate_fixed_global_pulse_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
)


def _states(count: int, mother: int = 1000):
    return deterministic_ideal_bunch_states(
        particle_count=count,
        mother_particle_count=mother,
        center_workbench_mm=(0.0, -55.0, -60.0),
        aperture_plane_axes=(0, 1),
        acceleration_axis=2,
        position_radius_mm=0.1,
        acceleration_axis_full_width_mm=0.2,
        kinetic_energy_center_ev=5.0,
        kinetic_energy_full_width_ev=0.1,
        nominal_direction_workbench=(0.0, 1.0, 0.0),
        angular_full_width_deg=0.2,
        mass_th=524.0,
        charge_e=1,
    )


PROJECT = Path(__file__).resolve().parents[2]
GEOMETRY_CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"
CANDIDATE_DEFINITION = PROJECT / "config" / "candidate_bunch_source_n100.json"


class BunchSourceAndScheduleTest(unittest.TestCase):
    @staticmethod
    def _write_provider_receipt(path: Path) -> Path:
        path.write_text(json.dumps({
            "schema_version": 1,
            "role": "orthogonal_accelerator_mrtof_runtime_receipt",
            "status": "published_read_only",
            "mrtof_projection": {"geometry": {
                "acceleration_direction": "-z",
                "repeller_to_exit_mm": 34.0,
                "release_position_in_gap_1_mm": 2.0,
            }},
        }), encoding="utf-8")
        return path

    def _definition(self) -> dict:
        return {
            "schema_version": 1,
            "role": "mrtof_ideal_bunch_source_definition",
            "status": "frozen",
            "source_profile_id": "full_mrtof_ideal_bunch_v1",
            "frame_id": "mrtof_workbench_v2",
            "particle_count": 100,
            "mother_particle_count": 1000,
            "center_workbench_mm": [0.0, -55.0, -60.0],
            "aperture_plane_axes": [0, 1],
            "acceleration_axis": 2,
            "position_radius_mm": 0.1,
            "acceleration_axis_full_width_mm": 0.2,
            "kinetic_energy_center_ev": 5.0,
            "kinetic_energy_full_width_ev": 0.1,
            "nominal_direction_workbench": [0.0, 1.0, 0.0],
            "angular_full_width_deg": 0.2,
            "mass_th": 524.0,
            "charge_e": 1,
            "common_time_of_birth_us": 0.0,
        }

    def test_solver_identity_rejects_removed_legacy_flight_switches(self) -> None:
        trial = {
            "selected_axial_energy_per_charge_v": 4000.0,
            "mirror_voltages_v": [0.0, 1000.0, 2000.0, 3000.0, 4100.0],
            "stripe_biases_v": [-25.0, 50.0],
            "prism_voltages_v": [190.0, -190.0],
            "accelerator_endpoint_voltages_v": [4000.0, 1000.0, 0.0],
            "accelerator_ring_voltages_v": [3500.0, 3000.0, 2500.0],
            "trajectory_profile": {"profile_id": "pilot", "maximum_step_us": 0.002},
            "inputs": {"reviewed_contract_sha256": "a" * 64},
            "continue_main_drift": True,
            "x_symmetry_plane_constraint": False,
        }
        with self.assertRaisesRegex(CandidateContractError, "complete 3-D flight scope"):
            solver_problem_identity_from_trial_receipt(trial)

    def test_bunch_sampler_projects_the_common_cylinder_phase_space(self) -> None:
        states = _states(100)
        common_samples = generate_center_first_halton_cylinder_phase_space(
            particle_count=100, center_mm=[0.0, -55.0, -60.0],
            transverse_axes=(0, 1), axis=2, radius_mm=0.1, height_mm=0.2,
            kinetic_energy_center_ev=5.0, kinetic_energy_full_width_ev=0.1,
            nominal_direction=[0.0, 1.0, 0.0], angular_full_width_deg=0.2,
        )
        self.assertEqual(
            [
                (state["particle_id"], state["position_workbench_mm"],
                 state["kinetic_energy_ev"], state["direction_workbench"])
                for state in states
            ],
            [
                (sample["particle_id"], sample["position_mm"],
                 sample["kinetic_energy_ev"], sample["direction"])
                for sample in common_samples
            ],
        )

    def test_n100_is_exact_mother_prefix_and_center_particle_is_nominal(self) -> None:
        n100 = _states(100)
        n1000 = _states(1000)
        self.assertEqual(n100, n1000[:100])
        self.assertEqual(n100[0]["position_workbench_mm"], [0.0, -55.0, -60.0])
        self.assertEqual(n100[0]["kinetic_energy_ev"], 5.0)
        self.assertEqual(n100[0]["direction_workbench"], [0.0, 1.0, 0.0])
        self.assertEqual([row["particle_id"] for row in n100], list(range(1, 101)))

    def test_source_identity_and_fly2_are_byte_stable(self) -> None:
        first = _states(100)
        second = _states(100)
        self.assertEqual(bunch_identity(first, 1000), bunch_identity(second, 1000))
        self.assertEqual(render_bunch_fly2(first), render_bunch_fly2(second))
        self.assertEqual(render_bunch_fly2(first).count("standard_beam {"), 100)
        self.assertNotIn("circle_distribution", render_bunch_fly2(first))

    def test_materialized_n100_csv_is_exact_prefix_of_n1000(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for count in (100, 1000):
                states = _states(count)
                table = root / f"n{count}.csv"
                receipt = materialize_bunch_source(
                    states=states, mother_particle_count=1000,
                    source_profile_id="full_mrtof_ideal_bunch_v1",
                    frame_id="mrtof_workbench_v2",
                    state_table_path=table, fly2_path=root / f"n{count}.fly2",
                    receipt_path=root / f"n{count}.json",
                )
                self.assertEqual(receipt["particle_count"], count)
                self.assertEqual(receipt["state_table"]["bytes"], table.stat().st_size)
                paths[count] = table
                self.assertEqual(
                    load_verified_bunch_source_receipt(root / f"n{count}.json")["particle_count"],
                    count,
                )
            validate_prefix_particle_sources(paths[100], paths[1000])

    def test_source_receipt_fails_closed_after_payload_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table, fly2, receipt_path = root / "source.csv", root / "source.fly2", root / "source.json"
            materialize_bunch_source(
                states=_states(100), mother_particle_count=1000,
                source_profile_id="full_mrtof_ideal_bunch_v1", frame_id="mrtof_workbench_v2",
                state_table_path=table, fly2_path=fly2, receipt_path=receipt_path,
            )
            fly2.write_text(fly2.read_text(encoding="utf-8") + "-- changed\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "fly2 identity changed"):
                load_verified_bunch_source_receipt(receipt_path)

    def test_complete_frozen_definition_is_the_only_source_materialization_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition_path = root / "definition.json"
            definition_path.write_text(
                json.dumps(self._definition()), encoding="utf-8"
            )
            receipt = materialize_bunch_source_from_definition(
                definition_path=definition_path,
                state_table_path=root / "source.csv",
                fly2_path=root / "source.fly2",
                receipt_path=root / "source.json",
            )
            self.assertEqual(receipt["particle_count"], 100)
            self.assertIn("definition", receipt)
            incomplete = self._definition()
            del incomplete["angular_full_width_deg"]
            definition_path.write_text(json.dumps(incomplete), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "angular_full_width_deg"):
                materialize_bunch_source_from_definition(
                    definition_path=definition_path,
                    state_table_path=root / "bad.csv",
                    fly2_path=root / "bad.fly2",
                    receipt_path=root / "bad.json",
                )

    def test_current_candidate_definition_matches_resolved_accelerator_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = self._write_provider_receipt(root / "provider.json")
            receipt = materialize_bunch_source_from_definition(
                definition_path=CANDIDATE_DEFINITION,
                geometry_contract_path=GEOMETRY_CONTRACT,
                accelerator_provider_receipt_path=provider,
                state_table_path=root / "source.csv",
                fly2_path=root / "source.fly2",
                receipt_path=root / "source.json",
            )
            contract = load_contract(GEOMETRY_CONTRACT)
            placement = derive_two_zone_placement(contract)
            definition = json.loads(CANDIDATE_DEFINITION.read_text(encoding="utf-8"))
            expected = [
                0.0,
                placement.focus_y_mm + definition["source_y_offset_mm"],
                34.0 - 2.0,
            ]
            self.assertEqual(
                definition["center_rule"], "resolved_provider_accelerator_release_position"
            )
            self.assertEqual(definition["source_y_offset_mm"], -1.71093484735312)
            self.assertEqual(
                definition["kinetic_energy_center_ev"], 4.961131691875479
            )
            self.assertEqual(definition["field_cache_dependency"], "none")
            self.assertEqual(definition["aperture_plane_axes"], [0, 2])
            self.assertEqual(definition["acceleration_axis"], 1)
            self.assertEqual(receipt["particle_count"], 1000)
            self.assertEqual(receipt["mother_particle_count"], 1000)
            self.assertEqual(receipt["geometry_contract"]["derived_center_workbench_mm"], expected)
            self.assertEqual(expected, [0.0, -46.71093484735312, 32.0])
            self.assertEqual(receipt["accelerator_provider_receipt"]["derived_release_z_mm"], 32.0)
            self.assertEqual(receipt["field_cache_dependency"], "none")
            self.assertEqual(receipt["common_time_of_birth_us"], 0.0)
            self.assertEqual(receipt["species"], {"mass_th": 524.0, "charge_e": 1})
            self.assertEqual(Path(receipt["state_table"]["path"]).read_text().count("\n"), 1001)
            self.assertEqual(Path(receipt["fly2"]["path"]).read_text().count("standard_beam {"), 1000)
            load_verified_bunch_source_receipt(root / "source.json")
            frozen_definition = root / "definition.json"
            frozen_definition.write_text(CANDIDATE_DEFINITION.read_text(encoding="utf-8"), encoding="utf-8")
            frozen_receipt = materialize_bunch_source_from_definition(
                definition_path=frozen_definition,
                geometry_contract_path=GEOMETRY_CONTRACT,
                accelerator_provider_receipt_path=provider,
                state_table_path=root / "bound.csv",
                fly2_path=root / "bound.fly2",
                receipt_path=root / "bound.json",
            )
            self.assertEqual(frozen_receipt["particle_count"], 1000)
            frozen_definition.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "definition identity changed"):
                load_verified_bunch_source_receipt(root / "bound.json")

    def test_schema4_definition_rejects_coupled_placement_or_wrong_frame(self) -> None:
        source = json.loads(CANDIDATE_DEFINITION.read_text(encoding="utf-8"))
        cases = (
            ("rule", lambda value: value.__setitem__("center_rule", "absolute"), "provider release position"),
            ("cache", lambda value: value.__setitem__("field_cache_dependency", "geometry"), "field-cache independent"),
            ("axis", lambda value: value["coordinate_semantics"].__setitem__("y", "wrong"), "identity project/workbench"),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                provider = self._write_provider_receipt(root / "provider.json")
                definition = json.loads(json.dumps(source))
                mutate(definition)
                path = root / "definition.json"
                path.write_text(json.dumps(definition), encoding="utf-8")
                with self.assertRaisesRegex(CandidateContractError, message):
                    materialize_bunch_source_from_definition(
                        definition_path=path,
                        geometry_contract_path=GEOMETRY_CONTRACT,
                        accelerator_provider_receipt_path=provider,
                        state_table_path=root / "source.csv",
                        fly2_path=root / "source.fly2",
                        receipt_path=root / "source.json",
                    )

    def test_file_schedule_binds_complete_cohort_and_solver_problem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_receipt_path = root / "source.json"
            materialize_bunch_source(
                states=_states(100), mother_particle_count=1000,
                source_profile_id="full_mrtof_ideal_bunch_v1",
                frame_id="mrtof_workbench_v2",
                state_table_path=root / "source.csv",
                fly2_path=root / "source.fly2",
                receipt_path=source_receipt_path,
            )
            source = load_verified_bunch_source_receipt(source_receipt_path)
            trial = {
                "source_particle_count": 100,
                "source_cohort": source_cohort_identity(source),
                "fly2_sha256": source["fly2"]["sha256"],
                "selected_axial_energy_per_charge_v": 4000.0,
                "mirror_voltages_v": [0.0, 100.0, 200.0, 300.0, 4500.0],
                "stripe_biases_v": [-25.0, 51.0],
                "prism_voltages_v": [177.0, -179.0],
                "accelerator_endpoint_voltages_v": [4000.0, 1000.0, 0.0],
                "accelerator_ring_voltages_v": [3500.0, 3000.0, 2500.0, 2000.0, 1500.0],
                "trajectory_profile": {"profile_id": "pilot", "maximum_step_us": 0.002},
                "inputs": {"reviewed_contract_sha256": "a" * 64},
                "flight_scope": "complete_three_dimensional_static_return",
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "accelerator_pulse": {
                    "mode": "static",
                    "qualification": "static_accelerator",
                    "fixed_global_time_applied": False,
                },
            }
            trial_path = root / "trial.json"
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            log_path = root / "pilot.log"
            log_path.write_text("".join(
                "MRTOF_EVENT accelerator_safe_exit "
                f"ion={particle_id} t_us={1.8 + particle_id * 1e-5:.12g} "
                "from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=-6 "
                "vx_mm_us=0 vy_mm_us=1 vz_mm_us=-10\n"
                for particle_id in range(1, 101)
            ), encoding="utf-8")
            schedule = freeze_bunch_pulse_schedule_from_files(
                source_receipt_path=source_receipt_path,
                pilot_log_path=log_path,
                pilot_trial_receipt_path=trial_path,
                guard_us=0.002,
                output_path=root / "schedule.json",
            )
            self.assertEqual(schedule["safe_exit_definition"]["event_count"], 100)
            self.assertEqual(schedule["source_cohort"], source_cohort_identity(source))
            self.assertIn("canonical_sha256", schedule["solver_problem_identity"])
            self.assertAlmostEqual(schedule["pulse_off_time_us"], 1.803)
            trial["accelerator_pulse"]["mode"] = "fixed_global_time"
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "static accelerator"):
                freeze_bunch_pulse_schedule_from_files(
                    source_receipt_path=source_receipt_path,
                    pilot_log_path=log_path,
                    pilot_trial_receipt_path=trial_path,
                    guard_us=0.002,
                    output_path=root / "invalid_schedule.json",
                )

    def test_file_schedule_accepts_verified_contiguous_source_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_receipt_path = root / "source.json"
            materialize_bunch_source(
                states=_states(100), mother_particle_count=1000,
                source_profile_id="interval_schedule_test",
                frame_id="mrtof_workbench_v2",
                state_table_path=root / "source.csv",
                fly2_path=root / "source.fly2",
                receipt_path=source_receipt_path,
            )
            interval = resolve_bunch_source_interval(
                receipt_path=source_receipt_path, particle_id_min=1, particle_id_max=25,
            )
            trial = {
                "source_particle_count": 25,
                "source_cohort": interval["source_cohort"],
                "source_selection": interval["source_cohort"]["selection"],
                "fly2_sha256": interval["fly2_sha256"],
                "selected_axial_energy_per_charge_v": 4000.0,
                "mirror_voltages_v": [0.0, 100.0, 200.0, 300.0, 4500.0],
                "stripe_biases_v": [-25.0, 51.0],
                "prism_voltages_v": [177.0, -179.0],
                "accelerator_endpoint_voltages_v": [4000.0, 1000.0, 0.0],
                "accelerator_ring_voltages_v": [3500.0, 3000.0, 2500.0, 2000.0, 1500.0],
                "trajectory_profile": {"profile_id": "pilot", "maximum_step_us": 0.002},
                "inputs": {"reviewed_contract_sha256": "a" * 64},
                "flight_scope": "complete_three_dimensional_static_return",
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "accelerator_pulse": {
                    "mode": "static", "qualification": "static_accelerator",
                    "fixed_global_time_applied": False,
                },
            }
            trial_path = root / "trial.json"
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            log_path = root / "pilot.log"
            log_path.write_text("".join(
                "MRTOF_EVENT accelerator_safe_exit "
                f"ion={particle_id} t_us={1.8 + particle_id * 1e-5:.12g} "
                "from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=-6 "
                "vx_mm_us=0 vy_mm_us=1 vz_mm_us=-10\n"
                for particle_id in range(1, 26)
            ), encoding="utf-8")
            schedule = freeze_bunch_pulse_schedule_from_files(
                source_receipt_path=source_receipt_path,
                pilot_log_path=log_path,
                pilot_trial_receipt_path=trial_path,
                guard_us=0.002,
                output_path=root / "schedule.json",
            )
            self.assertEqual(schedule["source_cohort"], interval["source_cohort"])
            self.assertEqual(schedule["safe_exit_definition"]["event_count"], 25)

    def test_file_schedule_accepts_explicit_complete_source_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_receipt_path = root / "source.json"
            materialize_bunch_source(
                states=_states(100), mother_particle_count=1000,
                source_profile_id="complete_interval_schedule_test",
                frame_id="mrtof_workbench_v2",
                state_table_path=root / "source.csv",
                fly2_path=root / "source.fly2",
                receipt_path=source_receipt_path,
            )
            interval = resolve_bunch_source_interval(
                receipt_path=source_receipt_path, particle_id_min=1, particle_id_max=100,
            )
            trial = {
                "source_particle_count": 100,
                "source_cohort": interval["source_cohort"],
                "source_selection": interval["source_cohort"]["selection"],
                "fly2_sha256": interval["fly2_sha256"],
                "selected_axial_energy_per_charge_v": 4000.0,
                "mirror_voltages_v": [0.0, 100.0, 200.0, 300.0, 4500.0],
                "stripe_biases_v": [-25.0, 51.0],
                "prism_voltages_v": [177.0, -179.0],
                "accelerator_endpoint_voltages_v": [4000.0, 1000.0, 0.0],
                "accelerator_ring_voltages_v": [3500.0, 3000.0, 2500.0, 2000.0, 1500.0],
                "trajectory_profile": {"profile_id": "pilot", "maximum_step_us": 0.002},
                "inputs": {"reviewed_contract_sha256": "a" * 64},
                "flight_scope": "complete_three_dimensional_static_return",
                "target_drift_period_ratio": 25.5,
                "target_half_oscillation_count": 51,
                "accelerator_pulse": {
                    "mode": "static", "qualification": "static_accelerator",
                    "fixed_global_time_applied": False,
                },
            }
            trial_path = root / "trial.json"
            trial_path.write_text(json.dumps(trial), encoding="utf-8")
            log_path = root / "pilot.log"
            log_path.write_text("".join(
                "MRTOF_EVENT accelerator_safe_exit "
                f"ion={particle_id} t_us={1.8 + particle_id * 1e-5:.12g} "
                "from_instance=3 to_instance=1 x_mm=0 y_mm=-55 z_mm=-6 "
                "vx_mm_us=0 vy_mm_us=1 vz_mm_us=-10\n"
                for particle_id in range(1, 101)
            ), encoding="utf-8")
            schedule = freeze_bunch_pulse_schedule_from_files(
                source_receipt_path=source_receipt_path,
                pilot_log_path=log_path,
                pilot_trial_receipt_path=trial_path,
                guard_us=0.002,
                output_path=root / "schedule.json",
            )
            self.assertEqual(schedule["source_cohort"], interval["source_cohort"])
            self.assertEqual(schedule["safe_exit_definition"]["event_count"], 100)

    def test_schedule_uses_last_unique_safe_exit_plus_explicit_guard(self) -> None:
        events = [
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.80,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -10.0},
            {"kind": "accelerator_safe_exit", "ion": 2, "t_us": 1.84,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -9.9},
        ]
        schedule = derive_bunch_pulse_schedule(
            events=events,
            expected_particle_ids=[1, 2],
            guard_us=0.002,
            pilot_maximum_step_us=0.002,
            source_cohort_identity={"particle_states_sha256": "a" * 64},
            solver_problem_identity={"geometry_sha256": "b" * 64},
        )
        self.assertEqual(schedule["schema_version"], 2)
        self.assertEqual(schedule["safe_exit_definition"]["last_safe_exit_particle_id"], 2)
        self.assertAlmostEqual(schedule["pulse_off_time_us"], 1.842)
        self.assertEqual(schedule["pulse_off_authority"], "cohort_last_safe_exit_plus_guard")
        self.assertAlmostEqual(schedule["minimum_pulse_off_time_us"], 1.842)

    def test_schedule_accepts_native_accelerator_slot(self) -> None:
        schedule = derive_bunch_pulse_schedule(
            events=[{
                "kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.8,
                "from_instance": 3, "to_instance": 1, "vz_mm_us": -10.0,
            }],
            expected_particle_ids=[1], guard_us=0.002,
            pilot_maximum_step_us=0.002,
            source_cohort_identity={"state": "x"},
            solver_problem_identity={"solver": "x"},
            accelerator_instance=3,
        )
        self.assertEqual(schedule["safe_exit_definition"]["from_instance"], 3)

    def test_schedule_accepts_one_later_common_time_and_rejects_an_early_one(self) -> None:
        events = [
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.80,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -10.0},
            {"kind": "accelerator_safe_exit", "ion": 2, "t_us": 1.84,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -9.9},
        ]
        arguments = {
            "events": events, "expected_particle_ids": [1, 2], "guard_us": 0.002,
            "pilot_maximum_step_us": 0.002,
            "source_cohort_identity": {"particle_states_sha256": "a" * 64},
            "solver_problem_identity": {"geometry_sha256": "b" * 64},
        }
        schedule = derive_bunch_pulse_schedule(**arguments, pulse_off_time_us=1.9)
        self.assertEqual(
            schedule["pulse_off_authority"],
            "caller_common_envelope_verified_against_this_cohort",
        )
        self.assertAlmostEqual(schedule["pulse_off_time_us"], 1.9)
        self.assertAlmostEqual(schedule["additional_common_envelope_margin_us"], 0.058)
        with self.assertRaisesRegex(CandidateContractError, "precedes"):
            derive_bunch_pulse_schedule(**arguments, pulse_off_time_us=1.841)

    def test_safe_exit_event_is_accepted_by_the_production_log_parser(self) -> None:
        line = (
            "MRTOF_EVENT accelerator_safe_exit ion=1 t_us=1.8 from_instance=3 "
            "to_instance=1 x_mm=0 y_mm=-55 z_mm=-6 vx_mm_us=0 "
            "vy_mm_us=1 vz_mm_us=-10"
        )
        event = parse_events(line)[0]
        self.assertEqual(event["kind"], "accelerator_safe_exit")
        self.assertEqual(event["from_instance"], 3.0)

    def test_schedule_rejects_missing_duplicate_wrong_direction_and_small_guard(self) -> None:
        valid = [
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.8,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -10.0},
        ]
        arguments = {
            "expected_particle_ids": [1],
            "guard_us": 0.002,
            "pilot_maximum_step_us": 0.002,
            "source_cohort_identity": {"state": "x"},
            "solver_problem_identity": {"solver": "x"},
        }
        with self.assertRaisesRegex(CandidateContractError, "exactly one"):
            derive_bunch_pulse_schedule(events=[], **arguments)
        with self.assertRaisesRegex(CandidateContractError, "exactly one"):
            derive_bunch_pulse_schedule(events=valid + valid, **arguments)
        wrong = [{**valid[0], "vz_mm_us": 1.0}]
        with self.assertRaisesRegex(CandidateContractError, "non-injection"):
            derive_bunch_pulse_schedule(events=wrong, **arguments)
        with self.assertRaisesRegex(CandidateContractError, "at least one"):
            derive_bunch_pulse_schedule(events=valid, **{**arguments, "guard_us": 0.001})

    def test_schedule_rejects_pre_exit_terminal(self) -> None:
        events = [
            {"kind": "terminal", "ion": 1, "t_us": 1.0},
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.8,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -10.0},
        ]
        with self.assertRaisesRegex(CandidateContractError, "terminated before"):
            derive_bunch_pulse_schedule(
                events=events, expected_particle_ids=[1], guard_us=0.002,
                pilot_maximum_step_us=0.002,
                source_cohort_identity={"state": "x"},
                solver_problem_identity={"solver": "x"},
            )

    def test_schedule_accepts_pilot_stop_at_the_safe_exit_timestamp(self) -> None:
        events = [
            {"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.8,
             "from_instance": 3, "to_instance": 1, "vz_mm_us": -10.0},
            {"kind": "splat", "ion": 1, "t_us": 1.8},
            {"kind": "terminal", "ion": 1, "t_us": 1.8},
        ]
        schedule = derive_bunch_pulse_schedule(
            events=events, expected_particle_ids=[1], guard_us=0.002,
            pilot_maximum_step_us=0.002,
            source_cohort_identity={"state": "x"},
            solver_problem_identity={"solver": "x"},
        )
        self.assertAlmostEqual(schedule["pulse_off_time_us"], 1.802)

    def test_declared_accelerator_instances_freeze_and_validate(self) -> None:
        for accelerator in (3,):
            with self.subTest(accelerator=accelerator):
                schedule = derive_bunch_pulse_schedule(
                    events=[{"kind": "accelerator_safe_exit", "ion": 1, "t_us": 1.8,
                             "from_instance": accelerator, "to_instance": 1, "vz_mm_us": -10.0}],
                    expected_particle_ids=[1], guard_us=0.002, pilot_maximum_step_us=0.002,
                    source_cohort_identity={"state": "x"}, solver_problem_identity={"solver": "x"},
                    accelerator_instance=accelerator,
                )
                self.assertEqual(schedule["safe_exit_definition"]["from_instance"], accelerator)
                args = {"expected_particle_ids": [1], "pulse_off_time_us": 1.802,
                        "time_tolerance_us": 1e-12, "accelerator_instance": accelerator}
                event = {"kind": "accelerator_global_pulse_applied", "ion": 1,
                         "t_us": 1.802, "scheduled_t_us": 1.802, "instance": 1.0,
                         "trigger": "fixed_global_time"}
                self.assertEqual(validate_fixed_global_pulse_events(events=[event], **args)["status"], "pass")
                with self.assertRaisesRegex(CandidateContractError, "remained in the accelerator"):
                    validate_fixed_global_pulse_events(events=[{**event, "instance": accelerator}], **args)
                for invalid in (None, -1, True, 1.5):
                    with self.assertRaisesRegex(CandidateContractError, "valid pulse-off instance"):
                        validate_fixed_global_pulse_events(events=[{**event, "instance": invalid}], **args)
                with self.assertRaisesRegex(CandidateContractError, "accelerator instance"):
                    validate_fixed_global_pulse_events(events=[event], **{**args, "accelerator_instance": 2})

    def test_fixed_global_pulse_requires_one_same_time_event_per_particle(self) -> None:
        events = [
            {"kind": "accelerator_global_pulse_applied", "ion": particle_id,
             "t_us": 1.842, "scheduled_t_us": 1.842, "instance": 1,
             "trigger": "fixed_global_time"}
            for particle_id in (1, 2)
        ]
        result = validate_fixed_global_pulse_events(
            events=events, expected_particle_ids=[1, 2], pulse_off_time_us=1.842,
            time_tolerance_us=1e-12,
        )
        self.assertEqual(result["event_count"], 2)
        with self.assertRaisesRegex(CandidateContractError, "exactly one"):
            validate_fixed_global_pulse_events(
                events=events[:1], expected_particle_ids=[1, 2], pulse_off_time_us=1.842,
                time_tolerance_us=1e-12,
            )
        with self.assertRaisesRegex(CandidateContractError, "remained in the accelerator"):
            validate_fixed_global_pulse_events(
                events=[{**event, "instance": 3} for event in events],
                expected_particle_ids=[1, 2], pulse_off_time_us=1.842,
                time_tolerance_us=1e-12,
            )


if __name__ == "__main__":
    unittest.main()
