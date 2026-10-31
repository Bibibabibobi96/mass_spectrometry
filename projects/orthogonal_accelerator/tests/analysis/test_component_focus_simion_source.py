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
  campaign={'release_spec':spec,'simion_projection':{'source_frame':'orthogonal_accelerator_exit_origin_v1','workbench_mapping':'identity_xyz_with_local_exit_z_translation_v1','local_pa_span_mm':[64,64,64],'iob_origin_rule':'x_mirror_plane__negative_half_y__local_z_zero_v1','local_exit_z_mm':6,'focus_plane_padding_mm':6,'positive_z_enclosure_padding_mm':6,'semantics':'test'}}
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
   import subprocess, sys, shutil, copy
   if not shutil.which('pwsh'): self.skipTest('PowerShell 7 required')
   materialize_release(campaign['release_spec'],state,receipt)
   projection=root/'resolved projection.json';projection.write_text(json.dumps(campaign['simion_projection']),encoding='utf-8')
   template=copy.deepcopy(campaign);template['simion_projection']['local_exit_z_mm']=999.0
   campaign_path.write_text(json.dumps(template),encoding='utf-8')
   write_provider_plan(root,campaign['simion_projection']['local_exit_z_mm']).replace(root/'component_focus_pa_plan.json')
   harness=root/'capture_source.ps1'
   harness.write_text(r"""param($Repo,$Root,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$source=Join-Path $Repo 'projects/orthogonal_accelerator/simion/run_component_focus_flight.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$null,[ref]$null)
$calls=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Invoke-FocusFrozenPython'-and
 @($n.CommandElements|Where-Object{$_-is[Management.Automation.Language.StringConstantExpressionAst]-and$_.Value-eq'projects.orthogonal_accelerator.analysis.component_focus_simion_source'}).Count},$true))
if($calls.Count-ne1){throw 'Expected one actual frozen source call'}
$inputs=$Root;$releaseReceipt=Join-Path $Root 'release_receipt.json';$runCampaign=Join-Path $Root 'campaign.json'
$projectionPath=Join-Path $Root 'resolved projection.json';$fly=Join-Path $Root 'component_focus_input.fly2'
$sourceStates=Join-Path $Root 'component_focus.source_states.lua';$sourceReceipt=Join-Path $Root 'projection_receipt.json'
$focusPython=@{code_root=(Join-Path $Root 'frozen code');origins_path=(Join-Path $Root 'origins.json')}
function Invoke-FocusFrozenPython {param($Python,$CodeRoot,$OriginsPath,$Module,[string[]]$Arguments)
 @{module=$Module;arguments=$Arguments;code_root=$CodeRoot;origins=$OriginsPath;python=$Python}|ConvertTo-Json -Depth 20 -Compress
}
Invoke-Expression $calls[0].Extent.Text
""",encoding='utf-8')
   repo=project_root.parents[1]
   selected=subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(harness),str(repo),str(root),sys.executable],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
   self.assertEqual(selected.returncode,0,selected.stdout+selected.stderr)
   call=json.loads(selected.stdout)
   self.assertEqual(call['module'],'projects.orthogonal_accelerator.analysis.component_focus_simion_source')
   self.assertEqual(call['arguments'],['--release-receipt',str(receipt),'--campaign',str(campaign_path),'--provider-plan',str(root/'component_focus_pa_plan.json'),'--resolved-projection',str(projection),'--fly2',str(fly),'--source-states',str(source_states),'--receipt',str(root/'projection_receipt.json')])
   self.assertEqual(call['code_root'],str(root/'frozen code'))
   actual=subprocess.run([sys.executable,'-m',call['module'],*call['arguments']],cwd=repo,capture_output=True,text=True,encoding='utf-8',timeout=30)
   self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
   self.assertEqual(json.loads((root/'projection_receipt.json').read_text())['particle_count'],100)
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
  self.assertIn("[Parameter(Mandatory)][string]$RuntimeControllerPath",runner)
  self.assertIn("$expectedRuntimeNames=@(0..$electrodeCount",runner)
  self.assertIn("Flight refuses a controller inside the published cache generation",runner)
  self.assertIn("Private runtime family inventory differs from the provider electrode namespace",runner)
  self.assertIn("published_standalone_responses__shared_private_native_fast_adjust_family",runner)
  self.assertIn('$failureDetail=$_.Exception.Message;throw',runner)
  self.assertIn('$reason+=" $failureDetail"',runner)

 def test_mr_component_release_uses_local_y_drift_and_not_nominal_negative_z_direction(self):
  repo=Path(__file__).resolve().parents[4]
  spec=json.loads((repo/'projects'/'parallel_mirror_dual_stripe_mr_tof'/'config'/'accelerator_component_release_n100.json').read_text(encoding='utf-8'))
  self.assertEqual(spec['frame_id'],'orthogonal_accelerator_exit_origin_v1')
  self.assertEqual(spec['geometry'],{'shape':'cylinder','center_mm':[0.0,0.0,32.0],'axis':'y','radius_mm':0.5,'height_mm':1.0})
  self.assertEqual(spec['sampling']['nominal_direction'],[0.0,1.0,0.0])
  self.assertEqual(spec['sampling']['angular_full_width_deg'],0.0)
  self.assertAlmostEqual(spec['sampling']['kinetic_energy']['center_ev'],4.961131691875479)
  state=generate_release_states(spec)[0]
  self.assertGreater(state['vy_m_s'],0.0)
  self.assertEqual(state['vz_m_s'],0.0)

 def test_fly2_retains_each_common_particle_energy(self):
  repo=Path(__file__).resolve().parents[4]
  spec=json.loads((repo/'projects'/'parallel_mirror_dual_stripe_mr_tof'/'config'/'accelerator_component_release_n100.json').read_text(encoding='utf-8'))
  campaign={'release_spec':spec,'simion_projection':{'source_frame':'orthogonal_accelerator_exit_origin_v1','workbench_mapping':'identity_xyz_with_local_exit_z_translation_v1','local_pa_span_mm':[44.5,24.5,50.0],'iob_origin_rule':'x_mirror_plane__negative_half_y__local_z_zero_v1','local_exit_z_mm':6,'focus_plane_padding_mm':6,'positive_z_enclosure_padding_mm':6,'semantics':'test'}}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);receipt=root/'r.json';state=root/'s.csv';campaign_path=root/'c.json';fly=root/'x.fly2';source_states=root/'states.lua'
   materialize_release(spec,state,receipt);campaign_path.write_text(json.dumps(campaign),encoding='utf-8')
   materialize(receipt,campaign_path,write_provider_plan(root,6.0),fly,source_states)
   fly_text=fly.read_text(encoding='ascii')
   self.assertIn('ke = 4.961131691875479',fly_text)
   self.assertIn('ke = 4.925417406161194',fly_text)

 def test_rejects_exit_adjacent_source_that_is_not_in_first_gap(self):
  spec={'schema_version':1,'role':'repository_ion_release','frame_id':'orthogonal_accelerator_exit_origin_v1','particle_count':1,'mother_particle_count':1,'common_time_of_birth_s':0.0,'geometry':{'shape':'cylinder','center_mm':[0,0,3],'axis':'z','radius_mm':1,'height_mm':1},'species':{'mass_amu':100.,'charge_state':1},'sampling':{'strategy':'center_first_halton_cylinder_v1','kinetic_energy':{'center_ev':.001,'full_width_ev':0},'nominal_direction':[0,0,-1],'angular_full_width_deg':0}}
  campaign={'release_spec':spec,'simion_projection':{'source_frame':'orthogonal_accelerator_exit_origin_v1','workbench_mapping':'identity_xyz_with_local_exit_z_translation_v1','local_pa_span_mm':[64,64,64],'iob_origin_rule':'x_mirror_plane__negative_half_y__local_z_zero_v1','local_exit_z_mm':6,'focus_plane_padding_mm':6,'positive_z_enclosure_padding_mm':6,'semantics':'test'}}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);receipt=root/'r.json';state=root/'s.csv';campaign_path=root/'c.json';fly=root/'x.fly2';source_states=root/'states.lua';materialize_release(spec,state,receipt);campaign_path.write_text(json.dumps(campaign),encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'first acceleration gap'):
    materialize(receipt,campaign_path,write_provider_plan(root),fly,source_states)

if __name__=='__main__':unittest.main()
