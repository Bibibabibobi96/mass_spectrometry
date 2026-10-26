"""Pure actual-occupancy selection; synthetic states are not flight evidence."""
from __future__ import annotations

import copy
import math
from pathlib import Path
import subprocess
import sys
import unittest

from integrations.tests.test_single_reflection_geometry import candidate_300mm_fixture
from integrations.workflows.single_reflection_flight.pulse import ROLE, select_discovery_pulse
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import resolve_accelerator_geometry


class ActualDiscoveryPulseTests(unittest.TestCase):
    def setUp(self):
        projection = resolve_accelerator_geometry(candidate_300mm_fixture(), variant_id="three_zone_square")
        self.geometry = dict(accelerator_projection=projection.local_region,
                             composition_plan=dict(assembly_frame_id="oatof_global"))
        self.records = {name: dict(path=name+".json", bytes=10, sha256="A"*64)
                        for name in ("collection", "request", "frontend_geometry")}

    def snapshot(self, pid, time, *, x=0., y=0., z=0.):
        g = self.geometry["accelerator_projection"]
        return dict(particle_id=pid, candidate_time_us=time, instrument_time_us=time,
                    x_mm=g["axis_x_mm"]+x, y_mm=g["axis_y_mm"]+y,
                    z_mm=(g["repeller_front_z_mm"]+g["grid1_z_mm"])/2+z,
                    vx_mm_per_us=.1, vy_mm_per_us=.02, vz_mm_per_us=.03)

    def arguments(self, *, ids=(1, 7, 41), times=None):
        times = [-1., 0., 1., 2.] if times is None else times
        return dict(births_us={pid:-2. for pid in ids},
                    terminal_times_us={pid:3. for pid in ids}, snapshots=[],
                    candidate_times_us=times, frontend_geometry=self.geometry,
                    pulse_width_us=.5, input_records=self.records)

    def test_actual_selector_runs_without_importing_the_instrument_layout_compiler(self):
        code = """
import sys
class NoLayout:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'integrations.runtime.single_flight_layout':
            raise ImportError('unrelated instrument layout compiler entered pulse selection')
sys.meta_path.insert(0, NoLayout())
from integrations.workflows.single_reflection_flight.pulse import select_discovery_pulse
record = dict(path='fixture.json', bytes=1, sha256='A'*64)
row = dict(particle_id=1, candidate_time_us=1., instrument_time_us=1.,
           x_mm=0., y_mm=0., z_mm=1., vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0.)
decision = select_discovery_pulse(births_us={1:0.}, terminal_times_us={1:2.},
    snapshots=[row], candidate_times_us=[1.], pulse_width_us=.5,
    frontend_geometry=dict(composition_plan=dict(assembly_frame_id='oatof_global'),
        accelerator_projection=dict(bore_width_mm=2., axis_x_mm=0., axis_y_mm=0.,
                                     repeller_front_z_mm=0., grid1_z_mm=2.)),
    input_records={name:record for name in ('collection','request','frontend_geometry')})
assert decision['actual_pulse_time_us'] == 1.
assert 'integrations.runtime.single_flight_layout' not in sys.modules
"""
        result = subprocess.run([sys.executable,'-B','-c',code],
            cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_shared_order_counts_then_spread_then_center_then_earlier(self):
        args = self.arguments()
        for time, spread, center in ((-1.,10.,0.),(0.,1.,5.),(1.,1.,0.),(2.,1.,0.)):
            args["snapshots"] += [self.snapshot(1,time,x=center-spread),
                                  self.snapshot(7,time,x=center+spread),
                                  self.snapshot(41,time,x=200.)]
        original = copy.deepcopy(args)
        decision = select_discovery_pulse(**args)
        self.assertEqual(decision["role"],ROLE)
        self.assertEqual(decision["schema_version"],2)
        self.assertEqual(decision["status"],"success")
        self.assertEqual(decision["actual_pulse_time_us"],1.)
        self.assertEqual(decision["selection"]["selected"]["eligible_ids"],[1,7])
        self.assertEqual(decision["input_records"],self.records)
        self.assertFalse(decision["selection_uses_future_terminal_outcome"])
        self.assertEqual(args,original)
        args["snapshots"][-1] = self.snapshot(41,2.)
        self.assertEqual(select_discovery_pulse(**args)["actual_pulse_time_us"],2.)

    def test_n100_missing_actual_snapshot_makes_candidate_unrankable(self):
        args = self.arguments(ids=tuple(range(1,101)),times=[0.])
        args["snapshots"] = [self.snapshot(pid,0.) for pid in range(1,100)]
        decision = select_discovery_pulse(**args)
        self.assertEqual(decision["status"],"no_supported_candidate")
        self.assertNotIn("actual_pulse_time_us",decision)
        selection = decision["selection"]
        self.assertEqual(selection["execution_cohort_count"],100)
        self.assertEqual(selection["candidates"][0]["unsupported_ids"],[100])
        self.assertFalse(selection["candidates"][0]["rankable"])
        counts = selection["candidate_status_counts"][0]
        self.assertEqual((counts["active"],counts["numerical_unsupported"]),(99,1))

    def test_birth_and_terminal_boundary_use_actual_lifetimes_without_future_causes(self):
        args = self.arguments(times=[-1.,0.,1.])
        args["births_us"] = {1:0.,7:-2.,41:2.}
        args["terminal_times_us"] = {1:2.,7:0.,41:3.}
        args["snapshots"] = [self.snapshot(7,-1.),self.snapshot(1,0.),self.snapshot(7,0.),
                             self.snapshot(1,1.)]
        decision = select_discovery_pulse(**args)
        counts = decision["selection"]["candidate_status_counts"]
        self.assertEqual(counts[0]["not_born"],2)
        self.assertEqual(counts[1]["already_terminal"],1)
        self.assertEqual(decision["selection"]["candidates"][1]["eligible_ids"],[1])
        # Moving endpoints beyond all candidate observations has no ranking effect.
        args = self.arguments(times=[0.])
        args["snapshots"] = [self.snapshot(pid,0.) for pid in args["births_us"]]
        first = select_discovery_pulse(**args)
        args["terminal_times_us"] = {pid:1000. for pid in args["births_us"]}
        for row in args["snapshots"]:
            row["detector_outcome"] = "irrelevant_extra_metadata"
        self.assertEqual(first,select_discovery_pulse(**args))

    def test_actual_clock_is_preserved_within_binary64_serialization_allowance(self):
        args = self.arguments(ids=(5,),times=[1.])
        row = self.snapshot(5,1.)
        row["instrument_time_us"] += 16*math.ulp(1.)
        args["snapshots"] = [row]
        actual = row["instrument_time_us"]
        decision = select_discovery_pulse(**args)
        self.assertEqual(row["instrument_time_us"],actual)
        self.assertEqual(decision["actual_pulse_time_us"],1.)
        row["instrument_time_us"] = 1.+100*math.ulp(1.)
        with self.assertRaisesRegex(ValueError,"interpolation"):
            select_discovery_pulse(**args)

    def test_capture_is_open_actual_first_gap_not_sideport_or_detector(self):
        args = self.arguments(ids=(1,7),times=[0.])
        a,b = self.snapshot(1,0.),self.snapshot(7,0.)
        a["z_mm"] = self.geometry["accelerator_projection"]["grid1_z_mm"]
        b["x_mm"] += self.geometry["accelerator_projection"]["bore_width_mm"]/2
        args["snapshots"] = [a,b]
        decision = select_discovery_pulse(**args)
        self.assertEqual(decision["status"],"no_supported_candidate")
        self.assertEqual(decision["selection"]["candidates"][0]["pulse_eligible_count"],0)
        self.assertEqual(decision["selection"]["candidates"][0]["unsupported_ids"],[])

    def test_invalid_mother_snapshot_authority_and_candidate_plan_fail_closed(self):
        base = self.arguments(ids=(1,),times=[0.])
        base["snapshots"] = [self.snapshot(1,0.)]
        for defect in ("missing_terminal","extra_terminal","bad_lifetime","duplicate","unknown_id",
                       "unknown_time","nonfinite_state","nonfinite_time","duplicate_times",
                       "unordered_times","bad_width","missing_record","extra_record"):
            args = copy.deepcopy(base)
            if defect == "missing_terminal": args["terminal_times_us"] = {}
            elif defect == "extra_terminal": args["terminal_times_us"][2] = 4.
            elif defect == "bad_lifetime": args["terminal_times_us"][1] = -3.
            elif defect == "duplicate": args["snapshots"] *= 2
            elif defect == "unknown_id": args["snapshots"][0]["particle_id"] = 8
            elif defect == "unknown_time": args["snapshots"][0]["candidate_time_us"] = 2.
            elif defect == "nonfinite_state": args["snapshots"][0]["vx_mm_per_us"] = float("nan")
            elif defect == "nonfinite_time": args["candidate_times_us"] = [float("inf")]
            elif defect == "duplicate_times": args["candidate_times_us"] = [0.,0.]
            elif defect == "unordered_times": args["candidate_times_us"] = [1.,0.]
            elif defect == "bad_width": args["pulse_width_us"] = 0.
            elif defect == "missing_record": del args["input_records"]["collection"]
            else: args["input_records"]["detector"] = {}
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                select_discovery_pulse(**args)


if __name__ == "__main__":
    unittest.main()
