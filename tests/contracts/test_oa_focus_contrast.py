"""OA contrast compares only identical original SI cohorts and explicit modes."""
import copy
import unittest
from msplatform.analysis.oa_focus_contrast import compare_focus_field_cases


class OaFocusContrastTests(unittest.TestCase):
    def fixture(self):
        cases={}
        for mode,width in (('native',3.),('zone1_ideal',2.),('zone2_ideal',1.),('full_ideal',.5)):
            cases[mode]=dict(field_mode=mode,source_identity={'packet_sha256':'A'*64},
                initial_states=[{'particle_id':1,'position_m':[0.,0.,.02]},{'particle_id':2,'position_m':[0.,0.,.021]}],
                metadata={'frame_id':'oa','clock':{'clock_epoch_id':'one','authority_sha256':'B'*64}},
                analysis={'role':'oa_focus_si_analysis','status':'analyzed',
                    'measurements':{'particle_count':2,'peak_to_peak_arrival_s':width*1e-9},
                    'energy_assessment':{'passed':False}})
        return cases

    def test_original_four_arm_math_and_empty_result_remain_distinct(self):
        cases=self.fixture();result=compare_focus_field_cases(cases)
        self.assertAlmostEqual(result['native_reduction_toward_ideal_ns']['zone2_ideal'],2.)
        self.assertEqual(result['dominant_finite_field_region'],'zone2_finite_field')
        self.assertFalse(result['exit_energy_assessment']['native']['passed'])
        cases['full_ideal']['analysis']['measurements']['peak_to_peak_arrival_s']=None
        incomplete=compare_focus_field_cases(cases)
        self.assertEqual(incomplete['status'],'incomplete');self.assertIsNone(incomplete['dominant_finite_field_region'])
        self.assertIsNone(incomplete['native_reduction_toward_ideal_ns']['full_ideal'])

    def test_rejects_different_birth_clock_or_selector(self):
        cases=self.fixture();cases['zone1_ideal']['initial_states'][0]['position_m'][0]=1e-6
        with self.assertRaisesRegex(ValueError,'cohort and clock'):compare_focus_field_cases(cases)
        cases=self.fixture();cases['zone2_ideal']['metadata']['clock']['clock_epoch_id']='other'
        with self.assertRaisesRegex(ValueError,'cohort and clock'):compare_focus_field_cases(cases)
        cases=self.fixture();cases['full_ideal']['field_mode']='zone2_ideal'
        with self.assertRaisesRegex(ValueError,'mode identity'):compare_focus_field_cases(cases)
        cases=self.fixture();del cases['native']
        with self.assertRaisesRegex(ValueError,'four OA field modes'):compare_focus_field_cases(cases)
        self.assertNotEqual(copy.deepcopy(cases),self.fixture())
