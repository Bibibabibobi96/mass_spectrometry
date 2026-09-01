from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_handoff_replay import (
    ROW_MAP_COLUMNS,
    STATE_COLUMNS,
    _parse_traces,
    compare,
)


class HandoffReplayComparisonTests(unittest.TestCase):
    def _write_map(self, path: Path, pairs: list[tuple[int, int]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(ROW_MAP_COLUMNS)
            writer.writerows(pairs)

    def _write_state(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATE_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for particle_id, x in ((1, -10.0), (2, -11.0)):
                writer.writerow({"particle_id": particle_id, "instrument_time_us": 5,
                    "mass_amu": 100, "charge_state": 1, "position_x_mm": x, "position_y_mm": 0, "position_z_mm": 1,
                    "velocity_x_m_s": 4000, "velocity_y_m_s": 0, "velocity_z_m_s": 20,
                    "kinetic_energy_eV": kinetic_energy_ev(100, 4000, 0, 20)})

    def _write_batch_plan(self, path: Path, counts: list[int]) -> None:
        offset = 0
        batches = []
        for index, count in enumerate(counts, start=1):
            batches.append({"index": index, "count": count,
                "particle_id_min": offset + 1, "particle_id_max": offset + count,
                "simion_particle_id_offset": offset})
            offset += count
        path.write_text(json.dumps({"role": "simion_single_wave_particle_batch_plan", "batches": batches}), encoding="utf-8")

    def _write_trace(self, path: Path, pairs: list[tuple[int, float]], *, terminal_instance: int = 3, simulation_offset: int = 0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for ion, x in pairs:
            lines.append(f"TRACE: source_release ion={ion} particle_id={simulation_offset + ion} instrument_time_us=5 x_mm={x} y_mm=0 z_mm=1 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0.02")
            lines.append(f"TRACE: handoff_pulse_on ion={ion} instrument_time_us=5 x_mm={x} y_mm=0 z_mm=1 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0.02")
            lines.append(f"TRACE: non_detector_splat ion={ion} instance={terminal_instance} t=6 x=0 y=0 z=0 zmax=1")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _validation(self, path: Path) -> None:
        path.write_text(json.dumps({"role": "canonical_pulse_restart_target_state_validation", "tolerances": {
            "position_rowwise_abs_tolerance_mm": 1e-9,
            "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
            "clock_abs_tolerance_us": 1e-9,
            "energy_abs_tolerance_eV": 5e-9,
        }}), encoding="utf-8")

    def test_pairs_producer_ids_and_passes_identical_restart_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous_map, restart_map, state, validation, continuous_plan, restart_plan = (root / name for name in ("continuous.csv", "restart.csv", "state.csv", "validation.json", "continuous-plan.json", "restart-plan.json"))
            continuous_trace, restart_trace = root / "continuous" / "simion__batch01.stdout.log", root / "restart" / "simion__batch01.stdout.log"
            self._write_map(continuous_map, [(1, 101), (2, 202)])
            self._write_map(restart_map, [(1, 101), (2, 202)])
            self._write_state(state); self._validation(validation); self._write_batch_plan(continuous_plan, [2]); self._write_batch_plan(restart_plan, [2])
            self._write_trace(continuous_trace, [(1, -10.0), (2, -11.0)])
            self._write_trace(restart_trace, [(1, -10.0), (2, -11.0)])
            result = compare([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["paired_identity"], "producer_particle_id")
        self.assertEqual(result["paired_producer_particle_count"], 2)
        self.assertEqual(result["restart_validation_contract"]["path"], str(validation))

    def test_fails_when_continuous_trace_omits_a_restart_producer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous_map, restart_map, state, validation, continuous_plan, restart_plan = (root / name for name in ("continuous.csv", "restart.csv", "state.csv", "validation.json", "continuous-plan.json", "restart-plan.json"))
            continuous_trace, restart_trace = root / "continuous" / "simion__batch01.stdout.log", root / "restart" / "simion__batch01.stdout.log"
            self._write_map(continuous_map, [(1, 101), (2, 202)]); self._write_map(restart_map, [(1, 101), (2, 202)])
            self._write_state(state); self._validation(validation); self._write_batch_plan(continuous_plan, [2]); self._write_batch_plan(restart_plan, [2])
            self._write_trace(continuous_trace, [(1, -10.0)]); self._write_trace(restart_trace, [(1, -10.0), (2, -11.0)])
            result = compare([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "continuous_pulse_trace_does_not_cover_restart_producer_set")

    def test_trace_parser_accepts_sparse_pulse_survivors_within_a_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "simion__batch01.stdout.log"
            self._write_trace(trace, [(2, -11.0)])
            pulse, terminal = _parse_traces(
                [trace], {1: 101, 2: 202},
                {1: {"index": 1, "count": 2, "particle_id_min": 1,
                     "particle_id_max": 2, "simion_particle_id_offset": 0}},
                clock_tolerance_us=1e-9,
            )
        self.assertEqual(set(pulse), {202})
        self.assertEqual(set(terminal), {202})

    def test_fails_when_terminal_categories_differ(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous_map, restart_map, state, validation, continuous_plan, restart_plan = (root / name for name in ("continuous.csv", "restart.csv", "state.csv", "validation.json", "continuous-plan.json", "restart-plan.json"))
            continuous_trace, restart_trace = root / "continuous" / "simion__batch01.stdout.log", root / "restart" / "simion__batch01.stdout.log"
            self._write_map(continuous_map, [(1, 101), (2, 202)]); self._write_map(restart_map, [(1, 101), (2, 202)])
            self._write_state(state); self._validation(validation); self._write_batch_plan(continuous_plan, [2]); self._write_batch_plan(restart_plan, [2])
            self._write_trace(continuous_trace, [(1, -10.0), (2, -11.0)])
            self._write_trace(restart_trace, [(1, -10.0), (2, -11.0)], terminal_instance=5)
            result = compare([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["terminal_category_mismatch_producer_particle_ids"], [101, 202])

    def test_maps_batch_local_ion_numbers_through_ordered_row_map_slices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous_map, restart_map, state, validation, continuous_plan, restart_plan = (root / name for name in ("continuous.csv", "restart.csv", "state.csv", "validation.json", "continuous-plan.json", "restart-plan.json"))
            continuous_one, continuous_two = root / "continuous" / "simion__batch01.stdout.log", root / "continuous" / "simion__batch02.stdout.log"
            restart_one, restart_two = root / "restart" / "simion__batch01.stdout.log", root / "restart" / "simion__batch02.stdout.log"
            self._write_map(continuous_map, [(1, 101), (2, 202)]); self._write_map(restart_map, [(1, 101), (2, 202)])
            self._write_state(state); self._validation(validation); self._write_batch_plan(continuous_plan, [1, 1]); self._write_batch_plan(restart_plan, [1, 1])
            self._write_trace(continuous_one, [(1, -10.0)]); self._write_trace(continuous_two, [(1, -11.0)], simulation_offset=1)
            self._write_trace(restart_one, [(1, -10.0)]); self._write_trace(restart_two, [(1, -11.0)], simulation_offset=1)
            result = compare([continuous_one, continuous_two], continuous_map, continuous_plan, [restart_one, restart_two], state, restart_map, restart_plan, validation)
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
