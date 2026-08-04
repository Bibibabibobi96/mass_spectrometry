from __future__ import annotations

import json
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import build_extension
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import compile_frontend


REPO = Path(__file__).resolve().parents[3]


class SingleFlightProgramTests(unittest.TestCase):
    def test_frontend_electrode_schedule_keeps_rf_and_pulse_in_one_instance(self) -> None:
        run = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
        if not run.is_dir():
            self.skipTest("local N=1000 octupole source artifact is unavailable")
        upstream = json.loads((run / "inputs/multipole_resolved_design.json").read_text(encoding="utf-8-sig"))
        oatof = json.loads((REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text())
        connection = json.loads((REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260804_125500__sim__simion__oct-aperture100x090-interface__n459/inputs/resolved_connection.json").read_text(encoding="utf-8-sig"))
        _, frontend = compile_frontend(upstream, oatof, connection)
        extension = build_extension(upstream, frontend)
        self.assertIn("adj_elect[9]=3", extension)
        self.assertIn("adj_elect[10]=pulse_on and V_repeller", extension)
        self.assertIn("adj_elect[17]=0; adj_elect[18]=0", extension)
        self.assertIn("single_flight_handoff", extension)
        self.assertIn("single_flight_rf_steps=160", extension)


if __name__ == "__main__":
    unittest.main()
