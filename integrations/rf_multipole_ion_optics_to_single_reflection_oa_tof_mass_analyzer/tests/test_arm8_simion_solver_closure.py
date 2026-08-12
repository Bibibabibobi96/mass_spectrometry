from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.arm8_simion_solver_closure import (
    ACCELERATOR_INSTANCE_MAPPINGS,
    EVENTS,
    _selected_ids,
    piecewise_potential_v,
    prepare,
    transverse_speed_m_per_s,
    verify_log,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.verify_axial_ideal_closure import (
    compute_receipt,
)


ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer"
CONTRACT = PROJECT / "config" / "diagnostics" / "axial_ideal_arm8_analytic_closure.json"
GEOMETRY = PROJECT / "config" / "resolved_geometry.json"
FORMAL = PROJECT / "simion" / "workbench" / "formal" / "oatof_ideal_grounded.lua"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _prepared(tmp_path: Path) -> tuple[dict, Path]:
    contract = _json(CONTRACT)
    geometry = _json(GEOMETRY)
    receipt = compute_receipt(
        contract,
        geometry,
        contract_path=CONTRACT,
        resolved_path=GEOMETRY,
    )
    receipt_path = tmp_path / "analytic_receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    layout = copy.deepcopy(geometry)
    scale = np.sqrt(2.0)
    layout["coordinate_convention"]["accelerator_axis_x"] *= scale
    layout["coordinate_convention"]["detector_x"] *= scale
    layout["single_flight_layout_derivation"] = {
        "layout_profile_id": "symmetric_10ev_injection_diagnostic",
        "target_injection_energy_eV": 10.0,
    }
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(layout), encoding="utf-8")
    output = tmp_path / "prepared"
    result = prepare(receipt_path, layout_path, FORMAL, output, 101)
    return result, output


class Arm8SimionSolverClosureTests(unittest.TestCase):
    def test_uniform_101_id_selection_preserves_endpoints_and_center(self) -> None:
        ids = _selected_ids(1001, 101)
        self.assertEqual(ids, list(range(1, 1002, 10)))
        self.assertEqual(ids[50], 501)

    def test_frontend_and_overlay_share_positive_global_z_local_z_mapping(self) -> None:
        self.assertEqual(set(ACCELERATOR_INSTANCE_MAPPINGS), {3, 5})
        for mapping in ACCELERATOR_INSTANCE_MAPPINGS.values():
            self.assertEqual(mapping["rotation_deg"], [0.0, 0.0, 0.0])
            self.assertEqual(mapping["local_derivative_axis"], "z")
            self.assertEqual(mapping["global_z_sign"], 1)

    def test_prepare_freezes_zero_axial_velocity_10ev_transport_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract, output = _prepared(Path(directory))
            self.assertEqual(contract["expected_center"]["analytic_particle_id"], 501)
            self.assertEqual(contract["source"]["transverse_energy_eV"], 10.0)
            self.assertEqual(contract["source"]["vz_m_s"], 0.0)
            self.assertAlmostEqual(
                contract["source"]["vx_m_s"], transverse_speed_m_per_s(10.0, 100.0)
            )
            detector = contract["closure_layers"]["full_instrument_detector_closure"]
            self.assertAlmostEqual(detector["source_axis_x_mm"], -69.01362184380704)
            self.assertAlmostEqual(detector["mechanical_detector_center_x_mm"], 69.01362184380704)
            self.assertLess(detector["predicted_radius_mm_max"], detector["mechanical_detector_radius_mm"])
            with (output / "arm8_expected_checkpoints.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            for analytic_id in contract["source"]["analytic_particle_ids"]:
                self.assertEqual(
                    [row["event"] for row in rows if int(row["analytic_particle_id"]) == analytic_id],
                    list(EVENTS),
                )
            with (output / "arm8_source_state.csv").open(newline="", encoding="utf-8") as stream:
                source = list(csv.DictReader(stream))
            self.assertEqual(len(source), 101)
            self.assertEqual({float(row["vz_m_s"]) for row in source}, {0.0})
            self.assertEqual({float(row["vy_m_s"]) for row in source}, {0.0})
            clock = contract["clock"]
            self.assertEqual(clock["analytic_particle_ids"], contract["source"]["analytic_particle_ids"])
            self.assertEqual(len(clock["entries"]), 101)
            self.assertEqual(clock["entries"][-1]["analytic_particle_id"], 1001)
            self.assertEqual({row["birth_time_us"] for row in clock["entries"]}, {0.0})
            self.assertEqual(
                {row["pulse_effective_time_us"] for row in clock["entries"]}, {0.0}
            )
            self.assertFalse(clock["fallback_allowed"])
            program = (output / "arm8_full_domain_piecewise_ideal.lua").read_text(
                encoding="utf-8"
            )
            self.assertIn("local arm8_birth_time_us_by_analytic_id", program)
            self.assertIn("local arm8_pulse_effective_time_us_by_analytic_id", program)
            self.assertGreaterEqual(program.count("[1001]=0"), 2)
            self.assertIn("assert(birth~=nil", program)
            self.assertIn("assert(pulse~=nil", program)
            self.assertIn("fallback_allowed=0", program)
            self.assertIn("local function arm8_emit_plane(event,plane,previous)", program)
            self.assertIn("local fraction=(plane-previous.z)/dz", program)
            self.assertIn("local t=previous.t+fraction*(ion_time_of_flight-previous.t)", program)
            self.assertIn("arm8_emit(event,t,x,y,plane)", program)
            self.assertNotIn("function segment.terminate()\n  if arm8_solver_closure_enable", program)
            self.assertIn("if q==3 and ion_vz_mm>0", program)
            self.assertIn("dt=(arm8_focus_z-ion_pz_mm)/ion_vz_mm", program)

    def test_fixed_plane_interpolation_closes_ids_21_and_31_without_changing_peak_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract, output = _prepared(Path(directory))
            with (output / "arm8_expected_checkpoints.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                rows = list(csv.DictReader(stream))
            for analytic_id, observed_z_mm, observed_time_us, vz_mm_us in (
                (21, 0.0498800538434207, 0.54467916735989, 63.3052906977435),
                (31, 0.0498799616571167, 0.544652510035189, 63.280889877053),
            ):
                expected = next(
                    row
                    for row in rows
                    if int(row["analytic_particle_id"]) == analytic_id
                    and row["event"] == "focus_forward"
                )
                interpolated_time_us = observed_time_us - observed_z_mm / vz_mm_us
                self.assertAlmostEqual(
                    interpolated_time_us,
                    float(expected["expected_pulse_effective_time_us"]),
                    delta=6.0e-6,
                )
            return_times = [
                float(row["expected_pulse_effective_time_us"])
                for row in rows
                if row["event"] == "theoretical_return_focus_plane"
            ]
            detector_times = [
                float(row["expected_pulse_effective_time_us"])
                for row in rows
                if row["event"] == "mechanical_detector_crossing"
            ]
            self.assertEqual(return_times, detector_times)
            self.assertEqual(contract["expected_subset_peak"]["particles"], len(detector_times))

    def test_piecewise_potential_is_continuous_across_complete_domain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract, _ = _prepared(Path(directory))
            potential = contract["potential"]
            planes = potential["planes_mm"]
            fields = potential["fields_V_per_mm"]
            boundaries = potential["boundary_potentials_V"]
            expected = {
                "repeller": boundaries["repeller"],
                "grid1": boundaries["grid1"],
                "grid2": boundaries["grid2"],
                "entrance": boundaries["entrance"],
                "midgrid": boundaries["midgrid"],
                "backplate": boundaries["backplate"],
            }
            for name, voltage in expected.items():
                self.assertAlmostEqual(
                    piecewise_potential_v(planes[name], planes, fields, boundaries), voltage
                )
            epsilon = 1e-9
            for name in ("grid1", "grid2", "entrance", "midgrid"):
                left = piecewise_potential_v(planes[name] - epsilon, planes, fields, boundaries)
                right = piecewise_potential_v(planes[name] + epsilon, planes, fields, boundaries)
                self.assertLess(abs(left - right), 1e-6)


def _synthetic_log(output: Path, *, time_error_ns: float = 0.0, swap_first_two: bool = False) -> Path:
    with (output / "arm8_expected_checkpoints.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    lines: list[str] = []
    seen_clock_ids: set[int] = set()
    for index, row in enumerate(rows):
        analytic_id = int(row["analytic_particle_id"])
        if analytic_id not in seen_clock_ids:
            lines.append(
                "TRACE: arm8_analytic_clock "
                f"ion={row['simulation_particle_id']} analytic_id={analytic_id} "
                "birth_time_us=0 pulse_effective_time_us=0 fallback_allowed=0"
            )
            seen_clock_ids.add(analytic_id)
        time_us = float(row["expected_pulse_effective_time_us"])
        if index == 0:
            time_us += time_error_ns / 1000.0
        if row["event"] == "mechanical_detector_crossing":
            lines.append(
                f"TRACE: detector_crossing ion={row['simulation_particle_id']} t={time_us} "
                f"x={row['expected_x_mm']} y=0 z={row['expected_z_mm']} r=0 zmax=0"
            )
        else:
            energy = (
                float(row["expected_exit_energy_eV"]) + 10.0
                if row["expected_exit_energy_eV"]
                else 0
            )
            lines.append(
                "TRACE: arm8_solver_checkpoint "
                f"ion={row['simulation_particle_id']} analytic_id={row['analytic_particle_id']} "
                f"event={row['event']} t_us={time_us} x_mm={row['expected_x_mm']} "
                f"y_mm=0 z_mm={row['expected_z_mm']} vx_mm_us={transverse_speed_m_per_s(10.0, 100.0) / 1000.0} vy_mm_us=0 "
                f"vz_mm_us=0 kinetic_energy_eV={energy}"
            )
    if swap_first_two:
        lines[1], lines[2] = lines[2], lines[1]
    path = output / "synthetic.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class Arm8VerifyLogTests(unittest.TestCase):
    def test_verify_log_fails_closed_for_missing_log_and_event_reordering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, output = _prepared(Path(directory))
            contract = output / "arm8_simion_solver_closure_contract.json"
            with self.assertRaisesRegex(ValueError, "log is missing"):
                verify_log(contract, [output / "missing.log"], output / "result.json")
            log = _synthetic_log(output, swap_first_two=True)
            with self.assertRaisesRegex(ValueError, "event order differs"):
                verify_log(contract, [log], output / "result.json")

    def test_verify_log_writes_fail_receipt_for_numeric_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, output = _prepared(Path(directory))
            contract = output / "arm8_simion_solver_closure_contract.json"
            log = _synthetic_log(output, time_error_ns=1.0)
            result = verify_log(contract, [log], output / "result.json")
            self.assertEqual(result["status"], "fail")
            self.assertFalse(result["all_assertions_passed"])
            self.assertAlmostEqual(result["maximum_errors"]["time_ns"], 1.0)


if __name__ == "__main__":
    unittest.main()
