from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_pre_pulse_aperture_comparison import (
    INTEGRATION_ID,
    main,
    publish_pre_pulse_aperture_comparison,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent


def _source_run(root: Path, name: str, z_values: list[float]) -> Path:
    run = root / name
    (run / "inputs").mkdir(parents=True)
    (run / "results").mkdir()
    (run / "run_manifest.json").write_text(
        json.dumps({"status": "success", "run_id": name}), encoding="utf-8"
    )
    (run / "summary.json").write_text(
        json.dumps({"status": "success", "role": "rf_oatof_simion_single_flight_summary"}),
        encoding="utf-8",
    )
    (run / "run_config.json").write_text(
        json.dumps({"parameters": {
            "execution_mode": "real_pa_rf_pre_pulse_time_series",
            "source_release_full_width_mm": 4.0,
        }}),
        encoding="utf-8",
    )
    pd.DataFrame({"particle_id": [1, 2, 3, 4]}).to_csv(
        run / "inputs" / "single_flight_initial_global_state.csv", index=False
    )
    pd.DataFrame({
        "particle_id": [1, 2, 3], "sample_index": [1, 1, 1],
        "z_mm": z_values, "vz_mm_per_us": [1.0, 1.5, 2.0],
    }).to_csv(run / "results" / "pre_pulse_time_series_states.csv", index=False)
    (run / "results" / "pre_pulse_time_series_screening_receipt.json").write_text(
        json.dumps({"terminal_census": {"window_complete": {"count": 3}, "splat": {"count": 1}}}),
        encoding="utf-8",
    )
    return run


class PrePulseApertureComparisonPublicationTests(unittest.TestCase):
    def test_publishes_detector_blind_result_and_freezes_source_inputs(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            source_root = Path(temporary)
            cases = {
                "square_h150": _source_run(source_root, "square", [0.0, 1.0, 2.0]),
                "cylindrical_h250": _source_run(source_root, "cylindrical", [0.0, 2.5, 5.0]),
            }
            run_id = "20260829_120001__analysis__python__pre-pulse-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
            self.assertFalse(output.exists())
            try:
                manifest_path = publish_pre_pulse_aperture_comparison(
                    repo_root=REPO_ROOT, run_id=run_id, cases=cases
                )
                result = json.loads((output / "results" / "pre_pulse_aperture_comparison.json").read_text(encoding="utf-8"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                config = json.loads((output / "run_config.json").read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "DETECTOR_BLIND_SOURCE_ONLY")
                self.assertTrue(result["cases"]["square_h150"]["accelerator_entry_axial_full_width_acceptance"]["passed"])
                self.assertFalse(result["cases"]["cylindrical_h250"]["accelerator_entry_axial_full_width_acceptance"]["passed"])
                self.assertEqual(manifest["status"], "success")
                self.assertFalse(manifest["formal_eligible"])
                self.assertEqual(config["parameters"]["analysis_scope"], "DETECTOR_BLIND_SOURCE_ONLY")
                self.assertIn("case_1_run_manifest_json", config["inputs"])
                self.assertIn("case_2_results_pre_pulse_time_series_states_csv", config["inputs"])
                self.assertIn("repository_snapshot", config["inputs"]["publication_implementation"])
            finally:
                if output.exists():
                    shutil.rmtree(output)

    def test_rejects_duplicate_or_invalid_sources_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT) as temporary:
            source_root = Path(temporary)
            valid = _source_run(source_root, "valid", [0.0, 1.0, 2.0])
            output_id = "20260829_120002__analysis__python__pre-pulse-aperture-comparison__n5000"
            output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / output_id
            with self.assertRaisesRegex(ContractError, "at least two cases"):
                publish_pre_pulse_aperture_comparison(
                    repo_root=REPO_ROOT, run_id=output_id, cases={"one": valid}
                )
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ContractError, "case IDs must be unique"):
                main([
                    "--repo-root", str(REPO_ROOT), "--run-id", output_id,
                    "--case", "one", str(valid), "--case", "one", str(valid),
                ])
            self.assertFalse(output.exists())
            invalid = source_root / "invalid"
            invalid.mkdir()
            with self.assertRaisesRegex(ContractError, "missing required input"):
                publish_pre_pulse_aperture_comparison(
                    repo_root=REPO_ROOT, run_id=output_id, cases={"one": valid, "two": invalid}
                )
            self.assertFalse(output.exists())
            duplicate_output = WORKSPACE_ROOT / "artifacts" / "projects" / INTEGRATION_ID / "runs" / output_id
            duplicate_output.mkdir(parents=True)
            try:
                with self.assertRaisesRegex(ContractError, "output already exists"):
                    publish_pre_pulse_aperture_comparison(
                        repo_root=REPO_ROOT, run_id=output_id, cases={"one": valid, "two": valid}
                    )
            finally:
                duplicate_output.rmdir()


if __name__ == "__main__":
    unittest.main()
