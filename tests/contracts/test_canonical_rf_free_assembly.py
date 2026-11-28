"""Canonical complete two-RF Assembly pure software evidence."""
import copy,unittest
from msplatform import assembly
from msplatform.backends.simion.operations import compile_geometry
from msplatform.backends.comsol.assembly_geometry import _world_bounds
from tests.contracts.test_support.canonical_rf_fixture import make_assembly,compile_case

class CanonicalFreeAssemblyTests(unittest.TestCase):
    def test_complete_connection_and_renamed_order(self):
        obj,members=make_assembly();self.assertEqual(len(members),64)
        check=obj.composition_plan['connection_checks'][0]
        self.assertEqual(check['upstream_center_mm'],[0.,0.,79.6]);self.assertEqual(check['downstream_center_mm'],[0.,0.,80.6]);self.assertEqual(check['gap_mm'],1.0)
        self.assertEqual(check['upstream_outward_normal'],[0.,0.,1.]);self.assertEqual(check['downstream_outward_normal'],[0.,0.,-1.])
        bounds=[_world_bounds(m) for m in members]
        self.assertTrue(all(-15<lo[0] and hi[0]<15 and -15<lo[1] and hi[1]<15 and -5<lo[2] and hi[2]<170 for lo,hi in bounds))
        first,nums=compile_case(obj,members);self.assertEqual(len(first.frontend_geometry['members']),64);self.assertEqual(len(first.frontend_geometry['electrode_mapping']),16)
        renamed,other=make_assembly(('alpha','beta'),True);second,_=compile_case(renamed,other)
        def keyed(rows,swap):
            return sorted((swap.get(x['instance_id'],x['instance_id']),x['electrode_group_id'],x['member_id'],repr(x['shape']),repr(x['transform']['translation_mm'])) for x in rows)
        self.assertEqual(keyed(members,{}),keyed(other,{'alpha':'first','beta':'second'}))
        self.assertEqual(first.frontend_gems,second.frontend_gems)
        self.assertNotEqual(obj.components_source['first'],obj.components_source['second'])
        self.assertEqual({m['shape']['radius_mm'] for m in members if m['instance_id']=='first'},{2.0})
        self.assertEqual({m['shape']['radius_mm'] for m in members if m['instance_id']=='second'},{1.8})
        with self.assertRaisesRegex(ValueError,'witness'):
            bad=copy.deepcopy(nums);bad['metal_witnesses'][0]['gu']=[0,0,0];compile_geometry(obj,numerics=bad)
        with self.assertRaises(ValueError):
            bad=copy.deepcopy(nums);bad['boundary']='unsupported';compile_geometry(obj,numerics=bad)

    def test_missing_port_and_true_overlap_refused(self):
        obj,_=make_assembly();recipe=copy.deepcopy(obj.composition_plan['recipe']);recipe['connections'][0]['upstream']['port_id']='missing'
        with self.assertRaisesRegex(ValueError,'port'):
            assembly.assemble(recipe,obj.components)
        recipe=copy.deepcopy(obj.composition_plan['recipe']);recipe['connections']=[];recipe['instances'][1]['transform']['translation_mm']=[0,0,0]
        overlap=assembly.assemble(recipe,obj.components)
        from msplatform.components.geometry_members import assembly_geometry_members
        snap=dict(composition_plan=overlap.composition_plan,components_resolved=overlap.components_resolved,components_source=overlap.components_source)
        self.assertEqual(len(list(assembly_geometry_members(snap))),64)
        _,nums=compile_case(*make_assembly())
        import importlib.util
        if importlib.util.find_spec('cadquery') is None:
            with self.assertRaisesRegex(RuntimeError,'optional cad-step'):
                compile_geometry(overlap,numerics=nums)
        else:
            with self.assertRaisesRegex(ValueError,'independent conductor solids overlap'):
                compile_geometry(overlap,numerics=nums)

    def test_canonical_drive_model_coverage(self):
        from msplatform.components.rf_multipole.drive import scientific_multipole_drive
        from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
        obj,members=make_assembly();compiled,_=compile_case(obj,members)
        groups={name:scientific_multipole_drive(resolved) for name,resolved in obj.components_resolved.items()}
        drive=dict(clock=dict(clock_epoch_id='instrument_clock_epoch_v1',authority_sha256='6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0',phase_reference_instrument_time_us=0.0),groups=groups)
        model=compile_prepared_model(compiled,obj.components_resolved,drive=drive,physics=RF_PHYSICS)
        self.assertEqual(model.document['drive']['groups'],groups)
        self.assertEqual({v['rf_amplitude_v'] for v in groups['first'].values()},{139.81792})
        self.assertEqual({v['rf_amplitude_v'] for v in groups['second'].values()},{100.0})
        bad=copy.deepcopy(drive);bad['groups']['first'].pop(next(iter(bad['groups']['first'])))
        with self.assertRaises(ValueError):compile_prepared_model(compiled,obj.components_resolved,drive=bad,physics=RF_PHYSICS)

    def test_public_inert_owner_chain_and_field_coverage(self):
        import json,os
        from pathlib import Path
        from unittest.mock import patch
        from tests.contracts.test_support.canonical_rf_fixture import sample_fixture
        from tests.contracts.test_support.generic_scalar_owner_harness import make_inert
        from tests.contracts.test_support.sfi_scalar_owner_fixture import make_context, retained_owner_directory
        from tests.contracts.test_simion_rf_tracking import rf_tracking_case
        from msplatform.components.rf_multipole.drive import scientific_multipole_drive
        from msplatform.backends.simion import operations
        from msplatform.backends.simion.model import RF_PHYSICS
        from msplatform.execution.run_session import RunSession
        obj,members=make_assembly();compiled,_=compile_case(obj,members)
        groups={name:scientific_multipole_drive(row) for name,row in obj.components_resolved.items()}
        private={'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
        with retained_owner_directory() as directory, patch.dict(os.environ,private):
            context,budget,retention=make_context(Path(directory))
            from msplatform.storage import ArtifactStore
            store = ArtifactStore(Path(directory)/'store')
            policy=json.loads(context.stage_policy_path.read_text(encoding='utf8'))
            for name in ('build_geometry','prepare_model','solve_fields'):policy['stages'][name]=copy.deepcopy(policy['stages']['track'])
            policy['stages']['solve_fields']['limits']['reserved_run_payload_bytes']=16777216
            context.stage_policy_path.write_text(json.dumps(policy),encoding='utf8')
            scalar_geometry,samples=sample_fixture(context,budget,retention,obj,members,groups)
            drive=dict(groups=groups,clock=dict(phase_reference_instrument_time_us=0.),clock_authority=dict(example_resource='instrument_clock_authority_v1.json'))
            operator=dict(relative_permittivity=1.0,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})
            calls=[];field_guards=[];tracking_guards=[];original=RunSession.run_process
            inert=make_inert(self,compiled,original,calls,field_guards,tracking_guards,[False],[],[],directory,context)
            with patch.object(RunSession,'run_process',new=inert):
                geometry=operations.build_geometry(compiled,context=context,artifact_store=store)
                model=operations.prepare_model(geometry,drive=drive,physics=RF_PHYSICS,context=context,artifact_store=store)
                field=operations.solve_fields(model,numerics={},context=context,artifact_store=store,scalar_field_basis=dict(geometry_artifact=scalar_geometry,operator=operator,samples=samples))
                self.assertEqual(field.metadata['field_representation'],'neutral_sampled_basis_with_collision_geometry')
                _,_,packet,_,propagation,numerics=rf_tracking_case()
                clock=model.data_path('compiled_model');document=json.loads(clock.read_text(encoding='utf8'))
                packet['clock']={k:document['drive']['clock'][k] for k in ('clock_epoch_id','authority_sha256')}
                for index,row in enumerate(packet['rows']):
                    name=('first','second')[index]
                    for record in (row,packet['mother']['records'][row['particle_id']]):
                        record.update(source_component_id=name,target_component_id=name,frame_id='multipole.cartesian.z_axis.v1',clock_epoch_id=packet['clock']['clock_epoch_id'],position_x_mm=0.,position_y_mm=0.,position_z_mm=10.)
                trajectory=operations.track(field,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context,artifact_store=store)
                self.assertEqual(trajectory.metadata['mother_count'],2)
                collection=json.loads(trajectory.data_path('collection').read_text(encoding='utf8'))
                self.assertEqual([x['particle_id'] for x in collection['native_terminals']],[7,91])
                self.assertEqual(collection['original_mother']['mother_records'],list(packet['mother']['records'].values()))
                bad=copy.deepcopy(packet);bad['rows'][0]['position_x_mm']=1000.;bad['mother']['records'][7]['position_x_mm']=1000.
                with self.assertRaisesRegex(ValueError,'(?i)(coverage|domain|outside)'):
                    operations.track(field,bad,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context,artifact_store=store)
            self.assertEqual(calls[:5],['geometry_world','build_geometry','verify_geometry','build_model','verify_model'])
