"""Synthetic protocol records exercise automatic cooled/OA analysis, not Fly.

The complete three-ID fixture deliberately contains one exit, one unresolved
native stop and one timeout. It must never be described as native physics or
as a replacement for the original N=100 scientific mother cohort.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.contracts.write_run_manifest import file_record
from integrations.tests.test_local_frontend_analysis import (
    _TIMES, fixture, write_log,
)
from integrations.workflows.cooled_frontend.analyze import analyze_cooled_frontend
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import build_cooled_buncher_contract
from projects.dual_pressure_rectilinear_ion_processor.tests.test_cooled_buncher import buncher_fixture, native_pose


def cooled_analysis_fixture(root: Path, *, pressure_scale: int, entrance_close_us: float = .5) -> tuple[Path, list[dict], dict]:
    """Extend the existing lawful-log fixture without changing its birth cohort."""
    log, events = fixture(root)
    shared = next(r for r in events if r["event"] == "local_shared_time" and r["particle_id"] == 11)
    shared.update(vx_mm_per_us=.2, vy_mm_per_us=.6, vz_mm_per_us=-2.)
    write_log(log, events)
    inputs = root/"inputs"
    model, guide, registration, request, ids = buncher_fixture()
    conditioner = build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                               request=request, electrode_ids=ids)
    drive = dict(schema_version=1, role="synthetic_cooled_analysis_drive",
                 capture_voltages_v={name: 0. for name in ids},
                 closed_voltages_v={name: 1. for name in ids},
                 release_voltages_v={name: 2. for name in ids},
                 entrance_close_us=entrance_close_us, release_start_us=1.5)
    pulse_path = inputs/"common_pulse_decision.json"
    pulse_path.write_text(json.dumps(dict(role="synthetic_common_pulse_decision", actual_pulse_time_us=2.))+"\n", encoding="utf-8")
    experiment = dict(schema_version=1, role="rf_oatof_cooled_pressure_control", pressure_scale=pressure_scale,
                      common_pulse_decision=file_record(pulse_path))
    for name, document in (("conditioner_contract.json", conditioner), ("cooled_experiment.json", experiment),
                           ("cooled_drive.json", drive)):
        (inputs/name).write_text(json.dumps(document)+"\n", encoding="utf-8")
    return log, events, experiment


class CooledFrontendAnalysisTests(unittest.TestCase):
    def test_pressure_metadata_all_mother_losses_component_units_and_automatic_figures(self):
        for pressure in (0, 1):
            with self.subTest(pressure=pressure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log, _, experiment = cooled_analysis_fixture(root, pressure_scale=pressure)
                source = root/"inputs/release_global.csv"
                before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, log)}
                result = analyze_cooled_frontend(root, [log], shared_times_us=_TIMES, pulse_time_us=2.)
                output = root/"results/local_frontend/extraction"
                document = json.loads((output/"cooling_evolution.json").read_text())
                self.assertEqual(document["pressure_scale"], pressure)
                self.assertEqual(document["mother_count"], 3)
                self.assertEqual(document["common_pulse_decision"], experiment["common_pulse_decision"])
                self.assertIn("instantaneous", document["interpretation"])
                self.assertEqual((result["mother_count"], result["exit_count"], result["loss_count"]), (3, 1, 2))
                terminal = pd.read_csv(output/"all_mother_terminal_census.csv")
                losses = pd.read_csv(output/"all_losses.csv")
                self.assertEqual(set(terminal.particle_id), {3, 11, 67})
                self.assertEqual(set(losses.particle_id), {11, 67})
                self.assertEqual(set(losses.terminal_class), {"native_stop_unresolved", "timeout"})
                self.assertTrue(losses.raw_line.str.startswith("TRACE:").all())
                by_time = {row["instrument_time_us"]: row for row in document["snapshots"]}
                row = by_time[.5]
                self.assertEqual(row["active_ids"], [3, 11])
                self.assertEqual(row["phase"], "closed")
                self.assertEqual(by_time[0.]["phase"], "capture")
                self.assertEqual(by_time[2.]["phase"], "released")
                self.assertNotIn(3., by_time)  # No propagation of ended particles.
                mass = 524*AMU_KG
                for axis, speeds in (("x", (100., 200.)), ("y", (1000., 600.)), ("z", (-10000., -2000.))):
                    expected = .5*mass*sum(v*v for v in speeds)/2/ELEMENTARY_CHARGE_C
                    self.assertAlmostEqual(row[f"mean_E{axis}_ev"], expected)
                self.assertAlmostEqual(row["sigma_vx_m_s"], 50.)
                self.assertAlmostEqual(row["sigma_vy_m_s"], 200.)
                self.assertAlmostEqual(row["sigma_vz_m_s"], 4000.)
                covariance = row["covariance_xyz_mm_velocity_m_s"]
                self.assertAlmostEqual(covariance[3][3], 2500.)
                self.assertAlmostEqual(covariance[4][4], 40000.)
                self.assertAlmostEqual(covariance[5][5], 16000000.)
                self.assertAlmostEqual(covariance[1][4], -400.)
                expected_phase = (2*math.pi*3.7e6*.5e-6)%(2*math.pi)
                self.assertAlmostEqual(row["rf_phase_rad"], expected_phase)
                outputs = set(result["output_paths"])
                for name in ("cooling_evolution.json", "cooling_evolution.csv", "cooling_evolution.png", "cooling_evolution.svg",
                             "shared_time_distributions.png", "shared_time_distributions.svg", "focus_recorded_focus.png"):
                    path = output/name
                    self.assertIn(str(path), outputs)
                    self.assertGreater(path.stat().st_size, 0)
                for path, digest in before.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_exact_recorded_gate_boundary_does_not_shift_phase_on_csv_readback(self):
        boundary = .1+.2  # Binary64 value distinct from decimal 0.3.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events, _ = cooled_analysis_fixture(root, pressure_scale=1, entrance_close_us=boundary)
            for pid in (3, 11):
                row = copy.deepcopy(next(r for r in events if r["event"] == "local_aperture_pre" and r["particle_id"] == pid))
                row.update(event="local_shared_time", instrument_time_us=boundary, requested_time_us=boundary)
                events.append(row)
            write_log(log, events)
            analyze_cooled_frontend(root, [log], shared_times_us=sorted([*_TIMES, boundary]), pulse_time_us=2.)
            document = json.loads((root/"results/local_frontend/extraction/cooling_evolution.json").read_text())
            snapshot = next(row for row in document["snapshots"] if abs(row["instrument_time_us"]-boundary) < math.ulp(boundary)*2)
            self.assertEqual(snapshot["instrument_time_us"], boundary)
            self.assertEqual(snapshot["phase"], "closed")

    def test_zero_exit_result_keeps_all_losses_and_cooling_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, events, _ = cooled_analysis_fixture(root, pressure_scale=0)
            events = [row for row in events if row["event"] != "local_accelerator_exit"]
            next(row for row in events if row["event"] == "accelerator_exit_stop")["event"] = "local_timeout"
            write_log(log, events)
            result = analyze_cooled_frontend(root, [log], shared_times_us=_TIMES, pulse_time_us=2.)
            self.assertEqual(result["exit_count"], 0)
            self.assertEqual(result["loss_count"], 3)
            output = root/"results/local_frontend/extraction"
            with (output/"all_losses.csv").open(newline="") as handle:
                self.assertEqual({int(row["particle_id"]) for row in csv.DictReader(handle)}, {3, 11, 67})
            document = json.loads((output/"cooling_evolution.json").read_text())
            self.assertEqual(document["mother_count"], 3)
            self.assertTrue(document["snapshots"])


if __name__ == "__main__":
    unittest.main()
