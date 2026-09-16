from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import (
    materialize_batch_fly2,
    merge_rebased_event_logs,
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
from common.simion.resource_scheduler import plan_adaptive_followup, plan_simion_dispatch


class MrtofBatchFlightTest(unittest.TestCase):
    def test_materializes_one_contiguous_local_id_fly2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / "states.csv"
            table.write_text(
                "particle_id,tob_us,mass_th,charge_e,kinetic_energy_ev,x_mm,y_mm,z_mm,direction_x,direction_y,direction_z\n"
                + "\n".join(f"{i},0,100,1,5,{i},0,0,0,1,0" for i in range(1, 5)) + "\n",
                encoding="utf-8",
            )
            receipt = {
                "source_profile_id": "fixture", "frame_id": "fixture",
                "sampling_method": "fixture", "particle_count": 4,
                "mother_particle_count": 4, "prefix_rule": "fixture",
                "clock_basis": "fixture", "expected_particle_ids_sha256": "A" * 64,
                "particle_states_sha256": "B" * 64,
                "state_table": {"path": str(table)},
            }
            (root / "receipt.json").write_text("{}\n", encoding="utf-8")
            output = root / "batch.fly2"
            with patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight.load_verified_bunch_source_receipt",
                return_value=receipt,
            ):
                result = materialize_batch_fly2(
                    receipt_path=root / "receipt.json", particle_id_min=2,
                    particle_id_max=3, output_path=output,
                )
            self.assertEqual(result["simion_particle_id_offset"], 1)
            self.assertEqual(output.read_text(encoding="utf-8").count("standard_beam {"), 2)

    def test_resolves_original_ids_97_and_98_without_mutating_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / "states.csv"
            table.write_text(
                "particle_id,tob_us,mass_th,charge_e,kinetic_energy_ev,x_mm,y_mm,z_mm,direction_x,direction_y,direction_z\n"
                + "\n".join(f"{i},0,524,1,5,{i},0,0,0,1,0" for i in range(1, 101)) + "\n",
                encoding="utf-8",
            )
            receipt = {
                "source_profile_id": "fixture", "frame_id": "fixture",
                "sampling_method": "fixture", "particle_count": 100,
                "mother_particle_count": 1000, "prefix_rule": "fixture",
                "clock_basis": "fixture", "expected_particle_ids_sha256": "A" * 64,
                "particle_states_sha256": "B" * 64,
                "state_table": {"path": str(table)},
            }
            (root / "receipt.json").write_text("{}\n", encoding="utf-8")
            with patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight.load_verified_bunch_source_receipt",
                return_value=receipt,
            ):
                selected = resolve_bunch_source_interval(
                    receipt_path=root / "receipt.json",
                    particle_id_min=97, particle_id_max=98,
                )
            self.assertEqual(selected["particle_ids"], [97, 98])
            self.assertEqual(
                [state["position_workbench_mm"][0] for state in selected["states"]],
                [97.0, 98.0],
            )
            self.assertEqual(selected["fly2"].count("standard_beam {"), 2)
            self.assertEqual(
                selected["source_cohort"]["selection"]["particle_id_min"], 97,
            )

    def test_resolves_one_particle_as_a_contiguous_diagnostic_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / "states.csv"
            table.write_text(
                "particle_id,tob_us,mass_th,charge_e,kinetic_energy_ev,x_mm,y_mm,z_mm,direction_x,direction_y,direction_z\n"
                "1,0,524,1,5,0,-55,36,0,1,0\n",
                encoding="utf-8",
            )
            receipt = {
                "source_profile_id": "fixture", "frame_id": "fixture",
                "sampling_method": "fixture", "particle_count": 1,
                "mother_particle_count": 100, "prefix_rule": "fixture",
                "clock_basis": "fixture", "expected_particle_ids_sha256": "A" * 64,
                "particle_states_sha256": "B" * 64,
                "state_table": {"path": str(table)},
            }
            (root / "receipt.json").write_text("{}\n", encoding="utf-8")
            with patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight.load_verified_bunch_source_receipt",
                return_value=receipt,
            ):
                selected = resolve_bunch_source_interval(
                    receipt_path=root / "receipt.json",
                    particle_id_min=1, particle_id_max=1,
            )
            self.assertEqual(selected["particle_ids"], [1])
            self.assertEqual(len(selected["states"]), 1)
            self.assertEqual(selected["fly2"].count("standard_beam {"), 1)

    def test_merge_rebases_local_ids_and_keeps_one_global_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "a.log", root / "b.log"
            first.write_text(
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=1 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 turns=2 central_crossings=2\n"
                "status,Fly completed. 1 splats\n", encoding="utf-8",
            )
            second.write_text(
                "MRTOF_EVENT terminal ion=1 splat=1 t_us=2 x_mm=0 y_mm=0 z_mm=1 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1 turns=4 central_crossings=4\n"
                "MRTOF_EVENT terminal ion=2 splat=2 t_us=3 x_mm=0 y_mm=0 z_mm=2 vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1 turns=6 central_crossings=6\n"
                "status,Fly completed. 2 splats\n", encoding="utf-8",
            )
            output, receipt = root / "merged.log", root / "merge.json"
            result = merge_rebased_event_logs(
                batches=[(first, 0, 1), (second, 1, 2)], particle_count=3,
                output_path=output, receipt_path=receipt,
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("ion=3", text)
            self.assertEqual(text.count("status,Fly completed."), 1)
            self.assertTrue(result["all_batch_losses_retained"])

    def test_merge_can_preserve_a_non_one_based_diagnostic_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "batch.log"
            batch.write_text(
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=1 x_mm=0 y_mm=0 z_mm=-97 "
                "vx_mm_us=0 vy_mm_us=0 vz_mm_us=1 turns=51 central_crossings=51\n"
                "MRTOF_EVENT terminal ion=2 splat=1 t_us=2 x_mm=0 y_mm=0 z_mm=97 "
                "vx_mm_us=0 vy_mm_us=0 vz_mm_us=-1 turns=51 central_crossings=51\n"
                "status,Fly completed. 2 splats\n",
                encoding="utf-8",
            )
            output = root / "merged.log"
            result = merge_rebased_event_logs(
                batches=[(batch, 96, 2)], particle_count=2,
                particle_id_min=97, output_path=output,
                receipt_path=root / "receipt.json",
            )
            events = parse_events(output.read_text(encoding="utf-8"))
            self.assertEqual([event["ion"] for event in events], [97, 98])
            self.assertEqual(result["global_particle_ids"], [97, 98])

    def test_small_serial_and_parallel_event_receipts_are_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = (
                "MRTOF_EVENT terminal ion={ion} splat=-1 t_us={time} x_mm=0 y_mm=0 z_mm=0 "
                "vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 turns=2 central_crossings=2\n"
            )
            serial = root / "serial.log"
            serial.write_text("".join(event.format(ion=i, time=i) for i in range(1, 4)) +
                              "status,Fly completed. 3 splats\n", encoding="utf-8")
            first, second = root / "a.log", root / "b.log"
            first.write_text(event.format(ion=1, time=1) + "status,Fly completed. 1 splats\n", encoding="utf-8")
            second.write_text(event.format(ion=1, time=2) + event.format(ion=2, time=3) +
                              "status,Fly completed. 2 splats\n", encoding="utf-8")
            merged = root / "merged.log"
            merge_rebased_event_logs(
                batches=[(first, 0, 1), (second, 1, 2)], particle_count=3,
                output_path=merged, receipt_path=root / "receipt.json",
            )
            self.assertEqual(
                parse_events(serial.read_text(encoding="utf-8")),
                parse_events(merged.read_text(encoding="utf-8")),
            )

    def test_unknown_n100_dispatch_observes_the_first_ten_particles(self) -> None:
        plan = plan_simion_dispatch(
            {"solver": "SIMION", "field_kind": "electrostatic",
             "particle_count": 100, "independent_particles": True}, [],
            available_memory_bytes=32 * 1024**3,
            total_physical_memory_bytes=48 * 1024**3,
            logical_processors=12,
        )
        first = plan["waves"][0]["batches"][0]
        self.assertEqual(
            (first["count"], first["particle_id_min"], first["particle_id_max"]),
            (10, 1, 10),
        )
        replanned = plan_adaptive_followup(
            plan, 1024**3, observed_cpu_percent=10.0,
            available_memory_bytes=32 * 1024**3,
            total_physical_memory_bytes=48 * 1024**3,
            first_batch_completed=True,
        )
        self.assertEqual(replanned["waves"][0]["batches"][0], first)


if __name__ == "__main__":
    unittest.main()
