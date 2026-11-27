"""Small real-file tests for the existing native owner consumption guard."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.native_source_guard import guard_native_source
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
class NativeSourceGuardTests(unittest.TestCase):
    def test_historical_comsol_model_guards_linked_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            root, geometry_data, geometry_ref = self.fixture(Path(directory))
            run = root / 'projects/fixture/runs/20261127_010104__test__python__legacy-model'
            run.mkdir(parents=True)
            config = run / 'run_config.json'
            config.write_text(json.dumps({'schema_version': 1, 'run_id': run.name, 'project': 'fixture',
                'mode': 'software', 'inputs': {'geometry': geometry_ref['manifest']['path']},
                'capacity_ledger_lifecycle': {'schema_version': 1, 'enabled': True,
                    'artifact_root': str(root), 'light_evidence_budget_bytes': 1024}}), encoding='utf-8')
            model = run / 'model.mph'
            model.write_bytes(b'legacy synthetic model')
            product = {'schema_version': 1, 'kind': 'prepared_model', 'status': 'complete',
                'metadata': {'backend': 'comsol', 'scope': 'assembly_electrostatic_unsolved'},
                'data': {'geometry_manifest': geometry_ref['manifest'], 'model': file_record(model)}}
            document = build_run_manifest(config, 'success', output_paths=[model],
                                          extra_fields={'products': {'model': product}})
            manifest = run / 'run_manifest.json'
            manifest.write_text(json.dumps(document), encoding='utf-8')
            reference = {'manifest': file_record(manifest), 'product_id': 'model'}
            with guard_native_source(reference, expected_kind='prepared_model', expected_artifact_root=root):
                with self.assertRaises(PermissionError):
                    geometry_data.unlink()
            geometry_data.unlink()
            with self.assertRaises((OSError, ValueError)):
                with guard_native_source(reference, expected_kind='prepared_model', expected_artifact_root=root):
                    self.fail('missing legacy geometry was accepted')

    def test_standalone_store_run_keeps_required_source_asset(self):
        from msplatform.execution.owner import standalone_native_store
        from msplatform.storage.store import ArtifactStore
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / 'store')
            work = store.new_work()
            (work / 'geometry.dat').write_bytes(b'geometry')
            source = store.put_asset('native_stage', 'source', work)
            with store.claim_token(source):
                with standalone_native_store(store, task_key='derived', budget=100000,
                                             required_assets=(source,)) as scope:
                    parent_work = store.root / store.run_status(scope['parent_run_id'])['work_path']
                    (parent_work / 'result.json').write_text('{}', encoding='utf-8')
                    asset, path, _, seal = scope['lifetime'].enter_context(store.inplace_asset('native_stage', 'derived'))
                    (path / 'model.dat').write_bytes(b'model')
                    scope['produced'].append(asset)
                    scope['account'](path)
                    seal()
                parent_id = scope['parent_run_id']
            self.assertEqual(store.run_status(parent_id)['execution_status'], 'succeeded')
            store.collect(100000)
            with store.claim_verified(source) as source_path:
                self.assertEqual((source_path / 'geometry.dat').read_bytes(), b'geometry')

    def test_store_model_recursively_holds_its_geometry_and_rejects_missing_source(self):
        from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
        from msplatform.storage.store import ArtifactStore
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            legacy_root, geometry_data, geometry_ref = self.fixture(base)
            store = ArtifactStore(base / 'model-store')
            with store.inplace_asset('native_stage', 'model-fixture') as (model_id, asset, _claim, seal):
                run = asset / 'runs' / '20261127_010102__test__python__model'
                run.mkdir(parents=True)
                (run / TERMINAL_LOCK_NAME).touch()
                copied = run / 'geometry_manifest.json'
                copied.write_bytes(Path(geometry_ref['manifest']['path']).read_bytes())
                model = run / 'model.mph'
                model.write_bytes(b'synthetic model')
                config = run / 'run_config.json'
                config.write_text(json.dumps({'schema_version': 1, 'run_id': run.name, 'project': 'fixture',
                    'mode': 'software', 'inputs': {}, 'capacity_ledger_lifecycle': {'schema_version': 1,
                    'enabled': False, 'artifact_root': str(store.root), 'light_evidence_budget_bytes': 1024}}), encoding='utf-8')
                product = {'schema_version': 1, 'kind': 'prepared_model', 'status': 'complete',
                    'metadata': {'geometry_source_reference': geometry_ref},
                    'data': {'geometry_manifest': file_record(copied), 'model': file_record(model)}}
                document = build_run_manifest(config, 'success', output_paths=[copied, model],
                                              extra_fields={'products': {'model': product}})
                manifest = run / 'run_manifest.json'
                manifest.write_text(json.dumps(document), encoding='utf-8')
                reference = {'manifest': file_record(manifest), 'product_id': 'model'}
                seal()
            with store.inplace_asset('native_stage', 'field-fixture') as (field_id, asset, _claim, seal):
                field_run = asset / 'runs' / '20261127_010103__test__python__field'
                field_run.mkdir(parents=True)
                (field_run / TERMINAL_LOCK_NAME).touch()
                model_copy = field_run / 'prepared.json'
                model_copy.write_bytes(manifest.read_bytes())
                payload = field_run / 'field.mph'
                payload.write_bytes(b'synthetic field')
                config = field_run / 'run_config.json'
                config.write_text(json.dumps({'schema_version': 1, 'run_id': field_run.name, 'project': 'fixture',
                    'mode': 'software', 'inputs': {}, 'capacity_ledger_lifecycle': {'schema_version': 1,
                    'enabled': False, 'artifact_root': str(store.root), 'light_evidence_budget_bytes': 1024}}), encoding='utf-8')
                product = {'schema_version': 1, 'kind': 'field_solution', 'status': 'complete',
                    'metadata': {'backend': 'comsol', 'scope': 'single_stationary_workpoint',
                                 'stationary_source': {'reference': reference, 'kind': 'prepared_model'}},
                    'data': {'prepared_manifest': file_record(model_copy), 'model': file_record(payload)}}
                document = build_run_manifest(config, 'success', output_paths=[model_copy, payload],
                                              extra_fields={'products': {'solution': product}})
                field_manifest = field_run / 'run_manifest.json'
                field_manifest.write_text(json.dumps(document), encoding='utf-8')
                field_reference = {'manifest': file_record(field_manifest), 'product_id': 'solution'}
                seal()
            collected = set()
            with guard_native_source(field_reference, expected_kind='field_solution',
                                     expected_artifact_root=legacy_root, artifact_store=store, asset_ids=collected):
                self.assertEqual(collected, {model_id, field_id})
                with self.assertRaises(PermissionError):
                    geometry_data.unlink()
                store.collect(10**6)
                self.assertTrue(manifest.exists())
            geometry_data.unlink()
            rejected = {'unrelated'}
            with self.assertRaises((OSError, ValueError)):
                with guard_native_source(field_reference, expected_kind='field_solution',
                                         expected_artifact_root=legacy_root, artifact_store=store, asset_ids=rejected):
                    self.fail('missing geometry was accepted')
            self.assertEqual(rejected, {'unrelated'})

    def fixture(self, base):
        root = base / "owner"
        run = root / "projects" / "fixture" / "runs" / "20261127_010101__test__python__source"
        run.mkdir(parents=True)
        config = run / "run_config.json"
        config.write_text(json.dumps({"schema_version": 1, "run_id": run.name, "project": "fixture", "mode": "software",
            "inputs": {}, "capacity_ledger_lifecycle": {"schema_version": 1, "enabled": True,
                "artifact_root": str(root), "light_evidence_budget_bytes": 1024}}), encoding="utf-8")
        data = run / "payload.pa0"
        data.write_bytes(b"small native fixture")
        record = file_record(data)
        product = {"schema_version": 1, "kind": "geometry_artifact", "status": "complete",
                   "metadata": {}, "data": {"payload": record}}
        manifest = build_run_manifest(config, "success", output_paths=[data], extra_fields={"products": {"geometry": product}})
        path = run / "run_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return root, data, {"manifest": file_record(path), "product_id": "geometry"}

    def test_real_process_cannot_delete_or_write_guarded_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root, data, reference = self.fixture(Path(directory))
            probe = """import pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    p.unlink()
except OSError:
    print("DELETE_BLOCKED")
else:
    raise SystemExit(3)
try:
    p.open("ab").close()
except OSError:
    print("WRITE_BLOCKED")
else:
    raise SystemExit(4)
"""
            with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root) as artifact:
                self.assertEqual(artifact.data_path("payload"), data)
                with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root) as again:
                    self.assertEqual(again.data_path("payload"), data)
                for path in (data, Path(reference["manifest"]["path"]), data.parent / "run_config.json"):
                    result = subprocess.run([sys.executable, "-c", probe, str(path)], cwd=root,
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("DELETE_BLOCKED", result.stdout)
                    self.assertIn("WRITE_BLOCKED", result.stdout)
                retirement_probe = """import pathlib, sys
from msplatform.execution.recorded_file_removal import remove_recorded_files
p = pathlib.Path(sys.argv[1])
record = {"path": p.name, "bytes": p.stat().st_size}
try:
    list(remove_recorded_files(p.parent, [record], identities_verified=True))
except OSError:
    print("RETIREMENT_BLOCKED")
else:
    raise SystemExit(5)
"""
                result = subprocess.run([sys.executable, "-c", retirement_probe, str(data)],
                                        cwd=root, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RETIREMENT_BLOCKED", result.stdout)
            data.unlink()
            self.assertFalse(data.exists())

    def test_historical_run_holds_only_explicit_inputs_and_outputs(self):
        from msplatform.execution.native_source_guard import guard_historical_run
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "historic-run"
            run.mkdir()
            selected = run / "mode.json"
            selected.write_text('{"species":[1]}', encoding="utf-8")
            output = run / "result.csv"
            output.write_bytes(b"particle,result\n1,ok\n")
            config = run / "run_config.json"
            config.write_text(json.dumps({"run_id": run.name, "project": "fixture", "mode": "analysis",
                                          "inputs": {"mode": str(selected)}}), encoding="utf-8")
            manifest = run / "run_manifest.json"
            manifest.write_text(json.dumps({"schema_version": 2, "role": "simulation_run_manifest", "status": "success",
                "run_id": run.name, "project": "fixture", "mode": "analysis", "run_config": file_record(config),
                "inputs": {"mode": file_record(selected)}, "outputs": [file_record(output)]}), encoding="utf-8")
            source = file_record(manifest)
            before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
            with guard_historical_run(source, expected_project="fixture", expected_mode="analysis") as opened:
                self.assertEqual(opened.input("mode")["path"], str(selected))
                self.assertEqual(opened.output("result.csv")["path"], str(output))
                with self.assertRaises(OSError):
                    output.unlink()
                with self.assertRaises(ValueError):
                    opened.output("missing.csv")
            self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()})
            with self.assertRaisesRegex(ValueError, "identity differs"):
                with guard_historical_run(source, expected_project="fixture", expected_mode="wrong"):
                    pass
            output.write_bytes(b"changed")
            with guard_historical_run(source, expected_project="fixture", expected_mode="analysis") as opened:
                with self.assertRaises((ValueError, OSError)):
                    opened.output("result.csv")

    def test_frozen_formal_v1_bundle_holds_exact_manifest_and_assets(self):
        from msplatform.execution.native_source_guard import guard_formal_v1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            source = root / "formal/simion/model.iob"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"frozen source")
            asset = file_record(source)
            record = {"path": "simion/model.iob", "bytes": asset["bytes"], "sha256": asset["sha256"]}
            manifest = root / "formal/asset_manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "role": "formal_asset_manifest", "project": "fixture",
                "release_id": "frozen", "assets": {"model": record}}), encoding="utf-8")
            original = file_record(manifest)
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with guard_formal_v1(original, project_id="fixture", artifact_project_root=root) as (document, paths):
                self.assertEqual(document["release_id"], "frozen")
                self.assertEqual(paths["model"], source)
                with self.assertRaises(OSError):
                    source.unlink()
                with self.assertRaises(OSError):
                    manifest.write_text("changed", encoding="utf-8")
            self.assertEqual(before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()})
            with self.assertRaisesRegex(ValueError, "identity differs"):
                with guard_formal_v1(original, project_id="wrong", artifact_project_root=root):
                    pass
            source.write_bytes(b"different")
            with self.assertRaises((ValueError, OSError)):
                with guard_formal_v1(original, project_id="fixture", artifact_project_root=root):
                    pass

    def test_history_read_is_readonly_and_fails_closed_if_source_disappears(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        from msplatform.io.file_identity import guarded_file_identity
        with tempfile.TemporaryDirectory() as directory:
            root, data, reference = self.fixture(Path(directory))
            before = {item.relative_to(root).as_posix(): item.read_bytes() for item in root.rglob("*") if item.is_file()}
            with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root):
                pass
            after = {item.relative_to(root).as_posix(): item.read_bytes() for item in root.rglob("*") if item.is_file()}
            self.assertEqual(before, after)
            removed = False
            @contextmanager
            def race(path, **kwargs):
                nonlocal removed
                if Path(path).name == "run_config.json" and not removed:
                    data.unlink()
                    removed = True
                with guarded_file_identity(path, **kwargs) as guard:
                    yield guard
            with patch("msplatform.execution.native_source_guard.guarded_file_identity", race):
                with self.assertRaises((FileNotFoundError, OSError, ValueError)):
                    with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root):
                        pass
            self.assertTrue(removed)

    def test_rejects_wrong_root_wrong_kind_and_damaged_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root, data, reference = self.fixture(Path(directory))
            other = Path(directory) / "other"
            other.mkdir()
            with self.assertRaisesRegex(ValueError, "outside"):
                with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=other):
                    pass
            with self.assertRaises(ValueError):
                with guard_native_source(reference, expected_kind="field_bundle", expected_artifact_root=root):
                    pass
            data.write_bytes(b"different bytes")
            with self.assertRaises((ValueError, AssertionError, OSError)):
                with guard_native_source(reference, expected_kind="geometry_artifact", expected_artifact_root=root):
                    pass
