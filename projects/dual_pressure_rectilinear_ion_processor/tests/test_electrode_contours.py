"""Analytic occupancy and variable-isolation checks for formed IP candidates."""
import copy
import json
from pathlib import Path
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection, render_gem
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import contains_shape, shape_bounds

ROOT = Path(__file__).resolve().parents[1]


def occupied(e: dict, point: list[float]) -> bool:
    return any(contains_shape(s,point) for s in e["solids"]) and not any(contains_shape(s,point) for s in e["cutouts"])


class ElectrodeContourTests(unittest.TestCase):
    def setUp(self) -> None:
        self.b = json.loads((ROOT/"config/baseline.json").read_text())
        self.n = json.loads((ROOT/"config/numerics.json").read_text())
        self.c = dict(schema_version=1, mode="formed_extraction", nose_halfwidth_mm=.8,
                      shoulder_halfwidth_mm=1.5,nose_depth_mm=.3,backing_thickness_mm=.2,
                      slit_lip_depth_mm=.2,slit_outlet_width_mm=1.2,push_window_length_mm=8,push_window_width_mm=2)
        self.old = native_projection(self.b,self.n)
        self.b["electrode_contours"] = self.c

    def test_formed_only_changes_declared_four_electrodes(self) -> None:
        before = copy.deepcopy(self.b)
        p = native_projection(self.b,self.n)
        self.assertEqual(self.b,before)
        self.assertEqual(p["shape_gu"],self.old["shape_gu"])
        for a,b in zip(p["electrodes"],self.old["electrodes"]):
            if a["electrode_id"] not in {5,6,7,8}:
                self.assertEqual(a,b)
        self.assertIn("half_space(",render_gem(native_projection(self.b,self.n)))

    def test_near_slit_and_outlet_lip_are_distinct_real_cutouts(self) -> None:
        p = native_projection(self.b,self.n)
        pull,push = p["electrodes"][4:6]
        cx = self.b["geometry"]["lp_center_mm"]
        for y in (2.05,2.15):
            self.assertFalse(occupied(pull,[cx,y,.39]))
            self.assertTrue(occupied(pull,[cx,y,.41]))
        self.assertFalse(occupied(pull,[cx,2.49,.58]))
        self.assertTrue(occupied(pull,[cx,2.49,.61]))
        self.assertTrue(occupied(pull,[cx+4.01,2.1,0]))
        self.assertFalse(occupied(push,[cx,-2.4,.9]))
        self.assertTrue(occupied(push,[cx,-2.4,1.1]))
        self.assertTrue(occupied(push,[cx+4.01,-2.1,0]))

    def test_split_tips_keep_four_grid_width_and_do_not_touch_aux(self) -> None:
        p = native_projection(self.b,self.n)
        cx = self.b["geometry"]["lp_center_mm"]
        self.assertTrue(occupied(p["electrodes"][6],[cx,.6,2.05]))
        self.assertFalse(occupied(p["electrodes"][6],[cx,.2,2.05]))
        for e in p["electrodes"][4:8]:
            for s in e["solids"]:
                lo,hi=shape_bounds(s)
                self.assertLessEqual(max(abs(v) for v in [*lo[1:],*hi[1:]]),2.5)

    def test_continuous_aux_replaces_axial_steps_without_changing_inner_sheet(self) -> None:
        formed = native_projection(self.b,self.n)
        self.c["mode"] = "formed_extraction_continuous_aux"
        p = native_projection(self.b,self.n)
        for a,b in zip(p["electrodes"],formed["electrodes"]):
            if a["electrode_id"] not in {9,10}:
                self.assertEqual(a,b)
        self.assertEqual(len(p["electrodes"][8]["solids"]),4)
        self.assertEqual(len(p["electrodes"][9]["solids"]),4)
        outer=p["electrodes"][9]
        center=self.b["geometry"]["lp_center_mm"]
        self.assertFalse(occupied(outer,[center,0,1.999]))
        self.assertTrue(occupied(outer,[center,0,2.001]))
        start=132
        self.assertFalse(occupied(outer,[start,0,1.849]))
        self.assertTrue(occupied(outer,[start,0,1.851]))

    def test_invalid_or_ambiguous_contour_inputs_fail_before_solver(self) -> None:
        for key,value in (("mode","vendor_exact"),("nose_halfwidth_mm",.4),
                          ("slit_lip_depth_mm",.5),("push_window_width_mm",3),
                          ("nose_depth_mm",float("nan"))):
            b=copy.deepcopy(self.b);b["electrode_contours"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                native_projection(b,self.n)

    def test_parabolic_inner_retains_tip_back_length_and_symmetric_continuous_edge(self) -> None:
        self.c.update(mode="formed_extraction_continuous_aux_parabolic_inner",inner_parabola_sag_mm=.1)
        p=native_projection(self.b,self.n)
        e=p["electrodes"][10]
        cx=self.b["geometry"]["lp_center_mm"]
        self.assertFalse(occupied(e,[cx,0,1.399]))
        self.assertTrue(occupied(e,[cx,0,1.401]))
        self.assertFalse(occupied(e,[cx+1.25,0,1.499]))
        self.assertTrue(occupied(e,[cx+1.25,0,1.501]))
        self.assertTrue(occupied(e,[cx-1.25,0,1.501]))
        self.assertFalse(occupied(e,[cx+1.251,0,1.55]))
        self.assertFalse(occupied(e,[cx,0,1.601]))
        self.assertAlmostEqual(p["inner_parabola_chord_error_bound_mm"],.1/60**2)
        self.c["inner_parabola_sag_mm"] = .2
        with self.assertRaises(ValueError):
            native_projection(self.b,self.n)

    def test_default_d_outer_coverage_is_unchanged(self) -> None:
        self.b["geometry"]["lp_length_mm"] = 61.5
        self.c.update(mode="formed_extraction_continuous_aux_parabolic_inner",inner_parabola_sag_mm=.1)
        default = native_projection(self.b,self.n)
        outer = default["electrodes"][9]
        self.assertEqual({v[0] for s in outer["solids"] for v in s["vertices_mm"]}, {132,170,189.5})
        self.c["outer_axial_bounds_mm"] = [132,189.5]
        explicit = native_projection(self.b,self.n)
        self.assertEqual(default["electrodes"],explicit["electrodes"])

    def test_symmetric_outer_bounds_change_only_e10(self) -> None:
        self.b["geometry"]["lp_length_mm"] = 61.5
        for mode in ("formed_extraction_continuous_aux", "formed_extraction_continuous_aux_parabolic_inner"):
            self.c["mode"] = mode
            if mode.endswith("parabolic_inner"):
                self.c["inner_parabola_sag_mm"] = .1
            before = native_projection(self.b,self.n)
            self.c["outer_axial_bounds_mm"] = [150.5,189.5]
            frozen = copy.deepcopy(self.b)
            after = native_projection(self.b,self.n)
            self.assertEqual(self.b,frozen)
            for a,b in zip(before["electrodes"],after["electrodes"]):
                if a["electrode_id"] != 10:
                    self.assertEqual(a,b)
            vertices = {tuple(v) for s in after["electrodes"][9]["solids"] for v in s["vertices_mm"]}
            self.assertEqual({v[0] for v in vertices},{150.5,170,189.5})
            self.assertEqual(vertices,{(340-x,y,z) for x,y,z in vertices})
            self.assertFalse(occupied(after["electrodes"][9],[140,0,2]))
            self.assertTrue(occupied(after["electrodes"][9],[150.5,0,1.851]))
            self.assertIn("half_space(",render_gem(native_projection(self.b,self.n)))
            del self.c["outer_axial_bounds_mm"]

    def test_invalid_outer_bounds_fail_before_solver(self) -> None:
        self.b["geometry"]["lp_length_mm"] = 61.5
        self.c["mode"] = "formed_extraction_continuous_aux"
        for bounds in (None, [], [150.5], [150.5,189.5,190], [True,189.5],
                       [float("nan"),189.5], [150.5,float("inf")], ["150.5",189.5],
                       [170,189.5], [150.5,170], [189.5,150.5], [130.4,189.5], [150.5,191.1]):
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):
                b=copy.deepcopy(self.b);b["electrode_contours"]["outer_axial_bounds_mm"]=bounds
                native_projection(b,self.n)
        self.c["outer_axial_bounds_mm"] = [150.5,189.5]
        self.c["mode"] = "formed_extraction"
        with self.assertRaises(ValueError):
            native_projection(self.b,self.n)
        self.c["mode"] = "formed_extraction_continuous_aux"
        self.c["outer_axial_bounds_m"] = self.c.pop("outer_axial_bounds_mm")
        with self.assertRaises(ValueError):
            native_projection(self.b,self.n)


if __name__ == "__main__":
    unittest.main()
