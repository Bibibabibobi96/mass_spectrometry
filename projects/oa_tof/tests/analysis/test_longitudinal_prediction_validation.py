from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np

from projects.oa_tof.analysis.validate_longitudinal_prediction import (
    comparison_metrics,
    predict_times_us,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LongitudinalPredictionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = json.loads(
            (PROJECT_ROOT / "config" / "baseline.json").read_text(encoding="utf-8")
        )

    def test_coupled_prediction_differs_from_local_reference_away_from_center(self) -> None:
        source = self.baseline["particle_source"]
        z = np.asarray(
            [source["center_z_mm"] - 0.4, source["center_z_mm"], source["center_z_mm"] + 0.4]
        )
        _, old, coupled = predict_times_us(self.baseline, 524.0, z)
        self.assertAlmostEqual(old[1], coupled[1], places=12)
        self.assertGreater(abs(old[0] - coupled[0]), 1.0e-4)
        self.assertGreater(abs(old[2] - coupled[2]), 1.0e-4)

    def test_identical_prediction_has_zero_error(self) -> None:
        values = np.asarray([1.0, 2.0, 4.0, 8.0])
        metrics = comparison_metrics(values, values.copy())
        self.assertEqual(metrics["absolute_rmse_ns"], 0.0)
        self.assertEqual(metrics["centered_rmse_ns"], 0.0)
        self.assertAlmostEqual(metrics["particlewise_correlation"], 1.0)

    def test_stable_comsol_entry_always_passes_a_resolved_contract(self) -> None:
        entry = (PROJECT_ROOT / "comsol" / "run_oatof_model.m").read_text(encoding="utf-8")
        builder = (
            PROJECT_ROOT / "comsol" / "ms_oaTOF_two_stage_ringstack_reflectron.m"
        ).read_text(encoding="utf-8")
        self.assertIn("config', 'resolved_geometry.json", entry)
        self.assertIn("char(options.OutputModelPath), char(contractPath)", entry)
        explicit_branch = builder.index("if ~isempty(contract_path)")
        legacy_read = builder.index(
            "reflectron_incident_energy_ev = reflectronDesign.incident_energy_eV;",
            explicit_branch,
        )
        self.assertGreater(legacy_read, explicit_branch)


if __name__ == "__main__":
    unittest.main()
