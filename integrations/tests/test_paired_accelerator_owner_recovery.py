"""Thin paired owner release adapters; the public owner owns finalization faults."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(shutil.which("pwsh"),"PowerShell 7 required")
class PairedOwnerRecoveryTests(unittest.TestCase):
    def test_actual_cli_resume_passes_original_owner_paths_and_propagates_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contracts = root / "repository/common/contracts"
            contracts.mkdir(parents=True)
            (contracts / "run_artifact_support.ps1").write_text("# inert import fixture\n", encoding="utf-8")
            (contracts / "run_artifact_workflow.ps1").write_text(
                "param($ResultPath,[switch]$ResumeFinalization)\n"
                "function Invoke-RunArtifactWorkflow {param($RequestPath,$ResultPath,[switch]$ResumeFinalization)\n"
                " @{request=$RequestPath;result=$ResultPath;resume=[bool]$ResumeFinalization}|ConvertTo-Json|Set-Content ($ResultPath+'.called')\n"
                " $prior=Get-Content -LiteralPath $ResultPath -Raw|ConvertFrom-Json\n"
                " return @{status=$prior.expected_status}\n}\n", encoding="utf-8")
            for owner in ("paired_accelerator_static_field", "paired_accelerator_pulse"):
                for status in ("success", "failed"):
                    with self.subTest(owner=owner, status=status):
                        run = root / owner / status / "managed_run"
                        result = root / (owner + status + ".json")
                        payload = json.dumps(dict(run_directory=str(run), expected_status=status)).encode("utf-8")
                        result.write_bytes(payload)
                        actual = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File",
                            str(ROOT / f"integrations/workflows/{owner}/execute.ps1"),
                            "-ResumeFinalization", "-ResultPath", str(result), "-RunId", "managed_run",
                            "-RepoRoot", str(root / "repository")], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
                        self.assertEqual(actual.returncode == 0, status == "success", actual.stdout + actual.stderr)
                        call = json.loads(Path(str(result) + ".called").read_text(encoding="utf-8-sig"))
                        self.assertEqual(Path(call["request"]), run / "inputs/execution_request.json")
                        self.assertEqual(Path(call["result"]), result)
                        self.assertTrue(call["resume"])
                        self.assertEqual(result.read_bytes(), payload)
                        self.assertFalse(run.exists())

    def test_unconfirmed_host_release_is_attempted_once_and_preserves_protection(self):
        code=r"""param($Owner,$Failure,$Repo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$pathEnvironmentNames=@('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
$savedPathEnvironment=Save-RunEnvironment -Names $pathEnvironmentNames
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$close=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Close-PairedHostStage'},$true)
. ([scriptblock]::Create($close.Extent.Text))
$body=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$null-ne$_.Finally})[-1]
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
$lease=@{token='test-owner';inherited=$false};$writerUnknown=$false;$hostReleaseUnknown=$false;$writersStopped=$true;$ownerContext=$null;$failure=$null;$script:releaseCalls=0
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
function Exit-HostResourceStage {param($Lease,[switch]$PassThru);$script:releaseCalls++;if($Failure-eq'throw'){throw 'PRIMARY_RELEASE_FAILURE'};return @{status='retained';token=$Lease.token}}
function Exit-ArtifactWorkflowCapacitySession {throw 'capacity released while unknown'}
function Remove-RunPackageExecutionAlias {throw 'alias removed while unknown'}
function Unprotect-ImmutablePaSource {throw 'guard released while unknown'}
try{Close-PairedHostStage}catch{$failure=$_}
. $finalizer
if($releaseCalls-ne1-or-not$writerUnknown-or-not$hostReleaseUnknown-or$null-eq$lease){throw 'owner release was retried or protection forgotten'}
if($Failure-eq'throw'-and$failure.Exception.Message-ne'PRIMARY_RELEASE_FAILURE'){throw 'primary release error was replaced'}
'UNKNOWN_RELEASE_PRESERVED=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/"release.ps1";script.write_text(code,encoding="utf-8",newline="\n")
            for owner,failure in (("paired_accelerator_static_field","throw"),("paired_accelerator_pulse","retained")):
                with self.subTest(owner=owner):
                    result=subprocess.run([shutil.which("pwsh"),"-NoProfile","-File",str(script),str(ROOT/f"integrations/workflows/{owner}/execute.ps1"),failure,str(ROOT)],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertIn("UNKNOWN_RELEASE_PRESERVED=PASS",result.stdout)

    def test_failed_owners_pass_saved_raw_outputs_and_original_error_to_public_finalizer(self):
        code=r"""param($Owner,$Run,$Repo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$pathEnvironmentNames=@('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
$savedPathEnvironment=Save-RunEnvironment -Names $pathEnvironmentNames
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
foreach($name in @('Register-PairedInputs','Register-PulseInputs')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 if($node){. ([scriptblock]::Create($node.Extent.Text))}
}
$body=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$null-ne$_.Finally})[-1]
$finalizer=[scriptblock]::Create(($body.Finally.Statements.Extent.Text-join"`n"))
foreach($name in @('inputs','results','logs','comsol','simion')){[IO.Directory]::CreateDirectory((Join-Path $Run $name))|Out-Null}
$package=@{native_path_preparation=@{calls=0;elapsed_seconds=0.0;transport_bytes=0L};run_dir=$Run;artifact_run_dir=$Run;input_dir=(Join-Path $Run inputs);result_dir=(Join-Path $Run results);log_dir=(Join-Path $Run logs);run_config=(Join-Path $Run run_config.json)}
[IO.File]::WriteAllText($package.run_config,'{"inputs":{}}')
$raw=Join-Path $Run 'comsol/saved.mph';$fact=Join-Path $Run 'comsol/solution.json'
[IO.File]::WriteAllText($raw,'TEST_ONLY_SMALL_RAW');[IO.File]::WriteAllText($fact,'{"TEST_ONLY":true,"status":"solved_saved"}')
function Write-RunJson {param($Path,$Value,$Depth);[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100))}
$ownerContext=@{completion_written=$false};$capacity=@{};$lease=$null;$guard=$null;$buildAlias=$null;$paGuards=@();$writerUnknown=$false;$hostReleaseUnknown=$false;$writersStopped=$true
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$phaseTimings=[ordered]@{};$stageClock=[Diagnostics.Stopwatch]::StartNew();$runClock=[Diagnostics.Stopwatch]::StartNew();$stage='extract';$ResultPath='TEST_ONLY_RESULT';$DryRun=$false
$completedComsolExports=$null;$completedSimionExports=$null;$reusedComsol=$false;$comsolSourceStage='solved_saved';$comsolNativeExecuted=$false
$reusedParticleSolution=$false;$reusedBaseline=$false;$reusedReplay=$false;$reusedParticleExports=$false;$plan=@{particle_count=2;sample_points=@{count=2}}
$failure=$null;try{throw 'PRIMARY_EXTRACTION_FAILURE'}catch{$failure=$_}
$script:called=$false
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure)
 if($Status-ne'failed'-or-not$WritersStopped-or$OriginalFailure.Exception.Message-ne'PRIMARY_EXTRACTION_FAILURE'){throw 'owner changed completion or primary failure'}
 if($OutputPaths-notcontains$raw-or$OutputPaths-notcontains$fact){throw 'saved original output omitted'}
 if($Summary.failure_reason-ne'PRIMARY_EXTRACTION_FAILURE'-or$Summary.failure_stage-ne'extract'){throw 'owner lost failure stage/reason'}
 $script:called=$true;$Context.completion_written=$true
}
. $finalizer
if(-not$called-or$failure.Exception.Message-ne'PRIMARY_EXTRACTION_FAILURE'-or[IO.File]::ReadAllText($raw)-ne'TEST_ONLY_SMALL_RAW'){throw 'finalizer adapter failed or changed raw model'}
'RAW_COMPLETION_ADAPTER=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/"complete.ps1";script.write_text(code,encoding="utf-8",newline="\n")
            for owner in ("paired_accelerator_static_field","paired_accelerator_pulse"):
                result=subprocess.run([shutil.which("pwsh"),"-NoProfile","-File",str(script),str(ROOT/f"integrations/workflows/{owner}/execute.ps1"),str(root/owner),str(ROOT)],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn("RAW_COMPLETION_ADAPTER=PASS",result.stdout)
