from __future__ import annotations

import ast
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
PARTICLE_COUNT_POLICY = (
    REPO_ROOT / "common" / "contracts" / "particle_count_policy.json"
)
ANALYSIS = PROJECT_ROOT / "analysis"
INTERFACE = PROJECT_ROOT / "workflows" / "interface_readiness" / "evaluate.py"
NO_COLLISION = (
    PROJECT_ROOT / "workflows" / "no_collision_transport" / "evaluate.py"
)
ANALYZER_MODULES = {
    INTERFACE: (
        "projects.rf_quadrupole_collision_cooling.workflows."
        "interface_readiness.evaluate"
    ),
    NO_COLLISION: (
        "projects.rf_quadrupole_collision_cooling.workflows."
        "no_collision_transport.evaluate"
    ),
}
CORE = ANALYSIS / "particle_state_comparison_core.py"
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


class SplitParticleStateComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.resolved = self.root / "resolved.json"
        self.resolved.write_text(
            json.dumps(
                {
                    "role": "multipole_resolved_design_do_not_edit",
                    "geometry_mm": {"inscribed_radius_r0": 3.5},
                }
            ),
            encoding="utf-8",
        )
        self.no_collision_mode = self.root / "no_collision.json"
        self.no_collision_mode.write_text(
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
        self.interface_mode = self.root / "interface.json"
        self.interface_mode.write_text(
            json.dumps(
                {
                    "mode": "transport_interface_readiness",
                    "status": "candidate_only",
                    "numerics": {"minimum_diagnostic_particles": 100},
                    "candidate_acceptance_targets": {
                        "policy": "diagnostic_only",
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

    @staticmethod
    def write_state(
        path: Path,
        particle_count: int,
        handoff_ids: set[int],
        source_ids: set[int] | None = None,
        duplicate_source: bool = False,
    ) -> None:
        if source_ids is None:
            source_ids = set(range(1, particle_count + 1))
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
            writer.writeheader()
            for particle_id in sorted(source_ids):
                writer.writerow({"particle_id": particle_id, "event": "source"})
            if duplicate_source:
                writer.writerow({"particle_id": 1, "event": "source"})
            for particle_id in range(1, particle_count + 1):
                if particle_id in handoff_ids:
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "event": "handoff",
                            "elapsed_time_us": 10 + particle_id / 1000,
                            "radial_position_mm": 0.1,
                            "divergence_angle_deg": 0.1,
                            "kinetic_energy_eV": 2,
                            "transverse_x_mm": 0.1,
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

    def run_analyzer(
        self,
        analyzer: Path,
        particle_count: int,
        comsol_handoffs: set[int],
        simion_handoffs: set[int],
        *,
        source_ids: set[int] | None = None,
        duplicate_source: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], dict | None, list[dict[str, str]]]:
        case = self.root / f"case_{len(list(self.root.glob('case_*')))}"
        case.mkdir()
        comsol = case / "comsol.csv"
        simion = case / "simion.csv"
        particles = case / "particles.dat"
        output = case / "result.json"
        census = case / "census.csv"
        self.write_state(
            comsol,
            particle_count,
            comsol_handoffs,
            source_ids,
            duplicate_source,
        )
        self.write_state(simion, particle_count, simion_handoffs, source_ids)
        particles.write_text("particle\n" * particle_count, encoding="ascii")
        arguments = [
            sys.executable,
            "-m",
            ANALYZER_MODULES[analyzer],
            "--comsol",
            str(comsol),
            "--simion",
            str(simion),
        ]
        if analyzer == NO_COLLISION:
            arguments += [
                "--resolved",
                str(self.resolved),
                "--mode-contract",
                str(self.no_collision_mode),
                "--particle-count-policy",
                str(PARTICLE_COUNT_POLICY),
            ]
        else:
            arguments += [
                "--mode-contract",
                str(self.interface_mode),
            ]
        arguments += [
            "--particles",
            str(particles),
            "--particle-count",
            str(particle_count),
            "--output",
            str(output),
            "--census-output",
            str(census),
        ]
        completed = subprocess.run(
            arguments,
            cwd=REPO_ROOT,
            timeout=60,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        report = (
            json.loads(output.read_text(encoding="utf-8"))
            if output.is_file()
            else None
        )
        rows: list[dict[str, str]] = []
        if census.is_file():
            with census.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        return completed, report, rows

    def test_interface_identical_eighty_percent_survivors_can_pass(self) -> None:
        survivors = set(range(1, 81))
        result, report, census = self.run_analyzer(
            INTERFACE, 100, survivors, survivors
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(report["gates"].values()))
        self.assertEqual(report["paired_handoff_particles"], 80)
        self.assertEqual(len(census), 100)

    def test_no_collision_requires_full_handoff_pairing(self) -> None:
        survivors = set(range(1, 81))
        result, report, _ = self.run_analyzer(
            NO_COLLISION, 100, survivors, survivors
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["gates"]["full_handoff_pairing"])

    def test_interface_below_minimum_is_not_evaluated(self) -> None:
        survivors = set(range(1, 100))
        result, report, _ = self.run_analyzer(
            INTERFACE, 99, survivors, survivors
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "NOT_EVALUATED")
        self.assertFalse(report["sample_size_eligible"])
        self.assertEqual(report["gates"], {})

    def test_invalid_source_identity_is_not_a_physical_fail(self) -> None:
        source_ids = set(range(1, 100))
        result, report, _ = self.run_analyzer(
            INTERFACE,
            100,
            set(range(1, 81)),
            set(range(1, 81)),
            source_ids=source_ids,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert report is not None
        self.assertEqual(report["status"], "NOT_EVALUATED")
        self.assertFalse(report["source_evidence"]["valid"])
        self.assertEqual(report["gates"], {})

    def test_no_collision_claim_does_not_switch_with_sample_size(self) -> None:
        statuses = []
        reports = []
        for count in (5, 100):
            all_ids = set(range(1, count + 1))
            result, report, _ = self.run_analyzer(
                NO_COLLISION, count, all_ids, all_ids
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            assert report is not None
            reports.append(report)
            statuses.append((report["workflow"], report["status"]))
        self.assertEqual(
            statuses,
            [
                ("transport_no_collision", "NOT_EVALUATED"),
                ("transport_no_collision", "PASS"),
            ],
        )
        self.assertFalse(reports[0]["sample_size_eligible"])
        self.assertEqual(reports[0]["gates"], {})
        self.assertTrue(reports[1]["sample_size_eligible"])

    def test_duplicate_event_is_an_execution_error(self) -> None:
        result, report, _ = self.run_analyzer(
            INTERFACE,
            100,
            set(range(1, 81)),
            set(range(1, 81)),
            duplicate_source=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(report)
        self.assertIn("duplicate particle event", result.stderr)

    def test_shared_core_has_no_claim_vocabulary(self) -> None:
        source = CORE.read_text(encoding="utf-8").lower()
        for forbidden in (
            "solver",
            "comsol",
            "simion",
            "mode",
            "role",
            "threshold",
            "decision",
        ):
            self.assertNotIn(forbidden, source)
        tree = ast.parse(source)
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        arguments = {
            argument.arg
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in (*node.args.args, *node.args.kwonlyargs)
        }
        self.assertTrue(
            names.isdisjoint({"within", "acceptance", "threshold", "limit"})
        )
        self.assertTrue(
            arguments.isdisjoint(
                {"maximum", "limit", "acceptance", "threshold"}
            )
        )


if __name__ == "__main__":
    unittest.main()
