"""Real lease CRUD on two roots; metadata only, no solver or payload scan."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.capacity_ledger import initialize_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases
from common.contracts.write_run_manifest import build_run_manifest, file_record
from common.contracts.run_capacity_lifecycle import resolve_consumed_run_capacity_owner

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows shared reader required")
class CrossRootProtectionTests(unittest.TestCase):
    def source(self, root):
        root.mkdir()
        initialize_capacity_ledger(root, objects=[])
        run = root / "projects/fixture/runs/20261030_010000__test__python__source"
        run.mkdir(parents=True)
        config = run / "run_config.json"
        config.write_text(json.dumps(dict(schema_version=1, run_id=run.name, project="fixture", mode="software",
            inputs={}, capacity_ledger_lifecycle=dict(schema_version=1, enabled=True,
                artifact_root=str(root), light_evidence_budget_bytes=1024))), encoding="utf-8")
        manifest = run / "run_manifest.json"
        manifest.write_text(json.dumps(build_run_manifest(config, "success")), encoding="utf-8")
        return run, dict(manifest_record=file_record(manifest), protected_paths=[str(run)], protected_cache_keys=[])

    def test_source_owner_uses_bound_metadata_and_rejects_incomplete_or_conflicting_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root, target = base / "source", base / "target"
            run, reference = self.source(source_root)
            target.mkdir()
            manifest = run / "run_manifest.json"
            config_path = run / "run_config.json"
            with patch.dict("os.environ", {"MASS_SPECTROMETRY_ARTIFACT_ROOT": str(target)}), \
                    patch("common.contracts.run_capacity_lifecycle._inventory", side_effect=AssertionError("must not scan source payload")):
                self.assertEqual(resolve_consumed_run_capacity_owner(reference["manifest_record"]),
                                 dict(artifact_root=str(source_root.resolve()), run_directory=str(run.resolve())))
            journal = run / ".run_terminal_publication.json"
            journal.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "publication is incomplete"):
                resolve_consumed_run_capacity_owner(reference["manifest_record"])
            journal.unlink()
            manifest.write_bytes(manifest.read_bytes() + b"\n")
            with self.assertRaisesRegex(AssertionError, "byte count changed"):
                resolve_consumed_run_capacity_owner(reference["manifest_record"])
            config = json.loads(config_path.read_text())
            config["paths"] = dict(artifact_root=str(target))
            config_path.write_text(json.dumps(config), encoding="utf-8")
            manifest.write_text(json.dumps(build_run_manifest(config_path, "success")), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "path context and capacity owner differ"):
                resolve_consumed_run_capacity_owner(file_record(manifest))
            config.pop("paths")
            config.pop("capacity_ledger_lifecycle")
            config_path.write_text(json.dumps(config), encoding="utf-8")
            manifest.write_text(json.dumps(build_run_manifest(config_path, "success")), encoding="utf-8")
            legacy = file_record(manifest)
            self.assertEqual(resolve_consumed_run_capacity_owner(legacy, consumer_artifact_root=source_root)["artifact_root"], str(source_root.resolve()))
            with self.assertRaisesRegex(ValueError, "cross-root source has no frozen capacity owner"):
                resolve_consumed_run_capacity_owner(legacy, consumer_artifact_root=target)

    def test_source_root_has_zero_commitment_and_release_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_root, target = base / "source", base / "target"
            run, reference = self.source(source_root)
            target.mkdir()
            initialize_capacity_ledger(target, objects=[])
            manifest = run / "run_manifest.json"
            before = manifest.read_bytes()
            request = base / "request.json"
            request.write_text(json.dumps(dict(target=str(target), references=[reference, reference])), encoding="utf-8")
            script = base / "check.ps1"
            script.write_text(r'''param($Repo,$Python,$Request)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
function Invoke-ArtifactWorkflowCapacityAdmission {return @{satisfied=$true;fixture_admission=$true}}
$data=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -AsHashtable
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $data.target `
 -RunDirectory (Join-Path $data.target 'projects/fixture/runs/new') -CommittedNewBytes 1024 -SourceReferences @($data.references)
if($session.source_protection_leases.Count-ne1){throw 'Duplicate source references created duplicate leases'}
$source=$session.source_protection_leases[0]
if($source.artifact_root-eq$session.artifact_root){throw 'Source root became a target object'}
$lease=Get-Content -LiteralPath (Join-Path $source.artifact_root ('common/capacity_protection_leases/'+$source.lease_id+'.json')) -Raw|ConvertFrom-Json
if($lease.committed_new_bytes-ne0-or$session.committed_new_bytes-ne1024){throw 'Borrowed bytes were reserved as new payload'}
# No release occurs until the owner explicitly settles its writers.
if(-not(Test-Path -LiteralPath (Join-Path $source.artifact_root ('common/capacity_protection_leases/'+$source.lease_id+'.json')))){throw 'Unsettled source protection disappeared'}
$script:realCapacity=${function:Invoke-RunCapacityCommand};$script:rejectSourceRelease=$true
function Invoke-RunCapacityCommand {
 param($Python,$RepoRoot,$Arguments,$FailureLabel)
 if($script:rejectSourceRelease-and$Arguments-contains'--delete-protection-lease'-and$Arguments-contains$source.lease_id){
  $script:rejectSourceRelease=$false;throw 'fixture source release failure'
 }
 & $script:realCapacity @PSBoundParameters
}
$caught=$false
try{Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session|Out-Null}catch{
 if($_.Exception.Message-ne'fixture source release failure'){throw};$caught=$true
 if($_.Exception.Data['capacity_session']-ne$session){throw 'Source recovery descriptor was lost'}
}
if(-not$caught-or$source.status-ne'active'){throw 'Failed source release was hidden'}
$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
if($session.status-ne'released'-or$source.status-ne'released'){throw 'Repeated finalization did not release the original leases'}
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ROOT), sys.executable, str(request)],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(manifest.read_bytes(), before)
            self.assertFalse(load_capacity_protection_leases(source_root)["protected_paths"])
            self.assertFalse(load_capacity_protection_leases(target)["protected_paths"])

    def test_alias_deduplication_and_failed_second_source_pin_roll_back(self):
        for scenario in ("alias", "second_pin_failure"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                first, second, target = base / "source-a", base / "source-b", base / "target"
                run, reference = self.source(first)
                _, other = self.source(second)
                target.mkdir()
                initialize_capacity_ledger(target, objects=[])
                alias = base / "alias"
                aliased = dict(reference, manifest_record=dict(reference["manifest_record"],
                    path=str(alias / run.relative_to(first) / "run_manifest.json")),
                    protected_paths=[str(alias / run.relative_to(first))])
                request = base / "request.json"
                request.write_text(json.dumps(dict(scenario=scenario, target=str(target), first=str(first),
                    second=str(second), alias=str(alias), references=[reference, aliased if scenario == "alias" else other])), encoding="utf-8")
                script = base / "check.ps1"
                script.write_text(r'''param($Repo,$Python,$Request)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
function Invoke-ArtifactWorkflowCapacityAdmission {return @{satisfied=$true;fixture_admission=$true}}
$data=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -AsHashtable
if($data.scenario-eq'alias'){$null=New-Item -ItemType Junction -Path $data.alias -Target $data.first}
$script:realCapacity=${function:Invoke-RunCapacityCommand};$script:createdRoots=@()
function Invoke-RunCapacityCommand {
 param($Python,$RepoRoot,$Arguments,$FailureLabel)
 if($Arguments-contains'--create-protection-lease'){
  $root=$Arguments[[Array]::IndexOf($Arguments,'--artifact-root')+1]
  if($data.scenario-eq'second_pin_failure'-and$root-eq$data.second){throw 'fixture second source pin failure'}
  $script:createdRoots+=@($root)
 }
 & $script:realCapacity @PSBoundParameters
}
try{
 $caught=$false
 try{
  $session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $data.target `
   -RunDirectory (Join-Path $data.target 'projects/fixture/runs/new') -CommittedNewBytes 1024 -SourceReferences @($data.references)
 }catch{
  if($data.scenario-ne'second_pin_failure'-or$_.Exception.Message-ne'fixture second source pin failure'){throw}
  if($_.Exception.Data['capacity_lease_cleanup'].status-ne'released'){throw 'Failed source acquisition lost cleanup facts'}
  $caught=$true
 }
 if($data.scenario-eq'alias'){
  if($session.source_protection_leases.Count-ne1){throw 'Physical alias created duplicate source owners'}
  $source=$session.source_protection_leases[0]
  if(@($source.protected_paths|Where-Object{$_.StartsWith($data.alias,[StringComparison]::OrdinalIgnoreCase)}).Count){throw 'Temporary alias leaked into the persisted source descriptor'}
  $leasePath=Join-Path $source.artifact_root ('common/capacity_protection_leases/'+$source.lease_id+'.json')
  $before=[datetimeoffset](Get-Content -LiteralPath $leasePath -Raw|ConvertFrom-Json).expires_at_utc
  Remove-Item -LiteralPath $data.alias -Force
  $session.lease_ttl_seconds+=100
  $null=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
  $after=Get-Content -LiteralPath $leasePath -Raw|ConvertFrom-Json
  if([datetimeoffset]$after.expires_at_utc-le$before-or$after.committed_new_bytes-ne0){throw 'Ordinary Update failed to renew the original zero-commit source lease'}
  $null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
 }elseif(-not$caught-or$script:createdRoots.Count-ne1-or$script:createdRoots[0]-ne$data.first){
  throw 'Second-source failure did not occur after one real source pin'
 }
}finally{if(Test-Path -LiteralPath $data.alias){Remove-Item -LiteralPath $data.alias -Force}}
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ROOT), sys.executable, str(request)],
                                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for root in (first, second, target):
                    self.assertFalse(load_capacity_protection_leases(root)["protected_paths"])

    def test_same_root_guard_is_held_until_initial_and_expanded_pin_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "source"
            run, reference = self.source(root)
            alias = base / "alias"
            aliased = dict(reference, protected_paths=[str(alias / run.relative_to(root))])
            request = base / "request.json"
            request.write_text(json.dumps(dict(root=str(root), run=str(run), alias=str(alias),
                references=[aliased], canonical_references=[reference])), encoding="utf-8")
            script = base / "guard.ps1"
            script.write_text(r'''param($Repo,$Python,$Request)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
function Invoke-ArtifactWorkflowCapacityAdmission {return @{satisfied=$true;fixture_admission=$true}}
$data=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -AsHashtable
$null=New-Item -ItemType Junction -Path $data.alias -Target $data.root
$script:realCapacity=${function:Invoke-RunCapacityCommand};$script:pinChecks=0;$script:requireGuard=$true
function Invoke-RunCapacityCommand {
 param($Python,$RepoRoot,$Arguments,$FailureLabel)
 if($script:requireGuard-and($Arguments-contains'--create-protection-lease'-or$Arguments-contains'--renew-protection-lease')){
  $stream=[IO.File]::Open((Join-Path $data.run '.run_terminal_publication.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
  $exclusive=$false
  try{try{$stream.Lock(0,1);$stream.Unlock(0,1);$exclusive=$true}catch [IO.IOException]{}}finally{$stream.Dispose()}
  if($exclusive){throw 'Same-root source guard was released before actual pin publication'}
  $script:pinChecks++
 }
 & $script:realCapacity @PSBoundParameters
}
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -ArtifactRoot $data.root `
 -RunDirectory (Join-Path $data.root 'projects/fixture/runs/new') -CommittedNewBytes 1024 -SourceReferences @($data.references)
if($session.source_protection_leases.Count){throw 'Same-root source created a second lease'}
if(@($session.protected_paths|Where-Object{$_.StartsWith($data.alias,[StringComparison]::OrdinalIgnoreCase)}).Count){throw 'Same-root session retained an execution alias'}
Remove-Item -LiteralPath $data.alias -Force
$script:requireGuard=$false
$null=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
$script:requireGuard=$true
$null=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session -SourceReferences @($data.canonical_references)
if($script:pinChecks-ne2){throw 'Initial or expanded source pin did not execute'}
$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $Repo -Session $session
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ROOT), sys.executable, str(request)],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(load_capacity_protection_leases(root)["protected_paths"])
