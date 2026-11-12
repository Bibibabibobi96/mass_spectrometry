"""Retained SFI checkpoint statistics independent of withdrawn local frontend."""
import unittest
import pandas as pd
from msplatform.workflows.single_reflection_flight.checkpoint_diagnostics import _checkpoint_distribution_summary


class SingleReflectionCheckpointTests(unittest.TestCase):
    def test_recorded_checkpoint_keeps_mother_coordinates_and_axis(self):
        rows=pd.DataFrame([dict(x_mm=2.,y_mm=4.,z_mm=6.,vx_mm_per_us=1.,vy_mm_per_us=2.,vz_mm_per_us=3.),
                           dict(x_mm=4.,y_mm=8.,z_mm=10.,vx_mm_per_us=1.,vy_mm_per_us=2.,vz_mm_per_us=3.)])
        result=_checkpoint_distribution_summary(rows,'pre_pulse_state',frame_id='oatof_global_cartesian',propagation_axis='x')
        self.assertEqual(result['particle_count'],2)
        self.assertEqual(result['local_propagation_axis'],'x')
        self.assertEqual(result['space_mm']['x']['mean'],3.)
        self.assertEqual(result['space_mm']['y']['mean'],6.)
        self.assertEqual(result['space_mm']['z']['mean'],8.)


if __name__=='__main__':unittest.main()
