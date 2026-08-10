from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.aggregate_single_flight_batches import (
    aggregate,
)


class AggregateSingleFlightBatchTests(unittest.TestCase):
    def test_legacy_absolute_clock_rows_receive_detector_birth_offset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_roots = []
            expected_batches = []
            for index in range(5):
                run = root / f"run{index}"
                (run / "inputs").mkdir(parents=True)
                (run / "results").mkdir()
                source = run / "inputs/mother_particle_source.csv"
                source.write_text(f"particle_id\n{index + 1}\n", encoding="utf-8")
                geometry = run / "inputs/oatof_resolved_geometry.json"
                geometry.write_text("{}\n", encoding="utf-8")
                birth = 0.1 * index
                with (run / "results/single_flight_particle_checkpoints.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerow(["particle_id", "event", "instrument_time_us"])
                    writer.writerow([1, "source_release", birth])
                    writer.writerow([1, "detector_crossing", 70.4 - birth + index * 1e-6])
                (run / "summary.json").write_text(
                    json.dumps({
                        "status": "success",
                        "census": {
                            "launched": 1,
                            "source_release": 1,
                            "multipole_handoff": 1,
                            "pre_pulse_state": 1,
                            "local_accelerator_exit": 1,
                            "detector_crossing": 1,
                        },
                        "pulse_first_observed_us": 40.0,
                        "pulse_capture": {
                            "counts": {
                                "eligible": 1,
                                "upstream_of_repeller": 0,
                                "downstream_of_grid1": 0,
                                "outside_transverse_bore": 0,
                                "missing_before_pulse": 0,
                            },
                            "detected_eligible_count": 1,
                        },
                    }),
                    encoding="utf-8",
                )
                (run / "run_config.json").write_text(
                    json.dumps({"parameters": {"clock_basis": "absolute_birth_time"}}),
                    encoding="utf-8",
                )
                run_roots.append(run)
                expected_batches.append({
                    "sha256": file_sha256(source),
                    "particle_count": 1,
                    "global_particle_id_offset": index,
                })
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "execution_batches": expected_batches,
                "execution_batch_count": 5,
                "physics_scope": {
                    "collisions_enabled": False,
                    "space_charge_enabled": False,
                },
            }), encoding="utf-8")
            result = aggregate(
                run_roots,
                receipt,
                root / "checkpoints.csv",
                root / "summary.json",
            )
        self.assertLess(result["instrument_clock_peak"]["std_tof_ns"], 0.002)
        self.assertEqual(result["detector_time_basis"], "instrument_time_us")


if __name__ == "__main__":
    unittest.main()
