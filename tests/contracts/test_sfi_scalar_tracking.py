"""SFI common-scalar tracking integration; no native solver execution."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.contracts import test_sfi_scalar_binding as fixture
from msplatform.backends.simion import tracking_execution, tracking_program, tracking_units


class SfiScalarTrackingTests(unittest.TestCase):
    def setUp(self):
        self.basis_case = fixture.SfiScalarAdmissionTests(methodName='runTest')
        self.basis_case.setUp()
        self.addCleanup(self.basis_case.doCleanups)

    def test_real_admission_and_changed_source_refusal(self):
        c = self.basis_case
        design = c.root/'selected_field_design.json'
        design.write_text(json.dumps(c.design), encoding='utf-8')
        source = SimpleNamespace(data_path=lambda name: design)
        selection = dict(geometry_artifact=c.geometry_ref, samples=c.sample_refs)
        plan = dict(propagation={'scope':'continuous_assembly'}, rows=[1], flight=c.flight)
        actual = tracking_execution._resolve_scalar_basis(source, c.model, plan, selection)
        self.assertEqual(actual, c.resolve())
        bad = copy.deepcopy(selection)
        bad['samples']['carrier']['manifest']['sha256'] = '0'*64
        with self.assertRaises(AssertionError):
            tracking_execution._resolve_scalar_basis(source, c.model, plan, bad)
        with self.assertRaisesRegex(ValueError, 'nonempty continuous'):
            tracking_execution._resolve_scalar_basis(source, c.model, dict(plan, rows=[]), selection)

    def test_scalar_identity_changes_recovery_and_resources(self):
        basis = self.basis_case.resolve()
        plan = dict(source_realization={},field_manifest_identity={},model_identity_sha256='a',rows=[],
                    native_source_rows=[],source_provenance={'clock_records':{'clock_authority':{},'instrument_epoch':{}}},
                    absolute_deadlines_us_by_particle_id={},flight={},propagation={},observations={},numerics={},units=[],
                    scalar_field_basis=basis)
        with patch('msplatform.backends.simion.resources.native_resource_path',
                   side_effect=lambda name: Path(tracking_program.__file__).parent/'resources'/name):
            first = tracking_units.tracking_applicability(plan)
            changed = copy.deepcopy(plan)
            changed['scalar_field_basis']['bases']['carrier']['records']['field_v']['sha256'] = '0'*64
            self.assertNotEqual(first, tracking_units.tracking_applicability(changed))

    def test_scalar_observation_preserves_legacy_validation_boundary(self):
        from msplatform.backends.simion.tracking_field_observation import _validate_field_observation_row
        spec = dict(domain_id='detector', buckets=[dict(bucket_id='b',time_min_us=0,time_max_us=2)],deadline_us=2)
        sources = {name:{'field_v':{'path':'C:/fixture/'+name+'.pa'}}
                   for name in ('carrier','rf_reference','pulse_delta')}
        context = dict(observation_basis='native_entry_gradient_no_extra_query',
            static_carrier_record={'path':'C:/fixture/detector.pa'},eligible_batch_particle_ids=[7],
            instance_index=4,world_frame_id='world',scalar_sources=sources)
        row = dict(schema_version=1,role='single_reflection_applied_field_query',basis='common_scalar_query_v1',
            record_seq=1,callback_seq=1,bucket_id='b',instrument_time_us=1.,solver_elapsed_us=1.,particle_id=7,
            ion_number=1,instance_index=4,domain_id='detector',world_frame_id='world',world_position_mm=[0,0,0],
            grid_spacing_mm=[1,1,1],instance_scale=1,instance_rotation_deg=[0,0,0],entry_gradient_gu=[0,0,0],
            pulse_active_used=False,pulse_basis='not_applied_not_queried',after_dynamic_gradient_gu=[0,0,0],
            region_override={'replace_all':False},after_region_gradient_gu=[0,0,0],final_gradient_gu=[1,2,3],
            actual_rf_phase_rad=0.,rf_phase_basis='unwrapped_kernel_phase_at',carrier_native_path='C:/fixture/detector.pa',
            scalar_sources={name:record['field_v']['path'] for name,record in sources.items()},
            scalar_rf_coefficient=0.,scalar_pulse_coefficient=0,legacy_fields_intermediate_only=True)
        _validate_field_observation_row(row,spec,context,{'record_seq':0,'callback_seq':0},{'b':0})
        bad = copy.deepcopy(row)
        bad['scalar_sources']['carrier'] = 'C:/other.pa'
        with self.assertRaisesRegex(ValueError,'scalar observation'):
            _validate_field_observation_row(bad,spec,context,{'record_seq':0,'callback_seq':0},{'b':0})
        legacy_context = dict(context)
        legacy_context.pop('scalar_sources')
        legacy = {key:value for key,value in row.items() if key not in
                  {'scalar_sources','scalar_rf_coefficient','scalar_pulse_coefficient','legacy_fields_intermediate_only'}}
        legacy['basis'] = 'native_entry_gradient_no_extra_query'
        with self.assertRaisesRegex(ValueError,'final capture'):
            _validate_field_observation_row(legacy,spec,legacy_context,{'record_seq':0,'callback_seq':0},{'b':0})

    def test_split_rf_rejects_historical_scalar_basis_before_owner(self):
        from tests.contracts import test_simion_tracking_execution as tracking_fixture
        from msplatform.backends.simion import operations
        case = tracking_fixture.TrackingExecutionPlanTests(methodName='runTest');case.setUp()
        self.addCleanup(case.doCleanups)
        public_root=self.basis_case.root/'public';public_root.mkdir()
        source, session_type, _ = tracking_fixture.tracking_action_fixture(case,public_root)
        selection=dict(geometry_artifact=self.basis_case.geometry_ref,samples=self.basis_case.sample_refs)
        with patch('msplatform.execution.owner.run_managed_stage') as owner:
            with self.assertRaisesRegex(ValueError,'only OA and TOF without RF'):
                operations.track(source,case.packet,propagation=case.policy,observations=case.observations,
                    numerics=case.numerics,context=session_type().context,scalar_field_basis=selection)
            owner.assert_not_called()

    def test_split_rf_rejects_derived_historical_basis_before_owner(self):
        from tests.contracts import test_simion_tracking_execution as tracking_fixture
        from msplatform.backends.simion import operations
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        from msplatform.results.artifacts import open_artifact
        raw_ref=self.basis_case.sample_refs['carrier']
        raw=open_artifact(raw_ref,expected_kind='scalar_field_samples')
        root=self.basis_case.root/'derived';root.mkdir()
        borrowed={key:dict(value) for key,value in raw.data_records.items() if key not in ('field_v','field_valid')}
        borrowed['sampled_field_v']=dict(raw.data_records['field_v'])
        borrowed['sampled_field_valid']=dict(raw.data_records['field_valid'])
        data=dict(borrowed);outputs=[]
        for key in ('field_v','field_valid'):
            path=root/(key+'.pa');path.write_bytes(raw.data_path(key).read_bytes());data[key]=file_record(path);outputs.append(data[key])
        metadata=dict(raw.metadata,derivation='offline_from_published_raw_samples',original_samples_reference=raw.reference)
        manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='derived',project='instrument_assembly',mode='test_only',status='success',
            inputs=borrowed,outputs=outputs,products={'product':dict(schema_version=1,kind='scalar_field_samples',status='complete',metadata=metadata,data=data)})
        publish_terminal_state(root,{'status':'success'},manifest)
        derived={'manifest':file_record(root/'run_manifest.json'),'product_id':'product'}
        samples=dict(self.basis_case.sample_refs,carrier=derived)
        case=tracking_fixture.TrackingExecutionPlanTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        public_root=self.basis_case.root/'lease_public';public_root.mkdir()
        source,session_type,_=tracking_fixture.tracking_action_fixture(case,public_root);session=session_type()
        # The current split RF chain explicitly rejects the historical three-basis
        # SFI selection before owner; its raw and derived records remain readable.
        selected_derived=open_artifact(derived,expected_kind='scalar_field_samples')
        self.assertEqual(selected_derived.metadata['original_samples_reference'],raw.reference)
        with patch('msplatform.execution.owner.run_managed_stage') as owner:
            with self.assertRaisesRegex(ValueError,'only OA and TOF without RF'):
                operations.track(source,case.packet,propagation=case.policy,observations=case.observations,
                    numerics=case.numerics,context=session.context,
                    scalar_field_basis=dict(geometry_artifact=self.basis_case.geometry_ref,samples=samples))
            owner.assert_not_called()
