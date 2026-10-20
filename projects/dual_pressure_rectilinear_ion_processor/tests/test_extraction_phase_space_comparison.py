"""Pure analysis regression for controlled extraction; no commercial solver."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matplotlib import pyplot as plt
from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_numerical_boundaries
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection

from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison import (
    analyze_registered_study, export_comparison, build_comparison_figures, build_spatial_figures, factorial_effects, prepare_statistics, prepare_velocity_changes, validate_controlled_cases, prepare_spatial_crossings,
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
            case=dict(label="test",run=str(run),config=dict(native_timing=dict(pulse_start_us=10),diagnostics=dict(max_extraction_bracket_us=.02),source=dict(species=dict(mass_amu=524))),
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


if __name__ == "__main__":
    unittest.main()
