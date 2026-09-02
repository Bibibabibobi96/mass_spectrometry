from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.validate_post_pulse_handoff_envelope import (
    validate_handoff_envelope,
)


class PostPulseHandoffEnvelopeTests(unittest.TestCase):
    @staticmethod
    def _contract(bounds: dict[str, float]) -> dict:
        return {"instance_bounds_mm": bounds}

    def test_accepts_states_covered_by_main_or_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "restart.csv"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["simulation_particle_id", "x_mm", "y_mm", "z_mm"],
                )
                writer.writeheader()
                writer.writerows((
                    {"simulation_particle_id": "1", "x_mm": "1", "y_mm": "0", "z_mm": "0"},
                    {"simulation_particle_id": "2", "x_mm": "11", "y_mm": "0", "z_mm": "0"},
                ))
            main = root / "main.json"
            local = root / "local.json"
            main.write_text(json.dumps(self._contract({"x_min": 0, "x_max": 10, "y_min": -1, "y_max": 1, "z_min": -1, "z_max": 1})), encoding="utf-8")
            local.write_text(json.dumps({"active_bounds_mm": {"x_min": 10, "x_max": 12, "y_min": -1, "y_max": 1, "z_min": -1, "z_max": 1}}), encoding="utf-8")
            receipt = validate_handoff_envelope(source, main, local)
        self.assertEqual(receipt["source_row_count"], 2)

    def test_rejects_a_state_requiring_an_omitted_upstream_pa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "restart.csv"
            source.write_text(
                "simulation_particle_id,x_mm,y_mm,z_mm\n1,20,0,0\n",
                encoding="utf-8",
            )
            main = root / "main.json"
            local = root / "local.json"
            bounds = {"x_min": 0, "x_max": 10, "y_min": -1, "y_max": 1, "z_min": -1, "z_max": 1}
            main.write_text(json.dumps(self._contract(bounds)), encoding="utf-8")
            local.write_text(json.dumps(self._contract(bounds)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "would omit restart states"):
                validate_handoff_envelope(source, main, local)

    def test_accepts_runnable_materialized_state_coordinate_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "initial_state.csv"
            source.write_text(
                "particle_id,position_x_mm,position_y_mm,position_z_mm\n"
                "46,1,0,0\n",
                encoding="utf-8",
            )
            main = root / "main.json"
            local = root / "local.json"
            bounds = {"x_min": 0, "x_max": 10, "y_min": -1, "y_max": 1, "z_min": -1, "z_max": 1}
            main.write_text(json.dumps(self._contract(bounds)), encoding="utf-8")
            local.write_text(json.dumps(self._contract(bounds)), encoding="utf-8")
            receipt = validate_handoff_envelope(source, main, local)
        self.assertEqual(receipt["source_row_count"], 1)
