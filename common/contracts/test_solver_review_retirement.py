from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from common.contracts.capacity_protection import create_capacity_protection_lease
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.run_capacity_lifecycle import register_writing, seal_checkpoint
from common.contracts.write_run_manifest import file_record
from common.contracts.solver_review_retirement import (
    LEGACY_INITIALIZATION_SUMMARY,
    RetirementError,
    _downstream_references,
    apply_retirement,
    main,
    plan_retirement,
    structured_target_references,
    verify_retirement,
    repair_preserved_native_file,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class RetirementWrapperTest(unittest.TestCase):
    def test_preserved_repair_wrapper_uses_capacity_and_forwards_original_identities(self):
        pwsh=shutil.which("pwsh")
        if not pwsh:self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);contracts=root/"contracts";contracts.mkdir()
            wrapper=contracts/"invoke_solver_review_retirement.ps1"
            wrapper.write_bytes(Path(__file__).with_name(wrapper.name).read_bytes())
            (root/"host_execution_lease.ps1").write_text("""
function Enter-HostExecutionLease { $global:calls.Add('host-enter');return @{} }
function Exit-HostExecutionLease { $global:calls.Add('host-exit') }
""")
            (contracts/"run_artifact_support.ps1").write_text("""
function Enter-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$Owner)
 if($CommittedNewBytes-ne63-or$ProtectedPaths.Count-ne2-or$Owner-ne'owned-payload-view-repair:p:audit'){throw 'capacity arguments differ'}
 $global:calls.Add('capacity-enter');return @{lease_id='fixture'}
}
function Exit-ArtifactWorkflowCapacitySession {$global:calls.Add('capacity-exit');@{released=$true}}
""")
            script=root/"test.ps1"
            script.write_text("""
param($Root)
$global:calls=[Collections.Generic.List[string]]::new()
function python {
 if($args-contains'--apply'){
  if($args-notcontains'--capacity-lease-id'-or$args-notcontains'fixture'-or$args-notcontains'MANIFEST'-or$args-notcontains'RETIREMENT'){throw 'identity or lease missing'}
  $global:calls.Add('repair');'{"status":"complete"}'
 }else{$global:calls.Add('plan');'{"committed_new_bytes":63}'}
 $global:LASTEXITCODE=0
}
$out=@(& "$Root/contracts/invoke_solver_review_retirement.ps1" -ArtifactRoot $Root -RepositoryRoot $Root -TargetRun "$Root/source" -Owner p -ConfirmWritingStopped -RepairPreservedFile simion/collision.pa -RepairEvidenceRun "$Root/audit" -ExpectedManifestSha256 MANIFEST -ExpectedRetirementSha256 RETIREMENT -Apply -Confirm:$false)
if($out.Count-ne1-or($out[0]|ConvertFrom-Json).status-ne'complete'){throw 'repair stdout was polluted'}
$global:calls|ConvertTo-Json -Compress
""")
            result=subprocess.run([pwsh,"-NoProfile","-File",str(script),str(root)],cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout),["host-enter","plan","capacity-enter","repair","capacity-exit","host-exit"])

    def test_apply_finalizes_opted_in_terminal_under_same_lease(self) -> None:
        self._check_wrapper("apply", enabled=True, expected=["enter", "retire", "finalize", "exit"])

    def test_nonapply_and_legacy_do_not_finalize(self) -> None:
        for mode, enabled, expected in (
            ("plan", True, ["retire"]), ("whatif", True, []),
            ("apply", False, ["enter", "retire", "exit"]),
            ("apply", None, ["enter", "retire", "exit"]),
            ("checkpoint", True, ["enter", "retire", "exit"]),
            ("subset", True, ["enter", "retire", "exit"]),
        ):
            with self.subTest(mode=mode, enabled=enabled):
                self._check_wrapper(mode, enabled=enabled, expected=expected)

    def test_failure_exits_without_retry_and_releases_lease(self) -> None:
        self._check_wrapper("retire_fail", enabled=True,
                            expected=["enter", "retire", "exit"], error="retirement failed with exit code 7")
        self._check_wrapper("finalize_fail", enabled=True,
                            expected=["enter", "retire", "finalize", "exit"], error="do not repeat deletion")

    def test_whatif_under_non_utf8_parent_console(self) -> None:
        self._check_wrapper("whatif", enabled=True, expected=[], legacy_console=True)

    def _check_wrapper(self, mode: str, *, enabled: bool | None, expected: list[str], error: str = "",
                       legacy_console: bool = False) -> None:
        """Execute the real wrapper, mocking only Python and host lease command boundaries."""
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is required for the wrapper behavior regression")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contracts = root / "contracts"
            contracts.mkdir()
            wrapper = contracts / "invoke_solver_review_retirement.ps1"
            wrapper.write_bytes(Path(__file__).with_name(wrapper.name).read_bytes())
            (root / "host_execution_lease.ps1").write_text("""
function Enter-HostExecutionLease { $global:calls.Add('enter'); return @{id='fixture'} }
function Exit-HostExecutionLease { param($Lease); $global:calls.Add('exit') }
""", encoding="utf-8")
            config = {} if enabled is None else {"capacity_ledger_lifecycle": {"enabled": enabled}}
            (root / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
            harness = root / "check.ps1"
            harness.write_text("""
param($Root, $Mode)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
Write-Host 'UTF8:编码边界'
$global:calls = [Collections.Generic.List[string]]::new()
function python {
  if ($args -contains 'common.contracts.run_capacity_lifecycle') {
    $global:calls.Add('finalize'); '{"status":"ready"}'
    $global:LASTEXITCODE = $(if ($Mode -eq 'finalize_fail') {9} else {0})
  } else {
    if($Mode -eq 'subset' -and ($args -notcontains '--selected-heavy-path' -or $args -notcontains 'simion/analyzer.pa0')) {throw 'subset selection was not forwarded'}
    $global:calls.Add('retire'); '{"lifecycle_status":"completed_experiment_payload_retired"}'
    $global:LASTEXITCODE = $(if ($Mode -eq 'retire_fail') {7} else {0})
  }
}
$params = @{ArtifactRoot=$Root; RepositoryRoot=$Root; TargetRun=$Root;
  Owner='p'; OwnerAbandonmentReason='isolated wrapper test'}
if ($Mode -ne 'plan') { $params.Apply = $true }
if ($Mode -eq 'whatif') { $params.WhatIf = $true }
if ($Mode -eq 'checkpoint') { $params.RuntimeCheckpoint='frozen.json'; $params.ConfirmWritingStopped=$true }
if ($Mode -eq 'subset') { $params.SelectedHeavyPaths=@('simion/analyzer.pa0') }
$failed = $false; $message = ''; $output = @()
try { $output = @(& (Join-Path $Root 'contracts/invoke_solver_review_retirement.ps1') @params) }
catch { $failed=$true; $message=$_.Exception.Message }
'RESULT:' + (@{calls=@($global:calls.ToArray()); output=@($output); error=$message} | ConvertTo-Json -Compress)
if ($failed) { exit 1 }
""", encoding="utf-8")
            command = [pwsh, "-NoLogo", "-NoProfile", "-File", str(harness), str(root), mode]
            if legacy_console:
                parent = root / "cp936_parent.ps1"
                parent.write_text("""
param($Pwsh, $Harness, $Root, $Mode)
[Console]::OutputEncoding = [Text.Encoding]::GetEncoding(936)
$OutputEncoding = [Console]::OutputEncoding
'PARENT_CODEPAGE:' + [Console]::OutputEncoding.CodePage
& $Pwsh -NoLogo -NoProfile -File $Harness $Root $Mode
exit $LASTEXITCODE
""", encoding="utf-8")
                command = [pwsh, "-NoLogo", "-NoProfile", "-File", str(parent), pwsh, str(harness), str(root), mode]
            result = subprocess.run(command,
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 1 if error else 0, result.stdout + result.stderr)
            self.assertIn("UTF8:编码边界", result.stdout)
            if legacy_console:
                self.assertIn("PARENT_CODEPAGE:936", result.stdout)
            report = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith("RESULT:")))
            self.assertEqual(report["calls"], expected)
            if error:
                self.assertIn(error, report["error"])
            elif mode != "whatif":
                self.assertEqual(len(report["output"]), 1)
                self.assertEqual(json.loads(report["output"][0])["lifecycle_status"],
                                 "completed_experiment_payload_retired")


class SolverReviewRetirementTest(unittest.TestCase):
    compatibility_roles = (
        "candidate_contract", "resolved_prototype_contract", "analyzer_pa0",
        "accelerator_pa0", "detector_pa", "three_instance_seed",
    )
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.artifacts = self.root / "artifacts"
        self.repo.mkdir()
        self.runs = self.artifacts / "projects" / "p" / "runs"
        self.target = self._run("20260101_000000__build__simion__old", "2026-01-01T00:00:00Z")
        self.replacement = self._run("20260102_000000__build__simion__new", "2026-01-02T00:00:00Z")
        initialize_capacity_ledger(self.artifacts, objects=[])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_wrapper_real_retirement_updates_opted_in_ledger(self) -> None:
        """Real Python deletion and finalization; only the lease boundary is isolated."""
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is required for the wrapper integration regression")
        config_path = self.target / "run_config.json"
        config = json.loads(config_path.read_text())
        config["capacity_ledger_lifecycle"] = {
            "schema_version": 1, "enabled": True, "artifact_root": str(self.artifacts),
            "light_evidence_budget_bytes": 26_214_400,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["run_config"].update(bytes=config_path.stat().st_size, sha256=_sha(config_path))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        register_writing(self.artifacts, config_path)
        seal_checkpoint(self.artifacts, config_path, owner="p", writing_stopped=True,
                        retain_payload=True, retention_reason="tiny completed experiment")
        contracts = self.root / "contracts"
        contracts.mkdir()
        wrapper = contracts / "invoke_solver_review_retirement.ps1"
        wrapper.write_bytes(Path(__file__).with_name(wrapper.name).read_bytes())
        (self.root / "host_execution_lease.ps1").write_text("""
function Enter-HostExecutionLease {
  $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID = [string]$PID
  return @{id='isolated fixture lease'}
}
function Exit-HostExecutionLease { param($Lease) }
""", encoding="utf-8")
        repository = Path(__file__).resolve().parents[2]
        result = subprocess.run([
            pwsh, "-NoLogo", "-NoProfile", "-File", str(wrapper),
            "-ArtifactRoot", str(self.artifacts), "-RepositoryRoot", str(repository),
            "-TargetRun", str(self.target), "-Owner", "p",
            "-OwnerAbandonmentReason", "completed tiny experiment without consumers", "-Apply",
        ], cwd=repository, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)  # Reject a second finalize-ready JSON document.
        self.assertEqual(receipt["lifecycle_status"], "completed_experiment_payload_retired")
        self.assertGreater(receipt["removed_bytes"], 0)
        self.assertFalse((self.target / "simion/analyzer.pa0").exists())
        ledger = load_capacity_ledger(self.artifacts)
        entry = next(item for item in ledger["objects"] if item["path"].endswith(self.target.name))
        self.assertEqual((entry["status"], entry["class"], entry["pin"]), ("ready", "light_evidence", False))
        self.assertEqual(entry["bytes"], sum(path.stat().st_size for path in self.target.rglob("*") if path.is_file()))

    def test_structured_references_resolves_target_once_for_nested_strings(self) -> None:
        resolved = self.target.resolve()
        value = {
            "paths": [str(self.target / "simion/analyzer.pa0")] * 100,
            "nested": ({"run": self.target.name}, ["unrelated prose", "", None]),
        }
        with mock.patch.object(Path, "resolve", autospec=True, return_value=resolved) as resolve:
            actual = structured_target_references(value, self.target, self.target.name)
        self.assertEqual(actual, {"", "simion/analyzer.pa0"})
        resolve.assert_called_once_with(self.target)

    def test_structured_references_preserves_path_matching_boundaries(self) -> None:
        cases = (
            (str(self.target / "simion/analyzer.pa0"), {"simion/analyzer.pa0"}),
            (str(self.target / "simion/analyzer.pa0").upper(), {"simion/analyzer.pa0"}),
            (f"../projects/p/runs/{self.target.name}/summary.json", {"summary.json"}),
            (self.target.name, {""}),
            (str(self.target) + "-other/simion/analyzer.pa0", set()),
            (f"../runs/{self.target.name}-other/summary.json", set()),
            (f"../runs/{self.target.name}/../../foreign.pa0", set()),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(structured_target_references(value, self.target, self.target.name), expected)

    def test_downstream_scan_resolves_target_once_and_rereads_documents(self) -> None:
        original_resolve = Path.resolve
        resolved_calls = []
        def track(path, *args, **kwargs):
            resolved_calls.append(path)
            return original_resolve(path, *args, **kwargs)
        with mock.patch.object(Path, "resolve", autospec=True, side_effect=track):
            first = _downstream_references(self.artifacts, self.target, self.target.name)
        self.assertEqual(resolved_calls.count(self.target), 2)  # target normalization and its directory entry
        self.assertEqual(first["active"], [])
        manifest_path = self.replacement / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["status"] = "running"
        manifest["inputs"]["late_dependency"] = {"path": str(self.target / "simion/analyzer.pa0")}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        second = _downstream_references(
            self.artifacts, self.target, self.target.name, removable_paths=["simion/analyzer.pa0"],
        )
        self.assertEqual([item["path"] for item in second["active"]], ["simion/analyzer.pa0"])

    def test_host_lease_wrapper_forwards_role_mappings(self) -> None:
        wrapper = Path(__file__).with_name("invoke_solver_review_retirement.ps1")
        source = wrapper.read_text(encoding="utf-8-sig")
        self.assertIn("[string[]]$CompatibilityInputRoleMaps=@()", source)
        self.assertIn("$CompatibilityInputRoles.Count -eq 0", source)
        self.assertIn("$CompatibilityInputRoleMaps.Count -eq 0", source)
        self.assertIn("'--compatibility-input-role-map',$mapping", source)
        self.assertIn("[string]$RuntimeCheckpoint=''", source)
        self.assertIn("[switch]$ConfirmWritingStopped", source)
        self.assertIn("'--runtime-checkpoint',$RuntimeCheckpoint,'--confirm-writing-stopped'", source)
        self.assertIn("-not $RuntimeCheckpoint -or -not $ConfirmWritingStopped", source)
        self.assertIn("[string[]]$ApprovedStoppedConsumers=@()", source)
        self.assertIn("'--approved-stopped-consumer',$consumer", source)

    def _run(self, run_id: str, recorded: str, *, status: str = "success") -> Path:
        run = self.runs / run_id
        simion = run / "simion"
        simion.mkdir(parents=True, exist_ok=True)
        roles = {
            "candidate_contract": run / "candidate.json",
            "resolved_prototype_contract": run / "resolved.json",
            "analyzer_pa0": simion / "analyzer.pa0",
            "accelerator_pa0": simion / "accelerator.pa0",
            "detector_pa": simion / "detector.pa#",
            "three_instance_seed": simion / "seed.iob",
        }
        for name, path in roles.items():
            path.write_bytes(b"native" if path.suffix.lower().startswith(".pa") else name.encode())
        config = {"schema_version": 2, "run_id": run_id, "project": "p", "mode": "three_component_candidate_iob_assembly",
                  "inputs": {name: str(path) for name, path in roles.items()}, "formal_gate_passed": False,
                  "artifact_retention": {"policy_version": 1, "class": "solver_review", "reason": "GUI review"}}
        summary = {"run_id": run_id, "status": status}
        for name, value in (("run_config.json", config), ("summary.json", summary)):
            (run / name).write_text(json.dumps(value), encoding="utf-8")
        inputs = {name: {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)} for name, path in roles.items()}
        manifest = {"schema_version": 2, "run_id": run_id, "project": "p", "mode": config["mode"], "status": status,
                    "recorded_at_utc": recorded, "run_config": {"path": str(run / 'run_config.json'), "exists": True,
                    "bytes": (run / 'run_config.json').stat().st_size, "sha256": _sha(run / 'run_config.json')},
                    "inputs": inputs, "outputs": [{"path": str(run / 'summary.json'), "exists": True,
                    "bytes": (run / 'summary.json').stat().st_size, "sha256": _sha(run / 'summary.json'), "retention_role": "required_evidence"}],
                    "formal_eligible": False, "artifact_retention": config["artifact_retention"]}
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    def _owner_plan(self, **kwargs: object) -> dict[str, object]:
        return plan_retirement(
            self.artifacts, self.repo, self.target, owner="p",
            owner_abandonment_reason="completed pilot comparison; no further payload consumer",
            **kwargs,
        )

    def _view_repair_fixture(self):
        """Retire one actual fixture member while preserving a second native PA."""
        source = self.target / "simion/collision.pa"
        source.write_bytes(b"original-native-bytes")
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["outputs"].append(dict(path=str(source), exists=True, bytes=source.stat().st_size,
                                        sha256=_sha(source), retention_role="solver_native_binary"))
        manifest_path.write_text(json.dumps(manifest))
        with mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[]), mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(self._owner_plan(selected_heavy_paths=["simion/analyzer.pa0"]))
        audit = self.runs / "20260103_000000__analysis__python__payload-view-repair"
        audit.mkdir()
        (audit / "run_config.json").write_text(json.dumps(dict(
            project="p", run_id=audit.name, mode="owned_payload_view_repair",
            artifact_retention=dict(policy_version=1, **{"class":"solver_review"}, reason="view repair audit"),
            capacity_ledger_lifecycle=dict(enabled=True, artifact_root=str(self.artifacts)))))
        create_capacity_protection_lease(self.artifacts, lease_id="repair", ttl_seconds=60,
            owner=f"owned-payload-view-repair:p:{audit.name}", protected_paths=[self.target, audit],
            committed_new_bytes=3 * source.stat().st_size)
        options = dict(owner="p", expected_manifest_sha256=_sha(manifest_path),
            expected_retirement_sha256=_sha(self.target / "solver_review_retirement_receipt.json"),
            writing_stopped=True, capacity_lease_id="repair", apply=True)
        return source, audit, options

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_keeps_large_io_outside_capacity_lock(self):
        from contextlib import contextmanager
        from common.contracts import solver_review_retirement as module
        from common.simion.cache_generation import snapshot_immutable_file
        source, audit, options = self._view_repair_fixture()
        original_lock = module.protection.capacity_decision_lock
        original_replace = os.replace
        original_atomic = module._atomic_json
        held = False
        calls = []

        @contextmanager
        def tracked_lock(root):
            nonlocal held
            with original_lock(root):
                self.assertFalse(held)
                held = True
                calls.append("lock")
                try:
                    yield
                finally:
                    held = False

        def checked_hash(path):
            if Path(path).suffix == ".pa":
                self.assertFalse(held, "PA hashing must not hold the capacity lock")
            return _sha(Path(path))

        def checked_copy(src, dst, record):
            self.assertFalse(held, "PA snapshots must not hold the capacity lock")
            return snapshot_immutable_file(src, dst, record)

        def checked_atomic(path, document):
            self.assertFalse(held, "journal publication must not hold the capacity lock")
            return original_atomic(path, document)

        def checked_replace(src, dst):
            if Path(src).suffix == ".pa":
                self.assertTrue(held, "payload renames require the short capacity CAS lock")
                calls.append("rename")
            return original_replace(src, dst)

        with mock.patch.object(module, "_VIEW_REPAIR_MIN_BYTES", 1), mock.patch.object(
            module.protection, "capacity_decision_lock", side_effect=tracked_lock), mock.patch.object(
            module, "file_sha256", side_effect=checked_hash), mock.patch.object(
            module, "file_sha256_unbuffered", side_effect=checked_hash), mock.patch.object(
            module, "_atomic_json", side_effect=checked_atomic), mock.patch.object(
            module.os, "replace", side_effect=checked_replace), mock.patch(
            "common.simion.cache_generation.snapshot_immutable_file", side_effect=checked_copy), mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            result = repair_preserved_native_file(self.artifacts, self.target, "simion/collision.pa", audit, **options)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls, ["lock", "lock", "rename", "lock", "rename"])

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_replaces_object_without_changing_records(self):
        source, audit, options = self._view_repair_fixture()
        before = source.stat().st_ino
        expected = source.read_bytes()
        def buffered(path):
            if Path(path) == source and source.stat().st_ino == before:
                return "A" * 64
            return _sha(Path(path))
        with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES", 1), mock.patch(
            "common.contracts.solver_review_retirement.file_sha256", side_effect=buffered), mock.patch(
            "common.contracts.solver_review_retirement.file_sha256_unbuffered", side_effect=_sha), mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            result = repair_preserved_native_file(self.artifacts, self.target, "simion/collision.pa", audit, **options)
            self.assertEqual(result,repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["observations"][0]["buffered_sha256"], "A" * 64)
        self.assertNotEqual(source.stat().st_ino, before)
        self.assertEqual(Path(result["quarantine_path"]).stat().st_ino, before)
        self.assertEqual(Path(result["retained_snapshot"]).read_bytes(), expected)
        self.assertEqual(source.read_bytes(), expected)
        self.assertEqual(_sha(self.target/"run_manifest.json"), options["expected_manifest_sha256"])
        self.assertEqual(_sha(self.target/"solver_review_retirement_receipt.json"), options["expected_retirement_sha256"])
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_rejects_bad_snapshot_and_protection(self):
        from common.simion.cache_generation import snapshot_immutable_file
        source,audit,options=self._view_repair_fixture()
        before=source.stat().st_ino
        count=0
        def bad_copy(src,dst,record):
            nonlocal count
            count+=1
            result=snapshot_immutable_file(src,dst,record)
            if count==2:dst.write_bytes(b"changed")
            return result
        with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES",1),mock.patch(
            "common.contracts.solver_review_retirement.file_sha256_unbuffered",side_effect=_sha),mock.patch.dict(
            os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
            with mock.patch("common.simion.cache_generation.snapshot_immutable_file",side_effect=bad_copy), self.assertRaisesRegex(RetirementError,"read views"):
                repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
            self.assertEqual(source.stat().st_ino,before)
            create_capacity_protection_lease(self.artifacts,lease_id="other",owner="consumer",ttl_seconds=60,protected_paths=[self.target])
            with self.assertRaisesRegex(RetirementError,"consumer lease"):
                repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
            with self.assertRaisesRegex(RetirementError,"CAS"):
                repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**{**options,"expected_manifest_sha256":"0"*64})

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_replays_both_rename_boundaries(self):
        source,audit,options=self._view_repair_fixture()
        real_replace=os.replace
        for phase in ("before_quarantine", "quarantine", "replace"):
            def interrupt(src,dst):
                if phase == "before_quarantine" and Path(src) == source:
                    raise OSError("fixture interrupted before rename")
                real_replace(src,dst)
                if (phase=="quarantine" and Path(src)==source) or (phase=="replace" and Path(dst)==source):
                    raise OSError("fixture interrupted after rename")
            with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES",1),mock.patch(
                "common.contracts.solver_review_retirement.file_sha256_unbuffered",side_effect=_sha),mock.patch.dict(
                os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
                with mock.patch("common.contracts.solver_review_retirement.os.replace",side_effect=interrupt),self.assertRaisesRegex(OSError,"interrupted"):
                    repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
        with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES",1),mock.patch(
            "common.contracts.solver_review_retirement.file_sha256_unbuffered",side_effect=_sha),mock.patch.dict(
            os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
            result=repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
        self.assertEqual(result["status"],"complete")
        self.assertEqual(source.read_bytes(),b"original-native-bytes")

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_preflight_is_read_only_and_rejects_scope_changes(self):
        source,audit,options=self._view_repair_fixture()
        with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES",1):
            plan=repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**{**options,"apply":False})
            self.assertEqual(plan["status"],"plan")
            self.assertFalse((audit/"results").exists())
            cases=({"writing_stopped":False},{"owner":"other"},{"capacity_lease_id":"missing"},
                   {"expected_retirement_sha256":"0"*64})
            with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
                for change in cases:
                    with self.subTest(change=change),self.assertRaises((RetirementError,ValueError)):
                        repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**{**options,**change})
                for path in ("simion/analyzer.pa0","simion/unknown.pa","../collision.pa","summary.json"):
                    with self.subTest(path=path),self.assertRaises(RetirementError):
                        repair_preserved_native_file(self.artifacts,self.target,path,audit,**options)
            self.assertFalse((audit/"results").exists())
            self.assertEqual(source.read_bytes(),b"original-native-bytes")

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_writer_and_final_divergence_fail_closed(self):
        source,audit,options=self._view_repair_fixture()
        original_id=source.stat().st_ino
        def divergent(path):
            return "F"*64 if Path(path)==source and source.stat().st_ino!=original_id else _sha(Path(path))
        with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES",1),mock.patch(
            "common.contracts.solver_review_retirement.file_sha256_unbuffered",side_effect=_sha),mock.patch.dict(
            os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
            with source.open("r+b"),self.assertRaises(OSError):
                repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
            with mock.patch("common.contracts.solver_review_retirement.file_sha256",side_effect=divergent),self.assertRaisesRegex(RetirementError,"read views"):
                repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
        journal=json.loads((audit/"results/payload_view_repair/repair_journal.json").read_text())
        self.assertEqual(journal["status"],"replaced")
        self.assertEqual((audit/"results/payload_view_repair/quarantine/collision.pa").stat().st_ino,original_id)

    @unittest.skipUnless(os.name == "nt", "Windows preserved PA read-view repair")
    def test_preserved_payload_view_repair_original_manifest_cas_after_snapshots(self):
        from common.simion.cache_generation import snapshot_immutable_file
        source,audit,options=self._view_repair_fixture()
        original_id=source.stat().st_ino
        def change_manifest(src,dst,record):
            result=snapshot_immutable_file(src,dst,record)
            if dst.parent.name=="snapshot_2":
                with (self.target/"run_manifest.json").open("a") as stream:stream.write(" ")
            return result
        with mock.patch("common.contracts.solver_review_retirement._VIEW_REPAIR_MIN_BYTES",1),mock.patch(
            "common.contracts.solver_review_retirement.file_sha256_unbuffered",side_effect=_sha),mock.patch.dict(
            os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}),mock.patch(
            "common.simion.cache_generation.snapshot_immutable_file",side_effect=change_manifest),self.assertRaisesRegex(RetirementError,"before quarantine"):
            repair_preserved_native_file(self.artifacts,self.target,"simion/collision.pa",audit,**options)
        self.assertEqual(source.stat().st_ino,original_id)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_selected_heavy_scope_preserves_other_native_assets_and_verifies(self, _scan):
        plan=self._owner_plan(selected_heavy_paths=["simion/analyzer.pa0"])
        self.assertEqual([r["path"] for r in plan["removed_files"]],["simion/analyzer.pa0"])
        self.assertIn("simion/detector.pa#",[r["path"] for r in plan["preserved_files"]])
        with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
            apply_retirement(plan)
        self.assertTrue((self.target/"simion/accelerator.pa0").is_file())
        self.assertTrue((self.target/"simion/detector.pa#").is_file())
        self.assertEqual(verify_retirement(self.target)["status"],"PASS")
        receipt=self.target/"solver_review_retirement_receipt.json"
        changed=json.loads(receipt.read_text())
        from common.contracts.run_capacity_lifecycle import _verify_retired_payload_remainder

        records = [{"path": p.relative_to(self.target).as_posix(), "bytes": p.stat().st_size}
                   for p in self.target.rglob("*") if p.is_file()]
        _verify_retired_payload_remainder(
            self.target, {"artifact_retention": {"class": "solver_review"}}, "p",
            {"pin": True, "bytes": sum(r["bytes"] for r in changed["original_file_inventory"])},
            records,
        )
        changed["selected_heavy_paths"]=["simion/detector.pa#"]
        receipt.write_text(json.dumps(changed))
        with self.assertRaises(RetirementError):
            verify_retirement(self.target)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_selected_heavy_scope_rejects_invalid_selection_and_manual_plan_changes(self, _scan):
        for selected in ([],["../outside.pa"],["simion/analyzer.pa0"]*2,["candidate.json"],["missing.pa"]):
            with self.subTest(selected=selected),self.assertRaises(RetirementError):
                self._owner_plan(selected_heavy_paths=selected)
        with self.assertRaisesRegex(RetirementError,"owner completion"):
            plan_retirement(self.artifacts,self.repo,self.target,self.replacement,"same",self.compatibility_roles,
                selected_heavy_paths=["simion/analyzer.pa0"])
        plan=self._owner_plan(selected_heavy_paths=["simion/analyzer.pa0"])
        plan["removed_files"].append(next(r for r in plan["preserved_files"] if r["path"]=="simion/accelerator.pa0"))
        with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
            with self.assertRaisesRegex(RetirementError,"scope differs"):
                apply_retirement(plan)
        self.assertTrue((self.target/"simion/analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_selected_heavy_pending_resume_keeps_exact_scope(self, _scan):
        selected=["simion/analyzer.pa0"]
        plan=self._owner_plan(selected_heavy_paths=selected)
        (self.target/selected[0]).unlink()
        (self.target/"solver_review_retirement_receipt.json").write_text(json.dumps({**plan,
            "role":"solver_review_retirement_receipt","lifecycle_status":"retirement_pending"}))
        with self.assertRaisesRegex(RetirementError,"scope changed"):
            self._owner_plan(selected_heavy_paths=["simion/accelerator.pa0"])
        resumed=self._owner_plan(selected_heavy_paths=selected)
        with mock.patch.dict(os.environ,{"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID":"123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"],"PASS")

    def _prepared_gui(self, run: Path, **summary_changes: object) -> None:
        config = json.loads((run / "run_config.json").read_text())
        config["inputs"] = {key: value for key, value in config["inputs"].items()
                            if not Path(value).suffix.startswith(".pa")}
        for path in (run / "simion").glob("*.pa*"):
            path.unlink()
        for suffix in (".gem", ".iob", ".pa#", ".pa0", ".pa1", ".pa2"):
            path = run / "simion" / ("processor" + suffix)
            path.write_bytes(("frozen " + suffix).encode())
            config["inputs"]["native" + suffix] = str(path)
        baseline = run / "baseline_manifest.json"
        baseline.write_text(json.dumps({"project": "p", "run_id": "scientific-source", "status": "failed"}))
        config["inputs"]["frozen_source"] = str(baseline)
        config["parameters"] = {"workflow": "native_gui_replay", "manual_gui_confirmed": False,
            "native_field_construction": "private_refine_and_native_IOB_prepared_not_flown",
            "baseline_run": str(self.runs / "scientific-source"), "baseline_manifest_sha256": _sha(baseline)}
        summary = {"status": "gui_replay_prepared", "gui_fly_completed": False,
            "trajectory_equivalence_verified": False, "field_construction": "new_private_refine_from_frozen_GEM",
            **summary_changes}
        (run / "run_config.json").write_text(json.dumps(config))
        (run / "summary.json").write_text(json.dumps(summary))
        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}
        manifest = json.loads((run / "run_manifest.json").read_text())
        manifest.update(status="checkpoint", run_config=record(run / "run_config.json"),
                        inputs={key: record(Path(value)) for key, value in config["inputs"].items()},
                        outputs=[record(run / "summary.json")])
        (run / "run_manifest.json").write_text(json.dumps(manifest))

    def _gui_plan(self, **kwargs: object) -> dict[str, object]:
        return plan_retirement(self.artifacts, self.repo, self.target, self.replacement,
            "newer prepared GUI replaces the obsolete source", ["candidate_contract"],
            prepared_gui_checkpoint=True, writing_stopped=True, **kwargs)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_supersession_preserves_light_and_replacement(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        self._prepared_gui(self.replacement)
        originals = {name: (self.target / name).read_bytes()
                     for name in ("summary.json", "run_manifest.json", "run_config.json")}
        plan = self._gui_plan()
        self.assertEqual(len(plan["removed_files"]), 4)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(plan)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertTrue((self.replacement / "simion/processor.pa0").exists())
        self.assertTrue((self.target / "simion/processor.iob").exists())
        self.assertEqual(originals, {name: (self.target / name).read_bytes() for name in originals})

    def test_prepared_gui_requires_stopped_confirmation_and_explicit_mode(self) -> None:
        self._prepared_gui(self.target)
        self._prepared_gui(self.replacement)
        for options in ({}, {"prepared_gui_checkpoint": True}, {"writing_stopped": True}):
            with self.subTest(options=options), self.assertRaises(RetirementError):
                plan_retirement(self.artifacts, self.repo, self.target, self.replacement,
                    "newer GUI", ["candidate_contract"], **options)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_rejects_flown_or_mismatched_summary(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.replacement)
        for changes in ({"gui_fly_completed": True}, {"status": "prepared"},
                        {"trajectory_equivalence_verified": True}):
            self._prepared_gui(self.target, **changes)
            with self.subTest(changes=changes), self.assertRaises(RetirementError):
                self._gui_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_rechecks_replacement_field_and_target_protection(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        self._prepared_gui(self.replacement)
        plan = self._gui_plan()
        create_capacity_protection_lease(self.artifacts, lease_id="old-gui-protected", owner="test",
                                        ttl_seconds=3600, protected_paths=[self.target])
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "protection lease"):
                apply_retirement(plan)
        (self.replacement / "simion/processor.pa0").write_bytes(b"changed")
        with self.assertRaises(RetirementError):
            self._gui_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_partial_retirement_replays_same_scope(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        self._prepared_gui(self.replacement)
        plan = self._gui_plan()
        (self.target / plan["removed_files"][0]["path"]).unlink()
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps({
            **plan, "role": "solver_review_retirement_receipt", "lifecycle_status": "retirement_pending"}))
        resumed = self._gui_plan()
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_owner_abandonment_without_replacement_preserves_evidence(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        originals = {path: path.read_bytes() for path in self.target.rglob("*")
                     if path.is_file() and not path.suffix.startswith(".pa")}
        plan = self._owner_plan(prepared_gui_checkpoint=True, writing_stopped=True)
        self.assertEqual(plan["retirement_mode"], "completed_experiment")
        self.assertIsNone(plan["replacement_run_path"])
        self.assertIsNone(plan["compatibility_checks"])
        self.assertEqual(len(plan["removed_files"]), 4)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["lifecycle_status"], "completed_experiment_payload_retired")
        self.assertEqual(verify_retirement(self.target)["target_terminal_status"], "checkpoint")
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_owner_exit_requires_reason_scope_stopped_and_exact_owner(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        for options in ({"prepared_gui_checkpoint": True}, {"writing_stopped": True}, {}):
            with self.subTest(options=options), self.assertRaises(RetirementError):
                self._owner_plan(**options)
        for owner, reason in (("other", "abandoned"), ("p", ""), ("", "abandoned")):
            with self.subTest(owner=owner, reason=reason), self.assertRaises(RetirementError):
                plan_retirement(self.artifacts, self.repo, self.target, owner=owner,
                    owner_abandonment_reason=reason, prepared_gui_checkpoint=True, writing_stopped=True)
        with self.assertRaisesRegex(RetirementError, "mutually exclusive"):
            plan_retirement(self.artifacts, self.repo, self.target, self.replacement,
                owner="p", owner_abandonment_reason="abandoned", prepared_gui_checkpoint=True, writing_stopped=True)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_owner_exit_rechecks_active_native_consumer_before_apply(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        plan = self._owner_plan(prepared_gui_checkpoint=True, writing_stopped=True)
        consumer = self.runs/"new_consumer"
        consumer.mkdir()
        (consumer/"run_config.json").write_text(json.dumps({"field": str(self.target/"simion/processor.pa0")}))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "active references"):
                apply_retirement(plan)
        self.assertTrue((self.target/"simion/processor.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_prepared_gui_active_native_consumer_blocks(self, _scan: mock.Mock) -> None:
        self._prepared_gui(self.target)
        self._prepared_gui(self.replacement)
        consumer = self.runs / "waiting_consumer"
        consumer.mkdir()
        (consumer / "run_config.json").write_text(json.dumps({"field": str(self.target / "simion/processor.pa0")}))
        with self.assertRaisesRegex(RetirementError, "active references"):
            self._gui_plan()

    def _checkpoint_runtime(self) -> Path:
        """Model sealed small inventory with unlisted private PA members."""
        for path in (self.target / "simion").glob("*.pa*"):
            path.unlink()
        config = json.loads((self.target / "run_config.json").read_text())
        config["inputs"] = {}
        config["artifact_retention"] = {"policy_version": 1, "class": "compact", "reason": None}
        (self.target / "run_config.json").write_text(json.dumps(config))
        (self.target / "summary.json").write_text(json.dumps({"status": "checkpoint", "run_id": self.target.name}))
        directory = self.target / "runtime" / "native_family"
        directory.mkdir(parents=True)
        members = []
        for index in range(3):
            path = directory / f"analyzer.pa{index}"
            path.write_bytes(b"native" + bytes([index]))
            members.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)})
        checkpoint = self.target / "results" / "runtime_checkpoint.json"
        checkpoint.parent.mkdir()
        checkpoint.write_text(json.dumps({
            "schema_version": 1, "role": "fixture_native_runtime_checkpoint", "status": "prepared",
            "directory": str(directory), "members": members,
            "runtime_receipt": {"status": "prepared", "run_id": self.target.name,
                                "controller_path": str(directory / "analyzer.pa0"),
                                "source_responses": [{"response_id": 1}, {"response_id": 2}]},
        }))
        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}
        manifest = json.loads((self.target / "run_manifest.json").read_text())
        manifest.update(status="checkpoint", inputs={}, artifact_retention=config["artifact_retention"],
                        run_config=record(self.target / "run_config.json"),
                        outputs=[record(self.target / "summary.json"), record(checkpoint)])
        (self.target / "run_manifest.json").write_text(json.dumps(manifest))
        return checkpoint

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_retirement_preserves_originals_without_pa_hash(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        originals = {name: (self.target / name).read_bytes() for name in (
            "run_config.json", "summary.json", "run_manifest.json", "results/runtime_checkpoint.json")}
        from common.contracts.solver_review_retirement import file_sha256
        def small_only(path: Path) -> str:
            self.assertFalse(path.suffix.lower().startswith(".pa"))
            return file_sha256(path)
        with mock.patch("common.contracts.solver_review_retirement.file_sha256", side_effect=small_only):
            plan = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
            self.assertEqual(plan["target_terminal_status"], "checkpoint")
            self.assertEqual(len(plan["removed_files"]), 3)
            self.assertTrue(all(item["manifest_role"] == "runtime_checkpoint_member" for item in plan["removed_files"]))
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                apply_retirement(plan)
            self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertEqual(originals, {name: (self.target / name).read_bytes() for name in originals})
        self.assertTrue((self.target / "simion/seed.iob").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_requires_explicit_scope_and_stopped_owner(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        for kwargs in ({}, {"runtime_checkpoint_path": checkpoint}, {"writing_stopped": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RetirementError):
                self._owner_plan(**kwargs)
        with self.assertRaises(RetirementError):
            plan_retirement(self.artifacts, self.repo, self.target, self.replacement,
                            "not an owner exit", self.compatibility_roles,
                            runtime_checkpoint_path=checkpoint, writing_stopped=True)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_rejects_unbound_inventory_and_payload_drift(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        copied = self.target / "results/unbound.json"
        copied.write_bytes(checkpoint.read_bytes())
        with self.assertRaisesRegex(RetirementError, "manifest-bound"):
            self._owner_plan(runtime_checkpoint_path=copied, writing_stopped=True)
        payload = self.target / "runtime/native_family/analyzer.pa2"
        payload.write_bytes(b"changed size")
        with self.assertRaisesRegex(RetirementError, "member differs"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_rechecks_gui_consumer_and_lease(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        plan = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        review = self.artifacts / "projects/p/reviews/current_view"
        review.mkdir(parents=True)
        receipt_path = review / "inspection_receipt.json"
        receipt_path.write_text(json.dumps({"status": "ready", "source_run": self.target.name}))
        with self.assertRaisesRegex(RetirementError, "current GUI"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "current GUI"):
                apply_retirement(plan)
        receipt_path.unlink()
        downstream = self.runs / "waiting_consumer"
        downstream.mkdir()
        config_path = downstream / "run_config.json"
        config_path.write_text(json.dumps({"runtime_checkpoint": str(checkpoint)}))
        with self.assertRaisesRegex(RetirementError, "active references"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        config_path.write_text("{}")
        create_capacity_protection_lease(self.artifacts, lease_id="runtime-owner-protected", owner="test",
                                         ttl_seconds=3600, protected_paths=[self.target])
        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        self.assertTrue((self.target / "runtime/native_family/analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_rejects_extra_unsealed_pa(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        (self.target / "runtime/native_family/unexpected.pa").write_bytes(b"unknown")
        with self.assertRaisesRegex(RetirementError, "lacks sealed identity"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_partial_retirement_replays(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        plan = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        first = self.target / plan["removed_files"][0]["path"]
        first.unlink()
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps({
            **plan, "role": "solver_review_retirement_receipt", "lifecycle_status": "retirement_pending",
        }))
        resumed = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        self.assertEqual(resumed["bytes_to_release"], plan["bytes_to_release"] - plan["removed_files"][0]["bytes"])
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_stopped_checkpoint_runtime_rejects_sealed_invalid_member_and_owner(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        original = json.loads(checkpoint.read_text())
        for case in ("owner", "path", "sha", "missing_member"):
            value = json.loads(json.dumps(original))
            if case == "owner":
                value["runtime_receipt"]["run_id"] = self.replacement.name
            elif case == "path":
                value["members"][1]["name"] = "../outside.pa1"
            elif case == "sha":
                value["members"][1]["sha256"] = "Z" * 64
            else:
                value["members"].pop()
            checkpoint.write_text(json.dumps(value))
            manifest_path = self.target / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["outputs"][1].update(bytes=checkpoint.stat().st_size, sha256=_sha(checkpoint))
            manifest_path.write_text(json.dumps(manifest))
            with self.subTest(case=case), self.assertRaises(RetirementError):
                self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)

    def _stopped_consumer(self, checkpoint: Path, name: str = "stopped-consumer") -> Path:
        """Match real historical owners: sealed checkpoint, summary has no run_id."""
        run = self.runs / name
        run.mkdir()
        config = run / "run_config.json"
        config.write_text(json.dumps({"run_id": run.name, "project": "p",
                                      "inputs": {"native_checkpoint": str(checkpoint)}}))
        summary = run / "summary.json"
        summary.write_text(json.dumps({"status": "checkpoint", "role": "iteration_summary"}))
        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}
        (run / "run_manifest.json").write_text(json.dumps({
            "run_id": run.name, "project": "p", "status": "checkpoint",
            "run_config": record(config), "outputs": [record(summary)],
        }))
        return run

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_approved_stopped_consumer_exit_is_scoped_and_preserves_scientific_checkpoint(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        consumer = self._stopped_consumer(checkpoint)
        before = {path.name: path.read_bytes() for path in consumer.iterdir()}
        with self.assertRaisesRegex(RetirementError, "active references"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        plan = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True,
                                approved_stopped_consumers=[consumer])
        self.assertEqual(plan["approved_stopped_consumers"][0]["run_path"], str(consumer))
        self.assertTrue(any(item.get("classification_basis") == "owner_explicit_consumer_abandonment_for_this_runtime"
                            for item in plan["historical_downstream_references"]))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(plan)
        self.assertEqual(verify_retirement(self.target)["target_terminal_status"], "checkpoint")
        self.assertEqual(before, {path.name: path.read_bytes() for path in consumer.iterdir()})
        with mock.patch("common.contracts.solver_review_retirement.plan_retirement", return_value={}) as planner:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--artifact-root", str(self.artifacts), "--repository-root", str(self.repo),
                                       "--target-run", str(self.target), "--owner", "p", "--owner-abandonment-reason", "old GUI reassembly",
                                       "--runtime-checkpoint", str(checkpoint), "--confirm-writing-stopped",
                                       "--approved-stopped-consumer", str(consumer)]), 0)
            self.assertEqual(planner.call_args.kwargs["approved_stopped_consumers"], [consumer])

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_approved_stopped_consumer_requires_owner_scope_and_new_consumers_still_block(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        consumer = self._stopped_consumer(checkpoint)
        for values in ({}, {"runtime_checkpoint_path": checkpoint}, {"writing_stopped": True}):
            with self.subTest(values=values), self.assertRaises(RetirementError):
                self._owner_plan(approved_stopped_consumers=[consumer], **values)
        plan = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True,
                                approved_stopped_consumers=[consumer])
        self._stopped_consumer(checkpoint, "new-unapproved-consumer")
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "active references"):
                apply_retirement(plan)
        self.assertFalse((self.target / "solver_review_retirement_receipt.json").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_approved_stopped_consumer_bad_evidence_and_owner_fail_closed(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        for case in ("missing_manifest", "config_drift", "summary_drift", "cross_owner", "duplicate"):
            consumer = self._stopped_consumer(checkpoint, case)
            if case == "missing_manifest":
                (consumer / "run_manifest.json").unlink()
            elif case == "config_drift":
                (consumer / "run_config.json").write_text("{}")
            elif case == "summary_drift":
                (consumer / "summary.json").write_text('{"status":"success"}')
            elif case == "cross_owner":
                manifest = consumer / "run_manifest.json"
                value = json.loads(manifest.read_text())
                value["project"] = "other"
                manifest.write_text(json.dumps(value))
            approved = [consumer, consumer] if case == "duplicate" else [consumer]
            with self.subTest(case=case), self.assertRaises(RetirementError):
                self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True,
                                 approved_stopped_consumers=approved)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_approved_stopped_consumer_rechecks_lease_gui_and_identity_before_apply(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        consumer = self._stopped_consumer(checkpoint)
        plan = self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True,
                                approved_stopped_consumers=[consumer])
        manifest_path = consumer / "run_manifest.json"
        original = manifest_path.read_bytes()
        manifest_path.write_bytes(original + b" ")
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "evidence changed"):
                apply_retirement(plan)
        manifest_path.write_bytes(original)
        review = self.artifacts / "projects/p/reviews/current_consumer"
        review.mkdir(parents=True)
        receipt = review / "inspection_receipt.json"
        receipt.write_text(json.dumps({"status": "ready", "source_run": consumer.name}))
        with self.assertRaisesRegex(RetirementError, "current GUI"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True,
                             approved_stopped_consumers=[consumer])
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "current GUI"):
                apply_retirement(plan)
        receipt.unlink()
        create_capacity_protection_lease(self.artifacts, lease_id="stopped-consumer-reader", owner="test",
                                         ttl_seconds=3600, protected_paths=[consumer])
        with self.assertRaisesRegex(RetirementError, "consumer has an active protection lease"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True,
                             approved_stopped_consumers=[consumer])

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_approved_stopped_consumer_pending_replay_requires_exact_list_and_identity(self, _scan: mock.Mock) -> None:
        checkpoint = self._checkpoint_runtime()
        consumer = self._stopped_consumer(checkpoint)
        kwargs = {"runtime_checkpoint_path": checkpoint, "writing_stopped": True,
                  "approved_stopped_consumers": [consumer]}
        plan = self._owner_plan(**kwargs)
        (self.target / plan["removed_files"][0]["path"]).unlink()
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps({
            **plan, "role": "solver_review_retirement_receipt", "lifecycle_status": "retirement_pending",
        }))
        with self.assertRaisesRegex(RetirementError, "consumer list or identity changed"):
            self._owner_plan(runtime_checkpoint_path=checkpoint, writing_stopped=True)
        consumer_manifest = consumer / "run_manifest.json"
        original = consumer_manifest.read_bytes()
        consumer_manifest.write_bytes(original + b" ")
        with self.assertRaisesRegex(RetirementError, "consumer list or identity changed"):
            self._owner_plan(**kwargs)
        consumer_manifest.write_bytes(original)
        resumed = self._owner_plan(**kwargs)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")

    def _nested_window(self, *, sealed: bool = True) -> Path:
        child = self.target / "windows/window-001"
        (child / "inputs").mkdir(parents=True)
        (child / "inputs/field_v.pa").write_bytes(b"window-native")
        config = json.loads((self.target / "run_config.json").read_text())
        config["inputs"] = {}
        (child / "run_config.json").write_text(json.dumps(config))
        (child / "summary.json").write_text(json.dumps({"run_id": self.target.name, "status": "success"}))
        def record(path: Path) -> dict[str, object]:
            return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)}
        manifest = json.loads((self.target / "run_manifest.json").read_text())
        manifest["run_config"] = record(child / "run_config.json")
        manifest["inputs"] = {}
        manifest["outputs"] = [record(child / "summary.json"), record(child / "inputs/field_v.pa")]
        (child / "run_manifest.json").write_text(json.dumps(manifest))
        if sealed:
            parent = json.loads((self.target / "run_manifest.json").read_text())
            parent["outputs"].append(record(child / "run_manifest.json"))
            (self.target / "run_manifest.json").write_text(json.dumps(parent))
        return child

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_nested_sealed_window_apply_and_verify(self, _scan: mock.Mock) -> None:
        child = self._nested_window()
        original = (child / "run_manifest.json").read_bytes()
        from common.contracts.solver_review_retirement import file_sha256
        def small_only(path: Path) -> str:
            self.assertFalse(path.suffix.lower().startswith(".pa"))
            return file_sha256(path)
        with mock.patch("common.contracts.solver_review_retirement.file_sha256", side_effect=small_only):
            plan = self._owner_plan()
            self.assertEqual(len(plan["removed_files"]), 4)
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                apply_retirement(plan)
            self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertFalse((child / "inputs/field_v.pa").exists())
        self.assertEqual((child / "run_manifest.json").read_bytes(), original)
        self.assertTrue((child / "run_config.json").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_nested_manifest_requires_parent_seal(self, _scan: mock.Mock) -> None:
        self._nested_window(sealed=False)
        with self.assertRaisesRegex(RetirementError, "lacks sealed identity"):
            self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_nested_manifest_damage_is_rejected(self, _scan: mock.Mock) -> None:
        child = self._nested_window()
        with (child / "run_manifest.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaises(RetirementError):
            self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_nested_partial_retirement_replays(self, _scan: mock.Mock) -> None:
        child = self._nested_window()
        plan = self._owner_plan()
        (child / "inputs/field_v.pa").unlink()
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps({
            **plan, "role": "solver_review_retirement_receipt", "lifecycle_status": "retirement_pending",
        }))
        resumed = self._owner_plan()
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")

    def _bind_external_input_manifest(self) -> Path:
        outside = self.replacement / "run_manifest.json"
        config_path = self.target / "run_config.json"
        config = json.loads(config_path.read_text())
        config["inputs"]["upstream_manifest"] = str(outside)
        config_path.write_text(json.dumps(config))
        parent_path = self.target / "run_manifest.json"
        parent = json.loads(parent_path.read_text())
        parent["run_config"].update(bytes=config_path.stat().st_size, sha256=_sha(config_path))
        parent["inputs"]["upstream_manifest"] = {
            "path": str(outside), "exists": True,
            "bytes": outside.stat().st_size, "sha256": _sha(outside),
        }
        parent_path.write_text(json.dumps(parent))
        return outside

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_external_input_manifest_preserved_without_payload_inheritance(self, _scan: mock.Mock) -> None:
        outside = self._bind_external_input_manifest()
        before = {str(p.relative_to(self.replacement)): p.read_bytes()
                  for p in self.replacement.rglob("*") if p.is_file()}
        plan = self._owner_plan()
        self.assertTrue(all((self.target / item["path"]).resolve().is_relative_to(self.target)
                            for item in plan["removed_files"]))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(plan)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertTrue(outside.is_file())
        self.assertEqual(before, {str(p.relative_to(self.replacement)): p.read_bytes()
                                  for p in self.replacement.rglob("*") if p.is_file()})
        retained = json.loads((self.target / "run_manifest.json").read_text())
        self.assertEqual(retained["inputs"]["upstream_manifest"]["sha256"], _sha(outside))

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_external_input_manifest_identity_drift_rejected(self, _scan: mock.Mock) -> None:
        outside = self._bind_external_input_manifest()
        outside.write_text(outside.read_text() + " ")
        with self.assertRaises(RetirementError):
            self._owner_plan()

    def _bind_frozen_input_manifest(self) -> Path:
        outside = self._bind_external_input_manifest()
        frozen = self.target / "inputs/reference_parent/run_manifest.json"
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(outside.read_bytes())
        config_path = self.target / "run_config.json"
        config = json.loads(config_path.read_text())
        config["inputs"]["upstream_manifest"] = str(frozen)
        config_path.write_text(json.dumps(config))
        parent_path = self.target / "run_manifest.json"
        parent = json.loads(parent_path.read_text())
        parent["run_config"].update(bytes=config_path.stat().st_size, sha256=_sha(config_path))
        parent["inputs"]["upstream_manifest"].update(path=str(frozen))
        parent_path.write_text(json.dumps(parent))
        return frozen

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_frozen_input_manifest_preserved_without_payload_inheritance(self, _scan: mock.Mock) -> None:
        frozen = self._bind_frozen_input_manifest()
        original = frozen.read_bytes()
        outside = {str(p.relative_to(self.replacement)): p.read_bytes()
                   for p in self.replacement.rglob("*") if p.is_file()}
        self.assertFalse((frozen.parent / "run_config.json").exists())
        plan = self._owner_plan()
        self.assertNotIn(frozen.relative_to(self.target).as_posix(),
                         [item["path"] for item in plan["removed_files"]])
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(plan)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertEqual(frozen.read_bytes(), original)
        self.assertEqual(outside, {str(p.relative_to(self.replacement)): p.read_bytes()
                                  for p in self.replacement.rglob("*") if p.is_file()})

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_frozen_input_manifest_identity_drift_rejected(self, _scan: mock.Mock) -> None:
        frozen = self._bind_frozen_input_manifest()
        frozen.write_text(frozen.read_text() + " ")
        with self.assertRaises(RetirementError):
            self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_frozen_manifest_input_cannot_bypass_child_output_contract(self, _scan: mock.Mock) -> None:
        frozen = self._bind_frozen_input_manifest()
        parent_path = self.target / "run_manifest.json"
        parent = json.loads(parent_path.read_text())
        parent["outputs"].append(dict(parent["inputs"]["upstream_manifest"]))
        parent_path.write_text(json.dumps(parent))
        with self.assertRaisesRegex(RetirementError, "unreadable JSON.*run_config"):
            self._owner_plan()
        self.assertTrue(frozen.is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_external_manifest_input_cannot_authorize_output(self, _scan: mock.Mock) -> None:
        outside = self._bind_external_input_manifest()
        parent_path = self.target / "run_manifest.json"
        parent = json.loads(parent_path.read_text())
        parent["outputs"].append(dict(parent["inputs"]["upstream_manifest"]))
        parent_path.write_text(json.dumps(parent))
        with self.assertRaisesRegex(RetirementError, "strict local descendant"):
            self._owner_plan()
        self.assertTrue(outside.is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_external_child_manifest_rejected(self, _scan: mock.Mock) -> None:
        parent_path = self.target / "run_manifest.json"
        parent = json.loads(parent_path.read_text())
        outside = self.replacement / "run_manifest.json"
        parent["outputs"].append({"path": str(outside), "exists": True,
                                  "bytes": outside.stat().st_size, "sha256": _sha(outside)})
        parent_path.write_text(json.dumps(parent))
        with self.assertRaisesRegex(RetirementError, "strict local descendant"):
            self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_completed_apply_preserves_evidence_without_heavy_hash(self, _scan: mock.Mock) -> None:
        from common.contracts.solver_review_retirement import file_sha256

        def small_only(path: Path) -> str:
            self.assertFalse(path.name.lower().startswith(("analyzer.pa", "accelerator.pa", "detector.pa")))
            return file_sha256(path)

        original_manifest = (self.target / "run_manifest.json").read_bytes()
        with mock.patch("common.contracts.solver_review_retirement.file_sha256", side_effect=small_only):
            plan = self._owner_plan()
            self.assertIsNone(plan["replacement_manifest"])
            self.assertTrue(all(item["identity_source"] == "sealed_manifest" for item in plan["removed_files"]))
            with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                receipt = apply_retirement(plan)
            self.assertEqual(receipt["lifecycle_status"], "completed_experiment_payload_retired")
            self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertEqual((self.target / "run_manifest.json").read_bytes(), original_manifest)
        self.assertTrue((self.target / "simion/seed.iob").is_file())
        self.assertTrue((self.target / "candidate.json").is_file())
        self.assertFalse((self.target / "simion/analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_completed_requires_reason_owner_and_exclusive_mode(self, _scan: mock.Mock) -> None:
        for values in (
            {"owner": "p"},
            {"owner_abandonment_reason": "finished"},
            {"owner": "other", "owner_abandonment_reason": "finished"},
            {"owner": "p", "owner_abandonment_reason": "finished", "replacement_run": self.replacement},
            {"owner": "p", "owner_abandonment_reason": "finished", "compatibility_assertion": "compatible"},
        ):
            with self.subTest(values=values), self.assertRaises(RetirementError):
                plan_retirement(self.artifacts, self.repo, self.target, **values)
        for status in ("checkpoint",):
            self._set_status(self.target, status)
            with self.subTest(status=status), self.assertRaisesRegex(RetirementError, "complete failed/interrupted/success"):
                self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_interrupted_preserves_terminal_and_small_evidence(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "interrupted")
        evidence = {name: (self.target / name).read_bytes() for name in (
            "run_manifest.json", "summary.json", "run_config.json", "candidate.json", "simion/seed.iob",
        )}
        with self.assertRaisesRegex(RetirementError, "complete failed/success"):
            plan_retirement(self.artifacts, self.repo, self.target, self.replacement,
                            "replacement does not authorize interrupted retirement", self.compatibility_roles)
        plan = self._owner_plan()
        self.assertEqual(plan["target_terminal_status"], "interrupted")
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(plan)
        self.assertEqual(verify_retirement(self.target)["target_terminal_status"], "interrupted")
        for name, original in evidence.items():
            self.assertEqual((self.target / name).read_bytes(), original)
        self.assertFalse((self.target / "simion/analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_interrupted_rechecks_consumer_and_lease(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "interrupted")
        plan = self._owner_plan()
        downstream = self.runs / "20260103_000000__analysis__python__consumer"
        downstream.mkdir()
        config = downstream / "run_config.json"
        config.write_text(json.dumps({"source": str(self.target / "simion/analyzer.pa0")}), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "active references"):
            self._owner_plan()
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "active references"):
                apply_retirement(plan)
        config.write_text("{}", encoding="utf-8")
        create_capacity_protection_lease(
            self.artifacts, lease_id="interrupted-owner-protected", owner="test",
            ttl_seconds=3600, protected_paths=[self.target],
        )
        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            self._owner_plan()
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "protection"):
                apply_retirement(plan)
        self.assertTrue((self.target / "simion/analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_failed_apply_and_verify_preserve_terminal_evidence(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        original_manifest = (self.target / "run_manifest.json").read_bytes()
        original_summary = (self.target / "summary.json").read_bytes()
        with self.assertRaisesRegex(RetirementError, "nonempty abandonment reason"):
            plan_retirement(self.artifacts, self.repo, self.target, owner="p")
        plan = self._owner_plan()
        self.assertEqual(plan["target_terminal_status"], "failed")
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["target_terminal_status"], "failed")
        self.assertEqual(receipt["lifecycle_status"], "completed_experiment_payload_retired")
        self.assertEqual(verify_retirement(self.target)["target_terminal_status"], "failed")
        self.assertEqual((self.target / "run_manifest.json").read_bytes(), original_manifest)
        self.assertEqual((self.target / "summary.json").read_bytes(), original_summary)
        self.assertTrue((self.target / "simion/seed.iob").is_file())
        self.assertFalse((self.target / "simion/analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_failed_rejects_active_consumer_at_plan_and_apply(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        plan = self._owner_plan()
        downstream = self.runs / "20260103_000000__analysis__python__consumer"
        downstream.mkdir()
        (downstream / "run_config.json").write_text(json.dumps({
            "source": str(self.target / "simion/analyzer.pa0"),
        }), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "active references"):
            self._owner_plan()
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            with self.assertRaisesRegex(RetirementError, "active references"):
                apply_retirement(plan)
        self.assertTrue((self.target / "simion/analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_completed_rejects_lease_and_active_consumer(self, _scan: mock.Mock) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__consumer"
        downstream.mkdir()
        config = downstream / "run_config.json"
        config.write_text(json.dumps({"source": str(self.target / "simion/analyzer.pa0")}), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "active references"):
            self._owner_plan()
        config.write_text("{}", encoding="utf-8")
        create_capacity_protection_lease(
            self.artifacts, lease_id="owner-completion-protected", owner="test",
            ttl_seconds=3600, protected_paths=[self.target],
        )
        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_completed_apply_rechecks_new_consumer_and_removal_scope(self, _scan: mock.Mock) -> None:
        plan = self._owner_plan()
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            altered = {**plan, "removed_files": plan["removed_files"] + [plan["preserved_files"][0]]}
            with self.assertRaisesRegex(RetirementError, "removal scope"):
                apply_retirement(altered)
            downstream = self.runs / "20260103_000000__analysis__python__consumer"
            downstream.mkdir()
            (downstream / "run_config.json").write_text(json.dumps({"source": str(self.target)}), encoding="utf-8")
            with self.assertRaisesRegex(RetirementError, "active references"):
                apply_retirement(plan)
        self.assertTrue((self.target / "simion/analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_completed_pending_receipt_replays_without_replacement(self, _scan: mock.Mock) -> None:
        plan = self._owner_plan()
        (self.target / plan["removed_files"][0]["path"]).unlink()
        (self.target / "solver_review_retirement_receipt.json").write_text(
            json.dumps({**plan, "role": "solver_review_retirement_receipt", "lifecycle_status": "retirement_pending"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RetirementError, "manifest identity changed"):
            plan_retirement(self.artifacts, self.repo, self.target, owner="p", owner_abandonment_reason="different")
        resumed = self._owner_plan()
        self.assertTrue(any(item.get("already_removed_before_resume") for item in resumed["removed_files"]))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_owner_completed_cli_plans_without_replacement(self, _scan: mock.Mock) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "--artifact-root", str(self.artifacts), "--repository-root", str(self.repo),
                "--target-run", str(self.target), "--owner", "p", "--owner-abandonment-reason", "completed pilot",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["retirement_mode"], "completed_experiment")

    def _set_status(self, run: Path, status: str) -> None:
        summary_path = run / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["status"] = status
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = status
        summary_record = next(
            item for item in manifest["outputs"]
            if Path(item["path"]).name == "summary.json"
        )
        summary_record["bytes"] = summary_path.stat().st_size
        summary_record["sha256"] = _sha(summary_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _make_real_legacy_initialization_fixture(self, run: Path) -> None:
        """Match the historical success-manifest/unbound-init-summary shape."""

        (run / "summary.json").write_text(
            json.dumps(LEGACY_INITIALIZATION_SUMMARY), encoding="utf-8"
        )
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["outputs"] = [
            record
            for record in manifest["outputs"]
            if Path(record["path"]).name != "summary.json"
        ]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _rename_input_role(self, run: Path, old: str, new: str) -> None:
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["inputs"][new] = config["inputs"].pop(old)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"][new] = manifest["inputs"].pop(old)
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _rewrite_input_identity(self, run: Path, role: str, payload: bytes) -> None:
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        input_path = Path(manifest["inputs"][role]["path"])
        input_path.write_bytes(payload)
        manifest["inputs"][role]["bytes"] = input_path.stat().st_size
        manifest["inputs"][role]["sha256"] = _sha(input_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _add_config_inputs(self, run: Path, values: dict[str, object]) -> None:
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["inputs"].update(values)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _replace_config_input(self, run: Path, role: str, value: object) -> None:
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["inputs"][role] = value
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_plan_apply_and_retired_verification(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "new successful GUI package supersedes old", self.compatibility_roles,
        )
        self.assertGreater(plan["bytes_to_release"], 0)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["lifecycle_status"], "superseded_payload_retired")
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertTrue((self.target / "run_manifest.json").is_file())
        self.assertTrue((self.target / "simion" / "seed.iob").is_file())
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

        receipt_path = self.target / "solver_review_retirement_receipt.json"
        legacy_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        legacy_receipt.pop("target_terminal_status")
        receipt_path.write_text(json.dumps(legacy_receipt), encoding="utf-8")
        self.assertEqual(
            verify_retirement(self.target)["target_terminal_status"], "success"
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_real_legacy_initialization_summary_can_use_superseded_entrypoint(
        self, _scan: mock.Mock,
    ) -> None:
        self._make_real_legacy_initialization_fixture(self.target)

        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "new verified package supersedes legacy initialized solver review",
            self.compatibility_roles,
        )

        self.assertTrue(plan["target_legacy_initialization_summary"])
        self.assertGreater(plan["bytes_to_release"], 0)
        self.assertIn(
            "summary.json", {item["path"] for item in plan["preserved_files"]}
        )
        with mock.patch.dict(
            os.environ,
            {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"},
        ):
            receipt = apply_retirement(plan)
        self.assertTrue(receipt["target_legacy_initialization_summary"])
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertEqual(
            json.loads((self.target / "summary.json").read_text(encoding="utf-8")),
            LEGACY_INITIALIZATION_SUMMARY,
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_legacy_initialization_summary_requires_exact_template(
        self, _scan: mock.Mock,
    ) -> None:
        mutations = {
            "extra_field": lambda value: value.update(unexpected=True),
            "reason_text": lambda value: value.update(
                reason=f"{value['reason']} "
            ),
            "role": lambda value: value.update(role="run_package_checkpoint_summary"),
            "schema": lambda value: value.update(schema_version=2),
            "running": lambda value: value.update(status="running"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self._run(
                    self.target.name, "2026-01-01T00:00:00Z"
                )
                self._make_real_legacy_initialization_fixture(self.target)
                summary = dict(LEGACY_INITIALIZATION_SUMMARY)
                mutate(summary)
                (self.target / "summary.json").write_text(
                    json.dumps(summary), encoding="utf-8"
                )

                with self.assertRaisesRegex(
                    RetirementError, "target is not a complete"
                ):
                    plan_retirement(
                        self.artifacts,
                        self.repo,
                        self.target,
                        self.replacement,
                        "near-match is not legacy authority",
                        self.compatibility_roles,
                    )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_legacy_exception_does_not_admit_replacement_or_non_solver_review(
        self, _scan: mock.Mock,
    ) -> None:
        self._make_real_legacy_initialization_fixture(self.replacement)
        with self.assertRaisesRegex(
            RetirementError, "replacement is not a complete success"
        ):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "replacement must remain complete",
                self.compatibility_roles,
            )

        self._run(
            self.replacement.name, "2026-01-02T00:00:00Z"
        )
        self._make_real_legacy_initialization_fixture(self.target)
        config_path = self.target / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["artifact_retention"] = {
            "policy_version": 1,
            "class": "compact",
            "reason": None,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "not solver_review"):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "compact target is not eligible",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_checkpoint_manifest_is_not_terminalized_from_success_summary(
        self, _scan: mock.Mock,
    ) -> None:
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "checkpoint"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(RetirementError, "target is not a complete"):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "summary cannot terminalize a checkpoint manifest",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_active_lease_blocks_legacy_initialization_target(
        self, _scan: mock.Mock,
    ) -> None:
        self._make_real_legacy_initialization_fixture(self.target)
        create_capacity_protection_lease(
            self.artifacts,
            lease_id="active-producer-consumer-chain",
            owner="test",
            ttl_seconds=3600,
            protected_paths=[self.target],
        )

        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "active chain must remain protected",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_failed_target_with_identity_equal_role_mapping_can_be_retired(
        self, _scan: mock.Mock,
    ) -> None:
        self._set_status(self.target, "failed")
        self._rename_input_role(
            self.target, "candidate_contract", "legacy_candidate_contract"
        )
        self._add_config_inputs(self.replacement, {
            "optional_input": None,
            "grouped_inputs": [
                str(self.replacement / "candidate.json"),
                str(self.replacement / "resolved.json"),
            ],
        })
        self._replace_config_input(
            self.replacement, "analyzer_pa0",
            str(self.root / "removed-short-alias" / "simion" / "analyzer.pa0"),
        )
        roles = tuple(
            role for role in self.compatibility_roles if role != "candidate_contract"
        )

        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "new successful GUI package supersedes failed legacy package", roles,
            (("legacy_candidate_contract", "candidate_contract"),),
        )

        self.assertEqual(plan["target_terminal_status"], "failed")
        self.assertEqual(
            plan["compatibility_checks"]["verified_input_role_mappings"][0][
                "target_role"
            ],
            "legacy_candidate_contract",
        )
        with mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
        ):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["target_terminal_status"], "failed")
        verification = verify_retirement(self.target)
        self.assertEqual(verification["target_terminal_status"], "failed")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_unbound_configured_input_collection_is_rejected(self, _scan: mock.Mock) -> None:
        self._add_config_inputs(
            self.replacement,
            {"grouped_inputs": [str(self.replacement / "unrecorded-input.json")]},
        )

        with self.assertRaisesRegex(RetirementError, "input collection"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "all configured input members remain bound", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_configured_file_record_binds_verified_input_identity(self, _scan: mock.Mock) -> None:
        configured = file_record(self.target / "candidate.json")
        configured["sha256"] = configured["sha256"].lower()
        self._add_config_inputs(self.target, {"frozen_record": configured})
        self.assertEqual(self._owner_plan()["status"], "eligible")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_configured_file_record_binds_generated_output_with_source_metadata(self, _scan: mock.Mock) -> None:
        frozen = self.target / "inputs/finalization.py"
        frozen.parent.mkdir(exist_ok=True)
        frozen.write_bytes(b"# frozen loader used at finalization\n")
        configured = file_record(frozen)
        configured["source_path"] = str(self.root / "changed-or-missing-live-source.py")
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["outputs"].append(file_record(frozen, "lightweight_optional"))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self._add_config_inputs(self.target, {"generated_records": {"group": [configured]}})
        plan = self._owner_plan()
        self.assertEqual(plan["status"], "eligible")
        self.assertTrue(any(item["path"] == "inputs/finalization.py" for item in plan["preserved_files"]))

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_configured_file_record_identity_must_match_verified_record(self, _scan: mock.Mock) -> None:
        configured = file_record(self.target / "candidate.json")
        for change in ({"sha256": "0" * 64}, {"bytes": configured["bytes"] + 1}):
            with self.subTest(change=change):
                self._add_config_inputs(self.target, {"frozen_record": {**configured, **change}})
                with self.assertRaisesRegex(RetirementError, "file record identity differs"):
                    self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_configured_file_record_requires_manifest_bound_file(self, _scan: mock.Mock) -> None:
        unbound = self.target / "unrecorded-input.json"
        unbound.write_bytes(b"valid file bytes are insufficient without a seal")
        self._add_config_inputs(self.target, {"frozen_record": file_record(unbound)})
        with self.assertRaisesRegex(RetirementError, "does not bind configured input file record"):
            self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_configured_file_record_rejects_incomplete_or_extra_metadata_shapes(self, _scan: mock.Mock) -> None:
        configured = file_record(self.target / "candidate.json")
        invalid = [
            {key: value for key, value in configured.items() if key != "bytes"},
            {**configured, "exists": False}, {**configured, "exists": 1},
            {**configured, "bytes": True}, {**configured, "bytes": -1},
            {**configured, "sha256": "x" * 64}, {**configured, "path": 1},
            {**configured, "source_path": {"unbound": "hidden.json"}},
            {**configured, "extra_dependency": "unbound.json"},
        ]
        for value in invalid:
            with self.subTest(value=value):
                self._add_config_inputs(self.target, {"frozen_record": value})
                with self.assertRaisesRegex(RetirementError, "file record has an invalid shape"):
                    self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_plain_configured_dictionary_retains_strict_collection_validation(self, _scan: mock.Mock) -> None:
        self._add_config_inputs(self.target, {"grouped_inputs": {"bound": str(self.target / "candidate.json")}})
        self.assertEqual(self._owner_plan()["status"], "eligible")
        for member, message in ((str(self.target / "unbound.json"), "input collection"), (False, "invalid shape")):
            with self.subTest(member=member):
                self._add_config_inputs(self.target, {"grouped_inputs": {"bound": member}})
                with self.assertRaisesRegex(RetirementError, message):
                    self._owner_plan()

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_short_alias_suffix_mismatch_is_rejected(self, _scan: mock.Mock) -> None:
        self._replace_config_input(
            self.replacement, "analyzer_pa0",
            str(self.root / "removed-short-alias" / "simion" / "other.pa0"),
        )

        with self.assertRaisesRegex(RetirementError, "configured input: analyzer_pa0"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "short alias must map exactly", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_failed_replacement_is_not_accepted(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        self._set_status(self.replacement, "failed")

        with self.assertRaisesRegex(RetirementError, "replacement is not a complete success"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "failed replacement is not authoritative", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_role_mapping_requires_roles_at_both_ends(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")

        with self.assertRaisesRegex(RetirementError, "mapping roles missing"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "legacy roles must be explicit", (),
                (("missing_legacy_role", "candidate_contract"),),
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_role_mapping_requires_equal_manifest_identity(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        self._rename_input_role(
            self.target, "candidate_contract", "legacy_candidate_contract"
        )
        replacement_input = self.replacement / "candidate.json"
        original = replacement_input.read_bytes()
        for payload in (b"x" * len(original), original + b"-different-size"):
            with self.subTest(payload_size=len(payload)):
                self._rewrite_input_identity(
                    self.replacement, "candidate_contract", payload
                )
                with self.assertRaisesRegex(RetirementError, "mapping identity differs"):
                    plan_retirement(
                        self.artifacts, self.repo, self.target, self.replacement,
                        "identity drift must fail closed", (),
                        (("legacy_candidate_contract", "candidate_contract"),),
                    )
                self._rewrite_input_identity(
                    self.replacement, "candidate_contract", original
                )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_role_mappings_must_be_one_to_one(self, _scan: mock.Mock) -> None:
        for mappings in (
            (
                ("candidate_contract", "candidate_contract"),
                ("candidate_contract", "resolved_prototype_contract"),
            ),
            (
                ("candidate_contract", "candidate_contract"),
                ("resolved_prototype_contract", "candidate_contract"),
            ),
        ):
            with self.subTest(mappings=mappings), self.assertRaisesRegex(
                RetirementError, "one-to-one"
            ):
                plan_retirement(
                    self.artifacts, self.repo, self.target, self.replacement,
                    "ambiguous mappings must fail closed", (), mappings,
                )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_cli_accepts_repeated_input_role_mappings(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        self._rename_input_role(
            self.target, "candidate_contract", "legacy_candidate_contract"
        )
        output = io.StringIO()

        with redirect_stdout(output):
            status = main([
                "--artifact-root", str(self.artifacts),
                "--repository-root", str(self.repo),
                "--target-run", str(self.target),
                "--replacement-run", str(self.replacement),
                "--compatibility-assertion", "explicit legacy role migration",
                # Existing lease-owning PowerShell wrapper forwards mappings
                # through this older repeatable switch.
                "--compatibility-input-role",
                "legacy_candidate_contract=candidate_contract",
                "--compatibility-input-role-map",
                "analyzer_pa0=analyzer_pa0",
            ])

        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["target_terminal_status"], "failed")
        self.assertEqual(
            len(result["compatibility_checks"]["verified_input_role_mappings"]), 2
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=["docs/x.md"])
    def test_historical_document_reference_is_audited_not_a_heavy_dependency(
        self, _scan: mock.Mock,
    ) -> None:
        self._set_status(self.target, "failed")
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        self.assertEqual(plan["historical_document_references"], ["docs/x.md"])

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_capacity_protection_lease_blocks_failed_target(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        create_capacity_protection_lease(
            self.artifacts, lease_id="protected-failed-target", owner="test",
            ttl_seconds=3600, protected_paths=[self.target],
        )

        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "protected targets remain immutable", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_rechecks_new_capacity_protection_lease(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "lease changes must be rechecked", self.compatibility_roles,
        )
        create_capacity_protection_lease(
            self.artifacts, lease_id="late-protection", owner="test",
            ttl_seconds=3600, protected_paths=[self.target],
        )

        with mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
        ), self.assertRaisesRegex(RetirementError, "gained an active capacity"):
            apply_retirement(plan)
        self.assertFalse((self.target / "solver_review_retirement_receipt.json").exists())
        self.assertTrue((self.target / "simion" / "analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_rechecks_new_downstream_reference(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "references must be rechecked", self.compatibility_roles,
        )
        downstream = self.runs / "20260103_000000__analysis__python__late-consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps({"source_run": self.target.name}), encoding="utf-8"
        )

        with mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
        ), self.assertRaisesRegex(RetirementError, "gained active references"):
            apply_retirement(plan)
        self.assertFalse((self.target / "solver_review_retirement_receipt.json").exists())
        self.assertTrue((self.target / "simion" / "analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_audits_late_terminal_downstream_reference_without_blocking(
        self, _scan: mock.Mock,
    ) -> None:
        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "terminal references remain historical",
            self.compatibility_roles,
        )
        downstream = self.runs / "20260103_000000__analysis__python__late-history"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        config_path.write_text(
            json.dumps({"source_run": str(self.target)}), encoding="utf-8"
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "failed"}),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ,
            {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"},
        ):
            receipt = apply_retirement(plan)

        self.assertEqual(
            receipt["apply_historical_downstream_references"][0][
                "run_config_path"
            ],
            str(config_path),
        )
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

    def test_apply_records_new_historical_document_reference_without_blocking(self) -> None:
        with mock.patch(
            "common.contracts.solver_review_retirement._git_document_references",
            return_value=[],
        ) as scan:
            plan = plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "document references must be rechecked", self.compatibility_roles,
            )
            scan.return_value = ["docs/new-reference.md"]
            with mock.patch.dict(
                os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
            ):
                receipt = apply_retirement(plan)
        self.assertEqual(
            receipt["apply_historical_document_references"],
            ["docs/new-reference.md"],
        )
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_downstream_manifest_reference_preserves_light_evidence_only(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        downstream = self.runs / "20260103_000000__analysis__python__consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps(
                {
                    "inputs": {
                        "source_manifest": str(self.target / "run_manifest.json")
                    }
                }
            ),
            encoding="utf-8",
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "referenced manifest remains immutable", self.compatibility_roles,
        )
        self.assertEqual(
            plan["active_preserved_file_references"][0]["path"],
            "run_manifest.json",
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_active_reference_to_preserved_light_file_does_not_pin_heavy_payload(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__light-consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps({"source_summary": str(self.target / "summary.json")}),
            encoding="utf-8",
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "preserved evidence remains available", self.compatibility_roles,
        )

        self.assertEqual(plan["active_preserved_file_references"][0]["path"], "summary.json")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_active_reference_to_nested_heavy_file_blocks_retirement(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__payload-consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps({"source_pa": str(self.target / "simion" / "analyzer.pa0")}),
            encoding="utf-8",
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RetirementError, "active references"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "active payload cannot retire", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_terminal_downstream_reference_is_historical_audit_not_blocker(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__historical"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        config_path.write_text(
            json.dumps({"source_run": self.target.name}), encoding="utf-8"
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "success"}),
            encoding="utf-8",
        )

        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "terminal consumers are historical evidence",
            self.compatibility_roles,
        )

        self.assertEqual(
            plan["historical_downstream_references"],
            [
                {
                    "run_config_path": str(config_path),
                    "manifest_status": "success",
                    "reason": "configured_target_run_dependency",
                }
            ],
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_unreadable_active_run_config_blocks_conservatively(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__uncertain"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text("{", encoding="utf-8")
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            RetirementError, "run_config_unreadable_reference_uncertain"
        ):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "uncertain active consumers block",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_corrupt_active_run_config_is_audit_only_when_manifest_identity_differs(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__corrupt-config"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        original = json.dumps(
            {"source_pa": str(self.target / "simion" / "analyzer.pa0")},
            separators=(",", ":"),
        ).encode()
        config_path.write_bytes(original)
        manifest = {
            "run_id": downstream.name,
            "status": "checkpoint",
            "run_config": {
                "path": str(config_path),
                "exists": True,
                "bytes": len(original),
                "sha256": hashlib.sha256(original).hexdigest().upper(),
            },
        }
        (downstream / "run_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        # Simulate the observed all-zero/corrupt file while retaining the
        # manifest's last-known identity.
        config_path.write_bytes(b"\x00" * len(original))

        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "corrupt downstream config is not usable evidence of a consumer",
            self.compatibility_roles,
        )

        self.assertEqual(plan["active_preserved_file_references"], [])
        self.assertEqual(
            plan["corrupt_run_config_reference_unavailable"][0]["reason"],
            "corrupt_run_config_reference_unavailable",
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_unreadable_active_run_config_with_matching_manifest_identity_still_blocks(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__matching-invalid-config"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        invalid = b"{"
        config_path.write_bytes(invalid)
        manifest = {
            "run_id": downstream.name,
            "status": "checkpoint",
            "run_config": {
                "path": str(config_path),
                "exists": True,
                "bytes": len(invalid),
                "sha256": hashlib.sha256(invalid).hexdigest().upper(),
            },
        }
        (downstream / "run_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        with self.assertRaisesRegex(
            RetirementError, "run_config_unreadable_reference_uncertain"
        ):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "matching but unparsable config remains uncertain",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_declared_compatibility_role_must_exist_at_both_ends(self, _scan: mock.Mock) -> None:
        with self.assertRaisesRegex(RetirementError, "identity roles missing"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "compatible", (*self.compatibility_roles, "project_specific_missing_role"),
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_requires_host_lease(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RetirementError):
            apply_retirement(plan)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_plan_rejects_missing_or_changed_recorded_evidence(self, _scan: mock.Mock) -> None:
        for run in (self.target, self.replacement):
            payload = run / "simion" / "analyzer.pa0"
            original = payload.read_bytes()
            for mutation in (None, b"drift!"):
                with self.subTest(run=run.name, mutation=mutation):
                    if mutation is None:
                        payload.unlink()
                    else:
                        payload.write_bytes(mutation)
                    with self.assertRaisesRegex(RetirementError, "identity differs"):
                        plan_retirement(
                            self.artifacts, self.repo, self.target, self.replacement,
                            "compatible", self.compatibility_roles,
                        )
                    payload.write_bytes(original)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_replacement_cannot_omit_compatibility_input_record(self, _scan: mock.Mock) -> None:
        path = self.replacement / "run_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["inputs"]["analyzer_pa0"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "does not bind configured input"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "compatible", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_rechecks_evidence_before_any_removal(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        for run, relative in (
            (self.replacement, "simion/analyzer.pa0"),
            (self.target, "summary.json"),
            (self.replacement, "run_manifest.json"),
        ):
            path = run / relative
            original = path.read_bytes()
            with self.subTest(run=run.name, relative=relative):
                path.write_bytes(original + b" ")
                with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                    with self.assertRaises(RetirementError):
                        apply_retirement(plan)
                marker = json.loads(
                    (self.target / "solver_review_retirement_receipt.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(marker["status"], "preflight_pending")
                self.assertEqual(marker["lifecycle_status"], "retirement_pending")
                for item in plan["removed_files"]:
                    self.assertTrue((self.target / item["path"]).is_file())
                path.write_bytes(original)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_pending_receipt_resumes_only_recorded_partial_removal(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        first = plan["removed_files"][0]
        (self.target / first["path"]).unlink()
        pending = {
            **plan,
            "role": "solver_review_retirement_receipt",
            "lifecycle_status": "retirement_pending",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps(pending), encoding="utf-8")
        resumed = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        self.assertTrue(any(item.get("already_removed_before_resume") for item in resumed["removed_files"]))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
