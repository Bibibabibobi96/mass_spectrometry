from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_handoff_replay import (
    ROW_MAP_COLUMNS,
    STATE_COLUMNS,
    _parse_traces,
    compare,
)


class HandoffReplayComparisonTests(unittest.TestCase):
    def _compare(self, *args, **kwargs):
        root = args[1].parent
        for side in ("continuous", "restart"):
            checkpoints = root / f"{side}-checkpoints.csv"
            build = root / f"{side}-build.json"
            if not checkpoints.exists():
                checkpoints.write_text("particle_id,event,instrument_time_us,pulse_effective_elapsed_us,x_mm,y_mm,z_mm\n101,source_release,5,0,0,0,0\n202,source_release,5,0,0,0,0\n", encoding="utf-8")
            if not build.exists():
                build.write_text(json.dumps({"role": "rf_oatof_simion_single_flight_program_build", "instance_roles": {"flight_tube": 1, "reflectron": 2, "accelerator": 3, "detector": 4, "local": 5}}), encoding="utf-8")
            kwargs[f"{side}_checkpoints_path"] = checkpoints
            kwargs[f"{side}_program_build_path"] = build
        return compare(*args, **kwargs)

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
            lines.append(f"TRACE: source_release ion={ion} particle_id={(simulation_offset + ion) * 101} instrument_time_us=5 x_mm={x} y_mm=0 z_mm=1 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0.02")
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

    def _fixture(self, root: Path) -> tuple:
        continuous_map, restart_map, state, validation, continuous_plan, restart_plan = (root / name for name in ("continuous.csv", "restart.csv", "state.csv", "validation.json", "continuous-plan.json", "restart-plan.json"))
        continuous_trace, restart_trace = root / "continuous" / "simion__batch01.stdout.log", root / "restart" / "simion__batch01.stdout.log"
        for path in (continuous_map, restart_map):
            self._write_map(path, [(1, 101), (2, 202)])
        self._write_state(state)
        self._validation(validation)
        for path in (continuous_plan, restart_plan):
            self._write_batch_plan(path, [2])
        for path in (continuous_trace, restart_trace):
            self._write_trace(path, [(1, -10.0), (2, -11.0)])
        args = ([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
        self._compare(*args)
        return args

    def test_same_physical_role_different_slots_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            path = root / "continuous-build.json"
            data = json.loads(path.read_text())
            data["instance_roles"]["accelerator"] = 5
            data["instance_roles"]["local"] = 3
            path.write_text(json.dumps(data))
            self._write_trace(args[0][0], [(1, -10.0), (2, -11.0)], terminal_instance=5)
            self.assertEqual(self._compare(*args)["status"], "PASS")
            self._write_trace(args[0][0], [(1, -10.0), (2, -11.0)], terminal_instance=3)
            self.assertEqual(self._compare(*args)["status"], "FAIL")

    def test_detector_canonical_values_ignore_solver_epoch_and_report_differences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            header = "particle_id,event,instrument_time_us,pulse_effective_elapsed_us,x_mm,y_mm,z_mm\n"
            for side, trace, local_time in (("continuous", args[0][0], 15), ("restart", args[3][0], 10)):
                text = trace.read_text().replace("TRACE: non_detector_splat ion=1 instance=3 t=6 x=0 y=0 z=0 zmax=1", f"TRACE: detector_crossing ion=1 t={local_time} x=1 y=2 z=3 r=2 zmax=100")
                trace.write_text(text)
                (root / f"{side}-checkpoints.csv").write_text(header + "101,detector_crossing,15,10,1,2,3\n202,source_release,5,0,0,0,0\n")
            result = self._compare(*args)
            self.assertTrue(result["detector_comparison"]["paired_values_exactly_equal"])
            (root / "restart-checkpoints.csv").write_text(header + "101,detector_crossing,16,11,4,2,3\n202,source_release,5,0,0,0,0\n")
            result = self._compare(*args)
            errors = result["detector_comparison"]["paired_absolute_errors"][0]
            self.assertEqual(errors["pulse_effective_elapsed_us"], 1)
            self.assertEqual(errors["x_mm"], 3)
            self.assertFalse(result["detector_comparison"]["paired_values_exactly_equal"])
            self.assertIn("not_assessed", result["detector_comparison"]["trajectory_equivalence_qualification"])

    def test_missing_role_map_unknown_and_duplicate_checkpoint_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            path = root / "restart-checkpoints.csv"
            original = path.read_text()
            for invalid in (original + original.splitlines()[1] + "\n", original.replace("101,", "999,"), original.replace("source_release,5", "detector_crossing,nan"), "particle_id,event\n101,source_release\n"):
                path.write_text(invalid)
                self.assertEqual(self._compare(*args)["reason"], "invalid_comparison_input")
            path.write_text(original)
            (root / "restart-build.json").write_text("{}")
            self.assertEqual(self._compare(*args)["reason"], "invalid_comparison_input")

    def test_no_detector_is_not_evidence_of_trajectory_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self._fixture(Path(directory))
            result = self._compare(*args)
            self.assertIsNone(result["detector_comparison"]["paired_values_exactly_equal"])
            self.assertEqual(result["detector_comparison"]["paired_absolute_errors"], [])

    def test_current_compact_validation_reads_validation_bound_summary_tolerances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            validation = args[7]
            validation.write_text(json.dumps({
                "role": "canonical_pulse_restart_target_state_validation", "status": "PASS",
            }), encoding="utf-8")
            tolerances = {
                "position_rowwise_abs_tolerance_mm": 1e-9,
                "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
                "clock_abs_tolerance_us": 1e-9,
                "energy_abs_tolerance_eV": 5e-9,
            }
            summary = root / "restart-summary.json"
            summary.write_text(json.dumps({
                "role": "rf_oatof_simion_single_flight_summary", "status": "success",
                "pre_pulse_restart_source_release_validation": {
                    "status": "PASS", "validation_contract_sha256": file_sha256(validation),
                    **tolerances,
                },
            }), encoding="utf-8")
            result = self._compare(*args, restart_summary_path=summary)
            self.assertEqual(result["status"], "PASS")
            data = json.loads(summary.read_text())
            data["pre_pulse_restart_source_release_validation"]["validation_contract_sha256"] = "0" * 64
            summary.write_text(json.dumps(data))
            self.assertEqual(
                self._compare(*args, restart_summary_path=summary)["reason"],
                "invalid_comparison_input",
            )

    def test_timeout_splat_is_an_independent_terminal_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            for trace in (args[0][0], args[3][0]):
                trace.write_text(trace.read_text().replace(
                    "TRACE: non_detector_splat ion=1 instance=3 t=6 x=0 y=0 z=0 zmax=1",
                    "TRACE: timeout_splat ion=1 instance=3 instrument_time_us=90 x_mm=0 y_mm=0 z_mm=0 zmax_mm=1",
                ))
            result = self._compare(*args)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["terminal_category_match"])

    def test_continuous_detector_outside_restart_subset_is_not_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            self._write_map(args[1], [(1, 101), (2, 202), (3, 303)])
            self._write_batch_plan(args[2], [3])
            path = root / "continuous-checkpoints.csv"
            path.write_text(path.read_text() + "303,detector_crossing,15,10,1,2,3\n")
            result = self._compare(*args)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["detector_comparison"]["continuous_only_particle_ids"], [303])

    def test_checkpoint_terminal_disagreement_and_wrong_canonical_epoch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self._fixture(root)
            path = root / "restart-checkpoints.csv"
            path.write_text(path.read_text().replace("101,source_release,5,0", "101,detector_crossing,15,10"))
            self.assertEqual(self._compare(*args)["reason"], "invalid_comparison_input")
            trace = args[3][0]
            trace.write_text(trace.read_text().replace("TRACE: non_detector_splat ion=1 instance=3 t=6 x=0 y=0 z=0 zmax=1", "TRACE: detector_crossing ion=1 t=10 x=0 y=0 z=0 r=0 zmax=100"))
            path.write_text(path.read_text().replace("15,10", "16,10"))
            result = self._compare(*args)
            self.assertIn("pulse epoch", result["detail"])

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
            result = self._compare([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
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
            result = self._compare([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
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
                instance_roles={1: "flight_tube", 2: "reflectron", 3: "accelerator"},
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
            result = self._compare([continuous_trace], continuous_map, continuous_plan, [restart_trace], state, restart_map, restart_plan, validation)
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
            result = self._compare([continuous_one, continuous_two], continuous_map, continuous_plan, [restart_one, restart_two], state, restart_map, restart_plan, validation)
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
