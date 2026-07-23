from __future__ import annotations

import json
import copy
import tempfile
import unittest
from pathlib import Path

from common.multipole.family_contract import (
    VoltageDrive,
    electrode_group_voltages,
    from_high_order_baseline,
    from_quadrupole_contract,
    load_family_contract,
)
from common.multipole.mass_response import aggregate_response, evaluate_functional_contrast, load_terminal_statuses
from common.multipole.ideal_transport import source_particles
from common.multipole.paired_mass_scan import build_paired_ion_rows
from common.multipole.verify_family_foundation import validate_family_foundation


REPO_ROOT = Path(__file__).parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MultipoleFamilyContractTests(unittest.TestCase):
    def test_frozen_family_foundation_gate(self) -> None:
        validate_family_foundation()

    def test_high_order_n100_source_is_n1000_prefix(self) -> None:
        baseline = load_json(REPO_ROOT / "projects" / "rf_hexapole_ion_guide" / "config" / "baseline.json")
        statistical = copy.deepcopy(baseline)
        statistical["particle_source"]["count"] = 1000
        self.assertEqual(source_particles(baseline), source_particles(statistical)[:100])

    def test_obsolete_family_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "family.json"
            path.write_text('{"schema_version": 1, "role": "rf_multipole_family_contract"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema or role differs"):
                load_family_contract(path)

    def test_three_projects_share_one_family_identity(self) -> None:
        hexapole = from_high_order_baseline(
            load_json(REPO_ROOT / "projects" / "rf_hexapole_ion_guide" / "config" / "baseline.json")
        )
        octupole = from_high_order_baseline(
            load_json(REPO_ROOT / "projects" / "rf_octupole_ion_guide" / "config" / "baseline.json")
        )
        quad_root = REPO_ROOT / "projects" / "rf_quadrupole_collision_cooling" / "config"
        quadrupole = from_quadrupole_contract(
            load_json(quad_root / "baseline.json"),
            load_json(quad_root / "modes" / "mass_filter_reference.json"),
        )
        self.assertEqual(
            {hexapole.identity.family_id, octupole.identity.family_id, quadrupole.identity.family_id},
            {"rf_multipole_ion_optics"},
        )
        self.assertEqual(
            [quadrupole.identity.radial_order_n, hexapole.identity.radial_order_n, octupole.identity.radial_order_n],
            [2, 3, 4],
        )
        self.assertEqual({hexapole.geometry.r0_mm, octupole.geometry.r0_mm, quadrupole.geometry.r0_mm}, {4.0})

    def test_rf_dc_group_voltage_semantics_are_shared(self) -> None:
        root = REPO_ROOT / "projects" / "rf_quadrupole_collision_cooling" / "config"
        operating = from_quadrupole_contract(
            load_json(root / "baseline.json"), load_json(root / "modes" / "mass_filter_reference.json")
        )
        positive, negative = electrode_group_voltages(operating.voltage, 0.0)
        self.assertAlmostEqual(positive, 14.763014939677756)
        self.assertAlmostEqual(negative, -30.763014939677756)
        self.assertAlmostEqual(positive - negative, 45.52602987935551)

    def test_interface_mode_requires_and_records_explicit_rf_binding(self) -> None:
        root = REPO_ROOT / "projects" / "rf_quadrupole_collision_cooling" / "config"
        baseline = load_json(root / "baseline.json")
        mode = load_json(root / "modes" / "transport_interface_readiness.json")
        with self.assertRaisesRegex(ValueError, "explicit per-run RF amplitude"):
            from_quadrupole_contract(baseline, mode)
        operating = from_quadrupole_contract(baseline, mode, rf_amplitude_v_per_group=140.0)
        self.assertEqual(operating.voltage.rf_amplitude_v_per_group, 140.0)
        self.assertEqual(operating.voltage.frequency_hz, 1.1e6)
        self.assertEqual(operating.voltage.dc_amplitude_v_per_group, 0.0)

    def test_explicit_run_binding_overrides_embedded_rf_values(self) -> None:
        root = REPO_ROOT / "projects" / "rf_quadrupole_collision_cooling" / "config"
        operating = from_quadrupole_contract(
            load_json(root / "baseline.json"),
            load_json(root / "modes" / "transport_no_collision.json"),
            rf_amplitude_v_per_group=141.0,
            frequency_hz=1.2e6,
        )
        self.assertEqual(operating.voltage.rf_amplitude_v_per_group, 141.0)
        self.assertEqual(operating.voltage.frequency_hz, 1.2e6)

    def test_waveform_phase_dc_and_common_mode_are_all_executed(self) -> None:
        drive = VoltageDrive("cosine", 10.0, 2.0, -3.0, 1.0, 0.0)
        self.assertEqual(electrode_group_voltages(drive, 0.0), (9.0, -15.0))
        solver = (REPO_ROOT / "common" / "multipole" / "solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        for token in ("V_dc", "V_axis", "phi_rf", "rf.waveform", "Vdiff", "Vstatic"):
            self.assertIn(token, solver)

    def test_all_acceleration_modes_use_separate_static_solutions(self) -> None:
        shared_solver = (
            REPO_ROOT / "common" / "multipole" / "solve_finite_3d_transport.m"
        ).read_text(encoding="utf-8")
        quadrupole_solver = (
            REPO_ROOT
            / "projects"
            / "rf_quadrupole_collision_cooling"
            / "comsol"
            / "ms_rf_quadrupole_no_collision.m"
        ).read_text(encoding="utf-8")
        self.assertIn("if accelerationEnabled\n        studyDiff=", shared_solver)
        self.assertIn("if accelerationEnabled\n        force.set('E'", shared_solver)
        self.assertNotIn("withsol(", quadrupole_solver)
        self.assertNotIn("axial_acceleration_reference", quadrupole_solver)
        self.assertNotIn("endplate_acceleration_reference", quadrupole_solver)
        self.assertIn("withsol(", shared_solver)
        self.assertIn("configure_comsol_stationary_direct_solver", shared_solver)
        self.assertIn("if isfinite(workingHmax) && workingHmax>0", shared_solver)

    def test_comsol_run_freezes_executed_matlab_sources(self) -> None:
        runner = (REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        self.assertIn("$multipoleCodeDir=Join-Path $inputDir 'code\\multipole'", runner)
        self.assertIn("$task = Join-Path $multipoleCodeDir 'solve_finite_3d_transport.m'", runner)
        self.assertIn("comsol_connector_builder = Join-Path $multipoleCodeDir", runner)
        self.assertIn("comsol_mesh_size_builder = Join-Path $comsolCodeDir", runner)


class MultipoleMassResponseTests(unittest.TestCase):
    def test_paired_rows_change_only_mass(self) -> None:
        source = [["0", "100", "1", "0", "0.1", "0.2", "0", "0", "2", "1", "3"]]
        rows = build_paired_ion_rows(source, [90.0, 100.0, 110.0])
        self.assertEqual([float(row[1]) for row in rows], [90.0, 100.0, 110.0])
        self.assertEqual(rows[0][2:], rows[1][2:])

    def test_generic_functional_contrast(self) -> None:
        response = aggregate_response(
            {1: 90.0, 2: 100.0, 3: 110.0},
            {1: "lost", 2: "transmitted", 3: "lost"},
        )
        metrics = evaluate_functional_contrast(response, 100.0, {
            "minimum_center_transmission": 0.8,
            "maximum_endpoint_transmission": 0.2,
            "minimum_center_to_endpoint_contrast": 0.6,
        })
        self.assertEqual(metrics["status"], "PASS")

    def test_unknown_terminal_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "particle_state.csv"
            fixture.write_text("particle_id,event,status\n1,terminal,unknown\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown terminal status"):
                load_terminal_statuses(fixture)


if __name__ == "__main__":
    unittest.main()
