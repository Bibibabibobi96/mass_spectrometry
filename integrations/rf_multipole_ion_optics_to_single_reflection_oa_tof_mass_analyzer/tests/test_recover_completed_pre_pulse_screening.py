"""Unit checks for immutable pre-pulse-screening recovery setup."""

from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.recover_completed_pre_pulse_screening import (
    RECOVERY_MODE,
    build_recovery_config,
)


class RecoveryConfigurationTests(unittest.TestCase):
    def test_binds_only_run_local_frozen_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            failed = Path(directory) / "failed"
            (failed / "inputs").mkdir(parents=True)
            (failed / "inputs" / "pre_pulse_time_series_screening_contract.json").write_text("{}\n", encoding="utf-8")
            (failed / "inputs" / "single_flight_particle_row_map.csv").write_text("source_particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "single_flight_initial_global_state.csv").write_text("particle_id\n1\n", encoding="utf-8")
            (failed / "inputs" / "mother_particle_source.csv").write_text("particle_id\n1\n", encoding="utf-8")
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
            self.assertFalse(config["formal_gate_passed"])


if __name__ == "__main__":
    unittest.main()
