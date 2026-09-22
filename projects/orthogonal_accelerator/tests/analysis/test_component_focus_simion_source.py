from __future__ import annotations
import tempfile, unittest
from pathlib import Path
import json
from common.ion_release.release import generate_release_states, materialize_release
from projects.orthogonal_accelerator.analysis.component_focus_simion_source import materialize


def write_provider_plan(root: Path, local_exit_z_mm: float = 6.0) -> Path:
 plan=root/'plan.json';plan.write_text(json.dumps({'role':'orthogonal_accelerator_component_focus_pa_plan','numerical_domain':{'local_exit_z_mm':local_exit_z_mm},'layout':{'gap_1_mm':6.0,'gap_2_mm':30.6}}),encoding='utf-8');return plan

class SimionSourceTests(unittest.TestCase):
 def test_projects_common_release_into_local_first_gap_frame(self):
  spec={'schema_version':1,'role':'repository_ion_release','frame_id':'orthogonal_accelerator_exit_origin_v1','particle_count':1,'mother_particle_count':1,'common_time_of_birth_s':0.0,'geometry':{'shape':'cylinder','center_mm':[0,0,33.6],'axis':'z','radius_mm':1,'height_mm':1},'species':{'mass_amu':100.,'charge_state':1},'sampling':{'strategy':'center_first_halton_cylinder_v1','kinetic_energy':{'center_ev':.001,'full_width_ev':0},'nominal_direction':[0,0,-1],'angular_full_width_deg':0}}
  campaign={'release_spec':spec,'simion_projection':{'source_frame':'orthogonal_accelerator_exit_origin_v1','workbench_mapping':'identity_xyz_with_local_exit_z_translation_v1','local_pa_span_mm':[64,64,64],'iob_origin_rule':'negative_half_transverse_span__local_z_zero_v1','local_exit_z_mm':6,'focus_plane_padding_mm':6,'positive_z_enclosure_padding_mm':6,'semantics':'test'}}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);receipt=root/'r.json';state=root/'s.csv';materialize_release(spec,state,receipt);camp=root/'c.json';import json;camp.write_text(json.dumps(campaign));fly=root/'x.fly2';source_states=root/'component_focus.source_states.lua';out=materialize(receipt,camp,write_provider_plan(root),fly,source_states);self.assertEqual(out['particle_count'],1);self.assertIn('position = vector(0.0,0.0,39.6)',fly.read_text());self.assertIn('[1]={t=0,x=0,y=0,z=39.6',source_states.read_text());self.assertIn('source_states_sha256',out)

 def test_campaign_input_has_one_hundred_beams_and_cannot_be_the_iob_companion(self):
  project_root=Path(__file__).resolve().parents[2]
  campaign=json.loads((project_root/"config"/"two_zone_component_focus_campaign.json").read_text(encoding="utf-8"))
  states=generate_release_states(campaign["release_spec"])
  self.assertEqual(len(states),100)
  span=campaign['simion_projection']['local_pa_span_mm'];origin=(-span[0]/2,-span[1]/2,0.0)
  for state in states:
   self.assertGreaterEqual(state['x_mm']-origin[0],0.0);self.assertLessEqual(state['x_mm']-origin[0],span[0])
   self.assertGreaterEqual(state['y_mm']-origin[1],0.0);self.assertLessEqual(state['y_mm']-origin[1],span[1])
   self.assertGreaterEqual(state['z_mm']+campaign['simion_projection']['local_exit_z_mm']-origin[2],0.0);self.assertLessEqual(state['z_mm']+campaign['simion_projection']['local_exit_z_mm']-origin[2],span[2])
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);receipt=root/'release_receipt.json';state=root/'release.csv';fly=root/'component_focus_input.fly2';source_states=root/'component_focus.source_states.lua';campaign_path=root/'campaign.json'
   materialize_release(campaign['release_spec'],state,receipt);campaign_path.write_text(json.dumps(campaign),encoding='utf-8')
   materialize(receipt,campaign_path,write_provider_plan(root,campaign['simion_projection']['local_exit_z_mm']),fly,source_states)
   self.assertEqual(fly.read_text(encoding='ascii').count('standard_beam {'),100)
   self.assertEqual(source_states.read_text(encoding='ascii').count(']={t='),100)
  runner=(project_root/'simion'/'run_component_focus_flight.ps1').read_text(encoding='utf-8')
  builder=(project_root/'simion'/'build_component_focus_iob.lua').read_text(encoding='utf-8')
  self.assertIn("component_focus_input.fly2",runner)
  self.assertIn("fly --trajectory-quality $($c.numerics.trajectory_quality) --particles $fly --programs 1 --retain-trajectories 0 $iob",runner)
  self.assertIn("cp(fly,output:gsub('%.iob$','.fly2'))",builder)
  self.assertIn("origin_x,origin_y,origin_z",builder)
  self.assertIn("[Parameter(Mandatory)][string]$PABuildRunPath",runner)
  self.assertIn("[Parameter(Mandatory)][string]$ReleaseSpecPath",runner)
  self.assertIn("$campaignTemplate=Join-Path $inputs 'campaign_template.json'",runner)
  self.assertIn("Copy-VerifiedRunInput (Resolve-Path -LiteralPath $ReleaseSpecPath).Path $releaseSpec",runner)
  self.assertIn("$c.release_spec=(Get-Content -Raw $releaseSpec|ConvertFrom-Json)",runner)
  self.assertIn("component_focus_pa_result.json",runner)
  self.assertIn("--resolved-projection $projectionPath",runner)
  self.assertIn("--provider-plan (Join-Path $inputs 'component_focus_pa_plan.json')",runner)
  self.assertIn("runtime_fast_adjust__no_copy_refine_or_rebuild",runner)
  self.assertIn('$failureDetail=$_.Exception.Message;throw',runner)
  self.assertIn('$reason+=" $failureDetail"',runner)

 def test_mr_component_release_uses_local_y_drift_and_not_nominal_negative_z_direction(self):
  repo=Path(__file__).resolve().parents[4]
  spec=json.loads((repo/'projects'/'parallel_mirror_dual_stripe_mr_tof'/'config'/'accelerator_component_release_n100.json').read_text(encoding='utf-8'))
  self.assertEqual(spec['frame_id'],'orthogonal_accelerator_exit_origin_v1')
  self.assertEqual(spec['geometry'],{'shape':'cylinder','center_mm':[0.0,0.0,32.0],'axis':'z','radius_mm':1.0,'height_mm':1.0})
  self.assertEqual(spec['sampling']['nominal_direction'],[0.0,1.0,0.0])
  self.assertAlmostEqual(spec['sampling']['kinetic_energy']['center_ev'],4.961131691875479)
  state=generate_release_states(spec)[0]
  self.assertGreater(state['vy_m_s'],0.0)
  self.assertEqual(state['vz_m_s'],0.0)

 def test_rejects_exit_adjacent_source_that_is_not_in_first_gap(self):
  spec={'schema_version':1,'role':'repository_ion_release','frame_id':'orthogonal_accelerator_exit_origin_v1','particle_count':1,'mother_particle_count':1,'common_time_of_birth_s':0.0,'geometry':{'shape':'cylinder','center_mm':[0,0,3],'axis':'z','radius_mm':1,'height_mm':1},'species':{'mass_amu':100.,'charge_state':1},'sampling':{'strategy':'center_first_halton_cylinder_v1','kinetic_energy':{'center_ev':.001,'full_width_ev':0},'nominal_direction':[0,0,-1],'angular_full_width_deg':0}}
  campaign={'release_spec':spec,'simion_projection':{'source_frame':'orthogonal_accelerator_exit_origin_v1','workbench_mapping':'identity_xyz_with_local_exit_z_translation_v1','local_pa_span_mm':[64,64,64],'iob_origin_rule':'negative_half_transverse_span__local_z_zero_v1','local_exit_z_mm':6,'focus_plane_padding_mm':6,'positive_z_enclosure_padding_mm':6,'semantics':'test'}}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);receipt=root/'r.json';state=root/'s.csv';campaign_path=root/'c.json';fly=root/'x.fly2';source_states=root/'states.lua';materialize_release(spec,state,receipt);campaign_path.write_text(json.dumps(campaign),encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'first acceleration gap'):
    materialize(receipt,campaign_path,write_provider_plan(root),fly,source_states)

if __name__=='__main__':unittest.main()
