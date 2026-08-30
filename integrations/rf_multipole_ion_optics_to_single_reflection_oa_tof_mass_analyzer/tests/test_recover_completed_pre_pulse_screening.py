"""Unit checks for immutable pre-pulse-screening recovery setup."""

from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.recover_completed_pre_pulse_screening import (
    RECOVERY_MODE,
    _is_recoverable_stale_config,
    build_recovery_config,
)


class RecoveryConfigurationTests(unittest.TestCase):
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
            (failed / "inputs" / "pre_pulse_time_series_screening_contract.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "single_flight_particle_row_map.csv").write_text("source_particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "single_flight_initial_global_state.csv").write_text("particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "mother_particle_source.csv").write_text("particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "resolved_source_contract.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "resolved_single_flight_pulse_schedule.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "oatof_resolved_geometry.json").write_text("{}\n", encoding="utf-8")
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
            self.assertEqual(
                Path(config["inputs"]["pre_pulse_time_series_contract"]),
                failed / "inputs" / "pre_pulse_time_series_screening_contract.json",
            )
            self.assertEqual(
                Path(config["inputs"]["particle_row_map"]),
                failed / "inputs" / "single_flight_particle_row_map.csv",
            )
            self.assertTrue(Path(config["inputs"]["initial_global_state"]).is_file())
            self.assertEqual(config["experiment_id"], "pre_pulse_fixture")
            self.assertTrue(Path(config["inputs"]["resolved_population_contract"]).is_file())
            self.assertTrue(Path(config["inputs"]["mother_particle_source"]).is_file())
            self.assertTrue(Path(config["inputs"]["resolved_source_contract"]).is_file())
            self.assertTrue(Path(config["inputs"]["pulse_schedule"]).is_file())
            self.assertTrue(Path(config["inputs"]["oatof_resolved_geometry"]).is_file())
            self.assertFalse(config["formal_gate_passed"])


if __name__ == "__main__":
    unittest.main()
