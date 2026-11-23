"""Production static comparison contract; no native solver is invoked."""
import copy
import unittest
import pandas as pd
from msplatform.analysis.field_comparison import compare_same_scene_field_variants, compare_static_field_samples
from msplatform.contracts.rigid_transform import RigidTransform


class StaticFieldComparisonTests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame([dict(point_id='p1', x_mm=1., y_mm=2., z_mm=3.,
            Ex_V_per_m=0., Ey_V_per_m=2., Ez_V_per_m=0., potential_V=0., status='valid')])
        self.meta = dict(source={'manifest':'explicit-source'}, bvp={'electrodes':{'ground':0}},
            frame_id='world', units={'length':'mm','electric_field':'V/m','potential':'V'}, potential_reference='ground')
        self.identity = RigidTransform.identity('world')

    def compare(self, left=None, right=None, lm=None, rm=None, lt=None, rt=None, tol=0.):
        return compare_static_field_samples(self.rows if left is None else left, self.rows if right is None else right,
            reference_metadata=self.meta if lm is None else lm, candidate_metadata=self.meta if rm is None else rm,
            reference_transform=self.identity if lt is None else lt, candidate_transform=self.identity if rt is None else rt,
            coordinate_tolerance_mm=tol)

    def test_f01_identical_is_descriptive_without_threshold(self):
        value=self.compare(); self.assertEqual(value['status'],'DESCRIPTIVE_ONLY')
        self.assertEqual(value['paired_valid_count'],1); self.assertEqual(value['metrics']['field_vector']['rms_difference_V_per_m'],0)

    def test_f02_zero_reference_retains_absolute_error(self):
        changed=self.rows.copy(); changed.loc[0,'Ex_V_per_m']=2.
        value=self.compare(right=changed)['metrics']['field_components']['Ex']
        self.assertEqual(value['difference_rms_V_per_m'],2.); self.assertIsNone(value['relative_to_reference_rms_pct'])

    def test_unequal_near_zero_does_not_claim_zero_normalized_difference(self):
        changed=self.rows.copy(); changed.loc[0,'Ex_V_per_m']=1e-20
        value=self.compare(right=changed)['metrics']['field_components']['Ex']
        self.assertGreater(value['difference_rms_V_per_m'],0.)
        self.assertIsNone(value['relative_to_reference_rms_pct'])
        self.assertIsNone(value['symmetric_scale_pct'])
        equal=self.compare()['metrics']['field_components']['Ex']
        self.assertEqual(equal['symmetric_scale_pct'],0.)
    def test_f03_reports_missing_and_status_without_dropping(self):
        other=self.rows.copy(); other.loc[0,'point_id']='p2'; other.loc[0,'status']='outside'
        value=self.compare(right=other); self.assertEqual(value['coverage_counts']['total_union'],2)
        self.assertEqual(value['coverage_counts']['candidate']['outside'],1); self.assertIsNone(value['metrics'])

    def test_f04_bvp_and_potential_reference_must_match(self):
        meta=copy.deepcopy(self.meta); meta['bvp']['electrodes']['ground']=1
        with self.assertRaisesRegex(ValueError,'BVP differs'): self.compare(rm=meta)
        meta=copy.deepcopy(self.meta); meta['potential_reference']='other'
        with self.assertRaisesRegex(ValueError,'potential reference differs'): self.compare(rm=meta)

    def test_f05_explicit_rigid_transform_changes_position_and_vector(self):
        meta=copy.deepcopy(self.meta); meta['frame_id']='local'
        rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.))
        transform=RigidTransform('local','world',rotation,(4.,1.,0.))
        local=self.rows.copy(); local.loc[0,['x_mm','y_mm','z_mm']]=[1.,3.,3.]
        local.loc[0,['Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']]=[2.,0.,0.]
        value=self.compare(right=local,rm=meta,rt=transform)
        self.assertEqual(value['metrics']['field_vector']['rms_difference_V_per_m'],0.)

    def test_f06_same_id_different_position_rejected(self):
        changed=self.rows.copy(); changed.loc[0,'x_mm']=1.01
        with self.assertRaisesRegex(ValueError,'coordinates differ'):self.compare(right=changed)

    def test_f07_potential_uses_volts_and_requires_reference(self):
        changed=self.rows.copy(); changed.loc[0,'potential_V']=3.
        result=self.compare(right=changed)['metrics']['potential']
        self.assertEqual(result['rms_difference_V'],3.); self.assertIsNone(result['relative_to_reference_rms_pct'])
        meta=copy.deepcopy(self.meta);meta['potential_reference']=None
        with self.assertRaisesRegex(ValueError,'potential reference is required'):self.compare(lm=meta,rm=meta)

    def test_f08_explicit_source_and_unit_required(self):
        meta=copy.deepcopy(self.meta);meta['source']={}
        with self.assertRaisesRegex(ValueError,'source identity'):self.compare(rm=meta)
        meta=copy.deepcopy(self.meta);meta['units']['electric_field']='V/mm'
        with self.assertRaisesRegex(ValueError,'units differ'):self.compare(rm=meta)

    def test_f09_duplicate_and_nonfinite_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'unique'):self.compare(right=pd.concat([self.rows,self.rows]))
        invalid=self.rows.copy();invalid.loc[0,'Ey_V_per_m']=float('nan')
        with self.assertRaises(ValueError):self.compare(right=invalid)

    def test_report_snapshots_nested_provenance(self):
        metadata=copy.deepcopy(self.meta)
        metadata['potential_reference']={'electrode':{'name':'ground'}}
        result=self.compare(lm=metadata,rm=metadata)
        metadata['source']['manifest']='changed'
        metadata['bvp']['electrodes']['ground']=99
        metadata['potential_reference']['electrode']['name']='changed'
        self.assertEqual(result['reference_source']['manifest'],'explicit-source')
        self.assertEqual(result['candidate_source']['manifest'],'explicit-source')
        self.assertEqual(result['bvp']['electrodes']['ground'],0)
        self.assertEqual(result['potential_reference']['electrode']['name'],'ground')

    def test_boolean_coordinate_tolerance_is_rejected(self):
        for tolerance in (True,False):
            with self.subTest(tolerance=tolerance), self.assertRaisesRegex(ValueError,'coordinate tolerance'):
                self.compare(tol=tolerance)
    def test_f10_all_domain_states_remain_visible(self):
        frames=[]
        for i,status in enumerate(('valid','solid','interface','outside','excluded','sample_error')):
            frame=self.rows.copy();frame.loc[0,'point_id']=str(i);frame.loc[0,'status']=status;frames.append(frame)
        samples=pd.concat(frames,ignore_index=True); result=self.compare(left=samples,right=samples)
        self.assertEqual(result['paired_valid_count'],1)
        self.assertEqual(result['coverage_counts']['reference']['sample_error'],1)
        self.assertEqual(result['coverage_counts']['candidate']['interface'],1)


    def test_descriptive_variants_preserve_distinct_bvps_scene_and_coverage(self):
        metadata=copy.deepcopy(self.meta);metadata['bvp']={'domain':'partitioned'}
        excitation={'electrode_voltages_v':{'ground':0.,'rod':3.},'rf_phase':'positive_peak','pulse_state':'off'}
        other=self.rows.copy();other.loc[0,'Ex_V_per_m']=3.;other.loc[0,'potential_V']=4.
        missing=other.copy();missing.loc[0,'point_id']='missing';missing.loc[0,'status']='outside'
        result=compare_same_scene_field_variants(self.rows,pd.concat([other,missing],ignore_index=True),
            reference_metadata=self.meta,candidate_metadata=metadata,reference_transform=self.identity,
            candidate_transform=self.identity,coordinate_tolerance_mm=0.,reference_scene_sha256='a'*64,
            candidate_scene_sha256='A'*64,reference_excitation=excitation,candidate_excitation=excitation)
        self.assertEqual(result['status'],'DESCRIPTIVE_ONLY');self.assertEqual(result['bvp_equivalence'],'NOT_CLAIMED')
        self.assertEqual(result['reference_bvp'],self.meta['bvp']);self.assertEqual(result['candidate_bvp'],metadata['bvp'])
        self.assertEqual(result['metrics']['field_vector']['rms_difference_V_per_m'],3.)
        self.assertEqual(result['metrics']['potential']['rms_difference_V'],4.)
        self.assertEqual(result['coverage_counts']['reference']['missing'],1)
        metadata['bvp']['domain']='mutated';excitation['electrode_voltages_v']['rod']=99.
        self.assertEqual(result['candidate_bvp']['domain'],'partitioned');self.assertEqual(result['excitation']['electrode_voltages_v']['rod'],3.)

    def test_descriptive_static_excitation_needs_no_rf_or_pulse_placeholder(self):
        excitation={'electrode_voltages_v':{'ground':0.,'plate':5.}}
        result=compare_same_scene_field_variants(self.rows,self.rows,
            reference_metadata=self.meta,candidate_metadata=self.meta,reference_transform=self.identity,
            candidate_transform=self.identity,coordinate_tolerance_mm=0.,reference_scene_sha256='a'*64,
            candidate_scene_sha256='a'*64,reference_excitation=excitation,candidate_excitation=copy.deepcopy(excitation))
        self.assertEqual(result['excitation'],excitation)
        self.assertEqual(result['bvp_equivalence'],'NOT_CLAIMED')
    def test_descriptive_variants_reject_mismatch_and_preserve_numerical_guards(self):
        def call(**changes):
            excitation={'electrode_voltages_v':{'ground':0.},'rf_phase':'zero','pulse_state':'off'}
            metadata=copy.deepcopy(self.meta);metadata['bvp']={'domain':'partitioned'}
            args=dict(reference_metadata=self.meta,candidate_metadata=metadata,reference_transform=self.identity,
                candidate_transform=self.identity,coordinate_tolerance_mm=0.,reference_scene_sha256='a'*64,
                candidate_scene_sha256='a'*64,reference_excitation=excitation,candidate_excitation=copy.deepcopy(excitation))
            left=changes.pop('left',self.rows);right=changes.pop('right',self.rows);args.update(changes)
            return compare_same_scene_field_variants(left,right,**args)
        with self.assertRaisesRegex(ValueError,'scene differs'):call(candidate_scene_sha256='b'*64)
        with self.assertRaisesRegex(ValueError,'SHA-256'):call(candidate_scene_sha256='')
        with self.assertRaisesRegex(ValueError,'excitation differs'):call(candidate_excitation={'electrode_voltages_v':{'ground':1.},'rf_phase':'zero','pulse_state':'off'})
        with self.assertRaisesRegex(ValueError,'finite electrode'):call(candidate_excitation={'electrode_voltages_v':{'ground':float('nan')},'rf_phase':'zero','pulse_state':'off'})
        meta=copy.deepcopy(self.meta);meta['potential_reference']='other'
        with self.assertRaisesRegex(ValueError,'potential reference differs'):call(candidate_metadata=meta)
        meta=copy.deepcopy(self.meta);meta['units']['electric_field']='V/mm'
        with self.assertRaisesRegex(ValueError,'units differ'):call(candidate_metadata=meta)
        bad=self.rows.copy();bad.loc[0,'x_mm']=2.
        with self.assertRaisesRegex(ValueError,'coordinates differ'):call(right=bad)
        bad=self.rows.copy();bad.loc[0,'Ex_V_per_m']=float('nan')
        with self.assertRaises(ValueError):call(right=bad)
        bad=self.rows.copy();bad.loc[0,'status']='not_known'
        with self.assertRaisesRegex(ValueError,'unknown sample status'):call(right=bad)



if __name__=='__main__':unittest.main()
