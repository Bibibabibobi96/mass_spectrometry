from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    GROUPS,
    RealFieldL1Error,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_workflow import (
    REGION_ORDER,
    _responsibility_ranges,
    merge_region_csvs,
    write_sampler_spec,
)


class MirrorRealFieldL1WorkflowTests(unittest.TestCase):
    def test_responsibilities_come_from_handoffs_without_overlap(self) -> None:
        plan = {
            "handoff_planes_project_mm": {
                "negative_bridge_to_mirror": -2.0,
                "negative_central_to_bridge": -1.0,
                "positive_central_to_bridge": 1.0,
                "positive_bridge_to_mirror": 2.0,
            }
        }
        ranges = _responsibility_ranges(plan, (-3.0, 3.0), 0.5)
        self.assertEqual(
            [ranges[region] for region in REGION_ORDER],
            [(-3.0, -2.5), (-2.0, -1.5), (-1.0, 0.5), (1.0, 1.5), (2.0, 3.0)],
        )

    def test_sampler_spec_preserves_canonical_order_and_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = {
                "role": "mrtof_real_3d_mirror_l1_response_sampling_plan",
                "status": "prepared",
                "project_frame": "project_xyz",
                "slice_y_mm": 2.0,
                "basis_normalization_v": 10000.0,
                "regions": [{
                    "region_id": "central_transport",
                    "region_origin_project_mm": [-1.0, -2.0, -3.0],
                    "x_range_mm": [-0.5, 0.5],
                    "z_range_mm": [-0.5, 0.5],
                }],
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            paths = [root / f"{group}.pa" for group in "BCDE"]
            output = root / "spec.lua"
            write_sampler_spec(
                plan_path=plan_path, region_id="central_transport",
                response_paths=paths, output_path=output,
            )
            text = output.read_text(encoding="utf-8")
            self.assertLess(text.index('group="B"'), text.index('group="E"'))
            self.assertEqual(text.count("normalization_v=10000"), 4)
            self.assertIn("x=-1, y=-2, z=-3", text)

    def test_merge_proves_complete_grid_and_rejects_seam_duplicates(self) -> None:
        columns = ["x_mm", "z_mm", "is_electrode"]
        for group in GROUPS:
            columns.extend(
                [f"{group}_potential_v", *(f"{group}_e{axis}_v_per_mm" for axis in "xyz")]
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regions = []
            csvs = []
            for index, region in enumerate(REGION_ORDER):
                z = float(index)
                regions.append({"region_id": region, "z_range_mm": [z, z]})
                path = root / f"{region}.csv"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                    writer.writeheader()
                    for x in (0.0, 1.0):
                        row = {name: "0" for name in columns}
                        row.update({"x_mm": x, "z_mm": z, "is_electrode": 0})
                        writer.writerow(row)
                csvs.append(path)
            plan = {
                "role": "mrtof_real_3d_mirror_l1_response_sampling_plan",
                "basis_normalization_v": 1.0,
                "slice_y_mm": 0.0,
                "regions": regions,
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            output = root / "basis.csv"
            merge_region_csvs(plan_path=plan_path, region_csvs=csvs, output_path=output)
            with output.open(encoding="utf-8") as stream:
                self.assertEqual(sum(1 for _line in stream), 11)
            with csvs[1].open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["z_mm"] = "0"
            with csvs[1].open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(RealFieldL1Error, "responsibility|overlaps"):
                merge_region_csvs(plan_path=plan_path, region_csvs=csvs, output_path=output)


if __name__ == "__main__":
    unittest.main()
