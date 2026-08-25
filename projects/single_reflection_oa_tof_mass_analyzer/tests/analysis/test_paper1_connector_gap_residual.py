from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_connector_gap_residual import (
    compare_connector_gap_sources,
    load_fixed_pulse_checkpoint_source,
    load_governed_source,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class ConnectorGapResidualTests(unittest.TestCase):
    def _source(self, root: Path, name: str, *, residual_scale: float) -> tuple[Path, Path]:
        state_path = root / f"{name}_states.csv"
        receipt_path = root / f"{name}_receipt.json"
        generator = np.random.default_rng(20260825)
        fields = [
            "particle_id", "event", "sample_index", "instrument_time_us",
            "actual_instrument_time_us", "x_mm", "y_mm", "z_mm",
            "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
            "kinetic_energy_eV", "survival_status",
        ]
        with state_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for particle_id in range(1, 257):
                z_mm = -62.0 + particle_id / 256.0
                noise_m_per_s = generator.normal(scale=residual_scale)
                vz_m_per_s = 25.0 + 85.0 * z_mm + 3.0 * z_mm * z_mm + noise_m_per_s
                writer.writerow({
                    "particle_id": particle_id, "event": "pre_pulse_time_series_state",
                    "sample_index": 3, "instrument_time_us": 44.0,
                    "actual_instrument_time_us": 44.0, "x_mm": -69.0,
                    "y_mm": 0.0, "z_mm": z_mm, "vx_mm_per_us": 4.0,
                    "vy_mm_per_us": 0.0, "vz_mm_per_us": vz_m_per_s / 1000.0,
                    "kinetic_energy_eV": 10.0, "survival_status": "alive",
                })
        receipt_path.write_text(json.dumps({
            "role": "rf_oatof_pre_pulse_time_series_screening_receipt",
            "status": "success", "pulse_disabled": True,
            "outputs": {"states": {"sha256": _sha256(state_path)}},
            "sample_census": [
                {"sample_index": 1, "alive_count": 256, "missing_count": 0},
                {"sample_index": 2, "alive_count": 256, "missing_count": 0},
                {"sample_index": 3, "alive_count": 256, "missing_count": 0},
            ],
        }) + "\n", encoding="utf-8")
        return state_path, receipt_path

    def test_compares_locked_axial_residuals_without_detector_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_state, first_receipt = self._source(root, "gap0", residual_scale=8.0)
            second_state, second_receipt = self._source(root, "gap51", residual_scale=2.0)
            first = load_governed_source(state_path=first_state, receipt_path=first_receipt, mother_count=256, screened_count=256, sample_index=3)
            second = load_governed_source(state_path=second_state, receipt_path=second_receipt, mother_count=256, screened_count=256, sample_index=3)
            result = compare_connector_gap_sources(first=first, second=second, cohort_salt="gap-residual-test", bootstrap_replicates=200, bootstrap_seed=71)
            self.assertEqual(result["qualification"], "DETECTOR_BLIND_SOURCE_ONLY")
            self.assertGreaterEqual(result["cohort"]["common_locked_test_count"], 32)
            self.assertLess(result["paired_locked_axial_residual"]["second_rms_m_per_s"], result["paired_locked_axial_residual"]["first_rms_m_per_s"])
            self.assertLess(result["paired_locked_axial_residual"]["second_minus_first_mse_m2_per_s2"]["upper_95"], 0.0)
            self.assertIn("transmission", result["claims_prohibited"][0])

    def test_rejects_receipt_that_enables_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, receipt_path = self._source(root, "bad", residual_scale=1.0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["pulse_disabled"] = False
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pulse-disabled"):
                load_governed_source(state_path=state_path, receipt_path=receipt_path, mother_count=256, screened_count=256, sample_index=3)

    def _fixed_checkpoint(self, root: Path, name: str, *, residual_scale: float) -> tuple[Path, Path, Path]:
        state_path = root / f"{name}_checkpoints.csv"
        summary_path = root / f"{name}_summary.json"
        manifest_path = root / f"{name}_manifest.json"
        generator = np.random.default_rng(20260826)
        fields = [
            "particle_id", "event", "instrument_time_us", "x_mm", "y_mm",
            "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
            "kinetic_energy_eV", "pulse_eligibility",
        ]
        with state_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for particle_id in range(1, 257):
                z_mm = -62.0 + particle_id / 256.0
                vz_m_per_s = 25.0 + 85.0 * z_mm + 3.0 * z_mm * z_mm + generator.normal(scale=residual_scale)
                writer.writerow({
                    "particle_id": particle_id, "event": "pre_pulse_state",
                    "instrument_time_us": 44.0, "x_mm": -69.0, "y_mm": 0.0,
                    "z_mm": z_mm, "vx_mm_per_us": 4.0, "vy_mm_per_us": 0.0,
                    "vz_mm_per_us": vz_m_per_s / 1000.0,
                    "kinetic_energy_eV": 10.0, "pulse_eligibility": "eligible",
                })
        ids = list(range(1, 257))
        ids_sha = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode("utf-8")).hexdigest().upper()
        summary_path.write_text(json.dumps({
            "role": "rf_oatof_simion_single_flight_summary", "status": "success",
            "pulse_effective_time_us": 44.0,
            "census": {"launched": 256, "pre_pulse_state": 256},
            "observed_cohort_authority": {
                "source_release": {"ordered_particle_ids": ids, "count": 256, "ordered_particle_id_sha256": ids_sha},
                "pre_pulse_state": {"count": 256},
            },
        }) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps({
            "role": "simulation_run_manifest", "status": "success",
            "outputs": [{"path": str(root / name / "single_flight_particle_checkpoints.csv"), "sha256": _sha256(state_path)}],
        }) + "\n", encoding="utf-8")
        return state_path, summary_path, manifest_path

    def test_compares_fixed_integration_pulse_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_paths = self._fixed_checkpoint(root, "gap0", residual_scale=8.0)
            second_paths = self._fixed_checkpoint(root, "gap51", residual_scale=2.0)
            first = load_fixed_pulse_checkpoint_source(
                state_path=first_paths[0], summary_path=first_paths[1],
                run_manifest_path=first_paths[2], mother_count=256, screened_count=256,
            )
            second = load_fixed_pulse_checkpoint_source(
                state_path=second_paths[0], summary_path=second_paths[1],
                run_manifest_path=second_paths[2], mother_count=256, screened_count=256,
            )
            result = compare_connector_gap_sources(
                first=first, second=second, cohort_salt="fixed-pulse-gap-residual-test",
                bootstrap_replicates=200, bootstrap_seed=71,
            )
            self.assertEqual(result["arms"][0]["checkpoint"]["kind"], "integration_fixed_pulse")
            self.assertLess(result["paired_locked_axial_residual"]["second_rms_m_per_s"], result["paired_locked_axial_residual"]["first_rms_m_per_s"])

    def test_rejects_fixed_checkpoint_with_different_screened_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_paths = self._fixed_checkpoint(root, "gap0", residual_scale=8.0)
            second_paths = self._fixed_checkpoint(root, "gap51", residual_scale=2.0)
            summary = json.loads(second_paths[1].read_text(encoding="utf-8"))
            summary["observed_cohort_authority"]["source_release"]["ordered_particle_ids"][-1] = 999
            ids = summary["observed_cohort_authority"]["source_release"]["ordered_particle_ids"]
            summary["observed_cohort_authority"]["source_release"]["ordered_particle_id_sha256"] = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode("utf-8")).hexdigest().upper()
            second_paths[1].write_text(json.dumps(summary), encoding="utf-8")
            first = load_fixed_pulse_checkpoint_source(state_path=first_paths[0], summary_path=first_paths[1], run_manifest_path=first_paths[2], mother_count=256, screened_count=256)
            second = load_fixed_pulse_checkpoint_source(state_path=second_paths[0], summary_path=second_paths[1], run_manifest_path=second_paths[2], mother_count=256, screened_count=256)
            with self.assertRaisesRegex(ValueError, "share one screened particle-ID cohort"):
                compare_connector_gap_sources(first=first, second=second, cohort_salt="fixed-pulse-gap-residual-test", bootstrap_replicates=20, bootstrap_seed=71)


if __name__ == "__main__":
    unittest.main()
