from __future__ import annotations

import importlib.util
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from common.contracts.file_identity import file_sha256
from projects.rf_multipole_ion_optics.analysis import plot_transport_phase_diagnostics as phase

SCRIPT = (
    Path(__file__).parents[2]
    / "workflows"
    / "interface_readiness"
    / "assess_integration.py"
)
SPEC = importlib.util.spec_from_file_location("integration_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IntegrationGateTests(unittest.TestCase):
    def test_legacy_mixed_result_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity is invalid"):
            MODULE.validate_comparison_result(
                {
                    "schema_version": 1,
                    "execution_status": "success",
                    "status": "PASS",
                    "regression_gates": {"legacy": True},
                },
                "rf_quadrupole_no_collision_cross_solver_result",
                "transport_no_collision",
            )

    def test_contract_requires_all_frozen_sections(self) -> None:
        self.assertFalse(MODULE.integration_contract_complete(None))
        self.assertFalse(MODULE.integration_contract_complete({"status": "draft"}))
        self.assertFalse(MODULE.integration_contract_complete({"status": "frozen", "coordinate_transform": {"x": 1}}))
        self.assertTrue(MODULE.integration_contract_complete({
            "status": "frozen",
            "coordinate_transform": {"matrix": "identity"},
            "timing_contract": {"time_zero": "handoff"},
            "acceptance_criteria": {"transmission_min": 0.8},
        }))

    def test_regression_failure_cannot_pass(self) -> None:
        status, _, reason = MODULE.decide_gate(
            False, True, True, True, "PASS"
        )
        self.assertEqual(status, "FAIL")
        self.assertEqual(reason, "component_regression_failed")

    def test_missing_contract_cannot_pass(self) -> None:
        status, blockers, reason = MODULE.decide_gate(
            True, True, True, False, "NOT_EVALUATED"
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("missing_integration_contract", blockers)
        self.assertEqual(reason, "missing_integration_contract")

    def test_strict_pass_with_complete_contract(self) -> None:
        status, _, reason = MODULE.decide_gate(
            True, True, True, True, "NOT_EVALUATED"
        )
        self.assertEqual((status, reason), ("PASS", "none"))

    def test_functional_pass_is_conditional(self) -> None:
        status, _, reason = MODULE.decide_gate(
            True, False, True, True, "PASS"
        )
        self.assertEqual(status, "CONDITIONAL_PASS")
        self.assertIn("functional_acceptance_passed", reason)

    def test_unresolved_or_failed_functional_gate_fails(self) -> None:
        self.assertEqual(
            MODULE.decide_gate(True, False, True, True, "NOT_EVALUATED")[0],
            "FAIL",
        )
        self.assertEqual(
            MODULE.decide_gate(True, False, True, True, "FAIL")[0],
            "FAIL",
        )

    def test_unevaluated_interface_cannot_use_functional_override(self) -> None:
        status, blockers, reason = MODULE.decide_gate(
            True, False, False, True, "PASS"
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("interface_readiness_not_evaluated", blockers)
        self.assertEqual(reason, "interface_readiness_not_evaluated")


class TransportPhaseDiagnosticsTests(unittest.TestCase):
    """Exercise the existing CLI and its actual downstream JSON consumer."""

    CLI = "projects.rf_multipole_ion_optics.analysis.plot_transport_phase_diagnostics"
    REPO = Path(__file__).resolve().parents[4]
    COLUMNS = ("particle_id", "axial_z_mm", "time_us", "transverse_x_mm", "transverse_y_mm")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rf_phase_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.resolved, interface = phase.load_contract()
        self.planes = phase.diagnostic_planes(self.resolved, interface)
        self.end = max(self.planes.values()) + 1.
        self.comsol = self.root / "comsol.csv"
        self.simion = self.root / "simion.csv"
        self.rows = [dict(zip(self.COLUMNS, (pid, z, .1*z+.01*pid, .01*z, 0.), strict=True))
                     for pid in (7, 31) for z in (0., self.end/2, self.end)]
        self.write_rows(self.comsol, self.rows)
        other = [dict(row, time_us=row["time_us"]+.001*row["axial_z_mm"]+.0001*row["particle_id"],
                      transverse_x_mm=row["transverse_x_mm"]+.0002*row["axial_z_mm"]+.0001*row["particle_id"])
                 for row in self.rows]
        self.write_rows(self.simion, other)

    def write_rows(self, path, rows):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, "-B", "-m", self.CLI, *map(str, arguments)],
                              cwd=self.REPO, capture_output=True, text=True, timeout=60, check=False)

    def export(self):
        result = self.run_cli("--run-dir", self.root, "--comsol-trajectory", self.comsol,
                              "--simion-trajectory", self.simion, "--output-label", "fixture")
        return result, self.root / "results/cross_solver/transport_no_collision_phase_diagnostics_fixture.json"

    def test_module_help_works_from_repository_root(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--comsol-trajectory", result.stdout)

    def test_tracks_reject_ambiguous_nonfinite_and_invalid_identity_before_interpolation(self):
        for scenario in ("reverse_z", "duplicate_z", "reverse_time", "duplicate_time", "nonfinite", "fractional_id", "zero_id", "negative_id", "one_sample", "empty"):
            rows = [dict(row) for row in self.rows[:3]]
            if scenario == "reverse_z": rows[1]["axial_z_mm"] = -1.
            elif scenario == "duplicate_z": rows[1]["axial_z_mm"] = rows[0]["axial_z_mm"]
            elif scenario == "reverse_time": rows[1]["time_us"] = -1.
            elif scenario == "duplicate_time": rows[1]["time_us"] = rows[0]["time_us"]
            elif scenario == "nonfinite": rows[1]["transverse_x_mm"] = float("nan")
            elif scenario == "fractional_id": rows[0]["particle_id"] = 7.5
            elif scenario == "zero_id": rows[0]["particle_id"] = 0
            elif scenario == "negative_id": rows[0]["particle_id"] = -7
            elif scenario == "one_sample": rows = rows[:1]
            elif scenario == "empty": rows = []
            self.write_rows(self.comsol, rows)
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                phase.load_tracks(self.comsol)
        self.comsol.write_text("particle_id,time_us\n7,1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "trajectory columns"):
            phase.load_tracks(self.comsol)

    def test_support_boundaries_are_inclusive_and_do_not_clamp_missing_windows(self):
        track = phase.load_tracks(self.comsol)[7]
        np.testing.assert_array_equal(phase.interpolate(track, np.array([0., self.end]), "time"), track["time"][[0, -1]])
        for points in ([-.1], [self.end+.1], [float("inf")]):
            with self.subTest(points=points), self.assertRaisesRegex(ValueError, "support interval"):
                phase.interpolate(track, np.array(points), "time")
        self.write_rows(self.simion, [row for row in self.rows if row["axial_z_mm"] > 0])
        result, output = self.export()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("support interval", result.stderr)
        self.assertFalse(output.parent.exists())

    def test_different_observed_ids_fail_without_dropping_a_particle(self):
        self.write_rows(self.simion, self.rows[:3])
        result, output = self.export()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("particle IDs differ", result.stderr)
        self.assertFalse(output.parent.exists())

    def test_zero_variance_correlation_is_null_in_strict_json(self):
        self.write_rows(self.simion, self.rows)
        result, output = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"), parse_constant=lambda value: self.fail(value))
        self.assertIsNone(report["rod_phase_distance_pearson_r"])
        self.assertEqual(report["rod_phase_distance_correlation_status"], "zero_variance")

    def test_cli_preserves_valid_arithmetic_records_evidence_and_feeds_existing_gate(self):
        result, output = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"), parse_constant=lambda value: self.fail(value))
        with Image.open(output.with_suffix(".png")) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 0)
        meta = report["analysis_metadata"]
        self.assertEqual(meta["observed_particle_ids"], [7, 31])
        for field in ("mother_cohort", "frame", "clock"):
            self.assertEqual(meta[field], "unspecified")
        for role, path in (("comsol_trajectory", self.comsol), ("simion_trajectory", self.simion)):
            self.assertEqual(meta["inputs"][role]["sha256"], file_sha256(path))
            self.assertEqual(meta["inputs"][role]["bytes"], path.stat().st_size)
        # Independent old arithmetic over the same valid samples and unchanged grid.
        z = np.arange(self.planes["first_common_plane"], self.planes["detector_front"]+1e-9, .2)
        left, right = phase.load_tracks(self.comsol), phase.load_tracks(self.simion)
        dt = np.array([np.interp(z, left[pid]["z"], left[pid]["time"])-np.interp(z, right[pid]["z"], right[pid]["time"]) for pid in (7, 31)])
        distance = np.array([np.hypot(np.interp(z, left[pid]["z"], left[pid]["x"])-np.interp(z, right[pid]["z"], right[pid]["x"]),
                                     np.interp(z, left[pid]["z"], left[pid]["y"])-np.interp(z, right[pid]["z"], right[pid]["y"])) for pid in (7, 31)])
        wrapped = (dt/(1e6/self.resolved["drive"]["frequency_Hz"])*360+180)%360-180
        rod = (z >= self.resolved["geometry_mm"]["rod_z_min"]) & (z <= self.resolved["geometry_mm"]["rod_z_max"])
        self.assertEqual(report["rod_phase_distance_pearson_r"], float(np.corrcoef(np.abs(wrapped[:, rod]).ravel(), distance[:, rod].ravel())[0, 1]))
        for name, plane in self.planes.items():
            index = int(np.argmin(np.abs(z-plane)))
            self.assertEqual(report["plane_metrics"][name], dict(axial_z_mm=plane, mean_delta_time_us=float(np.mean(dt[:, index])),
                mean_wrapped_phase_deg=float(np.mean(wrapped[:, index])), mean_transverse_distance_mm=float(np.mean(distance[:, index]))))
        documents = {
            "component-regression": dict(schema_version=2, role="rf_quadrupole_no_collision_cross_solver_result", workflow="transport_no_collision", execution_status="success", status="PASS", gates={"fixture": True}),
            "interface-comparison": dict(schema_version=2, role="rf_quadrupole_interface_readiness_cross_solver_result", workflow="transport_interface_readiness", execution_status="success", status="PASS", gates={"fixture": True}, particles=2,
                comparison={key: 0. for key in ("transmission_absolute_difference", "mean_tof_relative_difference", "rms_radius_relative_difference", "rms_divergence_relative_difference", "mean_energy_relative_difference")}),
            "field-convergence": dict(status="PASS", **{solver: {region: dict(vector_relative_rms=.01) for region in ("entrance_fringe", "rod_region", "exit_fringe_and_detector")} for solver in ("SIMION_0p2_to_0p1", "COMSOL_mesh1_to_hmax0p5")}),
            "internal-release": {**report, "plane_metrics": {**report["plane_metrics"], "internal_window_end": report["plane_metrics"]["rod_entry"]}},
            "mode": dict(candidate_acceptance_targets={key: .1 for key in ("cross_solver_transmission_absolute_difference", "cross_solver_relative_mean_tof_difference", "cross_solver_relative_rms_output_radius_difference", "cross_solver_relative_rms_divergence_difference", "cross_solver_relative_mean_energy_difference")}),
            "integration-contract": dict(status="frozen", coordinate_transform={"fixture": True}, timing_contract={"fixture": True}, acceptance_criteria={"fixture": True}),
        }
        arguments = []
        for role, document in documents.items():
            path = self.root / f"{role}.json"
            path.write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
            arguments.extend(["--"+role, str(path)])
        gate_output = self.root / "gate"
        consumed = subprocess.run([sys.executable, "-B", "-m", "projects.rf_multipole_ion_optics.workflows.interface_readiness.assess_integration",
            *arguments, "--phase-diagnostics", str(output), "--output-dir", str(gate_output)], cwd=self.REPO,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(consumed.returncode, 0, consumed.stderr)
        self.assertEqual(json.loads((gate_output/"oatof_integration_gate.json").read_text())["status"], "PASS")
        self.assertEqual(json.loads((gate_output/"edge_localization.json").read_text())["baseline_trajectory"]["rod_exit_mean_distance_mm"],
                         report["plane_metrics"]["rod_exit"]["mean_transverse_distance_mm"])


if __name__ == "__main__":
    unittest.main()
