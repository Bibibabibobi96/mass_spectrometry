"""Opt-in SIMION checkpoint transport smoke; N=1 is exploration, never qualification.

Set MASS_SPECTROMETRY_RUN_NATIVE_RF_FIELD_CHECKPOINT=1 to run on Windows.
The normal L1/L2 path skips this commercial test. Its permanent evidence uses
the existing RF project runs and scratch directories and public lifecycle.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

from common.simion.particle_source import render_standard_beams
from common.contracts.particle_count_policy import validate_positive_particle_count

REPO = Path(__file__).resolve().parents[4]
PROJECT = "rf_multipole_ion_optics"
OPT_IN = "MASS_SPECTROMETRY_RUN_NATIVE_RF_FIELD_CHECKPOINT"

HARNESS = r'''param($Repo,$Python,$SimionExe,$Stamp,$Tag,$Evidence,$SourceRun='')
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Text.UTF8Encoding]::new($false)
. (Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/simion_field_checkpoint_support.ps1')
. (Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
. (Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/simion_layout_template_support.ps1')
if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN){throw 'Native checkpoint fixture requires its own standalone host owner.'}
$artifacts=Join-Path (Split-Path -Parent $Repo) 'artifacts'
$projectArtifacts=Join-Path $artifacts 'projects/rf_multipole_ion_optics'
$reason='Opt-in 9x9x9 fractional N1 exploration: software field/IOB ownership only, no Candidate or scientific qualification.'
$package=$null;$capacity=$null;$lease=$null;$guard=$null;$writersStopped=$true;$terminalPublished=$false;$sealPending=$false
$software=@('SIMION 2020','Python 3.11');$stage='producer_package'
function New-FixturePackage([string]$Suffix){
 New-RunPackage -Python $Python -RepoRoot $Repo -ArtifactRoot $projectArtifacts -RunId ($Stamp+'__test__simion__rf-field-'+$Suffix+'-'+$Tag) `
  -Project rf_multipole_ion_optics -Mode native_field_checkpoint_smoke -Software $software `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $reason -CapacityLedgerLifecycleEnabled `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
}
function Invoke-FixtureNative([string]$Name,[string[]]$Arguments,$Operations,[hashtable]$Environment=@{}){
 $script:writersStopped=$false
 try{
  $native=Invoke-RfSimionPreparationProcess -Name $Name -SimionExe $SimionExe -ArgumentList $Arguments `
   -CandidateDir (Join-Path $package.run_dir 'simion') -RunDir $package.artifact_run_dir `
   -Stdout (Join-Path $package.log_dir ($Name+'.log')) -Stderr (Join-Path $package.log_dir ($Name+'.stderr.log')) -NativeOperations $Operations -Environment $Environment
  $script:writersStopped=$true
  return $native
 }catch{if($_.Exception.Data['simion_wave_writer_completion_confirmed']){$script:writersStopped=$true};throw}
}
function Inspect-FixtureIob([string]$Iob,$Operations){
 $expected=Join-Path $package.input_dir 'toy_iob_expected.lua'
 [IO.File]::WriteAllText($expected,'return {expected_pa_nx=9,expected_pa_ny=9,expected_pa_nz=9,expected_pa_cell_mm=1}',[Text.Encoding]::ASCII)
 $inspector=Join-Path $package.input_dir 'inspect_builtin_quad_reference.lua'
 Copy-VerifiedRunInput -Source (Join-Path $Repo 'projects/rf_multipole_ion_optics/simion/workbench/inspect_builtin_quad_reference.lua') -Destination $inspector|Out-Null
 $config=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs.toy_iob_expected=$expected;$config.inputs.iob_inspector=$inspector
 Write-RunJson -Path $package.run_config -Value $config -Depth 20
 $environment=@{MULTIPOLE_SIMION_RUN_CONFIG_LUA=$expected;RFQUAD_SIMION_REFERENCE_IOB=$Iob;
  RFQUAD_SIMION_REFERENCE_REPORT=(Join-Path $package.result_dir 'iob_readback.txt')}
 $null=Invoke-FixtureNative inspect_runtime_iob @('--nogui','--noprompt','lua',$inspector) $Operations $environment
}
function Publish-FixtureRun($Summary){
 if($null-ne$lease){
  try{Exit-HostResourceStage -Lease $lease;$script:lease=$null}
  catch{$script:writersStopped=$false;throw}
 }
 Write-RunJson -Path $package.summary -Value $Summary -Depth 20
 $retention=Apply-RunArtifactRetention -Python $Python -RepoRoot $Repo -RunConfig $package.run_config
 $paths=@($package.summary,$retention)+@(foreach($folder in @('results','logs','simion')){
  Get-ChildItem (Join-Path $package.artifact_run_dir $folder) -Recurse -File | ForEach-Object{$_.FullName}
 })
 Write-VerifiedRunManifest -Python $Python -RepoRoot $Repo -RunConfig $package.run_config -Status success -Software $software -Outputs $paths -DeferCapacityFinalization
 $script:terminalPublished=$true
 $script:sealPending=$true
 $script:capacity=(Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $capacity -RemainingCommittedNewBytes 0).session
 Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $capacity|Out-Null;$script:capacity=$null
 & $Python -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts --run-config $package.run_config --owner rf_multipole_ion_optics --confirm-writing-stopped --retention-reason $reason
 if($LASTEXITCODE-ne0){throw 'Native fixture stopped payload did not seal.'}
 $script:sealPending=$false
}
try{
 if($SourceRun){$producer=(Resolve-Path -LiteralPath $SourceRun).Path}else{
 $package=New-FixturePackage producer
 $producer=$package.artifact_run_dir
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $artifacts -RunDirectory $producer -CommittedNewBytes 67108864 -ProtectedPaths @($Evidence)
 $lease=Enter-HostResourceStage -Role SIMION -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RunId (Split-Path -Leaf $producer)
 $solver=Join-Path $package.run_dir 'simion'
 $template=Resolve-MultipoleSimionLayoutTemplate -Python $Python -RepositoryRoot $Repo -TemplateDirectory (Join-Path $package.input_dir 'layout_template')
 $gem=Join-Path $solver 'quad_monolithic.gem'
 [IO.File]::WriteAllText($gem,@'
pa_define(9,9,9,planar,non-mirrored,electrostatic,1,surface=fractional)
e(1) { within { box3d(0,0,0,0.8,8,8) } }
e(2) { within { box3d(7.2,0,0,8,8,8) } }
'@,[Text.Encoding]::ASCII)
 $program=Join-Path $package.input_dir 'toy_program.lua'
 [IO.File]::WriteAllText($program,@'
simion.workbench_program()
function segment.initialize() print('CHECKPOINT_PARTICLE_STARTED id='..ion_number) end
function segment.tstep_adjust() ion_time_step=math.min(ion_time_step,0.01) end
function segment.other_actions() if ion_time_of_flight >= 0.1 then ion_splat=-1 end end
function segment.terminate() print('CHECKPOINT_PARTICLE_TERMINAL id='..ion_number..' tof_us='..ion_time_of_flight) end
'@,[Text.Encoding]::ASCII)
 $fly=Join-Path $package.input_dir 'toy_particles.fly2'
 Copy-VerifiedRunInput -Source (Join-Path $Evidence 'toy_particles.fly2') -Destination $fly|Out-Null
 $builder=Join-Path $package.input_dir 'build_simion_runtime_iob.lua'
 Copy-VerifiedRunInput -Source (Join-Path $Repo 'projects/rf_multipole_ion_optics/simion/build_simion_runtime_iob.lua') -Destination $builder|Out-Null
 Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.input_dir 'native_fixture.ps1')|Out-Null
 $identityPath=Join-Path $package.input_dir 'simion_field_identity.json'
 $argv=Get-RfSimionPaBasisArguments
 $identity=New-RfSimionFieldIdentity -GemPath $gem -SimionExe $SimionExe -Grid @(9,9,9) -CellMm @(1,1,1) -ResponseIds @(1,2) -Gem2PaArguments $argv.gem2pa -RefineArguments $argv.refine
 Write-RunJson -Path $identityPath -Value $identity -Depth 20
 $config=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs=@{simion_field_identity=$identityPath;simion_layout_template_iob=$template.iob;simion_layout_template_con=$template.con;toy_program=$program;toy_particles=$fly;builder=$builder;harness=(Join-Path $package.input_dir 'native_fixture.ps1')}
 $config.parameters=@{particle_count=1;exploration=$true;qualification_passed=$false;native_grid=@(9,9,9);surface='fractional'}
 Write-RunJson -Path $package.run_config -Value $config -Depth 20
 $producerOperations=[Collections.Generic.List[object]]::new();$stage='gem2pa_refine';$writersStopped=$false
 try{Initialize-RfSimionPaBasis -SimionExe $SimionExe -CandidateDir $solver -HostLease $lease -NativeOperations $producerOperations;$writersStopped=$true}
 catch{if($_.Exception.Data['simion_wave_writer_completion_confirmed']){$writersStopped=$true};throw}
 $iob=Join-Path $producer 'simion/quad_monolithic.iob'
 $fieldOnly=Write-RfSimionFieldCheckpoint -RunDirectory $producer -IdentityPath $identityPath -IobPath $iob -NativeOperations $producerOperations -Python $Python -RepoRoot $Repo
 $stage='build_runtime_iob'
 Copy-VerifiedRunInput -Source $template.iob -Destination (Join-Path $solver 'quad_monolithic.iob')|Out-Null
 Copy-VerifiedRunInput -Source $template.con -Destination (Join-Path $solver 'quad_monolithic.con')|Out-Null
 # Build only the small IOB; argument four binds the permanent original PA0.
 $null=Invoke-FixtureNative build_runtime_iob @('--nogui','--noprompt','lua',$builder,$iob,$program,$fly,(Join-Path $producer 'simion/quad_monolithic.pa0')) $producerOperations
 Inspect-FixtureIob $iob $producerOperations
 $checkpoint=Write-RfSimionFieldCheckpoint -RunDirectory $producer -IdentityPath $identityPath -IobPath $iob -NativeOperations $producerOperations -Python $Python -RepoRoot $Repo
 if(@($producerOperations|Where-Object operation_id -eq refine).Count-ne1){throw 'Producer did not perform exactly one Refine.'}
 Publish-FixtureRun @{schema_version=1;role='rf_native_field_checkpoint_smoke';status='success';stage='producer_sealed';refine_count=1;particle_count=1;exploration=$true;scientific_qualification=$false}
 $alias=$package.execution_alias;Remove-RunPackageExecutionAlias -Package $package
 if(Test-Path -LiteralPath $alias){throw 'Producer execution alias survived cleanup.'}
 }
 $parentManifest=Join-Path $producer 'run_manifest.json';$parentBytes=[IO.File]::ReadAllBytes($parentManifest)
 # These are permanent run paths, not the disposed execution alias.
 $parentPublished=Get-Content (Join-Path $producer 'run_manifest.json') -Raw|ConvertFrom-Json
 $producerIdentity=[string]$parentPublished.inputs.simion_field_identity.path
 $producerProgram=[string]$parentPublished.inputs.toy_program.path
 $templateIob=[string]$parentPublished.inputs.simion_layout_template_iob.path
 $templateCon=[string]$parentPublished.inputs.simion_layout_template_con.path
 $package=New-FixturePackage consumer;$terminalPublished=$false;$child=$package.artifact_run_dir;$stage='read_protected_checkpoint'
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $artifacts -RunDirectory $child -CommittedNewBytes 67108864 -ProtectedPaths @($producer,$Evidence)
 $lease=Enter-HostResourceStage -Role SIMION -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RunId (Split-Path -Leaf $child)
 $plan=Read-RfSimionFieldCheckpoint -SourceRunPath $producer -IdentityPath $producerIdentity -ProgramSourcePath $producerProgram -TemplateIobPath $templateIob -TemplateConPath $templateCon -Python $Python -RepoRoot $Repo
 $capacity=(Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $capacity -ProtectedPaths @($plan.protected_paths)).session
 $guard=Protect-RfSimionFieldCheckpoint -Checkpoint $plan
 if($guard.pa_records.Count-ne5){throw 'Original fractional family inventory differs.'}
 foreach($record in $guard.pa_records){
  $blocked=$false;try{$writer=[IO.File]::Open($record.path,'Open','Write','ReadWrite');$writer.Dispose()}catch{$blocked=$true}
  if(-not$blocked){throw 'Producer PA remained writable during consumption.'}
 }
 $config=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs=@{simion_field_checkpoint=$plan.checkpoint_path;simion_field_producer_manifest=$plan.producer_manifest;simion_field_identity=$producerIdentity}
 $config.parameters=@{particle_count=1;exploration=$true;qualification_passed=$false;source_run=$producer;refine_count=0}
 Write-RunJson -Path $package.run_config -Value $config -Depth 20
 $childOperations=[Collections.Generic.List[object]]::new()
 $activeIob=[string]$plan.iob_path
 # This fixture deliberately changes its source and adds native diagnostics and
 # a tiny-grid integration step cap. Always own a child layout/Program, even
 # when the immutable producer layout itself is already reusable. No Refine.
  $activeIob=Join-Path $child 'simion/quad_monolithic.iob'
  $layout=Resolve-MultipoleSimionLayoutTemplate -Python $Python -RepositoryRoot $Repo -TemplateDirectory (Join-Path $package.input_dir 'layout_template')
  if((Get-FileHash -LiteralPath $layout.iob -Algorithm SHA256).Hash-ne$parentPublished.inputs.simion_layout_template_iob.sha256-or
     (Get-FileHash -LiteralPath $layout.con -Algorithm SHA256).Hash-ne$parentPublished.inputs.simion_layout_template_con.sha256){throw 'Native fixture template differs from its declared producer.'}
  Copy-VerifiedRunInput -Source $templateIob -Destination $activeIob|Out-Null
  Copy-VerifiedRunInput -Source $templateCon -Destination ([IO.Path]::ChangeExtension($activeIob,'.con'))|Out-Null
  $builder=Join-Path $package.input_dir 'build_simion_runtime_iob.lua'
  Copy-VerifiedRunInput -Source (Join-Path $Repo 'projects/rf_multipole_ion_optics/simion/build_simion_runtime_iob.lua') -Destination $builder|Out-Null
  $config.inputs.iob_builder=$builder
  $config.inputs.template_seed_pa0=$layout.placeholder_pa0
  $config.inputs.template_seed_registration=$layout.registration_manifest
  Write-RunJson -Path $package.run_config -Value $config -Depth 20
  $sourceFly=Join-Path $package.input_dir 'consumer_particles.fly2'
  Copy-VerifiedRunInput -Source (Join-Path $Evidence 'toy_particles.fly2') -Destination $sourceFly|Out-Null
  $config.inputs.consumer_particles=$sourceFly
  Write-RunJson -Path $package.run_config -Value $config -Depth 20
  $stage='rebind_only_layout'
  $seed=New-RfSimionLayoutSeedCompanion -IobPath $activeIob -SeedPaPath $layout.placeholder_pa0
  $null=Invoke-FixtureNative build_runtime_iob @('--nogui','--noprompt','lua',$builder,$activeIob,$producerProgram,$sourceFly,[string]$plan.controller_path) $childOperations
  $build=@($childOperations|Where-Object operation_id -eq build_runtime_iob)[-1]
  Remove-RfSimionLayoutSeedCompanion -Companion $seed -BuildObservation $build.observation
  Inspect-FixtureIob $activeIob $childOperations
 # Obtain the absolute source from the loaded native instance, including its
 # origin offsets. Orientation vectors alone do not specify a WB position.
 $probe=Join-Path $package.input_dir 'probe_source.lua'
 $sourceReport=Join-Path $package.result_dir 'source_position.csv'
 [IO.File]::WriteAllText($probe,@'
simion.command('"'..assert(os.getenv('CHECKPOINT_IOB'))..'"')
local instance=assert(simion.wb.instances[1])
assert(not instance.pa:electrode(4,4,4),'toy source is in electrode')
local x,y,z=instance:pa_to_wb_coords(4,4,4)
local b=simion.wb.bounds
print(string.format('WB_BOUNDS=%.17g,%.17g,%.17g,%.17g,%.17g,%.17g',b.xl,b.yl,b.zl,b.xr,b.yr,b.zr))
assert(x>b.xl and x<b.xr and y>b.yl and y<b.yr and z>b.zl and z<b.zr,'source outside native WB bounds')
local f=assert(io.open(assert(os.getenv('CHECKPOINT_SOURCE_REPORT')),'w'))
f:write(string.format('%.17g,%.17g,%.17g\n',x,y,z));f:close()
print(string.format('SOURCE_PA=4,4,4 SOURCE_WB=%.17g,%.17g,%.17g ORIGIN=%.17g,%.17g,%.17g',x,y,z,instance.ox,instance.oy,instance.oz))
local child=assert(os.getenv('CHECKPOINT_CHILD_IOB'))
assert(child==assert(os.getenv('CHECKPOINT_IOB')),'diagnostics require child IOB')
local program=assert(io.open(child:gsub('%.iob$','.lua'),'a'))
program:write('\n')
program:write([[
local prior_initialize=segment.initialize
function segment.initialize()
  prior_initialize()
  print('CHECKPOINT_NATIVE_STATE instance='..tostring(ion_instance)..' splat='..tostring(ion_splat)..' xyz='..ion_px_mm..','..ion_py_mm..','..ion_pz_mm)
end
-- 1 mm cells, 100 u at 0.1 eV: speed ~0.439 mm/us. This exploration
-- cap advances ~0.0044 mm per step and does not change production defaults.
function segment.tstep_adjust() ion_time_step=math.min(ion_time_step,0.01) end
]])
program:close()
'@,[Text.Encoding]::ASCII)
 $config.inputs.source_probe=$probe
 Write-RunJson -Path $package.run_config -Value $config -Depth 20
 $stage='native_source_position'
 $null=Invoke-FixtureNative probe_source @('--nogui','--noprompt','lua',$probe) $childOperations @{CHECKPOINT_IOB=$activeIob;CHECKPOINT_CHILD_IOB=(Join-Path $child 'simion/quad_monolithic.iob');CHECKPOINT_SOURCE_REPORT=$sourceReport}
 $sourceFly=Join-Path $package.input_dir 'native_position_particles.fly2'
 & $Python -c 'import sys;from pathlib import Path;from common.simion.particle_source import render_standard_beams;x,y,z=map(float,Path(sys.argv[1]).read_text().strip().split(","));Path(sys.argv[2]).write_text(render_standard_beams([dict(tob=0,mass=100,charge=1,x=x,y=y,z=z,direction=(1,0,0),ke=.1,cwf=1,color=1)]),encoding="ascii")' $sourceReport $sourceFly
 if($LASTEXITCODE-ne0){throw 'Native source projection failed.'}
 $config.inputs.consumer_native_particles=$sourceFly
 Write-RunJson -Path $package.run_config -Value $config -Depth 20
 $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
 $stage='fly_after_alias_removal'
 $null=Invoke-FixtureNative fly @('--nogui','--noprompt','fly','--particles',$sourceFly,'--programs','1','--retain-trajectories','0',$activeIob) $childOperations
 $flyLog=Join-Path $package.log_dir 'fly.log'
 & $Python -c 'import re,sys;from pathlib import Path;from common.simion.native_completion import require_one_fly_completion;text=Path(sys.argv[1]).read_text(encoding="utf-8-sig");assert require_one_fly_completion(text.splitlines()).splats==1;hit=re.search(r"CHECKPOINT_PARTICLE_TERMINAL id=1 tof_us=([0-9.eE+-]+)",text);assert hit and float(hit.group(1))>0' $flyLog
 if($LASTEXITCODE-ne0-or(Get-Content $flyLog -Raw)-notmatch'CHECKPOINT_PARTICLE_STARTED id=1'){throw 'Native N1 Fly completion/Program evidence missing.'}
 if(@($childOperations|Where-Object operation_id -eq refine).Count){throw 'Checkpoint reuse performed Refine.'}
 if([Convert]::ToBase64String($parentBytes)-cne[Convert]::ToBase64String([IO.File]::ReadAllBytes($parentManifest))){throw 'Consumption changed parent terminal manifest bytes.'}
 Publish-FixtureRun @{schema_version=1;role='rf_native_field_checkpoint_smoke';status='success';stage='consumer_sealed';refine_count=0;producer_refine_count=1;source_run=$producer;particle_count=1;exploration=$true;scientific_qualification=$false;parent_manifest_bytes_unchanged=$true;producer_alias_removed=$true;original_iob_reused=$false;child_layout_reason='fixture source, diagnostic Program and 0.01 us timestep cap';pa_write_blocked=$true}
 Close-RfSimionFieldCheckpointGuard -Context $guard;$guard=$null
 Remove-RunPackageExecutionAlias -Package $package
 Write-RunJson -Path (Join-Path $Evidence 'result.json') -Value @{status='PASS';producer=$producer;consumer=$child;refine_initial=1;refine_reuse=0;particle_count=1;exploration=$true;scientific_qualification=$false} -Depth 10
}catch{
 $primaryFailure=$_
 Write-Output "RF_NATIVE_CHECKPOINT=FAILED STAGE=$stage WRITERS_STOPPED=$writersStopped REASON=$($_.Exception.Message)"
 if($writersStopped-and$null-ne$package-and-not$terminalPublished){
  try{Complete-FailedRun -Python $Python -RepoRoot $Repo -RunConfig $package.run_config -Summary $package.summary -SummaryRole rf_native_field_checkpoint_smoke -Reason $primaryFailure.Exception.Message -Software $software -Status failed -FailureStage $stage -DeferCapacityFinalization;$terminalPublished=$true;$sealPending=$true}
  catch{$primaryFailure.Exception.Data['fixture_closeout_error']=$_.Exception.Message;Write-Warning "Native fixture closeout also failed: $_"}
 }
 throw $primaryFailure
}finally{
 if($writersStopped){
  if($null-ne$guard){Close-RfSimionFieldCheckpointGuard -Context $guard}
  if($null-ne$lease){Exit-HostResourceStage -Lease $lease}
  if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $capacity|Out-Null}
  if($sealPending-and$null-ne$package){
   & $Python -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts --run-config (Join-Path $package.artifact_run_dir 'run_config.json') --owner rf_multipole_ion_optics --confirm-writing-stopped --retention-reason $reason
   if($LASTEXITCODE-ne0){throw 'Native fixture final stopped payload sealing failed.'}
  }
  if($null-ne$package){Remove-RunPackageExecutionAlias -Package $package}
 }
}
'''


@unittest.skipUnless(os.name == "nt" and os.environ.get(OPT_IN) == "1",
                     "opt-in Windows SIMION N1 software exploration; excluded from L1/L2")
class NativeFieldCheckpointTests(unittest.TestCase):
    def test_fractional_field_survives_alias_cleanup_and_reuses_without_refine(self) -> None:
        validate_positive_particle_count(1)  # Explicit exploration, not a standard cohort.
        pwsh = shutil.which("pwsh")
        self.assertIsNotNone(pwsh, "PowerShell 7 is required")
        simion = Path(os.environ.get("SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe"))
        self.assertTrue(simion.is_file(), "SIMION 2020 is required for this explicit native test")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = uuid.uuid4().hex[:8]
        evidence = REPO.parent / "artifacts/projects" / PROJECT / "scratch/native_field_checkpoint" / (stamp + "_" + tag)
        evidence.mkdir(parents=True)
        script = evidence / "execute.ps1"
        script.write_text(HARNESS, encoding="utf-8", newline="\n")
        (evidence / "toy_particles.fly2").write_text(render_standard_beams([
            # Placeholder for IOB construction; Fly uses native-probed coordinates.
            dict(tob=0, mass=100, charge=1, x=4, y=-4, z=4, direction=(1, 0, 0), ke=.1, cwf=1, color=1),
        ]), encoding="ascii", newline="\n")
        result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO), sys.executable,
                                 str(simion), stamp, tag, str(evidence),
                                 os.environ.get("MASS_SPECTROMETRY_NATIVE_RF_FIELD_CHECKPOINT_SOURCE", "")], cwd=REPO,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=None)
        (evidence / "console.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-12000:])
        report = json.loads((evidence / "result.json").read_text(encoding="utf-8-sig"))
        self.assertEqual((report["status"], report["refine_initial"], report["refine_reuse"]), ("PASS", 1, 0))
        self.assertTrue(report["exploration"])
        self.assertFalse(report["scientific_qualification"])
        print("RF_NATIVE_CHECKPOINT_EVIDENCE=" + str(evidence), flush=True)


if __name__ == "__main__":
    unittest.main()
