from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_native_transverse_l1 import (
    NativeTransverseL1Error,
    analyze_native_l1_log,
    build_native_l1_probe_contract,
    write_fly2,
    write_lua_source_contract,
)


def _period_probe() -> dict:
    nominal = 4000.0
    particles = []
    for particle_id, energy in enumerate((3999.0, nominal, 4001.0), start=1):
        particles.append({
            "particle_id": particle_id,
            "target_energy_ev": energy,
            "theory_period_us": 30.0,
            "position_project_mm": [0.0, 280.0, 0.0],
            "direction_project": [0.0, 0.0, 1.0],
        })
    return {
        "schema_version": 2,
        "role": "mrtof_bare_mirror_real_field_period_probe",
        "status": "prepared",
        "qualification": "fixed_grid_diagnostic",
        "mirror_voltages_v": [0.0, -5900.0, -2600.0, 4200.0, 6000.0],
        "stripe_biases_v": [0.0, 0.0],
        "prism_voltages_v": [0.0, 0.0],
        "nominal_energy_ev": nominal,
        "particle_mass_th": 524.0,
        "particle_charge_e": 1.0,
        "probe_y_mm": 280.0,
        "particles": particles,
    }


def _event(
    *, ion: int, direction: int, kind: str, phase: str, time: float, x: float, vx: float, vz: float,
) -> str:
    turns = 1 if phase == "first_return" else 2
    return (
        f"MRTOF_NATIVE_L1 ion={ion} phase={phase} direction_z={direction} probe_kind={kind} "
        f"energy_ev=4000 time_us={time} turns={turns} x_mm={x} y_mm=280 "
        f"vx_mm_us={vx} vy_mm_us=0 vz_mm_us={vz}"
    )


def _good_log(contract: dict) -> str:
    lines = []
    position = contract["position_probe_mm"]
    angle = contract["angle_probe_rad"]
    f = 20.0
    for particle in contract["particles"]:
        direction = particle["direction_z"]
        kind = particle["probe_kind"]
        initial_x = particle["initial_x_mm"]
        initial_alpha = particle["initial_alpha_rad"]
        first_x = f * initial_alpha
        first_alpha = -initial_x / f
        first_denominator = 10.0
        full_denominator = 10.0
        full_time = 100.0
        if kind in {"x_positive", "x_negative"}:
            full_time += 2.0 * position * position
        elif kind in {"alpha_positive", "alpha_negative"}:
            full_time += 8.0 * angle * angle
        lines.append(_event(
            ion=particle["particle_id"], direction=direction, kind=kind, phase="first_return",
            time=10.0, x=first_x, vx=first_alpha * first_denominator,
            vz=-direction * first_denominator,
        ))
        lines.append(_event(
            ion=particle["particle_id"], direction=direction, kind=kind, phase="full_return",
            time=full_time, x=initial_x, vx=initial_alpha * full_denominator,
            vz=direction * full_denominator,
        ))
    lines.append("status,Fly completed. 10 splats, 1 seconds")
    return "\n".join(lines) + "\n"


class NativeTransverseL1Tests(unittest.TestCase):
    def _contract(self, root: Path) -> dict:
        source = root / "period_probe.json"
        source.write_text(json.dumps(_period_probe()), encoding="utf-8")
        return build_native_l1_probe_contract(source, position_probe_mm=0.1, angle_probe_rad=0.01)

    def test_builds_ten_deterministic_particles_and_writes_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            fly2 = root / "native_l1.fly2"
            lua = root / "native_l1.lua"
            write_fly2(contract, fly2)
            write_lua_source_contract(contract, lua)
            fly2_text = fly2.read_text(encoding="utf-8")
            lua_text = lua.read_text(encoding="utf-8")
        self.assertEqual(len(contract["particles"]), 10)
        self.assertEqual(fly2_text.count("standard_beam"), 10)
        self.assertIn("direction = vector(0, 0, -1)", fly2_text)
        self.assertIn("[10]", lua_text)
        self.assertIn('probe_kind="alpha_negative"', lua_text)

    def test_reduces_two_return_events_with_same_l1_formulas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            log = root / "native_l1.log"
            log.write_text(_good_log(contract), encoding="utf-8")
            result = analyze_native_l1_log(contract, log)
        for direction in ("-1", "1"):
            record = result["directions"][direction]
            self.assertTrue(record["stable"])
            self.assertAlmostEqual(record["gamma_degrees"], 90.0, places=12)
            self.assertAlmostEqual(record["determinant"], 1.0, places=12)
            self.assertAlmostEqual(record["f_mm"], 20.0, places=12)
            self.assertAlmostEqual(record["T_xx_us_per_mm2"], 2.0, places=12)
            self.assertAlmostEqual(record["T_alphaalpha_us_per_rad2"], 8.0, places=10)
            self.assertAlmostEqual(record["Tbar_xx_us_per_mm2"], 1.01, places=11)

    def test_rejects_duplicate_phase_and_noncomplete_simion_flight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            log = root / "native_l1.log"
            text = _good_log(contract)
            first = text.splitlines()[0]
            log.write_text(first + "\n" + text, encoding="utf-8")
            with self.assertRaisesRegex(NativeTransverseL1Error, "duplicate"):
                analyze_native_l1_log(contract, log)
            log.write_text(_good_log(contract).replace("10 splats", "9 splats"), encoding="utf-8")
            with self.assertRaisesRegex(NativeTransverseL1Error, "did not complete"):
                analyze_native_l1_log(contract, log)

    def test_rejects_wrong_phase_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            log = root / "native_l1.log"
            text = _good_log(contract).replace("ion=1 phase=first_return direction_z=-1", "ion=1 phase=first_return direction_z=1", 1)
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(NativeTransverseL1Error, "disagrees"):
                analyze_native_l1_log(contract, log)

    def test_rejects_first_return_with_the_launch_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            log = root / "native_l1.log"
            text = _good_log(contract).replace("vz_mm_us=10", "vz_mm_us=-10", 1)
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(NativeTransverseL1Error, "wrong longitudinal"):
                analyze_native_l1_log(contract, log)

    def test_allows_interpolated_return_section_but_rejects_material_y_offset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._contract(root)
            log = root / "native_l1.log"
            interpolated = _good_log(contract).replace("y_mm=280 ", "y_mm=280.0000037 ", 1)
            log.write_text(interpolated, encoding="utf-8")
            analyze_native_l1_log(contract, log)
            displaced = _good_log(contract).replace("y_mm=280 ", "y_mm=280.0011 ", 1)
            log.write_text(displaced, encoding="utf-8")
            with self.assertRaisesRegex(NativeTransverseL1Error, "left its frozen y slice"):
                analyze_native_l1_log(contract, log)


if __name__ == "__main__":
    unittest.main()
