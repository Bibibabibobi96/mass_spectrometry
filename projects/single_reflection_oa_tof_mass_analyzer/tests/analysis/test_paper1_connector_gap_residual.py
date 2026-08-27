from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_connector_gap_residual import (
    assess_connector_gap_triplet,
    compare_connector_gap_sources,
    load_fixed_pulse_checkpoint_source,
    load_governed_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_stage_evidence import (
    publish_stage_evidence,
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
            "inputs": {
                "mother_particle_source": {"sha256": "A" * 64},
                "three_zone_t5_candidate": {"sha256": "B" * 64},
                "resolved_source_contract": {"sha256": "C" * 64},
                "resolved_region_field_contract": {"sha256": "D" * 64},
                "resolved_single_flight_execution_profile": {"sha256": "E" * 64},
            },
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

    def _fixed_triplet_request(self, root: Path) -> Path:
        records = [
            self._fixed_checkpoint(root, name, residual_scale=scale)
            for name, scale in (("gap0", 8.0), ("gap51", 4.0), ("gap102", 2.0))
        ]
        request = {
            "schema_version": 1,
            "role": "oatof_paper1_c1_connector_gap_triplet_request",
            "cohort_salt": "triplet-fixed-pulse-test",
            "bootstrap_replicates": 100,
            "bootstrap_seed": 71,
            "required_checkpoint_kind": "integration_fixed_pulse",
            "arms": [
                {
                    "gap_mm": gap, "checkpoint_kind": "integration_fixed_pulse",
                    "mother_count": 5000, "screened_count": 256,
                    "state_table": str(paths[0]), "summary": str(paths[1]),
                    "run_manifest": str(paths[2]),
                }
                for gap, paths in zip((0.0, 51.2, 102.4), records)
            ],
        }
        path = root / "triplet_request.json"
        path.write_text(json.dumps(request) + "\n", encoding="utf-8")
        return path

    def test_triplet_publishes_c1_stage_evidence_from_one_checkpoint_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = assess_connector_gap_triplet(config_path=self._fixed_triplet_request(root))
            self.assertEqual(evidence.conclusion, "PASS_CONTINUE")
            self.assertEqual(len(evidence.metrics["adjacent_locked_residual_comparisons"]), 2)
            self.assertTrue(evidence.metrics["all_full_mother_denominators_retained"])
            published = publish_stage_evidence(root / "C1", evidence)
            self.assertEqual(
                {item.name for item in published.iterdir()},
                {"stage_contract.md", "stage_manifest.json", "stage_report.md", "stage_report.json", "stage_conclusion.md"},
            )

    def test_triplet_v2_records_an_explicit_blind_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request_path = self._fixed_triplet_request(Path(directory))
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["schema_version"] = 2
            request["cohort_partition"] = {
                "role": "detector_blind_hash_partition",
                "development_upper_fraction": 0.40,
                "validation_upper_fraction": 0.55,
                "optimization_upper_fraction": 0.65,
                "locked_test_upper_fraction": 1.00,
            }
            request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
            evidence = assess_connector_gap_triplet(config_path=request_path)
            self.assertEqual(evidence.conclusion, "PASS_CONTINUE")
            self.assertEqual(
                evidence.metrics["cohort_partition"]["role_upper_bounds"]["locked_test"], 1.0,
            )

    def test_triplet_fails_closed_for_mixed_checkpoint_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = self._fixed_triplet_request(root)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["arms"][1]["checkpoint_kind"] = "pulse_disabled_time_series"
            request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
            evidence = assess_connector_gap_triplet(config_path=request_path)
            self.assertEqual(evidence.conclusion, "INCONCLUSIVE_REVISE")
            self.assertIn("uniform checkpoint kind", " ".join(evidence.failures))

    def _time_series_triplet_request(self, root: Path, *, matched_epoch: bool) -> Path:
        records = [
            self._source(root, name, residual_scale=scale)
            for name, scale in (("gap0", 8.0), ("gap51", 4.0), ("gap102", 2.0))
        ]
        schedules: list[Path] = []
        for index, (_, receipt_path) in enumerate(records):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["identities"] = {
                "mother_particle_source_sha256": "A" * 64,
                "ordered_particle_id_sha256": "B" * 64,
                "source_profile_id": "s1",
                "layout_profile_id": "three-zone",
                "architecture_generation_id": "three-zone-v1",
                "candidate_sha256": "C" * 64,
                "time_integration_profile_id": "dt40",
                "field_profile_id": "real-pa",
                "region_field_semantic_sha256": "D" * 64,
                "frontend_grid_profile_id": "frontend-z005",
                "oatof_numerical_profile_id": "formal-mesh",
                "trajectory_quality_profile_id": "tqual-8",
            }
            for census in receipt["sample_census"]:
                census["instrument_time_us"] = 44.0
            receipt["sample_times_us"] = [44.0, 44.0, 44.0]
            receipt["rf_time_grid"] = {
                "grid_origin_us": 44.0,
                "frequency_hz": 1_100_000.0,
                "rf_steps_per_period": 40,
                "waveform": "cosine",
            }
            receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
            schedule_path = root / f"gap{index}_pulse_schedule.json"
            schedule_path.write_text(json.dumps({
                "role": "rf_oatof_resolved_single_flight_pulse_schedule",
                "pulse_effective_time_us": 44.0 if matched_epoch or index != 1 else 44.1,
                "layout_profile_id": "three-zone",
                "time_integration_profile_id": "dt40",
                "source_state_sha256": "E" * 64,
            }) + "\n", encoding="utf-8")
            schedules.append(schedule_path)
        request = {
            "schema_version": 1,
            "role": "oatof_paper1_c1_connector_gap_triplet_request",
            "cohort_salt": "triplet-time-series-test",
            "bootstrap_replicates": 100,
            "bootstrap_seed": 71,
            "required_checkpoint_kind": "pulse_disabled_time_series",
            "arms": [
                {
                    "gap_mm": gap, "checkpoint_kind": "pulse_disabled_time_series",
                    "mother_count": 5000, "screened_count": 256,
                    "state_table": str(paths[0]), "time_series_receipt": str(paths[1]),
                    "sample_index": 3, "resolved_pulse_schedule": str(schedule),
                    "equivalence_protocol": "resolved_pulse_epoch_state_equivalence_v1",
                }
                for gap, paths, schedule in zip((0.0, 51.2, 102.4), records, schedules)
            ],
        }
        path = root / "time_series_triplet_request.json"
        path.write_text(json.dumps(request) + "\n", encoding="utf-8")
        return path

    def test_triplet_accepts_pre_pulse_equivalent_time_series(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = assess_connector_gap_triplet(
                config_path=self._time_series_triplet_request(Path(directory), matched_epoch=True)
            )
            self.assertEqual(evidence.conclusion, "PASS_CONTINUE")
            modes = evidence.metrics["arms"]
            self.assertTrue(all(item["source_mode"] == "PRE_PULSE_EQUIVALENT_TIME_SERIES" for item in modes))
            self.assertTrue(all("mode_equivalence" in item for item in modes))

    def test_triplet_rejects_time_series_not_at_resolved_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = assess_connector_gap_triplet(
                config_path=self._time_series_triplet_request(Path(directory), matched_epoch=False)
            )
            self.assertEqual(evidence.conclusion, "INCONCLUSIVE_REVISE")
            self.assertIn("resolved pulse epoch", " ".join(evidence.failures))


if __name__ == "__main__":
    unittest.main()
