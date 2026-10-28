from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.contracts.capacity_ledger import initialize_capacity_ledger
from common.contracts.frozen_inputs import freeze_file
from common.ion_release.numpy_box_cone import sample_numpy_box_cone_phase_space
from projects.rf_multipole_ion_optics.workflows.mass_filter_reference import (
    run_finite_length as MODULE,
)

PROJECT_ROOT = Path(__file__).parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MassFilterL1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json")
        cls.resolved = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_mass_filter.json")
        cls.mode = load_json(PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json")
        cls.source = load_json(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json")

    @staticmethod
    def _run(artifact_root: Path, run_id: str) -> Path:
        return MODULE.run(
            MODULE.DEFAULT_BASELINE, MODULE.DEFAULT_RESOLVED, MODULE.DEFAULT_MODE,
            MODULE.DEFAULT_SOURCE, run_id, artifact_root,
        )

    @staticmethod
    def _synthetic_response(mass: float, particles: dict, resolved: dict, steps: int) -> dict:
        count = len(particles["x_m"])
        transmitted = count if 99.5 <= mass <= 103.5 else 0
        return {"mass_Th": mass, "particles": count, "transmitted": transmitted,
                "transmission_fraction": transmitted / count}

    def test_run_failures_publish_triplet_and_preserve_original_error(self) -> None:
        for index, stage in enumerate(("input_freezing", "analysis_preparation", "simulation", "analysis_execution")):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                capacity_root = Path(temporary) / "artifacts"
                capacity_root.mkdir()
                initialize_capacity_ledger(capacity_root, objects=[])
                artifact_root = capacity_root / "projects/rf_multipole_ion_optics"
                run_id = f"20261028_12000{index}__test__python__l1-failure"
                destination = artifact_root / "runs" / run_id
                error = OSError(f"injected {stage} failure")
                invoke = MODULE._invoke_analysis_stage

                def freeze(source: Path, target: Path) -> dict:
                    if target.name == "baseline.json":
                        initial = MODULE.load_json(destination / "run_manifest.json")
                        self.assertEqual(initial["status"], "checkpoint")
                    if stage == "input_freezing" and target.name == "resolved_design_mass_filter.json":
                        raise error
                    return freeze_file(source, target)

                def analysis(request: Path, *, prepare_only: bool) -> dict:
                    if stage == ("analysis_preparation" if prepare_only else "analysis_execution"):
                        raise error
                    return invoke(request, prepare_only=prepare_only)

                with patch("common.contracts.frozen_inputs.freeze_file", side_effect=freeze), \
                     patch.object(MODULE, "_invoke_analysis_stage", side_effect=analysis), \
                     patch.object(MODULE, "simulate_mass", side_effect=(
                         error if stage == "simulation" else self._synthetic_response)):
                    with self.assertRaises(OSError) as caught:
                        self._run(artifact_root, run_id)
                self.assertIs(caught.exception, error)
                config = MODULE.load_json(destination / "run_config.json")
                summary = MODULE.load_json(destination / "summary.json")
                manifest = MODULE.load_json(destination / "run_manifest.json")
                self.assertEqual(config["parameters"]["lifecycle_stage"], stage)
                self.assertEqual(config["parameters"]["requested_input_paths"]["baseline"],
                                 str(MODULE.DEFAULT_BASELINE.resolve()))
                self.assertEqual((summary["status"], summary["failure_stage"], summary["reason"]),
                                 ("failed", stage, f"OSError: {error}"))
                self.assertFalse(summary["threshold_result_eligible"])
                self.assertEqual(summary["model_level"], "L1")
                self.assertEqual(manifest["status"], "failed")
                for document in (config, manifest):
                    self.assertEqual(document["run_id"], run_id)
                    self.assertEqual(document["project"], "rf_multipole_ion_optics")
                    self.assertEqual(document["mode"], "mass_filter_reference")
                frozen_paths = {Path(item["path"]) for item in manifest["inputs"].values()}
                self.assertIn(destination / "inputs/baseline.json", frozen_paths)
                if stage != "input_freezing":
                    self.assertIn(destination / "inputs/analysis_request.json", frozen_paths)
                if stage == "analysis_execution":
                    self.assertIn(destination / "inputs/mass_response_for_analysis.csv", frozen_paths)
                if stage in ("simulation", "analysis_execution"):
                    self.assertIn(destination / "inputs/analysis_package.json", frozen_paths)
                if stage == "simulation":
                    self.assertFalse((destination / "inputs/mass_response_for_analysis.csv").exists())
                    self.assertFalse((destination / "results/mass-response__finite-length.csv").exists())
                    self.assertFalse((destination / "results/mass-filter__functional-metrics.json").exists())
                original = {name: (destination / name).read_bytes() for name in
                            ("run_config.json", "summary.json", "run_manifest.json")}
                with self.assertRaises(FileExistsError):
                    self._run(artifact_root, run_id)
                self.assertEqual(original, {name: (destination / name).read_bytes() for name in original})

    def test_run_success_and_physical_failure_keep_published_terminal(self) -> None:
        for passed in (True, False):
            with self.subTest(passed=passed), tempfile.TemporaryDirectory() as temporary:
                capacity_root = Path(temporary) / "artifacts"
                capacity_root.mkdir()
                initialize_capacity_ledger(capacity_root, objects=[])
                artifact_root = capacity_root / "projects/rf_multipole_ion_optics"
                run_id = "20261028_120005__test__python__l1-terminal"
                destination = artifact_root / "runs" / run_id

                def response(*args: object) -> dict:
                    result = self._synthetic_response(*args)
                    if not passed:
                        result.update(transmitted=0, transmission_fraction=0.0)
                    return result

                with patch.object(MODULE, "simulate_mass", side_effect=response):
                    if passed:
                        self.assertEqual(self._run(artifact_root, run_id), destination)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "functional gate failed"):
                            self._run(artifact_root, run_id)
                config = MODULE.load_json(destination / "run_config.json")
                summary = MODULE.load_json(destination / "summary.json")
                manifest = MODULE.load_json(destination / "run_manifest.json")
                metrics = MODULE.load_json(destination / "results/mass-filter__functional-metrics.json")
                self.assertEqual(summary["functional_gate"], "PASS" if passed else "FAIL")
                self.assertNotIn("failure_class", summary)
                self.assertEqual(manifest["status"], "success" if passed else "failed")
                self.assertEqual(config["parameters"]["lifecycle_stage"], "complete")
                self.assertEqual(metrics["particle_count_per_mass"], self.mode["functional_screen"]["particle_count"])
                self.assertTrue(config["frozen_python_analysis"]["environment"]["module_invoked"])
                self.assertTrue((destination / "results/mass-response__passband.png").is_file())
                self.assertFalse(manifest["formal_eligible"])
                if passed:
                    self.assertEqual(metrics["sampled_response_analysis"]["interpolated_main_peak_fwhm_Th"], 4.5)

    def test_run_cleanup_preserves_original_error_and_existing_terminal(self) -> None:
        for published in (False, True):
            with self.subTest(published=published), tempfile.TemporaryDirectory() as temporary:
                capacity_root = Path(temporary) / "artifacts"
                capacity_root.mkdir()
                initialize_capacity_ledger(capacity_root, objects=[])
                artifact_root = capacity_root / "projects/rf_multipole_ion_optics"
                run_id = "20261028_120006__test__python__l1-cleanup"
                destination = artifact_root / "runs" / run_id
                error = OSError("original workflow failure")
                invoke = MODULE._invoke_run_artifact_support
                prepare = MODULE._prepare_analysis_request
                terminal = {}

                def lifecycle(command: str, arguments: dict) -> None:
                    if not published and "Complete-FailedRun" in command:
                        raise RuntimeError("injected cleanup failure")
                    invoke(command, arguments)
                    if published and "Write-VerifiedRunManifest" in command:
                        terminal.update({name: (destination / name).read_bytes() for name in
                                         ("run_config.json", "summary.json", "run_manifest.json")})
                        raise error

                def prepare_analysis(*args: Path) -> tuple:
                    if not published:
                        raise error
                    return prepare(*args)

                with patch.object(MODULE, "_invoke_run_artifact_support", side_effect=lifecycle), \
                     patch.object(MODULE, "_prepare_analysis_request", side_effect=prepare_analysis), \
                     patch.object(MODULE, "simulate_mass", side_effect=self._synthetic_response):
                    with self.assertRaises(OSError) as caught:
                        self._run(artifact_root, run_id)
                self.assertIs(caught.exception, error)
                if published:
                    self.assertEqual(terminal, {name: (destination / name).read_bytes() for name in terminal})
                    self.assertEqual(MODULE.load_json(destination / "run_manifest.json")["status"], "success")
                else:
                    self.assertIn("injected cleanup failure", str(error.__notes__))
                    self.assertEqual(MODULE.load_json(destination / "run_manifest.json")["status"], "checkpoint")

    def test_contract_brackets_theory_passband(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        self.assertAlmostEqual(derived["theory_low_mass_Th"], 99.3275, delta=0.001)
        self.assertAlmostEqual(derived["theory_high_mass_Th"], 103.4120, delta=0.001)
        self.assertAlmostEqual(derived["calibration_mass_Th"], 101.3707, delta=0.001)

    def test_l1_charge_is_exactly_positive_one_without_integer_truncation(self) -> None:
        for charge in (True, 1.5, -1, 0, float("nan"), float("inf")):
            with self.subTest(charge=charge), self.assertRaisesRegex(ValueError, "singly charged"):
                MODULE.validate_l1_contract(self.baseline, self.mode, {**self.source, "charge_state": charge})

    def test_sample_envelope_and_existing_functional_values_are_preserved(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        rows = [{"mass_Th": mass, "transmission_fraction": float(99.5 <= mass <= 103.5)}
                for mass in derived["masses_Th"]]
        result = MODULE.evaluate_response(rows, derived, self.mode)
        self.assertEqual({key: value for key, value in result.items() if key != "sampled_response_analysis"}, {
            "status": "PASS", "checks": {name: True for name in (
                "peak_transmission", "inside_band_transmission", "outside_endpoint_rejection",
                "low_boundary_alignment", "high_boundary_alignment")},
            "peak_mass_Th": 99.5, "peak_transmission": 1.0,
            "minimum_inside_theory_band_transmission": 1.0, "maximum_scan_endpoint_transmission": 0.0,
            "theory_passband_Th": [derived["theory_low_mass_Th"], derived["theory_high_mass_Th"]],
            "observed_half_maximum_band_Th": [99.5, 103.5], "mass_step_Th": 0.5,
        })
        self.assertEqual(result["sampled_response_analysis"]["interpolated_main_peak_fwhm_Th"], 4.5)
        for row in rows:
            row["transmission_fraction"] = 0.0
        zero = MODULE.evaluate_response(rows, derived, self.mode)
        self.assertEqual(zero["status"], "FAIL")
        self.assertIsNone(zero["observed_half_maximum_band_Th"])
        self.assertFalse(zero["checks"]["low_boundary_alignment"])
        self.assertFalse(zero["checks"]["high_boundary_alignment"])

    def test_frozen_l1_analysis_runs_from_snapshot_and_rejects_changed_peak_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, results = root / "inputs", root / "results"
            inputs.mkdir()
            results.mkdir()
            for filename, value in (("baseline.json", self.baseline), ("mass_filter_reference.json", self.mode),
                                    ("official_particle_source.json", self.source)):
                (inputs / filename).write_text(json.dumps(value), encoding="utf-8")
            derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
            count = int(self.mode["functional_screen"]["particle_count"])
            rows = [{"mass_Th": float(mass), "particles": count,
                     "transmitted": count if 99.5 <= mass <= 103.5 else 0,
                     "transmission_fraction": float(99.5 <= mass <= 103.5)}
                    for mass in derived["masses_Th"]]
            MODULE.write_response_csv(inputs / "mass_response_for_analysis.csv", rows)
            request, _ = MODULE._prepare_analysis_request(inputs, results)
            package = MODULE._invoke_analysis_stage(request, prepare_only=True)
            execution = MODULE._invoke_analysis_stage(request, prepare_only=False)
            self.assertTrue(execution["module_invoked"])
            origins = {entry["name"]: Path(entry["origin"]) for entry in execution["frozen_modules"]}
            for name in ("common.analysis.peak_metrics", "projects.rf_multipole_ion_optics.core.mass_response"):
                self.assertTrue(origins[name].is_relative_to(inputs / "analysis_code"))
            actual = load_json(results / "mass-filter__functional-metrics.json")
            self.assertEqual(actual["status"], "PASS")
            self.assertEqual(actual["sampled_response_analysis"], MODULE.evaluate_response(rows, derived, self.mode)["sampled_response_analysis"])
            self.assertTrue((results / "mass-response__passband.png").is_file())
            peak = origins["common.analysis.peak_metrics"]
            original = peak.read_bytes()
            peak.write_bytes(original + b"\n# changed frozen source\n")
            with self.assertRaisesRegex(RuntimeError, "hash differs"):
                MODULE._invoke_analysis_stage(request, prepare_only=False)
            peak.write_bytes(original)
            peak.unlink()
            with self.assertRaisesRegex(RuntimeError, "missing"):
                MODULE._invoke_analysis_stage(request, prepare_only=False)
            self.assertEqual(len(package["package"]["files"]), 11)

    def test_finite_length_screen_transmits_tuned_and_rejects_outer_masses(self) -> None:
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        transmissions = {}
        for mass in (96.0, 101.5, 106.0):
            result = MODULE.simulate_mass(mass, particles, self.resolved, 80)
            transmissions[mass] = result["transmission_fraction"]
        self.assertGreaterEqual(transmissions[101.5], 0.9)
        self.assertLessEqual(transmissions[96.0], 0.1)
        self.assertLessEqual(transmissions[106.0], 0.1)

    def test_l1_projection_preserves_common_box_cone_release(self) -> None:
        release = sample_numpy_box_cone_phase_space(
            source=self.source, seed=20260722, particle_count=64,
        )
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        self.assertTrue(np.array_equal(particles["x_m"], release["transverse_1_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["y_m"], release["transverse_2_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["energy_j"], release["energy_eV"] * MODULE.electron_volt))
        self.assertTrue(np.array_equal(particles["direction_x"], release["direction_transverse_1"]))
        self.assertTrue(np.array_equal(particles["direction_y"], release["direction_transverse_2"]))
        self.assertTrue(np.array_equal(particles["direction_z"], release["direction_axial"]))
        self.assertTrue(np.array_equal(particles["rf_phase_rad"], release["phase_rad"]))


if __name__ == "__main__":
    unittest.main()
