"""Exercise the production native-operation adapter with Python-only writers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.file_identity import file_sha256


REPO = Path(__file__).resolve().parents[4]
BUILDER = REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1"


class ManagedCandidatePaTests(unittest.TestCase):
    def test_detached_handoff_reuses_completed_responses_and_rebuilds_only_incomplete_component(self):
        self._exercise_detached_handoff(("complete_and_partial", "verification_fails", "prepared_and_unproven"))

    def test_repeated_handoff_keeps_original_build_proof_through_publication_failures(self):
        self._exercise_detached_handoff(("repeated_publication_failure",))

    def _exercise_detached_handoff(self, cases):
        """Real PS/cache/lease; inert native bytes never claim a solved field."""
        from unittest.mock import patch
        from common.contracts.capacity_ledger import record_capacity_object
        from common.contracts.run_capacity_lifecycle import seal_checkpoint
        from common.contracts.write_run_manifest import build_run_manifest
        from common.simion import pa_family_cache
        from common.simion.test_pa_family_cache import PAFamilyCacheTest
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
            freeze_candidate_source_closure, frozen_source_path, verify_candidate_source_closure,
        )
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import compile_component_pa_plan
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
            render_fly2, render_program, render_resolved_lua,
        )

        for case in cases:
            with self.subTest(case=case):
                fixture = PAFamilyCacheTest()
                fixture.setUp()
                try:
                    root = fixture.root
                    artifacts, cache = fixture._artifact_cache()
                    predecessor = fixture.producer_run_config.parent
                    artifact_project = predecessor.parent.parent
                    project = REPO / "projects/single_reflection_oa_tof_mass_analyzer"
                    closure = freeze_candidate_source_closure(root / "code", artifact_project)
                    frozen_builder = frozen_source_path(closure, BUILDER.relative_to(REPO).as_posix())
                    inputs = root / "science"
                    inputs.mkdir()
                    contract = json.loads((project / "config/resolved_geometry.json").read_text(encoding="utf-8"))
                    (inputs / "resolved.json").write_text(json.dumps(contract), encoding="utf-8")
                    shutil.copyfile(project / "config/baseline.json", inputs / "baseline.json")
                    for name, payload in {
                        "oatof_resolved.lua": render_resolved_lua(contract),
                        "oatof_ideal_grounded.lua": render_program(contract),
                        "oatof_ideal_grounded.fly2": render_fly2(contract, particle_source_seed=7),
                    }.items():
                        (inputs / name).write_text(payload, encoding="utf-8")
                    for name in ("template.iob", "template.con"):
                        (inputs / name).write_text("inert fixture, never vendor-opened", encoding="utf-8")
                    plan = compile_component_pa_plan(contract, repository_root=REPO, simion_exe=Path(sys.executable))
                    (inputs / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
                    config = json.loads(fixture.producer_run_config.read_text(encoding="utf-8"))
                    config["artifact_retention"] = {"policy_version": 1, "class": "solver_review", "reason": "software handoff fixture"}
                    config["inputs"] = {"plan": str(inputs / "plan.json")}
                    fixture.producer_run_config.write_text(json.dumps(config), encoding="utf-8")
                    record_capacity_object(artifacts, path=predecessor, object_class="rebuildable_payload",
                        bytes_count=fixture.producer_run_config.stat().st_size, status="writing", owner="fixture",
                        recovery_reason="inert fixture is active", review_deadline="2026-10-01")
                    manifest_path = predecessor / "run_manifest.json"
                    manifest_path.write_text(json.dumps(build_run_manifest(fixture.producer_run_config, "checkpoint")), encoding="utf-8")
                    sources, components, operations, retained = [], [], [], []
                    transactions = {}
                    worker = dict(schema_version=1, role="repository_managed_python_completion", worker_process_id=10,
                        worker_started_at_utc_ticks=638000000000000000, launcher_process_id=11, exit_code=0,
                        ownership_confirmed=True, worker_exit_confirmed=True, launcher_exit_confirmed=True,
                        stdout_drained=True, stderr_drained=True)
                    for component in plan["components"][:2]:
                        stem, key = component["stem"], component["cache_key"]
                        recipe = dict(schema_version=2, receipt_name=stem + ".standalone_responses.json",
                            exporter_path=str(REPO / "common/simion/export_standalone_pa.lua"), source_location="build_scratch",
                            exports=[dict(response_id=i, source_name=f"{stem}.pa{i}", standalone_name=f"{stem}.response{i}.pa")
                                     for i in component["response_ids"]])
                        first = pa_family_cache.advance_pa_family_cache_transaction(cache, component["identity"], component["expected_files"],
                            owner=fixture.artifact_owner, producer_run_config=fixture.producer_run_config, response_receipt=recipe)
                        transactions[stem] = first
                        # The second arm deliberately lacks any completed-build
                        # attestation for its sealed reflectron. It must not be
                        # inferred from equal bytes or a roundtrip reconstruction.
                        complete = stem == "accelerator" or case in {"prepared_and_unproven", "repeated_publication_failure"}
                        seal_members = case == "prepared_and_unproven" or (case == "repeated_publication_failure" and stem == "reflectron")
                        if complete:
                            for i in ["#", *range(len(component["response_ids"]) + 1)]:
                                (first.scratch_directory / f"{stem}.pa{i}").write_bytes(b"inert field fixture" * 8)
                            (first.build_directory / f"{stem}.pa#").write_bytes(b"inert field fixture" * 8)
                            for i in component["response_ids"]:
                                target = first.build_directory if seal_members else first.scratch_directory
                                (target / f"{stem}.response{i}.pa").write_bytes(b"inert field fixture" * 8)
                            if seal_members:
                                sealed = pa_family_cache.advance_pa_family_cache_transaction(cache, component["identity"], component["expected_files"],
                                    owner=fixture.artifact_owner, producer_run_config=fixture.producer_run_config)
                            if stem == "accelerator":
                                opid = "fixture_complete_accelerator_build_and_exports"
                                components.append(dict(role=stem, cache_key=key, response_ids=component["response_ids"],
                                    response_build_operation_ids=[opid]))
                                operations.append(dict(operation_id=opid, observation=dict(exit_confirmed=True, returncode=0),
                                    managed_process_completion=worker))
                                if case == "prepared_and_unproven":
                                    evidence = fixture._verification_evidence(sealed)
                                    retained += [Path(evidence["verifier_path"]), Path(evidence["verification_output_path"])]
                                    with patch.object(pa_family_cache, "_publish_transaction_payload", side_effect=OSError("fixture publication interruption")):
                                        with self.assertRaisesRegex(OSError, "fixture publication interruption"):
                                            pa_family_cache.advance_pa_family_cache_transaction(cache, component["identity"], component["expected_files"],
                                                owner=fixture.artifact_owner, verification_evidence=evidence)
                        else:
                            (first.scratch_directory / f"{stem}.pa1").write_bytes(b"incomplete old unit")
                        sources.append(dict(transaction_path=str(first.transaction_directory / "transaction.json"),
                            owner_result_path=str(root / "owner_result.json")))
                    completion_path = predecessor / "build_completion.json"
                    completion_path.write_text(json.dumps(dict(schema_version=1, role="oatof_component_build_completion",
                        run_id=predecessor.name, components=components, operations=operations)), encoding="utf-8")
                    manifest_path.write_text(json.dumps(build_run_manifest(fixture.producer_run_config, "checkpoint",
                        output_paths=[completion_path, *retained])), encoding="utf-8")
                    stopped = seal_checkpoint(artifacts, fixture.producer_run_config, owner="fixture", writing_stopped=True,
                        retain_payload=True, retention_reason="inert fixture producer is stopped")
                    (root / "owner_result.json").write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_result",
                        stage="complete", run_directory=str(predecessor), terminal_published=True, capacity_finalized=True,
                        lease_released=True, stopped_payload_receipt=stopped)), encoding="utf-8")
                    if case == "repeated_publication_failure":
                        sources = sources[:1]
                    (inputs / "handoff_sources.json").write_text(json.dumps(sources), encoding="utf-8")
                    old_reflectron = (transactions["reflectron"].transaction_directory / "transaction.json").read_bytes()
                    # This is only a native argument boundary adapter. The real
                    # producer, selected-worker handshake and observer stay in use.
                    native = root / "inert_native.py"
                    native.write_text(r'''
import json,os,shutil,sys
from pathlib import Path
a=json.loads(sys.argv[1]);name=Path(a[3]).name;p=a[4:]
with open(os.environ['FIXTURE_CALLS'],'a',encoding='utf-8') as out: out.write(json.dumps(a)+'\n')
counts=json.loads(os.environ['FIXTURE_COUNTS'])
if name in {'build_two_zone_pa.lua','build_reflectron_variant.lua'}:
    raw=Path(p[1]);stem=raw.name[:-4];count=counts[stem]
    for suffix in ['#',*range(count+1)]: raw.with_name(stem+'.pa'+str(suffix)).write_bytes(b'inert field fixture'*8)
elif name=='refine_single_pa.lua': assert Path(p[0]).is_file()
elif name in {'export_standalone_pa.lua','voltageize_pa0.lua'}: shutil.copyfile(p[0],p[1])
elif name=='assemble_native_fast_adjust_family.lua':
    if p[0]=='--controller':
        controller=Path(p[2]);stem=controller.name[:-4]
        for i in range(int(p[3])+1): controller.with_name(stem+'.pa'+str(i)).write_bytes(Path(p[1]).read_bytes())
    else: shutil.copyfile(p[1],p[2])
elif name=='verify_component_pa.lua':
    if os.environ['FIXTURE_VERIFY_FAIL']=='1': raise SystemExit(23)
    stem=Path(p[0]); ids=[int(p[10])] if len(p)==12 else range(1,int(p[2])+1)
    for i in ids:
        source=Path(p[11]) if len(p)==12 else Path(p[1])/(stem.name+'.response'+str(i)+'.pa')
        assert stem.with_name(stem.name+'.pa'+str(i)).read_bytes()==source.read_bytes()
    print('INERT_BYTE_COMPARISON_ONLY')
elif name=='build_flight_tube_variant.lua': raise SystemExit(17)
else: raise AssertionError(name)
''', encoding="utf-8")
                    driver = root / "driver.ps1"
                    driver.write_text(r'''
param($LiveRepo,$FrozenRepo,$Python,$ArtifactProject,$Inputs,$Builder,$Native,$Predecessor,$Report,$Attempt)
$ErrorActionPreference='Stop';$PSNativeCommandUseErrorActionPreference=$false
. (Join-Path $LiveRepo 'common/contracts/run_artifact_support.ps1')
function Invoke-ArtifactCapacityGate { return @{satisfied=$true;fixture_admission=$true} }
$runId='20261029_01000'+$Attempt+'__test__simion__handoff-builder'
$run=Join-Path $ArtifactProject ('runs/'+$runId)
$artifactRoot=Split-Path (Split-Path $ArtifactProject -Parent) -Parent
$plan=Get-Content (Join-Path $Inputs 'plan.json') -Raw|ConvertFrom-Json -Depth 80
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $LiveRepo -ArtifactRoot $artifactRoot `
 -RunDirectory $run -CommittedNewBytes 0 -Owner 'handoff-fixture' -ProtectedPaths @($Predecessor) `
 -ProtectedCacheKeys @($plan.components|Where-Object cacheable|ForEach-Object{$_.cache_key})
try{
 $package=New-RunPackage -Python $Python -RepoRoot $LiveRepo -ArtifactRoot $ArtifactProject -RunId $runId -Project fixture `
  -Mode handoff_builder_fixture -Software @('inert Python native substitute') -RetentionContractEnabled -CapacityLedgerLifecycleEnabled `
  -RetentionClass solver_review -RetentionReason 'inert retained-payload handoff fixture'
 $sessionPath=Join-Path $package.log_dir 'capacity_session.json'
 Write-RunJson -Path $sessionPath -Value $session -Depth 32
 $env:PYTHONPATH=$FrozenRepo;$env:PYTHONDONTWRITEBYTECODE='1'
 $freeze=@'
import json,sys
from pathlib import Path
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import freeze_pa_producer_handoffs,plan_pa_producer_handoffs
from common.contracts.recorded_file_removal import write_json_atomic
run,inputs,session=map(Path,sys.argv[1:]);plan=json.loads((inputs/'plan.json').read_text())
keys={c['cache_key'] for c in plan['components'] if c['cacheable']};capacity=json.loads(session.read_text(encoding='utf-8-sig'))
sources=json.loads((inputs/'handoff_sources.json').read_text())
handoff=plan_pa_producer_handoffs([(Path(s['transaction_path']),Path(s['owner_result_path'])) for s in sources],
 expected_cache_keys=keys,artifact_root=Path(capacity['artifact_root']))
bound=freeze_pa_producer_handoffs(run,handoff,expected_cache_keys=keys,capacity_session=capacity)
config=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'))
config['pa_producer_handoffs']={k:bound[k] for k in ('path','exists','bytes','sha256')}
config['inputs'].update({f'pa_handoff_{i}':r['path'] for i,r in enumerate(bound['frozen_input_records'])})
write_json_atomic(run/'run_config.json',config)
'@
 & $Python -B -c $freeze $run $Inputs $sessionPath
 if($LASTEXITCODE-ne0){throw 'Frozen handoff fixture failed'}
 function Enter-FixtureHost {param($Role,$Stage,$RunId);return [pscustomobject]@{inherited=$true;token='fixture';role=$Role;stage=$Stage}}
 function Update-FixtureHost {param($Lease,$Stage,$Budget,$RetainedMemoryBytes);return $Lease}
 function Exit-FixtureHost {param($Lease,[switch]$PassThru);return $null}
 function Invoke-FixtureNative {param($ArgumentList,$OperationId)
  $original=(Get-Command Invoke-OwnedSimionArguments -CommandType Function).ScriptBlock
  & $original -ArgumentList @('-B',$env:FIXTURE_NATIVE,(ConvertTo-Json -InputObject @($ArgumentList) -Compress)) -OperationId $OperationId
 }
 Set-Alias Enter-HostExecutionLease Enter-FixtureHost
 Set-Alias Update-HostResourceStage Update-FixtureHost
 Set-Alias Exit-HostResourceStage Exit-FixtureHost
 Set-Alias Invoke-OwnedSimionArguments Invoke-FixtureNative
 $completion=Join-Path $package.result_dir 'build_completion.json';$failure=$null
 try{
  & $Builder -SimionExe $Python -OutputDir (Join-Path $run 'simion') -ArtifactProjectRoot $ArtifactProject -RunId $runId `
   -ContractPath (Join-Path $Inputs 'resolved.json') -CandidateBaselinePath (Join-Path $Inputs 'baseline.json') `
   -CandidateTextDir $Inputs -TemplateIob (Join-Path $Inputs 'template.iob') -ParticleSeed 7 -ParticleCount 100 `
   -CapacitySessionPath $sessionPath -ComponentPlanPath (Join-Path $Inputs 'plan.json') -CompletionPath $completion `
   -ProducerHandoffPath (Join-Path $run 'inputs/pa_producer_handoffs/handoffs.json') -ContextSha256 ('a'*64) -DeferRunFinalization
 }catch{$failure=$_.Exception.Message}
 @{failure=$failure;completion=$completion;run=$run}|ConvertTo-Json|Set-Content -LiteralPath $Report -Encoding utf8
}finally{
 Remove-Item Alias:Enter-HostExecutionLease,Alias:Update-HostResourceStage,Alias:Exit-HostResourceStage,Alias:Invoke-OwnedSimionArguments -ErrorAction SilentlyContinue
 $null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $LiveRepo -Session $session
}
''', encoding="utf-8")
                    attempts = range(1, 4) if case == "repeated_publication_failure" else [1]
                    if case == "repeated_publication_failure":
                        blocker = cache / plan["components"][0]["cache_key"] / "generations"
                        blocker.parent.mkdir(exist_ok=True)
                        blocker.write_text("test-owned publication destination conflict", encoding="utf-8")
                    for attempt in attempts:
                        if case == "repeated_publication_failure" and attempt == 3:
                            blocker.unlink()
                        report = root / f"report{attempt}.json"
                        calls = root / f"native_calls{attempt}.jsonl"
                        process = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO), closure["code_root"],
                            sys.executable, str(artifact_project), str(inputs), frozen_builder, str(native), str(predecessor), str(report), str(attempt)],
                            cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "FIXTURE_CALLS": str(calls), "FIXTURE_NATIVE": str(native),
                                "FIXTURE_COUNTS": json.dumps({c["stem"]: len(c["response_ids"]) for c in plan["components"][:2]}),
                                "FIXTURE_VERIFY_FAIL": "1" if case == "verification_fails" else "0"},
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=300)
                        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                        result = json.loads(report.read_text(encoding="utf-8-sig"))
                        result["native_errors"] = {path.name: path.read_text(encoding="utf-8")
                            for path in Path(result["run"]).rglob("*.stderr.log") if path.stat().st_size}
                        actual = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []
                        if case == "repeated_publication_failure" and attempt < 3:
                            acc = pa_family_cache.load_pa_family_cache_transaction(cache, plan["components"][0]["cache_key"])
                            self.assertEqual(acc["status"], "prepared", result)
                            self.assertIn("Component cache operation failed", result["failure"], result)
                            self.assertEqual([Path(row[3]).name for row in actual], ["verify_component_pa.lua"] if attempt == 1 else [])
                            predecessor = Path(result["run"])
                            current_completion = json.loads(Path(result["completion"]).read_text(encoding="utf-8-sig"))
                            component = current_completion["components"][0]
                            self.assertEqual(component["response_build_operation_ids"], [])
                            origin = json.loads(Path(component["response_build_completion"]["path"]).read_text(encoding="utf-8"))
                            self.assertEqual(origin["run_id"], fixture.producer_run_config.parent.name)
                            self.assertNotIn("response_build_completion", origin["components"][0])
                            retained = [p for p in predecessor.rglob("*") if p.is_file() and p.name not in {"run_manifest.json", "run_config.json"}]
                            retained.append(Path(frozen_source_path(closure, "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/verify_component_pa.lua")))
                            config_path = predecessor / "run_config.json"
                            retained_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                            retained_config.setdefault("inputs", {})["original_build_completion"] = component["response_build_completion"]["path"]
                            config_path.write_text(json.dumps(retained_config), encoding="utf-8")
                            (predecessor / "run_manifest.json").write_text(json.dumps(build_run_manifest(config_path, "checkpoint", output_paths=retained)), encoding="utf-8")
                            stopped = seal_checkpoint(artifacts, config_path, owner="fixture", writing_stopped=True,
                                retain_payload=True, retention_reason="inert publication failure with confirmed closed writers")
                            transport = root / f"owner_result{attempt}.json"
                            transport.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_result", stage="complete",
                                run_directory=str(predecessor), terminal_published=True, capacity_finalized=True, lease_released=True,
                                stopped_payload_receipt=stopped)), encoding="utf-8")
                            sources[0]["owner_result_path"] = str(transport)
                            (inputs / "handoff_sources.json").write_text(json.dumps(sources), encoding="utf-8")
                    scripts = [Path(row[3]).name for row in actual]
                    self.assertNotIn("build_two_zone_pa.lua", scripts, result)
                    acc = pa_family_cache.load_pa_family_cache_transaction(cache, plan["components"][0]["cache_key"])
                    if case == "verification_fails":
                        self.assertIn("native=23", result["failure"], result)
                        self.assertEqual(acc["status"], "building")
                        self.assertFalse(acc["files"])
                        self.assertEqual(scripts, ["verify_component_pa.lua"])
                        self.assertFalse(list(cache.rglob("current_generation.json")))
                        verify_candidate_source_closure(closure)
                        continue
                    self.assertEqual(acc["status"], "published", result)
                    if case == "complete_and_partial":
                        self.assertIn("native=17", result["failure"], result)
                        self.assertEqual(scripts.count("build_reflectron_variant.lua"), 1)
                        self.assertEqual(scripts.count("refine_single_pa.lua"), len(plan["components"][1]["response_ids"]) + 1)
                        self.assertEqual(scripts.count("verify_component_pa.lua"), 2)
                        self.assertTrue(all(len(row[4:]) == 10 for row in actual if Path(row[3]).name == "verify_component_pa.lua"))
                        reflectron = pa_family_cache.load_pa_family_cache_transaction(cache, plan["components"][1]["cache_key"])
                        self.assertEqual(reflectron["status"], "published")
                        completion = json.loads(Path(result["completion"]).read_text(encoding="utf-8-sig"))
                        self.assertTrue(completion["components"][1]["response_build_operation_ids"])
                    elif case == "prepared_and_unproven":
                        self.assertIn("lacks manifest-bound completed response-build evidence", result["failure"], result)
                        self.assertNotIn("verify_component_pa.lua", scripts)
                        self.assertNotIn("build_reflectron_variant.lua", scripts)
                        self.assertEqual((transactions["reflectron"].transaction_directory / "transaction.json").read_bytes(), old_reflectron)
                    else:
                        self.assertIn("reflectron_begin", result["failure"], result)
                        self.assertIn("PA transaction owner differs", result["native_errors"]["reflectron_begin.stderr.log"])
                        self.assertEqual((transactions["reflectron"].transaction_directory / "transaction.json").read_bytes(), old_reflectron)
                        self.assertNotIn("verify_component_pa.lua", scripts)
                        self.assertNotIn("build_reflectron_variant.lua", scripts)
                    verify_candidate_source_closure(closure)
                finally:
                    fixture.tearDown()

    def test_handoff_freezing_preserves_raw_owner_result_and_binds_receipt_projection(self):
        from common.contracts.write_run_manifest import file_record
        from common.simion.test_pa_family_cache import PAFamilyCacheTest
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import (
            freeze_pa_producer_handoffs, load_pa_producer_handoffs, plan_pa_producer_handoffs,
        )

        fixture = PAFamilyCacheTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        artifacts, _, first, successor, request = fixture._producer_handoff_fixture(sealed=True)
        predecessor = fixture.producer_run_config.parent
        stopped = json.loads(Path(request["stopped_receipt"]["path"]).read_text(encoding="utf-8"))
        owner_result = fixture.root / "owner_result.json"
        owner_result.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_result", stage="complete",
            run_directory=str(predecessor), terminal_published=True, capacity_finalized=True, lease_released=True,
            stopped_payload_receipt=stopped)), encoding="utf-8")
        session = dict(role="artifact_workflow_capacity_session", status="active", artifact_root=str(artifacts),
            lease_id=request["capacity_lease_id"], owner=request["capacity_lease_owner"],
            protected_paths=[str(predecessor), str(successor.parent)])
        pair = (first.transaction_directory / "transaction.json", owner_result)
        allowed = {first.cache_key, "B" * 64}
        handoff_plan = plan_pa_producer_handoffs([pair, pair], expected_cache_keys=allowed, artifact_root=artifacts)
        self.assertEqual(len(handoff_plan["sources"]), 1)
        self.assertEqual(len(handoff_plan["source_records"]), 3)
        self.assertIn(str(predecessor), handoff_plan["protected_paths"])
        other_result = fixture.root / "other_owner_result.json"
        other_result.write_bytes(owner_result.read_bytes())
        with self.assertRaisesRegex(ValueError, "conflicting inputs"):
            plan_pa_producer_handoffs([pair, (pair[0], other_result)], expected_cache_keys=allowed, artifact_root=artifacts)
        with self.assertRaisesRegex(ValueError, "absent from the compiled"):
            plan_pa_producer_handoffs([pair], expected_cache_keys={"B" * 64}, artifact_root=artifacts)
        with self.assertRaisesRegex(ValueError, "allowed keys differ"):
            freeze_pa_producer_handoffs(successor.parent, handoff_plan,
                expected_cache_keys={first.cache_key}, capacity_session=session)
        original_result = owner_result.read_bytes()
        owner_result.write_bytes(original_result + b"\n")
        with self.assertRaisesRegex(AssertionError, "byte count changed"):
            freeze_pa_producer_handoffs(successor.parent, handoff_plan, expected_cache_keys=allowed, capacity_session=session)
        self.assertFalse((successor.parent / "inputs/pa_producer_handoffs").exists())
        owner_result.write_bytes(original_result)
        bound = freeze_pa_producer_handoffs(successor.parent, handoff_plan,
            expected_cache_keys=allowed, capacity_session=session)
        index = Path(bound["path"])
        mapping = json.loads(index.read_text(encoding="utf-8"))
        entry = mapping["entries"][first.cache_key]
        self.assertEqual(mapping["declared_cache_keys"], sorted(allowed))
        self.assertEqual({Path(row["path"]) for row in bound["frozen_input_records"]},
                         {path for path in index.parent.rglob("*") if path.is_file()})
        self.assertEqual(load_pa_producer_handoffs(index, successor.parent,
            expected_cache_keys={"B" * 64}, capacity_session=session), {})
        self.assertEqual(Path(entry["owner_result"]["path"]).read_bytes(), owner_result.read_bytes())
        selected = load_pa_producer_handoffs(index, successor.parent, expected_cache_keys={first.cache_key}, capacity_session=session)
        self.assertFalse(selected[first.cache_key]["response_build_complete"])
        self.assertTrue(selected[first.cache_key]["has_sealed_inventory"])
        with self.assertRaisesRegex(ValueError, "current workflow capacity session"):
            load_pa_producer_handoffs(index, successor.parent, expected_cache_keys={first.cache_key},
                capacity_session={**session, "owner": "different-session"})
        request_path = Path(entry["request"]["path"])
        frozen_request = json.loads(request_path.read_text(encoding="utf-8"))
        projection = Path(frozen_request["stopped_receipt"]["path"])
        projection.write_text(json.dumps({**stopped, "run_status": "failed"}), encoding="utf-8")
        frozen_request["stopped_receipt"] = file_record(projection)
        request_path.write_text(json.dumps(frozen_request), encoding="utf-8")
        entry["request"] = file_record(request_path)
        index.write_text(json.dumps(mapping), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact projection"):
            load_pa_producer_handoffs(index, successor.parent, expected_cache_keys={first.cache_key}, capacity_session=session)
        with self.assertRaisesRegex(ValueError, "exact projection"):
            load_pa_producer_handoffs(index, successor.parent, expected_cache_keys={"B" * 64}, capacity_session=session)

    def test_handoff_freeze_rejects_source_change_between_precheck_and_copy(self):
        from unittest import mock
        from common.contracts.frozen_inputs import freeze_file
        from common.simion.test_pa_family_cache import PAFamilyCacheTest
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import (
            freeze_pa_producer_handoffs, plan_pa_producer_handoffs,
        )
        fixture = PAFamilyCacheTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        artifacts, _, first, successor, request = fixture._producer_handoff_fixture(sealed=True)
        predecessor = fixture.producer_run_config.parent
        stopped = json.loads(Path(request["stopped_receipt"]["path"]).read_text(encoding="utf-8"))
        owner_result = fixture.root / "owner_result.json"
        owner_result.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_result", stage="complete",
            run_directory=str(predecessor), terminal_published=True, capacity_finalized=True, lease_released=True,
            stopped_payload_receipt=stopped)), encoding="utf-8")
        plan = plan_pa_producer_handoffs([(first.transaction_directory / "transaction.json", owner_result)],
            expected_cache_keys={first.cache_key}, artifact_root=artifacts)
        session = dict(role="artifact_workflow_capacity_session", status="active", artifact_root=str(artifacts),
            lease_id=request["capacity_lease_id"], owner=request["capacity_lease_owner"],
            protected_paths=[str(predecessor), str(successor.parent)])
        original = owner_result.read_bytes()
        def copy_after_source_changed(source, destination):
            if source == owner_result:
                source.write_bytes(original + b"\n")
            return freeze_file(source, destination)
        with mock.patch("common.contracts.frozen_inputs.freeze_file", side_effect=copy_after_source_changed):
            with self.assertRaisesRegex(ValueError, "differs from its planned byte identity"):
                freeze_pa_producer_handoffs(successor.parent, plan,
                    expected_cache_keys={first.cache_key}, capacity_session=session)
        self.assertFalse((successor.parent / "inputs/pa_producer_handoffs/handoffs.json").exists())

    def test_detached_builder_reaches_first_native_with_real_capacity_and_cache(self):
        # Keep the frozen producer byte-identical. Only host admission is an
        # explicit software adapter; the outer test keeps its real GATE grant.
        # Python deliberately rejects SIMION's first argument, before any PA.
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        from common.contracts.capacity_protection import load_capacity_protection_leases
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
            freeze_candidate_source_closure, frozen_source_path, verify_candidate_source_closure,
        )
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import compile_component_pa_plan
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
            render_fly2, render_program, render_resolved_lua,
        )

        with tempfile.TemporaryDirectory(prefix="candidate-detached-build-") as directory:
            root = Path(directory)
            project = REPO / "projects/single_reflection_oa_tof_mass_analyzer"
            artifacts = root / "artifacts"
            artifact_project = artifacts / "projects/single_reflection_oa_tof_mass_analyzer"
            artifact_project.mkdir(parents=True)
            initialize_capacity_ledger(artifacts, objects=[])
            closure = freeze_candidate_source_closure(root / "code", artifact_project)
            frozen_builder = frozen_source_path(closure, BUILDER.relative_to(REPO).as_posix())
            inputs = root / "science"
            inputs.mkdir()
            contract = json.loads((project / "config/resolved_geometry.json").read_text(encoding="utf-8"))
            (inputs / "resolved.json").write_text(json.dumps(contract), encoding="utf-8")
            shutil.copyfile(project / "config/baseline.json", inputs / "baseline.json")
            for name, payload in {
                "oatof_resolved.lua": render_resolved_lua(contract),
                "oatof_ideal_grounded.lua": render_program(contract),
                "oatof_ideal_grounded.fly2": render_fly2(contract, particle_source_seed=7),
            }.items():
                (inputs / name).write_text(payload, encoding="utf-8")
            (inputs / "template.iob").write_text("software fixture; not opened before first native", encoding="utf-8")
            (inputs / "template.con").write_text("software fixture", encoding="utf-8")
            plan = compile_component_pa_plan(contract, repository_root=REPO, simion_exe=Path(sys.executable))
            (inputs / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            driver = root / "driver.ps1"
            driver.write_text(r'''
param($LiveRepo,$FrozenRepo,$Python,$ArtifactProject,$Inputs,$Builder,$Report)
$ErrorActionPreference='Stop';$PSNativeCommandUseErrorActionPreference=$false
. (Join-Path $LiveRepo 'common/contracts/run_artifact_support.ps1')
# A small, test-owned capacity ledger is real. Its admission decision is a
# software fixture, independent of the developer machine's current free disk.
function Invoke-ArtifactCapacityGate { return @{satisfied=$true;fixture_admission=$true} }
$runId='20261029_010000__test__simion__detached-builder-boundary'
$artifactRoot=Split-Path (Split-Path $ArtifactProject -Parent) -Parent
$run=Join-Path $ArtifactProject ('runs/'+$runId)
$session=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $LiveRepo `
 -ArtifactRoot $artifactRoot -RunDirectory $run -CommittedNewBytes 0 -Owner 'detached-builder-fixture'
try{
 $package=New-RunPackage -Python $Python -RepoRoot $LiveRepo -ArtifactRoot $ArtifactProject `
  -RunId $runId -Project single_reflection_oa_tof_mass_analyzer -Mode detached_builder_fixture `
  -Software @('Python 3.11 software native substitute') -RetentionContractEnabled -CapacityLedgerLifecycleEnabled
 $sessionPath=Join-Path $package.log_dir 'capacity_session.json'
 Write-RunJson -Path $sessionPath -Value $session -Depth 32
 # Aliases are scoped to this fixture process and survive the producer's
 # normal dot-sourcing without editing any frozen source file.
 function Enter-FixtureHost {param($Role,$Stage,$RunId)
  if($Role-ne'SIMION'-or$Stage-ne'prepare'){throw 'Unexpected builder admission'}
  return [pscustomobject]@{inherited=$true;token='explicit-software-admission';role=$Role;stage=$Stage}
 }
 function Update-FixtureHost {param($Lease,$Stage,$Budget,$RetainedMemoryBytes);return $Lease}
 function Exit-FixtureHost {param($Lease,[switch]$PassThru);return $null}
 Set-Alias Enter-HostExecutionLease Enter-FixtureHost
 Set-Alias Update-HostResourceStage Update-FixtureHost
 Set-Alias Exit-HostResourceStage Exit-FixtureHost
 $completion=Join-Path $package.result_dir 'builder_completion.json'
 $failure=$null
 $env:PYTHONPATH=$FrozenRepo;$env:PYTHONDONTWRITEBYTECODE='1'
 try{
  & $Builder -SimionExe $Python -OutputDir (Join-Path $run 'simion') -ArtifactProjectRoot $ArtifactProject `
   -RunId $runId -ContractPath (Join-Path $Inputs 'resolved.json') -CandidateBaselinePath (Join-Path $Inputs 'baseline.json') `
   -CandidateTextDir $Inputs -TemplateIob (Join-Path $Inputs 'template.iob') -ParticleSeed 7 -ParticleCount 100 `
   -CapacitySessionPath $sessionPath -ComponentPlanPath (Join-Path $Inputs 'plan.json') `
   -CompletionPath $completion -ContextSha256 ('a'*64) -DeferRunFinalization
 }catch{$failure=$_.Exception.Message}
 @{failure=$failure;completion=$completion;run=$run}|ConvertTo-Json|Set-Content -LiteralPath $Report -Encoding utf8
}finally{
 Remove-Item Alias:Enter-HostExecutionLease,Alias:Update-HostResourceStage,Alias:Exit-HostResourceStage -ErrorAction SilentlyContinue
 $null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $LiveRepo -Session $session
}
''', encoding="utf-8")
            report = root / "report.json"
            process = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO), closure["code_root"],
                sys.executable, str(artifact_project), str(inputs), frozen_builder, str(report)], cwd=root,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False, timeout=180)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads(report.read_text(encoding="utf-8-sig"))
            self.assertIn("worker=1, native=2", result["failure"], result)
            completion = json.loads(Path(result["completion"]).read_text(encoding="utf-8-sig"))
            native = [item for item in completion["operations"] if item.get("operation_kind") != "python_metadata"]
            self.assertEqual(len(native), 1, completion)
            self.assertTrue(native[0]["observation"]["exit_confirmed"])
            self.assertEqual(native[0]["observation"]["returncode"], 2)
            self.assertTrue(native[0]["managed_process_completion"]["worker_exit_confirmed"])
            self.assertTrue(any(item["operation_id"] == "cache_accelerator_begin" for item in completion["operations"]))
            self.assertFalse(list(artifacts.rglob("current_generation.json")))
            self.assertFalse(list(artifacts.rglob("*.pa#")))
            self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])
            verify_candidate_source_closure(closure)

    def test_cache_metadata_dispatch_waits_for_actual_writer_and_records_failures(self):
        from common.simion.test_pa_family_cache import identity

        with tempfile.TemporaryDirectory(prefix="candidate-cache-worker-") as directory:
            root = Path(directory)
            (root / "identity.json").write_text(json.dumps(identity()), encoding="utf-8")
            (root / "run_config.json").write_text(json.dumps({"run_id": "fixture-pa-producer", "project": "fixture"}), encoding="utf-8")
            driver = root / "driver.ps1"
            driver.write_text(r'''
param($Repo,$Python,$Root,$Builder)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/resource_budget_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Builder,[ref]$tokens,[ref]$errors)
$node=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and
 $node.Name-eq'Invoke-ComponentCache'},$true))
if($node.Count-ne1){throw 'Expected the unique production cache dispatch.'}
. ([scriptblock]::Create($node[0].Extent.Text))
$script:cacheFactIndex=0
$actualManaged=(Get-Item Function:Invoke-RepositoryManagedPythonProcess).ScriptBlock
function Invoke-RepositoryManagedPythonProcess {
 param($Python,$ArgumentList,$WorkingDirectory,$StandardOutputPath,$StandardErrorPath)
 $ArgumentList=@($ArgumentList)
 $fact=Join-Path $Root ('worker-'+$script:cacheFactIndex+'.json');$script:cacheFactIndex++
 $ArgumentList[2]=$ArgumentList[2].Replace('import runpy;',
  'import os,json,sys; from pathlib import Path; Path(os.environ["CACHE_WORKER_FACT"]).write_text(json.dumps({"pid":os.getpid(),"python":sys.executable}),encoding="utf-8"); import runpy;')
 & $actualManaged -Python $Python -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory `
  -StandardOutputPath $StandardOutputPath -StandardErrorPath $StandardErrorPath `
  -Environment @{CACHE_WORKER_FACT=$fact}
}
$repoRoot=$Repo;$python=$Python;$buildLogs=Join-Path $Root 'logs';New-Item -ItemType Directory $buildLogs|Out-Null
$nativeOperations=[Collections.Generic.List[object]]::new()
$arguments=@('--cache-root',(Join-Path $Root 'cache'),'--identity',(Join-Path $Root 'identity.json'),
 '--filenames','field.pa#,field.pa0,field.pa1')
$probe=Invoke-ComponentCache ($arguments+@('--action','probe')) 'probe'
$transaction=Invoke-ComponentCache ($arguments+@('--action','advance-transaction','--owner','fixture',
 '--producer-run-config',(Join-Path $Root 'run_config.json'))) 'begin'
$failure=$null
try{$null=Invoke-ComponentCache ($arguments+@('--action','not-an-action')) 'bad-action'}catch{$failure=$_.Exception.Message}
@{probe=$probe;transaction=$transaction;operations=$nativeOperations.ToArray();error=$failure;stopped=$script:allOperationsStopped}|
 ConvertTo-Json -Depth 64|Set-Content -LiteralPath (Join-Path $Root 'report.json') -Encoding utf8
''', encoding="utf-8")
            process = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO), sys.executable,
                str(root), str(BUILDER)], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads((root / "report.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(result["probe"]["disposition"], "miss")
            self.assertEqual(result["transaction"]["action_required"], "build")
            self.assertTrue(Path(result["transaction"]["transaction_directory"]).is_dir())
            self.assertTrue(result["stopped"])
            self.assertIn("Component cache operation failed", result["error"])
            self.assertEqual(len(result["operations"]), 3)
            for index, operation in enumerate(result["operations"]):
                self.assertEqual(operation["operation_kind"], "python_metadata")
                self.assertTrue(operation["observation"]["exit_confirmed"])
                self.assertEqual(operation["observation"]["returncode"] == 0, index < 2)
                self.assertTrue(operation["managed_process_completion"]["ownership_confirmed"])
                receipt = operation["managed_process_completion"]
                actual = json.loads((root / f"worker-{index}.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["worker_process_id"], actual["pid"])
                self.assertEqual(Path(actual["python"]).resolve(), Path(sys.executable).resolve())
                self.assertGreater(receipt["worker_started_at_utc_ticks"], 0)
                self.assertGreater(receipt["launcher_process_id"], 0)
                self.assertTrue(receipt["ack_attempted"] and receipt["worker_exit_confirmed"]
                                and receipt["launcher_exit_confirmed"]
                                and receipt["stdout_drained"] and receipt["stderr_drained"])
                print("CACHE_ACTUAL_WORKER=" + json.dumps({"actual": actual, "completion": receipt}))

    def test_guarded_flight_real_entry_keeps_guards_until_native_and_worker_completion(self):
        # Admission alone is a software fixture adapter. The production entry,
        # file guards, actual-worker handshake and native observer are real;
        # the explicitly synthetic native writer is Python, never SIMION.
        for case in ("pass", "nonzero", "changed_source", "unknown"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="candidate-flight-") as directory:
                root = Path(directory)
                repo = root / "repo"
                relatives = (
                    "common/host_execution_lease.ps1", "common/host_resource_python.py",
                    "common/contracts/run_artifact_support.ps1", "common/require_powershell7.ps1",
                    "common/resource_budget_support.ps1", "common/simion/short_pa_path_support.ps1",
                    "common/simion/process_observation.py", "common/contracts/recorded_file_removal.py",
                    "common/contracts/file_identity.py",
                    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_candidate_flight.ps1",
                )
                for relative in relatives:
                    target = repo / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(REPO / relative, target)
                host = repo / "common/host_execution_lease.ps1"
                host.write_text(host.read_text(encoding="utf-8") + r'''
function Enter-HostExecutionLease {
 param($Role,$Stage,$RunId)
 if($Role-ne'SIMION'-or$Stage-ne'flight'){throw 'wrong fixture stage request'}
 return [pscustomobject]@{inherited=$true;token='explicit-software-fixture'}
}
function Exit-HostResourceStage {param($Lease,[switch]$PassThru); return $null}
''', encoding="utf-8")
                artifact_support = repo / "common/contracts/run_artifact_support.ps1"
                artifact_support.write_text(artifact_support.read_text(encoding="utf-8") + r'''
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session)
 if($Session.status-ne'active'){throw 'fixture session is inactive'}
 return @{session=$Session}
}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation);Push-Location $RepoRoot;try{&$Operation}finally{Pop-Location}}
''', encoding="utf-8")
                if case == "unknown":
                    resources = repo / "common/resource_budget_support.ps1"
                    resources.write_text(resources.read_text(encoding="utf-8") +
                        "\nfunction Get-ManagedSolverProcessSample {throw 'deliberate initial identity observation failure'}\n", encoding="utf-8")
                run = root / "artifacts/projects/fixture/runs/fixture-run"
                runtime = run / "simion"
                runtime.mkdir(parents=True)
                logs = run / "logs"
                logs.mkdir()
                pa, iob = runtime / "fixture.pa0", runtime / "fixture.iob"
                pa.write_bytes(b"explicit software PA fixture")
                iob.write_bytes(b"explicit software IOB fixture")

                def record(path):
                    return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}

                receipt = {"schema_version": 1, "role": "oatof_simion_private_runtime", "status": "verified",
                    "run_id": run.name, "context_sha256": "a" * 64, "canonical_iob_verified": True,
                    "execution_alias_removed": True, "published_native_members_opened": False,
                    "output_directory": str(runtime), "simion_executable_sha256": file_sha256(Path(sys.executable)),
                    "files": [record(pa)], "iob": record(iob), "components": []}
                if case == "changed_source":
                    receipt["files"][0]["sha256"] = "0" * 64
                runtime_receipt = run / "runtime.json"
                runtime_receipt.write_text(json.dumps(receipt), encoding="utf-8")
                session = run / "session.json"
                session.write_text(json.dumps({"role": "artifact_workflow_capacity_session", "status": "active",
                    "protected_paths": [str(run)]}), encoding="utf-8")
                marker = run / "native_started.txt"
                code = ("from pathlib import Path\n" + f"Path({str(marker)!r}).write_text('started')\n"
                    + f"p=Path({str(pa)!r})\ntry:\n p.write_bytes(b'forbidden write')\n"
                    + "except PermissionError:\n print('software guard blocked write')\n"
                    + "else:\n raise RuntimeError('private PA guard was absent')\n"
                    + f"raise SystemExit({7 if case == 'nonzero' else 0})\n")
                result_path = logs / "result.json"
                request = {"schema_version": 1, "role": "oatof_candidate_flight_request", "run_id": run.name,
                    "context_sha256": "a" * 64, "case_id": "fixture", "mode": "native",
                    "executable": sys.executable, "argv": ["-c", code, "fly", str(iob)], "cwd": str(runtime),
                    "stdout": str(logs / "native.stdout.log"), "stderr": str(logs / "native.stderr.log"),
                    "result_receipt": str(result_path), "warning_seconds": 30}
                request_path = run / "request.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                driver = root / "driver.ps1"
                driver.write_text(r'''
param($Repo,$Python,$Request,$Runtime,$Session,$Report)
$ErrorActionPreference='Stop';$failure=$null
try{& (Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_candidate_flight.ps1') `
 -ExecutionRequestPath $Request -RuntimeReceiptPath $Runtime -CapacitySessionPath $Session -PythonExe $Python -RepositoryRoot $Repo}
catch{$failure=$_.Exception.Message}
@{error=$failure;guard_count=$global:MassSpectrometryImmutablePaSourceGuards.Count}|
 ConvertTo-Json|Set-Content -LiteralPath $Report -Encoding utf8
# Every process in this fixture is now naturally exited; retained guards in
# the deliberately unknown arm are inspected before this test-owned cleanup.
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
foreach($path in @($global:MassSpectrometryImmutablePaSourceGuards.Keys)){Unprotect-ImmutablePaSource -Source $path|Out-Null}
''', encoding="utf-8")
                report = root / "report.json"
                process = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(repo), sys.executable,
                    str(request_path), str(runtime_receipt), str(session), str(report)], cwd=repo,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=90)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                outcome = json.loads(report.read_text(encoding="utf-8-sig"))
                native = json.loads(result_path.read_text(encoding="utf-8-sig"))
                self.assertEqual(pa.read_bytes(), b"explicit software PA fixture")
                if case in {"pass", "nonzero"}:
                    self.assertTrue(marker.is_file())
                    self.assertTrue(native["native_exit_confirmed"])
                    self.assertEqual(native["native_returncode"], 7 if case == "nonzero" else 0)
                    self.assertTrue(native["managed_process_completion"]["ownership_confirmed"])
                    self.assertEqual(outcome["guard_count"], 0)
                    self.assertEqual(outcome["error"] is None, case == "pass")
                else:
                    self.assertFalse(marker.exists())
                    self.assertFalse(native["native_exit_confirmed"])
                    self.assertIsNotNone(outcome["error"])
                    self.assertEqual(outcome["guard_count"], 2 if case == "unknown" else 0)
                self.assertEqual(native["host_release"], {"inherited": True, "token": "explicit-software-fixture", "result": None, "error": None})

    def test_builder_actual_worker_handshake_preserves_native_failure_and_unknown(self):
        with tempfile.TemporaryDirectory(prefix="candidate-pa-worker-") as directory:
            root = Path(directory)
            fixture_repo = root / "observer_failure_repo"
            for relative in ("common/host_resource_python.py", "common/simion/process_observation.py",
                             "common/contracts/recorded_file_removal.py", "common/contracts/file_identity.py"):
                target = fixture_repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / relative, target)
            observer = fixture_repo / "common/simion/process_observation.py"
            observer.write_text(observer.read_text(encoding="utf-8") +
                "\ndef process_working_set_bytes(process_id):\n    raise RuntimeError('deliberate native metric failure')\n",
                encoding="utf-8")
            driver = root / "driver.ps1"
            driver.write_text(r'''
param($Repo,$Python,$Root,$Builder,$ObserverFailureRepo)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/resource_budget_support.ps1')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Builder,[ref]$tokens,[ref]$errors)
if($errors){throw $errors[0]}
$node=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and
 $node.Name-eq'Invoke-OwnedSimionArguments'},$true))
if($node.Count-ne1){throw 'Expected the unique production native adapter.'}
. ([scriptblock]::Create($node[0].Extent.Text))
$repoRoot=$Repo;$python=$Python;$SimionExe=$Python;$outputFull=$Root
$buildLogs=Join-Path $Root 'logs';New-Item -ItemType Directory $buildLogs|Out-Null
$script:allOperationsStopped=$true
$report=[Collections.Generic.List[object]]::new()
foreach($code in @(0,7)){
 $label='native'+$code
 try{
  $result=Invoke-OwnedSimionArguments -ArgumentList @('-c',("print('real fixture native');raise SystemExit("+$code+")")) -OperationId $label
  $report.Add(@{label=$label;returned=$true;facts=$result;stopped=$script:allOperationsStopped})
 }catch{
  $report.Add(@{label=$label;returned=$false;facts=$_.Exception.Data['native_operation_observation'];
    stopped=$script:allOperationsStopped;error=$_.Exception.Message})
 }
}
$repoRoot=$ObserverFailureRepo
try{
 $result=Invoke-OwnedSimionArguments -ArgumentList @('-c',"import time;time.sleep(0.3)") -OperationId 'observer_failure'
 $report.Add(@{label='observer_failure';returned=$true;facts=$result;stopped=$script:allOperationsStopped})
}catch{
 $report.Add(@{label='observer_failure';returned=$false;facts=$_.Exception.Data['native_operation_observation'];
   stopped=$script:allOperationsStopped;error=$_.Exception.Message})
}
$repoRoot=$Repo
function Get-ManagedSolverProcessSample {throw 'deliberate initial observation failure'}
$marker=Join-Path $Root 'must_not_start.txt'
try{
 $null=Invoke-OwnedSimionArguments -ArgumentList @('-c',"from pathlib import Path;Path(r'$marker').write_text('unexpected')") -OperationId 'unknown'
 throw 'Unknown initial observation unexpectedly passed.'
}catch{
 $report.Add(@{label='unknown';facts=$_.Exception.Data['native_operation_observation'];
   stopped=$script:allOperationsStopped;error=$_.Exception.Message;native_started=(Test-Path -LiteralPath $marker)})
}
$report.ToArray()|ConvertTo-Json -Depth 32|Set-Content -LiteralPath (Join-Path $Root 'report.json') -Encoding utf8
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO), sys.executable,
                str(root), str(BUILDER), str(fixture_repo)], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = {row["label"]: row for row in json.loads((root / "report.json").read_text(encoding="utf-8-sig"))}
            for code in (0, 7):
                row = rows[f"native{code}"]
                self.assertEqual(row["returned"], code == 0, row)
                self.assertTrue(row["stopped"], row)
                facts = row["facts"]
                self.assertTrue(facts["observation"]["exit_confirmed"])
                self.assertEqual(facts["observation"]["returncode"], code)
                completion = facts["managed_process_completion"]
                self.assertEqual(completion["role"], "repository_managed_python_completion")
                for key in ("ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed", "stdout_drained", "stderr_drained"):
                    self.assertTrue(completion[key], completion)
            failure = rows["observer_failure"]
            self.assertFalse(failure["returned"], failure)
            self.assertTrue(failure["stopped"], failure)
            self.assertEqual(failure["facts"]["observation"]["returncode"], 0)
            self.assertEqual(failure["facts"]["managed_process_completion"]["exit_code"], 1)
            self.assertIn("deliberate native metric failure", failure["error"])
            unknown = rows["unknown"]
            self.assertFalse(unknown["stopped"] or unknown["native_started"], unknown)
            self.assertFalse(unknown["facts"]["observation"]["exit_confirmed"])
            self.assertIn("deliberate initial observation failure", unknown["error"])


if __name__ == "__main__":
    unittest.main()
