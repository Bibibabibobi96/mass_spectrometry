"""Original focus author projected into existing public OA geometry and model."""
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.workflows.oa_focus_model_projection import project_focus_model

ROOT=Path(__file__).resolve().parents[2]
COMPONENT=ROOT/'src/msplatform/components/orthogonal_accelerator'

class FocusModelProjectionTests(unittest.TestCase):
    def test_original_author_projects_exact_physics_and_planes(self):
        campaign=COMPONENT/'config/two_zone_component_focus_campaign.json'
        author=json.loads(campaign.read_text(encoding='utf8'))
        profile=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))['geometry_profiles'][author['geometry_profile_id']]
        clock=dict(clock_epoch_id='focus_test_clock',authority_sha256='A'*64,phase_reference_instrument_time_us=0.)
        result=project_focus_model(campaign,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)
        model=result['model'].document;geometry=model['geometry']['frontend_geometry']
        self.assertEqual(geometry['role'],'simion_independent_oa_geometry')
        self.assertIsNone(model['components_resolved']['oa']['side_entry'])
        self.assertEqual(geometry['numerical_domains']['oa']['dimensions'],dict(nx=90,ny=139,nz=501))
        self.assertEqual(geometry['numerical_domains']['oa']['symmetry'],'mirror_x')
        self.assertEqual(geometry['numerical_domains']['oa']['surface'],'none')
        self.assertEqual(result['observations']['exit_z_mm'],0.)
        self.assertEqual(result['observations']['focus_z_mm'],author['operating_point']['focus_plane_offset_from_exit_mm'])
        self.assertEqual(result['observations']['geometry_profile'],profile)
        self.assertEqual(result['observations']['mesh_mm_per_gu'],[.25,.25,.1])
        self.assertEqual(result['observations']['clock'],clock)
        grid=result['observations']['focus_native_grid']
        self.assertEqual(grid['dimensions'],[90,139,501])
        self.assertEqual(grid['component_domain']['symmetry'],'mirror_x')
        self.assertEqual(grid['component_domain']['surface'],'none')
        self.assertEqual(grid['component_domain']['pa_bounds_mm'],dict(x_min=0.,x_max=22.25,
            y_min=-17.25,y_max=17.25,z_min=-6.,z_max=44.))
        groups=model['drive']['groups']['oa'];volts=author['operating_point']['electrode_voltages_v']
        for name,index in [('grounded_shield',0),('repeller',1),('intermediate_grid_1',2),('exit_grid',3)]:
            self.assertEqual(groups[name],dict(kind='static',voltage_v=volts[index]))
        for i in range(15):self.assertEqual(groups[f'ring_{i+1:04d}']['voltage_v'],volts[i+4])
        self.assertEqual(result['focus_plan']['requirements']['schema_version'],1)
        self.assertEqual(result['release_spec'],author['release_spec'])
        from msplatform.backends.simion.oa_focus_model_projection import focus_model_facts
        contract=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))
        facts=focus_model_facts(result['observations'],campaign=author,component_contract=contract,model_document=model)
        self.assertEqual(facts['release_spec'],author['release_spec'])
        self.assertEqual(facts['drive']['groups'],model['drive']['groups'])
        self.assertEqual(facts['geometry']['aperture_height_y_mm'],profile['aperture_height_y_mm'])
        self.assertEqual(facts['endpoint_voltages_v'],volts[1:4])
        self.assertEqual(facts['ring_voltages_v'],volts[4:])
        self.assertEqual(facts['geometry']['repeller_to_exit_mm'],profile['gap_1_mm']+profile['gap_2_mm'])
        self.assertEqual(facts['geometry']['release_position_in_gap_1_mm'],
            profile['gap_1_mm']+profile['gap_2_mm']-author['release_spec']['geometry']['center_mm'][2])
        self.assertEqual(facts['clock'],clock)
        self.assertEqual(result['focus_plan']['numerical_domain']['mirror_axes'],['x'])
        self.assertEqual(geometry['numerical_domains']['oa']['cell_mm_xyz'],dict(x=.25,y=.25,z=.1))
        self.assertEqual(result['focus_plan']['numerical_domain']['stored_span_mm'][0],
                         geometry['numerical_domains']['oa']['bounds_mm']['x_max']-geometry['numerical_domains']['oa']['bounds_mm']['x_min'])
        # Independent coordinate translation of each emitted electrode primitive;
        # this compares original and new geometry rather than only names or roles.
        import re
        def primitives(gem,offset):
            result=[]
            for line in gem.splitlines():
                electrode=re.search(r'\be\((\d+)\)',line)
                if electrode is None:continue
                boxes=[]
                for body in re.findall(r'box3D\(([^)]*)\)',line):
                    coords=[float(value) for value in body.split(',')]
                    boxes.append(tuple(value+offset[index%3] for index,value in enumerate(coords)))
                result.append((int(electrode.group(1)),tuple(boxes),line.count('notin_inside'),
                               line.count('notin {')))
            return result
        old=primitives(result['focus_plan']['gem'],(0.,17.25,0.))
        new=primitives(model['geometry']['frontend_gems']['oa'],(0.,17.25,6.))
        self.assertEqual(old,new)
        changed=dict(profile,gap_1_mm=profile['gap_1_mm']+1)
        with self.assertRaisesRegex(ValueError,'component authority'):
            project_focus_model(campaign,geometry_profile=changed,mesh_mm_per_gu=[.25,.25,.1],clock=clock)

    def test_gain_correction_preserves_theory_seed_and_rejects_unbound_voltage(self):
        import copy
        from msplatform.components.orthogonal_accelerator.focus_voltage_adjustment import _candidate_campaign
        campaign_path=COMPONENT/'config/two_zone_component_focus_campaign.json'
        author=json.loads(campaign_path.read_text(encoding='utf8'))
        contract=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))
        profile=contract['geometry_profiles'][author['geometry_profile_id']]
        clock=dict(clock_epoch_id='focus_test_clock',authority_sha256='A'*64,phase_reference_instrument_time_us=0.)
        corrected=_candidate_campaign(author,dict(instance_center_y_mm=0.,finite_3d_gain_correction_v=5.),geometry_profile=profile)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'campaign.json'
            def project(value):
                path.write_text(json.dumps(value),encoding='utf8')
                return project_focus_model(path,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)
            baseline=project(author);changed=project(corrected)
            self.assertAlmostEqual(baseline['focus_plan']['theory_seed']['nominal_energy_per_charge_v'],
                                   changed['focus_plan']['theory_seed']['nominal_energy_per_charge_v'],places=9)
            self.assertEqual(changed['model'].document['drive']['groups']['oa']['repeller']['voltage_v'],
                             corrected['operating_point']['electrode_voltages_v'][1])
            undeclared=copy.deepcopy(corrected);undeclared['operating_point']['finite_3d_gain_correction_v']=0.
            with self.assertRaisesRegex(ValueError,'first-gap voltages'):project(undeclared)
            inconsistent=copy.deepcopy(corrected);inconsistent['operating_point']['electrode_voltages_v'][1]+=1.
            with self.assertRaises(ValueError):project(inconsistent)
            wrong_ring=copy.deepcopy(corrected);wrong_ring['operating_point']['electrode_voltages_v'][4]+=1.
            with self.assertRaisesRegex(ValueError,'rings do not linearly'):project(wrong_ring)

    def test_focus_author_nonzero_instance_y_is_the_actual_assembly_pose(self):
        campaign=COMPONENT/'config/two_zone_component_focus_campaign.json'
        author=json.loads(campaign.read_text(encoding='utf8'))
        profile=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))['geometry_profiles'][author['geometry_profile_id']]
        author['operating_point']['instance_center_y_mm']=1.25
        clock=dict(clock_epoch_id='focus_test_clock',authority_sha256='A'*64,phase_reference_instrument_time_us=0.)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'campaign.json';path.write_text(json.dumps(author),encoding='utf8')
            result=project_focus_model(path,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)
        recipe=result['model'].document['geometry']['frontend_geometry']['composition_plan']['recipe']
        self.assertEqual(recipe['instances'][0]['transform']['translation_mm'],[0.,1.25,0.])

    def test_original_release_is_wrapped_once_with_explicit_clock_and_species(self):
        from msplatform.particle_release.authoring import sample_release
        from msplatform.particle_release.release import generate_release_states
        campaign=COMPONENT/'config/two_zone_component_focus_campaign.json'
        author=json.loads(campaign.read_text(encoding='utf8'))
        profile=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))['geometry_profiles'][author['geometry_profile_id']]
        clock=dict(clock_epoch_id='focus_test_clock',authority_sha256='A'*64,phase_reference_instrument_time_us=0.)
        result=project_focus_model(campaign,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)
        request=dict(schema_version=1,role='canonical_birth_source_request',release_spec=result['release_spec'],
            clock={'clock_epoch_id':clock['clock_epoch_id'],'authority_sha256':clock['authority_sha256']},
            instrument_origin_us=0.,species_id='focus_fixture_ion',source_component_id='oa',relative_weights=None)
        actual=sample_release(request).to_dict();expected=generate_release_states(author['release_spec'])
        self.assertEqual(actual['realization']['generator_rows'],expected)
        self.assertEqual(len(actual['rows']),100)
        self.assertEqual([row['particle_id'] for row in actual['rows']],[row['particle_id'] for row in expected])
        self.assertEqual(actual['realization']['spec']['mother_particle_count'],1000)

    def test_backend_rederives_authority_and_rejects_forged_plane_or_model(self):
        import copy
        from msplatform.backends.simion.oa_focus_model_projection import validate_focus_authority
        campaign_path=COMPONENT/'config/two_zone_component_focus_campaign.json'
        campaign=json.loads(campaign_path.read_text(encoding='utf8'))
        contract=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))
        profile=contract['geometry_profiles'][campaign['geometry_profile_id']]
        clock=dict(clock_epoch_id='focus_test_clock',authority_sha256='A'*64,phase_reference_instrument_time_us=0.)
        projection=project_focus_model(campaign_path,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)
        authority=projection['observations'];model=projection['model'].document
        self.assertEqual(validate_focus_authority(authority,campaign=campaign,component_contract=contract,model_document=model),authority)
        forged=copy.deepcopy(authority);forged['focus_z_mm']=-1.
        with self.assertRaisesRegex(ValueError,'differs from frozen author'):
            validate_focus_authority(forged,campaign=campaign,component_contract=contract,model_document=model)
        altered=copy.deepcopy(model);altered['drive']['groups']['oa']['repeller']['voltage_v']+=1.
        with self.assertRaisesRegex(ValueError,'differs from frozen author'):
            validate_focus_authority(authority,campaign=campaign,component_contract=contract,model_document=altered)
