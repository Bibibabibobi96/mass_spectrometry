import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    analyze_stage_field_2x2 as stage_field,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_stage_field_2x2 import (
    ARMS,
    EVENTS,
    bind_checkpoint_evidence,
    checkpoint_peak_metrics,
    effect_vectors,
    fwhm_factorial_effects,
)


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": stage_field.file_sha256(path),
    }


def _evidence_fixture(root: Path) -> tuple[Path, Path, dict[str, object]]:
    run_id = "20260814_120000__sim__simion__fixture__n1000"
    run = root / run_id
    results = run / "results"
    results.mkdir(parents=True)
    checkpoint = results / "single_flight_particle_checkpoints.csv"
    checkpoint.write_text("particle_id,event,instrument_time_us\n", encoding="utf-8")
    config = run / "run_config.json"
    config.write_text(json.dumps({"schema_version": 2, "run_id": run_id}), encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "role": "simulation_run_manifest",
        "run_id": run_id,
        "status": "success",
        "run_config": _record(config),
        "outputs": [_record(checkpoint)],
    }
    manifest_path = run / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return checkpoint, manifest_path, manifest

class StageField2x2Tests(unittest.TestCase):
    def test_official_manifest_verifier_is_invoked(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path, manifest = _evidence_fixture(Path(temporary))
            with patch.object(stage_field.subprocess, "run") as run_mock:
                self.assertEqual(
                    stage_field._verify_success_v2_manifest(manifest_path), manifest
                )
            command = run_mock.call_args.args[0]
            self.assertEqual(
                command[1:3], ["-m", "common.contracts.verify_run_manifest"]
            )
            self.assertIn("--require-status", command)
            self.assertEqual(run_mock.call_args.kwargs["check"], True)

    def test_failed_or_v1_manifest_is_rejected_before_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path, manifest = _evidence_fixture(Path(temporary))
            for key, value in (("status", "failed"), ("schema_version", 1)):
                changed = dict(manifest)
                changed[key] = value
                manifest_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    stage_field._verify_success_v2_manifest(manifest_path)

    def test_checkpoint_must_be_the_exact_manifest_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint, manifest_path, manifest = _evidence_fixture(root)
            unrelated = root / "unrelated.csv"
            unrelated.write_bytes(checkpoint.read_bytes())
            with patch.object(
                stage_field, "_verify_success_v2_manifest", return_value=manifest
            ):
                with self.assertRaisesRegex(ValueError, "does not uniquely bind"):
                    bind_checkpoint_evidence("IR", unrelated, manifest_path)

    def test_success_v2_manifest_binds_checkpoint_path_and_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest_path, manifest = _evidence_fixture(Path(temporary))
            with patch.object(
                stage_field, "_verify_success_v2_manifest", return_value=manifest
            ):
                evidence = bind_checkpoint_evidence("IR", checkpoint, manifest_path)
            self.assertEqual(evidence["evidence_type"], "success_v2_manifest")
            self.assertEqual(
                evidence["checkpoint_sha256"], stage_field.file_sha256(checkpoint)
            )

    def test_rr_canonical_receipt_requires_publisher_output_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest_path, manifest = _evidence_fixture(Path(temporary))
            receipt = manifest_path.parent / "results" / "rr_canonical_clock_receipt.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": stage_field.CANONICAL_RR_RECEIPT_ROLE,
                        "status": "success",
                        "derived_checkpoint_sha256": stage_field.file_sha256(checkpoint),
                        "particle_count": 1000,
                        "old_source_files_modified": False,
                    }
                ),
                encoding="utf-8",
            )
            manifest["outputs"].append(_record(receipt))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(
                stage_field, "_verify_success_v2_manifest", return_value=manifest
            ):
                evidence = bind_checkpoint_evidence(
                    "RR", checkpoint, manifest_path, receipt
                )
            self.assertEqual(
                evidence["evidence_type"], "published_canonical_rr_receipt"
            )
            self.assertEqual(
                evidence["canonical_receipt_sha256"], stage_field.file_sha256(receipt)
            )

    def test_rr_receipt_with_unbound_checkpoint_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest_path, manifest = _evidence_fixture(Path(temporary))
            receipt = manifest_path.parent / "results" / "rr_canonical_clock_receipt.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": stage_field.CANONICAL_RR_RECEIPT_ROLE,
                        "status": "success",
                        "derived_checkpoint_sha256": "0" * 64,
                        "particle_count": 1000,
                        "old_source_files_modified": False,
                    }
                ),
                encoding="utf-8",
            )
            manifest["outputs"].append(_record(receipt))
            with patch.object(
                stage_field, "_verify_success_v2_manifest", return_value=manifest
            ):
                with self.assertRaisesRegex(ValueError, "does not bind checkpoint"):
                    bind_checkpoint_evidence("RR", checkpoint, manifest_path, receipt)

    def test_canonical_receipt_is_rejected_for_factorial_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest_path, manifest = _evidence_fixture(Path(temporary))
            receipt = manifest_path.parent / "results" / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            manifest["outputs"].append(_record(receipt))
            with patch.object(
                stage_field, "_verify_success_v2_manifest", return_value=manifest
            ):
                with self.assertRaisesRegex(ValueError, "only valid for RR"):
                    bind_checkpoint_evidence("II", checkpoint, manifest_path, receipt)

    def test_high_minus_low_effects_and_interaction_scale(self):
        values = {"RR": np.array([1.0]), "IR": np.array([3.0]), "RI": np.array([5.0]), "II": np.array([11.0])}
        effects = effect_vectors(values)
        self.assertEqual(effects["stage1_ideal_main"].item(), 4.0)
        self.assertEqual(effects["stage2_ideal_main"].item(), 6.0)
        self.assertEqual(effects["stage1_stage2_interaction"].item(), 2.0)

    def test_fwhm_fixture_uses_complete_difference_in_differences(self):
        fixture = {"RR": 10.0, "IR": 20.0, "RI": 30.0, "II": 50.0}
        effects = fwhm_factorial_effects(fixture)
        self.assertEqual(effects["stage1_ideal_main"], 15.0)
        self.assertEqual(effects["stage2_ideal_main"], 25.0)
        self.assertEqual(
            effects["stage1_stage2_interaction_complete_did"], 10.0
        )

    @patch(
        "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer."
        "analysis.analyze_stage_field_2x2.compute_peak_metrics"
    )
    def test_checkpoint_peak_metrics_covers_every_event_and_arm(self, peak_mock):
        peak_mock.return_value = ({
            "particles": 3,
            "mean_tof_us": 1.0,
            "std_tof_ns": 2.0,
            "direct_fwhm_tof_ns": 3.0,
            "time_equivalent_resolution": 4.0,
            "mass_resolution": 5.0,
            "significant_kde_modes": 1,
        }, {})
        rows = [
            {"particle_id": particle_id, "event": event,
             "instrument_time_us": 1.0 + particle_id * 0.001}
            for event in EVENTS
            for particle_id in (1, 2, 3)
        ]
        result = checkpoint_peak_metrics({arm: pd.DataFrame(rows) for arm in ARMS})
        self.assertEqual(set(result), set(EVENTS))
        self.assertEqual(
            set(result["reflectron_entrance_forward"]["arms"]), set(ARMS)
        )
        self.assertEqual(
            result["detector_crossing"]["arms"]["RR"]["particles"], 3
        )
        self.assertEqual(
            result["detector_crossing"]["fwhm_factorial_effects_ns"]
            ["stage1_stage2_interaction_complete_did"],
            0.0,
        )
        self.assertEqual(peak_mock.call_count, len(EVENTS) * len(ARMS))
