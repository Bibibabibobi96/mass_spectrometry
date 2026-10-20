"""Analytic local-plane and aperture regressions; no solver dependencies."""
from __future__ import annotations

import unittest
import copy
import json
import csv
from pathlib import Path
import shutil
from unittest.mock import patch

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_focus_diagnostics as d
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_ip_prism_local_diagnostics as fixtures


def state(t: float, x: float, y: float, z: float) -> dict:
    return dict(particle_id=1, t_us=t, x_mm=x, y_mm=y, z_mm=z,
                vx_mm_us=0., vy_mm_us=1., vz_mm_us=-2., potential_v=0.)


class FocusDiagnosticsTests(unittest.TestCase):
    def test_numerical_comparison_rows_preserve_frozen_vectors_order_and_missing_ids(self) -> None:
        first = dict(case=dict(case_id="coarse", pitch_mm=[.1, .2, .1], maximum_step_us=.001),
                     planes={"near": {9: state(10., 1., 2., -3.), 2: state(20., 4., 5., -6.)},
                             "far": {2: state(30., 7., 8., -9.), 7: state(40., 0., 0., -9.)}})
        second = dict(case=dict(case_id="fine", pitch_mm=[.1, .1, .1], maximum_step_us=.001),
                      planes={"near": {2: state(20.25, 5., 3., -6.), 9: state(10.5, 2., 4., -3.),
                                       11: state(21., 0., 0., -3.)},
                              "far": {2: state(30.125, 9., 7., -9.)}})
        second["planes"]["near"][9].update(vx_mm_us=3., vy_mm_us=5., vz_mm_us=-1., potential_v=6.)
        planes = [dict(name="near"), dict(name="far")]
        original = copy.deepcopy((first, second, planes))
        expected = []
        for plane, pid, dt, dx, dy, dvx, dvy, dvz, dv in (
                ("near", 2, 250., 1., -2., 0., 0., 0., 0.),
                ("near", 9, 500., 1., 2., 3., 4., 1., 6.),
                ("far", 2, 125., 2., -1., 0., 0., 0., 0.)):
            expected.append(dict(case_a="coarse", case_b="fine", plane=plane, particle_id=pid,
                pitch_a_mm=[.1, .2, .1], pitch_b_mm=[.1, .1, .1], maximum_step_a_us=.001,
                maximum_step_b_us=.001, delta_t_ns=dt, delta_x_mm=dx, delta_y_mm=dy,
                delta_z_mm=0., delta_vx_mm_us=dvx, delta_vy_mm_us=dvy, delta_vz_mm_us=dvz,
                delta_potential_v=dv))
        actual = d.numerical_comparison_rows([(first, second)], planes)
        self.assertEqual(actual, expected)
        self.assertEqual([list(row) for row in actual], [list(row) for row in expected])
        self.assertEqual((first, second, planes), original)
        self.assertEqual(d.numerical_comparison_rows([], planes), [])
        self.assertEqual(d.numerical_comparison_rows([(first, second)], []), [])
        # Freeze the former inline algorithm as an independent equivalence oracle.
        legacy = []
        for a, b in [(first, second)]:
            for plane in planes:
                x, y = a["planes"][plane["name"]], b["planes"][plane["name"]]
                for pid in sorted(x.keys() & y.keys()):
                    legacy.append(dict(case_a=a["case"]["case_id"], case_b=b["case"]["case_id"],
                        plane=plane["name"], particle_id=pid, pitch_a_mm=a["case"]["pitch_mm"],
                        pitch_b_mm=b["case"]["pitch_mm"], maximum_step_a_us=a["case"]["maximum_step_us"],
                        maximum_step_b_us=b["case"]["maximum_step_us"],
                        delta_t_ns=(y[pid]["t_us"]-x[pid]["t_us"])*1000,
                        **{f"delta_{k}": y[pid][k]-x[pid][k] for k in d.local.STATE_FIELDS[1:]}))
        self.assertEqual(actual, legacy)

    def test_integer_selector_centers_project_in_both_frames(self) -> None:
        normal = np.array([0., 1., -2.]) / np.sqrt(5)
        reference = dict(origin_mm=[0, 0, -20], normal=normal.tolist(),
                         e_x=[1, 0, 0], e_y=(np.array([0., 2., 1.]) / np.sqrt(5)).tolist(),
                         global_z_mm=-20)
        aperture = dict(center_x_mm=0, center_y_mm=-55)
        original = copy.deepcopy((reference, aperture))
        for frame in ("global_z", "reference_normal"):
            with self.subTest(frame=frame):
                plane, center = d._selector_plane(reference, aperture, frame)
                self.assertEqual(center.dtype.kind, "f")
                self.assertTrue(np.all(np.isfinite(center)))
                self.assertAlmostEqual(float((center - np.array(plane["origin_mm"])) @
                                             np.array(plane["normal"])), 0.)
                if frame == "global_z":
                    np.testing.assert_allclose(center, [0., -55., -20.])
                else:
                    np.testing.assert_allclose(center, [0., -44., -42.])
        self.assertEqual((reference, aperture), original)

    def test_virtual_selector_planes_have_distinct_six_panel_figures(self) -> None:
        metrics = ("sigma_local_theta_x_deg", "sigma_local_theta_y_deg", "sigma_local_x_mm",
                   "sigma_local_y_mm", "time_sigma_ns", "sigma_kinetic_energy_ev")
        rows = []
        for plane, z, value in (("p_near", -1., 10.), ("p_far", -2., 100.)):
            for shape, width, offset in (("unfiltered", None, 5.), ("circle", .1, 0.), ("circle", .2, 1.),
                                         ("y_slit", .1, 2.), ("y_slit", .2, 3.)):
                rows.append(dict(case_id="C", plane=plane, z_mm=z, shape=shape, half_width_mm=width,
                    frame="global_z", center_x_mm=0., center_y_mm=-55., selector_center_x_mm=0.,
                    selector_center_y_mm=-55., selector_center_z_mm=z, slit_x_half_width_mm=None,
                    mother_count=100, exit_count=96, arrival_count=90, accepted_count=40,
                    transmission_mother=.9 if shape == "unfiltered" else .4,
                    **{key: value+offset for key in metrics}))
        before = copy.deepcopy(rows)
        saved = []
        def save(figure, path):
            figure.canvas.draw()
            self.assertEqual(len(figure.axes), 6)
            near = "p_near" in path.name
            self.assertIn("p_near" if near else "p_far", figure._suptitle.get_text())
            expected = [10., 11.] if near else [100., 101.]
            for ax in figure.axes:
                self.assertEqual(list(ax.lines[0].get_ydata()), expected)
                self.assertEqual(ax.lines[0].get_marker(), "o")
                self.assertEqual(ax.lines[1].get_marker(), "^")
                self.assertNotEqual(ax.lines[0].get_linestyle(), ax.lines[1].get_linestyle())
            saved.append(path.name)
            from matplotlib import pyplot as plt
            plt.close(figure)
        with patch.object(d.local, "_save_figure", side_effect=save):
            names = d._virtual_aperture_figures(Path("unused"), rows, [dict(case=dict(case_id="C"))])
        self.assertEqual(names, ["virtual_aperture__C__p_near", "virtual_aperture__C__p_far"])
        self.assertEqual(names, saved)
        self.assertEqual(rows, before)

    def test_zero_field_reference_uses_birth_clocks_and_pairs_without_survival_reselection(self) -> None:
        births = {1: state(10., 0., 0., 0.), 2: dict(state(10.004, .2, .1, 0.), particle_id=2, vz_mm_us=-1.),
                  3: dict(state(10.008, .3, .2, 0.), particle_id=3, vz_mm_us=2.)}
        planes = [dict(name=f"p{i}", z_mm=-2.*i) for i in (1, 2, 3)]
        actual = dict(p1={1: state(10.5, .1, .2, -2.),
                         2: dict(state(10.504, .4, .3, -2.), particle_id=2)},
                      p2={1: state(11., .2, .4, -4.)}, p3={})
        case = dict(case=dict(case_id="test", label="B", mass_u=524.), births=births,
                    planes=actual, census=dict.fromkeys((1, 2, 3, 4)))
        unchanged = copy.deepcopy(case)
        tables = d._zero_field_tables([case], planes, {1, 2})
        self.assertEqual(case, unchanged)
        self.assertEqual(len(tables["zero_field_plane_particles"]), 6)
        self.assertEqual(len(tables["zero_field_plane_decisions"]), 12)
        decisions = [r for r in tables["zero_field_plane_decisions"] if r["plane"] == "p1"]
        self.assertEqual(next(r for r in decisions if r["particle_id"] == 3)["reason"], "velocity_not_forward_negative_z")
        self.assertEqual(next(r for r in decisions if r["particle_id"] == 4)["status"], "upstream_not_handed_off")
        first = [r for r in tables["actual_zero_field_paired_particles"] if r["plane"] == "p1"]
        self.assertAlmostEqual(first[0]["zero_field_t_us"], 11.)
        self.assertAlmostEqual(first[0]["delta_t_ns"], -500.)
        self.assertAlmostEqual(first[1]["zero_field_t_us"], 12.004)
        self.assertAlmostEqual(first[1]["delta_t_ns"], -1500.)
        self.assertAlmostEqual(first[1]["delta_x_mm"], .2)
        paired = [r for r in tables["actual_zero_field_paired_statistics"] if r["cohort"] == "common_extracted_ids" and r["plane"] == "p2"]
        self.assertTrue(all(r["available_ids"] == [1] and r["missing_ids"] == [2] and r["count"] == 1 for r in paired))
        self.assertTrue(all(r["reference_available_count"] == 2 and r["actual_available_count"] == 1 for r in paired))
        empty = [r for r in tables["actual_zero_field_paired_statistics"] if r["plane"] == "p3"]
        self.assertTrue(all(r["time_sigma_ns"] is None for r in empty))
        minima = tables["zero_field_minima"]
        self.assertTrue(all(r["propagation_model"] == "zero_field_reference" for r in minima))
        reference_minimum = next(r for r in minima if r["cohort"] == "common_extracted_ids" and r["minimum_kind"] == "fixed_complete_cohort_segment_minimum")
        self.assertTrue(reference_minimum["complete_cohort_covers_full_scan"])
        self.assertEqual(reference_minimum["plane"], "p1")
        self.assertEqual(reference_minimum["count"], 2)

    def _identity_inputs(self, fixture) -> None:
        fixture.contract["prism_voltage_v"] = 0.  # Explicit synthetic static field.
        fixture.contract["contract"]["source_registration"] = dict(
            translation_mm=[0., 0., 0.], from_frame_id="fixture_source", to_frame_id="fixture_mr")
        for index, spec in enumerate(fixture.contract["cases"]):
            old = fixture.run/spec["directory"]
            directory = fixture.run/"simion"/f"case_{index:02d}"
            shutil.copytree(old, directory)
            spec.update(directory=str(directory), source_run="synthetic_native_source", label="same display",
                        source_count=2, mother_count=3, source_epoch_us=7500., pulse_time_us=7500.,
                        mass_u=524., charge_state=1, distance_mm=52.828, exit_z_mm=0., delta_z_mm=0., gap_mm=1.,
                        maximum_step_us=.001, pitch_mm=[.1, .2, .1], field_case_id=f"field_{index}",
                        source_csv="inputs/component_particle_state.csv", source_census_csv="inputs/source_census.csv")
            geometry = dict(frame_id="fixture_mr", ion_processor_electrodes=[], prism_electrodes=[], prism_ground_shields=[])
            (directory/"geometry.json").write_text(json.dumps(dict(geometry=geometry, geometry_checks=dict(pitch_mm=spec["pitch_mm"]))), encoding="utf-8")
        projection = fixture.run/"inputs/native_sources/source_01/provider_voltage_projection.json"
        projection.parent.mkdir(parents=True)
        projection.write_text(json.dumps(dict(values_v15=[0.]*15, evaluation_time_us=7500., basis="synthetic_held_static_fixture")), encoding="utf-8")

    def _comparison_fixture(self):
        fixture = fixtures.LocalPrismDiagnosticsTests("test_empty_statistics_do_not_invent_fwhm")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self._identity_inputs(fixture)
        return fixture, fixture.contract, [dict(case=spec) for spec in fixture.contract["cases"]]

    def test_numerical_pairs_exclude_same_label_physical_aperture_changes(self) -> None:
        fixture, resolved, cases = self._comparison_fixture()
        self.assertEqual(len(d._numerical_case_pairs(fixture.run, resolved, cases)), 1)
        cases[1]["case"]["physical_aperture"] = dict(shape="circle", radius_mm=.1, voltage_v=0.)
        self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, cases), [])
        cases[0]["case"]["physical_aperture"] = dict(shape="circle", radius_mm=.1, voltage_v=0.)
        cases[1]["case"]["physical_aperture"]["radius_mm"] = .2
        self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, cases), [])

    def test_display_labels_paths_mesh_and_step_do_not_define_physics(self) -> None:
        fixture, resolved, cases = self._comparison_fixture()
        cases[1]["case"].update(label="renamed display", pitch_mm=[.05, .1, .05], maximum_step_us=.0005,
                                 field_path="different.pa", source_run="relocated_native_provenance")
        projection = fixture.run/"inputs/native_sources/source_02/provider_voltage_projection.json"
        projection.parent.mkdir(parents=True)
        shutil.copyfile(d.contour_projection_paths(resolved)["synthetic_native_source"], projection)
        original = fixture.run/"inputs/component_particle_state.csv"
        duplicate = fixture.run/"inputs/reanalysis_source.csv"
        shutil.copyfile(original, duplicate)
        cases[1]["case"]["source_csv"] = str(duplicate)
        self.assertEqual(len(d._numerical_case_pairs(fixture.run, resolved, cases)), 1)

    def test_physical_source_clock_pose_geometry_and_voltage_changes_excluded(self) -> None:
        fixture, resolved, cases = self._comparison_fixture()
        for key, value in (("pulse_time_us", 7500.1), ("source_epoch_us", 7500.1), ("distance_mm", 10.),
                           ("delta_z_mm", 1.), ("gap_mm", 2.), ("mass_u", 525.)):
            candidate = copy.deepcopy(cases)
            candidate[1]["case"][key] = value
            self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, candidate), [], key)
        geometry_path = Path(cases[1]["case"]["directory"])/"geometry.json"
        data = json.loads(geometry_path.read_text())
        data["geometry"]["physical_change"] = [1., 2., 3.]
        geometry_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, cases), [])
        del data["geometry"]["physical_change"]
        geometry_path.write_text(json.dumps(data), encoding="utf-8")
        changed_source = fixture.run/"inputs/changed_source.csv"
        with (fixture.run/"inputs/component_particle_state.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["velocity_x_m_s"] = float(rows[0]["velocity_x_m_s"])+1.
        fixtures._write_csv(changed_source, rows)
        candidate = copy.deepcopy(cases)
        candidate[1]["case"]["source_csv"] = str(changed_source)
        self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, candidate), [])
        resolved["cases"][1]["source_run"] = "second_voltage_authority"
        projection = fixture.run/"inputs/native_sources/source_02/provider_voltage_projection.json"
        projection.parent.mkdir(parents=True)
        for change in (dict(values_v15=[1.]*15), dict(evaluation_time_us=7500.1), dict(basis="different_held_stage")):
            authority = dict(values_v15=[0.]*15, evaluation_time_us=7500., basis="synthetic_held_static_fixture")
            authority.update(change)
            projection.write_text(json.dumps(authority), encoding="utf-8")
            self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, cases), [])
        projection.unlink()
        with self.assertRaises(FileNotFoundError):
            d._numerical_case_pairs(fixture.run, resolved, cases)

    def test_aperture_grid_representation_is_not_physical_identity(self) -> None:
        fixture, resolved, cases = self._comparison_fixture()
        for i, case in enumerate(cases):
            path = Path(case["case"]["directory"])/"geometry.json"
            data = json.loads(path.read_text())
            data["geometry"]["aperture_electrodes"] = [dict(specification=dict(shape="circle", radius_mm=.1),
                solids=[], cutouts=[], grid_representation=dict(thickness_cells=i+1),
                gem_subtraction=dict(cutting_tool_z_extent_mm=[-120-i, 25+i]))]
            path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(len(d._numerical_case_pairs(fixture.run, resolved, cases)), 1)
        data["geometry"]["aperture_electrodes"][0]["specification"]["radius_mm"] = .2
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(d._numerical_case_pairs(fixture.run, resolved, cases), [])

    def test_recorded_nine_case_identity_preserves_nine_intended_pairs(self) -> None:
        run = Path(__file__).resolve().parents[5]/"artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_134013__test__python__ip-bcd-local-prepare__r02"
        if not run.is_dir():
            self.skipTest("Read-only native preparation artifact unavailable")
        resolved = json.loads((run/"inputs/resolved_study.json").read_text(encoding="utf-8-sig"))
        pairs = d._numerical_case_pairs(run, resolved, [dict(case=spec) for spec in resolved["cases"]])
        actual = {(a["case"]["case_id"], b["case"]["case_id"]) for a, b in pairs}
        expected = {(f"{name}_{first}", f"{name}_{second}") for name in "BCD"
                    for first, second in (("h010", "h005"), ("h010", "h005_halfdt"), ("h005", "h005_halfdt"))}
        self.assertEqual(actual, expected)
    def test_time_focus_figure_does_not_show_loss_selected_zero_width(self) -> None:
        from matplotlib import pyplot as plt

        case=dict(case=dict(case_id="B",label="B",pitch_mm=[.1,.2,.1],maximum_step_us=.001))
        rows=[dict(case_id="B",cohort="own_extracted_ids",frame="global_z",z_mm=-i,
                   count=n,missing_ids=missing,time_sigma_ns=s,central68_ns=2*s,central90_ns=3*s)
              for i,n,missing,s in ((1,3,[],2.),(2,2,[3],1.),(3,1,[2,3],0.))]
        curves=[]
        def save(figure,path):
            if path.name=="time_focus":
                curves.extend(np.asarray(ax.lines[0].get_ydata()) for ax in figure.axes)
            plt.close(figure)
        with patch.object(d.local,"_save_figure",side_effect=save):
            d._figures(fixtures.Path("unused"),rows,[],[case],[])
        self.assertEqual(len(curves),3)
        for curve in curves:
            self.assertTrue(np.isfinite(curve[0]))
            self.assertTrue(np.isnan(curve[1:]).all())

    def test_time_and_transport_comparisons_share_column_scales_without_removing_data(self) -> None:
        from matplotlib import pyplot as plt

        cases = [dict(case=dict(case_id=name, label=label, mass_u=524.,
                               pitch_mm=[.1, .2, .1], maximum_step_us=.001),
                      planes=dict(p1_exit={}), births={}, terminals={})
                 for name, label in (("reference", "B reference"), ("candidate", "D candidate"))]
        metrics = ("time_sigma_ns", "central68_ns", "central90_ns", "sigma_x_mm",
                   "sigma_y_mm", "sigma_theta_x_deg", "sigma_theta_y_deg", "sigma_kinetic_energy_ev")
        rows = [dict(case_id=case["case"]["case_id"], cohort="own_extracted_ids", frame="global_z",
                     z_mm=-z, count=96, missing_ids=[], **{key: scale*z for key in metrics})
                for case, scale, positions in zip(cases, (1., 30.), ((1., 2.), (5., 10.))) for z in positions]
        unchanged = copy.deepcopy(rows)
        for empty in (False, True):
            with self.subTest(empty=empty):
                data = [] if empty else rows
                seen = []
                def save(figure, path):
                    if path.name in {"time_focus", "transport_widths"}:
                        figure.canvas.draw()
                        columns = 3 if path.name == "time_focus" else 6
                        for col in range(columns):
                            upper, lower = figure.axes[col], figure.axes[columns+col]
                            self.assertEqual(upper.get_xlim(), lower.get_xlim())
                            self.assertEqual(upper.get_ylim(), lower.get_ylim())
                            for index, ax in enumerate((upper, lower)):
                                expected_x = [] if empty else ([1., 2.] if index == 0 else [5., 10.])
                                self.assertEqual(list(ax.lines[0].get_xdata()), expected_x)
                                expected_y = [] if empty else ([96, 96] if path.name == "transport_widths" and col == 5
                                                               else ([1., 2.] if index == 0 else [150., 300.]))
                                self.assertEqual(list(ax.lines[0].get_ydata()), expected_y)
                        seen.append(path.name)
                    plt.close(figure)
                with patch.object(d.local, "_save_figure", side_effect=save):
                    d._figures(Path("unused"), data, [], cases, [])
                    d._transport_figures(Path("unused"), cases, data, [], 7500.)
                self.assertEqual(seen, ["time_focus", "transport_widths"])
        self.assertEqual(rows, unchanged)

    def test_complete_interval_focus_survives_later_single_ion_false_minimum(self) -> None:
        planes = [dict(name=f"p{i}", z_mm=-float(i)) for i in range(5)]
        rows = [dict(plane=p["name"], declared_count=3, count=n, missing_ids=[] if n == 3 else [2, 3],
                     time_sigma_ns=sigma, central68_ns=2*sigma, central90_ns=3*sigma)
                for p, n, sigma in zip(planes, (3, 3, 3, 1, 1), (3., 1., 2., 0., 0.))]
        observed, focus = d._sampled_minima(rows, planes, "B", "global_z", "own")
        self.assertEqual(observed["plane"], "p3")
        self.assertEqual(observed["sigma_t_ns"], 0.)
        self.assertFalse(observed["eligible_complete_cohort"])
        self.assertEqual(focus["plane"], "p1")
        self.assertEqual(focus["z_mm"], -1.)
        self.assertEqual(focus["sigma_t_ns"], 1.)
        self.assertTrue(focus["primary_complete_minimum"])
        self.assertFalse(focus["at_complete_interval_boundary"])
        self.assertFalse(focus["at_scan_boundary"])
        self.assertFalse(focus["complete_cohort_covers_full_scan"])
        self.assertEqual(focus["interval_last_plane"], "p2")
        self.assertEqual(focus["neighboring_plane_spacings_mm"], [1., 1.])

    def test_no_complete_planes_explicitly_unavailable_and_segments_not_joined(self) -> None:
        planes = [dict(name=f"p{i}", z_mm=-float(i)) for i in range(3)]
        rows = [dict(plane=p["name"], declared_count=3, count=2, missing_ids=[3],
                     time_sigma_ns=1., central68_ns=2., central90_ns=3.) for p in planes]
        results = d._sampled_minima(rows, planes, "B", "global_z", "own")
        self.assertFalse(results[1]["available"])
        self.assertIsNone(results[1]["sigma_t_ns"])
        for i in (0, 2):
            rows[i].update(count=3, missing_ids=[])
        results = d._sampled_minima(rows, planes, "B", "global_z", "own")
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r["at_complete_interval_boundary"] for r in results[1:]))
        self.assertEqual(len(results[1]["complete_intervals"]), 2)

    def test_spatial_minimum_uses_its_metric_and_complete_support(self) -> None:
        planes = [dict(name=f"p{i}", z_mm=-float(i)) for i in range(4)]
        rows = [dict(plane=p["name"], declared_count=3, count=3 if i < 3 else 1,
                     missing_ids=[] if i < 3 else [2, 3], time_sigma_ns=float(i+1),
                     central68_ns=2., central90_ns=3., sigma_x_mm=x)
                for i, (p, x) in enumerate(zip(planes, (3., 1., 2., 0.)))]
        observed, complete = d._sampled_minima(rows, planes, "C", "global_z", "own", metric="sigma_x_mm")
        self.assertEqual(observed["plane"], "p3")
        self.assertFalse(observed["eligible_complete_cohort"])
        self.assertEqual(complete["plane"], "p1")
        self.assertEqual(complete["metric"], "sigma_x_mm")
        self.assertEqual(complete["metric_unit"], "mm")
        self.assertEqual(complete["minimum_value"], 1.)
        self.assertEqual(complete["sigma_t_ns"], 2.)
        self.assertFalse(complete["at_complete_interval_boundary"])
        with self.assertRaisesRegex(ValueError, "Unsupported sampled focus metric"):
            d._sampled_minima(rows, planes, "C", "global_z", "own", metric="not_a_metric")

    def test_actual_tilted_plane_crossing(self) -> None:
        normal = np.array([0., 1., -2.])/np.sqrt(5)
        plane = dict(origin_mm=[0., .5, -1.], normal=normal.tolist())
        row = d.normal_crossing([state(3., 0., 0., 0.), state(4., 0., 1., -2.)], plane, 1.)
        self.assertAlmostEqual(row["t_us"], 3.5)
        self.assertAlmostEqual(row["interpolation_fraction"], .5)
        self.assertIsNone(d.normal_crossing([state(3., 0., 0., 0.), state(4., 0., 1., -2.)], plane, .1))

    def test_no_extrapolation_or_backward_intersection(self) -> None:
        plane = dict(origin_mm=[0., 0., -3.], normal=[0., 0., -1.])
        self.assertIsNone(d.normal_crossing([state(0., 0., 0., 0.), state(1., 0., 1., -2.)], plane, 1.))
        plane["origin_mm"] = [0., 0., -1.]
        self.assertIsNone(d.normal_crossing([state(0., 0., 1., -2.), state(1., 0., 0., 0.)], plane, 1.))

    def test_time_budget_retains_covariance_and_missing(self) -> None:
        first = {i: dict(t_us=t) for i, t in enumerate([1., 1.004, 1.008], 1)}
        second = {i: dict(t_us=2.004) for i in (1, 2, 3)}
        row = d.time_variance_budget(first, second, {1, 2, 3, 4})
        self.assertEqual(row["missing_ids"], [4])
        self.assertAlmostEqual(row["variance_b_ns2"], 0.)
        self.assertLess(row["twice_covariance_ns2"], 0.)
        self.assertAlmostEqual(row["closure_residual_ns2"], 0., places=10)
        self.assertIsNone(d.time_variance_budget({}, {}, {1})["variance_b_ns2"])

    def test_slit_vs_circle_and_boundary(self) -> None:
        self.assertTrue(d.aperture_accepts(5., .5, .5, "y_slit", None))
        self.assertFalse(d.aperture_accepts(5., .5, .5, "circle", None))
        self.assertTrue(d.aperture_accepts(0., .5, .5, "circle", None))
        self.assertFalse(d.aperture_accepts(5., .5, .5, "y_slit", 1.))

    def test_reference_shared_basis_points_along_positive_y(self) -> None:
        case = dict(case=dict(case_id="B"), planes=dict(p={1: state(0., 0., -55., -10.)}))
        plane = d._reference_planes(case, [dict(name="p", z_mm=-10.)])[0]
        self.assertGreater(plane["e_y"][1], 0)
        self.assertAlmostEqual(float(np.dot(plane["e_y"], plane["normal"])), 0.)
        self.assertAlmostEqual(np.linalg.norm(plane["e_y"]), 1.)

    def test_full_export_keeps_mother_and_fixed_source_cohorts(self) -> None:
        fixture = fixtures.LocalPrismDiagnosticsTests("test_empty_statistics_do_not_invent_fwhm")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        contract = fixture.contract
        contract["role"] = "resolved_ip_prism_contour_focus_study"
        contract["cases"] = contract["cases"][:1]
        spec = contract["cases"][0]
        spec.update(label="B", source_count=2, mother_count=3, source_epoch_us=7500., mass_u=524.,
                    charge_state=1, maximum_step_us=.004, sample_interval_us=.2,
                    pitch_mm=[.1, .2, .1], field_case_id="field", source_csv="inputs/component_particle_state.csv",
                    source_census_csv="inputs/source_census.csv", physical_aperture=dict(shape="y_slit"))
        contract["contract"] = dict(schema_version=1, observation_planes=[dict(name=n, z_mm=z) for n, z in
            (("p1_near", -52.828), ("p1_far", -82.), ("p1_exit", -98.))],
            aperture_comparison=dict(plane_names=["p1_near"], half_widths_mm=[.5, 1.],
                                     center_x_mm=0., center_y_mm=-55., slit_x_half_width_mm=None,
                                     reference_case_id="current"))
        self._identity_inputs(fixture)
        spec["label"] = "B"
        spec["sample_interval_us"] = .2
        spec["maximum_step_us"] = .004
        fixture._write_contract()
        figures = []
        def save(figure, path):
            # Exercise headless renderer and actual single-header layout.
            figure.canvas.draw()
            figures.append(path.name)
            from matplotlib import pyplot as plt
            plt.close(figure)
        with patch.object(d.local, "_save_figure", side_effect=save):
            result = d.analyze_focus_study(fixture.run)
        self.assertEqual(result["common_count"], 2)
        self.assertEqual(result["figure_names"], figures)
        self.assertEqual(len(figures), len(set(figures)))
        self.assertIn("virtual_aperture__current__p1_near", figures)
        self.assertEqual(result["physical_aperture_case_ids"], ["current"])
        root = fixture.run / "results/local_focus_diagnostics"
        metadata = json.loads((root/"metadata.json").read_text())
        self.assertIn("fixed upstream", metadata["cohort_definition"])
        self.assertIn("actual physical-aperture", metadata["physical_aperture_scope"])
        self.assertIn("zero_field_reference_comparison", figures)
        self.assertTrue({"transport_packet_spatial_evolution_xz", "transport_packet_spatial_evolution_yz",
                         "transport_lifecycle_status"} <= set(figures))
        with (root/"transport_time_counts.csv").open(newline="", encoding="utf-8") as stream:
            lifecycle_counts = list(csv.DictReader(stream))
        self.assertEqual(len(lifecycle_counts), len(result["transport_snapshot_times_us"]))
        for row in lifecycle_counts:
            self.assertEqual(sum(int(row[key]) for key in d.lifecycle.STATUSES), 3)
        self.assertEqual(int(lifecycle_counts[-1]["active"]), 0)
        self.assertEqual(metadata["full_transport_snapshots"]["times_us"], result["transport_snapshot_times_us"])
        old_snapshots = d.local._load_rows(root/"simultaneous_positions.csv")
        self.assertEqual(len({row["snapshot_index"] for row in old_snapshots}), 5)
        self.assertEqual(result["actual_minima_table"], "sampled_minima.csv")
        self.assertEqual(result["actual_spatial_minima_table"], "sampled_spatial_minima.csv")
        with (root/"sampled_spatial_minima.csv").open(newline="", encoding="utf-8") as stream:
            spatial = list(csv.DictReader(stream))
        self.assertEqual({r["metric"] for r in spatial},
                         {"sigma_x_mm", "sigma_y_mm", "sigma_local_x_mm", "sigma_local_y_mm"})
        self.assertTrue(all(r["metric_unit"] == "mm" for r in spatial))
        self.assertEqual(result["zero_field_minima_table"], "zero_field_minima.csv")
        zero = d.local._load_rows(root/"zero_field_plane_particles.csv")
        self.assertEqual(len(zero), 6)
        self.assertTrue(all(float(r["t_us"]) > float(r["birth_t_us"]) >= 7500. for r in zero))
        self.assertEqual(len(d.local._load_rows(root/"zero_field_plane_decisions.csv")), 9)
        with (root/"zero_field_minima.csv").open(newline="", encoding="utf-8") as stream:
            self.assertTrue(all(r["propagation_model"] == "zero_field_reference" for r in csv.DictReader(stream)))
        with (root/"sampled_minima.csv").open(newline="", encoding="utf-8") as stream:
            self.assertTrue(all(r.get("propagation_model") != "zero_field_reference" for r in csv.DictReader(stream)))
        with (root/"actual_zero_field_paired_statistics.csv").open(newline="", encoding="utf-8") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 12)
        rows = d.local._load_rows(root/"virtual_aperture_particles.csv")
        self.assertEqual(len(rows), 3*(1+2*2))
        self.assertTrue(any(r["status"] == "upstream_not_handed_off" for r in rows))
        self.assertTrue(all(r["frame"] == "reference_normal" for r in rows))
        contract["contract"]["schema_version"] = 2
        contract["contract"]["aperture_comparison"]["frame"] = "global_z"
        fixture._write_contract()
        with patch.object(d.local, "_save_figure", side_effect=save):
            result = d.analyze_focus_study(fixture.run)
        self.assertEqual(result["aperture_frame"], "global_z")
        rows = d.local._load_rows(root/"virtual_aperture_particles.csv")
        self.assertTrue(all(r["frame"] == "global_z" for r in rows))

    def test_explicit_plane_changes_selector_on_same_slanted_track(self) -> None:
        n = np.array([0., 1., -2.])/np.sqrt(5)
        reference = dict(origin_mm=[0., 0., -1.], normal=n.tolist(), e_x=[1., 0., 0.],
                         e_y=(np.array([0., 2., 1.])/np.sqrt(5)).tolist(), global_z_mm=-1.)
        aperture = dict(center_x_mm=0., center_y_mm=0.)
        track = [state(0., 0., .6, 0.), state(1., 0., 1.6, -2.)]
        accepted = {}
        for frame in ("global_z", "reference_normal"):
            plane, center = d._selector_plane(reference, aperture, frame)
            crossing = d.normal_crossing(track, plane, 1.)
            eta = float((d._vector(crossing)-center) @ np.array(plane["e_y"]))
            accepted[frame] = d.aperture_accepts(0., eta, 1., "y_slit", None)
        self.assertEqual(accepted, dict(global_z=False, reference_normal=True))
        with self.assertRaisesRegex(ValueError, "requires explicit"):
            d._aperture_frame(dict(schema_version=2, aperture_comparison={}))
        self.assertEqual(d._aperture_frame(dict(schema_version=1, aperture_comparison={})), "reference_normal")
        self.assertEqual(d._aperture_frame(dict(schema_version=3, aperture_comparison=dict(frame="global_z"))), "global_z")
        self.assertEqual(d._aperture_frame(dict(schema_version=4, aperture_comparison=dict(frame="global_z"))), "global_z")

    def test_transport_figures_handle_no_arrivals(self) -> None:
        from matplotlib import pyplot as plt

        case = dict(case=dict(case_id="D_empty", label="D", mass_u=524.,
                              pitch_mm=[.1, .2, .1], maximum_step_us=.001),
                    planes=dict(p1_exit={}), births={}, terminals={})
        texts = []
        def save(figure, path):
            figure.canvas.draw()
            texts.extend(t.get_text() for ax in figure.axes for t in ax.texts)
            plt.close(figure)
        with patch.object(d.local, "_save_figure", side_effect=save):
            names = d._transport_figures(fixtures.Path("unused"), [case], [], [], 7500.)
        self.assertEqual(len(names), 5)
        self.assertIn("No exit events", texts)
        self.assertIn("No shared active-time support", texts)

    def test_raw_halo_is_retained_but_not_used_for_normal_crossing(self) -> None:
        fixture = fixtures.LocalPrismDiagnosticsTests("test_empty_statistics_do_not_invent_fwhm")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        spec = fixture.contract["cases"][0]
        spec.update(mother_count=3, source_count=2, mass_u=524., maximum_step_us=.004,
                    source_csv="inputs/component_particle_state.csv", source_census_csv="inputs/source_census.csv")
        path = fixture.run/spec["directory"]/"samples.csv"
        with path.open(newline="") as stream:
            samples = list(csv.DictReader(stream))
        halo = fixtures._state(1, 7500.002+1.1+.001, "step", "sample", -99.1)
        halo["vx_mm_us"] = 10.
        fixtures._write_csv(path, [*samples, halo])
        planes = [dict(name=n, z_mm=z) for n, z in (("p1_near", -52.828), ("p1_far", -82.), ("p1_exit", -98.))]
        case = d._load_case(fixture.run, spec, planes)
        self.assertTrue(case["overshoots"][0]["bounded_interpolation_halo"])
        self.assertGreater(case["raw_tracks"][1][-1]["t_us"], case["tracks"][1][-1]["t_us"])
        energy = d.local._energy_drift_rows([case], 524., 1)
        by_scope = {r["observation_scope"]: r for r in energy if r["particle_id"] == 1}
        self.assertGreater(by_scope["all_raw_observations_with_interpolation_halo"]["max_absolute_drift_ev"],
                           by_scope["canonical_lifetime"]["max_absolute_drift_ev"])
        plane = dict(origin_mm=[0., 0., -99.05], normal=[0., 0., -1.])
        self.assertIsNone(d.normal_crossing(case["tracks"][1], plane, .3))
        halo["t_us"] += .01
        fixtures._write_csv(path, [*samples, halo])
        case = d._load_case(fixture.run, spec, planes)
        self.assertFalse(case["overshoots"][0]["bounded_interpolation_halo"])
        self.assertEqual(len(case["overshoots"]), 1)


if __name__ == "__main__":
    unittest.main()
