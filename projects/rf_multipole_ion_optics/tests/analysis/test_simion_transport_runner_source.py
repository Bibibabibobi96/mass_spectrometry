from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.capacity_ledger import initialize_capacity_ledger
from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from projects.rf_multipole_ion_optics.runtime.particle_source_preflight import COLUMNS
from projects.rf_multipole_ion_optics.analysis.verify_resolved_design import verify as verify_resolved_design
from projects.rf_multipole_ion_optics.workflows.interface_readiness.particle_source_policy import (
    generate_interface_bundle as generate_bundle,
)
from projects.rf_multipole_ion_optics.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
MASS_RUNNER = (
    PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_simion.ps1"
)
RUN_CONFIG_CONTRACT = PROJECT_ROOT / "runtime" / "simion_run_config.ps1"
SHARED_LUA = REPO_ROOT / "projects/rf_multipole_ion_optics/simion/simion_transport.lua"
EXECUTION_PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"
RESOLVED = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "resolved_design_official.json"
SOURCE_FAMILY = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "interface_readiness_particle_source.json"
INTERFACE_CONTRACT = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "interface_contract.json"
SOLVER_NUMERICS = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "simion_solver_numerics.json"


def write_canonical_source(path: Path) -> None:
    resolved = json.loads(RESOLVED.read_text(encoding="utf-8"))
    speed = math.sqrt(2.0 * 2.0 * ELEMENTARY_CHARGE_C / (100.0 * AMU_KG))
    vx, vy = 100.0, -50.0
    vz = math.sqrt(speed * speed - vx * vx - vy * vy)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for particle_id in range(1, 101):
            writer.writerow(
                {
                    "particle_id": particle_id,
                    "birth_time_s": 0,
                    "x_mm": 0.1,
                    "y_mm": -0.2,
                    "z_mm": resolved["interfaces_mm"]["entrance"][
                        "release_plane_z_mm"
                    ],
                    "vx_m_s": format(vx, ".17g"),
                    "vy_m_s": format(vy, ".17g"),
                    "vz_m_s": format(vz, ".17g"),
                    "mass_amu": 100,
                    "charge_state": 1,
                }
            )


class SimionTransportRunnerSourceTests(unittest.TestCase):
    def test_preparation_completion_never_turns_unknown_descendants_into_stopped(self) -> None:
        script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
function Invoke-ResourceBudgetedProcess {
 param($Limits)
 if($null-ne$Limits){throw 'Invented project limits'}
 if($scenario-eq'observation_failure'){$error=[Exception]::new('observation-failed');$error.Data['observed_process_exit_confirmed']=$true;throw $error}
 [pscustomobject]@{exit_code=$(if($scenario-eq'nonzero'){7}else{0});resource_budget_exceeded=($scenario-eq'danger');root_process_id=44;root_process_started_at_utc_ticks=123}
}
foreach($scenario in @('success','nonzero','observation_failure','danger')){
 $operations=[Collections.Generic.List[object]]::new();$caught=$null
 try{$null=Invoke-RfSimionPreparationProcess -Name refine -SimionExe fixture -ArgumentList @('refine') -CandidateDir $env:RF_TEST_TEMP `
  -RunDir $env:RF_TEST_TEMP -Stdout (Join-Path $env:RF_TEST_TEMP 'stdout.txt') -Stderr (Join-Path $env:RF_TEST_TEMP 'stderr.txt') -NativeOperations $operations}
 catch{$caught=$_}
 if($scenario-eq'success'){if($caught-or-not$operations[0].observation.exit_confirmed-or$operations[0].observation.returncode-ne0){throw 'Natural completion lost'};continue}
 if($null-eq$caught){throw 'Failure was hidden'}
 if($scenario-eq'nonzero'){if(-not$caught.Exception.Data['simion_wave_writer_completion_confirmed']-or$operations[0].observation.returncode-ne7){throw 'Known failure facts lost'}}
 else{if($caught.Exception.Data['simion_wave_writer_completion_confirmed']-ne$false-or$operations[0].observation.exit_confirmed){throw 'Unknown writer was sealed'}}
 if($scenario-eq'observation_failure'-and$caught.Exception.Message-cne'observation-failed'){throw 'Original observation exception was replaced'}
}
'PREPARATION_OWNER=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                env={**os.environ, "RF_TEST_TEMP": directory}, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PREPARATION_OWNER=PASS", result.stdout)

    def test_prepared_identity_and_mass_analysis_consume_resolved_radian_phase(self) -> None:
        from projects.rf_multipole_ion_optics.core.compile_design_request import resolved_design_sha256
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolved = json.loads((PROJECT_ROOT / "variants/quadrupole/config/resolved_design_mass_filter.json").read_text(encoding="utf-8"))
            resolved["drive"]["phase_rad"] = 0.37
            resolved["resolved_sha256"] = resolved_design_sha256(resolved)
            (root / "resolved.json").write_text(json.dumps(resolved), encoding="utf-8")
            script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/contracts/run_artifact_support.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_run_config.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
$r=Get-Content (Join-Path $env:RF_TEST_TEMP 'resolved.json') -Raw|ConvertFrom-Json
$i=Get-Content 'projects/rf_multipole_ion_optics/variants/quadrupole/config/interface_contract.json' -Raw|ConvertFrom-Json
$n=Get-Content 'projects/rf_multipole_ion_optics/variants/quadrupole/config/simion_solver_numerics.json' -Raw|ConvertFrom-Json
$coreConfig=New-RfSimionCoreRunConfig -ResolvedDesign $r -InterfaceContract $i -SolverNumerics $n `
 -RfStepsPerPeriod $n.baseline_rf_steps_per_period -TrajectoryQuality $n.trajectory_quality -ModeName mass_filter_reference `
 -OperatingPoint mass_filter_reference -IobPath 'C:\fixture\a.iob' -Fly2Path 'C:\fixture\a.fly2' `
 -SourceStatesLua 'C:\fixture\source.lua' -ParticleStateCsv 'C:\fixture\state.csv' -TrajectoryCsv 'C:\fixture\trajectory.csv' -SummaryJson 'C:\fixture\summary.json'
if($coreConfig.phase_rad-ne0.37-or$coreConfig.Contains('phase_deg')){throw 'Core radian authority differs'}
$program='projects/rf_multipole_ion_optics/simion/simion_transport.lua'
$source=@{files=@(@{relative_path='fixture.py';sha256=('A'*64)})}
$one=Join-Path $env:RF_TEST_TEMP 'one.json';$two=Join-Path $env:RF_TEST_TEMP 'two.json';$three=Join-Path $env:RF_TEST_TEMP 'three.json'
Write-RfSimionPreparedFlyIdentity -CoreConfig $coreConfig -Path $one -CaseName fixture -SourcePackage $source -SourceRelativePaths fixture.py -ProgramSourcePath $program -NativeFlyArguments @(Get-RfSimionFlyArgumentIdentity -CoreConfig $coreConfig)
$coreConfig.iob='C:\other\a.iob';$coreConfig.particle_state_csv='C:\other\state.csv'
Write-RfSimionPreparedFlyIdentity -CoreConfig $coreConfig -Path $two -CaseName fixture -SourcePackage $source -SourceRelativePaths fixture.py -ProgramSourcePath $program -NativeFlyArguments @(Get-RfSimionFlyArgumentIdentity -CoreConfig $coreConfig)
if((Get-Content $one -Raw)-cne(Get-Content $two -Raw)){throw 'Owner output location invalidated Fly'}
$lua=ConvertTo-RfSimionLuaConfig -CoreConfig $coreConfig -SharedProgramPath $program
if(-not$lua.Contains('phase_rad=0.37,')){throw 'Lua converted radians a second time'}
function Invoke-TestParticleState {
 $index=[array]::IndexOf($args,'--phase-rad')
 if($index-lt0-or[double]$args[$index+1]-ne0.37){throw 'Analysis did not receive the same radian phase'}
 $global:LASTEXITCODE=0
}
$python='Invoke-TestParticleState';$particleStateCsv='state';$particlePath='particles';$frozenInterface='interface';$stateContractReport='report'
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'projects/rf_multipole_ion_optics/workflows/mass_filter_reference/run_simion.ps1'),[ref]$null,[ref]$null)
$command=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.CommandAst]-and$node.Extent.Text.Contains('-m common.contracts.particle_state')},$true))
if($command.Count-ne1){throw 'Missing mass-analysis boundary'}
. ([scriptblock]::Create($command[0].Extent.Text))
$coreConfig.phase_rad=0.38
Write-RfSimionPreparedFlyIdentity -CoreConfig $coreConfig -Path $three -CaseName fixture -SourcePackage $source -SourceRelativePaths fixture.py -ProgramSourcePath $program -NativeFlyArguments @(Get-RfSimionFlyArgumentIdentity -CoreConfig $coreConfig)
if((Get-Content $two -Raw)-ceq(Get-Content $three -Raw)){throw 'Physical phase change was ignored'}
'RADIAN_AUTHORITY=PASS'
"""
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                env={**os.environ, "RF_TEST_TEMP": directory}, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RADIAN_AUTHORITY=PASS", result.stdout)

    def test_both_prepared_clis_bind_explicit_predecessor_to_shared_recovery(self) -> None:
        script = r"""
$ErrorActionPreference='Stop'
$script:calls=0
function Initialize-RfSimionPreparedContinuation {
 param($ManifestPath,$RunDir,$CaseName,$InputNames,$BatchPlanPath,$DispatchPlanPath)
 if($ManifestPath-cne'parent/run_manifest.json'-or$RunDir-cne$env:RF_TEST_TEMP){throw 'Wrong predecessor or physical owner'}
 foreach($name in @('resolved_design','particle_table','simion_program_source','simion_rf_drive_kernel','simion_iob_builder','simion_gem','simion_fly2','source_states')){
  if($name-cnotin$InputNames){throw "Missing physical identity: $name"}
 }
 if(@($InputNames|Where-Object{$_-in@('mode','interface_contract','numerical_contract')}).Count){throw 'Whole analysis contracts invalidate effective Fly projection'}
 if($CaseName-cnotin@('interface_readiness','mass_filter_reference')){throw 'Wrong case'}
 $script:calls++
 @{batch_count=2}|ConvertTo-Json|Set-Content $BatchPlanPath
 @{estimation=@{kind='exact_resource_profile'}}|ConvertTo-Json -Depth 5|Set-Content $DispatchPlanPath
 [pscustomobject]@{all_reused=$true;units=@{}}
}
$ContinuationPredecessorManifestPath='parent/run_manifest.json';$package=@{artifact_run_dir=$env:RF_TEST_TEMP}
$artifactRoot=Join-Path $env:RF_TEST_TEMP 'artifacts/projects/rf_multipole_ion_optics'
$python='unused';$repoRoot=$PWD;$runConfig=@{};$runConfigPath='unused';$runDir='alias'
$batchPlan=Join-Path $env:RF_TEST_TEMP 'batches.json';$dispatchPlan=Join-Path $env:RF_TEST_TEMP 'dispatch.json'
foreach($runner in @('workflows/interface_readiness/run_simion.ps1','workflows/mass_filter_reference/run_simion.ps1')){
 $path=Join-Path $PWD ('projects/rf_multipole_ion_optics/'+$runner)
 $command=Get-Command $path
 if($null-eq$command.Parameters['ContinuationPredecessorManifestPath']){throw 'Missing public CLI predecessor'}
 $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$null,[ref]$null)
 $bindings=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.IfStatementAst]-and
  $n.Extent.Text.StartsWith('if($ContinuationPredecessorManifestPath)')},$true))
 if($bindings.Count-ne1){throw 'Recovery has no unique normal-entry binding'}
 . ([scriptblock]::Create($bindings[0].Extent.Text))
 if(-not$continuation.all_reused-or$batchPlanDocument.batch_count-ne2){throw 'CLI did not use recovered partition'}
}
if($script:calls-ne2){throw 'Shared recovery not called'}
'CLI_RECOVERY=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                env={**os.environ, "RF_TEST_TEMP": directory}, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CLI_RECOVERY=PASS", result.stdout)

    def test_prepared_wave_full_and_partial_reuse_preserve_native_units(self) -> None:
        script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/contracts/run_artifact_support.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
function Initialize-RfSimionPaBasis {if($script:fieldReady){throw 'Completed field was refined again'};$script:pa++}
function Initialize-RfSimionPreparedBatch {if($script:fieldReady){throw 'Prepared IOB was rebuilt'};$script:iob++}
function Update-HostResourceStage {param($Lease) $Lease}
function Get-HostResourceBudget {@{}}
function Invoke-ResourceBudgetedProcesses {
 param($ProcessSpecifications,$OnProcessCompleted)
 $records=@()
 foreach($spec in $ProcessSpecifications){
  $script:launched.Add($spec.name)
  $record=[pscustomobject]@{name=$spec.name;specification=$spec;exit_code=$(if($script:failNative){7}else{0})}
  & $OnProcessCompleted $record
  $records+=$record
 }
 [pscustomobject]@{resource_budget_exceeded=$false;processes=$records}
}
foreach($scenario in @('full','partial','prepared_partial','failed')){
 $full=$scenario-eq'full';$script:failNative=$scenario-eq'failed'
 $script:fieldReady=$scenario-eq'prepared_partial'
 $root=Join-Path $env:RF_TEST_TEMP $scenario
 $current=Join-Path $root 'child';$parent=Join-Path $root 'parent'
 New-Item -ItemType Directory -Force -Path (Join-Path $current 'results'),(Join-Path $current 'logs'),(Join-Path $parent 'results')|Out-Null
 $batches=@();$units=@{};$script:pa=0;$script:iob=0;$script:launched=[Collections.Generic.List[string]]::new()
 foreach($index in @(1,2)){
  $state=Join-Path $current ('results/particle_state__batch_{0:D2}.csv'-f$index)
  $summary=Join-Path $current ('results/solver_summary__batch_{0:D2}.json'-f$index)
  $log=Join-Path $current ('logs/batch_{0:D2}'-f$index);New-Item -ItemType Directory -Force -Path $log|Out-Null
  "particle_id,event`n1,terminal"|Set-Content $state
  @{solver='SIMION';particles=1;census_plane_crossings=1;hits=1;mode='fixture';operating_point='fixture';parent_resolved_design_sha256='same'}|ConvertTo-Json|Set-Content $summary
  'status,Fly completed. 1 splats, 0.1 seconds'|Set-Content (Join-Path $log 'simion_stdout.txt')
  $batch=[pscustomobject]@{index=$index;particle_id_min=$index;particle_id_max=$index;simion_particle_id_offset=$index-1;count=1}
  $batches += [pscustomobject]@{name="batch_$index";batch=$batch;config=@{iob='unused';fly2='unused';trajectory_quality=1;rf_steps_per_period=1};
   state=$state;summary=$summary;trajectory='unused';lua='unused';log_dir=$log;
   merged_state=(Join-Path $current 'results/particle_state.csv');merged_trajectory='unused';merged_summary=(Join-Path $current 'results/solver_summary.json')}
  if($full-or$index-eq1){
   $oldState=Join-Path $parent ('results/particle_state__batch_{0:D2}.csv'-f$index)
   $oldSummary=Join-Path $parent ('results/solver_summary__batch_{0:D2}.json'-f$index)
   Copy-Item $state $oldState;Copy-Item $summary $oldSummary
   $units[('fixture.batch_{0:D2}'-f$index)]=@{terminal_outputs=@(@{path=$oldState},@{path=$oldSummary})}
  }
 }
 $plan=Join-Path $current 'plan.json'
 @{dispatch='single_wave_parallel';particle_count=2;batch_count=2;batches=@($batches|ForEach-Object{$_.batch})}|ConvertTo-Json -Depth 8|Set-Content $plan
 $completed=[Collections.Generic.List[string]]::new()
 $caught=$false
 try{$result=Invoke-RfSimionParticleBatchWave -HostLease @{} -SimionExe 'never-launch' -CandidateDir $current `
  -IobPath unused -RootFly2Path unused -IobBuilderScript unused -ProgramSourcePath unused -RootRunConfigLua unused `
  -InspectScript unused -IobReport unused -LogDir (Join-Path $current 'logs') -TrajectoryQuality 1 -RfStepsPerPeriod 1 `
  -BatchRuns $batches -BatchPlanPath $plan -DispatchPlanPath 'unused' -RunDir $current -UsagePath unused `
  -PythonExe $env:RF_TEST_PYTHON -RepositoryRoot $PWD -CaseName fixture -ContinuationUnits $units -CompletionOutputs $completed -RfDriveKernelPath unused -Prepared:$script:fieldReady
 }catch{if(-not$script:failNative-or-not$_.Exception.Message.Contains('batch wave failed')){throw};$caught=$true}
 if($script:failNative){if(-not$caught-or$completed.Count){throw 'Failed native unit was accepted'};continue}
 if($full){if($script:pa-or$script:iob-or$script:launched.Count-or$completed.Count){throw 'Full reuse performed native work'}}
 else{$expectedBuilds=if($script:fieldReady){0}else{1};if($script:pa-ne$expectedBuilds-or$script:iob-ne$expectedBuilds-or($script:launched-join',')-cne'batch_2'){throw 'Partial recovery replayed a complete unit or rebuilt its field'}
  if(-not(Test-Path (Join-Path $current 'results/simion_batch_completion__fixture__batch_02.json'))){throw 'Missing durable completion receipt'}}
 $ids=@(Import-Csv (Join-Path $current 'results/particle_state.csv')|ForEach-Object{[int]$_.particle_id})
 if(($ids-join',')-cne'1,2'){throw 'Original mother IDs lost'}
}
'PREPARED_REUSE=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                env={**os.environ, "RF_TEST_TEMP": directory, "RF_TEST_PYTHON": sys.executable},
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PREPARED_REUSE=PASS", result.stdout)

    def test_particle_wave_dispatches_through_shared_batch_phase(self) -> None:
        support = PROJECT_ROOT / "runtime/simion_execution.ps1"
        script = r"""
$ErrorActionPreference='Stop'
. $env:RF_EXECUTION_SUPPORT
function New-RfSimionFlyProcessSpecification {param($Name) [pscustomobject]@{name=$Name}}
function Invoke-FixturePython {$global:LASTEXITCODE=0}
function Invoke-SimionBatchPhase {
 param($PrepareRemaining,$FirstSpecification,$Replan)
 $formal=if($FirstSpecification){[pscustomobject]@{process_record=@{name='first';specification=@{name='first'}}}}else{$null}
 $prepared=& $PrepareRemaining $formal
 $expected=if($formal){1}else{2}
 if(@($prepared.pending).Count-ne$expected){throw 'wrong pending specification count'}
 if($formal-and$prepared.pending[0].name-ne'second'){throw 'formal first worker was dispatched twice'}
 return [pscustomobject]@{prepared=$prepared;resource_budget_exceeded=$false;processes=@()}
}
function New-Batch($name,$offset) {
 [pscustomobject]@{name=$name;config=@{iob='iob';fly2='fly';trajectory_quality=1;rf_steps_per_period=1};
  lua='lua';log_dir='log';merged_state='merged-state';merged_trajectory='merged-trajectory';merged_summary='merged-summary';
  state='state';trajectory='trajectory';summary='summary';batch=@{simion_particle_id_offset=$offset}}
}
$batches=@((New-Batch 'first' 0),(New-Batch 'second' 1))
$arguments=@{HostLease=@{};SimionExe='simion';CandidateDir=$PWD;IobPath='iob';RootFly2Path='fly';
 IobBuilderScript='builder';ProgramSourcePath='program';RootRunConfigLua='config';InspectScript='inspect';
 IobReport='report';LogDir='log';TrajectoryQuality=1;RfStepsPerPeriod=1;BatchRuns=$batches;
 BatchPlanPath='plan';DispatchPlanPath='dispatch';RunDir=$PWD;UsagePath='usage';
 PythonExe='Invoke-FixturePython';RepositoryRoot=$PWD;Prepared=$true}
$null=Invoke-RfSimionParticleBatchWave @arguments
$arguments.FirstSpecification=@{name='first'};$arguments.Replan={};$arguments.PrepareAfterObservation={param($formal) $batches}
$null=Invoke-RfSimionParticleBatchWave @arguments
"""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=REPO_ROOT, env={**os.environ, "RF_EXECUTION_SUPPORT": str(support)},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_adaptive_wave_retains_first_batch_and_failure_inventory(self) -> None:
        """Execute the shared lifecycle with native work replaced at its boundary."""
        support = PROJECT_ROOT / "runtime/simion_execution.ps1"
        script = r"""
$ErrorActionPreference='Stop'
. $env:RF_EXECUTION_SUPPORT
. (Join-Path $PWD 'common/resource_budget_support.ps1')
function Initialize-RfSimionPaBasis { if($prebuilt){throw 'Prepared PA rebuilt'}; "PA build diagnostics" }
function Initialize-RfSimionPreparedBatch { if($prebuilt){throw 'Prepared IOB rebuilt'}; "IOB build diagnostics" }
function New-RfSimionFlyProcessSpecification { return @{name='first'} }
function Start-ObservedFormalProcess {
 $script:events+='observe'; return @{process_record=[pscustomobject]@{name='first';completed=$false};resource_budget_exceeded=$false}
}
function Invoke-ObservedPreparationFailureDrain {param($Failure) $script:events+='drain'; throw $Failure}
function Update-RfSimionDispatchAfterFormalObservation {
 $script:events+='replan'
 if($fail-eq'replan'){throw 'replan-failed'}
 return @{batches=@{batch_count=2}}
}
function Invoke-RfSimionParticleBatchWave {
 param($BatchRuns,$FirstSpecification,$Replan,$PrepareAfterObservation,[switch]$Prepared,$DispatchPlanPath,$RunDir,$UsagePath)
 if($unknown-and(-not$Prepared-or$null-eq$FirstSpecification)){throw 'first batch lost'}
 if(-not$unknown-and($null-ne$FirstSpecification-or([bool]$Prepared-ne[bool]$prebuilt))){throw 'unexpected observed batch'}
 $prepare={param($formal) if($formal-and@(& $PrepareAfterObservation $formal).Count-ne2){throw 'replanned batch inventory lost'};[pscustomobject]@{pending=@('pending')}}
 $null=Invoke-SimionBatchPhase -DispatchPlanPath $DispatchPlanPath -RunDir $RunDir -UsagePath $UsagePath `
  -PrepareRemaining $prepare -FirstSpecification $FirstSpecification -Replan $Replan
 return @{ok=$true}
}
function Invoke-ResourceBudgetedProcesses {
 param($ExistingProcessRecords=@())
 $script:events+='wave'
 if($unknown-and($ExistingProcessRecords.Count-ne1-or$ExistingProcessRecords[0].name-ne'first')){throw 'first batch lost'}
 if($fail-eq'wave'){throw 'wave-failed'}
 return @{resource_budget_exceeded=$false;processes=@()}
}
function Update-HostResourceStage { param($Stage) $script:events+=$Stage; return @{token='same'} }
function Get-HostResourceBudget { return @{} }
function Complete-ResourceUsage { $script:events+='usage' }
function Invoke-FixturePython { $script:events+='publish'; $global:LASTEXITCODE=0; 'profile publication diagnostics' }
foreach($prebuilt in @($false,$true)){
foreach($unknown in @($false,$true)){
 foreach($fail in @('none','wave','replan')){
  $script:events=@();$batches=@(@{name='first';config=@{iob='iob';fly2='fly';trajectory_quality=1;rf_steps_per_period=1};lua='lua';log_dir='log'});$caught=$null
  $kind=if($unknown){'formal_first_batch_observation'}else{'exact_resource_profile'}
  $run=@{run_id='fixture';execution_batch_count=1}
  $wave=@{BatchRuns=$batches;PythonExe='Invoke-FixturePython';RepositoryRoot=$PWD;
   UsagePath=(Join-Path $env:RF_TEST_TEMP 'usage.json');RunDir=$env:RF_TEST_TEMP;
   DispatchPlanPath='dispatch';BatchPlanPath='batches';HostLease=@{token='same'};
   SimionExe='fixture';CandidateDir=$PWD;IobPath='iob';RootFly2Path='fly';IobBuilderScript='builder';
   ProgramSourcePath='program';RootRunConfigLua='lua';InspectScript='inspect';IobReport='report';LogDir='log';RfDriveKernelPath='kernel'}
  if($prebuilt){$wave.Prepared=$true}
  try {
   $result=Invoke-RfSimionAdaptiveBatchWave -WaveArguments $wave -BatchRuns ([ref]$batches) `
    -DispatchPlan @{estimation=@{kind=$kind}} -DispatchRequestPath request -ResourceProfilesPath profiles `
    -RunConfig $run -RunConfigPath (Join-Path $env:RF_TEST_TEMP 'run_config.json') `
    -PrepareReplannedBatches {param($plan) if($plan.batch_count-ne2){throw 'wrong plan'}; @('first','second')}
  } catch { $caught=$_.Exception.Message }
  $expected=if($fail-eq'wave'){'wave-failed'}elseif($unknown-and$fail-eq'replan'){'replan-failed'}else{$null}
  if($caught-ne$expected){throw "Unexpected error: $caught expected $expected"}
  if($unknown-and$fail-ne'replan'){
   if($batches.Count-ne2-or$run.execution_batch_count-ne2){throw 'failure inventory lost replanned batches'}
  }elseif($batches.Count-ne1){throw 'unobserved batch changed'}
  $events=@();if($unknown-or$prebuilt){$events+='flight'};if($unknown){$events+=@('observe','replan')}
  if($unknown-and$fail-eq'replan'){$events+='drain'}
  if(-not($unknown-and$fail-eq'replan')){$events+='wave'}
  if(-not$expected){
   if(@($result).Count-ne1-or-not$result.receipt.ok){throw 'diagnostics polluted return value'}
   $events+=@('postprocess','usage');if($unknown){$events+='publish'}
  }
  if(($script:events-join ',')-ne($events-join ',')){throw "Wrong lifecycle: $script:events"}
 }
}
}
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT, env={**os.environ, "RF_EXECUTION_SUPPORT": str(support),
                                   "RF_TEST_TEMP": directory},
                capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runner_host_permission_lifecycle_without_solver(self) -> None:
        # Execute the production acquisition/finally AST with an isolated ledger.
        # Only the scientific body and host pressure are fixtures.
        script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/host_execution_lease.ps1')
$script:HostResourceStatePath=$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH
function Get-HostResourceSnapshot {
    return @{complete=$true;unknown_process_ids=@();logical_processors=8;
        cpu_percent=0;total_memory_bytes=64GB;available_memory_bytes=32GB;io_pressure=$false;
        processes=@(@{pid=$PID;parent_pid=0;started='fixture-owner';memory_bytes=1MB})}
}
function Remove-RunPackageExecutionAlias { param($Package) }
function Invoke-RunToolRootContext {param($Operation)}
$artifactRoot=$PWD;$repoRoot=$PWD
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_TEST_RUNNER,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Runner parse failed' }
$outer=@($ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.TryStatementAst] })
if ($outer.Count -ne 1) { throw 'Expected one protected runner body' }
$acquire=@($outer[0].Body.Statements | Where-Object { $_.Extent.Text -match '^if\(\$null-eq\$continuation-or-not\$continuation.all_reused\)' -and $_.Extent.Text.Contains('Enter-HostExecutionLease') })
if ($acquire.Count -ne 1) { throw 'Host acquisition must be inside the protected body' }
$calls=@($outer[0].Body.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst] -and
    $n.GetCommandName() -in @('Invoke-RfSimionAdaptiveBatchWave')},$true))
if ($calls.Count -ne 1 -or @($calls | Where-Object { $_.Extent.StartOffset -lt $acquire[0].Extent.StartOffset }).Count) {
    throw 'Every solver branch must follow host acquisition'
}
$package=@{artifact_run_dir=$PWD};$RunId='rf-lease-fixture'
foreach ($nested in @($false,$true)) {
    foreach ($fail in @($false,$true)) {
        $parent=$null
        if ($nested) { $parent=Enter-HostExecutionLease -Role SIMION -Stage flight -RunId parent }
        $hostExecutionLease=$null;$hostExecutionOutcome='failed';$caught=$false
        $writerCompletionUnknown=$false;$interfaceFailure=$null;$massFilterFailure=$null;$continuation=$null;$fieldContext=$null
        $hostReleaseState=@{released=$false;completion=$null};$nativePreparation=[Collections.Generic.List[object]]::new()
        $ownerCapacity=$null;$deferFinalization=$false;$ResultPath='fixture-result.json'
        $execution=@{clock=[Diagnostics.Stopwatch]::StartNew();phase='prepare';phase_started=0.0;phase_seconds=[ordered]@{};elapsed_seconds=0.0}
        $executionStatus='failed';$dataValidity='unavailable';$scienceStatus='not_evaluated';$failureStage=$null
        $body=$acquire[0].Extent.Text + @'

# Exercise production PA stage transitions around a native-command fixture.
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
function Invoke-TestSimion {
    if ('gem2pa' -in $args) {
        $current=@((Get-HostResourceStatus).records)[0]
        if (-not $nested -and $current.stage -ne 'prepare') { throw 'GEM preparation held heavy stage' }
    } elseif ('refine' -in $args) { Assert-HostResourceHeavyStage }
    else { throw 'Unexpected native operation' }
    $global:LASTEXITCODE=0
}
function Invoke-RfSimionPreparationProcess {
 param($ArgumentList)
 & Invoke-TestSimion @ArgumentList
 [pscustomobject]@{exit_code=0}
}
Initialize-RfSimionPaBasis -SimionExe Invoke-TestSimion -CandidateDir $PWD -HostLease $hostExecutionLease
$current=@((Get-HostResourceStatus).records)[0]
if (-not $nested -and $current.stage -ne 'prepare') { throw 'Refine did not return to preparation' }
$hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage flight `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
Assert-HostResourceHeavyStage
if ($hostExecutionLease.inherited -ne $nested) { throw 'Wrong inheritance' }
if (@((Get-HostResourceStatus).records).Count -ne 1) { throw 'Duplicate host reservation' }
if ($fail) { throw 'injected-scientific-failure' }
$hostExecutionOutcome='success'
'@
        try {
            . ([scriptblock]::Create('try {'+$body+'} finally '+$outer[0].Finally.Extent.Text))
        } catch {
            if ($_.Exception.Message -ne 'injected-scientific-failure') { throw }
            $caught=$true
        }
        if ($caught -ne $fail) { throw 'Failure did not propagate' }
        $expected=if($nested){1}else{0}
        if (@((Get-HostResourceStatus).records).Count -ne $expected) { throw 'Incorrect terminal release' }
        if ($nested) { Assert-HostResourceHeavyStage -Lease $parent; Exit-HostExecutionLease -Lease $parent }
    }
}
'HOST_LIFECYCLE=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            for index, runner in enumerate((RUNNER, MASS_RUNNER)):
                with self.subTest(runner=runner.name, workflow=runner.parent.name):
                    environment = os.environ.copy()
                    for key in tuple(environment):
                        if key.startswith("MASS_SPECTROMETRY_HOST_"):
                            environment.pop(key)
                    environment.update({
                        "RF_TEST_RUNNER": str(runner),
                        "SIMULATION_PYTHON_EXE": sys.executable,
                        "SIMULATION_COMPLETION_SOUND": "off",
                        "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(
                            Path(directory) / f"state-{index}.sqlite3"
                        ),
                    })
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                        cwd=REPO_ROOT, env=environment, capture_output=True,
                        encoding="utf-8", errors="replace", timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("HOST_LIFECYCLE=PASS", result.stdout)

    def test_unknown_writer_preserves_dedicated_runner_ownership(self) -> None:
        script = r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_TEST_RUNNER,[ref]$tokens,[ref]$errors)
$owner=@($ast.EndBlock.Statements|Where-Object{$_ -is [Management.Automation.Language.TryStatementAst] -and $_.CatchClauses.Count -and $_.CatchClauses[0].Extent.Text.Contains('writerCompletionUnknown')})[-1]
if ($null -eq $owner) { throw 'missing owner failure guard' }
$tail=$owner.CatchClauses[0].Extent.Text+'finally'+$owner.Finally.Extent.Text
$script:events=[Collections.Generic.List[string]]::new()
function Write-RunJson {param($Path,$Value) if($Value.status -ne 'writer_completion_unknown'){throw 'bad result'};$script:events.Add('result')}
function Complete-FailedRun {throw 'published terminal'}
function Remove-RunPackageExecutionAlias {$script:events.Add('alias')}
function Exit-HostExecutionLease {$script:events.Add('host')}
function Close-RfSimionFieldCheckpointGuard {throw 'unknown writer source guard released'}
function Exit-ArtifactWorkflowCapacitySession {throw 'unknown writer capacity released'}
function Set-RfSimionExecutionPhase {}
$execution=@{phase='flight';phase_seconds=@{};elapsed_seconds=0.0};$dataValidity='unavailable';$scienceStatus='not_evaluated'
$runSummary='inert';$hostExecutionLease=@{};$package=@{artifact_run_dir=$PWD};$hostExecutionOutcome='failed';$RunId='fixture';$continuation=$null;$fieldContext=[pscustomobject]@{guard=@{};owns_capacity=$true;capacity=@{}}
foreach($data in @("`$e.Data['simion_first_batch_writer_unknown']=`$true", "`$e.Data['simion_first_batch_drain_error']='drain'", "`$e.Data['simion_wave_writer_completion_confirmed']=`$false", "`$e.Data['simion_wave_drain_error']='drain'")) {
 $script:events.Clear();$writerCompletionUnknown=$false
 try {. ([scriptblock]::Create("try{`$e=[Exception]::new('primary');$data;throw `$e}"+$tail))} catch {if($_.Exception.Message -ne 'primary'){throw}}
 if(($script:events -join ',') -ne 'result'){throw 'unknown writer protection released'}
}
exit 0
"""
        for runner in (RUNNER, MASS_RUNNER):
            with self.subTest(workflow=runner.parent.name):
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO_ROOT, env={**os.environ, "RF_TEST_RUNNER": str(runner)},
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dedicated_runners_accept_an_optional_simion_executable(self) -> None:
        for runner in (RUNNER, MASS_RUNNER):
            script = (
                f"$command = Get-Command -Name '{runner}'; "
                "$parameter = $command.Parameters['SimionExe']; "
                "if ($null -eq $parameter) { throw 'SimionExe is missing' }; "
                "$mandatory = @($parameter.Attributes | Where-Object { "
                "$_ -is [System.Management.Automation.ParameterAttribute] -and $_.Mandatory "
                "}).Count -gt 0; "
                "if ($mandatory) { throw 'SimionExe must remain optional' }; "
                "'SIMION_EXE_PARAMETER=PASS'"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SIMION_EXE_PARAMETER=PASS", result.stdout)

    def test_dedicated_runners_expose_unqualified_exploration_mode(self) -> None:
        for runner in (RUNNER, MASS_RUNNER):
            script = (
                f"$command = Get-Command -Name '{runner}'; "
                "if ($null -eq $command.Parameters['Exploration']) { "
                "throw 'Exploration is missing' }; "
                "'EXPLORATION_PARAMETER=PASS'"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("EXPLORATION_PARAMETER=PASS", result.stdout)
            source = runner.read_text(encoding="utf-8")
            self.assertIn("Get-RfSimionNumericsQualification", source)

    def test_pwsh_invalid_utf8_error_output_remains_assertable(self) -> None:
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OpenStandardError().WriteByte(0xA1); exit 1",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIsInstance(result.stderr, str)
        self.assertIn("\ufffd", result.stderr)

    def test_resolved_design_logical_hash_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            document = json.loads(RESOLVED.read_text(encoding="utf-8"))
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(verify_resolved_design(path), document["resolved_sha256"])
            document["drive"]["phase_rad"] = 0.25
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "recomputed logical design hash"):
                verify_resolved_design(path)

    def test_dedicated_runners_cover_shared_lua_required_config_fields(self) -> None:
        lua = SHARED_LUA.read_text(encoding="utf-8")
        required_fields = set(
            re.findall(r"assert\(run_config\.([a-z0-9_]+)", lua)
        )
        self.assertIn("waveform", required_fields)
        self.assertIn("parent_resolved_design_sha256", required_fields)
        self.assertGreater(len(required_fields), 10)
        helper = RUN_CONFIG_CONTRACT.read_text(encoding="utf-8")
        for token in (
            "function New-RfSimionCoreRunConfig",
            "function ConvertTo-RfSimionLuaConfig",
            "function Assert-RfSimionLuaConfigContract",
            "'parent_resolved_design_sha256'",
            "Generated SIMION run config lacks required fields",
        ):
            self.assertIn(token, helper)
        for runner_path in (RUNNER, MASS_RUNNER):
            runner = runner_path.read_text(encoding="utf-8")
            for token in (
                "New-RfSimionCoreRunConfig",
                "ConvertTo-RfSimionLuaConfig",
                "Invoke-RfSimionAdaptiveBatchWave",
                "Copy-VerifiedRunInput",
                "Write-RunDirectoryChecksumInventory",
                "parent_resolved_design_sha256 = $coreConfig.parent_resolved_design_sha256",
                "waveform = $coreConfig.waveform",
            ):
                self.assertIn(token, runner)
            for forbidden in (
                "return {",
                "Copy-Item",
                                "Start-Process -FilePath $simion",
            ):
                self.assertNotIn(forbidden, runner)

    def test_waveform_contract_accepts_only_exact_governed_enum(self) -> None:
        command = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "$resolved=Get-Content -LiteralPath $env:RF_RESOLVED_JSON "
            "-Raw -Encoding UTF8|ConvertFrom-Json; "
            "Get-VerifiedRfSimionWaveform -ResolvedDesign $resolved"
        )
        cases = (
            ({"drive": {"waveform": "sine"}}, True, "sine"),
            ({"drive": {"waveform": "cosine"}}, True, "cosine"),
            ({"drive": {}}, False, "drive.waveform is missing"),
            ({"drive": {"waveform": "sinusoidal"}}, False, "exactly sine or cosine"),
            ({"drive": {"waveform": "SINE"}}, False, "exactly sine or cosine"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (payload, accepted, message) in enumerate(cases):
                resolved_path = root / f"resolved_{index}.json"
                resolved_path.write_text(json.dumps(payload), encoding="utf-8")
                environment = os.environ.copy()
                environment.update(
                    {
                        "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
                        "RF_RESOLVED_JSON": str(resolved_path),
                    }
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    timeout=30,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                output = result.stdout if accepted else result.stderr
                self.assertIn(message, output)

    def test_core_compiler_fails_closed_on_hash_numeric_and_mapping_drift(self) -> None:
        prefix = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "$r=Get-Content $env:RF_RESOLVED_JSON -Raw|ConvertFrom-Json; "
            "$i=Get-Content $env:RF_INTERFACE_JSON -Raw|ConvertFrom-Json; "
            "$n=Get-Content $env:RF_NUMERICS_JSON -Raw|ConvertFrom-Json; "
            "$steps=40; "
            "$quality=10; "
            "$mechanical=@{}; "
        )
        suffix = (
            "$core=New-RfSimionCoreRunConfig -ResolvedDesign $r "
            "-InterfaceContract $i -SolverNumerics $n "
            "-RfStepsPerPeriod $steps "
            "-TrajectoryQuality $quality -ModeName transport_interface_readiness "
            "-OperatingPoint official_100amu_2eV -IobPath C:\\tmp\\a.iob "
            "-Fly2Path C:\\tmp\\a.fly2 -SourceStatesLua C:\\tmp\\s.lua "
            "-ParticleStateCsv C:\\tmp\\p.csv -TrajectoryCsv C:\\tmp\\t.csv "
            "-SummaryJson C:\\tmp\\q.json; "
            "if($core.rod_electrodes.Count-ne2-or$core.static_electrodes.Count-ne3){throw 'Reference electrode table sizes changed'}; "
            "if($core.rod_electrodes[0].common_mode_v-ne$r.drive.common_mode_offset_V-or$core.rod_electrodes[1].common_mode_v-ne$r.drive.common_mode_offset_V){throw 'Reference rod common-mode voltage changed'}; "
            "if($core.static_electrodes[0].potential_v-ne$r.static_electrodes_V.entrance_aperture_plate_and_connector_V-or$core.static_electrodes[1].potential_v-ne$r.static_electrodes_V.exit_outer_enclosure_and_connector_V-or$core.static_electrodes[2].potential_v-ne$r.static_electrodes_V.physical_detector_V){throw 'Reference static voltages changed'}; "
            "foreach($key in $mechanical.Keys){$core[$key]=$mechanical[$key]}; "
            "ConvertTo-RfSimionLuaConfig -CoreConfig $core "
            "-SharedProgramPath $env:RF_SHARED_LUA|Out-Null; "
            "Write-Output \"$($core.rf_steps_per_period)|$($core.trajectory_quality)\""
        )
        cases = (
            ("", True, ""),
            (
                "$mechanical=@{mechanical_exit_csv='C:\\tmp\\exit.csv'; "
                "mechanical_exit_plane_mm=82.1; mechanical_exit_aperture_radius_mm=3.6; "
                "mechanical_exit_guard_mm=82.4}; ",
                True,
                "",
            ),
            *(
                (
                    "$mechanical=@{mechanical_exit_csv='C:\\tmp\\exit.csv'; "
                    "mechanical_exit_plane_mm=82.1; mechanical_exit_aperture_radius_mm=3.6; "
                    "mechanical_exit_guard_mm=82.4}; "
                    f"$mechanical.Remove('{field}'); ",
                    False,
                    field,
                )
                for field in (
                    "mechanical_exit_csv",
                    "mechanical_exit_plane_mm",
                    "mechanical_exit_aperture_radius_mm",
                    "mechanical_exit_guard_mm",
                )
            ),
            (
                "$r.PSObject.Properties.Remove('resolved_sha256'); ",
                False,
                "resolved_sha256 is missing",
            ),
            ("$r.resolved_sha256='xyz'; ", False, "64 hexadecimal"),
            (
                "$r.drive.PSObject.Properties.Remove('frequency_Hz'); ",
                False,
                "RF frequency is missing",
            ),
            ("$r.drive.frequency_Hz=$null; ", False, "RF frequency is missing"),
            ("$r.drive.frequency_Hz=0; ", False, "RF frequency must be positive"),
            ("$r.drive.frequency_Hz='NaN'; ", False, "RF frequency must be finite"),
            (
                "$r.drive.frequency_Hz=[double]::PositiveInfinity; ",
                False,
                "RF frequency must be finite",
            ),
            ("$n.simion_cell_mm=0; ", False, "simion_cell_mm must be positive"),
            ("$i.planes.handoff.z_mm=90.3; ", False, "handoff plane mapping differs"),
            ("$steps=0; ", False, "rf_steps_per_period must be positive"),
            ("$steps=99; ", True, "99|10"),
            (
                "$quality=11; ",
                True,
                "40|11",
            ),
        )
        environment = os.environ.copy()
        environment.update(
            {
                "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
                "RF_RESOLVED_JSON": str(RESOLVED),
                "RF_INTERFACE_JSON": str(INTERFACE_CONTRACT),
                "RF_NUMERICS_JSON": str(SOLVER_NUMERICS),
                "RF_SHARED_LUA": str(SHARED_LUA),
            }
        )
        for mutation, accepted, message in cases:
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    prefix + mutation + suffix,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
            )
            self.assertEqual(result.returncode == 0, accepted, result.stderr)
            if not accepted:
                self.assertIn(message, result.stderr)
            elif message:
                self.assertIn(message, result.stdout)

    def test_nonbaseline_numerics_are_explicitly_unqualified(self) -> None:
        command = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "$n=Get-Content $env:RF_NUMERICS_JSON -Raw|ConvertFrom-Json; "
            "$values=@("
            "Get-RfSimionNumericsQualification -SolverNumerics $n -RfStepsPerPeriod 40 -TrajectoryQuality 10; "
            "Get-RfSimionNumericsQualification -SolverNumerics $n -RfStepsPerPeriod 99 -TrajectoryQuality 10; "
            "Get-RfSimionNumericsQualification -SolverNumerics $n -RfStepsPerPeriod 40 -TrajectoryQuality 11; "
            "Get-RfSimionNumericsQualification -SolverNumerics $n -RfStepsPerPeriod 40 -TrajectoryQuality 10 -Exploration $true); "
            "Write-Output ($values -join ',')"
        )
        environment = os.environ.copy()
        environment.update({
            "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
            "RF_NUMERICS_JSON": str(SOLVER_NUMERICS),
        })
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "registered,exploration_unqualified,exploration_unqualified,exploration_unqualified",
            result.stdout,
        )

    def test_full_lua_contract_reports_late_terminate_field_before_launch(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "RF_SIMION_CONFIG_CONTRACT": str(RUN_CONFIG_CONTRACT),
                "RF_SHARED_LUA": str(SHARED_LUA),
            }
        )
        command = (
            ". $env:RF_SIMION_CONFIG_CONTRACT; "
            "Assert-RfSimionLuaConfigContract "
            "-LuaConfig 'return { waveform=[[sine]], }' "
            "-SharedProgramPath $env:RF_SHARED_LUA"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("parent_resolved_design_sha256", result.stderr)

    def test_active_profiles_use_single_purpose_project_runners(self) -> None:
        profiles = {
            item["profile_id"]: item
            for item in json.loads(EXECUTION_PROFILES.read_text(encoding="utf-8"))[
                "profiles"
            ]
        }
        interface = profiles["quadrupole_transport_interface_readiness_candidate"]
        interface_steps = {step["step_id"]: step for step in interface["steps"]}
        self.assertEqual(
            set(interface["required_bindings"]),
            {
                "comsol_particle_source_path",
                "simion_particle_source_path",
                "particle_bundle_metadata_path",
                "particle_source_family_path",
                "particle_distribution_path",
                "simion_solver_numerics_contract_path",
                "operating_point_id",
            },
        )
        self.assertEqual(
            interface_steps["simion_run"]["entrypoint"],
            "workflows/interface_readiness/run_simion.ps1",
        )
        self.assertNotIn(
            "workflows/no_collision_transport/run_simion.ps1",
            json.dumps(interface),
        )
        mass_filter = profiles["quadrupole_mass_filter_simion_functional_reference"]
        mass_steps = {step["step_id"]: step for step in mass_filter["steps"]}
        self.assertEqual(
            mass_filter["required_bindings"],
            [
                "mass_filter_base_source_ion11_path",
                "simion_solver_numerics_contract_path",
            ],
        )
        self.assertEqual(
            mass_steps["simion_mass_response"]["entrypoint"],
            "workflows/mass_filter_reference/run_simion.ps1",
        )

    def test_runner_uses_current_canonical_source_cli_as_an_argument_array(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        parameter_block = source[: source.index("Set-StrictMode")]
        for forbidden in (
            "$Mode",
            "$SourceAxialOffsetMm",
            "mass_filter_reference",
        ):
            self.assertNotIn(forbidden, source)
        for required in (
            "[Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$ParticleTablePath",
            "[Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$ParticleBundleMetadataPath",
            "[Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$SourceFamilyPath",
            "[Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$ParticleDistributionPath",
        ):
            self.assertIn(required, parameter_block)
        self.assertIn("$mode = 'transport_interface_readiness'", source)
        invocation = source[source.index("$sourceProjectionArguments = @(") :]
        for token in (
            "'-m','projects.rf_multipole_ion_optics.runtime.simion_particle_source'",
            "'--particles',$particlePath",
            "'--resolved-design',$frozenResolved",
            "'--source-family',$frozenSourceFamily",
            "'--operating-point',$OperatingPoint",
            "'--expected-source-family-sha256',$sourceFamilySha",
            "'--fly2',$flyPath",
            "'--source-states-lua',$sourceStatesLua",
            "-Arguments @($sourceProjectionArguments|Select-Object -Skip 2)",
        ):
            self.assertIn(token, invocation)
        self.assertNotIn(
            "projects.rf_multipole_ion_optics.runtime.simion_particle_source --ion-table", source
        )
        self.assertIn("particle_source_metadata.json", source)
        self.assertIn("'--source',$particlePath", source)
        self.assertIn("particle_source_sha256", source)
        live_binding = source[
            source.index("$bindingArguments = @(") :
            source.index("& $python @bindingArguments")
        ]
        self.assertIn("'--bundle-metadata',$bundleMetadataInput", live_binding)
        self.assertIn("'--expected-consumed',$sourceParticlePath", live_binding)
        self.assertNotIn("$frozenBundleMetadata", live_binding)
        frozen_binding = source[
            source.index("$frozenBindingArguments = @(") :
            source.index("& $python @frozenBindingArguments")
        ]
        self.assertIn("'--bundle-metadata',$frozenBundleMetadata", frozen_binding)
        self.assertIn("'--expected-consumed',$particlePath", frozen_binding)
        self.assertNotIn("$bundleMetadataInput", frozen_binding)
        for field in (
            "source_ion11",
            "source_canonical10",
            "consumed_particle_table",
            "particle_bundle_metadata",
            "source_sample_family_sha256",
            "latent_sha256",
            "coordinate_mapping_version",
            "ion11_sha256",
            "canonical10_sha256",
            "n1000_parent",
        ):
            self.assertIn(field, source)

    def test_bundle_binding_recomputes_both_representations(self) -> None:
        distribution = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = generate_bundle(
                SOURCE_FAMILY, distribution, RESOLVED, root
            )
            canonical = root / "official_100amu_2eV_n100_canonical.csv"
            result = resolve_binding(
                root / "paired_particle_bundle.json",
                SOURCE_FAMILY,
                distribution,
                RESOLVED,
                "official_100amu_2eV",
                100,
                "canonical10",
                canonical,
            )
            entries = {
                entry["representation"]: entry
                for entry in metadata["artifacts"]
                if entry["operating_point_id"] == "official_100amu_2eV"
                and entry["particle_count"] == 100
            }
            self.assertEqual(result["representation"], "canonical10")
            self.assertEqual(result["consumed_sha256"], entries["canonical10"]["sha256"])
            self.assertEqual(result["ion11_sha256"], entries["ion11"]["sha256"])
            self.assertEqual(
                result["source_sample_family_sha256"],
                metadata["sample_family_sha256"],
            )
            self.assertEqual(result["representation_equivalence"], "PASS")
            self.assertEqual(result["n1000_parent"], entries["canonical10"]["n1000_parent"])
            n1000 = resolve_binding(
                root / "paired_particle_bundle.json",
                SOURCE_FAMILY,
                distribution,
                RESOLVED,
                "official_100amu_2eV",
                1000,
                "canonical10",
                root / "official_100amu_2eV_n1000_canonical.csv",
            )
            self.assertEqual(n1000["particle_count"], 1000)
            self.assertIsNone(n1000["n1000_parent"])
            with self.assertRaisesRegex(ValueError, "differs from its bundle artifact"):
                resolve_binding(
                    root / "paired_particle_bundle.json",
                    SOURCE_FAMILY,
                    distribution,
                    RESOLVED,
                    "official_100amu_2eV",
                    100,
                    "canonical10",
                    root / "official_100amu_2eV_n100.ion",
                )

    def test_exploration_bundle_allows_an_explicit_nonstandard_particle_count(self) -> None:
        distribution = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = generate_bundle(
                SOURCE_FAMILY, distribution, RESOLVED, root, particle_counts=[3]
            )
            self.assertEqual(metadata["particle_counts"], [3])
            result = resolve_binding(
                root / "paired_particle_bundle.json", SOURCE_FAMILY, distribution,
                RESOLVED, "official_100amu_2eV", 3, "canonical10",
                root / "official_100amu_2eV_n3_canonical.csv",
            )
            self.assertEqual(result["particle_count"], 3)
            self.assertIsNone(result["n1000_parent"])
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "if (-not $Exploration -and $expectedParticles -lt $minimumParticles)",
            source,
        )

    def test_live_and_frozen_bundle_bindings_reject_cross_root_mixing(self) -> None:
        distribution = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live"
            frozen = root / "frozen"
            generate_bundle(SOURCE_FAMILY, distribution, RESOLVED, live)
            live_metadata = live / "paired_particle_bundle.json"
            live_canonical = live / "official_100amu_2eV_n100_canonical.csv"
            live_result = resolve_binding(
                live_metadata,
                SOURCE_FAMILY,
                distribution,
                RESOLVED,
                "official_100amu_2eV",
                100,
                "canonical10",
                live_canonical,
            )
            shutil.copytree(live, frozen)
            frozen_metadata = frozen / "paired_particle_bundle.json"
            frozen_canonical = (
                frozen / "official_100amu_2eV_n100_canonical.csv"
            )
            frozen_result = resolve_binding(
                frozen_metadata,
                SOURCE_FAMILY,
                distribution,
                RESOLVED,
                "official_100amu_2eV",
                100,
                "canonical10",
                frozen_canonical,
            )
            self.assertEqual(
                live_result["consumed_sha256"],
                frozen_result["consumed_sha256"],
            )
            with self.assertRaisesRegex(
                ValueError, "differs from its bundle artifact"
            ):
                resolve_binding(
                    frozen_metadata,
                    SOURCE_FAMILY,
                    distribution,
                    RESOLVED,
                    "official_100amu_2eV",
                    100,
                    "canonical10",
                    live_canonical,
                )

    def test_real_python_cli_preserves_canonical_coordinate_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "inputs with spaces [poison]"
            root.mkdir()
            particles = root / "particles.csv"
            fly2 = root / "particles.fly2"
            states = root / "source states.lua"
            write_canonical_source(particles)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "projects.rf_multipole_ion_optics.runtime.simion_particle_source",
                    "--particles",
                    str(particles),
                    "--resolved-design",
                    str(RESOLVED),
                    "--source-family",
                    str(SOURCE_FAMILY),
                    "--operating-point",
                    "official_100amu_2eV",
                    "--expected-source-family-sha256",
                    hashlib.sha256(SOURCE_FAMILY.read_bytes()).hexdigest(),
                    "--fly2",
                    str(fly2),
                    "--source-states-lua",
                    str(states),
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            fly_text = fly2.read_text(encoding="ascii")
            state_text = states.read_text(encoding="ascii")
            self.assertEqual(fly_text.count("standard_beam {"), 100)
            self.assertIn("position=vector(-2.22044604925e-16,0.2,0.1)", fly_text)
            self.assertIn("[1]={t=0,x=-2.22044604925e-16,y=0.2,z=0.1", state_text)
            self.assertIn("vy=0.05,vz=0.1,ke=2", state_text)

    def test_pre_solver_failure_finishes_failed_run_without_simion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            particles = root / "empty canonical.csv"
            particles.write_text(",".join(COLUMNS) + "\n", encoding="utf-8")
            layout_asset = root / "self-contained layout fixture"
            layout_asset.write_text("test-only layout fixture\n", encoding="utf-8")
            layout_resolution = root / "layout resolution.json"
            layout_resolution.write_text(
                json.dumps(
                    {
                        "registry_path": str(layout_asset),
                        "run_manifest": {"path": str(layout_asset)},
                        "bundle": {
                            "iob": {"path": str(layout_asset)},
                            "con": {"path": str(layout_asset)},
                            "placeholder_pa0": {"path": str(layout_asset)},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            layout_stub = root / "resolve_layout_fixture.py"
            layout_stub.write_text(
                "\n".join(
                    (
                        "import os",
                        "import shutil",
                        "import sys",
                        "from pathlib import Path",
                        "",
                        "arguments = sys.argv[1:]",
                        "output = Path(arguments[arguments.index('--output') + 1])",
                        "output.parent.mkdir(parents=True, exist_ok=True)",
                        "shutil.copyfile(os.environ['RF_TEST_LAYOUT_RESOLUTION'], output)",
                        "print('MULTIPOLE_SIMION_LAYOUT_TEMPLATE=PASS TEMPLATE=test_single_pa_v1')",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            python_wrapper = root / "python_with_layout_fixture.cmd"
            python_wrapper.write_text(
                "\r\n".join(
                    (
                        "@echo off",
                        'if "%~1"=="-c" (echo 3.11& exit /b 0)',
                        'if "%~1"=="-m" if "%~2"=="projects.rf_multipole_ion_optics.runtime.simion_layout_template" goto layout',
                        '"%RF_TEST_REAL_PYTHON%" %*',
                        "exit /b %ERRORLEVEL%",
                        ":layout",
                        '"%RF_TEST_REAL_PYTHON%" "%RF_TEST_LAYOUT_STUB%" %*',
                        "exit /b %ERRORLEVEL%",
                    )
                )
                + "\r\n",
                encoding="ascii",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_TEST_REAL_PYTHON": sys.executable,
                    "RF_TEST_LAYOUT_STUB": str(layout_stub),
                    "RF_TEST_LAYOUT_RESOLUTION": str(layout_resolution),
                }
            )
            # Exercise the governed project layout in an isolated artifact tree.
            artifact_workspace = root / "artifacts"
            artifact_root = artifact_workspace / "projects" / "rf_multipole_ion_optics"
            artifact_root.mkdir(parents=True)
            initialize_capacity_ledger(artifact_workspace, objects=[])
            run_id = "20260725_120000__test__simion__source-preflight"
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(RUNNER),
                    "-RunId",
                    run_id,
                    "-ParticleTablePath",
                    str(particles),
                    "-ParticleBundleMetadataPath",
                    str(root / "missing bundle.json"),
                    "-SourceFamilyPath",
                    str(SOURCE_FAMILY),
                    "-ParticleDistributionPath",
                    str(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "official_particle_source.json"),
                    "-SolverNumericsContractPath",
                    str(PROJECT_ROOT / "variants" / "quadrupole" / "config" / "simion_solver_numerics.json"),
                    "-OperatingPoint",
                    "official_100amu_2eV",
                    "-ArtifactRootPath",
                    str(artifact_root),
                    "-PythonExe",
                    str(python_wrapper),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=60,
            )
            process_diagnostics = (
                f"returncode={result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
            self.assertNotEqual(result.returncode, 0, process_diagnostics)
            self.assertNotIn("STATUS=PASS", result.stdout)
            self.assertIn("bundle metadata is missing", result.stderr.lower())
            run = artifact_root / "runs" / run_id
            for filename in ("run_config.json", "summary.json", "run_manifest.json"):
                self.assertTrue(
                    (run / filename).is_file(),
                    f"missing failed-run {filename}\n{process_diagnostics}",
                )
            summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            manifest = json.loads(
                (run / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "failed")
            self.assertIn("bundle metadata is missing", summary["reason"].lower())
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse(any((run / "simion").glob("*.pa0")))

    def test_execution_failure_and_physical_decision_are_separate(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("SIMION transport execution integrity failed", source)
        self.assertIn("$physicalDecision = if", source)
        self.assertIn("physical_decision=$physicalDecision", source)
        self.assertIn("EXECUTION=PASS DECISION=$physicalDecision", source)
        self.assertIn("Complete-RunArtifactPowerShellOwner", source)
        integrity = source[
            source.index("if ($summary.particles -ne $expectedParticles")
            : source.index("$physicalDecision = if")
        ]
        self.assertNotIn("summary.transmission", integrity)
        self.assertNotIn("-ge 0.8", source)
        self.assertIn(
            "$summary.transmission -ge $minimumTransmission",
            source,
        )
        self.assertEqual(source.count("transport_interface_readiness.json"), 1)
        self.assertIn(
            "-LiteralPath $frozenMode -Raw -Encoding UTF8 | ConvertFrom-Json",
            source,
        )
        self.assertIn("minimum_transmission = $minimumTransmission", source)
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertLess(source.index("try {"), source.index("$sourceParticlePath"))


if __name__ == "__main__":
    unittest.main()
