"""Pure analysis regression for controlled extraction; no commercial solver."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from matplotlib import pyplot as plt
from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_numerical_boundaries
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection

from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison import (
    analyze_registered_study, export_comparison, build_comparison_figures, build_spatial_figures, factorial_effects, prepare_statistics, prepare_velocity_changes, validate_controlled_cases, prepare_spatial_crossings, prepare_spatial_crossings_from_samples,
)


def cases_fixture() -> list[dict]:
    cases = []
    for length in (80., 61.5):
        for lift in (4000., 4480.):
            a, b = int(length < 80), int(lift > 4000)
            scale = 1 + 2*a + 3*b + 4*a*b
            states = []
            for stage, factor in (("birth", 1), ("pre_extraction", 2), ("exit_z0", 3)):
                for pid, velocity in ((1, -1.), (2, 1.), (3, 9.)):
                    if stage == "exit_z0" and pid == 3:
                        continue
                    status = "lost" if pid == 3 and stage == "pre_extraction" else "extracted" if stage == "exit_z0" else "alive"
                    states.append(dict(stage=stage, particle_id=pid, status=status, x_mm=float(pid), vx_mm_us=velocity*factor*scale/1000,
                                       Ex_eV=(velocity*factor*scale)**2, Ez_eV=10., total_energy_eV=11., z_mm=0., vz_mm_us=-1., theta_x_deg=velocity*scale if stage == "exit_z0" else None,
                                       theta_y_deg=velocity if stage == "exit_z0" else None, y_mm=float(pid)))
            cases.append(dict(label=f"L{length:g}V{lift:g}", lp_length_mm=length, lift_v=lift, sources={1:{},2:{},3:{}}, exits={1:{},2:{}}, states=states,
                              stages=["birth", "pre_extraction", "exit_z0"]))
    return cases


class ExtractionPhaseSpaceComparisonTests(unittest.TestCase):
    def test_registered_analysis_uses_explicit_sources_and_rejects_wrong_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            run=Path(temporary)
            cells=[dict(cell=str(i),run_id=f"fixture-{i}",lp_length_mm=a,lift_v=b)
                   for i,(a,b) in enumerate(((80,4000),(61.5,4000),(80,4480),(61.5,4480)))]
            study=dict(schema_version=1,role="ion_processor_extraction_control_study",cells=cells,
                       factor_A=dict(field="baseline.geometry.lp_length_mm"),
                       factor_B=dict(authority="baseline.electric.lift_v",derived_projection="native_operating_point.lift_v"))
            source_map={row["cell"]:str(run/row["run_id"]) for row in cells}
            config=dict(project="dual_pressure_rectilinear_ion_processor",mode="extraction_controlled_phase_space",
                        inputs=dict(study_contract=str(run/"study.json")),parameters=dict(planned_runs=source_map))
            (run/"study.json").write_text(json.dumps(study))
            (run/"run_config.json").write_text(json.dumps(config))
            with patch("projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison.export_comparison",return_value={"role":"fixture"}) as export:
                result=analyze_registered_study(run)
                self.assertEqual(result["status"],"success")
                self.assertEqual(set(export.call_args.args[0].values()),{Path(p) for p in source_map.values()})
                self.assertTrue((run/"summary.json").exists())
                config["parameters"]["planned_runs"]["0"]=str(run/"wrong-id")
                (run/"run_config.json").write_text(json.dumps(config))
                with self.assertRaisesRegex(ValueError,"registered run identity"):
                    analyze_registered_study(run)
            study["schema_version"]=2
            (run/"study.json").write_text(json.dumps(study))
            with self.assertRaisesRegex(ValueError,"unsupported"):
                analyze_registered_study(run)

    def test_registered_factors_cannot_mislabel_a_source(self):
        case=dict(run="fixture",lp_length_mm=80,lift_v=4000)
        study=dict(schema_version=1,role="ion_processor_extraction_control_study",analysis={},
                   cells=[dict(run_id="fixture",lp_length_mm=61.5,lift_v=4000)])
        with tempfile.TemporaryDirectory() as temporary, patch(
                "projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison.load_recorded_case",return_value=case):
            with self.assertRaisesRegex(ValueError,"registered cell"):
                export_comparison({"test":Path("fixture")},Path(temporary)/"results",study)

    def test_existing_functional_cli_routes_registered_analysis(self):
        from projects.dual_pressure_rectilinear_ion_processor.analysis import functional
        result=dict(status="success",source_counts={},extracted_counts={})
        with patch("sys.argv",["functional","compare-extraction-study","--run","fixture"]), patch(
                "projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison.analyze_registered_study",return_value=result) as analyze, patch("builtins.print"):
            functional.main()
            analyze.assert_called_once_with(Path("fixture"))

    def test_spatial_crossings_respect_pulse_brackets_and_actual_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            run=Path(temporary);(run/"simion").mkdir()
            sample=run/"simion/samples.csv"
            fields=["particle_id","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us"]
            with sample.open("w",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                for t,z,vx in ((9,12,.0),(11,10,.1),(11.01,8,.3),(11.5,3,.9)):
                    writer.writerow(dict(zip(fields,[1,t,0,170,z,vx,0,-1])))
            exit_state=dict(zip(fields,[1,12,0,170,0,.4,0,-1]))
            case=dict(label="test",run=str(run),config=dict(native_timing=dict(pulse_start_us=10),diagnostics=dict(max_extraction_bracket_us=.02),source=dict(species=dict(mass_amu=524)),coordinate_transform=dict(to_frame_id="fixture_world"),baseline=dict(clock=dict(epoch_us=0.))),
                      sources={1:{},2:{}},exits={1:exit_state},terminals={1:{"reason":"acceptance_surface"},2:{"reason":"solver_stop"}},source_records=[dict(path=str(sample))])
            result=prepare_spatial_crossings(case,[11,9,8,3,0])
            nine=next(r for r in result if r["particle_id"]==1 and r["plane_z_mm"]==9)
            self.assertAlmostEqual(nine["vx_mm_us"],.2)
            self.assertAlmostEqual(nine["interpolation_alpha"],.5)
            self.assertEqual((nine["lower_sample_line"],nine["upper_sample_line"]),(3,4))
            self.assertEqual(next(r for r in result if r["particle_id"]==1 and r["plane_z_mm"]==11)["status"],"unknown")
            self.assertEqual(next(r for r in result if r["particle_id"]==1 and r["plane_z_mm"]==3)["status"],"unknown")
            zero=next(r for r in result if r["particle_id"]==1 and r["plane_z_mm"]==0)
            self.assertEqual(zero["vx_mm_us"],.4)
            self.assertEqual(zero["method"],"recorded_extraction_exit_event")
            self.assertIsNone(zero["bracket_gap_us"])
            self.assertTrue(all(r["status"]=="unknown" for r in result if r["particle_id"]==2))
            with self.assertRaisesRegex(ValueError,"descending"):
                prepare_spatial_crossings(case,[0,9])

            # A real exit may bound the unsampled positive-z tail, without z=0
            # being requested. A long gap must remain unknown.
            case["exits"][1]["t_us"] = 11.51
            tail = prepare_spatial_crossings(case,[2,1])
            self.assertTrue(all(r["status"] == "alive" for r in tail if r["particle_id"] == 1))
            self.assertEqual(tail[0]["method"],"bounded_sample_to_exit_event_crossing")
            self.assertEqual(tail[0]["lower_sample_line"],5)
            self.assertIsNone(tail[0]["upper_sample_line"])
            self.assertAlmostEqual(tail[0]["t_us"],11.5+.01/3)
            case["exits"][1]["t_us"] = 11.6
            self.assertTrue(all(r["status"] == "unknown" for r in prepare_spatial_crossings(case,[2,1])))
    def test_only_registered_physical_variables_may_change(self):
        cases = cases_fixture()
        contract = dict(factor_A=dict(levels=[80.,61.5]), factor_B=dict(levels=[4000.,4480.]), execution=dict(particle_count=3), stages=cases[0]["stages"])
        configuration = Path(__file__).resolve().parents[1] / "config"
        for case in cases:
            config = {key:json.loads((configuration / f"{key}.json").read_text(encoding="utf-8")) for key in ("baseline", "native_operating_point", "source", "numerics", "coordinate_transform", "diagnostics", "field_diagnostics", "acceptance")}
            config.update(native_timing={"pulse":1}, source_profile="functional")
            config["baseline"]["geometry"]["lp_length_mm"] = case["lp_length_mm"]
            config["baseline"]["electric"]["lift_v"] = case["lift_v"]
            config["native_operating_point"]["lift_v"] = case["lift_v"]
            config["native_projection"] = native_projection(config["baseline"], config["numerics"])
            config["numerical_boundaries"] = derive_numerical_boundaries(config["native_projection"])
            case["config"] = config
        validate_controlled_cases(cases,contract)
        for mutation, expected in ((lambda c:c[0]["config"]["numerics"].update(dt=.02),"undeclared"),
                                   (lambda c:c[0]["config"]["baseline"]["geometry"].update(lp_center_mm=169.),"projection|undeclared"),
                                   (lambda c:c[0]["config"]["native_operating_point"].update(lift_v=4001),"projection"),
                                   (lambda c:c[0].update(lp_length_mm=79.),"outside"),
                                   (lambda c:c[0]["config"]["numerical_boundaries"].update(downstream_exit_x_mm=999),"boundaries"),
                                   (lambda c:c[0]["config"]["native_projection"]["maximum_mm"].__setitem__(1,999),"projection"),
                                   (lambda c:c[0]["sources"].pop(3),"source count")):
            bad = copy.deepcopy(cases)
            mutation(bad)
            with self.assertRaisesRegex(ValueError,expected):
                validate_controlled_cases(bad,contract)

    def test_controlled_effects_have_declared_sign_and_interaction(self):
        cases = cases_fixture()
        stats, _, common = prepare_statistics(cases)
        self.assertEqual(common, [1, 2])
        effects = factorial_effects(stats, cases)
        row = next(r for r in effects if r["stage"] == "exit_z0" and r["cohort"] == "common_extracted_ids" and r["metric"] == "sigma_theta_x_deg")
        self.assertEqual(row["length_at_low"], 2)
        self.assertEqual(row["length_at_high"], 6)
        self.assertEqual(row["lift_at_long"], 3)
        self.assertEqual(row["lift_at_short"], 7)
        self.assertEqual(row["length_main_effect"], 4)
        self.assertEqual(row["lift_main_effect"], 5)
        self.assertEqual(row["interaction"], 4)

    def test_census_and_same_id_variance_do_not_count_loss_as_live(self):
        cases = cases_fixture()
        stats, intervals, _ = prepare_statistics(cases)
        row = next(r for r in stats if r["case"] == cases[0]["label"] and r["stage"] == "pre_extraction" and r["cohort"] == "all_available_alive")
        self.assertEqual(row["observed_count"], 2)
        self.assertEqual(row["lost_count"], 1)
        self.assertEqual(row["sigma_vx_m_s"], 2)
        self.assertEqual(row["angle_x_count"], 0)
        self.assertIsNone(row["sigma_theta_x_deg"])
        row = next(r for r in intervals if r["case"] == cases[0]["label"] and r["cohort"] == "all_available_alive" and r["to_stage"] == "pre_extraction")
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["variance_change_m2_s2"], 3)
        self.assertEqual(row["twice_cov_before_delta_m2_s2"], 2)
        self.assertEqual(row["variance_delta_m2_s2"], 1)
        self.assertEqual(row["variance_identity_residual_m2_s2"], 0)

    def test_factorial_fails_closed_on_missing_or_duplicate_cell(self):
        cases = cases_fixture()
        stats, _, _ = prepare_statistics(cases)
        for bad in (cases[:-1], cases[:-1]+[cases[0]]):
            with self.assertRaisesRegex(ValueError, "two-by-two"):
                factorial_effects(stats, bad)

    def test_no_common_exit_fails_closed(self):
        cases = cases_fixture()
        cases[-1]["exits"] = {4:{}}
        with self.assertRaisesRegex(ValueError, "no common"):
            prepare_statistics(cases)

    def test_pre_exit_variance_identity_and_correlations_use_available_same_ids(self):
        cases = cases_fixture()
        changes, decompositions, correlations = prepare_velocity_changes(cases, [1, 2])
        row = decompositions[0]
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["variance_pre_m2_s2"], 4)
        self.assertEqual(row["variance_exit_m2_s2"], 9)
        self.assertEqual(row["variance_delta_m2_s2"], 1)
        self.assertEqual(row["twice_cov_pre_delta_m2_s2"], 4)
        self.assertEqual(row["residual_m2_s2"], 0)
        self.assertTrue(all(r["particle_id"] != 3 for r in changes))
        self.assertAlmostEqual(correlations[0]["pearson_r"], 1)

    def test_render_shares_scales_and_labels_components(self):
        cases = cases_fixture()
        original = copy.deepcopy(cases)
        stats, _, _ = prepare_statistics(cases)
        figures = build_comparison_figures(cases, stats)
        try:
            self.assertEqual(len(figures), 3)
            fig = figures["extraction_control__exit_phase_space"]
            self.assertEqual(fig.axes[1].get_ylabel(), "Theta x, xz plane (deg)")
            self.assertEqual(fig.axes[2].get_ylabel(), "Theta y, yz plane (deg)")
            self.assertEqual(fig.axes[0].get_xlim(), fig.axes[3].get_xlim())
            self.assertEqual(fig.axes[1].get_ylim(), fig.axes[4].get_ylim())
            fig.canvas.draw()
            self.assertEqual(cases, original)
        finally:
            for fig in figures.values():
                plt.close(fig)

    def test_spatial_width_figure_discloses_each_plane_available_count(self):
        cases=cases_fixture()
        for case in cases:
            for row in case["states"]:
                z={"birth":9,"pre_extraction":5,"exit_z0":0}[row["stage"]]
                row.update(plane_z_mm=z,stage=f"z_{z:g}_mm")
                if row["status"]=="extracted":
                    row["status"]="alive"
            case["stages"]=["z_9_mm","z_5_mm","z_0_mm"]
        stats,_,_=prepare_statistics(cases)
        figures=build_spatial_figures(cases,stats,[9,5,0])
        try:
            fig=figures["extraction_control__spatial_widths"]
            self.assertEqual(fig.axes[4].get_ylabel(),"Valid crossings (of common N=2)")
            self.assertEqual(list(fig.axes[4].lines[0].get_ydata()),[2,2,2])
            fig.canvas.draw()
        finally:
            for fig in figures.values():
                plt.close(fig)


def sample(pid: int, time: float, z: float, **updates: float) -> dict:
    return dict(particle_id=pid, t_us=time, x_mm=2.0, y_mm=5.0, z_mm=z,
                vx_mm_us=0.0, vy_mm_us=0.0, vz_mm_us=-1.0) | updates


def case_fixture() -> dict:
    return dict(
        label="bounded-crossing",
        config=dict(coordinate_transform=dict(to_frame_id="fixture_world"),
                    baseline=dict(clock=dict(epoch_us=0.)), native_timing=dict(pulse_start_us=10.0),
                    diagnostics=dict(max_extraction_bracket_us=0.5),
                    source=dict(species=dict(mass_amu=524.0))),
        sources={1: {}, 2: {}, 3: {}}, exits={},
        terminals={1: {"reason": "acceptance_surface"},
                   2: {"reason": "solver_stop"}, 3: {"reason": "timeout"}},
    )


class SpatialCrossingSamplesTests(unittest.TestCase):
    def test_pure_module_import_does_not_load_workflow_or_plotting(self):
        code = (
            "import sys; "
            "from projects.dual_pressure_rectilinear_ion_processor.analysis.spatial_crossings "
            "import prepare_spatial_crossings_from_samples; "
            "assert callable(prepare_spatial_crossings_from_samples); "
            "assert 'projects.dual_pressure_rectilinear_ion_processor.analysis.functional' not in sys.modules; "
            "assert 'matplotlib.pyplot' not in sys.modules"
        )
        subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3],
                       check=True, capture_output=True, text=True, timeout=30)

    def test_file_wrapper_equals_pure_rows_without_mutating_inputs(self):
        case = case_fixture()
        rows = [sample(1, 9.75, 6), sample(1, 10, 4),
                sample(2, 10, 4), sample(1, 10.5, 2, x_mm=6, vx_mm_us=2)]
        case["exits"][1] = sample(1, 11, 0, x_mm=10, vx_mm_us=4)
        planes = [5.0, 4.0, 3.0, 2.0, 1.0, 0.0]
        before = copy.deepcopy((case, rows))
        pure = prepare_spatial_crossings_from_samples(case, planes, enumerate(rows, start=2))
        self.assertEqual((case, rows), before)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "simion" / "samples.csv"
            path.parent.mkdir()
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            file_case = case | {"run": temporary, "source_records": [{"path": str(path)}]}
            self.assertEqual(prepare_spatial_crossings(file_case, planes), pure)

        middle = next(row for row in pure if row["particle_id"] == 1 and row["plane_z_mm"] == 3)
        self.assertEqual((middle["t_us"], middle["x_mm"], middle["vx_mm_us"]), (10.25, 4, 1))
        self.assertEqual((middle["lower_sample_line"], middle["upper_sample_line"]), (3, 5))
        self.assertEqual(middle["theta_x_deg"], 45)
        tail = next(row for row in pure if row["particle_id"] == 1 and row["plane_z_mm"] == 1)
        self.assertEqual((tail["t_us"], tail["x_mm"]), (10.75, 8))
        self.assertEqual(tail["method"], "bounded_sample_to_exit_event_crossing")
        self.assertEqual(tail["lower_sample_line"], 5)
        self.assertIsNone(tail["upper_sample_line"])
        zero = next(row for row in pure if row["particle_id"] == 1 and row["plane_z_mm"] == 0)
        self.assertEqual(zero["method"], "recorded_extraction_exit_event")
        self.assertEqual((zero["t_us"], zero["vx_mm_us"]), (11, 4))
        self.assertIsNone(zero["interpolation_alpha"])

    def test_endpoints_are_inclusive_and_first_crossing_is_preserved(self):
        rows = [(11, sample(1, 10, 4)), (17, sample(1, 10.5, 2)),
                (23, sample(1, 10.75, 4, vz_mm_us=1)),
                (29, sample(1, 11, 4)), (35, sample(1, 11.5, 2))]
        result = prepare_spatial_crossings_from_samples(case_fixture(), [4, 2], iter(rows))
        observed = [row for row in result if row["particle_id"] == 1]
        self.assertEqual([row["interpolation_alpha"] for row in observed], [0, 1])
        self.assertEqual([row["t_us"] for row in observed], [10, 10.5])
        self.assertTrue(all((row["lower_sample_line"], row["upper_sample_line"]) == (11, 17)
                            for row in observed))

    def test_no_extrapolation_and_every_missing_mother_id_remains_explicit(self):
        case = case_fixture()
        rows = [(2, sample(1, 9.75, 6)), (3, sample(1, 10, 4)),
                (4, sample(1, 10.5, 2)), (5, sample(2, 10, 4))]
        result = prepare_spatial_crossings_from_samples(case, [5, 3, 1, 0], rows)
        self.assertEqual([(row["plane_z_mm"], row["particle_id"]) for row in result],
                         [(z, pid) for z in [5, 3, 1, 0] for pid in [1, 2, 3]])
        self.assertEqual(sum(row["status"] == "alive" for row in result), 1)
        empty = prepare_spatial_crossings_from_samples(case, [1, 0], iter(()))
        self.assertEqual(len(empty), 6)
        self.assertTrue(all(row["status"] == "unknown" for row in empty))
        for row in result:
            if row["status"] == "unknown":
                self.assertEqual(row["reason"], "no_valid_recorded_crossing")
                self.assertEqual(row["terminal_reason"], case["terminals"][row["particle_id"]]["reason"])
                for key in ("t_us", "x_mm", "z_mm", "vz_mm_us", "method", "theta_x_deg", "total_energy_eV"):
                    self.assertIsNone(row[key])

    def test_long_gap_or_nonforward_endpoint_does_not_make_a_crossing(self):
        for time, before_vz, after_vz in ((10.75, -1, -1), (10.5, 0, -1), (10.5, -1, 1)):
            with self.subTest(time=time, before_vz=before_vz, after_vz=after_vz):
                rows = [(2, sample(1, 10, 4, vz_mm_us=before_vz)),
                        (3, sample(1, time, 2, vz_mm_us=after_vz))]
                result = prepare_spatial_crossings_from_samples(case_fixture(), [3], rows)
                self.assertTrue(all(row["status"] == "unknown" for row in result))

    def test_equal_or_decreasing_per_particle_time_fails_despite_interleaving(self):
        for time in (10.0, 10.25):
            with self.subTest(time=time):
                rows = [(2, sample(1, 10.25, 4)), (3, sample(2, 10.5, 4)),
                        (4, sample(1, time, 2))]
                with self.assertRaisesRegex(ValueError, "time not increasing for particle"):
                    prepare_spatial_crossings_from_samples(case_fixture(), [3], rows)


    def test_prepulse_filter_keeps_prior_identity_state_and_order_skip_policy(self):
        rows = [(2, dict(particle_id=999, t_us=9.5)),
                (3, dict(particle_id=999, t_us=8.5)),
                (4, sample(1, 10., 4.)),
                (5, dict(t_us=9.)),
                (6, sample(1, 10.5, 2.))]
        result = prepare_spatial_crossings_from_samples(case_fixture(), [3.], iter(rows))[0]
        self.assertEqual((result["t_us"], result["lower_sample_line"], result["upper_sample_line"]),
                         (10.25, 4, 6))
        with self.assertRaisesRegex(ValueError, "source row number"):
            prepare_spatial_crossings_from_samples(case_fixture(), [3.], [(0, dict(t_us=9.))])

    def test_zero_only_request_checks_postpulse_time_but_requires_recorded_exit(self):
        rows = [(2, sample(1, 10., 1.)), (3, sample(1, 10.5, -1.))]
        result = prepare_spatial_crossings_from_samples(case_fixture(), [0.], iter(rows))
        self.assertTrue(all(row["status"] == "unknown" for row in result))
        for time in (10., 9.999):
            case = case_fixture()
            case["config"]["native_timing"]["pulse_start_us"] = 9.
            with self.subTest(time=time), self.assertRaisesRegex(ValueError, "time not increasing for particle"):
                prepare_spatial_crossings_from_samples(case, [0.],
                    [(2, sample(1, 10., 1.)), (3, sample(1, time, -1.))])

    def test_earlier_or_equal_exit_replaces_late_sample_as_final_anchor(self):
        for time in (10.75, 11.):
            with self.subTest(time=time):
                case = case_fixture()
                case["exits"][1] = sample(1, time, 0.)
                rows = [(2, sample(1, 10.5, 4.)), (3, sample(1, 11., 2.))]
                result = prepare_spatial_crossings_from_samples(case, [1., 0.], iter(rows))
                one, zero = [row for row in result if row["particle_id"] == 1]
                self.assertEqual(one["status"], "alive")
                self.assertEqual(one["t_us"], 10.5+.75*(time-10.5))
                self.assertEqual(one["method"], "bounded_sample_to_exit_event_crossing")
                self.assertEqual(one["lower_sample_line"], 2)
                self.assertIsNone(one["upper_sample_line"])
                self.assertEqual((zero["t_us"], zero["method"]), (time, "recorded_extraction_exit_event"))
                self.assertIsNone(zero["interpolation_alpha"])

    def test_known_exit_and_nonexit_terminal_preserve_supported_lifetime_segment(self):
        for reason, end_z in (("acceptance_surface", 0.), ("solver_stop", 1.), ("downstream_domain_exit", 1.)):
            with self.subTest(reason=reason):
                case = case_fixture()
                case["sources"] = {7: sample(7, 9., 8.), 19: sample(19, 9., 8.)}
                case["particle_weights"] = {7: .125, 19: 8.}
                endpoint = sample(7, 10.75, end_z, x_mm=10.)
                case["terminals"] = {7: dict(endpoint, reason=reason)}
                case["exits"] = {7: endpoint} if reason == "acceptance_surface" else {}
                samples = [(2, sample(7, 10.5, 4.)), (3, sample(19, 10.5, 4.)),
                           (4, sample(7, 11., -1., x_mm=99.))]
                original = copy.deepcopy((case, samples))
                rows = prepare_spatial_crossings_from_samples(case, [4., 2., 1., .5, 0.], iter(samples))
                self.assertEqual((case, samples), original)
                self.assertEqual({row["particle_id"] for row in rows}, {7,19})
                observed = {row["plane_z_mm"]: row for row in rows if row["particle_id"] == 7}
                middle = observed[2.]
                alpha = 2./(4.-end_z)
                self.assertEqual(middle["t_us"], 10.5+alpha*.25)
                self.assertEqual(middle["x_mm"], 2.+alpha*8.)
                self.assertEqual((middle["lower_sample_line"], middle["upper_sample_line"]), (2,None))
                self.assertEqual((middle["bracket_start_us"], middle["bracket_end_us"]), (10.5,10.75))
                self.assertEqual(observed[4.]["t_us"], 10.5)
                if reason == "acceptance_surface":
                    self.assertEqual((observed[.5]["status"], observed[.5]["t_us"]), ("alive",10.71875))
                    self.assertEqual(observed[0.]["t_us"], 10.75)
                else:
                    self.assertEqual(middle["method"], "bounded_sample_to_terminal_event_crossing")
                    self.assertTrue(all(observed[z]["status"] == "unknown" for z in (1.,.5,0.)))
                self.assertTrue(all(row["status"] == "unknown" for row in rows if row["particle_id"] == 19))

    def test_terminal_endpoint_is_excluded_and_missing_terminal_does_not_invent_a_bound(self):
        samples = [(2, sample(1, 10., 4.)), (3, sample(1, 10.5, 2.)), (4, sample(1, 10.75, 0.))]
        for terminal in (None, {"reason": "solver_stop"}, {"t_us": 10.5, "reason": "solver_stop"},
                         dict(sample(1, 10.5, 2.), reason="solver_stop")):
            case = case_fixture()
            case["terminals"] = {} if terminal is None else {1: terminal}
            with self.subTest(terminal=terminal):
                rows = prepare_spatial_crossings_from_samples(case, [3.,2.,1.], iter(samples))
                observed = [row for row in rows if row["particle_id"] == 1]
                self.assertEqual((observed[0]["status"], observed[0]["t_us"]), ("alive",10.25))
                expected = "unknown" if terminal and "t_us" in terminal else "alive"
                self.assertEqual([row["status"] for row in observed[1:]], [expected,expected])
                if terminal is None:
                    self.assertIsNone(observed[0]["terminal_reason"])
        case["terminals"] = {1: dict(t_us=10.25, reason="solver_stop")}
        rows = prepare_spatial_crossings_from_samples(case, [3.], iter(samples))
        self.assertTrue(all(row["status"] == "unknown" for row in rows))

    def test_terminal_anchor_keeps_gap_direction_and_pulse_bounds(self):
        for time, vz, expected in ((10.5,-1.,"alive"), (10.5000001,-1.,"unknown"),
                                   (10.5,0.,"unknown"), (10.5,1.,"unknown"),
                                   (9.9,-1.,"unknown"), (10.,-1.,"unknown")):
            case = case_fixture()
            case["terminals"][1] = dict(sample(1,time,2.,vz_mm_us=vz),reason="solver_stop")
            with self.subTest(time=time, vz=vz):
                rows = prepare_spatial_crossings_from_samples(case, [3.], [(2,sample(1,10.,4.))])
                self.assertEqual(rows[0]["status"], expected)
                if expected == "alive":
                    self.assertEqual(rows[0]["t_us"], 10.25)

    def test_known_lifetime_conflicts_and_invalid_postterminal_samples_fail(self):
        endpoint = dict(sample(1, 10.75, 0.), reason="acceptance_surface")
        for changed in (dict(t_us=10.5), dict(t_us=11.), dict(t_us=float("nan")), dict(x_mm=float("inf"))):
            case = case_fixture()
            case["exits"] = {1: endpoint}
            case["terminals"][1] = endpoint | changed
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "terminal|finite"):
                prepare_spatial_crossings_from_samples(case, [.5,0.], [(2,sample(1,10.5,4.))])
        case = case_fixture()
        case["terminals"][1] = dict(sample(1, 10.75, 0.), reason="solver_stop")
        for samples in ([(2,sample(1,11.,-1.)),(3,sample(1,10.9,-2.))],
                        [(2,sample(1,11.,-1.,x_mm=float("nan")))],
                        [(2,sample(99,11.,-1.))]):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                prepare_spatial_crossings_from_samples(case, [.5], iter(samples))

    def test_exit_tolerance_cannot_authorize_positive_plane_extrapolation(self):
        case = case_fixture()
        case["exits"][1] = sample(1, 10.5, 1e-11)
        result = prepare_spatial_crossings_from_samples(case, [1e-12, 0.], [(2, sample(1, 10., 1.))])
        below_exit, zero = [row for row in result if row["particle_id"] == 1]
        self.assertEqual(below_exit["status"], "unknown")
        self.assertIsNone(below_exit["interpolation_alpha"])
        self.assertEqual((zero["t_us"], zero["z_mm"]), (10.5, 1e-11))
        self.assertEqual(zero["method"], "recorded_extraction_exit_event")

    def test_epoch_is_added_once_only_in_core_view_and_raw_interpolation_is_preserved(self):
        from projects.dual_pressure_rectilinear_ion_processor.analysis import spatial_crossings as adapter
        case = case_fixture()
        case["config"]["baseline"]["clock"]["epoch_us"] = 1024.
        rows = [(2, sample(1, 10., 4., vx_mm_us=.49472944992699563)),
                (3, sample(1, 10.5, 2., vx_mm_us=.899852148325918))]
        original = adapter.iter_bounded_plane_crossings
        seen, call = [], {}
        def inspect(values, **keywords):
            call.update(keywords)
            def forward():
                for value in values:
                    seen.append(value)
                    yield value
            yield from original(forward(), **keywords)
        with patch.object(adapter, "iter_bounded_plane_crossings", side_effect=inspect):
            result = adapter.prepare_spatial_crossings_from_samples(case, [3.], iter(rows))[0]
        self.assertEqual([row.state.instrument_time_us for row in seen], [1034., 1034.5])
        self.assertEqual([row.state.frame_id for row in seen], ["fixture_world", "fixture_world"])
        self.assertEqual(call["minimum_time_us"], 1034.)
        self.assertEqual(seen[0].state.velocity_m_s[0], rows[0][1]["vx_mm_us"]*1000.)
        self.assertEqual((result["t_us"], result["bracket_start_us"], result["bracket_end_us"],
                          result["bracket_gap_us"], result["time_after_pulse_us"]), (10.25, 10., 10.5, .5, .25))
        expected = rows[0][1]["vx_mm_us"]+.5*(rows[1][1]["vx_mm_us"]-rows[0][1]["vx_mm_us"])
        self.assertEqual(result["vx_mm_us"], expected)

    def test_close_planes_keep_distinct_identity_and_samples_are_consumed_once(self):
        class OnePass:
            def __init__(self):
                self.started = False
            def __iter__(self):
                if self.started:
                    raise AssertionError("raw source was reread")
                self.started = True
                yield 2, sample(1, 10., 4.)
                yield 3, sample(2, 10., 4.)
                yield 4, sample(1, 10.5, 2., x_mm=6.)
                yield 5, sample(2, 10.5, 2., x_mm=10.)
        result = prepare_spatial_crossings_from_samples(case_fixture(), [3.0000001, 3.], OnePass())
        observed = [row for row in result if row["particle_id"] == 1]
        self.assertNotEqual(observed[0]["t_us"], observed[1]["t_us"])
        self.assertEqual(observed[1]["x_mm"], 4.)
        self.assertEqual((observed[1]["lower_sample_line"], observed[1]["upper_sample_line"]), (2, 4))
        other = next(row for row in result if row["particle_id"] == 2 and row["plane_z_mm"] == 3.)
        self.assertEqual((other["x_mm"], other["lower_sample_line"], other["upper_sample_line"]), (6., 3, 5))

    def test_frame_and_epoch_must_come_from_declared_case(self):
        for field in ("coordinate_transform", "baseline"):
            case = case_fixture()
            del case["config"][field]
            with self.subTest(field=field), self.assertRaises(KeyError):
                prepare_spatial_crossings_from_samples(case, [0.], iter(()))

    def test_source_line_numbers_must_be_positive_integers(self):
        for line in (0, -1, True, 2.0):
            with self.subTest(line=line):
                with self.assertRaisesRegex(ValueError, "source row number must be a positive integer"):
                    prepare_spatial_crossings_from_samples(case_fixture(), [3], [(line, sample(1, 10, 4))])


if __name__ == "__main__":
    unittest.main()
