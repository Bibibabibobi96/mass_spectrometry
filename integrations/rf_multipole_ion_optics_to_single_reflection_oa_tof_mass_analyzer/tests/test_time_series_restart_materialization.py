from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import validate_schema
from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    CSV_COLUMNS,
    TIME_SERIES_RESTART_RECEIPT_ROLE,
    _validate_selected_time,
    materialize_manifest_bound_restart,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _validate_time_series_restart_state,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.materialize_time_series_restart import (
    _resolve_sample_index,
)


SCHEMA = Path(__file__).resolve().parents[1] / "config" / "schemas" / (
    "rf_oatof_manifest_bound_time_series_restart_materialization_receipt.schema.json"
)


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()), "exists": True, "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


class TimeSeriesRestartMaterializationTest(unittest.TestCase):
    def test_selection_receipt_derives_the_natural_archive_sample_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "selection.json"
            receipt.write_text(json.dumps({
                "candidates_ranked": [
                    {"rank": 2, "sample_index": 99},
                    {"rank": 1, "sample_index": 3579},
                ],
            }), encoding="utf-8")
            self.assertEqual(_resolve_sample_index(None, receipt), 3579)
            self.assertEqual(_resolve_sample_index(4, receipt), 4)

    def test_materializes_detector_blind_pulse_disabled_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "artifacts/projects/integration/runs/source"
            inputs, results = run / "inputs", run / "results"
            inputs.mkdir(parents=True)
            results.mkdir()
            initial = inputs / "initial.csv"
            with initial.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for particle_id in (1, 2):
                    writer.writerow({
                        "particle_id": particle_id, "instrument_time_us": "0",
                        "mass_amu": "100", "charge_state": "1",
                        "position_x_mm": "-80", "position_y_mm": "0", "position_z_mm": "0",
                        "velocity_x_m_s": "4000", "velocity_y_m_s": "0", "velocity_z_m_s": "0",
                        "kinetic_energy_eV": format(kinetic_energy_ev(100, 4000, 0, 0), ".17g"),
                    })
            schedule = inputs / "schedule.json"
            schedule.write_text('{"pulse_effective_time_us":50.0}\n', encoding="utf-8")
            population = inputs / "population.json"
            population.write_text(json.dumps({"execution_population": {"particle_count": 2}, "denominators": {"population_count": 2}}), encoding="utf-8")
            geometry = inputs / "geometry.json"
            geometry.write_text("{}\n", encoding="utf-8")
            states = results / "pre_pulse_time_series_states.csv.gz"
            with gzip.open(states, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
                writer.writeheader()
                writer.writerow({
                    "particle_id": 2, "event": "pre_pulse_time_series_state", "sample_index": 1,
                    "instrument_time_us": "50", "actual_instrument_time_us": "50",
                    "x_mm": "-70", "y_mm": "0", "z_mm": "1",
                    "vx_mm_per_us": "4", "vy_mm_per_us": "0", "vz_mm_per_us": "0.01",
                    "kinetic_energy_eV": format(kinetic_energy_ev(100, 4000, 0, 10), ".17g"),
                    "survival_status": "alive",
                })
            screening = results / "pre_pulse_time_series_screening_receipt.json"
            screening.write_text(json.dumps({
                "role": "rf_oatof_pre_pulse_time_series_screening_receipt", "status": "success",
                "pulse_disabled": True, "sample_times_us": [50.0],
                "terminal_census": {"window_complete": {"count": 1}, "splat": {"count": 1}},
            }), encoding="utf-8")
            summary = run / "summary.json"
            summary.write_text('{"status":"success"}\n', encoding="utf-8")
            config = run / "run_config.json"
            config.write_text(json.dumps({"parameters": {"execution_mode": "real_pa_rf_pre_pulse_time_series"}}), encoding="utf-8")
            manifest = run / "run_manifest.json"
            manifest.write_text(json.dumps({
                "role": "simulation_run_manifest", "run_id": "20260826_120000__sim__simion__fixture__n2",
                "project": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
                "mode": "rf_to_oatof_simion_single_flight", "status": "success", "run_config": _record(config),
                "inputs": {"initial_global_state": _record(initial), "pulse_schedule": _record(schedule), "resolved_population_contract": _record(population), "oatof_resolved_geometry": _record(geometry)},
                "outputs": [_record(states), _record(screening), _record(summary)],
            }), encoding="utf-8")
            state = root / "restart.csv"
            receipt = materialize_manifest_bound_restart(
                child_manifest_path=manifest, workspace_root=root,
                state_output_path=state, receipt_output_path=root / "receipt.json",
            )
            validate_schema(receipt, SCHEMA)
            validation = _validate_time_series_restart_state(
                state,
                root / "receipt.json",
                {
                    "sha256": _record(state)["sha256"],
                    "particle_count": 1,
                    "materialization_receipt": {"sha256": _record(root / "receipt.json")["sha256"]},
                    "position_rowwise_abs_tolerance_mm": 1e-9,
                    "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
                    "clock_abs_tolerance_us": 1e-9,
                    "energy_abs_tolerance_eV": 5e-9,
                },
                {"pulse_effective_time_us": 50.0},
            )
            with state.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(receipt["role"], TIME_SERIES_RESTART_RECEIPT_ROLE)
        self.assertEqual(validation["status"], "PASS")
        # A restart has a contiguous SIMION row ID while retaining the
        # producer particle identity separately for mother-cohort accounting.
        self.assertEqual(rows[0]["simulation_particle_id"], "1")
        self.assertEqual(rows[0]["source_particle_id"], "2")
        self.assertEqual(receipt["selection"]["producer_population_denominator_count"], 2)
        self.assertEqual(receipt["selection"]["restart_to_producer_particle_id"], [{"restart_particle_id": 1, "producer_particle_id": 2}])
        self.assertEqual(
            receipt["pulse_target_state"]["clock_authority"],
            "resolved_single_flight_pulse_schedule",
        )

    def test_requires_detector_blind_receipt_for_off_seed_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            states = root / "states.csv"
            screening = root / "screening.json"
            states.write_text("state\n", encoding="utf-8")
            screening.write_text("{}\n", encoding="utf-8")
            receipt_path = root / "selection.json"
            receipt_path.write_text(json.dumps({
                "role": "rf_oatof_detector_blind_real_field_pulse_timing_selection_receipt",
                "status": "success", "selection_uses_detector_outcome": False,
                "detector_results_used": False,
                "authorities": {
                    "real_field_state_table": {"sha256": _record(states)["sha256"]},
                    "pre_pulse_time_series_receipt": {"sha256": _record(screening)["sha256"]},
                },
                "selected_time_us": 60.0,
                "candidates_ranked": [{"sample_index": 2, "candidate_time_us": 60.0}],
            }))
            record = _validate_selected_time(
                selection_receipt_path=receipt_path, states_path=states,
                screening_receipt_path=screening, sample_index=2,
                sample_time_us=60.0, workspace_root=root,
            )
            self.assertEqual(record["sha256"], _record(receipt_path)["sha256"])
            with self.assertRaisesRegex(Exception, "does not bind restart sample"):
                _validate_selected_time(
                    selection_receipt_path=receipt_path, states_path=states,
                    screening_receipt_path=screening, sample_index=1,
                    sample_time_us=50.0, workspace_root=root,
                )


if __name__ == "__main__":
    unittest.main()
