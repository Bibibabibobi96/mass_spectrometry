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
        source = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"
        source_rows = list(csv.reader(source.read_text(encoding="utf-8").splitlines()))
        with tempfile.TemporaryDirectory() as temporary:
            cases = generate_paired_case_tables(Path(source), Path(temporary), [96.0, 101.5, 106.0], 100)
            self.assertEqual(len(cases), 3)
            for case in cases:
                rows = list(csv.reader(Path(case["particle_table"]).read_text(encoding="utf-8").splitlines()))
                self.assertEqual(len(rows), 100)
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
                    "mode": "mass_filter_reference", "mass_Th": mass, "particles": 100,
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
        self.assertIn("runConfig.inputs,'resolved_design'", builder)
        self.assertIn("drive=resolved.drive", builder)
        self.assertIn("V_dc+V_rf*sin", builder)
        self.assertIn("Vdiff", builder)
        self.assertIn("Vstatic", builder)
        self.assertIn("-d(Vdiff,x))-axial_scale*d(Vstatic,x)", builder)
        self.assertIn("p.set('axial_scale','1')", builder)
        self.assertIn("staticElectrodes=resolved.static_electrodes_V", builder)

    def test_comsol_runners_freeze_the_governed_resolved_design(self) -> None:
        transport_runner = (PROJECT_ROOT / "tests" / "comsol" / "run_transport_candidate.ps1").read_text(
            encoding="utf-8"
        )
        mass_runner = (PROJECT_ROOT / "tests" / "comsol" / "run_mass_filter_candidate.ps1").read_text(
            encoding="utf-8"
        )
        for runner in (transport_runner, mass_runner):
            self.assertIn("resolved_design", runner)
            self.assertNotIn("resolve_family_operating_contract", runner)
            self.assertNotIn("family_operating_contract", runner)
        self.assertIn("--source-format ion11", transport_runner)
        self.assertIn("common.contracts.particle_state", transport_runner)

    def test_project_comsol_runner_and_builder_retain_only_specialized_modes(self) -> None:
        runner = (PROJECT_ROOT / "tests/comsol/run_transport_candidate.ps1").read_text(encoding="utf-8")
        builder = (PROJECT_ROOT / "comsol/ms_rf_quadrupole_no_collision.m").read_text(encoding="utf-8")
        for source in (runner, builder):
            self.assertNotIn("[ValidateSet('transport_no_collision'", source)
            self.assertNotIn("'axial_acceleration_reference'", source)
            self.assertNotIn("'endplate_acceleration_reference'", source)
        self.assertIn("'transport_interface_readiness'", runner)
        self.assertIn("'transport_interface_readiness'", builder)
        self.assertIn("'mass_filter_reference'", builder)


if __name__ == "__main__":
    unittest.main()
