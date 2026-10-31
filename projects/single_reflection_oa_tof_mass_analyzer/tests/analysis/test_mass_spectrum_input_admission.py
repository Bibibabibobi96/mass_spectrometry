"""Thin normal/resume geometry admission; does not grant Formal access."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class MassSpectrumInputAdmissionTests(unittest.TestCase):
    def test_workspace_context_and_final_publication_preserve_package_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root/'context.ps1'
            script.write_text(r'''param($Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
$mass=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1'
$ideal=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_ideal_field_diagnostic.ps1'
$text=[IO.File]::ReadAllText($mass);$ast=[Management.Automation.Language.Parser]::ParseFile($mass,[ref]$null,[ref]$null)
$first=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq'$python'},$true)
$last=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq'$environmentNames'},$true)
$prefix=$text.Substring($first.Extent.StartOffset,$last.Extent.StartOffset-$first.Extent.StartOffset)
$repoRoot=$Repo;$projectRoot=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer'
foreach($scenario in @('new','resume','missing_paths','root_mismatch')){
 $selected=Join-Path $Root ($scenario+'/configured-artifacts')
 $original=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot $selected -ExecutionRoot (Join-Path $Root ($scenario+'/original-exec')) -HostResourceStatePath (Join-Path $Root ($scenario+'/original-host.sqlite3')) -Python $Python
 $env:SIMULATION_PYTHON_EXE=$Python;$env:MASS_SPECTROMETRY_ARTIFACT_ROOT=$selected
 $env:MASS_SPECTROMETRY_EXECUTION_ROOT=Join-Path $Root 'today-exec';$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $Root 'today-host.sqlite3'
 $RunId='20261030_120600__sim__cross__mass-context';$ResumeAfterComsol=$scenario-ne'new';$ReanalyzeOnly=$false
 $expected=Join-Path $selected ('projects/single_reflection_oa_tof_mass_analyzer/runs/'+$RunId)
 if($ResumeAfterComsol){
  [IO.Directory]::CreateDirectory($expected)|Out-Null
  $record=@{run_id=$RunId;project='single_reflection_oa_tof_mass_analyzer';mode='mass_spectrum_candidate';paths=$original;capacity_ledger_lifecycle=@{artifact_root=$selected}}
  if($scenario-eq'missing_paths'){$record.Remove('paths')}
  if($scenario-eq'root_mismatch'){$record.paths=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot (Join-Path $Root 'other-artifacts') -Python $Python}
  Write-RunJson -Path (Join-Path $expected 'run_config.json') -Value $record -Depth 20
 }
 $caught=$null;try{Invoke-Expression $prefix}catch{$caught=$_.Exception.Message}
 if($scenario-eq'missing_paths'){
  if($caught-notlike'Resume lacks frozen path context. ACTION=*'){throw ('Missing frozen roots accepted: '+$caught)}
 }elseif($scenario-eq'root_mismatch'){
  if($caught-cne'Resume frozen run/root/capacity identity differs.'){throw ('Frozen root mismatch accepted: '+$caught)}
 }else{
  if($caught-or$artifactRoot-cne(Join-Path $selected 'projects/single_reflection_oa_tof_mass_analyzer')){throw ('Selected artifact root changed: '+$caught)}
  if($scenario-eq'resume'-and($pathContext.execution_root-cne$original.execution_root-or$pathContext.host_resource_state_path-cne$original.host_resource_state_path)){throw 'Resume followed today defaults'}
 }
}
foreach($entry in @(@{file=$ideal;variable='$finalConfig';pathVariable='$runConfig'},@{file=$mass;variable='$runConfig';pathVariable='$runConfigPath'})){
 $text=[IO.File]::ReadAllText($entry.file);$ast=[Management.Automation.Language.Parser]::ParseFile($entry.file,[ref]$null,[ref]$null)
 $variable=$entry.variable;$pathVariable=$entry.pathVariable
 $first=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq$variable},$true)
 $last=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Write-RunJson'-and$n.Extent.Text.Contains('-Value '+$variable+' ')},$true)
 $block=$text.Substring($first.Extent.StartOffset,$last.Extent.EndOffset-$first.Extent.StartOffset)
 $configFile=Join-Path $Root ([IO.Path]::GetFileName($entry.file)+'.json')
 $original=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot (Join-Path $Root 'publication-artifacts') -ExecutionRoot (Join-Path $Root 'publication-exec') -HostResourceStatePath (Join-Path $Root 'publication-host.sqlite3') -Python $Python
 Write-RunJson -Path $configFile -Value @{schema_version=2;paths=$original;package_sentinel='keep';artifact_retention=@{class='solver_review'};capacity_ledger_lifecycle=@{artifact_root=$original.artifact_root}} -Depth 20
 $runConfig=$configFile;$runConfigPath=$configFile;$runInputs=@{science='source-record'}
 $N=2;$Seed=17;$AnalyzeOnly=$true;$mode=[pscustomobject]@{species=@()};$sourceProvenance=@();$ResumeAfterComsol=$false;$ReanalyzeOnly=$true;$simionMaxTofUs=80
 Invoke-Expression $block
 $result=Get-Content -LiteralPath $configFile -Raw|ConvertFrom-Json -AsHashtable
 if($result.schema_version-ne2-or$result.package_sentinel-cne'keep'-or$result.paths.execution_root-cne$original.execution_root-or$result.paths.host_resource_state_path-cne$original.host_resource_state_path-or$result.capacity_ledger_lifecycle.artifact_root-cne$result.paths.artifact_root-or$result.inputs.science-cne'source-record'){throw 'Final scientific publication discarded package identity'}
}
'WORKSPACE_PUBLICATION=PASS'
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script),str(REPO),sys.executable,str(root)],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('WORKSPACE_PUBLICATION=PASS', result.stdout)

    def test_guard_freshness_and_original_resume_inputs(self):
        owner = PROJECT / "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1"
        for scenario in ("normal", "stale", "pending", "resume", "reanalyze", "foreign_resume"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture_project = root / "project"
                (fixture_project / "config").mkdir(parents=True)
                lifecycle = "formal_revalidation_pending" if scenario == "pending" else "prototype"
                (fixture_project / "config/project.json").write_text(
                    json.dumps({"lifecycle_status": lifecycle}), encoding="utf-8")
                fixture = root / "admit.ps1"
                fixture.write_text(r'''param($Repo,$Python,$Owner,$Root,$Project,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1')
$realCopy=(Get-Command Copy-VerifiedRunInput).ScriptBlock
$script:copies=0
function Copy-VerifiedRunInput {param($Source,$Destination)
 $script:copies++
 $result=& $realCopy -Source $Source -Destination $Destination
 if($Scenario-eq'stale'-and$Destination.Replace('\','/').EndsWith('/config/resolved_geometry.json')){[IO.File]::AppendAllText($Destination,' ')}
 return $result
}
$repoRoot=$Repo;$python=$Python;$projectRoot=$Project;$runDir=$Root
[IO.File]::WriteAllText((Join-Path $runDir 'run_config.json'),'{"inputs":{},"parameters":{}}')
$inputDir=Join-Path $Root 'inputs';New-Item -ItemType Directory $inputDir|Out-Null
$modePath=Join-Path $inputDir 'mass_spectrum.json';$particleCountPolicyPath=Join-Path $inputDir 'particle_count_policy.json'
$resolvedPath=Join-Path $inputDir 'resolved_geometry.json';$recordedResolved=Join-Path $inputDir 'original_recorded_resolved.json'
$liveModePath=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/config/modes/mass_spectrum.json'
$liveParticleCountPolicyPath=Join-Path $Repo 'common/contracts/particle_count_policy.json'
$geometryFrozenInputs=[ordered]@{}
$resumeExisting=$Scenario-in@('resume','reanalyze','foreign_resume')
$existingLifecycle=[pscustomobject]@{inputs=[pscustomobject]@{resolved_geometry=$recordedResolved;geometry_freshness_baseline=(Join-Path $inputDir 'original_baseline.json')}}
if($Scenario-eq'foreign_resume'){$recordedResolved=Join-Path $Root 'outside_resolved.json';$existingLifecycle.inputs.resolved_geometry=$recordedResolved}
if($resumeExisting){foreach($p in @($modePath,$particleCountPolicyPath,$recordedResolved)){[IO.File]::WriteAllText($p,'{}')}}
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$prepare=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.Contains('$geometrySnapshotRoot = Join-Path')},$true)
if($null-eq$prepare){throw 'Actual prepare branch not found'}
$downstream=0;$caught=$null
try{
 Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot
 Invoke-Expression $prepare.Extent.Text
 $downstream++
}catch{$caught=$_.Exception.Message}
switch($Scenario){
 'pending' {if($caught-notlike'FORMAL_REVALIDATION_REQUIRED*'-or$script:copies-ne0-or$downstream-ne0){throw 'Formal guard was bypassed or did unnecessary geometry work'}}
 'foreign_resume' {if($caught-cne'Recorded geometry must remain within this run frozen inputs.'-or$script:copies-ne0-or$downstream-ne0){throw 'Foreign recorded input escaped the original frozen-input boundary'}}
 'stale' {if($caught-cne'Frozen mass-spectrum geometry input freshness failed.'-or$downstream-ne0){throw ('Stale prepare was accepted: '+$caught)};$record=Get-Content (Join-Path $runDir 'run_config.json') -Raw|ConvertFrom-Json;if($record.inputs.resolved_geometry-cne$resolvedPath-or$record.parameters.lifecycle_stage-cne'geometry_input_freshness'){throw 'Failed geometry input identity was lost'}}
 {$_-in@('resume','reanalyze')} {if($caught-or$script:copies-ne0-or$resolvedPath-cne$recordedResolved-or$downstream-ne1-or$geometryFrozenInputs.geometry_freshness_baseline-cne$existingLifecycle.inputs.geometry_freshness_baseline){throw 'Historical inputs rebound to current defaults'}}
 default {if($caught-or$script:copies-ne12-or$resolvedPath-cne$geometryFrozenInputs.geometry_freshness_published-or$downstream-ne1){throw ('Valid pure prepare failed: '+$caught)}}
}
'MASS_SPECTRUM_ADMISSION=PASS'
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture), str(REPO),
                                         sys.executable, str(owner), str(root), str(fixture_project), scenario],
                                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("MASS_SPECTRUM_ADMISSION=PASS", result.stdout)
                if scenario == "normal":
                    self.assertIn("RESOLVED_GEOMETRY=PASS", result.stdout)
                if scenario == "stale":
                    self.assertIn("STALE=config/resolved_geometry.json", result.stdout + result.stderr)
