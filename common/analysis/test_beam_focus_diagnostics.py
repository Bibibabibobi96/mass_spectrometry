"""Independent analytic regression, drift, membership and headless checks."""
from __future__ import annotations

import copy
import unittest

import numpy as np

from common.analysis.beam_focus_diagnostics import (
    prepare_focus_diagnostics, build_focus_figure, prepare_time_focus_diagnostics, build_time_focus_figure,
)


def fixture() -> dict:
    states=[]
    # At reference z=0: x=-L*u with L=10, and t=10-20/abs(vz).
    for z in (1.,0.):
        for pid,u,speed in ((1,-.1,1.),(2,0.,2.),(3,.1,4.)):
            states.append(dict(plane_z_mm=z,particle_id=pid,status="alive",x_mm=-10*u-z*u,
                y_mm=float(pid),t_us=10-20/speed-z/speed,vx_mm_us=u*speed,vy_mm_us=0.,vz_mm_us=-speed))
    return dict(label="Analytic",particle_weights={i:1. for i in (1,2,3)},sources={i:{} for i in (1,2,3)},exits={i:{} for i in (1,2,3)},states=states)


class BeamFocusTests(unittest.TestCase):
    def prepare(self,case=None,common=None):
        return prepare_focus_diagnostics([fixture() if case is None else case],[1.,0.],[1,2,3] if common is None else common)

    def test_independent_regression_and_waist_predictions(self):
        result=self.prepare()
        rows=[r for r in result["field_free_predictions"] if r["cohort"]=="common_extracted_ids"]
        x=next(r for r in rows if r["coordinate"]=="x")
        self.assertAlmostEqual(x["L_star_mm"],10.)
        self.assertAlmostEqual(x["z_focus_mm"],-10.)
        self.assertAlmostEqual(x["sigma_at_prediction"],0.)
        time=next(r for r in rows if r["coordinate"]=="time")
        self.assertAlmostEqual(time["L_star_mm"],20.)
        self.assertAlmostEqual(time["sigma_at_prediction"],0.)
        self.assertEqual(time["sigma_unit"],"ns")
        angle=next(r for r in result["exit_angle_decomposition"] if r["axis"]=="x")
        self.assertAlmostEqual(angle["rho"],-1.)
        self.assertAlmostEqual(angle["sigma_residual_deg"],0.)
        self.assertAlmostEqual(angle["sigma_total_deg"],np.degrees(np.arctan(.1))*np.sqrt(2/3))
        self.assertAlmostEqual(angle["variance_identity_residual_deg2"],0.)

    def test_common_own_and_changing_alive_membership_are_explicit(self):
        case=fixture();case["exits"]={1:{},2:{}}
        next(r for r in case["states"] if r["plane_z_mm"]==0 and r["particle_id"]==3)["status"]="unknown"
        result=self.prepare(case,common=[1,2])
        alive=next(r for r in result["sampled_minima"] if r["cohort"]=="all_available_alive")
        self.assertFalse(alive["cohort_membership_constant"])
        self.assertFalse(alive["eligible_for_envelope_comparison"])
        own=next(r for r in result["sampled_minima"] if r["cohort"]=="own_extracted_ids")
        self.assertTrue(own["cohort_membership_constant"])
        self.assertTrue(own["eligible_for_envelope_comparison"])
        last=next(r for r in result["plane_statistics"] if r["cohort"]=="all_available_alive" and r["plane_z_mm"]==0)
        self.assertEqual(last["available_ids"],[1,2])
        self.assertEqual(last["missing_ids"],[3])

    def test_constant_empty_missing_and_nonfinite_values(self):
        case=fixture()
        for row in case["states"]:
            row["vx_mm_us"]=0.;row["x_mm"]=1.
        result=self.prepare(case,common=[])
        row=next(r for r in result["field_free_predictions"] if r["coordinate"]=="x" and r["cohort"]=="own_extracted_ids")
        self.assertIsNone(row["L_star_mm"])
        self.assertEqual(row["sigma_at_reference"],0.)
        empty=next(r for r in result["exit_angle_decomposition"] if r["cohort"]=="common_extracted_ids")
        self.assertIsNone(empty["sigma_total_deg"])
        case["states"][0]["t_us"]=None
        missing=self.prepare(case)
        row=next(r for r in missing["sampled_minima"] if r["metric"]=="sigma_t_ns")
        self.assertFalse(row["metric_complete_all_planes"])
        case["states"][0]["t_us"]=float("nan")
        with self.assertRaisesRegex(ValueError,"finite"):
            self.prepare(case)

    def test_stable_incomplete_common_is_not_a_complete_cohort_envelope(self):
        case=fixture()
        for row in case["states"]:
            if row["particle_id"]==3:
                row["status"]="unknown"
        result=self.prepare(case)
        row=next(r for r in result["sampled_minima"] if r["cohort"]=="common_extracted_ids")
        self.assertTrue(row["cohort_membership_constant"])
        self.assertFalse(row["covers_declared_cohort"])
        self.assertFalse(row["eligible_for_envelope_comparison"])
        from matplotlib import pyplot as plt
        figure=build_focus_figure(result)
        self.assertIn("valid N=2",figure.legends[0].get_texts()[0].get_text())
        self.assertIn("Declared common exit N=3",figure.legends[0].get_title().get_text())
        plt.close(figure)

    def test_invalid_duplicate_identity_and_reference_plane(self):
        case=fixture();case["states"].append(copy.deepcopy(case["states"][0]))
        with self.assertRaisesRegex(ValueError,"duplicate"):
            self.prepare(case)
        with self.assertRaises(ValueError):
            prepare_focus_diagnostics([fixture()],[0.,1.],[1])
        with self.assertRaises(ValueError):
            prepare_focus_diagnostics([fixture()],[1.,0.],[99])
        self.assertEqual(self.prepare()["reference_z_mm"],0.)

    def test_every_identity_container_rejects_noninteger_or_nonpositive_ids(self):
        for bad_id in (True, False, 1.0, np.float64(1.), 1+0j, "1", 0, -1):
            for field in ("sources", "exits", "particle_weights", "common", "states"):
                case, common = fixture(), [1,2,3]
                if field == "common":
                    common[0] = bad_id
                elif field == "states":
                    case["states"][0].update(particle_id=bad_id, status="unknown")
                else:
                    case[field] = {bad_id if pid == 1 else pid: value for pid, value in case[field].items()}
                for prepare in (prepare_focus_diagnostics, prepare_time_focus_diagnostics):
                    args = ([case], [1.,0.], common)
                    if prepare is prepare_time_focus_diagnostics:
                        args += ({"drift_lengths_mm":[0.]},)
                    with self.subTest(id=bad_id, field=field, entry=prepare.__name__), self.assertRaisesRegex(ValueError, "positive integer particle IDs"):
                        prepare(*args)

    def test_noncontiguous_original_ids_and_unknown_states_remain_explicit(self):
        case = fixture()
        mapping = {1:7, 2:19, 3:31}
        for field in ("sources", "exits", "particle_weights"):
            case[field] = {mapping[pid]: value for pid, value in reversed(list(case[field].items()))}
        for row in case["states"]:
            row["particle_id"] = mapping[row["particle_id"]]
            if row["particle_id"] == 31 and row["plane_z_mm"] == 0.:
                row["status"] = "unknown"
        before = copy.deepcopy(case)
        result = prepare_time_focus_diagnostics([case], [1.,0.], [31,7,19], {"drift_lengths_mm":[0.]})
        row = next(r for r in result["plane_time_statistics"] if r["cohort"] == "common_extracted_ids" and r["plane_z_mm"] == 0.)
        self.assertEqual(row["available_ids"], [7,19])
        self.assertEqual(row["missing_ids"], [31])
        self.assertEqual(row["weight_sum"], 2.)
        self.assertTrue(row["paired_complete"])  # The two observed states are complete.
        self.assertEqual(case, before)

    def test_sampled_boundary_minimum_and_single_header_render(self):
        from matplotlib import pyplot as plt
        result=self.prepare()
        minimum=next(r for r in result["sampled_minima"] if r["metric"]=="sigma_x_mm")
        self.assertEqual(minimum["plane_z_mm"],0.)
        self.assertTrue(minimum["boundary_minimum"])
        figure=build_focus_figure(result)
        self.assertEqual(len(figure.axes),6)
        self.assertEqual(len(figure.legends),1)
        self.assertIsNone(figure._suptitle)
        self.assertTrue(all(ax.get_legend() is None for ax in figure.axes))
        self.assertGreater(figure.axes[0].get_xlim()[0],figure.axes[0].get_xlim()[1])
        figure.canvas.draw();plt.close(figure)


class TimeFocusTests(unittest.TestCase):
    def prepare(self,case=None,common=None,lengths=None):
        return prepare_time_focus_diagnostics([fixture() if case is None else case],[1.,0.],
            [1,2,3] if common is None else common,{"drift_lengths_mm":[0.,10.,20.,30.] if lengths is None else lengths})

    def test_known_time_focus_quadratic_and_absolute_particle_times(self):
        result=self.prepare()
        row=next(r for r in result["plane_time_statistics"] if r["cohort"]=="common_extracted_ids" and r["plane_z_mm"]==0)
        self.assertAlmostEqual(row["unconstrained_L_star_mm"],20.)
        self.assertAlmostEqual(row["downstream_L_star_mm"],20.)
        self.assertAlmostEqual(row["downstream_min_sigma_t_ns"],0.)
        self.assertAlmostEqual(row["rho_t_inverse_abs_vz"],-1.)
        self.assertEqual(row["rho_t_x_mm_matched_count"],3)
        self.assertEqual(row["rho_t_y_mm_matched_count"],3)
        self.assertAlmostEqual(row["rho_t_x_mm"],np.corrcoef([-10.,0.,5.],[1.,0.,-1.])[0,1])
        focused=[r for r in result["reference_plane_predictions"] if r["cohort"]=="common_extracted_ids" and r["drift_length_mm"]==20]
        self.assertAlmostEqual(focused[0]["predicted_sigma_t_ns"],0.)
        self.assertAlmostEqual(focused[0]["predicted_central90_width_ns"],0.)
        particles=[r for r in result["reference_particle_predictions"] if r["cohort"]=="common_extracted_ids" and r["drift_length_mm"]==20]
        self.assertEqual(len(particles),3)
        self.assertTrue(all(r["predicted_t_us"]==10. for r in particles))
        self.assertTrue(all(r["predicted_z_mm"]==-20. for r in particles))
        budget=next(r for r in result["time_interval_variance_rows"] if r["cohort"]=="common_extracted_ids")
        self.assertEqual(budget["paired_count"],3)
        self.assertAlmostEqual(budget["closure_residual_ns2"],0.,places=7)

    def test_long_tail_retained_and_constant_speed_has_no_unique_focus(self):
        case=fixture();case["sources"][4]={};case["exits"][4]={};case["particle_weights"][4]=1.
        case["states"]=[]
        for z in (1.,0.):
            for pid,t in enumerate((0.,0.,0.,.1),1):
                case["states"].append(dict(plane_z_mm=z,particle_id=pid,status="alive",x_mm=0.,y_mm=0.,
                    t_us=t+(1-z),vx_mm_us=0.,vy_mm_us=0.,vz_mm_us=-2.,total_energy_eV=float(pid)))
        result=self.prepare(case,common=[1,2,3,4])
        row=next(r for r in result["plane_time_statistics"] if r["cohort"]=="own_extracted_ids" and r["plane_z_mm"]==0)
        self.assertAlmostEqual(row["sigma_t_ns"],25*np.sqrt(3))
        self.assertAlmostEqual(row["central68_width_ns"],52.)
        self.assertAlmostEqual(row["central90_width_ns"],85.)
        self.assertIsNone(row["unconstrained_L_star_mm"])
        self.assertFalse(row["unique_time_waist"])
        self.assertEqual(row["downstream_L_star_mm"],0.)
        self.assertIsNone(row["rho_t_vz"])
        self.assertEqual(row["rho_t_vz_matched_count"],4)
        self.assertEqual(result["metadata"]["energy_fields_available_by_case"][case["label"]],["total_energy_eV"])
        curve=[r for r in result["reference_plane_predictions"] if r["cohort"]=="own_extracted_ids"]
        self.assertTrue(all(abs(r["predicted_central90_width_ns"]-85)<1e-10 for r in curve))

    def test_empty_and_missing_pairs_keep_ids_and_null_predictions(self):
        case=fixture()
        next(r for r in case["states"] if r["particle_id"]==3 and r["plane_z_mm"]==0)["t_us"]=None
        result=self.prepare(case,common=[])
        empty=next(r for r in result["plane_time_statistics"] if r["cohort"]=="common_extracted_ids")
        self.assertIsNone(empty["sigma_t_ns"])
        curve=next(r for r in result["reference_plane_predictions"] if r["cohort"]=="own_extracted_ids")
        self.assertIsNone(curve["predicted_sigma_t_ns"])
        self.assertEqual(curve["paired_forward_count"],2)
        self.assertNotIn("available_ids",curve)
        self.assertNotIn("missing_ids",curve)
        particles=[r for r in result["reference_particle_predictions"] if r["particle_id"]==3]
        self.assertEqual(len(particles),4)
        self.assertTrue(all(r["predicted_t_us"] is None for r in particles))
        interval=next(r for r in result["time_interval_variance_rows"] if r["cohort"]=="own_extracted_ids")
        self.assertEqual(interval["paired_count"],2)
        self.assertEqual(interval["unpaired_available_ids"],[3])
        with self.assertRaises(ValueError):
            self.prepare(lengths=[])
        with self.assertRaises(ValueError):
            self.prepare(lengths=[-1.])
        with self.assertRaisesRegex(ValueError,"unique"):
            self.prepare(lengths=[0.,0.])
        with self.assertRaisesRegex(ValueError,"only drift_lengths_mm"):
            prepare_time_focus_diagnostics([fixture()],[1.,0.],[1],{"drift_lengths_mm":[0.],"hidden_distance":10})

    def test_single_header_time_focus_render(self):
        from matplotlib import pyplot as plt
        result=self.prepare(lengths=[10.,20.])  # Zero need not be declared.
        figure=build_time_focus_figure(result)
        self.assertEqual(len(figure.axes),6)
        self.assertEqual(len(figure.legends),1)
        self.assertIsNone(figure._suptitle)
        self.assertTrue(all(ax.get_legend() is None for ax in figure.axes))
        self.assertEqual(figure.axes[1].lines[0].get_xdata().tolist(),[10.,20.])
        figure.canvas.draw();plt.close(figure)


class WeightedBeamTests(unittest.TestCase):
    @staticmethod
    def case():
        case=fixture();case["particle_weights"]={1:1.,2:2.,3:1.}
        for row in case["states"]:
            index=row["particle_id"]-1
            row.update(x_mm=[0.,2.,4.][index],y_mm=[3.,2.,0.][index],
                t_us=[0.,.001,.004][index]+(1-row["plane_z_mm"])*.01,
                vx_mm_us=np.tan(np.radians([0.,10.,30.][index]))*[1.,2.,4.][index],
                Ex_eV=[1.,4.,2.][index],Ez_eV=[8.,2.,1.][index],
                total_energy_eV=[9.,6.,3.][index],theta_y_deg=[3.,2.,0.][index])
        return case

    def test_hand_computed_weighted_center_origin_rms_true_angle_and_quantiles(self):
        case=self.case()
        focus=prepare_focus_diagnostics([case],[1.,0.],[1,2,3])
        plane=focus["plane_statistics"][0]
        self.assertEqual(plane["mean_x_mm"],2.)
        self.assertAlmostEqual(plane["sigma_x_mm"],np.sqrt(2.))
        self.assertAlmostEqual(plane["rms_x_mm"],np.sqrt(6.))
        self.assertEqual(plane["weight_sum"],4.)
        self.assertAlmostEqual(plane["effective_sample_count"],8/3)
        angle=focus["exit_angle_decomposition"][0]
        self.assertAlmostEqual(angle["sigma_total_deg"]**2,118.75)
        self.assertAlmostEqual(angle["beta_deg_per_mm"],7.5)
        self.assertAlmostEqual(angle["sigma_residual_deg"]**2,6.25)
        self.assertAlmostEqual(angle["sigma_linear_correlated_deg"]**2,112.5)
        self.assertAlmostEqual(angle["epsilon_mm_mrad"],np.sqrt(2)*np.radians(2.5)*1000)
        time=prepare_time_focus_diagnostics([case],[1.,0.],[1,2,3],{"drift_lengths_mm":[0.,1.]})
        row=time["plane_time_statistics"][0]
        self.assertAlmostEqual(row["mean_t_us"],.0015)
        self.assertAlmostEqual(row["sigma_t_ns"]**2,2.25)
        self.assertEqual(row["central68_width_ns"],4.)
        self.assertEqual(row["central90_width_ns"],4.)
        self.assertEqual(row["quantile_method"],"weighted_ecdf_left_inverse_v1")
        # Independent pair products, without calling the public moment kernel.
        weights=np.array([1.,2.,1.])/4
        for field,values in (("x_mm",[0.,2.,4.]),("Ex_eV",[1.,4.,2.]),("total_energy_eV",[9.,6.,3.])):
            a=np.array([0.,.001,.004]);b=np.array(values)
            ac=a-sum(weights*a);bc=b-sum(weights*b)
            expected=sum(weights*ac*bc)/np.sqrt(sum(weights*ac**2)*sum(weights*bc**2))
            self.assertAlmostEqual(row[f"rho_t_{field}"],expected)
        inverse=np.array([1000.,500.,250.]);centered_inverse=inverse-sum(weights*inverse)
        centered_time=np.array([0.,1.,4.])-1.5
        self.assertAlmostEqual(row["variance_a_ns2"],2.25)
        self.assertAlmostEqual(row["variance_b_ns2_per_mm"],2*sum(weights*centered_time*centered_inverse))
        self.assertAlmostEqual(row["variance_c_ns2_per_mm2"],sum(weights*centered_inverse**2))
        interval=time["time_interval_variance_rows"][0]
        self.assertAlmostEqual(interval["mean_delta_t_ns"],10.)
        self.assertAlmostEqual(interval["closure_residual_ns2"],0.)

    def test_weighted_quantiles_choose_left_inverse_at_exact_probability(self):
        case=self.case();case["particle_weights"]={1:1.,2:15.,3:84.}
        for row in case["states"]:
            row["t_us"]=(row["particle_id"]-1)*.01+(1-row["plane_z_mm"])
        result=prepare_time_focus_diagnostics([case],[1.,0.],[1,2,3],{"drift_lengths_mm":[0.]})
        row=result["plane_time_statistics"][0]
        self.assertAlmostEqual(row["central68_width_ns"],10.)
        self.assertAlmostEqual(row["central90_width_ns"],10.)
        self.assertEqual(row["quantile_method"],"weighted_ecdf_left_inverse_v1")

    def test_relative_scale_id_order_and_equal_linear_method(self):
        case=self.case();before=copy.deepcopy(case)
        first=prepare_time_focus_diagnostics([case],[1.,0.],[1,2,3],{"drift_lengths_mm":[0.,1.]})
        case["particle_weights"]={pid:8*w for pid,w in reversed(list(case["particle_weights"].items()))}
        case["states"].reverse()
        scaled=prepare_time_focus_diagnostics([case],[1.,0.],[1,2,3],{"drift_lengths_mm":[0.,1.]})
        for left,right in zip(first["plane_time_statistics"],scaled["plane_time_statistics"],strict=True):
            for key,value in left.items():
                if key.endswith("weight_sum"):
                    self.assertEqual(right[key],8*value)
                else:
                    self.assertEqual(right[key],value)
        equal=copy.deepcopy(before);equal["particle_weights"]={pid:3.5 for pid in equal["sources"]}
        linear=prepare_time_focus_diagnostics([equal],[1.,0.],[1,2,3],{"drift_lengths_mm":[0.]})["plane_time_statistics"][0]
        self.assertEqual(linear["quantile_method"],"numpy_quantile_linear_v1")
        self.assertAlmostEqual(linear["central68_width_ns"],2.72)
        self.assertAlmostEqual(linear["central90_width_ns"],3.6)
        self.assertEqual(linear["weight_sum"],10.5)
        self.assertEqual(linear["effective_sample_count"],3.)

    def test_weight_identity_and_representation_fail_closed(self):
        for weights in (None,{1:1.,2:1.},{1:1.,2:1.,3:1.,99:1.},
                        {1:True,2:1.,3:1.},{1:"1",2:1.,3:1.},
                        {1:0.,2:1.,3:1.},{1:-1.,2:1.,3:1.},
                        {1:float("inf"),2:1.,3:1.},{1:1j,2:1.,3:1.}):
            case=self.case();case["particle_weights"]=weights
            with self.subTest(weights=weights),self.assertRaises(ValueError):
                prepare_focus_diagnostics([case],[1.,0.],[1,2,3])

    def test_complex_supplied_state_is_not_silently_projected_to_real(self):
        case=self.case();case["states"][0]["x_mm"]=np.complex128(1+2j)
        with self.assertRaisesRegex(ValueError,"real supplied states"):
            prepare_focus_diagnostics([case],[1.,0.],[1,2,3])

    def test_missing_observable_uses_matching_original_weights_only(self):
        case=self.case();case["states"][0]["Ex_eV"]=None
        case["states"][2]["status"]="unknown"
        result=prepare_time_focus_diagnostics([case],[1.,0.],[1,2,3],{"drift_lengths_mm":[0.]})
        row=result["plane_time_statistics"][0]
        self.assertEqual(row["available_ids"],[1,2])
        self.assertEqual(row["missing_ids"],[3])
        self.assertEqual(row["weight_sum"],3.)
        self.assertEqual(row["rho_t_Ex_eV_matched_count"],1)
        self.assertEqual(row["rho_t_Ex_eV_weight_sum"],2.)
        self.assertIsNone(row["rho_t_Ex_eV"])
        self.assertFalse(result["sampled_minima"][0]["eligible_for_envelope_comparison"])

    def test_translation_and_transverse_rotation_preserve_centered_physics(self):
        original=self.case()
        before=prepare_focus_diagnostics([original],[1.,0.],[1,2,3])
        moved=copy.deepcopy(original)
        for row in moved["states"]:
            row["x_mm"],row["y_mm"]=row["y_mm"]+10.,-row["x_mm"]+20.
            row["vx_mm_us"],row["vy_mm_us"]=row["vy_mm_us"],-row["vx_mm_us"]
            row["t_us"]+=100.
        after=prepare_focus_diagnostics([moved],[1.,0.],[1,2,3])
        a,b=before["plane_statistics"][0],after["plane_statistics"][0]
        self.assertAlmostEqual(a["sigma_x_mm"],b["sigma_y_mm"])
        self.assertAlmostEqual(a["sigma_y_mm"],b["sigma_x_mm"])
        self.assertAlmostEqual(a["epsilon_x_mm_mrad"],b["epsilon_y_mm_mrad"])
        self.assertNotEqual(a["rms_x_mm"],b["rms_y_mm"])
        self.assertAlmostEqual(a["sigma_t_ns"],b["sigma_t_ns"],places=9)
        for a,b in zip(before["field_free_predictions"],after["field_free_predictions"],strict=True):
            if a["coordinate"]=="time":
                self.assertAlmostEqual(a["L_star_mm"],b["L_star_mm"],places=9)


if __name__=="__main__":
    unittest.main()
