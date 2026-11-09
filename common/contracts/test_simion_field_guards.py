"""Published source/engineering/lease guards for fields, without any native process."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.test_simion_model_execution import model_plan
from msplatform.backends.simion.field_execution import execute_fields
from msplatform.backends.simion.field_closure import load_field_model
from msplatform.backends.simion.model import compile_prepared_model, model_geometry
from msplatform.execution import owner
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.capacity_protection import load_capacity_protection_leases
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.io.manifest_records import file_record
from msplatform.execution.resources import resource_path
from msplatform.execution.terminal_publication import publish_terminal_state


def _never_materialize(*args, **kwargs):
    raise AssertionError('preflight must not materialize or launch a process')


def published_model(root, mutation):
    model, assets, seed, _plan = model_plan(root)
    if mutation == 'clock_identity':
        document = model.document
        drive = copy.deepcopy(document['drive'])
        drive['clock']['clock_epoch_id'] += '_other'
        model = compile_prepared_model(model_geometry(model), document['components_resolved'],
            drive=drive, physics=document['physics'])
    producer = root/'producer'
    producer.mkdir()
    records, names = {}, {}
    target = producer/'compiled_model.json'
    target.write_text(json.dumps(model.document), encoding='utf-8')
    records['compiled_model'] = file_record(target, 'required_evidence')
    for domain, value in assets.items():
        keys = {}
        for label, record in [('raw_geometry', value['raw_record']),
                              *[('fractional_surface', row) for row in value['surface_records']]]:
            target = producer/Path(record['path']).name
            freeze_file(Path(record['path']), target)
            key = domain+'_'+label
            records[key] = file_record(target, 'solver_native_binary')
            keys[label] = key
        names[domain] = keys
    for key, source, target in (
            ('clock_authority', root/'clock-source/clock_authority.json', producer/'clock_authority.json'),
            ('instrument_epoch', root/'clock-source/inputs/instrument_epoch.json', producer/'inputs/instrument_epoch.json'),
            ('structural_seed', Path(seed['path']), producer/'seed.iob')):
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source, target)
        records[key] = file_record(target, 'required_evidence')
    if mutation == 'missing': names.pop('parent')
    elif mutation == 'alias': names['parent']['raw_geometry'] = names['reflectron']['raw_geometry']
    elif mutation == 'unknown': names['parent']['raw_geometry'] = 'not_a_bound_data_record'
    metadata = dict(backend='simion', drive_configured=True, geometry_materialized=True,
        field_status='not_solved', source_status='not_requested', native_assets=names,
        fixture='INERT_SOFTWARE_NOT_NATIVE_QUALIFICATION')
    manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-field-model', project='software_fixture',
        mode='inert_model_data', status='success', inputs={}, outputs=list(records.values()),
        products={'model':dict(schema_version=1, kind='prepared_model', status='complete', metadata=metadata, data=records)})
    publish_terminal_state(producer, {'status':'success'}, manifest)
    reference = dict(manifest=file_record(producer/'run_manifest.json', 'required_evidence'), product_id='model')
    if mutation == 'tamper': Path(records['parent_raw_geometry']['path']).write_bytes(b'TAMPERED')
    return reference, model


class FieldSourceGuardTests(unittest.TestCase):
    def test_complete_published_model_rejects_missing_alias_unknown_clock_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen', side_effect=AssertionError('no native or helper process')):
            for mutation in ('valid','missing','alias','unknown','clock_identity','tamper'):
                root = Path(directory)/mutation
                root.mkdir()
                reference, model = published_model(root, mutation)
                with self.subTest(mutation=mutation):
                    if mutation == 'valid':
                        self.assertEqual(load_field_model(reference).model.document, model.document)
                    else:
                        with self.assertRaises((ValueError, KeyError, AssertionError)):
                            load_field_model(reference)

    def test_reserve_and_io_preflight_refuse_before_artifact_or_process_and_zero_is_legal(self):
        arguments = dict(model_reference={}, numerics={}, materialize_geometry=_never_materialize,
                         materializer_record=file_record(Path(__file__), 'required_evidence'))
        with patch('subprocess.Popen', side_effect=AssertionError('must not start any process')):
            for reserve in (None, True, -1, 1.5, '0'):
                with self.subTest(reserve=reserve), self.assertRaisesRegex(ValueError, 'reserved_run_payload_bytes'):
                    execute_fields(object(), limits={'reserved_run_payload_bytes':reserve}, **arguments)
            with self.assertRaisesRegex(TypeError, 'asynchronous'):
                execute_fields(object(), limits={'reserved_run_payload_bytes':0}, allow_asynchronous_io='false', **arguments)
            with self.assertRaisesRegex(ValueError, 'artifact reference'):
                execute_fields(object(), limits={'reserved_run_payload_bytes':0}, **arguments)


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class FieldLeaseGuardTests(unittest.TestCase):
    def test_dynamic_cache_keys_accumulate_in_original_lease_without_clearing_accounting_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={}, host_state_path=root/'private.sqlite3',
                policy_path=resource_path('host_resource_policy.json'))
            budget = root/'budget.json'
            budget.write_text('{"bytes":1048576}', encoding='utf-8')
            lease_ids = []
            def action(session):
                lease_ids.append(session.capacity_session['lease_id'])
                session.renew_capacity(protected_cache_keys=['A'*64])
                session.defer_capacity_finalization('INJECTED_ACCOUNTING_HOLD')
                session.renew_capacity(protected_cache_keys=['B'*64])
                lease_ids.append(session.capacity_session['lease_id'])
                self.assertEqual(session.capacity_session['defer_capacity_finalization'], 'INJECTED_ACCOUNTING_HOLD')
                return dict(status='success', summary={}, output_paths=[], required_output_paths=[],
                    retention_preserve_paths=[], manifest_extra_fields={})
            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            private = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            with patch.dict(os.environ, private), patch(
                    'msplatform.execution.capacity_admission._capacity_policy', return_value=policy):
                with self.assertRaisesRegex(owner.CapacityAccountingDeferredError, 'INJECTED_ACCOUNTING_HOLD'):
                    owner.run_managed_stage(context, descriptor=dict(project='instrument_assembly',mode='inert_keys',software=[]),
                        run_id='20261104_120000__test__python__dynamic-field-keys', payload={}, committed_new_bytes=1048576,
                        commitment_inputs=[file_record(budget, 'required_evidence')],
                        retention=dict(policy_version=1, **{'class':'compact'}, reason=None),
                        expected_operation_ids=[], operation_dependencies={}, action=action,
                        action_record=file_record(Path(__file__), 'required_evidence'))
            self.assertEqual(lease_ids[0], lease_ids[1])
            protection = load_capacity_protection_leases(context.workspace/'artifacts')
            lease = next(row for row in protection['audit'] if row['lease_id'] == lease_ids[0])
            self.assertEqual(set(lease['protected_cache_keys']), {'a'*64,'b'*64})
            self.assertEqual(protection['committed_new_bytes'], 1048576)
