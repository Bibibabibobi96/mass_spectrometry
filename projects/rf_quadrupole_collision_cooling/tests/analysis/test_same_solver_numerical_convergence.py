from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
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
PARTICLE_COUNT_POLICY = (
    REPO_ROOT / "common" / "contracts" / "particle_count_policy.json"
)
PORTABLE_INPUT_ROLES = [
    "particle_table",
    "consumed_particle_table",
    "source_ion11",
    "source_canonical10",
    "particle_bundle_metadata",
    "particle_source_family",
    "particle_source_distribution",
    "resolved_design",
]
PORTABLE_SIMION_OUTPUT_ROLES = {
    "particle_state": "particle_state.csv",
    "solver_summary": "solver_summary.json",
    "pa_core_inventory": "SHA256SUMS.csv",
}
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


def iter_path_values(value: object) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower()
            is_path_key = (
                normalized in {"path", "file", "relative_path", "source"}
                or normalized.endswith("_path")
                or normalized.endswith("_dir")
            )
            if is_path_key and isinstance(item, str) and item:
                paths.append(item)
            paths.extend(iter_path_values(item))
    elif isinstance(value, list):
        for item in value:
            paths.extend(iter_path_values(item))
    return paths


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

    def copy_portable_closure(
        self,
        manifest: Path,
        destination: Path,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            **os.environ,
            "RF_REPO": str(REPO_ROOT),
            "RF_PROJECT": str(PROJECT_ROOT),
            "RF_MANIFEST": str(manifest),
            "RF_DESTINATION": str(destination),
            "RF_INPUT_ROLES": json.dumps(PORTABLE_INPUT_ROLES),
            "RF_OUTPUT_ROLES": json.dumps(PORTABLE_SIMION_OUTPUT_ROLES),
        }
        command = (
            ". (Join-Path $env:RF_REPO "
            "'common/contracts/run_artifact_support.ps1');"
            ". (Join-Path $env:RF_PROJECT "
            "'runtime/analysis_run_lifecycle.ps1');"
            "$inputRoles=ConvertFrom-Json $env:RF_INPUT_ROLES;"
            "$outputRoles=ConvertFrom-Json "
            "$env:RF_OUTPUT_ROLES -AsHashtable;"
            "$closure=Copy-PortableRunManifestClosure "
            "-SourceManifest $env:RF_MANIFEST "
            "-Destination $env:RF_DESTINATION "
            "-RequiredInputRoles $inputRoles "
            "-RequiredOutputRoles $outputRoles "
            "-BundleMetadataInputRole 'particle_bundle_metadata';"
            "$closure.manifest"
        )
        return subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            timeout=60,
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=environment,
        )

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
        particle_count: int | None = None,
    ) -> None:
        count = self.particles if particle_count is None else particle_count
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
            writer.writeheader()
            for particle_id in range(1, count + 1):
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
        particle_count: int | None = None,
        numerics_profile_override: str | None = None,
        compiled_authority_override: str | None = None,
        compiled_time_override: float | None = None,
    ) -> Path:
        count = self.particles if particle_count is None else particle_count
        run = root / name
        results = run / "results"
        simion = run / "simion"
        results.mkdir(parents=True)
        simion.mkdir()
        state = results / "particle_state.csv"
        summary = results / "solver_summary.json"
        self.write_state(
            state,
            handoff_ids,
            tof_scale=tof_scale,
            particle_count=count,
        )
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
        if solver == "COMSOL":
            inputs["comsol_solver_numerics"] = record(
                PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
            )
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
        comsol_logical_sha = (
            json.loads(
                (
                    PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
                ).read_text(encoding="utf-8")
            )["logical_sha256"]
            if solver == "COMSOL"
            else None
        )
        profile_id = (
            numerics_profile_override
            or ("baseline" if steps == 80 else "time_refined_160")
        )
        experiment_id = (
            "" if steps == 80 else "same_solver_numerical_convergence"
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
            "particles": count,
            "solver_numerics_contract_id": (
                "rf_quadrupole.comsol_solver_numerics.v1"
                if solver == "COMSOL"
                else None
            ),
            "solver_numerics_contract_logical_sha256": comsol_logical_sha,
            "solver_numerics_profile_id": (
                profile_id
                if solver == "COMSOL"
                else None
            ),
            "numerical_experiment_id": (
                experiment_id if solver == "COMSOL" else None
            ),
            "compiled_solver_numerics": (
                {
                    "schema_version": 1,
                    "role": "rf_quadrupole_compiled_comsol_solver_numerics",
                    "authority": {
                        "contract_id": "rf_quadrupole.comsol_solver_numerics.v1",
                        "logical_sha256": comsol_logical_sha,
                    },
                    "selection": {
                        "profile_id": profile_id,
                        "usage": (
                            "production"
                            if steps == 80
                            else "registered_experiment"
                        ),
                        "numerical_experiment_id": experiment_id,
                    },
                    "mesh": {
                        "global_auto_level": other_numerical,
                        "working_region_hmax_override_enabled": False,
                    },
                    "trajectory": {
                        "rf_steps_per_period": steps,
                        "maximum_time_us": 80.0,
                    },
                }
                if solver == "COMSOL"
                else None
            ),
            "maximum_time_us": 80.0,
            "output_policy": {
                "save_model": True,
                "write_detailed_outputs": True,
            },
            "parameters": {
                "lifecycle_stage": "inputs_frozen_and_validated",
            },
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
        else:
            config["provenance"]["solver_numerics_sha256"] = sha256(
                PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
            )
            if compiled_authority_override is not None:
                config["compiled_solver_numerics"]["authority"][
                    "logical_sha256"
                ] = compiled_authority_override
            if compiled_time_override is not None:
                config["compiled_solver_numerics"]["trajectory"][
                    "maximum_time_us"
                ] = compiled_time_override
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
        particle_count: int | None = None,
        refined_numerics_profile_override: str | None = None,
        refined_compiled_authority_override: str | None = None,
        refined_compiled_time_override: float | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        count = self.particles if particle_count is None else particle_count
        all_ids = set(range(1, count + 1))
        baseline = self.make_run(
            root,
            "baseline",
            solver=solver,
            steps=baseline_steps,
            bundle_root=self.primary_bundle,
            handoff_ids=baseline_handoffs
            if baseline_handoffs is not None
            else all_ids,
            particle_count=count,
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
            particle_count=count,
            numerics_profile_override=refined_numerics_profile_override,
            compiled_authority_override=refined_compiled_authority_override,
            compiled_time_override=refined_compiled_time_override,
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
                "--particle-count-policy",
                str(PARTICLE_COUNT_POLICY),
                "--output",
                str(output),
                "--census-output",
                str(census),
            ],
            cwd=REPO_ROOT,
            timeout=120,
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

    def test_below_functional_particle_count_is_not_evaluated(self) -> None:
        result, output, census = self.run_case(
            solver="SIMION",
            baseline_steps=40,
            refined_steps=80,
            particle_count=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "NOT_EVALUATED")
        self.assertFalse(report["sample_size_eligible"])
        self.assertEqual(report["minimum_functional_particles"], 100)
        self.assertEqual(report["gates"], {})
        self.assertEqual(len(read_csv(census)), 5)

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

    def test_comsol_derived_numerics_profile_drift_is_rejected(self) -> None:
        result, output, _ = self.run_case(
            solver="COMSOL",
            baseline_steps=80,
            refined_steps=160,
            refined_numerics_profile_override="baseline",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertIn("numerical profile identity differs", result.stderr)

    def test_comsol_compiled_authority_or_time_drift_is_rejected(self) -> None:
        for arguments in (
            {"refined_compiled_authority_override": "0" * 64},
            {"refined_compiled_time_override": 81.0},
        ):
            with self.subTest(arguments=arguments):
                result, output, _ = self.run_case(
                    solver="COMSOL",
                    baseline_steps=80,
                    refined_steps=160,
                    **arguments,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())
                self.assertIn(
                    "numerical profile identity differs", result.stderr
                )

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
        self.assertIn("Complete-FailedRun", runner)
        self.assertIn("decision_status=$decisionStatus", runner)
        success_manifest = runner.index("-Status success")
        decision_failure = runner.index("if ($decisionStatus -ne 'PASS')")
        self.assertLess(success_manifest, decision_failure)
        self.assertIn("Copy-VerifiedRunInput", runner)
        self.assertIn("Save-RunEnvironment", runner)
        self.assertIn("--simion-numerics $frozenSimionNumerics", runner)
        self.assertIn("Copy-PortableRunManifestClosure", runner)
        self.assertIn("-RequiredInputRoles $requiredInputRoles", runner)
        self.assertIn("-RequiredOutputRoles $requiredOutputRoles", runner)
        self.assertNotIn("Source success manifest verification failed", runner)
        self.assertIn("Portable source closure verification failed", runner)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_portable_source_closure_survives_live_run_removal(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        all_ids = set(range(1, self.particles + 1))
        baseline = self.make_run(
            root,
            "baseline",
            solver="SIMION",
            steps=40,
            handoff_ids=all_ids,
            bundle_root=self.primary_bundle,
        )
        refined = self.make_run(
            root,
            "refined",
            solver="SIMION",
            steps=80,
            handoff_ids=all_ids,
            bundle_root=self.primary_bundle,
        )
        for manifest_path in (baseline, refined):
            run_root = manifest_path.parent
            unused_model = run_root / "results" / "unused_large_model.mph"
            unused_log = run_root / "results" / "unused_solver.log"
            unused_model.write_bytes(b"M" * (2 * 1024 * 1024))
            unused_log.write_text("unused diagnostic log\n", encoding="utf-8")
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            document["outputs"].extend(
                (record(unused_model), record(unused_log))
            )
            manifest_path.write_text(json.dumps(document), encoding="utf-8")
        closure = root / "closure"
        copies = [
            self.copy_portable_closure(
                baseline,
                closure / "baseline",
            ),
            self.copy_portable_closure(
                refined,
                closure / "refined",
            ),
        ]
        for completed in copies:
            self.assertEqual(completed.returncode, 0, completed.stderr)
        manifests = [
            Path(completed.stdout.splitlines()[-1])
            for completed in copies
        ]
        for manifest_path in manifests:
            verified = subprocess.run(
                [
                    sys.executable,
                    str(
                        REPO_ROOT
                        / "common"
                        / "contracts"
                        / "verify_run_manifest.py"
                    ),
                    str(manifest_path),
                    "--require-status",
                    "success",
                    "--require-project",
                    "rf_quadrupole_collision_cooling",
                ],
                cwd=REPO_ROOT,
                timeout=30,
                capture_output=True,
                check=False,
                encoding="utf-8",
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                set(document["inputs"]),
                {
                    "particle_table",
                    "consumed_particle_table",
                    "source_ion11",
                    "source_canonical10",
                    "particle_bundle_metadata",
                    "particle_source_family",
                    "particle_source_distribution",
                    "resolved_design",
                },
            )
            self.assertEqual(
                {Path(record["path"]).name for record in document["outputs"]},
                {
                    "particle_state.csv",
                    "solver_summary.json",
                    "SHA256SUMS.csv",
                },
            )
            paths = [
                document["run_config"]["path"],
                document["portable_closure"]["source_run_identity"]["path"],
                *[record["path"] for record in document["inputs"].values()],
                *[record["path"] for record in document["outputs"]],
            ]
            self.assertTrue(
                all(Path(path).is_relative_to(closure) for path in paths)
            )
            identity_path = Path(
                document["portable_closure"]["source_run_identity"]["path"]
            )
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(identity["role"], "portable_source_run_identity")
            self.assertNotIn("inputs", identity)
            self.assertNotIn("outputs", identity)
            bundle_path = Path(
                document["inputs"]["particle_bundle_metadata"]["path"]
            )
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            relative_artifacts = [
                entry["relative_path"] for entry in bundle["artifacts"]
            ]
            artifact_targets = [
                (bundle_path.parent / relative).resolve()
                for relative in relative_artifacts
            ]
            self.assertEqual(
                len({relative.casefold() for relative in relative_artifacts}),
                len(relative_artifacts),
            )
            self.assertEqual(
                len({str(path).casefold() for path in artifact_targets}),
                len(artifact_targets),
            )
            self.assertTrue(all(path.is_file() for path in artifact_targets))
            evidence_text = (
                manifest_path.read_text(encoding="utf-8")
                + identity_path.read_text(encoding="utf-8")
            )
            for forbidden in (
                str(baseline.parent.resolve()),
                str(refined.parent.resolve()),
                "unused_large_model.mph",
                "unused_solver.log",
                "quad_monolithic.pa0",
                "quad_monolithic.pa1",
            ):
                self.assertNotIn(forbidden, evidence_text)
        copied_files = [
            path for path in closure.rglob("*") if path.is_file()
        ]
        self.assertFalse(
            any(path.suffix.lower() in {".mph", ".log"} for path in copied_files)
        )
        self.assertFalse(
            any(path.name.lower().startswith("quad_monolithic.pa")
                for path in copied_files)
        )
        for evidence_file in copied_files:
            if evidence_file.suffix.lower() == ".json":
                document = json.loads(
                    evidence_file.read_text(encoding="utf-8-sig")
                )
                values = iter_path_values(document)
            elif evidence_file.suffix.lower() == ".csv":
                values = [
                    value
                    for row in read_csv(evidence_file)
                    for key, value in row.items()
                    if value
                    and (
                        key.lower() in {"path", "file", "relative_path"}
                        or key.lower().endswith(("_path", "_dir"))
                    )
                ]
            else:
                continue
            for value in values:
                candidate = Path(value)
                resolved = (
                    candidate.resolve()
                    if candidate.is_absolute()
                    else (evidence_file.parent / candidate).resolve()
                )
                self.assertTrue(
                    resolved.is_relative_to(closure),
                    f"{evidence_file}: external path value {value}",
                )
        (root / "baseline").rename(root / "baseline_removed")
        (root / "refined").rename(root / "refined_removed")
        output = root / "portable_result.json"
        census = root / "portable_census.csv"
        analysis_arguments = [
            sys.executable,
            "-m",
            "projects.rf_quadrupole_collision_cooling.analysis.compare_same_solver_numerics",
            "--baseline-manifest",
            str(manifests[0]),
            "--refined-manifest",
            str(manifests[1]),
            "--contract",
            str(CONTRACT),
            "--particle-count-policy",
            str(PARTICLE_COUNT_POLICY),
            "--output",
            str(output),
            "--census-output",
            str(census),
        ]
        result = subprocess.run(
            analysis_arguments,
            cwd=REPO_ROOT,
            timeout=120,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8"))["status"],
            "PASS",
        )
        baseline_document = json.loads(
            manifests[0].read_text(encoding="utf-8")
        )
        identity_path = Path(
            baseline_document["portable_closure"]["source_run_identity"]["path"]
        )
        original_identity = identity_path.read_bytes()
        tampered_bytes = original_identity.replace(
            b'"baseline"',
            b'"tampered"',
            1,
        )
        self.assertNotEqual(tampered_bytes, original_identity)
        identity_path.write_bytes(tampered_bytes)
        tampered_hash = subprocess.run(
            analysis_arguments,
            cwd=REPO_ROOT,
            timeout=120,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        self.assertNotEqual(tampered_hash.returncode, 0)
        self.assertIn("source-run identity SHA-256 changed", tampered_hash.stderr)
        identity_path.write_bytes(original_identity)

        identity = json.loads(original_identity)
        identity["run"]["run_id"] = "tampered"
        identity_path.write_text(json.dumps(identity), encoding="utf-8")
        baseline_document["portable_closure"]["source_run_identity"] = record(
            identity_path
        )
        manifests[0].write_text(
            json.dumps(baseline_document),
            encoding="utf-8",
        )
        tampered_identity = subprocess.run(
            analysis_arguments,
            cwd=REPO_ROOT,
            timeout=120,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        self.assertNotEqual(tampered_identity.returncode, 0)
        self.assertIn(
            "source-run identity differs from its closure",
            tampered_identity.stderr,
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_portable_source_closure_fails_when_required_file_is_missing(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        manifest_path = self.make_run(
            root,
            "missing_summary",
            solver="SIMION",
            steps=40,
            handoff_ids=set(range(1, self.particles + 1)),
            bundle_root=self.primary_bundle,
        )
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = next(
            Path(record["path"])
            for record in document["outputs"]
            if Path(record["path"]).name == "solver_summary.json"
        )
        summary.unlink()
        completed = self.copy_portable_closure(
            manifest_path,
            root / "closure",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("manifest output solver_summary is missing", completed.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_portable_copy_rejects_incomplete_or_ambiguous_evidence(
        self,
    ) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cases = (
            ("missing_role", "Required input role is missing: resolved_design"),
            ("input_hash", "manifest input particle_table SHA-256 differs"),
            ("output_hash", "manifest output solver_summary SHA-256 differs"),
            (
                "duplicate_output",
                "Required output role solver_summary must resolve exactly once",
            ),
            (
                "duplicate_bundle",
                "Bundle artifact inventory contains a duplicate",
            ),
        )
        for case, expected in cases:
            with self.subTest(case=case):
                bundle_root = self.primary_bundle
                if case == "duplicate_bundle":
                    bundle_root = root / f"{case}_bundle"
                    shutil.copytree(self.primary_bundle, bundle_root)
                manifest_path = self.make_run(
                    root,
                    case,
                    solver="SIMION",
                    steps=40,
                    handoff_ids=set(range(1, self.particles + 1)),
                    bundle_root=bundle_root,
                )
                document = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                if case == "missing_role":
                    del document["inputs"]["resolved_design"]
                elif case == "input_hash":
                    document["inputs"]["particle_table"]["sha256"] = "0" * 64
                elif case == "output_hash":
                    summary_record = next(
                        item
                        for item in document["outputs"]
                        if Path(item["path"]).name == "solver_summary.json"
                    )
                    summary_record["sha256"] = "0" * 64
                elif case == "duplicate_output":
                    summary_record = next(
                        item
                        for item in document["outputs"]
                        if Path(item["path"]).name == "solver_summary.json"
                    )
                    document["outputs"].append(dict(summary_record))
                else:
                    metadata_path = Path(
                        document["inputs"]["particle_bundle_metadata"]["path"]
                    )
                    metadata = json.loads(
                        metadata_path.read_text(encoding="utf-8")
                    )
                    metadata["artifacts"][1]["relative_path"] = (
                        metadata["artifacts"][0]["relative_path"]
                    )
                    metadata_path.write_text(
                        json.dumps(metadata),
                        encoding="utf-8",
                    )
                    document["inputs"]["particle_bundle_metadata"] = record(
                        metadata_path
                    )
                manifest_path.write_text(
                    json.dumps(document),
                    encoding="utf-8",
                )
                completed = self.copy_portable_closure(
                    manifest_path,
                    root / f"{case}_closure",
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)

    def test_analyzer_reuses_neutral_particle_state_core(self) -> None:
        analyzer = (
            PROJECT_ROOT / "analysis" / "compare_same_solver_numerics.py"
        ).read_text(encoding="utf-8")
        self.assertIn("particle_state_comparison_core", analyzer)
        self.assertNotIn("def load_event_table", analyzer)
        self.assertNotIn("def aggregate_handoff", analyzer)
        self.assertNotIn("math.hypot", analyzer)

    def test_comsol_solver_summary_records_mesh_element_count(self) -> None:
        builder = (
            PROJECT_ROOT / "comsol" / "ms_rf_quadrupole_no_collision.m"
        ).read_text(encoding="utf-8")
        self.assertIn("'mesh_elements_total',sum(mi.numelem)", builder)


if __name__ == "__main__":
    unittest.main()
