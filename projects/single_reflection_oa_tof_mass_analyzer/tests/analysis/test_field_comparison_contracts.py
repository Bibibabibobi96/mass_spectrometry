from __future__ import annotations

import unittest
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_field_profiles import region_metrics
from projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_longitudinal_closure import analyze_axis_profiles
from common.analysis.field_comparison import (
    merge_complete_samples,
    normalized_rms_difference_pct,
)


class FieldComparisonContractTest(unittest.TestCase):
    def test_analysis_clis_round_trip_decimal_identity_and_complete_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c, s = root/'comsol.csv', root/'simion.csv'
            header = 'region,sample_index,x_mm,y_mm,z_mm,potential_V,Ez_V_per_m\n'
            c.write_text(header + ''.join(
                f'{region},{i},89.94434260835371,201.4266955495302,{i},{-2*i},2000\n'
                for region in ('accelerator_source', 'accelerator_full', 'reflectron') for i in range(5)), encoding='utf-8')
            s.write_text('region,sample_index,x_mm,y_mm,z_mm,Ez_V_per_m\n' + ''.join(
                f'{region},{i},89.944342608353708,201.42669554953019,{i},2000\n'
                for region in ('accelerator_source', 'accelerator_full', 'reflectron') for i in range(5)), encoding='utf-8')
            package = 'projects.single_reflection_oa_tof_mass_analyzer.analysis.'
            out = root/'profiles'
            result = subprocess.run([sys.executable, '-B', '-m', package+'compare_field_profiles',
                str(c), str(s), '--output', str(out)], cwd=Path(__file__).resolve().parents[4],
                capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(json.loads((out/'axis_field_metrics.json').read_text())['status'], 'PASS')
            merged = pd.read_csv(out/'axis_field_comparison.csv', float_precision='round_trip')
            self.assertEqual(set(merged.x_mm), {float('89.94434260835371')})
            self.assertEqual(set(merged.y_mm), {float('201.4266955495302')})
            self.assertTrue((out/'axis_field_comparison.png').is_file())
            mapping = root/'mapping.json'
            mapping.write_text(json.dumps({'comparison': {'paired_tof_difference': {'source_mapping': {
                'z_quadratic_r_squared': .4, 'z2_energy_xy_r_squared': .6}}}}), encoding='utf-8')
            closure = root/'closure.json'
            result = subprocess.run([sys.executable, '-B', '-m', package+'analyze_longitudinal_closure',
                '--comsol-axis', str(c), '--simion-axis', str(s), '--comparison', str(mapping), '--output', str(closure)],
                cwd=Path(__file__).resolve().parents[4], capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(json.loads(closure.read_text())['axis_profiles']['accelerator_source']['samples'], 5)
            changed = math.nextafter(float('89.94434260835371'), math.inf)
            s.write_text(s.read_text().replace('89.944342608353708', repr(changed), 1), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'coverage differs'):
                analyze_axis_profiles(c, s)

    def test_longitudinal_consumer_preserves_reordered_complete_sample_pairs(self) -> None:
        coordinates = np.arange(5, dtype=float)
        comsol = pd.DataFrame({"region": ["axis"] * 5, "sample_index": range(5),
            "x_mm": np.zeros(5), "y_mm": np.zeros(5), "z_mm": coordinates,
            "potential_V": -2 * coordinates, "Ez_V_per_m": np.full(5, 2000.)})
        simion = comsol.drop(columns="potential_V").copy()
        simion["Ez_V_per_m"] += np.asarray([0., 1., 2., 3., 4.])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol.to_csv(root / "comsol.csv", index=False)
            simion.iloc[::-1].to_csv(root / "simion.csv", index=False)
            result = analyze_axis_profiles(root / "comsol.csv", root / "simion.csv")["axis"]
        self.assertEqual(result["samples"], 5)
        self.assertEqual(result["simion_minus_comsol_ez_mean_V_per_m"], 2.)
        self.assertAlmostEqual(result["simion_minus_comsol_ez_rms_V_per_m"], np.sqrt(6.))
        self.assertAlmostEqual(result["integrated_ez_SIMION_minus_COMSOL_V"], .008)

    def test_merge_rejects_missing_sample_on_either_side(self) -> None:
        left = pd.DataFrame({"sample_id": [1, 2], "value": [10.0, 20.0]})
        right = pd.DataFrame({"sample_id": [1], "value": [10.0]})

        with self.assertRaisesRegex(ValueError, "sample coverage differs"):
            merge_complete_samples(
                left,
                right,
                keys=["sample_id"],
                left_label="COMSOL",
                right_label="SIMION",
            )

    def test_merge_rejects_duplicate_keys(self) -> None:
        left = pd.DataFrame({"sample_id": [1, 1], "value": [10.0, 20.0]})
        right = pd.DataFrame({"sample_id": [1], "value": [10.0]})

        with self.assertRaisesRegex(ValueError, "duplicate sample keys"):
            merge_complete_samples(
                left,
                right,
                keys=["sample_id"],
                left_label="COMSOL",
                right_label="SIMION",
            )

    def test_near_zero_reference_does_not_create_infinite_ratio(self) -> None:
        ratio = normalized_rms_difference_pct(
            np.zeros(3),
            np.asarray([0.0, 1.0e-12, -1.0e-12]),
        )
        self.assertIsNone(ratio["relative_to_reference_rms_pct"])
        self.assertTrue(np.isfinite(ratio["symmetric_scale_pct"]))

    def test_region_metrics_reports_near_zero_samples_without_inf(self) -> None:
        frame = pd.DataFrame(
            {
                "COMSOL_Ez_V_per_m": [0.0, 1.0, 1000.0],
                "SIMION_Ez_V_per_m": [1.0, 2.0, 1001.0],
            }
        )

        metrics = region_metrics(frame)

        self.assertGreater(metrics["near_zero_reference_points"], 0)
        self.assertTrue(np.isfinite(metrics["symmetric_normalized_rms_difference_pct"]))


if __name__ == "__main__":
    unittest.main()
