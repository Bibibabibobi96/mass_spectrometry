"""OA canonical SI focus-event measurements; no vendor execution."""
import copy
import unittest
from msplatform.analysis.oa_focus_events import focus_plane_measurements

class FocusPlaneMeasurementTests(unittest.TestCase):
    def fixture(self):
        starts=[dict(particle_id=1,species_id='negative_ion',position_m=[0.,0.,.01],velocity_m_s=[0.,0.,-2.],time_s=0.),
                dict(particle_id=2,species_id='electron',position_m=[0.,0.,.01],velocity_m_s=[0.,0.,-2.],time_s=0.)]
        ends=[dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=[0.,0.,-.02],
                   velocity_m_s=[0.,0.,-2.],time_s=.02) for row in starts]
        events=[]
        for pid,species,x in ((1,'negative_ion',.003),(2,'electron',.004)):
            for seq,(surface,z,t) in enumerate((('exit',0.,.005),('focus',-.01,.01)),1):
                events.append(dict(particle_id=pid,species_id=species,position_m=[x,0.,z],velocity_m_s=[0.,0.,-2.],
                    time_s=t,event_kind='observation',event_sequence=seq,surface_id=surface))
        return starts,ends,events
    def measure(self,starts,ends,events):
        return focus_plane_measurements(starts,ends,events,frame_id='oa_local',exit_surface_id='exit',focus_surface_id='focus',
            exit_z_m=0.,focus_z_m=-.01,plane_tolerance_m=1e-9)
    def test_exact_si_metrics_and_zero_hit_null(self):
        starts,ends,events=self.fixture();result=self.measure(starts,ends,events)
        self.assertEqual(result['particle_count'],2);self.assertEqual(result['focus_particle_count'],2)
        self.assertEqual(result['mean_arrival_s'],.01);self.assertEqual(result['peak_to_peak_arrival_s'],0.)
        self.assertAlmostEqual(result['transverse_rms_radius_m'],(.5*(.003**2+.004**2))**.5)
        empty=self.measure(starts,ends,[])
        self.assertEqual(empty['not_reached_focus_particle_ids'],[1,2]);self.assertEqual(empty['transport_fraction'],0.)
        self.assertIsNone(empty['mean_arrival_s']);self.assertIsNone(empty['transverse_rms_radius_m'])
    def test_rejects_incomplete_cohort_wrong_species_and_missing_exit_evidence(self):
        starts,ends,events=self.fixture()
        with self.assertRaisesRegex(ValueError,'cohorts differ'):self.measure(starts,ends[:1],events)
        altered=copy.deepcopy(events);altered[0]['species_id']='electron'
        with self.assertRaisesRegex(ValueError,'species identity'):self.measure(starts,ends,altered)
        with self.assertRaisesRegex(ValueError,'lacks the earlier exit'):self.measure(starts,ends,events[1:])
        altered=copy.deepcopy(events);altered[1]['time_s']=.001
        with self.assertRaisesRegex(ValueError,'precedes'):self.measure(starts,ends,altered)
        altered=copy.deepcopy(events)
        for row in altered:
            if row['surface_id']=='focus':row['position_m'][2]=0.
        with self.assertRaisesRegex(ValueError,'same-plane'):
            focus_plane_measurements(starts,ends,altered,frame_id='oa_local',exit_surface_id='exit',focus_surface_id='focus',
                exit_z_m=0.,focus_z_m=0.,plane_tolerance_m=1e-9)

    def test_matches_existing_focus_measurements_on_same_frozen_cohort(self):
        import csv
        from tests.components.orthogonal_accelerator.analysis import test_component_focus_analysis as old
        from msplatform.workflows.oa_focus_analysis import analyze
        fixture=old.ComponentFocusAnalysisTests();fixture.setUp()
        try:
            path=fixture.write_events()
            historical=analyze(path,fixture.receipt,fixture.campaign,geometry_profile=old._geometry_profile())
            rows=list(csv.DictReader(path.read_text(encoding='utf8').splitlines()))
            starts=[];ends=[];events=[]
            for row in rows:
                pid=int(row['ion']);state=dict(particle_id=pid,species_id='same_fixture_species',
                    position_m=[float(row[f'{axis}_mm'])*1e-3 for axis in 'xyz'],
                    velocity_m_s=[float(row[f'v{axis}_mm_us'])*1e3 for axis in 'xyz'],time_s=float(row['t_us'])*1e-6)
                if row['kind']=='source':starts.append(state)
                elif row['kind']=='terminal':ends.append(state)
                else:events.append(dict(state,event_kind='observation',event_sequence=1 if row['kind']=='exit' else 2,
                                        surface_id=row['kind']))
            result=focus_plane_measurements(starts,ends,events,frame_id='oa_local',exit_surface_id='exit',focus_surface_id='focus',
                exit_z_m=0.,focus_z_m=0.,plane_tolerance_m=1e-9)
            self.assertEqual(result['focus_particle_count'],historical['focus_particle_count'])
            self.assertEqual(result['transport_fraction'],historical['transport_fraction'])
            self.assertAlmostEqual(result['mean_arrival_s'],historical['focus_metrics']['mean_t_us']*1e-6)
            self.assertAlmostEqual(result['transverse_rms_radius_m'],historical['focus_metrics']['transverse_rms_radius_mm']*1e-3)
        finally:fixture.tearDown()


    def test_component_si_analysis_preserves_original_energy_and_ideal_theory(self):
        import csv
        from msplatform.components.orthogonal_accelerator.focus_result import analyze_focus_result
        from msplatform.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
        from msplatform.workflows.oa_focus_model_projection import project_focus_model
        from tests.components.orthogonal_accelerator.analysis import test_component_focus_analysis as old
        from msplatform.workflows.oa_focus_analysis import analyze
        fixture=old.ComponentFocusAnalysisTests();fixture.setUp()
        try:
            path=fixture.write_events();profile=old._geometry_profile()
            historical=analyze(path,fixture.receipt,fixture.campaign,geometry_profile=profile)
            campaign=__import__('json').loads(fixture.campaign.read_text(encoding='utf8'))
            clock=dict(clock_epoch_id='focus_test_clock',authority_sha256='A'*64,phase_reference_instrument_time_us=0.)
            authority=project_focus_model(fixture.campaign,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)['observations']
            rows=list(csv.DictReader(path.read_text(encoding='utf8').splitlines()));starts=[];ends=[];events=[]
            for row in rows:
                pid=int(row['ion']);state=dict(particle_id=pid,species_id='same_fixture_species',
                    position_m=[float(row[f'{axis}_mm'])*1e-3 for axis in 'xyz'],
                    velocity_m_s=[float(row[f'v{axis}_mm_us'])*1e3 for axis in 'xyz'],time_s=float(row['t_us'])*1e-6)
                if row['kind']=='source':starts.append(dict(state,mass_kg=100.*AMU_KG,charge_state=1,charge_c=ELEMENTARY_CHARGE_C,weight=1.))
                elif row['kind']=='terminal':ends.append(state)
                else:events.append(dict(state,event_kind='observation',event_sequence=1 if row['kind']=='exit' else 2,surface_id=row['kind'],component_id='oa'))
            data=dict(execution_status='succeeded',data_integrity={'status':'complete'},initial_states=starts,terminal_states=ends,
                events=events,metadata=dict(frame_id=authority['frame_id'],clock=clock,species=[dict(
                    species_id='same_fixture_species',species_kind='ion',mass_kg=100.*AMU_KG,
                    charge_state=1,charge_c=ELEMENTARY_CHARGE_C)]))
            packet={'rows':[dict(particle_id=row['particle_id'],species_id=row['species_id'],charge_state=row['charge_state'],
                frame_id=authority['frame_id'],clock_epoch_id=clock['clock_epoch_id'],mass_amu=100.,particle_weight=1.,
                instrument_time_us=row['time_s']*1e6,**{f'position_{axis}_mm':row['position_m'][i]*1e3 for i,axis in enumerate('xyz')},
                **{f'velocity_{axis}_m_s':row['velocity_m_s'][i] for i,axis in enumerate('xyz')}) for row in starts]}
            result=analyze_focus_result(data,campaign=campaign,geometry_profile=profile,authority=authority,
                projected_birth_rows=packet['rows'],exit_surface_id='exit',focus_surface_id='focus')
            from msplatform.components.orthogonal_accelerator.focus_voltage_adjustment import residual_from_focus_analysis
            adjustment=residual_from_focus_analysis(result)
            from msplatform.components.orthogonal_accelerator.focus_voltage_adjustment import adjustment_record_from_si
            record=adjustment_record_from_si(result)
            self.assertAlmostEqual(record['residuals'][0],
                historical['exit_energy_assessment']['center_particle']['axial_energy_residual_per_charge_v'])
            self.assertEqual(record['accepted'],historical['status']=='candidate_complete')
            self.assertAlmostEqual(adjustment['center_axial_residual_v'],
                historical['exit_energy_assessment']['center_particle']['axial_energy_residual_per_charge_v'])
            incomplete=copy.deepcopy(result);incomplete['measurements']['focus_particle_count']-=1
            with self.assertRaisesRegex(ValueError,'complete focus'):
                residual_from_focus_analysis(incomplete)
            actual_cohort=result['energy_assessment']['cohort'];expected_cohort=historical['exit_energy_assessment']['cohort']
            for key,expected in expected_cohort.items():
                if type(expected) is float:self.assertAlmostEqual(actual_cohort[key],expected,places=12)
                else:self.assertEqual(actual_cohort[key],expected)
            self.assertEqual(result['ideal_contrast']['requested_particle_ids'],historical['ideal_field_contrast']['requested_particle_ids'])
            for actual,expected in zip(result['ideal_contrast']['particle_pairs'],historical['ideal_field_contrast']['particle_pairs'],strict=True):
                self.assertAlmostEqual(actual['ideal_arrival_t_us'],expected['ideal_arrival_t_us'],places=12)
            incorrect_mass=copy.deepcopy(data)
            incorrect_mass['initial_states'][0]['mass_kg'] *= 2.
            with self.assertRaisesRegex(ValueError,'mass or signed charge'):
                analyze_focus_result(incorrect_mass,campaign=campaign,geometry_profile=profile,authority=authority,
                    projected_birth_rows=packet['rows'],exit_surface_id='exit',focus_surface_id='focus')
            wrong_birth=copy.deepcopy(packet['rows'])
            wrong_birth[0]['position_y_mm'] += 1.
            with self.assertRaisesRegex(ValueError,'frozen birth cohort'):
                analyze_focus_result(data,campaign=campaign,geometry_profile=profile,authority=authority,
                    projected_birth_rows=wrong_birth,exit_surface_id='exit',focus_surface_id='focus')
            from msplatform.contracts.particle_physics import ELECTRON_CONSTANTS
            from msplatform.io.file_identity import canonical_json_sha256
            for kind,mass_u,mass_kg in (('ion',100.,100.*AMU_KG),('electron',ELECTRON_CONSTANTS['mass_u'],ELECTRON_CONSTANTS['mass_kg'])):
                with self.subTest(species_kind=kind):
                    altered_campaign=copy.deepcopy(campaign)
                    altered_campaign['release_spec']['species']=dict(species_kind=kind,mass_amu=mass_u,charge_state=-1)
                    altered=copy.deepcopy(data);identifier='negative_ion' if kind=='ion' else 'electron'
                    altered['metadata']['species']=[dict(species_id=identifier,species_kind=kind,mass_kg=mass_kg,
                                                         charge_state=-1,charge_c=-ELEMENTARY_CHARGE_C)]
                    for collection in ('initial_states','terminal_states','events'):
                        for row in altered[collection]:row['species_id']=identifier
                    for row in altered['initial_states']:
                        row.update(mass_kg=mass_kg,charge_state=-1,charge_c=-ELEMENTARY_CHARGE_C)
                    changed_authority=dict(authority,campaign_content_sha256=canonical_json_sha256(altered_campaign))
                    changed_packet=copy.deepcopy(packet)
                    for row in changed_packet['rows']:row.update(species_id=identifier,charge_state=-1,mass_amu=mass_u)
                    nonpositive=analyze_focus_result(altered,campaign=altered_campaign,geometry_profile=profile,
                        authority=changed_authority,projected_birth_rows=changed_packet['rows'],exit_surface_id='exit',focus_surface_id='focus')
                    self.assertEqual(nonpositive['measurements']['focus_particle_count'],3)
                    self.assertEqual(nonpositive['ideal_contrast']['status'],'unsupported_nonpositive_charge')
        finally:fixture.tearDown()
