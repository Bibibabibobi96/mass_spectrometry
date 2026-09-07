from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime import (
    scan_pre_pulse_trace_pulse_time as subject,
)


def _trace(*, particle_id: int, sample_index: int, x_mm: float) -> str:
    instrument_time_us = sample_index - 1
    return (
        "TRACE: pre_pulse_time_series_state "
        f"ion={particle_id} particle_id={particle_id} sample_index={sample_index} "
        f"instrument_time_us={instrument_time_us} "
        f"actual_instrument_time_us={instrument_time_us} "
        f"x_mm={x_mm} y_mm=2 z_mm=3 vx_mm_per_us=0.001 "
        "vy_mm_per_us=0.002 vz_mm_per_us=0.003 kinetic_energy_eV=1 "
        "survival_status=alive"
    )


def _terminal(particle_id: int) -> str:
    return (
        f"TRACE: pre_pulse_screening_terminal ion={particle_id} particle_id={particle_id} "
        "instrument_time_us=5 x_mm=10 y_mm=2 z_mm=3 "
        "vx_mm_per_us=0.001 vy_mm_per_us=0.002 vz_mm_per_us=0.003 "
        "terminal_reason=geometry_collision"
    )


def _with_ranking(selected: dict) -> dict:
    """Provide the selector's winning-score contract to the scanner fixture."""
    selected.update({
        "selection_order": subject.SELECTION_ORDER,
        "metric_population_basis": "pulse_eligible",
        "normalization_bounds": {
            axis: {"center_mm": 0.0, "full_width_mm": 20.0,
                   "minimum_mm": -10.0, "maximum_mm": 10.0}
            for axis in "xyz"
        },
    })
    selected["candidates_ranked"][0].update({
        "normalized_xyz_spread": dict.fromkeys("xyz", 0.0),
        "normalized_xyz_spread_norm": 0.0,
        "normalized_xyz_centroid": dict.fromkeys("xyz", 0.1),
        "normalized_xyz_centroid_distance": 3 ** 0.5 / 10,
    })
    return selected


class ScanPrePulseTracePulseTimeTests(unittest.TestCase):
    def _write_run(self, root: Path) -> Path:
        run_dir = root / "run"
        inputs, logs = run_dir / "inputs", run_dir / "logs"
        inputs.mkdir(parents=True)
        logs.mkdir()
        (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "run_config.json").write_text("{}", encoding="utf-8")
        (inputs / "pre_pulse_time_series_screening_contract.json").write_text(
            json.dumps({
                "schema_version": 7,
                "selection_order": subject.SELECTION_ORDER,
                "trace_policy": {
                    "mode": "natural_trajectory_compact_handoff_v1",
                    "terminal_event": "geometry_collision_v1",
                    "retention_class": "transient_scan_input",
                },
                "rf_time_grid": {"grid_origin_us": 0.0, "step_us": 1.0},
                "identities": {"spatial_window_profile_id": "source_window"},
            }), encoding="utf-8",
        )
        with (inputs / "single_flight_particle_row_map.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["simulation_particle_id", "source_particle_id"],
            )
            writer.writeheader()
            writer.writerows(
                {
                    "simulation_particle_id": value,
                    "source_particle_id": value,
                }
                for value in (1, 2)
            )
        (inputs / "oatof_resolved_geometry.json").write_text("{}", encoding="utf-8")
        (inputs / "simion_single_flight.json").write_text("{}", encoding="utf-8")
        (inputs / "resolved_single_flight_pulse_schedule.json").write_text(
            json.dumps({"pulse_effective_time_us": 1.5}), encoding="utf-8"
        )
        with (inputs / "single_flight_initial_global_state.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=["particle_id", "mass_amu", "charge_state"])
            writer.writeheader()
            writer.writerows({"particle_id": value, "mass_amu": "100", "charge_state": "1"} for value in (1, 2))
        (logs / "simion__batch01.trace.log").write_text(
            "\n".join((_trace(particle_id=1, sample_index=2, x_mm=10), _trace(particle_id=2, sample_index=2, x_mm=20), _terminal(1), _terminal(2), "Fly completed.")) + "\n",
            encoding="utf-8",
        )
        return run_dir

    def test_scan_extracts_selected_native_trace_state_as_atomic_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            handoff = run_dir / "results" / "handoff.csv"
            selected = {
                "selected_time_us": 2.0,
                "ballistic_seed_time_us": 1.5,
                "candidates_ranked": [{
                    "sample_index": 2, "alive_count": 2, "pulse_eligible_count": 1,
                    "transverse_bore_count": 1, "source_region_count": 1,
                    "_natural_id_masks": {"pulse_eligible_ids": 2},
                }],
            }
            with patch.object(subject, "_select_source_region_profile", return_value={}), patch.object(
                subject, "select_detector_blind_natural_archive_pulse_time", return_value=_with_ranking(selected)
            ):
                result = subject.scan(run_dir, handoff_output=handoff)
            self.assertEqual(result["pulse_eligible_particle_ids"], [2])
            with handoff.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["particle_id"] for row in rows], ["2"])
            self.assertEqual(rows[0]["position_x_mm"], "20")
            self.assertEqual(rows[0]["velocity_z_m_s"], "3")
            self.assertFalse(list(handoff.parent.glob(".handoff.csv.*.tmp")))

    def test_scan_repairs_one_sample_token_character_from_the_frozen_grid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            trace = run_dir / "logs" / "simion__batch01.trace.log"
            trace.write_text(
                trace.read_text(encoding="utf-8").replace(
                    "particle_id=1 sample_index=2 ",
                    "particle_id=1 sample_index== ",
                ),
                encoding="utf-8",
            )
            rows = list(subject._trace_rows(
                [trace], grid_origin_us=0.0, grid_step_us=1.0,
            ))
            self.assertEqual(rows[0]["sample_index"], "2")

    def test_scan_rejects_unparseable_state_trace_instead_of_skipping_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            trace = run_dir / "logs" / "simion__batch01.trace.log"
            trace.write_text(
                "TRACE: pre_pulse_time_series_state malformed\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(subject.ContractError, "malformed"):
                list(subject._trace_rows(
                    [trace], grid_origin_us=0.0, grid_step_us=1.0,
                ))

    def test_scan_writes_compact_provenance_without_a_full_state_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            handoff = run_dir / "results" / "handoff.csv"
            receipt_path = run_dir / "results" / "handoff_receipt.json"
            selected = {
                "selected_time_us": 2.0, "ballistic_seed_time_us": 1.5,
                "candidates_ranked": [{
                    "sample_index": 2, "alive_count": 2, "pulse_eligible_count": 1,
                    "transverse_bore_count": 1, "source_region_count": 1,
                    "_natural_id_masks": {"pulse_eligible_ids": 2},
                }],
            }
            with patch.object(subject, "_select_source_region_profile", return_value={}), patch.object(
                subject, "select_detector_blind_natural_archive_pulse_time", return_value=_with_ranking(selected)
            ):
                subject.scan(run_dir, handoff_output=handoff, receipt_output=receipt_path)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["selection"]["mother_population_count"], 2)
            self.assertEqual(receipt["selection"]["pulse_eligible_particle_ids"], [2])
            self.assertIs(receipt["selection"]["postselection_prohibited"], True)
            self.assertEqual(receipt["producer"]["transient_trace_log_count"], 1)
            self.assertNotIn("raw_trace_logs", receipt["producer"])
            self.assertEqual(receipt["pulse_target_state"]["particle_count"], 1)
            self.assertEqual(receipt["pulse_target_state"]["coordinate_frame"], "oatof_global_cartesian")
            self.assertEqual(receipt["role"], "rf_oatof_compact_pre_pulse_trace_handoff_receipt")
            self.assertEqual(receipt["selection"]["ranking"]["selection_order"], subject.SELECTION_ORDER)
            self.assertEqual(receipt["selection"]["ranking"]["metric_population_basis"], "pulse_eligible")
            self.assertEqual(receipt["selection"]["ranking"]["normalized_xyz_spread_norm"], 0.0)
            self.assertEqual(receipt["selection"]["pulse_population_partition"], {
                "not_observed_alive": 0, "alive_not_eligible": 1, "eligible": 1,
            })
            self.assertEqual(receipt["natural_terminal_census"]["terminal_particle_count"], 2)
            self.assertEqual(receipt["natural_terminal_census"]["by_reason"], {
                "geometry_collision": 2, "splat": 0, "outside_pa_termination": 0,
            })

    def test_terminal_only_recovery_is_complete_and_does_not_select_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.log"
            trace.write_text("\n".join((_terminal(102), _terminal(101), "Fly completed.")), encoding="utf-8")
            output = root / "terminal.csv"
            with patch.object(subject, "select_detector_blind_natural_archive_pulse_time", side_effect=AssertionError("must not select")):
                census = subject.extract_natural_terminal_states(
                    trace_paths=[trace], frozen_particle_ids=[101, 102], output_path=output,
                )
            self.assertTrue(census["complete"])
            self.assertEqual(census["mother_population_count"], 2)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["particle_id"] for row in rows], ["101", "102"])
            self.assertEqual(rows[0]["vz_mm_per_us"], "0.003")

    def test_pulse_population_partition_is_exclusive_and_rejects_invalid_counts(self) -> None:
        self.assertEqual(subject.pulse_population_partition(
            mother_count=5000, alive_count=20, eligible_count=10,
        ), {"not_observed_alive": 4980, "alive_not_eligible": 10, "eligible": 10})
        for mother, alive, eligible in ((2, 3, 1), (2, 1, 2), (2, 1, 0)):
            with self.subTest(counts=(mother, alive, eligible)), self.assertRaises(subject.ContractError):
                subject.pulse_population_partition(mother_count=mother, alive_count=alive, eligible_count=eligible)

    def test_terminal_only_preserves_unobserved_terminal_as_last_alive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace, output = root / "trace.log", root / "terminal.csv"
            trace.write_text("\n".join((_terminal(1), _trace(particle_id=2, sample_index=2, x_mm=20), "Fly completed.")), encoding="utf-8")
            census = subject.extract_natural_terminal_states(trace_paths=[trace], frozen_particle_ids=[1, 2], output_path=output)
            self.assertFalse(census["complete"])
            self.assertEqual(census["terminal_particle_count"], 1)
            self.assertEqual(census["unknown_terminal_count"], 1)
            self.assertEqual(census["accounted_particle_count"], 2)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[1]["state_kind"], "last_observed_alive")
            self.assertEqual(rows[1]["terminal_reason"], "unobserved_terminal")
            self.assertEqual(rows[1]["instrument_time_us"], "1")

    def test_native_outside_pa_termination_is_known_but_not_a_wall_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace, output = root / "trace.log", root / "terminal.csv"
            trace.write_text("\n".join((_terminal(1), _terminal(2).replace(
                "geometry_collision", "outside_pa_termination"), "Fly completed.")), encoding="utf-8")
            census = subject.extract_natural_terminal_states(trace_paths=[trace], frozen_particle_ids=[1, 2], output_path=output)
            self.assertTrue(census["complete"])
            self.assertEqual(census["unknown_terminal_count"], 0)
            self.assertEqual(census["terminal_particle_count"], 2)
            self.assertEqual(census["by_reason"], {
                "geometry_collision": 1, "splat": 0, "outside_pa_termination": 1,
            })
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[1]["state_kind"], "terminal")
            self.assertEqual(rows[1]["terminal_reason"], "outside_pa_termination")

    def test_terminal_only_rejects_incomplete_or_ambiguous_evidence(self) -> None:
        cases = {
            "missing": [_terminal(1)],
            "duplicate": [_terminal(1), _terminal(1), _terminal(2)],
            "unknown": [_terminal(1), _terminal(3)],
            "infinite": [_terminal(1).replace("x_mm=10", "x_mm=1e999"), _terminal(2)],
            "nan": [_terminal(1).replace("x_mm=10", "x_mm=NaN"), _terminal(2)],
            "window": [_terminal(1).replace("geometry_collision", "window_complete"), _terminal(2)],
        }
        for name, lines in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                trace, output = root / "trace.log", root / "terminal.csv"
                trace.write_text("\n".join([*lines, "Fly completed."]), encoding="utf-8")
                with self.assertRaises(subject.ContractError):
                    subject.extract_natural_terminal_states(trace_paths=[trace], frozen_particle_ids=[1, 2], output_path=output)
                self.assertFalse(output.exists())

    def test_scan_uses_source_particle_ids_not_run_local_simion_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            row_map = run_dir / "inputs" / "single_flight_particle_row_map.csv"
            row_map.write_text(
                "simulation_particle_id,source_particle_id\n1,101\n2,102\n",
                encoding="utf-8",
            )
            trace = run_dir / "logs" / "simion__batch01.trace.log"
            trace.write_text(
                "\n".join((
                    _trace(particle_id=101, sample_index=2, x_mm=10),
                    _trace(particle_id=102, sample_index=2, x_mm=20),
                    "Fly completed.",
                )) + "\n",
                encoding="utf-8",
            )
            selected = {
                "selected_time_us": 2.0, "ballistic_seed_time_us": 1.5,
                "candidates_ranked": [{
                    "sample_index": 2, "alive_count": 2, "pulse_eligible_count": 1,
                    "transverse_bore_count": 1, "source_region_count": 1,
                    "_natural_id_masks": {"pulse_eligible_ids": 2},
                }],
            }
            with patch.object(subject, "_select_source_region_profile", return_value={}), patch.object(
                subject, "select_detector_blind_natural_archive_pulse_time", return_value=_with_ranking(selected)
            ):
                result = subject.scan(run_dir)
            self.assertEqual(result["pulse_eligible_particle_ids"], [102])

    def test_scan_rejects_reselection_under_a_different_frozen_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            path = run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["selection_order"] = ["maximize_transverse_bore_count"]
            path.write_text(json.dumps(contract), encoding="utf-8")
            with patch.object(subject, "select_detector_blind_natural_archive_pulse_time") as selector:
                with self.assertRaisesRegex(subject.ContractError, "selection order differs"):
                    subject.scan(run_dir)
                selector.assert_not_called()

    def test_scan_rejects_missing_frozen_selection_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._write_run(Path(directory))
            path = run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            del contract["selection_order"]
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(subject.ContractError, "selection order differs"):
                subject.scan(run_dir)


if __name__ == "__main__":
    unittest.main()
