"""Public native preparation contracts; no solver execution is claimed here."""
from contextlib import redirect_stdout, ExitStack, contextmanager
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from msplatform.cli import main
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import preflight_native
from msplatform.workflows.native_tracing import _native_reference
from msplatform.workflows.tracing import run_recipe
from msplatform.storage import ArtifactStore

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "src/msplatform/examples"


class NativeWorkflowTests(unittest.TestCase):
    def test_scoped_mr_assembly_preserves_parent_boundary(self):
        from msplatform.recipes.native import _assembly as recipe_assembly
        from msplatform.workflows.native_tracing import _assembly as workflow_assembly
        source = json.loads((ROOT / 'tests/contracts/test_support/ip_mr_current_requests.json').read_text(encoding='utf8'))
        study = {'component_requests': source['component_requests'], 'recipe': source['recipe'],
                 'local_scope': {'instance_ids': ['mrtof'], 'research_scope': 'local original-birth study',
                                 'boundary_assumptions': 'explicit independent source and sampled field'}}
        frozen = recipe_assembly(study)
        actual = workflow_assembly({'study': {'document': study}})
        self.assertEqual(frozen['composition_plan'], actual.composition_plan)
        self.assertEqual(actual.composition_plan['scope']['instance_ids'], ['mrtof'])
        self.assertEqual(actual.composition_plan['scope']['boundary_connection_ids'], ['ip_to_mr'])
        self.assertEqual(actual.composition_plan['local_scope'], study['local_scope'])
        document = dict(study, schema_version=2)
        recipe = {'schema_version': 2, 'field_source': {'kind': 'simion_native'},
                  'particle_tracer': 'simion', 'field_assembly_strategy': 'sampled_joint_field',
                  'study': {'document': document}, 'gas_environment': {'status': 'vacuum'},
                  'recording': {'plane_observations': []}, 'resource_snapshots': {}}
        with patch('msplatform.workflows.native_tracing.validate_recipe', return_value=recipe):
            with self.assertRaisesRegex(ValueError, 'sampled SIMION field'):
                preflight_native(recipe)

    def test_native_reservation_counts_only_new_owned_work_growth(self):
        from msplatform.workflows.native_tracing import _growth_accountant
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "store")
            work = store.new_work()
            (work / "existing").write_bytes(b"old")
            free = [20]
            with patch("msplatform.storage.store.shutil.disk_usage") as disk:
                disk.side_effect = lambda _path: SimpleNamespace(free=free[0])
                with store.reserve(10) as first:
                    account = _growth_accountant(store, first, 10, work)
                    (work / "new").write_bytes(b"123456")
                    free[0] = 14
                    account(work)
                    with store._db() as db:
                        self.assertEqual(db.execute("SELECT remaining FROM reservations WHERE id=?", (first,)).fetchone()[0], 4)
                    account(work)  # Reusing the same bytes does not spend twice.
                    with store.reserve(5):
                        pass
                    with store._db() as db:
                        self.assertEqual(db.execute("SELECT remaining FROM reservations WHERE id=?", (first,)).fetchone()[0], 4)
                    (work / "new").write_bytes(b"1")
                    account(work)
                    (work / "new").write_bytes(b"123456")
                    account(work)
                    with store._db() as db:
                        self.assertEqual(db.execute("SELECT remaining FROM reservations WHERE id=?", (first,)).fetchone()[0], 4)
                with self.assertRaisesRegex(RuntimeError, "failure"):
                    with store.reserve(1):
                        raise RuntimeError("failure")
                with store._db() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM reservations").fetchone()[0], 0)

    def test_large_executable_identity_has_an_explicit_evidence_role(self):
        from msplatform.workflows.native_tracing import _executable_records
        from msplatform.io.file_identity import file_sha256
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inert.exe"
            path.write_bytes(b"inert implementation bytes" * 400000)
            self.assertGreater(path.stat().st_size, 8 * 1024 * 1024)
            self.assertEqual(_executable_records({"simion": path}), {
                "simion": {"bytes": path.stat().st_size, "sha256": file_sha256(path)}})

    def test_reference_cache_second_call_verifies_kind_and_avoids_producer(self):
        artifact = SimpleNamespace(kind="geometry_artifact", reference={"manifest": {"path": "inert"}, "product_id": "geometry"})
        opened = []

        @contextmanager
        def guard(reference, *, expected_kind, expected_artifact_root, artifact_store):
            opened.append(expected_kind)
            self.assertEqual(expected_kind, "geometry_artifact")
            self.assertIs(artifact_store, store)
            yield artifact

        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "store")
            calls = []
            with patch("msplatform.execution.native_source_guard.guard_native_source", guard):
                for expected_reuse in (False, True):
                    with ExitStack() as stack:
                        result, receipt = _native_reference(store, stack, "inert-test-key", lambda: artifact,
                            kind="geometry_artifact", raw_root=Path(directory), claims=[], calls=calls, account=lambda _work: None)
                        self.assertIs(result, artifact)
                        self.assertEqual(receipt["reused"], expected_reuse)
            self.assertEqual(len(calls), 1)
            self.assertEqual(opened, ["geometry_artifact", "geometry_artifact"])

    def test_missing_prepared_model_dependency_recomputes_only_its_stage(self):
        missing = {"old-model": False}
        geometry = SimpleNamespace(kind="geometry_artifact", reference={"manifest": {"path": "geometry"}, "product_id": "geometry"})
        old = SimpleNamespace(kind="prepared_model", reference={"manifest": {"path": "old-model"}, "product_id": "model"})
        new = SimpleNamespace(kind="prepared_model", reference={"manifest": {"path": "new-model"}, "product_id": "model"})
        artifacts = {"geometry": geometry, "old-model": old, "new-model": new}
        @contextmanager
        def guard(reference, **kwargs):
            name = reference["manifest"]["path"]
            if missing.get(name, False):
                raise ValueError("prepared geometry dependency missing")
            yield artifacts[name]
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "store")
            calls = []
            with patch("msplatform.execution.native_source_guard.guard_native_source", guard):
                with ExitStack() as stack:
                    for key, kind, result in (("g", "geometry_artifact", geometry), ("m", "prepared_model", old)):
                        _native_reference(store, stack, key, lambda value=result: value, kind=kind,
                            raw_root=Path(directory), claims=[], calls=calls, account=lambda _: None)
                missing["old-model"] = True
                with ExitStack() as stack:
                    _, geometry_receipt = _native_reference(store, stack, "g", lambda: self.fail("geometry reused"),
                        kind="geometry_artifact", raw_root=Path(directory), claims=[], calls=calls, account=lambda _: None)
                    result, model_receipt = _native_reference(store, stack, "m", lambda: new,
                        kind="prepared_model", raw_root=Path(directory), claims=[], calls=calls, account=lambda _: None)
                self.assertTrue(geometry_receipt["reused"])
                self.assertFalse(model_receipt["reused"])
                self.assertIs(result, new)
                self.assertEqual(calls, ["g", "m", "m"])

    def test_discovery_author_compiles_pilot_without_selecting_a_time(self):
        import re
        from msplatform.workflows.native_tracing import compile_simion_model
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = 'oa_split_tof_native_small_v1'
            study = json.loads((EXAMPLES / (name + '.json')).read_bytes())
            study['drive']['pulse'] = {'mode': 'discover', 'width_us': 7.0, 'candidate_times_us': [10.0, 20.0]}
            data = json.dumps(study).encode()
            (root / (name + '.json')).write_bytes(data)
            author = (EXAMPLES / (name + '.toml')).read_text(encoding='utf8')
            author = re.sub(r'(?m)^sha256 = "[a-fA-F0-9]{64}"', 'sha256 = "' + hashlib.sha256(data).hexdigest() + '"', author, count=1)
            path = root / (name + '.toml'); path.write_text(author, encoding='utf8')
            recipe = load_recipe(path).to_dict()
            model = compile_simion_model(recipe)
            self.assertEqual(recipe['study']['document']['drive']['pulse']['mode'], 'discover')
            self.assertEqual(model.document['drive']['pulse'], {'mode': 'timed', 'time_us': 10.0, 'width_us': 7.0})
            self.assertTrue(preflight_native(recipe)['implemented'])
            study['drive']['pulse']['candidate_times_us'] = [20.0, 10.0]
            data = json.dumps(study).encode(); (root / (name + '.json')).write_bytes(data)
            path.write_text(re.sub(r'(?m)^sha256 = "[a-fA-F0-9]{64}"', 'sha256 = "' + hashlib.sha256(data).hexdigest() + '"', author, count=1), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'candidate times'):
                load_recipe(path)

    def test_author_field_intervention_reaches_public_planner(self):
        from msplatform.workflows.native_tracing import _assembly, _flight_request, _realizations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "oa_split_tof_native_small_v1"
            (root / (name + ".json")).write_bytes((EXAMPLES / (name + ".json")).read_bytes())
            text = (EXAMPLES / (name + ".toml")).read_text(encoding="utf8")
            text = text.replace("[gas_environment]", "field_intervention = {id = \"drift\", selector = \"ideal:drift.ez\"}\n\n[gas_environment]")
            author = root / (name + ".toml")
            author.write_text(text, encoding="utf8")
            recipe = load_recipe(author).to_dict()
            self.assertTrue(preflight_native(recipe)["implemented"])
            particles = _realizations(recipe["study"]["document"]["release"])[0]
            _, observations = _flight_request(recipe, _assembly(recipe), particles)
            self.assertEqual(observations["field_intervention"], {"id": "drift", "selector": "ideal:drift.ez"})
            author.write_text(text.replace("drift.ez", "drift.ex"), encoding="utf8")
            with self.assertRaisesRegex(ValueError, "Ez only"):
                load_recipe(author)
            import tomllib
            from msplatform.recipes.native import _options
            scalar = tomllib.loads(text)
            scalar['field_source']['kind'] = 'comsol_native'
            scalar['field_assembly_strategy'] = 'sampled_joint_field'
            _options(scalar)  # Actual scalar source admission is checked by its preflight.

    def test_mass_scan_author_and_native_only_controls_reach_real_planner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "oa_split_tof_native_small_v1"
            source = (EXAMPLES / (name + ".toml")).read_text(encoding="utf-8")
            study = json.loads((EXAMPLES / (name + ".json")).read_bytes())
            first = copy.deepcopy(study["release"])
            first.pop("particle_ids")
            second = copy.deepcopy(first)
            second["species_id"] = "same_mass_charge_2"
            second["release_spec"]["particle_count"] = 1
            second["release_spec"]["species"]["charge_state"] = 2
            study["release"] = {"schema_version": 1, "role": "canonical_mass_scan_request", "species_requests": [first, second]}
            def write():
                data = json.dumps(study).encode()
                (root / (name + ".json")).write_bytes(data)
                import re
                author = root / (name + ".toml")
                author.write_text(re.sub(r'sha256 = "[a-fA-F0-9]{64}"', 'sha256 = "' + hashlib.sha256(data).hexdigest() + '"', source), encoding="utf-8")
                return author
            self.assertTrue(preflight_native(load_recipe(write()).to_dict())["implemented"])
            study["numerics"]["tracing"]["simion"]["rf_steps_per_period"] = 32
            with self.assertRaisesRegex(ValueError, "tracking numerics"):
                preflight_native(load_recipe(write()).to_dict())

    def test_public_validate_compiles_both_real_split_examples_without_native_claim(self):
        for name in ("oa_split_tof", "rf_split_oatof"):
            output = io.StringIO()
            with self.subTest(name=name), redirect_stdout(output):
                self.assertEqual(main(["validate", str(EXAMPLES / (name + "_native_small_v1.toml"))]), 0)
            result = json.loads(output.getvalue())
            self.assertTrue(result["capabilities"]["implemented"])
            self.assertIsNone(result["capabilities"]["host_available"])
            self.assertFalse(result["capabilities"]["native_verified"])
            self.assertIn("single_reflection_tof", result["resolved"]["assembly"]["name"])

    def test_native_dispatch_reads_author_once_and_passes_same_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension in ("json", "toml"):
                name = "oa_split_tof_native_small_v1." + extension
                (root / name).write_bytes((EXAMPLES / name).read_bytes())
            author = root / "oa_split_tof_native_small_v1.toml"
            old = author.read_bytes()
            original_read = Path.read_bytes
            reads = []

            def mutate_after_read(path):
                data = original_read(path)
                if path == author:
                    reads.append(data)
                    author.write_bytes(data.replace(b"technical small N", b"later source version"))
                return data

            def execute(loaded, **kwargs):
                self.assertEqual(loaded.source_bytes, old)
                self.assertEqual(loaded.to_dict()["label"], "OA TOF split technical small N")
                return {"run_id": "inert_dispatch_test"}

            with patch.object(Path, "read_bytes", mutate_after_read), patch(
                    "msplatform.workflows.native_tracing.run_loaded_recipe", side_effect=execute):
                self.assertEqual(run_recipe(author, artifact_root=root / "store")["run_id"], "inert_dispatch_test")
            self.assertEqual(reads, [old])
            self.assertNotEqual(load_recipe(author).source_bytes, old)

    def test_unsupported_backend_combination_and_missing_context_fail_before_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "oa_split_tof_native_small_v1"
            (root / (name + ".json")).write_bytes((EXAMPLES / (name + ".json")).read_bytes())
            author = root / (name + ".toml")
            source = (EXAMPLES / (name + ".toml")).read_text(encoding="utf-8")
            author.write_text(source.replace("simion_native", "comsol_native"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not yet implemented"):
                preflight_native(load_recipe(author).to_dict())
            author.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ExecutionContext"):
                run_recipe(author, artifact_root=root / "store")
            self.assertFalse((root / "store").exists())


if __name__ == "__main__":
    unittest.main()
