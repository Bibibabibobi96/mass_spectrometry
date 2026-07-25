from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    generate_bundle,
)
from projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
ANALYZER = PROJECT_ROOT / "analysis" / "compare_same_solver_numerics.py"
CONTRACT = PROJECT_ROOT / "config" / "same_solver_numerical_convergence.json"
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class SameSolverNumericalConvergenceTests(unittest.TestCase):
    particles = 100

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle_temporary = tempfile.TemporaryDirectory()
        root = Path(cls.bundle_temporary.name)
        cls.source_family = (
            PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
        )
        cls.distribution = (
            PROJECT_ROOT / "config" / "official_particle_source.json"
        )
        cls.resolved_design = (
            PROJECT_ROOT / "config" / "resolved_design_official.json"
        )
        cls.primary_bundle = root / "primary"
        cls.alternate_bundle = root / "alternate"
        generate_bundle(
            cls.source_family,
            cls.distribution,
            cls.resolved_design,
            cls.primary_bundle,
        )
        generate_bundle(
            cls.source_family,
            cls.distribution,
            cls.resolved_design,
            cls.alternate_bundle,
            seed=8675309,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.bundle_temporary.cleanup()

    def test_contract_freezes_candidate_only_matrix_and_thresholds(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["status"], "numerical_screen_candidate_only")
        self.assertEqual(
            contract["required_mode"],
            "transport_interface_readiness",
        )
        self.assertEqual(
            contract["simion_solver_numerics_contract"],
            "config/simion_solver_numerics.json",
        )
        simion_numerics = json.loads(
            (PROJECT_ROOT / contract["simion_solver_numerics_contract"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(simion_numerics["baseline_rf_steps_per_period"], 40)
        self.assertEqual(simion_numerics["allowed_rf_steps_per_period"], [40, 80])
        self.assertEqual(
            contract["comparisons"]["SIMION"]["baseline_value_source"],
            "baseline_rf_steps_per_period",
        )
        self.assertEqual(
            contract["comparisons"]["COMSOL"]["baseline_value"],
            80,
        )
        self.assertEqual(
            contract["comparisons"]["COMSOL"]["refined_value"],
            160,
        )
        self.assertEqual(
            contract["acceptance"],
            {
                "transmission_absolute_difference": 0.01,
                "mean_tof_relative_difference": 0.01,
                "rms_radius_relative_difference": 0.02,
                "rms_divergence_relative_difference": 0.03,
                "mean_energy_relative_difference": 0.004,
                "handoff_particle_id_sets": "exact_match",
            },
        )

    def write_state(
        self,
        path: Path,
        handoff_ids: set[int],
        *,
        tof_scale: float = 1.0,
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
            writer.writeheader()
            for particle_id in range(1, self.particles + 1):
                writer.writerow({"particle_id": particle_id, "event": "source"})
                writer.writerow(
                    {
                        "particle_id": particle_id,
                        "event": "rod_exit",
                        "elapsed_time_us": 5,
                        "radial_position_mm": 0.01,
                        "divergence_angle_deg": 0.01,
                        "kinetic_energy_eV": 2,
                        "max_rod_radius_mm": 0.1,
                        "transverse_x_mm": 0.01,
                        "transverse_y_mm": 0,
                        "velocity_axial_m_s": 1000,
                        "velocity_x_m_s": 0,
                        "velocity_y_m_s": 0,
                        "rf_phase_rad": 0,
                    }
                )
                if particle_id in handoff_ids:
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "event": "handoff",
                            "elapsed_time_us": (10 + particle_id / 10) * tof_scale,
                            "radial_position_mm": particle_id / 100,
                            "divergence_angle_deg": particle_id / 100,
                            "kinetic_energy_eV": 2,
                            "max_rod_radius_mm": 0.1,
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

    def make_run(
        self,
        root: Path,
        name: str,
        *,
        solver: str,
        steps: int,
        handoff_ids: set[int],
        bundle_root: Path,
        tof_scale: float = 1.0,
        mesh_elements: int = 1000,
        other_numerical: int = 10,
        pa_hash_suffix: str = "A",
        provenance_drift: str | None = None,
    ) -> Path:
        run = root / name
        results = run / "results"
        simion = run / "simion"
        results.mkdir(parents=True)
        simion.mkdir()
        state = results / "particle_state.csv"
        summary = results / "solver_summary.json"
        self.write_state(state, handoff_ids, tof_scale=tof_scale)
        ion11 = bundle_root / "official_100amu_2eV_n100.ion"
        canonical10 = (
            bundle_root / "official_100amu_2eV_n100_canonical.csv"
        )
        consumed_representation = "canonical10" if solver == "SIMION" else "ion11"
        particles = canonical10 if solver == "SIMION" else ion11
        bundle_metadata = bundle_root / "paired_particle_bundle.json"
        binding = resolve_binding(
            bundle_metadata,
            self.source_family,
            self.distribution,
            self.resolved_design,
            "official_100amu_2eV",
            self.particles,
            consumed_representation,
            particles,
        )
        binding_path = run / "particle_source_binding.json"
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        summary.write_text(
            json.dumps(
                {
                    "solver": solver,
                    "mesh_elements_total": mesh_elements
                    if solver == "COMSOL"
                    else None,
                }
            ),
            encoding="utf-8",
        )
        outputs = [record(state), record(summary)]
        inputs = {
            "particle_table": record(particles),
            "consumed_particle_table": record(particles),
            "source_ion11": record(ion11),
            "source_canonical10": record(canonical10),
            "particle_bundle_metadata": record(bundle_metadata),
            "particle_source_binding": record(binding_path),
            "particle_source_family": record(self.source_family),
            "particle_source_distribution": record(self.distribution),
            "resolved_design": record(self.resolved_design),
        }
        if solver == "SIMION":
            inventory = simion / "SHA256SUMS.csv"
            pa0 = simion / "quad_monolithic.pa0"
            pa1 = simion / "quad_monolithic.pa1"
            pa0.write_bytes(pa_hash_suffix.encode("ascii") * 10)
            pa1.write_bytes(pa_hash_suffix.encode("ascii") * 11)
            with inventory.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=("file", "bytes", "sha256"),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "file": "quad_monolithic.pa0",
                        "bytes": pa0.stat().st_size,
                        "sha256": sha256(pa0),
                    }
                )
                writer.writerow(
                    {
                        "file": "quad_monolithic.pa1",
                        "bytes": pa1.stat().st_size,
                        "sha256": sha256(pa1),
                    }
                )
            outputs.append(record(inventory))
        varied = (
            "rf_steps_per_period"
            if solver == "SIMION"
            else "comsol_rf_steps_per_period"
        )
        config = {
            "schema_version": 1,
            "role": f"rf_quadrupole_{solver.lower()}_run_config",
            "run_id": name,
            "project": "rf_quadrupole_collision_cooling",
            "mode": "transport_interface_readiness",
            "project_root": str(PROJECT_ROOT),
            "inputs": {
                name: str(Path(identity["path"]).resolve())
                for name, identity in inputs.items()
            },
            "run_dir": str(run.resolve()),
            "results_dir": str(results.resolve()),
            varied: steps,
            "trajectory_quality"
            if solver == "SIMION"
            else "comsol_mesh_auto_level": other_numerical,
            "operating_point": "official_100amu_2eV",
            "source_axial_offset_mm": 0,
            "rf_peak_v": 139.81792,
            "frequency_hz": 1100000,
            "particles": self.particles,
            "formal_gate_passed": False,
            "provenance": {
                field: binding[field]
                for field in (
                    "source_sample_family_sha256",
                    "source_family_sha256",
                    "distribution_sha256",
                    "latent_sha256",
                    "coordinate_mapping_version",
                    "representation_equivalence",
                    "operating_point_id",
                    "particle_count",
                    "representation",
                    "consumed_sha256",
                    "ion11_sha256",
                    "canonical10_sha256",
                    "n1000_parent",
                    "ion11_n1000_parent",
                    "canonical10_n1000_parent",
                )
            },
        }
        if solver == "SIMION":
            config["provenance"]["rf_steps_per_period"] = steps
            config["provenance"]["rf_steps_override"] = steps != 40
        if provenance_drift is not None:
            config["provenance"]["unrelated_identity"] = provenance_drift
        config_path = run / "run_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "role": "simulation_run_manifest",
            "run_id": name,
            "project": config["project"],
            "mode": config["mode"],
            "status": "success",
            "software": [solver],
            "run_config": record(config_path),
            "inputs": inputs,
            "outputs": outputs,
        }
        manifest_path = run / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def run_case(
        self,
        *,
        solver: str,
        baseline_steps: int,
        refined_steps: int,
        baseline_handoffs: set[int] | None = None,
        refined_handoffs: set[int] | None = None,
        refined_tof_scale: float = 1.0,
        refined_bundle: Path | None = None,
        refined_mesh_elements: int = 1000,
        refined_other_numerical: int = 10,
        refined_pa_hash_suffix: str = "A",
        refined_provenance_drift: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        all_ids = set(range(1, self.particles + 1))
        baseline = self.make_run(
            root,
            "baseline",
            solver=solver,
            steps=baseline_steps,
            bundle_root=self.primary_bundle,
            handoff_ids=baseline_handoffs
            if baseline_handoffs is not None
            else all_ids,
        )
        refined = self.make_run(
            root,
            "refined",
            solver=solver,
            steps=refined_steps,
            bundle_root=refined_bundle or self.primary_bundle,
            handoff_ids=refined_handoffs
            if refined_handoffs is not None
            else all_ids,
            tof_scale=refined_tof_scale,
            mesh_elements=refined_mesh_elements,
            other_numerical=refined_other_numerical,
            pa_hash_suffix=refined_pa_hash_suffix,
            provenance_drift=refined_provenance_drift,
        )
        output = root / "comparison.json"
        census = root / "particle_census.csv"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "projects.rf_quadrupole_collision_cooling.analysis.compare_same_solver_numerics",
                "--baseline-manifest",
                str(baseline),
                "--refined-manifest",
                str(refined),
                "--contract",
                str(CONTRACT),
                "--output",
                str(output),
                "--census-output",
                str(census),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        return result, output, census

    def test_registered_simion_40_to_80_passes(self) -> None:
        result, output, census = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["execution_status"], "success")
        self.assertEqual(len(read_csv(census)), self.particles)

    def test_unrelated_simion_provenance_drift_is_rejected(self) -> None:
        result, _, _ = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            refined_provenance_drift="changed",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "differ outside the preregistered numerical parameter",
            result.stderr,
        )

    def test_registered_comsol_80_to_160_passes(self) -> None:
        result, output, _ = self.run_case(
            solver="COMSOL",
            baseline_steps=80,
            refined_steps=160,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["gates"]["mesh_element_identity"])

    def test_handoff_id_mismatch_is_complete_decision_failure(self) -> None:
        result, output, census = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            refined_handoffs={1, 2, 3, 4},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["gates"]["handoff_particle_id_sets"])
        rows = read_csv(census)
        self.assertEqual(len(rows), self.particles)
        self.assertEqual(rows[-1]["handoff_pair_status"], "baseline_only")

    def test_empty_handoff_metrics_fail_closed(self) -> None:
        result, output, _ = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            baseline_handoffs=set(),
            refined_handoffs=set(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "FAIL")
        self.assertIsNone(report["metrics"]["mean_tof_relative_difference"])

    def test_metric_over_threshold_is_decision_failure(self) -> None:
        result, output, _ = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            refined_tof_scale=1.02,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["gates"]["mean_tof"])

    def test_unregistered_step_pair_is_rejected(self) -> None:
        result, output, _ = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=160,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_source_sha_mismatch_is_rejected(self) -> None:
        result, output, _ = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            refined_bundle=self.alternate_bundle,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_other_numerical_setting_change_is_rejected(self) -> None:
        result, output, _ = self.run_case(
            solver="COMSOL",
            baseline_steps=80,
            refined_steps=160,
            refined_other_numerical=11,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_comsol_mesh_element_change_is_decision_failure(self) -> None:
        result, output, _ = self.run_case(
            solver="COMSOL",
            baseline_steps=80,
            refined_steps=160,
            refined_mesh_elements=1001,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["gates"]["mesh_element_identity"])

    def test_simion_pa_core_sha_change_is_rejected(self) -> None:
        result, output, _ = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            refined_pa_hash_suffix="B",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_managed_runner_separates_execution_and_decision(self) -> None:
        runner = (
            PROJECT_ROOT
            / "tests"
            / "analysis"
            / "run_same_solver_numerical_comparison.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("--require-status success", runner)
        self.assertIn("--status failed", runner)
        self.assertIn("decision_status=$report.status", runner)
        success_manifest = runner.index("--status success")
        decision_failure = runner.index("if ($report.status -ne 'PASS')")
        self.assertLess(success_manifest, decision_failure)
        self.assertIn("baseline_pa_inventory", runner)
        self.assertIn("refined_pa_inventory", runner)

    def test_comsol_solver_summary_records_mesh_element_count(self) -> None:
        builder = (
            PROJECT_ROOT / "comsol" / "ms_rf_quadrupole_no_collision.m"
        ).read_text(encoding="utf-8")
        self.assertIn("'mesh_elements_total',sum(mi.numelem)", builder)


if __name__ == "__main__":
    unittest.main()
