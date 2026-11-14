"""Static operating-workpoint identity and strict electrode coverage."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion import rf_field_execution as field


class StaticOperatingIdentityTests(unittest.TestCase):
    def setUp(self):
        self.geometry = {'role': 'simion_neutral_world_collision_geometry',
                         'electrode_mapping': [{'native_id': 3}, {'native_id': 1}]}
        self.rows = [{'kind': 'static', 'voltage_v': 5.0,
                      'native_targets': [{'domain': 'world', 'electrode_id': 3}]},
                     {'kind': 'static', 'voltage_v': -2.0,
                      'native_targets': [{'domain': 'world', 'electrode_id': 1}]}]
        self.model = object()

    def vector(self, rows):
        with patch.object(field, 'model_geometry', return_value=SimpleNamespace(frontend_geometry=self.geometry)), \
                patch.object(field, 'require_prepared_model', return_value={'native_drive_rows': rows}):
            return field.static_world_voltage_vector(self.model)

    def test_exact_sorted_and_rejects_missing_duplicate_nonfinite(self):
        self.assertEqual(self.vector(self.rows), [{'electrode_id': 1, 'voltage_v': -2.0},
                                                 {'electrode_id': 3, 'voltage_v': 5.0}])
        for rows in (self.rows[:1], self.rows+[self.rows[0]],
                     [dict(self.rows[0], voltage_v=float('nan')), self.rows[1]],
                     [dict(self.rows[0], voltage_v=True), self.rows[1]],
                     [dict(self.rows[0], native_targets=[{'domain': 'other', 'electrode_id': 3}]), self.rows[1]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.vector(rows)

    def test_voltage_change_changes_operating_identity(self):
        source = SimpleNamespace(model=self.model)
        first_vector = self.vector(self.rows)
        changed = copy.deepcopy(self.rows)
        changed[0]['voltage_v'] = 6
        second_vector = self.vector(changed)
        with patch.object(field, 'rf_spatial_identity', return_value={'identity_sha256': 'operator'}), \
                patch.object(field, 'static_world_voltage_vector') as vector:
            vector.return_value = first_vector
            first = field.static_world_operating_identity(source, numerics={}, tool_identity={}, auditor_identity={})
            vector.return_value = second_vector
            second = field.static_world_operating_identity(source, numerics={}, tool_identity={}, auditor_identity={})
        self.assertNotEqual(first['identity_sha256'], second['identity_sha256'])


class StaticOperatingReuseTests(unittest.TestCase):
    def test_exact_operating_assets_and_changed_workpoint_refuse(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts = root/'receipts.json'
            receipts.write_text(json.dumps([{'operation_id': operation, 'observation': {
                'exit_confirmed': True, 'returncode': 0, 'process_id': 10,
                'process_started_at_utc_ticks': 20}}
                for operation in ('refine_world', 'audit_family', 'export_operating', 'audit_fields')]), encoding='utf-8')
            records = {key: {'path': str(root/name)} for key, name in
                       (('pa', 'world.pa'), ('surface', 'world.pa-surf'), ('witness', 'witness.csv'))}
            identity = dict(schema_version=1, role='simion_static_world_operating_identity',
                            spatial_operator={}, voltages=[] )
            identity['identity_sha256'] = field.canonical_json_sha256(identity)
            cold_audit = root/'audit.json'
            cold_audit.write_text(json.dumps({'role': 'simion_static_operating_field_audit', 'status': 'success', 'checked_domains': ['world']}), encoding='utf-8')
            class Artifact:
                metadata = {'backend': 'simion', 'field_status': 'available',
                            'field_representation': field.STATIC_WORLD_OPERATING_REPRESENTATION,
                            'spatial_identity': identity,
                            'native_assets': {'world': {'operating': 'pa', 'surface': 'surface',
                                                        'surface_witnesses': 'witness'}}}
                reference = {'manifest': {'path': str(root/'manifest.json')}}
                def data_path(self, key):
                    if key == 'field_native_receipts':
                        return receipts
                    if key == 'field_audit':
                        return cold_audit
                    raise AssertionError(key)
            artifact = Artifact()
            geometry = {'role': 'simion_neutral_world_collision_geometry'}
            with patch.object(field, 'open_artifact', return_value=artifact), \
                    patch.object(field, 'data_record', side_effect=lambda _a, key: records[key]):
                _, producer, assets = field.require_static_world_reuse({}, identity=identity, geometry=geometry)
                self.assertIs(producer, artifact)
                self.assertEqual(set(assets['world']), {'carrier_record', 'surface_record', 'witness_record'})
                with self.assertRaisesRegex(ValueError, 'identity'):
                    field.require_static_world_reuse({}, identity=dict(identity, identity_sha256='different'), geometry=geometry)
                cold_audit.write_text(json.dumps({'role': 'simion_static_operating_field_audit',
                                                   'status': 'failed', 'checked_domains': ['world']}), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'cold audit'):
                    field.require_static_world_reuse({}, identity=identity, geometry=geometry)
                cold_audit.write_text(json.dumps({'role': 'simion_static_operating_field_audit',
                                                   'status': 'success', 'checked_domains': ['world']}), encoding='utf-8')
                records['surface']['path'] = str(root/'other.pa-surf')
                with self.assertRaisesRegex(ValueError, 'surface path'):
                    field.require_static_world_reuse({}, identity=identity, geometry=geometry)


class StaticOperatingGraphTests(unittest.TestCase):
    def test_fresh_and_reuse_graphs_are_distinct(self):
        geometry = {'role': 'simion_neutral_world_collision_geometry'}
        with patch.object(field, 'model_geometry', return_value=SimpleNamespace(frontend_geometry=geometry)), \
                patch.object(field, 'require_prepared_model', return_value={'physics': field.RF_PHYSICS}), \
                patch.object(field, 'static_world_voltage_vector', return_value=[{'electrode_id': 1, 'voltage_v': 5}]):
            fresh = field.plan_rf_fields(object(), numerics={'refine_policy': 'vendor_default'})
            reused = field.plan_rf_fields(object(), numerics={'refine_policy': 'vendor_default'},
                                          reuse_fields_reference={'manifest': 'existing'})
        self.assertEqual(fresh['expected_operation_ids'], ['materialize_geometry', 'refine_world', 'audit_family',
                                                          'export_operating', 'audit_fields'])
        self.assertEqual(fresh['operation_dependencies']['export_operating'], ['audit_family'])
        self.assertEqual(fresh['operation_dependencies']['audit_fields'], ['export_operating'])
        self.assertEqual(reused['expected_operation_ids'], ['audit_fields'])

    def test_real_published_artifact_detects_workpoint_and_tampering(self):
        import json
        import tempfile
        from pathlib import Path
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = dict(schema_version=1, role='simion_static_world_operating_identity',
                            spatial_operator={}, voltages=[{'electrode_id': 1, 'voltage_v': 5}])
            identity['identity_sha256'] = field.canonical_json_sha256(identity)
            receipts = [{'operation_id': op, 'observation': {'exit_confirmed': True, 'returncode': 0,
                         'process_id': 10, 'process_started_at_utc_ticks': 20}}
                        for op in ('refine_world', 'audit_family', 'export_operating', 'audit_fields')]
            payloads = {'operating': ('world.pa', b'operating'), 'surface': ('world.pa-surf', b'surface'),
                        'witness': ('witness.csv', b'witness'),
                        'field_native_receipts': ('receipts.json', json.dumps(receipts).encode()),
                        'field_audit': ('audit.json', json.dumps({'role': 'simion_static_operating_field_audit',
                            'status': 'success', 'checked_domains': ['world']}).encode())}
            records = {}
            for key, (name, content) in payloads.items():
                path = root/name
                path.write_bytes(content)
                records[key] = file_record(path, 'required_evidence')
            metadata = {'backend': 'simion', 'field_status': 'available',
                        'field_representation': field.STATIC_WORLD_OPERATING_REPRESENTATION,
                        'spatial_identity': identity,
                        'native_assets': {'world': {'operating': 'operating', 'surface': 'surface',
                                                    'surface_witnesses': 'witness'}}}
            manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-static',
                            project='software_fixture', mode='test', status='success', inputs={},
                            outputs=list(records.values()), products={'fields': dict(schema_version=1,
                                kind='field_bundle', status='complete', metadata=metadata, data=records)})
            publish_terminal_state(root, {'status': 'success'}, manifest)
            reference = {'manifest': file_record(root/'run_manifest.json'), 'product_id': 'fields'}
            geometry = {'role': 'simion_neutral_world_collision_geometry'}
            _, _, assets = field.require_static_world_reuse(reference, identity=identity, geometry=geometry)
            self.assertEqual(assets['world']['carrier_record']['path'], str(root/'world.pa'))
            changed = dict(identity, voltages=[{'electrode_id': 1, 'voltage_v': 6}])
            changed['identity_sha256'] = field.canonical_json_sha256(
                {key: value for key, value in changed.items() if key != 'identity_sha256'})
            with self.assertRaisesRegex(ValueError, 'workpoint'):
                field.require_static_world_reuse(reference, identity=changed, geometry=geometry)
            (root/'world.pa-surf').write_bytes(b'tampered')
            with self.assertRaises(AssertionError):
                field.require_static_world_reuse(reference, identity=identity, geometry=geometry)

    def test_failure_retains_partial_outputs_and_primary_error(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root/'results'
            family = root/'simion/fields/world'
            result.mkdir(parents=True)
            family.mkdir(parents=True)
            (result/'world_operating.pa').write_bytes(b'partial')
            (family/'world.pa0').write_bytes(b'family')
            declared = []
            class Session:
                run_dir = root
                def declare_file(self, path, role):
                    declared.append((path, role))
            primary = RuntimeError('actual child failure')
            with patch.object(field, '_execute_static_world_fields_inner', side_effect=primary):
                with self.assertRaisesRegex(RuntimeError, 'actual child failure') as raised:
                    field._execute_static_world_fields(Session())
            self.assertIs(raised.exception, primary)
            self.assertEqual(set(primary.failure_output_paths), {str(result/'world_operating.pa'), str(family/'world.pa0')})
            self.assertEqual({role for _, role in declared}, {'solver_native_binary'})

    def test_export_guards_frozen_workpoint_not_fresh_mutable_family(self):
        import ast
        import inspect
        source = inspect.getsource(field._execute_static_world_fields_inner)
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        exports = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == 'run'
                   and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == 'export_operating']
        self.assertEqual(len(exports), 1)
        self.assertEqual(ast.unparse(exports[0].args[3]), "[records['static_workpoint'], records['exporter']]")
        protection = [call for call in calls if isinstance(call.func, ast.Name)
                      and call.func.id == '_protected_source']
        self.assertTrue(protection)
        self.assertIn("source.artifact.reference['manifest']", ast.unparse(protection[0]))
        audits = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == 'run'
                  and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == 'audit_family']
        self.assertEqual(len(audits), 1)
        self.assertIn('family', ast.unparse(audits[0].args[3]))


class StaticOperatingGuardRegressionTests(unittest.TestCase):
    def test_every_child_guards_its_frozen_inputs(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(field._execute_static_world_fields_inner))
        calls = {node.args[0].value: node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == 'run' and node.args
                 and isinstance(node.args[0], ast.Constant)}
        expected = {
            'refine_world': "[records['refiner'], records['world_refine_spec']]",
            'audit_family': "family + [records['world_surface_witnesses'], records['family_auditor'], records['family_audit_spec']]",
            'export_operating': "[records['static_workpoint'], records['exporter']]",
            'audit_fields': "[*asset.values(), records['operating_auditor'], records['operating_audit_spec']]",
        }
        self.assertEqual(set(calls), set(expected))
        for operation, guards in expected.items():
            with self.subTest(operation=operation):
                self.assertEqual(ast.unparse(calls[operation].args[3]), guards)
        self.assertNotIn('family', ast.unparse(calls['export_operating'].args[3]))

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows identity guard required')
    def test_original_witness_mutation_before_copy_is_refused(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from msplatform.io.manifest_records import file_record
        from msplatform.backends.simion import field_execution

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            witness = root / 'witness.csv'
            witness.write_bytes(b'original')
            original = file_record(witness, 'required_evidence')
            sample = root / 'small.txt'
            sample.write_bytes(b'fixture')
            asset = {'raw_record': file_record(sample), 'surface_records': [file_record(sample)],
                     'witness_record': original}
            source = SimpleNamespace(model=object(), native_assets={'world': asset},
                artifact=SimpleNamespace(reference={'manifest': file_record(sample)}),
                clock_authority_reference={'contract': file_record(sample), 'authority': file_record(sample)})
            class Session:
                run_dir = root / 'run'
                input_dir = run_dir / 'inputs'
                log_dir = run_dir / 'logs'
                context = SimpleNamespace(tools={'simion': sample})
                expected_operation_ids = ('materialize_geometry', 'refine_world', 'audit_family',
                                          'export_operating', 'audit_fields')
                operation_dependencies = {'refine_world': ['materialize_geometry'],
                    'audit_family': ['refine_world'], 'export_operating': ['audit_family'],
                    'audit_fields': ['export_operating']}
                def declare_file(self, path, role):
                    return Path(path)
                def canonical_path(self, path):
                    return Path(path)
                def add_input(self, name, record):
                    pass
                def run_process(self, *args, **kwargs):
                    raise AssertionError('native child must not start')
            graph = {'expected_operation_ids': list(Session.expected_operation_ids),
                     'operation_dependencies': Session.operation_dependencies}
            def mutate_before_witness_copy(*args, **kwargs):
                witness.write_bytes(b'mutated!')  # same length; exercises the recorded SHA
            with patch.object(field, '_require_materializer'), \
                 patch.object(field, 'plan_rf_fields', return_value=graph), \
                 patch.object(field, '_protected_source'), \
                 patch.object(field, 'require_prepared_model', return_value={}), \
                 patch.object(field, 'model_geometry', return_value=SimpleNamespace(frontend_geometry={})), \
                 patch.object(field, 'static_world_voltage_vector', return_value=[]), \
                 patch.object(field, 'native_resource_path', return_value=sample), \
                 patch.object(field, '_clock_reference', return_value='epoch.json'), \
                 patch.object(field, 'static_world_operating_identity', return_value={}), \
                 patch.object(field_execution, '_copy_records', side_effect=mutate_before_witness_copy):
                with self.assertRaisesRegex(ValueError, 'guarded file SHA-256 does not match the file record'):
                    field._execute_static_world_fields_inner(Session(), source=source, numerics={},
                        limits={'reserved_run_payload_bytes': 1}, materialize_geometry=object(),
                        materializer_record={}, allow_asynchronous_io=False, reuse_fields_reference=None)
            self.assertFalse((Session.run_dir / 'results/world_surface.csv').exists())
