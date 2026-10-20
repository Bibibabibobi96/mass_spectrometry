"""Independent analytic regression, drift, membership and headless checks."""
from __future__ import annotations

import copy
import unittest

import numpy as np

from projects.dual_pressure_rectilinear_ion_processor.analysis.beam_focus_diagnostics import (
    prepare_focus_diagnostics, build_focus_figure, prepare_time_focus_diagnostics, build_time_focus_figure,
)


def fixture() -> dict:
    states=[]
    # At reference z=0: x=-L*u with L=10, and t=10-20/abs(vz).
    for z in (1.,0.):
        for pid,u,speed in ((1,-.1,1.),(2,0.,2.),(3,.1,4.)):
            states.append(dict(plane_z_mm=z,particle_id=pid,status="alive",x_mm=-10*u-z*u,
                y_mm=float(pid),t_us=10-20/speed-z/speed,vx_mm_us=u*speed,vy_mm_us=0.,vz_mm_us=-speed))
    return dict(label="Analytic",sources={i:{} for i in (1,2,3)},exits={i:{} for i in (1,2,3)},states=states)


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
        case=fixture();case["sources"][4]={};case["exits"][4]={}
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


if __name__=="__main__":
    unittest.main()
