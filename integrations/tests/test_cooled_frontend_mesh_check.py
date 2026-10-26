"""Pure local-mesh contracts; no native PA or physical result is fabricated."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from common.simion.aperture import resolve_rectangular_aperture_discretization
from integrations.runtime import single_flight_frontend as frontend_core
from integrations.tests.test_cooled_frontend import cooled_fixture
from integrations.workflows.cooled_frontend import geometry
from integrations.workflows.cooled_frontend.mesh_check import ROLE, sample_points, validate_request


def mesh_request_fixture():
    record = dict(path="artifacts/source.json", bytes=100, sha256="A"*64)
    return dict(schema_version=1, role=ROLE, source_request_record=record,
        field_source_record=copy.deepcopy(record),
        patch_bounds_mm=dict(x_min=-6., x_max=6., y_min=-70., y_max=38., z_min=26., z_max=38.),
        cell_mm_xyz=dict(x=.1, y=.1, z=.1), refine_convergence_v=1e-5,
        native_sampling=dict(axis_step_mm=.1, stencil_offsets_mm=[-.2, -.1, 0., .1, .2],
                             stencil_centers_y_mm=[28., 27.645]))


class CooledFrontendMeshTests(unittest.TestCase):
    def test_local_crop_reuses_identical_provider_csg_both_oa_variants(self):
        for variant in ("two_zone", "three_zone"):
            guide, connection, component, conditioner, _ = cooled_fixture(variant)
            before = copy.deepcopy((guide, connection, component, conditioner))
            bodies = []
            original = frontend_core._canonical_pa

            def capture(body, numerical):
                bodies.append(copy.deepcopy(body))
                return original(body, numerical)

            request = mesh_request_fixture()
            with (patch.object(frontend_core, "_canonical_pa", side_effect=capture) as wrapper,
                  patch.object(frontend_core, "_canonical_component", wraps=frontend_core._canonical_component) as projection,
                  patch.object(frontend_core, "render_bare_frontend_body", wraps=frontend_core.render_bare_frontend_body) as renderer,
                  patch.object(frontend_core, "resolve_rectangular_aperture_discretization",
                               wraps=resolve_rectangular_aperture_discretization) as aperture):
                _, coarse = geometry.compile_cooled_frontend(guide, connection, component, conditioner,
                    cell_mm_xyz=dict(x=.2, y=.2, z=.2), exit_gap_mm=1.)
                gem, fine = geometry.compile_cooled_frontend(guide, connection, component, conditioner,
                    cell_mm_xyz=request["cell_mm_xyz"], exit_gap_mm=1., numerical_bounds_mm=request["patch_bounds_mm"],
                    source_geometry_cell_mm_xyz=dict(x=.2, y=.2, z=.2))
            for operation in (wrapper, projection, renderer, aperture):
                self.assertEqual(operation.call_count, 2)
            for frontend in (coarse, fine):
                port = frontend["accelerator_local_region"]["port"]
                expected = resolve_rectangular_aperture_discretization(
                    mechanical_width_mm=port["width_mm"], mechanical_height_mm=port["height_mm"],
                    cell_mm_xyz=frontend["cell_mm_xyz"], normal_axis="y",
                    flange_min_mm=port["flange_min_mm"],
                    flange_max_mm=port["flange_min_mm"] + port["wall_thickness_mm"],
                    center_mm=dict(zip("xyz", port["center_mm"])), pa_origin_mm=frontend["instance_origin_mm"],
                    boolean_boundary_policy=("exclude_shape_inside_or_on_v1" if variant == "three_zone"
                                             else "exclude_shape_inside_only_v1"))
                actual = frontend["accelerator_local_region"]["accelerator_port_aperture_discretization"]
                self.assertEqual(actual, expected)
                self.assertEqual(actual["cell_mm_xyz"], frontend["cell_mm_xyz"])
                self.assertEqual(actual["pa_origin_mm"], {a: round(v, 12) for a, v in frontend["instance_origin_mm"].items()})
            self.assertEqual(bodies[0], bodies[1])
            self.assertEqual((guide, connection, component, conditioner), before)
            self.assertEqual(fine["instance_bounds_mm"], request["patch_bounds_mm"])
            self.assertEqual(fine["dimensions"], dict(nx=121, ny=1081, nz=121))
            self.assertEqual(gem.count("pa_define("), 1)
            self.assertIn("local static mesh diagnostic", fine["numerical_crop"]["qualification"])

    def test_explicit_sampling_keeps_both_independent_end_stencils(self):
        request = mesh_request_fixture()
        validate_request(request)
        conditioner = cooled_fixture()[3]
        points = sample_points(request, conditioner)
        names = [row["name"] for row in points]
        self.assertEqual(len(names), len(set(names)))
        for i, center in enumerate((28., 27.645)):
            rows = [p for p in points if p["name"].startswith(f"end_{i}_")]
            self.assertEqual(len(rows), 125)
            self.assertAlmostEqual(sum(p["y_mm"] for p in rows)/len(rows), center)
        self.assertTrue(any(name.startswith("mask_0_") for name in names))
        self.assertTrue(any(name.startswith("mask_1_") for name in names))

    def test_misaligned_crop_and_implicit_sampling_are_rejected(self):
        for change in (lambda r: r["patch_bounds_mm"].update(x_min=-6.01),
                       lambda r: r["native_sampling"].pop("axis_step_mm"),
                       lambda r: r.update(refine_convergence_v=float("nan"))):
            request = mesh_request_fixture()
            change(request)
            with self.assertRaises(ValueError): validate_request(request)


if __name__ == "__main__":
    unittest.main()
