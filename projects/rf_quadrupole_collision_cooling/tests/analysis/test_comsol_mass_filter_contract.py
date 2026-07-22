from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.multipole.paired_mass_scan import generate_paired_case_tables
from projects.rf_quadrupole_collision_cooling.analysis import analyze_comsol_mass_scan as module


PROJECT_ROOT = Path(__file__).parents[2]


class ComsolMassFilterContractTests(unittest.TestCase):
    def test_paired_case_tables_preserve_source_and_change_only_mass(self) -> None:
        source = PROJECT_ROOT / "config" / "particles" / "official_fixed_25.ion"
        source_rows = list(csv.reader(source.read_text(encoding="utf-8").splitlines()))
        with tempfile.TemporaryDirectory() as temporary:
            cases = generate_paired_case_tables(Path(source), Path(temporary), [96.0, 101.5, 106.0], 25)
            self.assertEqual(len(cases), 3)
            for case in cases:
                rows = list(csv.reader(Path(case["particle_table"]).read_text(encoding="utf-8").splitlines()))
                self.assertEqual(len(rows), 25)
                self.assertTrue(all(float(row[1]) == case["mass_Th"] for row in rows))
                self.assertEqual([row[:1] + row[2:] for row in rows], [row[:1] + row[2:] for row in source_rows])

    def test_comsol_functional_aggregate_uses_frozen_mass_contract(self) -> None:
        mode_path = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"
        baseline_path = PROJECT_ROOT / "config" / "baseline.json"
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        transmissions = [0.0, 0.2, 0.92, 1.0, 0.72, 0.24, 0.04]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for mass, transmission in zip(mode["solver_screen"]["paired_source_masses_Th"], transmissions):
                summary = root / f"mass_{mass:g}.json"
                summary.write_text(json.dumps({
                    "mode": "mass_filter_reference", "mass_Th": mass, "particles": 25,
                    "hits": round(25 * transmission), "transmission": transmission,
                }), encoding="utf-8")
                cases.append({"solver_summary": str(summary)})
            scan = root / "scan.json"
            scan.write_text(json.dumps({"cases": cases}), encoding="utf-8")
            response, metrics = module.analyze(scan, baseline_path, mode_path)
            self.assertEqual([row["mass_Th"] for row in response], mode["solver_screen"]["paired_source_masses_Th"])
            self.assertEqual(metrics["status"], "PASS")

    def test_matlab_builder_superposes_differential_and_static_fields(self) -> None:
        builder = (PROJECT_ROOT / "comsol" / "ms_rf_quadrupole_no_collision.m").read_text(encoding="utf-8")
        self.assertIn("'mass_filter_reference'", builder)
        self.assertIn("V_dc+V_rf*sin", builder)
        self.assertIn("Vdiff", builder)
        self.assertIn("Vstatic", builder)
        self.assertIn("-d(Vdiff,x))-d(Vstatic,x)", builder)
        self.assertIn("static_electrodes_V.detector", builder)


if __name__ == "__main__":
    unittest.main()
