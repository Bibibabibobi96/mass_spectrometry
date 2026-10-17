"""Native geometry tests; no SIMION, Refine, field values or flight claims."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection, render_gem


PROJECT = Path(__file__).resolve().parents[1]


def contains(shape: dict, point: tuple[float, float, float]) -> bool:
    """Independently evaluate material occupancy away from mesh conventions."""
    if shape["shape"] == "box":
        return all(low <= x <= high for low, x, high in
                   zip(shape["min_mm"], point, shape["max_mm"]))
    x, y, z = point
    return (shape["x_min_mm"] <= x <= shape["x_max_mm"] and
            math.hypot(y - shape["center_y_mm"], z - shape["center_z_mm"]) <= shape["radius_mm"])


def occupied(electrode: dict, point: tuple[float, float, float]) -> bool:
    """Evaluate solid union with true through-cut subtraction."""
    return (any(contains(shape, point) for shape in electrode["solids"]) and
            not any(contains(shape, point) for shape in electrode["cutouts"]))


def bounds(shape: dict) -> tuple[list, list]:
    """Return conservative AABBs; disjoint bounds prove non-contact."""
    if shape["shape"] == "box":
        return shape["min_mm"], shape["max_mm"]
    r = shape["radius_mm"]
    return ([shape["x_min_mm"], shape["center_y_mm"] - r, shape["center_z_mm"] - r],
            [shape["x_max_mm"], shape["center_y_mm"] + r, shape["center_z_mm"] + r])


class NativeGeometryTests(unittest.TestCase):
    """Check native metal identity, gaps, domain, and real extraction openings."""

    def setUp(self) -> None:
        self.baseline = json.loads((PROJECT / "config/baseline.json").read_text(encoding="utf-8"))
        self.numerics = json.loads((PROJECT / "config/numerics.json").read_text(encoding="utf-8"))
        self.p = native_projection(self.baseline, self.numerics)
        self.by_id = {row["electrode_id"]: row for row in self.p["electrodes"]}

    def test_full_adjustable_electrode_inventory(self) -> None:
        self.assertEqual(self.p["electrode_ids"], list(range(1, 16)))
        self.assertEqual(set(self.by_id), set(range(1, 16)))
        self.assertTrue(all(row["solids"] for row in self.by_id.values()))
        self.assertEqual(sum(len(self.by_id[k]["solids"]) for k in (1, 2)), 8)
        self.assertEqual(len(self.by_id[9]["solids"]), 4 * self.numerics["native_aux_segments"])
        self.assertEqual(len(self.by_id[10]["solids"]), 2 * self.numerics["native_aux_segments"])

    def test_baseline_pa_domain_and_grid(self) -> None:
        self.assertEqual(self.p["origin_mm"], [-2, -4, -4])
        grid = self.numerics["native_grid_mm"]
        self.assertEqual(self.p["shape_gu"], [math.ceil(span / grid - 1e-12) + 1 for span in (214, 14, 8)])
        self.assertEqual(self.p["span_mm"], [214, 14, 8])
        self.assertEqual(self.p["grid_mm"], grid)
        for electrode in self.by_id.values():
            for shape in electrode["solids"]:
                low, high = bounds(shape)
                for lo, hi, domain_lo, domain_hi in zip(
                    low, high, self.p["origin_mm"], self.p["maximum_mm"]
                ):
                    self.assertGreater(lo, domain_lo)
                    self.assertLess(hi, domain_hi)

    def test_extraction_slot_removes_pull_and_lp_shield_material(self) -> None:
        center = self.baseline["geometry"]["lp_center_mm"]
        for electrode_id, y in ((5, 2.25), (14, 3.25)):
            metal = self.by_id[electrode_id]
            self.assertFalse(occupied(metal, (center, y, 0)))
            self.assertFalse(occupied(metal, (center + 3.9, y, 0.39)))
            self.assertTrue(occupied(metal, (center + 4.1, y, 0)))
            self.assertTrue(occupied(metal, (center, y, 0.41)))
        self.assertTrue(occupied(self.by_id[6], (center, -2.25, 0)))
        self.assertTrue(occupied(self.by_id[15], (120, 3.25, 0)))

    def test_hp_entrance_is_a_two_mm_circular_bore_at_guide_interface(self) -> None:
        entrance = self.by_id[12]
        metal = entrance["solids"][0]
        x = (metal["min_mm"][0] + metal["max_mm"][0]) / 2
        self.assertEqual(metal["min_mm"][0], 29.5)
        self.assertEqual(metal["max_mm"][0], 30)
        self.assertFalse(occupied(entrance, (x, 0, 0)))
        for y, z in ((0.999, 0), (-0.999, 0), (0, 0.999), (0, -0.999), (0.7, 0.7)):
            self.assertFalse(occupied(entrance, (x, y, z)))
        for y, z in ((1.001, 0), (-1.001, 0), (0, 1.001), (0, -1.001), (0.75, 0.75)):
            self.assertTrue(occupied(entrance, (x, y, z)))
        cut = entrance["cutouts"][0]
        self.assertEqual(cut["shape"], "cylinder_x")
        self.assertEqual(2 * cut["radius_mm"], 2)
        self.assertLess(cut["x_min_mm"], metal["min_mm"][0])
        self.assertGreater(cut["x_max_mm"], metal["max_mm"][0])
        guide_end = max(shape["x_max_mm"] for key in (1, 2) for shape in self.by_id[key]["solids"])
        self.assertEqual(guide_end, 29)
        self.assertGreater(metal["min_mm"][0] - guide_end, 0)

    def test_exit_lens_retains_its_independent_square_bore(self) -> None:
        exit_lens = self.by_id[13]
        self.assertFalse(occupied(exit_lens, (210.25, 0, 0)))
        self.assertFalse(occupied(exit_lens, (210.25, 2.19, -2.19)))
        self.assertTrue(occupied(exit_lens, (210.25, 2.21, 0)))
        self.assertEqual(exit_lens["cutouts"][0]["shape"], "box")
        self.assertTrue(occupied(self.by_id[12], (29.75, 2.19, -2.19)))

    def test_lp_outer_inner_faces_match_literature_gaps_with_declared_stair_error(self) -> None:
        electrode = self.by_id[10]
        positive = sorted([shape for shape in electrode["solids"] if shape["min_mm"][2] > 0],
                          key=lambda shape: shape["min_mm"][0])
        negative = sorted([shape for shape in electrode["solids"] if shape["max_mm"][2] < 0],
                          key=lambda shape: shape["min_mm"][0])
        measured_gaps = []
        center = self.baseline["geometry"]["lp_center_mm"]
        start, stop = positive[0]["min_mm"][0], positive[-1]["max_mm"][0]
        for upper, lower in zip(positive, negative):
            x = (upper["min_mm"][0] + upper["max_mm"][0]) / 2
            actual_gap = upper["min_mm"][2] - lower["max_mm"][2]
            # Independent gap reference uses the paper's 4/3.7 mm facing-metal
            # distances; it does not interpret these values as sheet centers.
            half_span = center - start if x <= center else stop - center
            expected_gap = 4 - 0.3 * abs(x - center) / half_span
            self.assertAlmostEqual(actual_gap, expected_gap, places=12)
            measured_gaps.append(actual_gap)
            self.assertAlmostEqual(upper["max_mm"][2] - upper["min_mm"][2], 0.4, places=12)
            inner = upper["min_mm"][2]
            self.assertFalse(occupied(electrode, (x, 0, inner - 1e-6)))
            self.assertTrue(occupied(electrode, (x, 0, inner + 1e-6)))
            self.assertAlmostEqual(lower["min_mm"][2], -upper["max_mm"][2], places=12)
        # Midpoint stepping omits the exact wedge extrema. Its maximum total-gap
        # error is the half-step of each 0.3 mm half-wedge: 0.3/segment_count.
        stair_error = 0.3 / self.numerics["native_aux_segments"]
        self.assertLessEqual(abs(max(measured_gaps) - 4), stair_error + 1e-12)
        self.assertLessEqual(abs(min(measured_gaps) - 3.7), stair_error + 1e-12)
        self.assertGreaterEqual(min(measured_gaps), 3.7)
        self.assertLessEqual(max(measured_gaps), 4)

    def test_different_electrodes_have_no_touching_aabbs(self) -> None:
        # AABB separation is conservative for cylinders; for this geometry it
        # proves separation without depending on GEM/PA voxelization rules.
        for first_id, first in self.by_id.items():
            for second_id, second in self.by_id.items():
                if second_id <= first_id:
                    continue
                for first_shape in first["solids"]:
                    lo1, hi1 = bounds(first_shape)
                    for second_shape in second["solids"]:
                        lo2, hi2 = bounds(second_shape)
                        self.assertTrue(
                            any(a < b or c < d for a, b, c, d in zip(hi1, lo2, hi2, lo1)),
                            f"possible short between electrodes {first_id}, {second_id}",
                        )

    def test_staircase_has_direction_and_gap_to_shields(self) -> None:
        positive_corner = [shape for shape in self.by_id[9]["solids"] if shape["min_mm"][1] > 0 and shape["min_mm"][2] > 0]
        self.assertEqual(len(positive_corner), self.numerics["native_aux_segments"])
        values = [shape["min_mm"][1] for shape in positive_corner]
        self.assertEqual(values, sorted(values))
        self.assertGreater(min(shape["min_mm"][1] for shape in positive_corner), 1)
        self.assertLess(max(shape["max_mm"][1] for shape in positive_corner), 3)
        self.assertEqual(self.p["gas_model"], "prescribed_pressure_not_gas_flow_solution")

    def test_gem_serializes_solids_subtractions_and_grounded_faces(self) -> None:
        gem = render_gem(self.baseline, self.numerics)
        self.assertEqual(set(map(int, re.findall(r"\be\((\d+)\)", gem))), set(range(16)))
        nx, ny, nz = self.p["shape_gu"]
        grid = format(self.numerics["native_grid_mm"], ".12g")
        self.assertIn(f"pa_define({nx},{ny},{nz},planar,none,electrostatic,,{grid},{grid},{grid},surface=fractional)", gem)
        self.assertIn("locate(2,4,4)", gem)
        self.assertEqual(gem.count("cylinder("), 9)  # eight guide rods plus circular HP entrance
        self.assertEqual(gem.count("notin_inside"), 7)  # pull, four shield slabs, two lenses
        self.assertIn("e(0)", gem)
        self.assertEqual(gem.count("{"), gem.count("}"))

    def test_rejects_missing_nonfinite_and_shorting_inputs(self) -> None:
        for field, value in (("guide_rod_end_gap_mm", 0.4),
                             ("exit_lens_half_aperture_mm", 4),
                             ("entrance_aperture_diameter_mm", 6),
                             ("rf_plate_thickness_mm", float("nan"))):
            with self.subTest(field=field):
                baseline = copy.deepcopy(self.baseline)
                baseline["native_geometry"][field] = value
                with self.assertRaises(ValueError):
                    native_projection(baseline, self.numerics)
        baseline = copy.deepcopy(self.baseline)
        baseline["native_geometry"].pop("guide_rod_radius_mm")
        with self.assertRaises(ValueError):
            native_projection(baseline, self.numerics)
        numerics = {**self.numerics, "native_aux_segments": 9}
        with self.assertRaises(ValueError):
            native_projection(self.baseline, numerics)


if __name__ == "__main__":
    unittest.main()
