"""Focus analysis of a sealed software-only Store source; no vendor execution."""
import copy
import json
import math
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

import numpy as np

from msplatform.backends.simion.tracking_execution import _birth_states
from msplatform.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from msplatform.particle_release.authoring import sample_release
from msplatform.recipes import load_recipe
from msplatform.results.detector_observation import detector_observation
from msplatform.results.model import TraceResult
from msplatform.results.particle_data import write_particle_data
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.oa_focus_store_analysis import guard_focus_analysis, guard_focus_original_birth, initialize_focus_adjustment, advance_focus_adjustment, publish_focus_adjustment_step, recover_focus_adjustment_publication, publish_focus_analysis, recover_focus_analysis_publication, run_focus_recipe
from tests.contracts.test_support.oa_focus_study import make_focus_recipe


def source(store, root, *, alter_birth=False, alter_packet=False, all_hits=False, campaign_override=None, status='succeeded'):
    author, _, projection = make_focus_recipe(root)
    if campaign_override is not None:
        import hashlib
        import re
        from msplatform.workflows.oa_focus_model_projection import project_focus_model
        campaign_path=root/'focus_campaign.json';payload=(json.dumps(campaign_override,indent=2)+'\n').encode()
        campaign_path.write_bytes(payload)
        prior=projection['observations']
        projection=project_focus_model(campaign_path,geometry_profile=prior['geometry_profile'],
            mesh_mm_per_gu=prior['mesh_mm_per_gu'],clock=prior['clock'])
        study_path=root/'study.json';study=json.loads(study_path.read_bytes())
        study['model_input_sources']['oa_focus_campaign']['sha256']=hashlib.sha256(payload).hexdigest()
        study['drive']['groups']=projection['drive']['groups']
        study_bytes=(json.dumps(study,indent=2)+'\n').encode();study_path.write_bytes(study_bytes)
        author.write_text(re.sub(r'(\[study\]\npath = "study.json"\nsha256 = ")[^"]+',
            lambda match:match.group(1)+hashlib.sha256(study_bytes).hexdigest(),author.read_text(encoding='utf8')),encoding='utf8')
    recipe=load_recipe(author).to_dict()
    packet=sample_release(recipe['study']['document']['release']).to_dict()
    model=projection['model'].document
    geometry=dict(model['geometry']['frontend_geometry'],native_frame_id=model['native_frame_id'])
    rows,_,_=_birth_states(packet,geometry)
    authority=projection['observations']
    campaign=json.loads((root/'focus_campaign.json').read_bytes())
    run,work=store.begin_run()
    with store.run_writer(run):
        store.mark_running(run)
        documents={'resolved.json':recipe,'oa_focus_model.json':model,'oa_focus_authority.json':authority,
                   'oa_focus_source_packet.json':packet,'oa_focus_projected_birth_rows.json':copy.deepcopy(rows)}
        if alter_birth:documents['oa_focus_projected_birth_rows.json'][0]['position_y_mm']+=1.
        if alter_packet:documents['oa_focus_source_packet.json']['rows'][0]['species_id']='other'
        for name,document in documents.items():(work/name).write_text(json.dumps(document),encoding='utf8')
        (work/'oa_focus_campaign.json').write_bytes((root/'focus_campaign.json').read_bytes())
        contract=Path(__import__('msplatform.components.orthogonal_accelerator',fromlist=['']).__file__).parent/'component_contract.json'
        (work/'oa_focus_component_contract.json').write_bytes(contract.read_bytes())
        initial=[];terminal=[];events=[]
        for row in rows:
            state=dict(particle_id=row['particle_id'],species_id=row['species_id'],
                position_m=[row['position_'+a+'_mm']*1e-3 for a in 'xyz'],
                velocity_m_s=[row['velocity_'+a+'_m_s'] for a in 'xyz'],time_s=row['instrument_time_us']*1e-6)
            initial.append(dict(state,mass_kg=row['mass_amu']*AMU_KG,charge_state=row['charge_state'],
                charge_c=row['charge_state']*ELEMENTARY_CHARGE_C,weight=row['particle_weight'],
                parent_particle_id=None,lineage_status='primary_birth'))
            state['time_s'] += 2e-9
            terminal.append(dict(state,physical_outcome='unknown',stop_reason='normal',component_id=None,
                electrode_id=None,surface_id=None,attribution_method='unavailable',attribution_status='unavailable',
                started=True,backend_version='inert-fixture',native_termination_code='2',native_entity_id=None,detail=None))
            if all_hits or row['particle_id']==rows[0]['particle_id']:
                for seq,surface in enumerate(('oa_focus_exit','oa_focus_plane'),1):
                    event=dict(terminal[-1],event_kind='observation',event_sequence=seq,crossing_direction=-1,
                        surface_id=surface,component_id='oa')
                    event['time_s']=state['time_s']-1e-9
                    event['position_m']=list(event['position_m']);event['position_m'][2]=0.
                    from msplatform.components.orthogonal_accelerator.focus_theory import _target_axial_energy_per_charge_v
                    target=_target_axial_energy_per_charge_v(campaign,release_z_mm=row['position_z_mm'],
                        geometry_profile=authority['geometry_profile'])
                    mass=row['mass_amu']*AMU_KG
                    source_axial=.5*mass*row['velocity_z_m_s']**2/ELEMENTARY_CHARGE_C
                    energy=target+source_axial+campaign['operating_point']['finite_3d_gain_correction_v']-10.
                    event['velocity_m_s']=list(event['velocity_m_s']);event['velocity_m_s'][2]=-math.sqrt(2.*energy*ELEMENTARY_CHARGE_C/mass)
                    events.append(event)
        arrays=dict(particle_id=np.empty(0,dtype='int64'),time_s=np.empty(0),position_m=np.empty((0,3)),velocity_m_s=np.empty((0,3)))
        trace=TraceResult(initial,terminal,events,arrays,'succeeded',dict(status='complete',
            detector_observation=detector_observation('not_requested',[r['particle_id'] for r in rows],reason='not_a_detector')))
        species=recipe['species']
        write_particle_data(work,trace,metadata=dict(schema_version=2,initial_state_basis='native_birth_verified',
            frame_id=authority['frame_id'],clock=dict(basis='experiment_relative',unit='s',**packet['clock']),species=species))
        store.publish_run(work,run_id=run,execution_status=status)
    return run


class FocusStoreAnalysisTests(unittest.TestCase):
    def test_cold_read_publish_and_reject_changed_birth_and_failed_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ArtifactStore(root/'store',high_water_bytes=100_000_000,low_water_bytes=80_000_000)
            valid=source(store,root/'author')
            with patch('msplatform.workflows.tracing.run_recipe') as forbidden:
                with self.assertRaisesRegex(ValueError,'analysis_budget_bytes'):
                    run_focus_recipe(root/'author/recipe.toml',artifact_store=store,context=object(),analysis_budget_bytes=0)
                forbidden.assert_not_called()
            with patch('msplatform.workflows.tracing.run_recipe',return_value={'run_id':valid}) as public_run:
                joined=run_focus_recipe(root/'author/recipe.toml',artifact_store=store,context=object(),
                                        analysis_budget_bytes=10_000_000)
                self.assertEqual(public_run.call_count,1)
                self.assertEqual(public_run.call_args.kwargs['high_water_bytes'],store.high)
                self.assertEqual(public_run.call_args.kwargs['low_water_bytes'],store.low)
                self.assertEqual(public_run.call_args.kwargs['safety_bytes'],store.safety)
                self.assertEqual(joined['focus_analysis']['source_run_id'],valid)
            result=publish_focus_analysis(store=store,source_run_id=valid,budget_bytes=10_000_000,
                exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            self.assertEqual(result['analysis']['measurements']['particle_count'],100)
            self.assertEqual(result['analysis']['measurements']['focus_particle_count'],1)
            self.assertIsNotNone(result['analysis']['measurements']['mean_arrival_s'])
            self.assertEqual(store.inspect_run(result['run_id']),Path(result['path']))
            facts=json.loads((Path(result['path'])/'model_facts.json').read_text(encoding='utf8'))
            self.assertEqual(facts['role'],'oa_focus_authenticated_model_facts')
            self.assertEqual(len(facts['ring_voltages_v']),15)
            self.assertEqual(facts['release_spec']['particle_count'],100)
            with guard_focus_original_birth(store=store,analysis_run_id=result['run_id']) as birth:
                self.assertEqual(len(birth['packet']['rows']),100)
                self.assertEqual(birth['packet']['state_kind'],'source_birth')
                self.assertEqual(len(birth['projected_birth_rows']),100)
                with self.assertRaises(OSError):(store.inspect_run(valid)/'oa_focus_source_packet.json').unlink()
            with guard_focus_analysis(store=store,run_id=result['run_id']) as held:
                self.assertEqual(held['model_facts'],facts)
                self.assertEqual(held['provenance']['source_run_id'],valid)
                with self.assertRaises(OSError):(Path(result['path'])/'analysis.json').unlink()
            with patch('msplatform.storage.store.os.replace',side_effect=OSError('injected publication interruption')):
                with self.assertRaisesRegex(OSError,'injected publication') as stopped:
                    publish_focus_analysis(store=store,source_run_id=valid,budget_bytes=10_000_000,
                        exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            interrupted=next(note.split(': ',1)[1] for note in stopped.exception.__notes__ if note.startswith('Store run_id: '))
            self.assertTrue(recover_focus_analysis_publication(store=store,run_id=interrupted))
            self.assertFalse(recover_focus_analysis_publication(store=store,run_id=interrupted))
            self.assertEqual(store.run_status(interrupted)['execution_status'],'succeeded')
            altered=source(store,root/'altered',alter_birth=True)
            with self.assertRaisesRegex(ValueError,'projected birth rows differ'):
                publish_focus_analysis(store=store,source_run_id=altered,budget_bytes=10_000_000,
                    exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            wrong_packet=source(store,root/'wrong_packet',alter_packet=True)
            with self.assertRaisesRegex(ValueError,'birth packet identity'):
                publish_focus_analysis(store=store,source_run_id=wrong_packet,budget_bytes=10_000_000,
                    exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            state=initialize_focus_adjustment(store=store,base_analysis_run_id=result['run_id'],maximum_trials=4)
            forged=copy.deepcopy(state);forged['next_parameters']['finite_3d_gain_correction_v']+=1.
            with self.assertRaisesRegex(ValueError,'initial parameters'):
                advance_focus_adjustment(store=store,state=forged,analysis_run_id=result['run_id'])
            with self.assertRaisesRegex(ValueError,'complete focus'):
                advance_focus_adjustment(store=store,state=state,analysis_run_id=result['run_id'])
            complete_source=source(store,root/'complete',all_hits=True)
            complete=publish_focus_analysis(store=store,source_run_id=complete_source,budget_bytes=10_000_000,
                exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            complete_state=initialize_focus_adjustment(store=store,base_analysis_run_id=complete['run_id'],maximum_trials=4)
            decision=advance_focus_adjustment(store=store,state=complete_state,analysis_run_id=complete['run_id'])
            self.assertEqual(len(decision['state']['records']),1)
            self.assertEqual(decision['state']['records'][0]['analysis_run_id'],complete['run_id'])
            self.assertFalse(decision['state']['records'][0]['accepted'])
            self.assertEqual(len(complete_state['records']),0)
            saved=publish_focus_adjustment_step(store=store,base_analysis_run_id=complete['run_id'],
                analysis_run_id=complete['run_id'],maximum_trials=4,budget_bytes=1_000_000)
            self.assertEqual(json.loads((Path(saved['path'])/'state.json').read_text(encoding='utf8')),saved['state'])
            self.assertEqual(store.inspect_run(saved['run_id']),Path(saved['path']))
            self.assertEqual(saved['state']['phase'],'gain_probe')
            self.assertIsNotNone(saved['next_campaign'])
            probe_source=source(store,root/'probe',all_hits=True,campaign_override=saved['next_campaign'])
            probe=publish_focus_analysis(store=store,source_run_id=probe_source,budget_bytes=10_000_000,
                exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
            second=publish_focus_adjustment_step(store=store,base_analysis_run_id=complete['run_id'],
                analysis_run_id=probe['run_id'],previous_run_id=saved['run_id'],budget_bytes=1_000_000)
            self.assertEqual(len(second['state']['records']),2)
            self.assertEqual(second['state']['records'][1]['analysis_run_id'],probe['run_id'])
            with patch('msplatform.storage.store.os.replace',side_effect=OSError('injected decision interruption')):
                with self.assertRaisesRegex(OSError,'injected decision') as stopped_decision:
                    publish_focus_adjustment_step(store=store,base_analysis_run_id=complete['run_id'],
                        analysis_run_id=complete['run_id'],maximum_trials=4,budget_bytes=1_000_000)
            stopped_id=next(note.split(': ',1)[1] for note in stopped_decision.exception.__notes__ if note.startswith('Store run_id: '))
            self.assertTrue(recover_focus_adjustment_publication(store=store,run_id=stopped_id))
            self.assertFalse(recover_focus_adjustment_publication(store=store,run_id=stopped_id))
            self.assertEqual(store.run_status(stopped_id)['execution_status'],'succeeded')
            failed=source(store,root/'failed',status='failed')
            with self.assertRaisesRegex(ValueError,'successful source'):
                publish_focus_analysis(store=store,source_run_id=failed,budget_bytes=10_000_000,
                    exit_surface_id='oa_focus_exit',focus_surface_id='oa_focus_plane')
