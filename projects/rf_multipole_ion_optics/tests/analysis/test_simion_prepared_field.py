"""Real fractional checkpoint consumer, without invoking native simulation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from projects.rf_multipole_ion_optics.runtime.simion_field_checkpoint import write_checkpoint
from projects.rf_multipole_ion_optics.tests.domain import test_simion_field_checkpoint as fixtures

REPO = fixtures.REPO


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PA guards required")
class PreparedFieldConsumerTests(unittest.TestCase):
    def test_seed_cleanup_requires_known_builder_and_preserves_original_field(self):
        script = r'''
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/contracts/run_artifact_support.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
$seed=Join-Path $env:RF_TEST_TEMP 'registered.pa0';'inert registered companion'|Set-Content $seed
$iob=Join-Path $env:RF_TEST_TEMP 'quad.iob'
$companion=New-RfSimionLayoutSeedCompanion -IobPath $iob -SeedPaPath $seed
if(-not$companion.created){throw 'required template companion not created'}
foreach($fact in @(@{exit_confirmed=$false;returncode=0},@{exit_confirmed=$true;returncode=7})){
 $rejected=$false;try{Remove-RfSimionLayoutSeedCompanion -Companion $companion -BuildObservation $fact}catch{$rejected=$true}
 if(-not$rejected-or-not(Test-Path $companion.path)){throw 'unknown or failed builder companion deleted'}
}
Remove-RfSimionLayoutSeedCompanion -Companion $companion -BuildObservation @{exit_confirmed=$true;returncode=0}
if(Test-Path $companion.path){throw 'template companion survived confirmed build'}
'original field'|Set-Content $companion.path
$original=New-RfSimionLayoutSeedCompanion -IobPath $iob -SeedPaPath 'must-not-read'
Remove-RfSimionLayoutSeedCompanion -Companion $original -BuildObservation @{exit_confirmed=$true;returncode=0}
if((Get-Content $original.path -Raw).Trim()-cne'original field'){throw 'original field overwritten or removed'}
'''
        with tempfile.TemporaryDirectory() as temporary:
            process = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO,
                env={**os.environ, "RF_TEST_TEMP": temporary}, capture_output=True, text=True,
                encoding="utf-8", timeout=20)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_two_cli_field_options_reach_shared_owner_and_full_reuse_skips_it(self):
        script = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
function Set-RfSimionExecutionPhase {param($Context,$Name)}
function ConvertTo-RfSimionLuaConfig {param($CoreConfig,$SharedProgramPath) 'return {}'}
function Write-RunJson {param($Path,$Value,$Depth)}
$script:calls=0
$ownerCapacity=@{protected_paths=@()};$ownerContext=@{request_path=(Join-Path $env:RF_TEST_TEMP 'owner_request.json')}
'{"capacity":{"protected_paths":[]}}'|Set-Content $ownerContext.request_path
function Initialize-RfSimionPreparedField {
 param($SourceRunPath,$ExistingProtectedRuns,$CapacitySession,$Preparation)
 if($SourceRunPath-cne$script:expected){throw 'CLI field source not forwarded'}
 if($Preparation.RfDriveKernelPath-cne'kernel'-or$Preparation.ProgramSourcePath-cne'program'){throw 'frozen native inputs absent'}
 $script:calls++;[pscustomobject]@{capacity=$CapacitySession;iob_path='original.iob';source_reused=$true;checkpoint_path='small.json';producer_manifest='producer/run_manifest.json'}
}
$template=@{placeholder_pa0='registered-seed'};$package=@{};$execution=@{};$candidateDir='candidate';$simion='unused';$flyPath='source';$iobBuilder='builder';$programSource='program';$runConfigLua=Join-Path $env:RF_TEST_TEMP 'run.lua';$inspectScript='inspect';$iobReport='report';$logDir='logs';$rfDriveKernel='kernel';$hostExecutionLease=@{};$templateIob='template';$templateCon='con';$python='python';$repoRoot=$PWD;$artifactRoot=Join-Path $env:RF_TEST_TEMP 'artifacts/projects/rf';$nativePreparation=[Collections.Generic.List[object]]::new();$runConfigPath='unused'
foreach($workflow in @('interface_readiness','mass_filter_reference')){
 $path=Join-Path $PWD "projects/rf_multipole_ion_optics/workflows/$workflow/run_simion.ps1"
 if(-not(Get-Command $path).Parameters.ContainsKey('NativeFieldRunPath')){throw 'formal CLI lacks field option'}
 $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$null,[ref]$null)
 $branch=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.StartsWith('if($null-eq$continuation-or-not$continuation.all_reused)')-and$n.Extent.Text.Contains('Initialize-RfSimionPreparedField')},$true))
 if($branch.Count-ne1){throw 'field owner not wired once'}
 foreach($kind in @('normal','partial','explicit','all')){
  $coreConfig=@{iob='planned.iob'};$runConfig=@{inputs=@{simion_field_identity='identity'};project='rf'}
  $NativeFieldRunPath=if($kind-eq'explicit'){'independent-source'}else{''}
  $continuation=if($kind-eq'normal'){$null}else{[pscustomobject]@{all_reused=($kind-eq'all');predecessor='parent';chain=@('parent');capacity=@{}}}
  $script:expected=if($kind-eq'normal'){''}elseif($kind-eq'explicit'){'independent-source'}else{'parent'}
  $before=$script:calls;. ([scriptblock]::Create($branch[0].Extent.Text))
  if(($script:calls-$before)-ne[int]($kind-ne'all')){throw 'full reuse loaded field or missing Fly omitted owner'}
  if($kind-ne'all'-and$coreConfig.iob-cne'original.iob'){throw 'actual IOB not propagated'}
 }
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            process = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO,
                env={**os.environ, "RF_TEST_TEMP": temporary}, capture_output=True, text=True,
                encoding="utf-8", timeout=20)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_actual_source_owner_reuses_field_and_only_rebinds_missing_layout(self):
        for has_layout in (True, False):
            with self.subTest(has_layout=has_layout), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = fixtures.FieldCheckpointTests()
                parent, identity, iob = fixture.fixture(root, layout=has_layout)
                template = root / "template.iob"
                template.write_bytes(b"inert template")
                template.with_suffix(".con").write_bytes(b"inert configuration")
                config_path = parent / "run_config.json"
                config = json.loads(config_path.read_text())
                config["inputs"].update(simion_layout_template_iob=str(template),
                    simion_layout_template_con=str(template.with_suffix(".con")))
                config_path.write_text(json.dumps(config))
                result = write_checkpoint(parent, identity, iob, [
                    {"operation_id": name, "observation": dict(fixtures.NATIVE_SUCCESS)}
                    for name in (("refine", "build_runtime_iob", "inspect_runtime_iob") if has_layout else ("refine",))])
                fixture.publish(parent, result)
                before = (parent / "run_manifest.json").read_bytes()
                child = root / "child"
                (child / "simion").mkdir(parents=True)
                program = root / "program.lua"
                program.write_bytes(b"inert lua")
                script = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:RF_TEST_REPO 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
. (Join-Path $env:RF_TEST_REPO 'projects/rf_multipole_ion_optics/runtime/simion_field_checkpoint_support.ps1')
function Enter-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$Owner)
 if($ProtectedPaths.Count-lt1){throw 'source capacity not protected'};return @{protected_paths=$ProtectedPaths}}
function Initialize-RfSimionPaBasis {throw 'valid predecessor field must not be refined'}
$script:layouts=0
function Initialize-RfSimionPreparedBatch {param($SimionExe,$CandidateDir,$IobPath,$Fly2Path,$IobBuilderScript,$ProgramSourcePath,$RunConfigLua,$InspectScript,$IobReport,$LogDir,$RfDriveKernelPath,$NativeOperations,$ControllerPath)
 $script:layouts++;if($ControllerPath-cne(Join-Path $env:RF_TEST_PARENT 'simion/quad_monolithic.pa0')){throw 'original controller not bound'}
 if($IobPath-cne(Join-Path $env:RF_TEST_CHILD 'simion/quad_monolithic.iob')){throw 'layout save/inspect must use permanent physical IOB'}
 if(-not(Test-Path $IobPath)){throw 'required template absent'}}
$child=$env:RF_TEST_CHILD;$alias=Join-Path (Split-Path $child -Parent) 'short-execution-alias';$preparation=@{SimionExe='not-started';CandidateDir=(Join-Path $alias 'simion');IobPath=(Join-Path $alias 'simion/quad_monolithic.iob');Fly2Path='unused';IobBuilderScript='unused';ProgramSourcePath=$env:RF_TEST_PROGRAM;RunConfigLua='unused';InspectScript='unused';IobReport='unused';LogDir='unused';RfDriveKernelPath='unused'}
$context=Initialize-RfSimionPreparedField -Package @{run_dir=$alias;artifact_run_dir=$child} -IdentityPath $env:RF_TEST_IDENTITY -Preparation $preparation -HostLease @{} -TemplateIobPath $env:RF_TEST_TEMPLATE -TemplateConPath ([IO.Path]::ChangeExtension($env:RF_TEST_TEMPLATE,'.con')) -PythonExe $env:RF_TEST_PYTHON -RepositoryRoot $env:RF_TEST_REPO -ArtifactRoot $child -Owner rf_multipole_ion_optics -NativeOperations ([Collections.Generic.List[object]]::new()) -SourceRunPath $env:RF_TEST_PARENT
try{
 $expected=[int]$env:RF_TEST_LAYOUTS;if($script:layouts-ne$expected){throw 'layout rebuilt unnecessarily or missing'}
 if(-not$context.source_reused-or$context.output_paths.Count){throw 'reused field copied into child outputs'}
 if(Test-Path $preparation.IobPath){throw 'IOB was materialized through alias'}
 if($expected-eq1-and$context.iob_path-cne(Join-Path $child 'simion/quad_monolithic.iob')){throw 'Fly must receive permanent IOB'}
 if($expected-eq0-and(Test-Path (Join-Path $child 'simion/quad_monolithic.iob'))){throw 'unnecessary child IOB created'}
 foreach($record in $context.guard.pa_records){$blocked=$false;try{$s=[IO.File]::Open($record.path,'Open','Write','ReadWrite');$s.Dispose()}catch{$blocked=$true};if(-not$blocked){throw 'source guard not held'}}
}finally{Close-RfSimionFieldCheckpointGuard -Context $context.guard}
'''
                proc = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO,
                    env={**os.environ, "RF_TEST_REPO": str(REPO), "RF_TEST_PARENT": str(parent),
                        "RF_TEST_CHILD": str(child), "RF_TEST_IDENTITY": str(identity), "RF_TEST_PROGRAM": str(program),
                        "RF_TEST_TEMPLATE": str(template), "RF_TEST_LAYOUTS": str(int(not has_layout)),
                        "RF_TEST_PYTHON": sys.executable, "SIMULATION_PYTHON_EXE": sys.executable},
                    capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual((parent / "run_manifest.json").read_bytes(), before)
