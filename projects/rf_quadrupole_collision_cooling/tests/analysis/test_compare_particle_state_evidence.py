from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
ANALYZER = PROJECT_ROOT / "analysis" / "compare_particle_state.py"
STATE_FIELDS = [
    "particle_id",
    "event",
    "elapsed_time_us",
    "radial_position_mm",
    "divergence_angle_deg",
    "kinetic_energy_eV",
    "max_rod_radius_mm",
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_axial_m_s",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "rf_phase_rad",
]


class CompareParticleStateEvidenceTests(unittest.TestCase):
    particles = 5

    def write_state(self, path: Path, handoff_ids: set[int]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
            writer.writeheader()
            for particle_id in range(1, self.particles + 1):
                writer.writerow({"particle_id": particle_id, "event": "source"})
                if particle_id in handoff_ids:
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "event": "handoff",
                            "elapsed_time_us": 10 + particle_id / 10,
                            "radial_position_mm": particle_id / 100,
                            "divergence_angle_deg": particle_id / 100,
                            "kinetic_energy_eV": 2,
                            "transverse_x_mm": particle_id / 100,
                            "transverse_y_mm": 0,
                            "velocity_axial_m_s": 1000,
                            "velocity_x_m_s": 0,
                            "velocity_y_m_s": 0,
                            "rf_phase_rad": 0,
                        }
                    )
                writer.writerow(
                    {
                        "particle_id": particle_id,
                        "event": "terminal",
                        "max_rod_radius_mm": 0.1,
                    }
                )

    def run_case(
        self,
        comsol_handoffs: set[int],
        simion_handoffs: set[int],
    ) -> tuple[subprocess.CompletedProcess[str], dict, list[dict[str, str]]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        comsol = root / "comsol.csv"
        simion = root / "simion.csv"
        particles = root / "particles.ion"
        resolved = root / "resolved.json"
        regression = root / "regression.json"
        interface = root / "interface.json"
        output = root / "comparison.json"
        paired = root / "paired.csv"
        self.write_state(comsol, comsol_handoffs)
        self.write_state(simion, simion_handoffs)
        particles.write_text("particle-row\n" * self.particles, encoding="ascii")
        resolved.write_text(
            json.dumps(
                {
                    "role": "multipole_resolved_design_do_not_edit",
                    "geometry_mm": {"inscribed_radius_r0": 3.5},
                }
            ),
            encoding="utf-8",
        )
        regression.write_text(
            json.dumps(
                {
                    "mode": "transport_no_collision",
                    "numerics": {
                        "minimum_expected_transmission": 0.8,
                        "cross_solver_transmission_absolute_tolerance": 0.1,
                        "cross_solver_relative_mean_tof_tolerance": 0.1,
                    },
                }
            ),
            encoding="utf-8",
        )
        interface.write_text(
            json.dumps(
                {
                    "mode": "transport_interface_readiness",
                    "numerics": {"minimum_diagnostic_particles": 1},
                    "candidate_acceptance_targets": {
                        "minimum_transmission": 0.8,
                        "cross_solver_transmission_absolute_difference": 0.05,
                        "cross_solver_relative_mean_tof_difference": 0.05,
                        "cross_solver_relative_rms_output_radius_difference": 0.1,
                        "cross_solver_relative_rms_divergence_difference": 0.15,
                        "cross_solver_relative_mean_energy_difference": 0.02,
                    },
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ANALYZER),
                "--comsol",
                str(comsol),
                "--simion",
                str(simion),
                "--resolved",
                str(resolved),
                "--regression-mode",
                str(regression),
                "--interface-mode",
                str(interface),
                "--particles",
                str(particles),
                "--output",
                str(output),
                "--paired-output",
                str(paired),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        report = json.loads(output.read_text(encoding="utf-8"))
        with paired.open(encoding="utf-8", newline="") as handle:
            paired_rows = list(csv.DictReader(handle))
        return result, report, paired_rows

    def assert_complete_negative_evidence(
        self,
        comsol_handoffs: set[int],
        simion_handoffs: set[int],
    ) -> tuple[dict, list[dict[str, str]]]:
        result, report, paired = self.run_case(
            comsol_handoffs,
            simion_handoffs,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["execution_status"], "success")
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(paired), self.particles)
        self.assertEqual(
            [int(row["particle_id"]) for row in paired],
            list(range(1, self.particles + 1)),
        )
        return report, paired

    def test_empty_handoffs_fail_closed_with_full_id_evidence(self) -> None:
        report, paired = self.assert_complete_negative_evidence(set(), set())
        self.assertEqual(report["comsol"]["transmission"], 0)
        self.assertIsNone(report["comparison"]["mean_tof_relative_difference"])
        self.assertEqual({row["pair_status"] for row in paired}, {"neither"})

    def test_disjoint_handoffs_are_not_silently_dropped(self) -> None:
        report, paired = self.assert_complete_negative_evidence({1, 2}, {3, 4})
        self.assertEqual(report["paired_handoff_particles"], 0)
        self.assertEqual(
            [row["pair_status"] for row in paired],
            ["comsol_only", "comsol_only", "simion_only", "simion_only", "neither"],
        )

    def test_partial_pairing_is_reported_for_every_source_id(self) -> None:
        report, paired = self.assert_complete_negative_evidence(
            {1, 2, 3, 4, 5},
            {1, 2, 3, 4},
        )
        self.assertEqual(report["paired_handoff_particles"], 4)
        self.assertFalse(report["regression_gates"]["particle_identity"])
        self.assertEqual(paired[-1]["pair_status"], "comsol_only")

    def test_equal_but_low_transmission_fails_minimum_gate(self) -> None:
        report, _ = self.assert_complete_negative_evidence({1, 2, 3}, {1, 2, 3})
        self.assertFalse(
            report["candidate_interface_targets_diagnostic_only"][
                "minimum_transmission_comsol"
            ]
        )
        self.assertFalse(
            report["regression_gates"]["minimum_transmission_simion"]
        )

    def test_complete_matching_handoffs_pass(self) -> None:
        all_ids = set(range(1, self.particles + 1))
        result, report, paired = self.run_case(all_ids, all_ids)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["execution_status"], "success")
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(report["regression_gates"].values()))
        self.assertEqual({row["pair_status"] for row in paired}, {"paired"})


if __name__ == "__main__":
    unittest.main()
