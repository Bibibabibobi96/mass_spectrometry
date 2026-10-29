"""Software fixtures for the private family namespace; no SIMION is launched."""
from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import advance_pa_family_cache_transaction
from common.simion.test_pa_family_cache import identity


REPO = Path(__file__).resolve().parents[2]


class NativeFastAdjustRuntimeSupportTests(unittest.TestCase):
    def test_governed_transaction_uses_guarded_private_copy_without_generation(self):
        from common.contracts.capacity_protection import create_capacity_protection_lease
        from common.simion.test_pa_family_cache import PAFamilyCacheTest

        fixture = PAFamilyCacheTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        artifacts, cache = fixture._artifact_cache()
        root = fixture.root
        exporter = root / "export.lua"
        exporter.write_text("-- inert exporter identity", encoding="utf-8")
        names = ("field.pa#", "field.response1.pa", "responses.json")
        recipe = dict(schema_version=2, source_location="build_scratch", receipt_name="responses.json",
            exporter_path=str(exporter), exports=[dict(response_id=1, source_name="field.pa1", standalone_name="field.response1.pa")])
        first = advance_pa_family_cache_transaction(cache, identity(), names, owner=fixture.artifact_owner,
            producer_run_config=fixture.producer_run_config, response_receipt=recipe)
        for name in names[:-1]:
            (first.build_directory / name).write_bytes(b"inert PA bytes")
        (first.scratch_directory / "field.pa1").write_bytes(b"inert PA bytes")
        sealed = advance_pa_family_cache_transaction(cache, identity(), names, owner=fixture.artifact_owner)
        # No source native family is available. Only the actual sealed owner
        # inventory, raw array and detached response may supply the copy.
        (first.scratch_directory / "field.pa1").chmod(stat.S_IWRITE)
        (first.scratch_directory / "field.pa1").unlink()
        run = fixture.producer_run_config.parent
        create_capacity_protection_lease(artifacts, lease_id="runtime-fixture", owner="runtime-fixture", ttl_seconds=300,
            protected_cache_keys=[sealed.cache_key], protected_paths=[run])
        session = dict(role="artifact_workflow_capacity_session", status="active", artifact_root=str(artifacts),
            lease_id="runtime-fixture", owner="runtime-fixture", protected_paths=[str(run)])
        (root / "session.json").write_text(json.dumps(session), encoding="utf-8")
        before = {p.name: file_sha256(p) for p in first.build_directory.iterdir()}
        shim = root / "native.ps1"
        shim.write_text(r'''
if($args[4]-eq'--fixture-verify'){
 $refused=$false
 try{$stream=[IO.File]::Open([string]$args[5],[IO.FileMode]::Open,[IO.FileAccess]::Write);$stream.Dispose()}catch{$refused=$true}
 if(-not$refused){throw 'standalone verification copy was not guarded'}
 exit 0
}
if($args[4]-notin@('--controller','--append')){throw 'Unexpected software native operation'}
[IO.File]::WriteAllBytes([string]$args[6],[IO.File]::ReadAllBytes([string]$args[5]));exit 0
''', encoding="utf-8")
        driver = root / "driver.ps1"
        driver.write_text(r'''
param($Repo,$Python,$Root,$Transaction,$Key,$Inventory,$Owner,$Producer,$Shim)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/simion/native_fast_adjust_runtime_support.ps1')
function Get-HostResourceBudget {param($Role,$Stage);return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes);return $Lease}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation);Push-Location $RepoRoot;try{&$Operation}finally{Pop-Location}}
$base=@{TransactionPath=$Transaction;ExpectedCacheKey=$Key;ExpectedInventorySha256=$Inventory;ExpectedOwner=$Owner;
 ProducerRunConfig=$Producer;CapacitySessionPath=(Join-Path $Root 'session.json');ReceiptName='responses.json';RawName='field.pa#';
 ExpectedResponseIds=@(1);Python=$Python;RepoRoot=$Repo;SimionExe=$Shim;ResourceLease=@{fixture=$true};RunId='fixture'}
$rows=@()
foreach($label in @('valid','wrong-owner','wrong-inventory','wrong-session')){
 $args=@{}+$base
 if($label-eq'wrong-owner'){$args.ExpectedOwner='other-owner'}
 if($label-eq'wrong-inventory'){$args.ExpectedInventorySha256='F'*64}
 if($label-eq'wrong-session'){
  $session=Get-Content $base.CapacitySessionPath -Raw|ConvertFrom-Json -AsHashtable
  $session.owner='other-workflow';$session|ConvertTo-Json|Set-Content (Join-Path $Root 'wrong-session.json')
  $args.CapacitySessionPath=Join-Path $Root 'wrong-session.json'
 }
 $ops=[Collections.Generic.List[object]]::new()
 try{
  $result=New-NativeFastAdjustRuntimeFamily @args -FamilyPrefix $label -DestinationDirectory (Join-Path $Root $label) `
   -NativeOperationObservations $ops -GetResponseVerificationArguments {
    param($FamilyStem,$StandalonePath,$ResponseId)
    return @('--nogui','--noprompt','lua','software-fixture','--fixture-verify',$StandalonePath)
   }
  $rows+=@{label=$label;status='pass';receipt=$result.receipt;operations=@($ops.ToArray())}
 }catch{$rows+=@{label=$label;status='rejected';error=$_.Exception.Message;operations=@($ops.ToArray())}}
}
$rows|ConvertTo-Json -Depth 32|Set-Content (Join-Path $Root 'report.json')
''', encoding="utf-8")
        process = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO), sys.executable,
            str(root), str(first.transaction_directory / "transaction.json"), sealed.cache_key, sealed.inventory_sha256,
            fixture.artifact_owner, str(fixture.producer_run_config), str(shim)], cwd=REPO,
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=90)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        rows = json.loads((root / "report.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(rows[0]["status"], "pass", (rows, process.stdout, process.stderr))
        self.assertIsNone(rows[0]["receipt"]["generation_sha256"])
        self.assertIsNone(rows[0]["receipt"]["generation_directory"])
        self.assertEqual(rows[0]["receipt"]["source_transaction"]["inventory_sha256"], sealed.inventory_sha256)
        self.assertEqual(rows[0]["receipt"]["verified_response_ids"], [1])
        self.assertEqual(len(rows[0]["operations"]), 3)
        for row in rows[1:]:
            self.assertEqual(row["status"], "rejected", row)
            self.assertEqual(row["operations"], [])
        self.assertEqual(before, {p.name: file_sha256(p) for p in first.build_directory.iterdir()})
        self.assertFalse(list(cache.rglob("cache_manifest.json")))

    def test_private_namespaces_collisions_defaults_and_native_failure_receipts(self):
        with tempfile.TemporaryDirectory(prefix="native_family_namespace_") as directory:
            root = Path(directory)
            exporter = root / "export.lua"
            exporter.write_text("-- software fixture only", encoding="utf-8")
            recipe = {
                "schema_version": 2, "source_location": "build_scratch",
                "receipt_name": "responses.json", "exporter_path": str(exporter),
                "exports": [{"response_id": 1, "source_name": "field.pa1",
                             "standalone_name": "field.response1.pa"}],
            }
            names = ("field.pa#", "field.response1.pa", "responses.json")
            cache = root / "cache"
            building = advance_pa_family_cache_transaction(cache, identity(), names,
                owner="namespace-test", response_receipt=recipe)
            for name in names[:-1]:
                (building.build_directory / name).write_bytes(("fixture:" + name).encode())
            (building.scratch_directory / "field.pa1").write_bytes(b"fixture native response")
            sealed = advance_pa_family_cache_transaction(cache, identity(), names,
                owner="namespace-test", response_receipt=recipe)
            evidence_file = root / "verification.txt"
            evidence_file.write_text("software publication fixture; no physics claim", encoding="utf-8")
            evidence = {
                "schema_version": 1, "role": "simion_pa_family_verification", "status": "pass",
                "cache_key": sealed.cache_key, "inventory_sha256": sealed.inventory_sha256,
                "solver_release": "SIMION 2020", "verifier_path": str(exporter),
                "verifier_sha256": file_sha256(exporter),
                "verification_output_path": str(evidence_file),
                "verification_output_sha256": file_sha256(evidence_file),
            }
            published = advance_pa_family_cache_transaction(cache, identity(), names,
                owner="namespace-test", response_receipt=recipe, verification_evidence=evidence,
                recovery_policy="none")
            generation = published.generation_directory
            before = {p.name: file_sha256(p) for p in generation.iterdir() if p.is_file()}
            shim = root / "native_fixture.ps1"
            shim.write_text(r"""
if($args[4]-eq'--controller'){
 [IO.File]::WriteAllBytes([string]$args[6],[IO.File]::ReadAllBytes([string]$args[5]));exit 0
}
if($args[4]-ne'--append'){throw 'unexpected fixture command'}
if($env:NATIVE_FIXTURE_FAIL-eq'1'){exit 9}
[IO.File]::WriteAllBytes([string]$args[6],[IO.File]::ReadAllBytes([string]$args[5]));exit 0
""", encoding="utf-8")
            driver = root / "driver.ps1"
            driver.write_text(r"""
param($Repo,$Python,$Root,$Generation,$Key,$GenerationHash,$Shim)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/simion/native_fast_adjust_runtime_support.ps1')
# Native execution and admission are fixture adapters here; the tests run
# under the enclosing ordinary GATE lease and launch no commercial process.
function Get-HostResourceBudget { param($Role,$Stage); return @{} }
function Update-HostResourceStage { param($Lease,$Stage,$Budget,$RetainedMemoryBytes); return $Lease }
function Invoke-RunToolRootContext { param($RepoRoot,$Operation); Push-Location $RepoRoot;try{&$Operation}finally{Pop-Location} }
$base=@{GenerationDirectory=$Generation;ExpectedCacheKey=$Key;ExpectedGenerationSha256=$GenerationHash;
 ReceiptName='responses.json';RawName='field.pa#';ExpectedResponseIds=@(1);Python=$Python;RepoRoot=$Repo;
 SimionExe=$Shim;ResourceLease=@{fixture=$true};RunId='namespace-fixture'}
$report=[Collections.Generic.List[object]]::new()
function Run-Fixture($Label,$Destination,$Prefix,$Scoped,$Callback=$null){
 $ops=[Collections.Generic.List[object]]::new()
 try{
  $result=New-NativeFastAdjustRuntimeFamily @base -DestinationDirectory $Destination -FamilyPrefix $Prefix `
   -RequireEmptyFamilyNamespace:$Scoped -NativeOperationObservations $ops -InvokeNativeOperation $Callback
  $report.Add(@{label=$Label;status='pass';controller=$result.controller_path;operations=@($ops.ToArray())})
 }catch{$report.Add(@{label=$Label;status='rejected';error=$_.Exception.Message;operations=@($ops.ToArray())})}
}
$shared=Join-Path $Root 'shared';New-Item -ItemType Directory $shared|Out-Null
[IO.File]::WriteAllText((Join-Path $shared 'unrelated.txt'),'keep')
Run-Fixture 'default-nonempty' $shared 'alpha' $false
Run-Fixture 'first' $shared 'alpha' $true
Run-Fixture 'second' $shared 'beta' $true
Run-Fixture 'repeat' $shared 'alpha' $true
$index=0
foreach($name in @('alpha.pa#','alpha.pa0','alpha.response1.pa','alpha.pa-surf','alpha_source_response.pa')){
 $dest=Join-Path $Root ('collision'+$index);$index++;New-Item -ItemType Directory $dest|Out-Null
 [IO.File]::WriteAllText((Join-Path $dest $name),'keep collision')
 Run-Fixture $name $dest 'alpha' $true
}
$env:NATIVE_FIXTURE_FAIL='1'
Run-Fixture 'native-failure' (Join-Path $Root 'failed') 'gamma' $true
$env:NATIVE_FIXTURE_FAIL='0'
$knownCallback={param($ArgumentList,$OperationId)
 &$Shim @ArgumentList
 return @{observation=@{exit_confirmed=$true;returncode=[int]$LASTEXITCODE};
   managed_process_completion=@{ownership_confirmed=$true;worker_exit_confirmed=$true;launcher_exit_confirmed=$true;
    stdout_drained=$true;stderr_drained=$true}}
}
Run-Fixture 'callback-known' (Join-Path $Root 'known') 'known' $true $knownCallback
$powershellCallback={param($ArgumentList,$OperationId)
 $out=Join-Path $Root 'native.stdout';$err=Join-Path $Root 'native.stderr'
 $worker=Start-Process -FilePath (Get-Process -Id $PID).Path -WindowStyle Hidden -PassThru `
  -ArgumentList (@('-NoProfile','-File',$Shim)+$ArgumentList) -RedirectStandardOutput $out -RedirectStandardError $err
 $started=$worker.StartTime.ToUniversalTime().Ticks
 $worker.WaitForExit()
 $completion=@{role='powershell_process_completion';process_id=[int]$worker.Id;process_started_at_utc_ticks=[long]$started;
  exit_confirmed=$worker.HasExited;returncode=[int]$worker.ExitCode;stdout_drained=$true;stderr_drained=$true}
 if($script:badIdentity){$completion.process_started_at_utc_ticks++}
 return @{observation=@{exit_confirmed=$worker.HasExited;returncode=[int]$worker.ExitCode;
  process_id=[int]$worker.Id;process_started_at_utc_ticks=[long]$started};managed_process_completion=$completion}
}
$script:badIdentity=$false
Run-Fixture 'powershell-known' (Join-Path $Root 'ps-known') 'ps-known' $true $powershellCallback
$script:badIdentity=$true
Run-Fixture 'powershell-wrong-identity' (Join-Path $Root 'ps-wrong') 'ps-wrong' $true $powershellCallback
# No live writer remains in this deliberately rejected fixture.
Remove-ShortPaCopy -Path (Join-Path $Root 'ps-wrong/ps-wrong.pa#')
$unknownCallback={param($ArgumentList,$OperationId)
 &$Shim @ArgumentList
 return @{observation=@{exit_confirmed=$true;returncode=[int]$LASTEXITCODE};
   managed_process_completion=@{ownership_confirmed=$false;worker_exit_confirmed=$true;launcher_exit_confirmed=$true;
    stdout_drained=$true;stderr_drained=$true}}
}
$unknown=Join-Path $Root 'unknown'
Run-Fixture 'callback-unknown' $unknown 'unknown' $true $unknownCallback
$report.Add(@{label='unknown-protection';raw_exists=(Test-Path -LiteralPath (Join-Path $unknown 'unknown.pa#'));
 source_guard_count=$global:MassSpectrometryShortPaSourceGuards.Count;
 response_created=(Test-Path -LiteralPath (Join-Path $unknown 'unknown.pa1'))})
# This fixture owns no live writer. Guard retention here is in-process only;
# it cannot claim a lock survives the PowerShell owner. Close its own copy.
Remove-ShortPaCopy -Path (Join-Path $unknown 'unknown.pa#')
$report.ToArray()|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $Root 'report.json') -Encoding utf8
""", encoding="utf-8")
            result = subprocess.run([
                "pwsh", "-NoLogo", "-NoProfile", "-File", str(driver), str(REPO), sys.executable,
                str(root), str(generation), published.cache_key, published.generation_sha256, str(shim),
            ], cwd=REPO, capture_output=True, text=True, check=False, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = {r["label"]: r for r in json.loads((root / "report.json").read_text(encoding="utf-8-sig"))}
            for label in ("first", "second", "callback-known"):
                self.assertEqual(rows[label]["status"], "pass", rows[label])
                self.assertEqual([r["observation"] for r in rows[label]["operations"]],
                                 [{"exit_confirmed": True, "returncode": 0}] * 2)
            for label, row in rows.items():
                if label in {"first", "second", "native-failure", "callback-known", "callback-unknown", "unknown-protection",
                             "powershell-known", "powershell-wrong-identity"}:
                    continue
                self.assertEqual(row["status"], "rejected", row)
                self.assertEqual(row["operations"], [])
            self.assertIn("directory must be empty", rows["default-nonempty"]["error"])
            self.assertEqual(rows["native-failure"]["status"], "rejected")
            self.assertEqual(rows["native-failure"]["operations"][-1]["observation"],
                             {"exit_confirmed": True, "returncode": 9})
            self.assertEqual(rows["callback-unknown"]["status"], "rejected")
            self.assertEqual(rows["powershell-known"]["status"], "pass", rows["powershell-known"])
            self.assertEqual(len(rows["powershell-known"]["operations"]), 2)
            self.assertEqual(rows["powershell-wrong-identity"]["status"], "rejected")
            self.assertEqual(len(rows["powershell-wrong-identity"]["operations"]), 1)
            self.assertEqual(len(rows["callback-unknown"]["operations"]), 1)
            self.assertEqual(rows["unknown-protection"], {"label": "unknown-protection",
                "raw_exists": True, "source_guard_count": 1, "response_created": False})
            self.assertEqual((root / "shared/unrelated.txt").read_text(), "keep")
            self.assertEqual({p.name for p in (root / "shared").iterdir()},
                             {"unrelated.txt", "alpha.pa0", "alpha.pa1", "beta.pa0", "beta.pa1"})
            self.assertEqual(before, {p.name: file_sha256(p) for p in generation.iterdir() if p.is_file()})


if __name__ == "__main__":
    unittest.main()
