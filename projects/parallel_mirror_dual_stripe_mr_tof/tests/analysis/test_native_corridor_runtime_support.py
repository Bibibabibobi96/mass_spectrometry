"""Behavior fixture for bounded private native-family preparation."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT = Path(__file__).resolve().parents[2]


class NativeCorridorRuntimeSupportTest(unittest.TestCase):
    def test_managed_family_survives_session_and_resumes_without_reconstruction(self):
        script = r"""
param($Repo,$Root,$Python)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'projects/parallel_mirror_dual_stripe_mr_tof/simion/native_corridor_runtime_support.ps1')
$owner=Join-Path $Root 'runs/owner'
New-Item -ItemType Directory -Path (Join-Path $owner 'results') -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $owner 'run_config.json'),'{}')
$binary=Join-Path $Root 'simion.exe';[IO.File]::WriteAllText($binary,'fixture solver identity')
$script:builds=0;$script:registered=0;$script:inventories=0
function New-NativeCorridorRuntimeFamily {
  param($BankGenerationDirectory,$DestinationDirectory,$Python,$RepoRoot,$SimionExe,$ResourceLease,$RunId)
  $script:builds++
  foreach($i in 0..8){[IO.File]::WriteAllText((Join-Path $DestinationDirectory ('mrtof_analyzer_corridor.pa'+$i)),('fixture-'+$i))}
  return [pscustomobject]@{controller_path=(Join-Path $DestinationDirectory 'mrtof_analyzer_corridor.pa0');resource_lease=$ResourceLease;
    receipt=[ordered]@{run_id=$RunId;cache_key=('A'*64);generation_sha256=('B'*64);generation_directory=$BankGenerationDirectory;source_raw=@{bytes=10};controller_path='temporary'}}
}
function Invoke-RunCapacityLifecycleAdapter {param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig)
  if($Action-ne'register-writing'-or$RunConfig-ne(Join-Path $owner 'run_config.json')){throw 'Wrong owner accounting'}
  $script:registered++
}
function Write-VerifiedRunManifest {param($Python,$RepoRoot,$RunConfig,$Status,$Software,$Outputs)
  if($Status-ne'checkpoint'-or$RunConfig-ne(Join-Path $owner 'run_config.json')-or
     $Outputs-notcontains(Join-Path $owner 'results/native_corridor_runtime_checkpoint.json')){throw 'Prepared family lacks owner manifest binding'}
  Write-Output 'RUN_MANIFEST=PASS'
  Write-Output 'RUN_MANIFEST_VERIFY=PASS'
}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
  if($script:registered-ne1){throw 'Commitment reduced before resident accounting'}
  $Session.committed_new_bytes=$RemainingCommittedNewBytes
}
$originalInventory=${function:Get-NativeRuntimeInventory}
function Get-NativeRuntimeInventory {param($Directory,$Python,$RepoRoot)
  $script:inventories++
  & $originalInventory -Directory $Directory -Python $Python -RepoRoot $RepoRoot
}
function New-Session {
  return [pscustomobject]@{lease_id='lease';directory=(Join-Path $owner 'runtime/native_corridor_family');runtime=$null;
    owner_run_directory=$owner;owner_run_config=(Join-Path $owner 'run_config.json');resident_bytes=[int64]0;
    checkpoint_path=(Join-Path $owner 'results/native_corridor_runtime_checkpoint.json')}
}
$capacity=[pscustomobject]@{status='active';lease_id='lease';artifact_root=$Root;committed_new_bytes=[int64]125}
$session=New-Session
$args=@{Session=$session;CapacityWorkflowSession=$capacity;BankGenerationDirectory=$Root;CacheKey=('A'*64);GenerationSha256=('B'*64);
  Python=$Python;RepoRoot=$Repo;SimionExe=$binary;ResourceLease=@{};RunId='first'}
try{
  $first=Get-NativeCorridorRuntimeFamily @args
  if(@($first).Count-ne1-or$null-eq$first.PSObject.Properties['resource_lease']){throw 'Manifest logging polluted the runtime return value'}
  $second=Get-NativeCorridorRuntimeFamily @args
  if($script:builds-ne1-or$script:inventories-ne1-or-not$second.receipt.reused){throw 'Active session redundantly materialized or hashed'}
  if($session.resident_bytes-ne81-or$capacity.committed_new_bytes-ne25){throw 'Family resident and commitment double-counted'}
  $args.CacheKey='C'*64
  try{$null=Get-NativeCorridorRuntimeFamily @args;throw 'Wrong bank accepted'}catch{if($_.Exception.Message-notlike'*another bank*'){throw}}
  $args.CacheKey='A'*64;$capacity.lease_id='other'
  try{$null=Get-NativeCorridorRuntimeFamily @args;throw 'Wrong lease accepted'}catch{if($_.Exception.Message-notlike'*active capacity lease*'){throw}}
  $capacity.lease_id='lease'
  $alias=$session.execution_alias
  Suspend-NativeCorridorRuntimeSession -Session $session
  if((Test-Path -LiteralPath $alias)-or-not(Test-Path -LiteralPath $session.directory)){throw 'Suspend deleted payload or left alias'}
  $session=New-Session;$args.Session=$session;$args.RunId='resumed'
  $resumed=Get-NativeCorridorRuntimeFamily @args
  if($script:builds-ne1-or$script:inventories-ne1-or-not$resumed.receipt.reused){throw 'Cross-session resume rebuilt or reread the sealed payload'}
  $blocked=$false;try{[IO.File]::WriteAllText($resumed.controller_path,'changed')}catch{$blocked=$true}
  if(-not$blocked){throw 'Restored private family is writable'}
  Suspend-NativeCorridorRuntimeSession -Session $session
  $path=Join-Path $session.directory 'mrtof_analyzer_corridor.pa1'
  (Get-Item -LiteralPath $path).IsReadOnly=$false;[IO.File]::WriteAllText($path,'changed-size');(Get-Item -LiteralPath $path).IsReadOnly=$true
  $session=New-Session;$args.Session=$session
  try{$null=Get-NativeCorridorRuntimeFamily @args;throw 'Changed byte count accepted'}catch{if($_.Exception.Message-notlike'*member byte count differs*'){throw}}
  if($script:builds-ne1-or-not(Test-Path -LiteralPath $session.directory)){throw 'Invalid family was reconstructed or deleted'}
  [IO.File]::WriteAllText($binary,'changed generator')
  try{$null=Get-NativeCorridorRuntimeFamily @args;throw 'Changed generator accepted'}catch{if($_.Exception.Message-notlike'*generator identity differs*'){throw}}
  Write-Output 'MANAGED_NATIVE_RECOVERY=PASS'
}finally{
  Suspend-NativeCorridorRuntimeSession -Session $session
  Get-ChildItem -LiteralPath $owner -Recurse -File|ForEach-Object{$_.IsReadOnly=$false}
}
"""
        with TemporaryDirectory(prefix='mrtof-native-checkpoint-') as temporary:
            fixture = Path(temporary) / 'test.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture), str(PROJECT.parents[1]), temporary,
                 str(PROJECT.parents[1] / '.venv/Scripts/python.exe')],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('MANAGED_NATIVE_RECOVERY=PASS', result.stdout)

    @unittest.skipUnless(os.environ.get('SIMION_EXE'), 'requires explicit SIMION_EXE')
    def test_real_fast_adjust_reopens_guarded_family_without_writing(self) -> None:
        script = r"""
param($Repo,$Root,$Simion)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/host_execution_lease.ps1')
$lease=$null;$guards=@()
try{
  $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId ('native-readonly-fixture-'+[guid]::NewGuid().ToString('N'))
  $project=Join-Path $Repo 'projects/parallel_mirror_dual_stripe_mr_tof'
  & $Simion --nogui --noprompt lua (Join-Path $project 'tests/simion/test_native_local_family_fixture.lua') $Root (Join-Path $project 'simion/assemble_native_local_family.lua')
  if($LASTEXITCODE-ne0){throw 'Tiny native fixture construction failed'}
  $iobFixture=Join-Path $project 'tests/simion/test_native_corridor_iob_fixture.lua'
  & $Simion --nogui --noprompt lua $iobFixture $Root prepare
  if($LASTEXITCODE-ne0){throw 'Tiny IOB fixture construction failed'}
  $before=@()
  foreach($id in 0..8){
    $path=Join-Path $Root ('fixture.pa'+$id)
    $before+=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    (Get-Item -LiteralPath $path).IsReadOnly=$true
    $guards+=,[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  }
  & $Simion --nogui --noprompt lua (Join-Path $project 'simion/verify_native_corridor_family.lua') (Join-Path $Root 'fixture.pa0')
  if($LASTEXITCODE-ne0){throw 'Guarded Fast Adjust failed'}
  foreach($name in @('global.pa','accelerator.pa','detector.pa')){
    $path=Join-Path $Root $name
    (Get-Item -LiteralPath $path).IsReadOnly=$true
    $guards+=,[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  }
  $build=@('--nogui','--noprompt','lua',(Join-Path $project 'simion/build_native_corridor_iob.lua'),'--',
    (Join-Path $Repo 'common/simion/assets/iob_instance_seeds/4_instance_seed.iob'),
    (Join-Path $Root 'global.pa'),(Join-Path $Root 'fixture.pa0'),(Join-Path $Root 'accelerator.pa'),(Join-Path $Root 'detector.pa'),
    (Join-Path $Root 'fixture.iob'),(Join-Path $Root 'program.lua'),(Join-Path $Root 'source.fly2'),
    (Join-Path $Root 'operating.lua'),(Join-Path $Root 'voltage_map.lua'),(Join-Path $project 'simion/native_corridor_priority_contract.lua'),
    '0','0','0','0','0','0','0','0','0','8','0','0')
  & $Simion @build
  if($LASTEXITCODE-ne0){throw 'Guarded production native IOB builder failed'}
  & $Simion --nogui --noprompt lua $iobFixture $Root inspect
  if($LASTEXITCODE-ne0){throw 'Production native IOB reload failed'}
  foreach($id in 0..8){
    if((Get-FileHash -LiteralPath (Join-Path $Root ('fixture.pa'+$id)) -Algorithm SHA256).Hash-ne$before[$id]){throw 'Guarded member changed'}
  }
  Write-Output 'GUARDED_NATIVE_FAST_ADJUST=PASS'
}finally{
  foreach($guard in $guards){$guard.Dispose()}
  Get-ChildItem -LiteralPath $Root -File|ForEach-Object{$_.IsReadOnly=$false}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease}
}
"""
        with TemporaryDirectory(prefix='mrtof-guard-fixture-') as temporary:
            root = Path(temporary)
            fixture = root / 'verify.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['C:/Program Files/PowerShell/7/pwsh.exe', '-NoProfile', '-File',
                 str(fixture), str(PROJECT.parents[1]), str(root), os.environ['SIMION_EXE']],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotRegex(result.stdout + result.stderr, r'(?m)^error,|Failed saving PA|Aborting PA updates')
        self.assertIn('GUARDED_NATIVE_FAST_ADJUST=PASS', result.stdout)
        self.assertIn('MRTOF_NATIVE_CORRIDOR_IOB_BUILD=PASS', result.stdout)
        self.assertIn('NATIVE_CORRIDOR_IOB_FIXTURE_RELOAD=PASS', result.stdout)

    def test_streams_one_guarded_source_and_releases_it_before_next(self) -> None:
        bank = {
            'cache_key': 'A' * 64, 'generation_sha256': 'B' * 64,
            'raw': {'name': 'field.pa#', 'bytes': 3, 'sha256': 'C' * 64},
            'responses': [dict(response_id=i, name=f'field.response{i}.pa', bytes=3, sha256='D' * 64) for i in range(1, 9)],
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = """
param($Support,$Root,$Bank)
$ErrorActionPreference='Stop'
. $Support
$script:active=0;$script:copies=0;$script:stages=@()
function Invoke-RunToolRootContext { param($RepoRoot,$Operation) return $Bank }
function New-ShortPaCopy {
  param($Source,$Destination,$ExpectedBytes,$ExpectedSha256,[switch]$GuardDestinationReadOnly)
  if($script:active-ne0){throw 'More than one source retained'}
  $script:active++;$script:copies++
  [IO.File]::WriteAllText($Destination,'raw')
  return $Destination
}
function Remove-ShortPaCopy { param($Path) Remove-Item -LiteralPath $Path;$script:active-- }
function Update-HostResourceStage { param($Lease,$Stage,$Budget,$RetainedMemoryBytes) $script:stages+=@($Stage);return $Lease }
function Get-HostResourceBudget { param($Role,$Stage) return @{} }
function Invoke-FixtureSimion {
  $destination=$args[-1]
  [IO.File]::WriteAllText($destination,'new object')
  $global:LASTEXITCODE=0
}
$result=New-NativeCorridorRuntimeFamily -BankGenerationDirectory $Root -DestinationDirectory (Join-Path $Root 'private') -Python 'unused' -RepoRoot $Root -SimionExe 'Invoke-FixtureSimion' -ResourceLease ([pscustomobject]@{id='fixture'}) -RunId 'fixture'
if($script:active-ne0-or$script:copies-ne9){throw 'Source release/count differs'}
if(($script:stages-join',')-ne'pa_refine,mrtof_prepare'){throw 'Controller heavy stage differs'}
if(@(Get-ChildItem (Join-Path $Root 'private') -File).Count-ne9){throw 'Expected controller and eight responses'}
if(-not(Test-Path $result.controller_path)){throw 'Controller missing'}
if($result.receipt.published_native_members_opened-or$result.receipt.response_refine_performed){throw 'Wrong provenance'}
Write-Output 'STREAM_FIXTURE=PASS'
"""
            path = root / 'test_stream.ps1'
            path.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-NonInteractive', '-File', str(path),
                 '-Support', str(PROJECT / 'simion/native_corridor_runtime_support.ps1'),
                 '-Root', str(root), '-Bank', json.dumps(bank)],
                cwd=PROJECT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('STREAM_FIXTURE=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
