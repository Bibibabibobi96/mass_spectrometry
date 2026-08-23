from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.ordered_pre_pulse_subset import materialize_ordered_pre_pulse_subset, ordered_subset_source_particle_ids, validate_ordered_pre_pulse_subset
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import materialize, materialize_ideal_linear_source, materialize_pre_pulse_restart, render_pre_pulse_fly2
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import _validate_canonical_pulse_restart_state


REPO = Path(__file__).resolve().parents[3]


class SingleFlightSourceTests(unittest.TestCase):
    def test_uniform_n100_selection_spans_the_full_n1000_mother_width(self) -> None:
        n1 = ordered_subset_source_particle_ids("n1_center_source_id_500_v1")
        prefix = ordered_subset_source_particle_ids(
            "n100_file_order_source_ids_1_to_100_v1"
        )
        full_width = ordered_subset_source_particle_ids(
            "n100_uniform_full_width_source_ids_1_to_1000_v1"
        )
        self.assertEqual(n1, [500])
        self.assertEqual(prefix, list(range(1, 101)))
        self.assertEqual(
            full_width,
            [1 + round(index * 999 / 99) for index in range(100)],
        )
        self.assertEqual(len(full_width), 100)
        self.assertEqual(len(set(full_width)), 100)
        self.assertTrue(all(left < right for left, right in zip(
            full_width, full_width[1:]
        )))
        self.assertEqual((full_width[0], full_width[-1]), (1, 1000))

        local_z_mm = [-1.1 + 2.2 * (source_id - 1) / 999 for source_id in full_width]
        self.assertAlmostEqual(local_z_mm[0], -1.1)
        self.assertAlmostEqual(local_z_mm[-1], 1.1)
        self.assertAlmostEqual(local_z_mm[-1] - local_z_mm[0], 2.2)

    def test_three_zone_n1_and_n100_are_frozen_subsets_of_one_n1000_mother(self) -> None:
        repeller_z_mm = -62.992615461549526
        source_center_from_repeller_mm = 1.498375640839315
        target_z_mm = repeller_z_mm + source_center_from_repeller_mm
        connection = {"spatial_registration": {
            "rotation_upstream_to_downstream": [
                [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
            ],
            "translation_mm": [-100.0, 0.0, -20.0],
        }}
        geometry = {"particle_source": {
            "center_x_mm": -50.0, "center_y_mm": 0.0,
            "center_z_mm": target_z_mm,
        }}
        schedule = {
            "entry_surface_x_mm": -80.0,
            "pulse_effective_time_us": 45.416793965641695,
        }
        profile = {
            "profile_id": "canonical_ideal_linear_z_vz_2p2mm_n1000",
            "source_profile_id": "canonical_ideal_linear_z_vz_2p2mm_n1000",
            "particle_count": 1000, "source_full_width_mm": 2.2,
            "mass_amu": 100.0, "charge_state": 1, "kinetic_energy_eV": 10.0,
            "mean_velocity_z_m_per_s": -2.9323518410018137,
            "velocity_z_slope_m_per_s_per_mm": 228.80604377795845,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mother_source = root / "mother.csv"
            mother_receipt = root / "mother_receipt.json"
            materialize_ideal_linear_source(
                root / "upstream.csv", mother_receipt, connection, geometry,
                schedule, profile, mother_source,
            )
            for name, source_ids in (
                ("n1", [500]),
                ("n100", list(range(1, 101))),
                (
                    "n100_full_width",
                    ordered_subset_source_particle_ids(
                        "n100_uniform_full_width_source_ids_1_to_1000_v1"
                    ),
                ),
            ):
                with self.subTest(name=name):
                    subset_source = root / f"{name}.csv"
                    subset_receipt_path = root / f"{name}_receipt.json"
                    receipt = materialize_ordered_pre_pulse_subset(
                        mother_source, mother_receipt,
                        subset_source, subset_receipt_path,
                        pulse_time_us=schedule["pulse_effective_time_us"],
                        ordered_source_particle_ids=source_ids,
                    )
                    validate_schema(
                        receipt,
                        "rf_oatof_pre_pulse_ordered_subset_receipt.schema.json",
                    )
                    rows = validate_ordered_pre_pulse_subset(
                        subset_source, receipt, mother_source, mother_receipt,
                        pulse_time_us=schedule["pulse_effective_time_us"],
                    )
                    validation = _validate_canonical_pulse_restart_state(
                        subset_source,
                        subset_receipt_path,
                        {
                            "sha256": file_sha256(subset_source),
                            "particle_count": len(source_ids),
                            "materialization_receipt": {
                                "sha256": file_sha256(subset_receipt_path),
                            },
                            "position_rowwise_abs_tolerance_mm": 1e-9,
                            "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
                            "clock_abs_tolerance_us": 1e-9,
                            "energy_abs_tolerance_eV": 5e-9,
                        },
                        profile,
                        geometry,
                        schedule,
                    )
                    self.assertEqual(len(rows), len(source_ids))
                    self.assertEqual(validation["particle_count"], len(source_ids))
                    self.assertEqual(
                        receipt["resolved_target_center_mm"][2], target_z_mm
                    )
                    self.assertEqual(receipt["physics"]["mass_amu"], 100.0)
                    self.assertEqual(
                        receipt["selection"]["ordered_source_particle_ids"],
                        source_ids,
                    )
                    if name == "n100_full_width":
                        selected_z_mm = [
                            float(row["position_z_mm"]) for row in rows
                        ]
                        self.assertAlmostEqual(
                            selected_z_mm[0], target_z_mm - 1.1
                        )
                        self.assertAlmostEqual(
                            selected_z_mm[-1], target_z_mm + 1.1
                        )
                        self.assertAlmostEqual(
                            selected_z_mm[-1] - selected_z_mm[0], 2.2
                        )

    def test_ordered_pre_pulse_subset_rejects_changed_global_z(self) -> None:
        connection = {"spatial_registration": {
            "rotation_upstream_to_downstream": [
                [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
            ],
            "translation_mm": [-100.0, 0.0, -20.0],
        }}
        geometry = {"particle_source": {
            "center_x_mm": -50.0, "center_y_mm": 0.0, "center_z_mm": -61.5,
        }}
        schedule = {"entry_surface_x_mm": -80.0, "pulse_effective_time_us": 40.0}
        profile = {
            "profile_id": "canonical_ideal_linear_z_vz_2p2mm_n1000",
            "source_profile_id": "canonical_ideal_linear_z_vz_2p2mm_n1000",
            "particle_count": 1000, "source_full_width_mm": 2.2,
            "mass_amu": 100.0, "charge_state": 1, "kinetic_energy_eV": 10.0,
            "mean_velocity_z_m_per_s": 0.0,
            "velocity_z_slope_m_per_s_per_mm": 100.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mother_source = root / "mother.csv"
            mother_receipt = root / "mother_receipt.json"
            subset_source = root / "n1.csv"
            materialize_ideal_linear_source(
                root / "upstream.csv", mother_receipt, connection, geometry,
                schedule, profile, mother_source,
            )
            receipt = materialize_ordered_pre_pulse_subset(
                mother_source, mother_receipt, subset_source,
                root / "n1_receipt.json", pulse_time_us=40.0,
                ordered_source_particle_ids=[500],
            )
            with subset_source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["position_z_mm"] = str(
                float(rows[0]["position_z_mm"]) + 1.0
            )
            with subset_source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(rows[0]), lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "file identity"):
                validate_ordered_pre_pulse_subset(
                    subset_source, receipt, mother_source, mother_receipt,
                    pulse_time_us=40.0,
                )

    def test_direct_velocity_fly2_preserves_component_signs(self) -> None:
        row = {
            "mass_amu": "100", "charge_state": "1",
            "position_x_mm": "-1", "position_y_mm": "2", "position_z_mm": "-3",
            "velocity_x_m_s": "-4000", "velocity_y_m_s": "250", "velocity_z_m_s": "-5",
        }
        fly2 = render_pre_pulse_fly2([row])
        self.assertIn("position = vector(-1, 2, -3)", fly2)
        self.assertIn("velocity = vector(-4, 0.25, -0.0050000000000000001)", fly2)
        self.assertNotIn("ke =", fly2)
        self.assertNotIn("direction =", fly2)

    def test_ideal_linear_source_is_materialized_from_layout_and_pulse(self) -> None:
        connection = {"spatial_registration": {
            "rotation_upstream_to_downstream": [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "translation_mm": [-100.0, 0.0, -20.0],
        }}
        geometry = {"particle_source": {
            "center_x_mm": -50.0, "center_y_mm": 0.0, "center_z_mm": -10.0,
        }}
        schedule = {"entry_surface_x_mm": -80.0, "pulse_effective_time_us": 40.0}
        profile = {
            "profile_id": "canonical_test", "source_profile_id": "canonical_test",
            "particle_count": 3, "source_full_width_mm": 2.2,
            "mass_amu": 100.0, "charge_state": 1, "kinetic_energy_eV": 10.0,
            "mean_velocity_z_m_per_s": 0.0,
            "velocity_z_slope_m_per_s_per_mm": 100.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            pulse_target = Path(directory) / "pulse_target.csv"
            receipt_path = Path(directory) / "receipt.json"
            receipt = materialize_ideal_linear_source(
                source, receipt_path, connection, geometry, schedule, profile,
                pulse_target,
            )
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with pulse_target.open(encoding="utf-8", newline="") as handle:
                pulse_rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        target_positions = [
            float(row["y_mm"]) - 20.0
            + float(row["vy_m_s"]) * 30.0 / float(row["vz_m_s"])
            for row in rows
        ]
        self.assertAlmostEqual(target_positions[-1] - target_positions[0], 2.2)
        self.assertEqual(receipt["particle_count"], 3)
        self.assertEqual(receipt["resolved_pulse_time_us"], 40.0)
        self.assertEqual([int(row["particle_id"]) for row in pulse_rows], [1, 2, 3])
        for actual, expected in zip(
            [float(row["position_z_mm"]) for row in pulse_rows],
            [-11.1, -10.0, -8.9],
        ):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(
            [float(row["velocity_z_m_s"]) for row in pulse_rows],
            [-110.0, 0.0, 110.0],
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertTrue(all(float(row["instrument_time_us"]) == 40.0 for row in pulse_rows))
        self.assertTrue(all(abs(float(row["kinetic_energy_eV"]) - 10.0) < 1e-12 for row in pulse_rows))
        self.assertEqual(
            receipt["pulse_target_state"]["source_state_epoch"],
            "pulse_effective_time",
        )
        self.assertEqual(
            receipt["pulse_target_state"]["source_state_locus"],
            {
                "kind": "accelerator_stage1_interior_fixed_transverse_finite_local_z_interval",
                "resolved_target_center_mm": [-50.0, 0.0, -10.0],
                "z_local_interval_mm": [-11.1, -8.9],
            },
        )
        self.assertEqual(receipt["pulse_target_state"]["coordinate_frame"], "oatof_global_cartesian")

        profile["particle_count"] = 1
        with tempfile.TemporaryDirectory() as directory:
            pulse_target = Path(directory) / "pulse_target.csv"
            materialize_ideal_linear_source(
                Path(directory) / "source.csv",
                Path(directory) / "receipt.json",
                connection,
                geometry,
                schedule,
                profile,
                pulse_target,
            )
            with pulse_target.open(encoding="utf-8", newline="") as handle:
                center_rows = list(csv.DictReader(handle))
        self.assertEqual(len(center_rows), 1)
        self.assertEqual(float(center_rows[0]["position_z_mm"]), -10.0)
        self.assertEqual(float(center_rows[0]["velocity_z_m_s"]), 0.0)
        self.assertEqual(receipt["pulse_target_state"]["clock_basis"], "canonical_instrument_time_us")
        self.assertEqual(receipt["pulse_target_state"]["clock_authority"], "resolved_single_flight_pulse_schedule")

    def test_real_n1000_continuous_source_separates_solver_and_absolute_birth(self) -> None:
        source = REPO / "common/multipole/sources/rf_oatof_short_focus_ideal_linear_z_vz_entry_n1000.csv"
        connection = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260813_170000__sim__simion__rf-oatof-single-flight-gap0__n1000/inputs/resolved_connection.json"
        if not source.is_file() or not connection.is_file():
            self.skipTest("N=1000 continuous source fixture is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            ion = Path(directory) / "source.ion"
            global_state = Path(directory) / "global.csv"
            completed = subprocess.run([
                sys.executable, "-m",
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source",
                "--source", str(source), "--connection", str(connection),
                "--particle-input", str(ion), "--global-state", str(global_state),
                "--source-release-mode", "continuous_frontend",
            ], cwd=REPO, text=True, capture_output=True, timeout=300)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            ion_rows = ion.read_text(encoding="utf-8").splitlines()
            with global_state.open(encoding="utf-8", newline="") as handle:
                global_rows = list(csv.DictReader(handle))
        self.assertEqual(len(ion_rows), 1000)
        self.assertTrue(all(row.split(",", 1)[0] == "0" for row in ion_rows))
        self.assertEqual(len(global_rows), 1000)
        self.assertGreater(float(global_rows[0]["instrument_time_us"]), 41.0)
        self.assertLess(float(global_rows[0]["instrument_time_us"]), 41.1)

    def test_rejects_removed_legacy_clock_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            completed = subprocess.run([
                sys.executable, "-m",
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source",
                "--source", str(target / "source.csv"),
                "--connection", str(target / "connection.json"),
                "--particle-input", str(target / "source.ion"),
                "--global-state", str(target / "global.csv"),
                "--clock-basis", "legacy_relative_time",
            ], cwd=REPO, text=True, capture_output=True, timeout=300)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("unrecognized arguments", completed.stderr)

    def test_attribution_prepulse_state_is_read_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.csv"
            source.write_text(
                "simulation_particle_id,source_particle_id,arm_id,instrument_time_us,mass_amu,charge_state,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,kinetic_energy_eV\n"
                "1,7,ideal,45.5585544411,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            fly2, rows = materialize_pre_pulse_restart(source, 45.5585544411)
        self.assertEqual(fly2.count("standard_beam"), 1)
        self.assertEqual(rows[0]["particle_id"], "1")
        self.assertEqual(list(rows[0]), ["particle_id", "instrument_time_us", "mass_amu", "charge_state", "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV"])
        self.assertIn("coordinates = 0", fly2)
        self.assertIn("velocity = vector(4.3928426367593296, 0, 0)", fly2)
        self.assertNotIn("ke =", fly2)
        self.assertNotIn("direction =", fly2)
        self.assertEqual(rows[0]["instrument_time_us"], "45.5585544411")

    def test_real_n835_attribution_source_writes_both_outputs(self) -> None:
        source = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260812_210000__sim__simion__rf-oatof-terminal-analytic-ideal-boundary-step__n1000__r01/inputs/counterfactual_arms/current_layout_ideal_1mm_linear_z_vz__source_state.csv"
        if not source.is_file():
            self.skipTest("historical N=835 attribution source is unavailable")
        connection = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/connection_profiles.json"
        with tempfile.TemporaryDirectory() as directory:
            ion = Path(directory) / "source.fly2"
            global_state = Path(directory) / "global.csv"
            completed = subprocess.run([sys.executable, "-m", "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source", "--source", str(source), "--connection", str(connection), "--particle-input", str(ion), "--global-state", str(global_state), "--source-release-mode", "pre_pulse_restart", "--pulse-time-us", "45.5585544411"], cwd=REPO, text=True, capture_output=True, timeout=300)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            fly2 = ion.read_text(encoding="utf-8")
            self.assertEqual(fly2.count("standard_beam"), 835)
            self.assertNotIn("ke =", fly2)
            self.assertNotIn("direction =", fly2)
            with global_state.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                output_rows = list(reader)
            self.assertEqual(reader.fieldnames, ["particle_id", "instrument_time_us", "mass_amu", "charge_state", "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV"])
            self.assertEqual(len(output_rows), 835)
            self.assertEqual((output_rows[0]["particle_id"], output_rows[-1]["particle_id"]), ("1", "835"))
            self.assertTrue(all(row["instrument_time_us"] == "45.5585544411" for row in output_rows))

    def test_maps_all_n1000_particles_without_handoff_filtering(self) -> None:
        run = (
            REPO.parent
            / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
        )
        if not run.is_dir():
            self.skipTest("local N=1000 octupole source artifact is unavailable")
        connection = json.loads(
            (
                REPO.parent
                / "artifacts/projects/rf_octupole_ion_optics/runs"
                / "20260804_125500__sim__simion__oct-aperture100x090-interface__n459"
                / "inputs/resolved_connection.json"
            ).read_text(encoding="utf-8-sig")
        )
        ion, states = materialize(run / "inputs/particle_source.csv", connection)
        self.assertEqual(len(ion), 1000)
        self.assertEqual(len(states), 1000)
        first = states[0]
        self.assertAlmostEqual(float(first["position_x_mm"]), -149.9)
        self.assertAlmostEqual(float(first["position_y_mm"]), -0.08166000357342909)
        self.assertAlmostEqual(float(first["position_z_mm"]), -18.32170905524317)
        self.assertAlmostEqual(float(first["velocity_x_m_s"]), 1959.568200662977)
        self.assertAlmostEqual(float(first["velocity_y_m_s"]), -105.35913222607861)
        self.assertAlmostEqual(float(first["velocity_z_m_s"]), -91.67991313892833)
        self.assertEqual(len(ion[0]), 11)

    def test_rejects_noncontiguous_particle_ids(self) -> None:
        connection = {
            "spatial_registration": {
                "rotation_upstream_to_downstream": [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "translation_mm": [0.0, 0.0, 0.0],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(["particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state"])
                writer.writerow([2, 0, 0, 0, 0, 0, 0, 1, 100, 1])
            with self.assertRaisesRegex(ValueError, "contiguous"):
                materialize(path, connection)


if __name__ == "__main__":
    unittest.main()
