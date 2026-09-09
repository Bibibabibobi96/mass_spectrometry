from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_portal_interface import (
    SEAMS,
    analyze_portal_comparisons,
    prepare_portal_samples,
)


class AnalyzerLocalPortalInterfaceTest(unittest.TestCase):
    def test_prepare_samples_selects_only_effective_central_seams(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "flight.log"
            log.write_text(
                "MRTOF_EVENT patch_interface ion=1 name=central_transport__z_min "
                "region=central_transport face=z_min n=1 direction=-1 t_us=1 "
                "x_mm=0.1 y_mm=2 z_mm=-105 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-39\n"
                "MRTOF_EVENT patch_interface ion=1 name=central_transport__z_max "
                "region=central_transport face=z_max n=1 direction=1 t_us=2 "
                "x_mm=-0.2 y_mm=3 z_mm=102 vx_mm_us=0 vy_mm_us=1 vz_mm_us=39\n"
                "MRTOF_EVENT patch_interface ion=1 name=mirror_turn_positive__z_min "
                "region=mirror_turn_positive face=z_min n=1 direction=1 t_us=2 "
                "x_mm=-0.2 y_mm=3 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=39\n",
                encoding="utf-8",
            )
            result = prepare_portal_samples(log, root / "samples")
            self.assertEqual(result["qualification"], "single_center_portal_seed_only")
            self.assertEqual({item["seam"] for item in result["seams"]}, set(SEAMS))
            self.assertTrue(all(item["sample_count"] == 1 for item in result["seams"]))
            negative = next(item for item in result["seams"] if item["seam"].startswith("negative"))
            self.assertEqual(negative["mirror_transform"], "reflect_z")

    def test_aggregate_requires_complete_matrix_and_reports_scales(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            groups = [f"group_{index}" for index in range(8)]
            records = []
            for scale in (1.0, 0.5):
                for seam in SEAMS:
                    for group in groups:
                        path = root / f"{scale}_{seam}_{group}.csv"
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            writer = csv.writer(stream, lineterminator="\n")
                            writer.writerow((
                                "name", "x_mm", "y_mm", "z_mm",
                                "delta_potential_V", "delta_ex_V_per_mm",
                                "delta_ey_V_per_mm", "delta_ez_V_per_mm",
                            ))
                            value = scale
                            writer.writerow(("sample", 0, 0, 0, value, value, value, value))
                        records.append({
                            "scale_factor": scale, "seam": seam,
                            "group": group, "csv_path": str(path),
                        })
            request = root / "input.json"
            request.write_text(json.dumps({
                "role": "mrtof_analyzer_local_portal_comparison_input",
                "scale_factors": [1.0, 0.5],
                "seams": list(SEAMS),
                "response_groups": groups,
                "comparisons": records,
                "operating_group_voltages_V": [1] * 8,
                "basis_voltage_V_by_scale": {"1.0": 10.0, "0.5": 10.0},
            }), encoding="utf-8")
            result = analyze_portal_comparisons(request)
            self.assertEqual(result["comparison_count"], 32)
            self.assertEqual(result["maximum_abs_delta_ez_V_per_mm"], {"1.0": 1.0, "0.5": 0.5})
            operating = result["operating_point"]["maximum_abs_delta_ez_V_per_mm"]
            self.assertAlmostEqual(operating["1.0"], 0.8)
            self.assertAlmostEqual(operating["0.5"], 0.4)
            self.assertTrue(all(
                item["fine_over_coarse_max_abs_delta_ez"] == 0.5
                for item in result["convergence"]
            ))


if __name__ == "__main__":
    unittest.main()
