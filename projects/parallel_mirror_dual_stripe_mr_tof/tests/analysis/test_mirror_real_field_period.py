from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period import (
    analyze_log,
    load_exact_k_point,
    write_fly2,
)


class MirrorRealFieldPeriodTest(unittest.TestCase):
    def test_loads_explicit_selection_from_multiple_exact_k_roots(self) -> None:
        point = {"mirror_voltages_v": [0.0, -1.0, -2.0, 3.0, 4.0]}
        l0 = {"electrode_voltages_v": point["mirror_voltages_v"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            summary.write_text(json.dumps({
                "selected_root_index": 1,
                "selected_operating_point": point,
                "roots": [
                    {"point": {"mirror_voltages_v": [0.0] * 5}},
                    {"point": point, "refined_mirror_receipt": {"l0_receipt": l0}},
                ],
            }), encoding="utf-8")
            (root / "run_manifest.json").write_text(json.dumps({
                "project": "parallel_mirror_dual_stripe_mr_tof",
                "status": "success",
                "outputs": [{"path": str(summary)}],
            }), encoding="utf-8")

            loaded = load_exact_k_point(root)

        self.assertEqual(loaded["point"], point)
        self.assertEqual(loaded["l0"], l0)

    def _contract(self) -> dict:
        particles = []
        energies = [99.0, 100.0, 101.0, 199.0, 200.0, 201.0, 299.0, 300.0, 301.0]
        for index, energy in enumerate(energies, 1):
            particles.append({
                "particle_id": index,
                "target_energy_ev": energy,
                "theory_period_us": 10.0,
                "position_project_mm": [0.0, 280.0, 0.0],
                "direction_project": [0.0, 0.0, 1.0],
            })
        return {
            "particles": particles,
            "energy_centers_ev": [100.0, 200.0, 300.0],
            "derivative_step_ev": 1.0,
            "probe_y_mm": 280.0,
            "theory_normalized_period_slopes_per_v": [0.0, 0.0, 0.0],
        }

    def test_writes_exact_named_particle_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.fly2"
            write_fly2(self._contract(), output)
            text = output.read_text(encoding="utf-8")
            self.assertEqual(text.count("standard_beam"), 9)
            self.assertIn("center = vector(0, 280, 0)", text)

    def test_reduces_three_local_slopes(self) -> None:
        contract = self._contract()
        lines = []
        for item in contract["particles"]:
            energy = item["target_energy_ev"]
            period = 10.0 + 0.001 * energy
            lines.append(
                f"MRTOF_MIRROR_PERIOD ion={item['particle_id']} target_energy_ev={energy} "
                f"period_us={period} turns=2 x_mm=0 y_mm=280 z_mm=0 "
                "vx_mm_us=0 vy_mm_us=0 vz_mm_us=1"
            )
        lines.append("status,Fly'm complete. Splats: 9")
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "flight.log"
            log.write_text("\n".join(lines), encoding="utf-8")
            result = analyze_log(contract, log)
        self.assertEqual(len(result["simion_normalized_period_slopes_per_v"]), 3)
        self.assertGreater(result["simion_normalized_period_slopes_per_v"][0], 0.0)

    def test_accepts_simion_2020_native_completion_line(self) -> None:
        contract = self._contract()
        lines = []
        for item in contract["particles"]:
            lines.append(
                f"MRTOF_MIRROR_PERIOD ion={item['particle_id']} "
                f"target_energy_ev={item['target_energy_ev']} period_us=10 turns=2 "
                "x_mm=0 y_mm=280 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=1"
            )
        lines.append("status,Fly completed. 9 splats, 38.26 seconds")
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "flight.log"
            log.write_text("\n".join(lines), encoding="utf-8")
            result = analyze_log(contract, log)
        self.assertEqual(len(result["particles"]), 9)

    def test_rejects_missing_particle(self) -> None:
        contract = self._contract()
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "flight.log"
            log.write_text("status,Fly'm complete. Splats: 9\n", encoding="utf-8")
            with self.assertRaises(Exception):
                analyze_log(contract, log)


if __name__ == "__main__":
    unittest.main()
