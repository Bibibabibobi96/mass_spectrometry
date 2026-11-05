"""Native path and source ownership through the real workflow owner."""

from __future__ import annotations
import json
import os
import time
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from common.contracts import capacity_ledger
from common.contracts.capacity_ledger import initialize_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases
from common.contracts.write_run_manifest import file_record
from common.contracts.test_support import run_artifact_workflow as fixture
from common.contracts.test_support.run_artifact_workflow import CALLBACK, OWNER, PROJECT, PWSH, REPO, released_writer


@unittest.skipUnless(PWSH and os.name == "nt", "Windows PowerShell workflow boundary")
class RunArtifactSourceTests(fixture.RunArtifactWorkflowFixture):
    def test_prepared_src_import_roots_keep_core_and_resources_frozen(self) -> None:
        extra = '''    from msplatform.io import file_identity as core_identity
    from msplatform.contracts import machine_contracts as core_contracts
    prepared_root = Path(__file__).parent.resolve()
    assert Path(core_identity.__file__).resolve().is_relative_to(prepared_root / 'src')
    assert Path(core_contracts.__file__).resolve().is_relative_to(prepared_root / 'src')
    assert core_identity.file_sha256(Path(__file__))
    assert core_contracts.schema_registry()
    if payload.get('missing_core'):
        (prepared_root / 'src/msplatform/assembly/resolve_assembly.py').unlink()
    from msplatform.assembly import resolve_assembly
    assert Path(resolve_assembly.__file__).resolve().is_relative_to(prepared_root / 'src')
'''
        needle = '    counter = Path(payload["counter_path"])'
        callback = CALLBACK.replace(needle, extra + needle)
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory(prefix='src 工作 roots ') as directory:
                root = Path(directory)
                result, _, _, outcome = self.invoke_fixture(root, {'missing_core': missing}, callback_text=callback)
                if missing:
                    self.assertNotEqual(outcome.returncode, 0)
                    self.assertEqual(result['status'], 'failed')
                    self.assertIn('resolve_assembly', result['exception']['message'])
                else:
                    self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr + str(result))
                    self.assertEqual(result['status'], 'success')

    def test_declared_future_native_paths_select_managed_execution_before_callback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-native-plan-") as directory:
            root = Path(directory) / ("p" * 24)
            root.mkdir()
            relative = "results/native/" + ("n" * 90) + ".csv"
            extra = """    if payload.get("future_native_relative"):
        relative = payload["future_native_relative"]
        canonical = root / relative
        native_root = Path(os.environ["MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"])
        native = native_root / relative
        assert len(str(canonical)) > 259
        assert len(str(native)) <= 259 and native_root != root and native_root.is_dir()
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_text("inert_path_probe\\n1\\n", encoding="utf-8")
        assert canonical.read_bytes() == native.read_bytes()
        probe = root / "results/native_path_probe.json"
        probe.write_text(json.dumps({"canonical": str(canonical), "execution": str(native), "alias": str(native_root)}), encoding="utf-8")
        completion["output_paths"].extend([str(canonical), str(probe)])
"""
            needle = '    completion_path.write_text(json.dumps(completion), encoding="utf-8")'
            self.assertEqual(CALLBACK.count(needle), 1)
            callback = CALLBACK.replace(needle, extra + needle)
            with unittest.mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_EXECUTION_ROOT": str(Path(directory) / "x")}):
                result, run, _, outcome = self.invoke_fixture(root, {"future_native_relative": relative},
                    callback_text=callback, expected_execution_relative_paths=[relative])
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            probe = json.loads((run / "results/native_path_probe.json").read_text(encoding="utf-8"))
            self.assertTrue(Path(probe["canonical"]).is_file())
            self.assertFalse(Path(probe["alias"]).exists())
            self.assertTrue(result["execution_alias_removed"])
            self.assertEqual(json.loads((run / "inputs/execution_request.json").read_text(encoding="utf-8"))["package"]["expected_execution_relative_paths"], [relative])


    def test_declared_native_paths_reject_escape_and_invalid_types_before_run(self) -> None:
        for value in (["../escape.csv"], [str(REPO / "outside.csv")], "results/file.csv", [7]):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, run, _, outcome = self.invoke_fixture(root, {}, expected_execution_relative_paths=value)
                self.assertNotEqual(outcome.returncode, 0)
                self.assertEqual(result["stage"], "validate")
                self.assertFalse(run.exists())
                self.assertFalse((root / "callback_count.txt").exists())
                self.assertIn("path", (outcome.stdout + outcome.stderr).lower())


    def test_native_source_resolver_streams_large_session_and_keeps_authority(self) -> None:
        with tempfile.TemporaryDirectory(prefix="source-stdin-") as directory:
            root = Path(directory)
            parent, source_root, model, reference, before = self._native_source_fixture(root, deep=False)
            consumer = root / "consumer"
            consumer.mkdir()
            artifacts = consumer / "artifacts"
            artifacts.mkdir()
            initialize_capacity_ledger(artifacts, objects=[])
            request = root / "source.json"
            request.write_text(json.dumps({"references": [reference], "path": str(model)}), encoding="utf-8")
            result = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{return @{{satisfied=$true;fixture_admission=$true}}}}
$source=Get-Content -Raw '{request}'|ConvertFrom-Json -AsHashtable
$session=Enter-ArtifactWorkflowCapacitySession -Python '{sys.executable}' -RepoRoot '{REPO}' -ArtifactRoot '{artifacts}' -RunDirectory '{artifacts / 'projects' / PROJECT / 'runs/20261031_120000__test__python__stdin'}' -CommittedNewBytes 0 -SourceReferences $source.references
try{{
 $session|Add-Member -Force -NotePropertyName startup_gate -NotePropertyValue @{{diagnostic=('多字节' * 30000)}}
 $json=$session|ConvertTo-Json -Depth 64 -Compress
 if($json.Length-lt65536){{throw 'Large session fixture is too small'}}
 $rows=@(Resolve-RunSourceExecutionInputs -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $session -SourceReferences $source.references -NativeInputPaths @($source.path) -RequireProtection)
 if($rows.Count-ne1-or$rows[0].input_paths.Count-ne1-or$rows[0].input_paths[0]-ne$source.path){{throw 'Large source resolver result differs'}}
 $rejected=$false
 try{{Resolve-RunSourceExecutionInputs -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $session -SourceReferences @() -NativeInputPaths @($source.path) -RequireProtection|Out-Null}}catch{{if($_.Exception.Message-notmatch'uniquely bound'){{throw}};$rejected=$true}}
 if(-not$rejected){{throw 'Unbound source accepted'}}
 $inactive=$session|ConvertTo-Json -Depth 64|ConvertFrom-Json -AsHashtable
 $inactive.status='released'
 $rejected=$false
 try{{Resolve-RunSourceExecutionInputs -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $inactive -SourceReferences $source.references -NativeInputPaths @($source.path) -RequireProtection|Out-Null}}catch{{if($_.Exception.Message-notmatch'admitted protection owner'){{throw}};$rejected=$true}}
 if(-not$rejected){{throw 'Inactive protection accepted'}}
 Write-Output ('SESSION_UTF16_CHARS='+$json.Length)
}}finally{{Exit-ArtifactWorkflowCapacitySession -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $session|Out-Null}}
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SESSION_UTF16_CHARS=", result.stdout)
            self.assertEqual(before, {path: path.read_bytes() for path in before})
            self.assertFalse(load_capacity_protection_leases(source_root)["protected_paths"])
            self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])

    def test_initialize_source_authority_failure_cleans_only_own_execution_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix="initialize-alias-") as directory:
            root = Path(directory)
            execution = root / "execution"
            consumer = root / ("consumer_" + "x" * 180)
            consumer.mkdir()
            unbound = root / "unbound.json"
            unbound.write_text("{}", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_EXECUTION_ROOT": str(execution)}):
                result, run, artifacts, process = self.invoke_fixture(consumer, {},
                    source_references=[], native_input_paths=[str(unbound)],
                    expected_execution_relative_paths=["inputs/task.m"])
            self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertGreater(len(str(run)), 259)
            self.assertEqual(result["stage"], "initialize")
            self.assertIn("uniquely bound", result["exception"]["message"])
            self.assertTrue(result["lease_released"])
            self.assertTrue(result["execution_alias_removed"])
            self.assertFalse(list(execution.iterdir()))
            self.assertFalse((consumer / "callback_count.txt").exists())
            self.assertIsNone(result["prepared_exit_code"])
            self.assertFalse(result["terminal_published"])
            self.assertEqual(result["secondary_errors"], [])
            self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])
            self.assertEqual(unbound.read_text(encoding="utf-8"), "{}")
            self.assertTrue((run / "run_config.json").is_file())

    def test_python_native_source_context_short_inputs_need_no_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix='native-source-short-') as directory:
            root = Path(directory)
            with unittest.mock.patch.dict(os.environ, {'MASS_SPECTROMETRY_EXECUTION_ROOT': str(root / 'execution')}):
                parent, source_root, model, reference, before = self._native_source_fixture(root, deep=False)
                consumer = root / 'consumer'; consumer.mkdir()
                result, run, _, process = self.invoke_fixture(consumer,
                    {'source_artifact_root': str(source_root), 'source_run_directory': str(parent)},
                    source_references=[reference], native_input_paths=[str(model)])
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                context = result['source_execution_context']
                self.assertTrue(result['source_execution_aliases_removed'])
                self.assertGreaterEqual(result['native_path_preparation']['calls'], 2)
                self.assertGreater(result['native_path_preparation']['elapsed_seconds'], 0)
                self.assertEqual(result['native_path_preparation']['transport_bytes'], 0)
                self.assertTrue(all(row['execution_alias'] is None and row['execution_directory'] == row['target_directory']
                                    for row in context['sources']))
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                self.assertFalse(load_capacity_protection_leases(source_root)['protected_paths'])

    def test_python_native_source_context_recovers_cleanup_with_expired_leases_and_no_new_process(self) -> None:
        with tempfile.TemporaryDirectory(prefix='native-source-recovery-') as directory:
            root = Path(directory)
            with unittest.mock.patch.dict(os.environ, {'MASS_SPECTROMETRY_EXECUTION_ROOT': str(root / 'execution')}):
                parent, source_root, model, reference, before = self._native_source_fixture(root, deep=True)
                consumer = root / 'consumer'; consumer.mkdir()
                result, run, artifacts, process = self.invoke_fixture(consumer,
                    {'source_artifact_root': str(source_root), 'source_run_directory': str(parent)},
                    source_references=[reference], native_input_paths=[str(model)], failure_stage='source_alias_cleanup')
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertTrue(result['writers_confirmed'])
                self.assertEqual(result['resume_action'], 'resume_finalization')
                context = result['source_execution_context']
                aliases = [Path(row['execution_alias']) for row in context['sources']]
                self.assertTrue(aliases and all(path.is_dir() for path in aliases))
                session = json.loads((run / 'logs/capacity_session.json').read_text(encoding='utf-8-sig'))
                for artifact, lease_id in [(artifacts, session['lease_id']),
                        (source_root, session['source_protection_leases'][0]['lease_id'])]:
                    path = artifact / 'common/capacity_protection_leases' / f'{lease_id}.json'
                    value = json.loads(path.read_text(encoding='utf-8-sig'))
                    value['expires_at_utc'] = '2001-01-01T00:00:00Z'
                    path.write_text(json.dumps(value), encoding='utf-8')
                recovered, process = self.resume_fixture(consumer, run)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertTrue(recovered['source_execution_aliases_removed'] and recovered['terminal_published'])
                self.assertEqual(recovered['source_execution_context'], context)
                self.assertEqual(recovered['recovery_session']['source_execution_context'], context)
                self.assertTrue(all(not path.exists() for path in aliases))
                self.assertEqual((consumer / 'callback_count.txt').read_text(), '1')
                again, process = self.resume_fixture(consumer, run)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertTrue(again['terminal_published'])
                self.assertEqual((consumer / 'callback_count.txt').read_text(), '1')
                self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_python_native_source_unknown_writer_and_callback_tamper_keep_original_alias(self) -> None:
        for scenario in ('unknown', 'tamper'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix='native-source-hold-') as directory:
                root = Path(directory)
                with unittest.mock.patch.dict(os.environ, {'MASS_SPECTROMETRY_EXECUTION_ROOT': str(root / 'execution')}):
                    parent, source_root, model, reference, before = self._native_source_fixture(root, deep=True)
                    consumer = root / 'consumer'; consumer.mkdir()
                    payload = {'source_artifact_root': str(source_root), 'source_run_directory': str(parent)}
                    if scenario == 'unknown':
                        payload['writers'] = released_writer()
                        payload['writers']['operations'][0]['observation']['exit_confirmed'] = False
                    else:
                        payload['tamper_source_context'] = True
                    result, run, _, process = self.invoke_fixture(consumer, payload,
                        source_references=[reference], native_input_paths=[str(model)])
                    self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                    context = result['source_execution_context']
                    try:
                        self.assertFalse(result['writers_confirmed'] or result['lease_released'])
                        self.assertTrue(all(Path(row['execution_alias']).is_dir() for row in context['sources']))
                        self.assertTrue(load_capacity_protection_leases(source_root)['protected_paths'])
                        self.assertEqual(before, {path: path.read_bytes() for path in before})
                    finally:
                        self._remove_test_source_aliases(root, context)

    def test_source_context_cannot_clean_another_child_alias_of_the_same_parent(self) -> None:
        with tempfile.TemporaryDirectory(prefix='native-source-ownership-') as directory:
            root = Path(directory)
            with unittest.mock.patch.dict(os.environ, {'MASS_SPECTROMETRY_EXECUTION_ROOT': str(root / 'execution')}):
                parent, source_root, model, reference, before = self._native_source_fixture(root, deep=True)
                children = []
                for name in ('first', 'second'):
                    consumer = root / name; consumer.mkdir()
                    result, run, _, process = self.invoke_fixture(consumer,
                        {'source_artifact_root': str(source_root), 'source_run_directory': str(parent)},
                        source_references=[reference], native_input_paths=[str(model)], failure_stage='source_alias_cleanup')
                    self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertTrue(result['writers_confirmed'])
                    children.append((consumer, run, result))
                first, second = children
                alias1 = Path(first[2]['source_execution_context']['sources'][0]['execution_alias'])
                alias2 = Path(second[2]['source_execution_context']['sources'][0]['execution_alias'])
                self.assertNotEqual(alias1, alias2)
                original = {first[0] / 'result.json': (first[0] / 'result.json').read_bytes(),
                            first[1] / 'logs/capacity_session.json': (first[1] / 'logs/capacity_session.json').read_bytes()}
                try:
                    # Even coherent tampering of both transport records cannot
                    # turn the other child's alias into this request's cleanup.
                    for path in original:
                        document = json.loads(path.read_text(encoding='utf-8-sig'))
                        source = document['source_execution_context']['sources'][0]
                        source['execution_alias'] = str(alias2)
                        source['execution_directory'] = str(alias2)
                        path.write_text(json.dumps(document), encoding='utf-8')
                    failed, process = self.resume_fixture(first[0], first[1])
                    self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertTrue(alias1.is_dir() and alias2.is_dir())
                    self.assertIn('frozen owner scope', process.stdout + process.stderr)
                finally:
                    for path, content in original.items():
                        path.write_bytes(content)
                for consumer, run, result in children:
                    final, process = self.resume_fixture(consumer, run)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertTrue(final['source_execution_aliases_removed'])
                    self.assertEqual((consumer / 'callback_count.txt').read_text(), '1')
                self.assertFalse(alias1.exists() or alias2.exists())
                self.assertEqual(before, {path: path.read_bytes() for path in before})


    def test_native_source_partial_alias_preparation_rolls_back_before_callback(self) -> None:
        with tempfile.TemporaryDirectory(prefix='native-source-rollback-') as directory:
            root = Path(directory)
            with unittest.mock.patch.dict(os.environ, {'MASS_SPECTROMETRY_EXECUTION_ROOT': str(root / 'execution')}):
                parents = []
                for name in ('a', 'z'):
                    producer = root / (name + 'x' * 180); producer.mkdir()
                    payload = {'long_native_fixture': True} if name == 'z' else {}
                    _, run, artifacts, process = self.invoke_fixture(producer, payload)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    path = run / 'results' / ('n' * 190) / 'model.json' if name == 'z' else run / 'results/science.json'
                    parents.append((run, artifacts, path, {'manifest_record': file_record(run / 'run_manifest.json'),
                        'protected_paths': [str(run)]}, {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}))
                consumer = root / 'consumer'; consumer.mkdir()
                result, _, artifacts, process = self.invoke_fixture(consumer, {},
                    source_references=[row[3] for row in parents], native_input_paths=[str(row[2]) for row in parents])
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertIn('EXECUTION_PATH_CAPACITY=FAIL', process.stdout + process.stderr)
                self.assertTrue(result['source_execution_aliases_removed'] and result['lease_released'])
                created = result['source_execution_context']['sources']
                self.assertEqual(len(created), 1)  # First link genuinely created before second budget refusal.
                self.assertFalse(Path(created[0]['execution_alias']).exists())
                self.assertFalse((consumer / 'callback_count.txt').exists())
                self.assertFalse(load_capacity_protection_leases(artifacts)['protected_paths'])
                for run, source_root, _, _, before in parents:
                    self.assertFalse(load_capacity_protection_leases(source_root)['protected_paths'])
                    self.assertEqual(before, {path: path.read_bytes() for path in before})


    def test_native_source_default_execution_root_accepts_cross_root_and_resumes_without_new_alias(self) -> None:
        from common.contracts.execution_aliases import execution_alias_root_is_valid
        from common.contracts import legacy_capacity_calibration as calibration
        from common.contracts import reconcile_artifact_capacity as maintenance
        with tempfile.TemporaryDirectory(prefix='native-source-default-') as directory:
            root = Path(directory)
            with unittest.mock.patch.dict(os.environ, {'MASS_SPECTROMETRY_EXECUTION_ROOT': str(root / 'parent_execution')}):
                parent, source_root, model, reference, before = self._native_source_fixture(root, deep=True)
            consumer = root / 'consumer'; consumer.mkdir()
            with unittest.mock.patch.dict(os.environ):
                os.environ.pop('MASS_SPECTROMETRY_EXECUTION_ROOT', None)
                result, run, artifacts, process = self.invoke_fixture(consumer,
                    {'source_artifact_root': str(source_root), 'source_run_directory': str(parent)},
                    source_references=[reference], native_input_paths=[str(model)], failure_stage='source_alias_cleanup')
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                context = result['source_execution_context']
                aliases = artifacts / 'common/execution_aliases'
                self.assertEqual(Path(context['execution_root']).resolve(), aliases.resolve())
                source_alias = Path(context['sources'][0]['execution_alias'])
                self.assertTrue(source_alias.is_dir())
                self.assertTrue(execution_alias_root_is_valid(artifacts, aliases))
                capacity_ledger.record_capacity_object(artifacts, path=aliases, object_class='light_evidence',
                    bytes_count=0, owner='common.run_artifact_support')
                with unittest.mock.patch.object(Path, 'rglob', side_effect=AssertionError('source payload inventoried')):
                    measured, pending = calibration._execution_alias_root(artifacts, aliases, '2026-11-01')
                    self.assertIsNone(pending); self.assertEqual(measured['bytes'], 0)
                    self.assertEqual(maintenance._reconcile_execution_alias_root(artifacts),
                                     {'corrected_count': 0, 'released_bytes': 0})
                recovered, process = self.resume_fixture(consumer, run)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertTrue(recovered['source_execution_aliases_removed'] and recovered['terminal_published'])
                self.assertEqual(recovered['source_execution_context'], context)
                self.assertFalse(source_alias.exists())
                self.assertEqual((consumer / 'callback_count.txt').read_text(), '1')
                self.assertEqual(before, {path: path.read_bytes() for path in before})


    def test_python_native_source_inputs_reject_unbound_relative_and_nonpython_declarations(self) -> None:
        with tempfile.TemporaryDirectory(prefix='native-source-invalid-') as directory:
            root = Path(directory)
            unbound = root / 'unbound.json'; unbound.write_text('{}', encoding='utf-8')
            for name, paths in (('type', {}), ('relative', ['source/model.mph']), ('unbound', [str(unbound)])):
                with self.subTest(scenario=name):
                    fixture = root / name; fixture.mkdir()
                    result, run, artifacts, process = self.invoke_fixture(fixture, {}, native_input_paths=paths)
                    self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertFalse((fixture / 'callback_count.txt').exists())
                    self.assertFalse(load_capacity_protection_leases(artifacts)['protected_paths'])
            request_path = root / 'unbound/request.json'
            request = json.loads(request_path.read_text(encoding='utf-8'))
            request['prepared'] = {'owner_kind': 'powershell', 'entrypoint': request['prepared']['entrypoint'], 'native_input_paths': []}
            request_path.write_text(json.dumps(request), encoding='utf-8')
            process = self.run_ps(root, f""". '{OWNER}'
try{{Invoke-RunArtifactWorkflow -RequestPath '{request_path}' -ResultPath '{root / 'ps_result.json'}'|Out-Null;throw 'PowerShell native input unexpectedly accepted'}}
catch{{if($_.Exception.Message-notmatch'only for Python prepared'){{throw}}}}
""")
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


    def test_python_owner_protects_cross_root_source_before_compute_and_reacquires_on_resume(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-source-reference-") as directory:
            root = Path(directory)
            parent_fixture = root / "parent"
            parent_fixture.mkdir()
            parent, parent_run, source_root, process = self.invoke_fixture(parent_fixture, {})
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            parent_bytes = {path: path.read_bytes() for path in parent_run.rglob("*") if path.is_file()}
            reference = {"manifest_record": file_record(parent_run / "run_manifest.json"),
                         "protected_paths": [str(parent_run)]}
            consumer = root / "consumer"
            consumer.mkdir()
            first, run, artifacts, process = self.invoke_fixture(consumer,
                {"source_artifact_root": str(source_root), "source_run_directory": str(parent_run)},
                source_references=[reference], failure_stage="retention_before")
            self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(first["resume_action"], "resume_finalization")
            self.assertTrue(json.loads((run / "results/science.json").read_text())["source_protected_before_compute"])
            self.assertIn(parent_run.resolve(), load_capacity_protection_leases(source_root)["protected_paths"])
            session = json.loads((run / "logs/capacity_session.json").read_text(encoding="utf-8-sig"))
            leases = [(artifacts, session["lease_id"]),
                      (source_root, session["source_protection_leases"][0]["lease_id"])]
            for artifact, lease_id in leases:
                lease = artifact / "common/capacity_protection_leases" / f"{lease_id}.json"
                value = json.loads(lease.read_text(encoding="utf-8-sig"))
                value["expires_at_utc"] = "2001-01-01T00:00:00Z"
                lease.write_text(json.dumps(value), encoding="utf-8")
            # The original CLI must reacquire the same frozen source references
            # before any recovery publication, without running the callback.
            hooks = f"""$originalPublisher=${{function:Publish-WorkflowTerminal}}
function Publish-WorkflowTerminal {{
 param($Python,$RepoRoot,$CompletionPath,$SessionPath,$WaitPath,$MaximumRunBytes)
 & $Python -B -c 'from pathlib import Path;from common.contracts.capacity_protection import load_capacity_protection_leases;import sys;p=load_capacity_protection_leases(Path(sys.argv[1]));assert Path(sys.argv[2]).resolve() in p["protected_paths"];assert p["committed_new_bytes"]==0' '{source_root}' '{parent_run}'
 if($LASTEXITCODE-ne0){{throw 'Recovery source protection was absent'}}
 & $originalPublisher @PSBoundParameters
}}"""
            recovered, process = self.resume_fixture(consumer, run, additional_hooks=hooks)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(recovered["terminal_published"] and recovered["capacity_finalized"] and recovered["lease_released"])
            self.assertNotEqual(recovered["lease_id"], first["lease_id"])
            self.assertEqual((consumer / "callback_count.txt").read_text(), "1")
            self.assertEqual(parent_bytes, {path: path.read_bytes() for path in parent_bytes})
            self.assertFalse(load_capacity_protection_leases(source_root)["protected_paths"])
            self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])
            closed = {name: (run / name).read_bytes() for name in ("run_manifest.json", "results/execution_completion.json")}
            cli = self.run_ps(consumer, f"& '{OWNER}' -RequestPath '{run / 'inputs/execution_request.json'}' -ResultPath '{consumer / 'result.json'}' -ResumeFinalization")
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertEqual((consumer / "callback_count.txt").read_text(), "1")
            self.assertEqual(closed, {name: (run / name).read_bytes() for name in closed})
            self.assertEqual(parent_bytes, {path: path.read_bytes() for path in parent_bytes})

    def test_python_owner_rolls_back_partial_cross_root_source_acquisition_before_compute(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-partial-source-reference-") as directory:
            root = Path(directory)
            parents = []
            for name in ("a_parent", "z_parent"):
                fixture = root / name
                fixture.mkdir()
                result, run, artifacts, process = self.invoke_fixture(fixture, {})
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                parents.append((run, artifacts, {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}))
            first_run, first_root, _ = parents[0]
            second_run, second_root, _ = parents[1]
            references = [
                {"manifest_record": file_record(first_run / "run_manifest.json"), "protected_paths": [str(first_run)]},
                {"manifest_record": file_record(second_run / "run_manifest.json"),
                 "protected_paths": [str(second_run), str(first_root)]},
            ]
            consumer = root / "consumer"
            consumer.mkdir()
            trace = root / "capacity_successful_commands.jsonl"
            result, run, artifacts, process = self.invoke_fixture(consumer, {}, source_references=references,
                capacity_trace=trace)
            self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertFalse((consumer / "callback_count.txt").exists())
            self.assertFalse(run.exists())
            calls = [json.loads(line) for line in trace.read_text(encoding="utf-8-sig").splitlines()]
            successful = [call for call in calls
                          if Path(call["artifact_root"]).resolve() == first_root.resolve() and call["success"]]
            self.assertEqual([call["operation"] for call in successful],
                             ["create_capacity_protection_lease", "delete_capacity_protection_lease"])
            self.assertEqual(successful[0]["lease_id"], successful[1]["lease_id"])
            self.assertIn("protected path must remain below the artifact root",
                          str(result) + process.stdout + process.stderr)
            for parent_run, source_root, snapshot in parents:
                self.assertFalse(load_capacity_protection_leases(source_root)["protected_paths"])
                self.assertEqual(snapshot, {path: path.read_bytes() for path in snapshot})
            self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])

    def test_python_owner_rejects_malformed_or_missing_source_authority_before_compute(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-bad-source-reference-") as directory:
            root = Path(directory)
            absent = root / "absent/run_manifest.json"
            absent.parent.mkdir()
            cases = {
                "not_array": {},
                "missing_manifest_record": [{}],
                "missing_manifest": [{"manifest_record": {"path": str(absent), "exists": True,
                    "bytes": 0, "sha256": "0" * 64}}],
            }
            for name, references in cases.items():
                with self.subTest(case=name):
                    fixture = root / name
                    fixture.mkdir()
                    result, run, artifacts, process = self.invoke_fixture(fixture, {}, source_references=references)
                    self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertFalse((fixture / "callback_count.txt").exists())
                    self.assertFalse(run.exists())
                    self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])
                    self.assertIn(result["resume_action"], ("correct_request_and_use_new_run",))

    def test_deep_frozen_import_uses_run_execution_cwd_and_durable_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-deep-python-") as directory:
            short = Path(directory)
            root = short
            while len(str(root)) <= 280:
                root = root / "frozen_source_segment"
            root.mkdir(parents=True)
            copy_started = time.perf_counter()
            shutil.copytree(REPO / "common", root / "common", ignore=lambda directory, _names:
                            {"__pycache__"} | ({"assets"} if Path(directory) == REPO / "common/simion" else set()))
            fixture.copy_scientific_core(REPO, root)
            copied_bytes = sum(path.stat().st_size for path in (root / "common").rglob("*") if path.is_file())
            print(json.dumps({"fixture": "deep_frozen_python", "copied_bytes": copied_bytes,
                              "copy_seconds": time.perf_counter() - copy_started}))
            self.assertFalse((root / "common/simion/assets").exists())
            (root / "frozen_dependency.py").write_text("VALUE = 'frozen-only'\n", encoding="utf-8")
            (root / "frozen_resource.txt").write_text("frozen resource", encoding="utf-8")
            original = CALLBACK
            frozen = original.replace("sys.path.insert(0, REPOSITORY)", "from frozen_dependency import VALUE")
            frozen = frozen.replace("    config = json.loads", "    assert VALUE == 'frozen-only'\n    assert Path(__file__).with_name('frozen_resource.txt').read_text() == 'frozen resource'\n    assert Path.cwd() != Path(__file__).parent\n    config = json.loads", 1)
            execution = short / "execution"
            old_execution = os.environ.get("MASS_SPECTROMETRY_EXECUTION_ROOT")
            os.environ["MASS_SPECTROMETRY_EXECUTION_ROOT"] = str(execution)
            try:
                result, run, _, output = self.invoke_fixture(root, {}, callback_text=frozen)
            finally:
                if old_execution is None:
                    os.environ.pop("MASS_SPECTROMETRY_EXECUTION_ROOT", None)
                else:
                    os.environ["MASS_SPECTROMETRY_EXECUTION_ROOT"] = old_execution
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["execution_alias_removed"])
            completion = json.loads((run / "results/execution_completion.json").read_text(encoding="utf-8-sig"))
            self.assertFalse(Path(completion["execution_alias"]["path"]).exists())
            self.assertEqual(Path(completion["run_config"]["path"]), run / "run_config.json")
            stats = completion["summary"]["native_path_preparation"]
            self.assertGreater(stats["calls"], 0)
            self.assertGreaterEqual(stats["elapsed_seconds"], 0)
            self.assertEqual(stats["transport_bytes"], 0)
            self.assertEqual(result["native_path_preparation"], stats)
            self.assertEqual(json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))["native_path_preparation"], stats)
            self.assertTrue((root / "frozen_resource.txt").is_file())
            before = (run / "run_manifest.json").read_bytes()
            resumed, recovery = self.resume_fixture(root, run)
            self.assertEqual(recovery.returncode, 0, recovery.stdout + recovery.stderr + str(resumed))
            self.assertEqual(resumed["status"], "success")
            self.assertEqual((root / "callback_count.txt").read_text(), "1")
            self.assertEqual(resumed["native_path_preparation"], stats)
            self.assertEqual((run / "run_manifest.json").read_bytes(), before)

if __name__ == "__main__":
    unittest.main()
