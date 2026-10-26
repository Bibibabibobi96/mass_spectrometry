"""Real provider geometry and independently specified field-fit regressions."""
from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from common.contracts.rigid_transform import RigidTransform
from common.contracts.particle_physics import BOLTZMANN_CONSTANT_J_K, ELEMENTARY_CHARGE_C
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import (
    export_cooled_buncher_assembly_interface, BUNCHER_ELECTRODE_NAMES, analyze_buncher_axial_barriers, analyze_buncher_field_samples, build_cooled_buncher_contract,
    prepare_buncher_probe_points, render_cooled_buncher_gem_fragment,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import export_guide_contract
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import convex_planes, convex_section
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import (
    native_projection, render_gem, render_projection_electrodes,
)

PROJECT = Path(__file__).resolve().parents[1]


def buncher_fixture() -> tuple[dict, dict, dict, dict, dict]:
    """Use repository authored inputs, with synthetic verified-identity labels."""
    def load(name):
        return json.loads((PROJECT / "config" / name).read_text(encoding="utf-8"))
    baseline, numerics = load("baseline.json"), load("numerics.json")
    model = dict(baseline=baseline, numerics=numerics, native_projection=native_projection(baseline, numerics),
                 source=load("source.json"), native_operating_point=load("native_operating_point.json"))
    identities = {name: dict(path=name, bytes=1, sha256="A"*64) for name in ("resolved_model", "source_spec", "release_csv")}
    guide = export_guide_contract(model, identities)
    registration = dict(rotation_upstream_to_downstream=[[0, -1, 0], [0, 0, 1], [-1, 0, 0]], translation_mm=[0, -97, 32])
    request = dict(schema_version=1, role="ion_processor_hp_end_buncher_request", inner_center_inset_mm=5., inner_length_mm=2.5)
    ids = dict(zip(BUNCHER_ELECTRODE_NAMES, range(40, 47), strict=True))
    return model, guide, registration, request, ids


def native_pose(guide: dict, registration: dict) -> dict:
    return RigidTransform.from_contract(guide["coordinate_transform"]).then(
        RigidTransform(guide["frame_id"], "mrtof_global_cartesian",
                       registration["rotation_upstream_to_downstream"], registration["translation_mm"])
    ).to_contract()


class CooledBuncherGeometryTests(unittest.TestCase):
    def build(self):
        model, guide, registration, request, ids = buncher_fixture()
        return build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                            request=request, electrode_ids=ids)

    def test_assembly_interface_publishes_real_local_circular_gate_faces(self):
        from common.contracts.machine_contracts import validate_schema
        model, guide, registration, request, ids = buncher_fixture()
        contract = build_cooled_buncher_contract(model, guide_contract=guide,
            native_to_assembly=native_pose(guide, registration), request=request, electrode_ids=ids)
        interface = export_cooled_buncher_assembly_interface(contract, guide)
        validate_schema(interface, "component_geometry_interface.schema.json")
        gate = interface["ports"]["exit_gate_outer_face"]
        self.assertEqual(gate["center_mm"], [contract["geometry"]["exit_face_native_x_mm"], 0, 0])
        self.assertEqual(gate["outward_normal"], [1, 0, 0])
        self.assertEqual(gate["cross_section"], dict(shape="circle", radius_mm=model["baseline"]["native_geometry"]["entrance_aperture_diameter_mm"]/2))
        self.assertEqual(len(interface["component_electrodes"]), 15)
        self.assertEqual({r["component_electrode_id"] for r in interface["component_electrodes"]}, set(range(1, 9))|set(range(40, 47)))

    def test_real_hp_retained_and_new_well_is_symmetric_without_source_changes(self):
        model, guide, registration, request, ids = buncher_fixture()
        before = copy.deepcopy((model, guide, registration, request, ids))
        result = build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                              request=request, electrode_ids=ids)
        self.assertEqual((model, guide, registration, request, ids), before)
        self.assertEqual(result["geometry"]["trap_center_mr_mm"], [0., 28., 32.])
        self.assertEqual(result["geometry"]["exit_face_center_mr_mm"], [0., 33.5, 32.])
        electrodes = result["native_projection_fragment"]["electrodes"]
        self.assertEqual([e["electrode_id"] for e in electrodes], list(range(40, 47)))
        self.assertEqual(electrodes[0]["solids"], model["native_projection"]["electrodes"][2]["solids"])
        inner = electrodes[5]["solids"]
        self.assertEqual(len(inner), 2)
        self.assertEqual(inner[0]["min_mm"][0], 123.75)
        self.assertEqual(inner[0]["max_mm"][0], 126.25)
        self.assertEqual(inner[0]["min_mm"][2], -inner[1]["max_mm"][2])
        self.assertEqual(inner[0]["max_mm"][2], -inner[1]["min_mm"][2])
        text = render_cooled_buncher_gem_fragment(result)
        self.assertEqual(text.count("  e("), 7)
        self.assertNotIn("pa_define", text)
        self.assertNotIn("e(0)", text)
        self.assertIn("cylinder(", text)

    def test_invalid_geometry_ids_and_pose_fail_without_shaving_metal(self):
        model, guide, registration, request, ids = buncher_fixture()
        for wrong in (dict(request, inner_center_inset_mm=.1), dict(request, inner_length_mm=101.), dict(request, extra=1)):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                              request=wrong, electrode_ids=ids)
        ids["exit_gate"] = ids["entrance_gate"]
        with self.assertRaises(ValueError):
            build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                          request=request, electrode_ids=ids)

    def test_off_grid_inner_edges_remain_physical_instead_of_snapping(self):
        result = self.build()
        low = result["native_projection_fragment"]["electrodes"][5]["solids"][0]["min_mm"][0]
        self.assertEqual(low, 123.75)
        self.assertNotEqual(low/.1, round(low/.1))

    def test_shared_renderer_preserves_existing_ip_body(self):
        model, *_ = buncher_fixture()
        fragment = render_projection_electrodes(model["native_projection"])
        self.assertIn(fragment, render_gem(model["native_projection"]))

    def test_continuous_d_corner_tapers_survive_provider_without_staircase_fallback(self):
        model, guide, registration, request, ids = buncher_fixture()
        # Authored D contour mode, independent of generated/frozen artifacts.
        model["baseline"]["electrode_contours"] = dict(
            schema_version=1,mode="formed_extraction_continuous_aux_parabolic_inner",
            nose_halfwidth_mm=.8,shoulder_halfwidth_mm=1.5,nose_depth_mm=.3,
            backing_thickness_mm=.2,slit_lip_depth_mm=.2,slit_outlet_width_mm=1.2,
            push_window_length_mm=8,push_window_width_mm=2,inner_parabola_sag_mm=.1)
        projection = native_projection(model["baseline"],model["numerics"])
        result = build_cooled_buncher_contract(model,guide_contract=guide,native_to_assembly=native_pose(guide, registration),
                                              request=request,electrode_ids=ids)
        electrode = result["native_projection_fragment"]["electrodes"][2]
        self.assertEqual(electrode["solids"],projection["electrodes"][8]["solids"])
        self.assertEqual(len(electrode["solids"]),4)
        for solid in electrode["solids"]:
            self.assertEqual(solid["shape"],"convex_polyhedron")
            self.assertEqual(len(solid["vertices_mm"]),8)
            self.assertEqual(len(convex_planes(solid)),6)
            for x,radius in ((32.,2.),(80.,2.75),(128.,3.5)):
                section = np.abs(np.asarray(convex_section(solid,0,x))[:,1:])
                # Actual convex sections verify linear slanted faces, not AABB.
                for axis in (0,1):
                    self.assertAlmostEqual(section[:,axis].min(),radius/math.sqrt(2))
                    self.assertAlmostEqual(section[:,axis].max()-section[:,axis].min(),.4)
        body = render_cooled_buncher_gem_fragment(result)
        self.assertIn("half_space(",body)
        self.assertEqual(result["native_to_mr"],self.build()["native_to_mr"])
        for index,source_id in ((0,3),(1,4),(3,12),(4,15)):
            self.assertEqual(result["native_projection_fragment"]["electrodes"][index]["solids"],
                             projection["electrodes"][source_id-1]["solids"])

    def test_requested_probe_stencil_is_mr_centered_and_not_a_field(self):
        contract = self.build()
        points = prepare_buncher_probe_points(contract, [-.1, 0., .1])
        self.assertEqual(len(points), 27)
        self.assertEqual(points[13], dict(point_id=13, x_mm=0., y_mm=28., z_mm=32.))
        with self.assertRaises(ValueError):
            prepare_buncher_probe_points(contract, [0., .1, .2])

    def test_rf_response_preserves_amplitude_ratio_and_rejects_phase_mismatch(self):
        model, guide, registration, request, ids = buncher_fixture()
        model["baseline"]["electric"]["rf_peak_to_peak_v"] *= 2
        result = build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                              request=request, electrode_ids=ids)
        self.assertEqual(result["drive"]["hp_to_guide_amplitude_ratio"], 2.)
        guide["drive"]["phase_rad"] += .1
        with self.assertRaisesRegex(ValueError, "phase-locked"):
            build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration),
                                          request=request, electrode_ids=ids)


class BuncherActualFieldTheoryTests(unittest.TestCase):
    def samples(self, axial_curvature=2.):
        rows = []
        # A trace-free electrostatic DC saddle plus radial RF quadrupole:
        # DC Hessian diag(-k/2,k,-k/2), E_RF=(x,0,-z) V/mm for 1V.
        for x, y, z in itertools.product([-.2, 0., .2], repeat=3):
            rows.append(dict(x_mm=x, y_mm=y, z_mm=z, dc_potential_v=axial_curvature*(y*y/2-x*x/4-z*z/4),
                             unit_rf_ex_v_per_mm=x, unit_rf_ey_v_per_mm=0., unit_rf_ez_v_per_mm=-z))
        return pd.DataFrame(rows)

    def analyze(self, frame):
        return analyze_buncher_field_samples(frame, center_mr_mm=[0., 0., 0.], mass_amu=524., charge_state=1,
                                             temperature_k=300., rf_frequency_hz=3.7e6, rf_peak_amplitude_v=500.)

    def test_laplace_saddle_plus_actual_rf_fit_produces_thermal_axial_prediction(self):
        result = self.analyze(self.samples())
        self.assertTrue(result["locally_positive_effective_curvature"])
        self.assertTrue(result["equilibrium_within_sample_bounds"])
        self.assertAlmostEqual(result["effective_energy_hessian_ev_per_mm2"][1][1], 2.)
        expected = (BOLTZMANN_CONSTANT_J_K*300/ELEMENTARY_CHARGE_C/2)**.5
        self.assertAlmostEqual(result["thermal_sigma_xyz_mm"][1], expected)
        # Ten-column least squares and the Hessian solve accumulate roundoff;
        # use the same 64-epsilon scale as project geometry predicates.
        roundoff = 64*np.finfo(float).eps
        np.testing.assert_allclose(result["equilibrium_mr_mm"], [0., 0., 0.], atol=roundoff)
        self.assertLess(result["fit_residual_sigma_ev"], roundoff)

    def test_nontrapping_and_rank_deficient_actual_samples_do_not_create_fake_widths(self):
        result = self.analyze(self.samples(axial_curvature=-2.))
        self.assertFalse(result["locally_positive_effective_curvature"])
        self.assertIsNone(result["thermal_sigma_xyz_mm"])
        with self.assertRaisesRegex(ValueError, "quadratic"):
            self.analyze(pd.concat([self.samples().iloc[:1]]*10, ignore_index=True))
        wrong = self.samples()
        wrong.loc[0, "dc_potential_v"] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            self.analyze(wrong)

    def test_actual_axial_line_barriers_retain_asymmetry_and_missing_side_fails(self):
        profile = pd.DataFrame([dict(y_mm=y, dc_potential_v=v, unit_rf_ex_v_per_mm=0.,
                                     unit_rf_ey_v_per_mm=0., unit_rf_ez_v_per_mm=0.)
                                for y, v in ((-1., 3.), (0., 0.), (1., 5.))])
        kwargs = dict(well_center_y_mm=0., mass_amu=524., charge_state=1, temperature_k=300.,
                      rf_frequency_hz=3.7e6, rf_peak_amplitude_v=500.)
        result = analyze_buncher_axial_barriers(profile, **kwargs)
        self.assertEqual(result["upstream_line_barrier_ev"], 3.)
        self.assertEqual(result["downstream_line_barrier_ev"], 5.)
        with self.assertRaisesRegex(ValueError, "bracket"):
            analyze_buncher_axial_barriers(profile, **dict(kwargs, well_center_y_mm=1.))

    def test_positive_curvature_does_not_prove_equilibrium_inside_sampled_field(self):
        samples = self.samples()
        samples["dc_potential_v"] += 100*samples["y_mm"]
        result = self.analyze(samples)
        self.assertTrue(result["locally_positive_effective_curvature"])
        self.assertFalse(result["equilibrium_within_sample_bounds"])
        self.assertLess(result["equilibrium_mr_mm"][1], -.2)


if __name__ == "__main__":
    unittest.main()
