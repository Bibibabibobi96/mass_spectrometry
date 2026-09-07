"""Unit checks for immutable pre-pulse-screening recovery setup."""

from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.recover_completed_pre_pulse_screening import (
    RECOVERY_MODE,
    _completed_trace_logs,
    _is_recoverable_stale_config,
    _recoverable_source_status,
    _validate_recovery_run_id,
    build_recovery_config,
)
from common.contracts.machine_contracts import ContractError


class RecoveryConfigurationTests(unittest.TestCase):
    def test_recovery_identifier_is_checked_before_large_materialization(self) -> None:
        _validate_recovery_run_id(
            Path("20260903_012000__analysis__python__rf-oatof-natural-recovery__n5000")
        )
        with self.assertRaisesRegex(ContractError, "recovery run_id is invalid"):
            _validate_recovery_run_id(Path("x" * 97))

    def test_accepts_checkpoint_only_as_a_candidate_for_completed_log_recovery(self) -> None:
        self.assertTrue(_recoverable_source_status("checkpoint"))
        self.assertTrue(_recoverable_source_status("failed"))
        self.assertTrue(_recoverable_source_status("interrupted"))
        self.assertFalse(_recoverable_source_status("success"))
        self.assertFalse(_recoverable_source_status(None))

    def test_prefers_current_trace_streams_over_legacy_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            logs = run_dir / "logs"
            logs.mkdir()
            legacy = logs / "simion__batch01.stdout.log"
            trace1 = logs / "simion__batch01.trace.log"
            trace2 = logs / "simion__batch02.trace.log"
            for path in (legacy, trace1, trace2):
                path.write_text("status,Fly completed.\n", encoding="utf-8")
            self.assertEqual(_completed_trace_logs(run_dir), [trace1, trace2])
            trace1.unlink()
            trace2.unlink()
            self.assertEqual(_completed_trace_logs(run_dir), [legacy])

    def test_allows_only_manifest_bound_stale_input_index_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "20260830_150004__sim__simion__fixture__n1"
            manifest = {
                "inputs": {
                    "pre_pulse_time_series_contract": {"sha256": "A" * 64},
                },
            }
            config = {
                "run_id": run_dir.name,
                "project": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
                "mode": "rf_to_oatof_simion_single_flight",
                "parameters": {
                    "execution_mode": "real_pa_rf_pre_pulse_time_series",
                    "pre_pulse_time_series_contract_sha256": "A" * 64,
                },
            }
            self.assertTrue(_is_recoverable_stale_config(
                manifest=manifest, config=config, run_dir=run_dir
            ))
            config["parameters"]["pre_pulse_time_series_contract_sha256"] = "B" * 64
            self.assertFalse(_is_recoverable_stale_config(
                manifest=manifest, config=config, run_dir=run_dir
            ))

    def test_binds_only_run_local_frozen_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            failed = Path(directory) / "failed"
            (failed / "inputs").mkdir(parents=True)
            (failed / "inputs" / "pre_pulse_time_series_screening_contract.json").write_text(
                json.dumps({"trace_policy": {
                    "mode": "natural_trajectory_compact_handoff_v1"
                }}),
                encoding="utf-8",
            )
            (failed / "inputs" / "single_flight_particle_row_map.csv").write_text("source_particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "single_flight_initial_global_state.csv").write_text("particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "mother_particle_source.csv").write_text("particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "resolved_source_contract.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "resolved_single_flight_pulse_schedule.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "oatof_resolved_geometry.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "simion_single_flight.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "resolved_population_contract.json").write_text(
                json.dumps({"experiment_id": "pre_pulse_fixture"}), encoding="utf-8"
            )
            config = build_recovery_config(
                failed_run_dir=failed,
                failed_config={
                    "project_root": str(Path(directory)),
                    "inputs": {"particle_row_map": "C:/short/alias.csv"},
                    "parameters": {"execution_mode": "real_pa_rf_pre_pulse_time_series"},
                },
                recovery_dir=Path(directory) / "20260825_174500__analysis__simion__recovery__n1",
            )
            self.assertEqual(config["mode"], RECOVERY_MODE)
            self.assertEqual(config["artifact_retention"]["class"], "compact")
            self.assertIsNone(config["artifact_retention"]["reason"])
            self.assertEqual(
                Path(config["inputs"]["pre_pulse_time_series_contract"]),
                Path(directory) / "20260825_174500__analysis__simion__recovery__n1"
                / "inputs" / "pre_pulse_time_series_screening_contract.json",
            )
            self.assertEqual(
                Path(config["inputs"]["particle_row_map"]),
                Path(directory) / "20260825_174500__analysis__simion__recovery__n1"
                / "inputs" / "single_flight_particle_row_map.csv",
            )
            self.assertTrue(Path(config["inputs"]["initial_global_state"]).is_file())
            self.assertEqual(config["experiment_id"], "pre_pulse_fixture")
            self.assertTrue(Path(config["inputs"]["resolved_population_contract"]).is_file())
            self.assertTrue(Path(config["inputs"]["mother_particle_source"]).is_file())
            self.assertTrue(Path(config["inputs"]["resolved_source_contract"]).is_file())
            self.assertTrue(Path(config["inputs"]["pulse_schedule"]).is_file())
            self.assertTrue(Path(config["inputs"]["oatof_resolved_geometry"]).is_file())
            self.assertTrue(Path(config["inputs"]["simion_single_flight"]).is_file())
            self.assertFalse(config["formal_gate_passed"])

    def test_recovery_marks_omitted_pa_roles_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = root / "failed"
            inputs = failed / "inputs"
            inputs.mkdir(parents=True)
            for name in (
                "pre_pulse_time_series_screening_contract.json",
                "single_flight_particle_row_map.csv",
                "single_flight_initial_global_state.csv",
                "mother_particle_source.csv",
                "resolved_source_contract.json",
                "resolved_single_flight_pulse_schedule.json",
                "oatof_resolved_geometry.json",
                "simion_single_flight.json",
            ):
                (inputs / name).write_text("{}\n", encoding="utf-8")
            (inputs / "resolved_population_contract.json").write_text(
                json.dumps({"experiment_id": "fixture"}), encoding="utf-8"
            )
            config = build_recovery_config(
                failed_run_dir=failed,
                failed_config={
                    "inputs": {},
                    "parameters": {
                        "execution_mode": "real_pa_rf_pre_pulse_time_series",
                        "pa_cache_dispositions": {
                            "accelerator_main": {"key": "A", "disposition": "formal"},
                            "flight_tube": {"key": None, "disposition": "formal"},
                        },
                    },
                },
                recovery_dir=root / "recovery",
            )
            dispositions = config["parameters"]["pa_cache_dispositions"]
            self.assertEqual(dispositions["accelerator_main"]["disposition"], "not_applicable")
            self.assertIsNone(dispositions["accelerator_main"]["key"])
            self.assertEqual(dispositions["flight_tube"]["disposition"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
