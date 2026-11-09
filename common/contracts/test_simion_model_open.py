"""Actual owner/inert-process model viewing; no SIMION or GUI is started."""
from __future__ import annotations

from functools import partial
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.test_simion_model_execution import model_plan, _InertModelSession, _inert_small_materialization
from msplatform.applications.simion import _gui_inputs
from msplatform.applications.simion_model_execution import execute_simion_open_model
from msplatform.backends.simion.field_closure import load_field_model, data_record
from msplatform.backends.simion.model_view_preparation import prepare_view
from msplatform.backends.simion.native_plans import plan_solve_fields
from msplatform.execution import owner
from msplatform.results.artifacts import open_artifact
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import file_record
from msplatform.execution.payload_inputs import materialize_payloads
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.execution.terminal_publication import publish_terminal_state


def model_product(root, model, assets, clock_root):
    """Long-term software fixture: real model contract, clearly INERT native data."""
    root.mkdir(parents=True, exist_ok=True)
    records = {}
    def write(key, target, data, role='required_evidence'):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records[key] = file_record(target, role)
    write('compiled_model', root/'inputs/compiled_model.json', json.dumps(model.document).encode())
    write('clock_authority', root/'inputs/clock/clock_authority.json', (clock_root/'clock_authority.json').read_bytes())
    write('instrument_epoch', root/'inputs/clock/inputs/instrument_epoch.json', (clock_root/'inputs/instrument_epoch.json').read_bytes())
    names = {}
    for domain, row in assets.items():
        names[domain] = {}
        for label, record in [('raw_geometry', row['raw_record']),
                *(('fractional_surface', record) for record in row['surface_records'])]:
            key = domain+'_'+label
            write(key, root/'simion'/Path(record['path']).name, Path(record['path']).read_bytes(), 'solver_native_binary')
            names[domain][label] = key
    return dict(schema_version=1, kind='prepared_model', status='complete',
        metadata=dict(backend='simion', drive_configured=True, geometry_materialized=True,
            field_status='not_solved', source_status='not_requested', native_assets=names), data=records)


class SimionModelOpenTests(unittest.TestCase):
    def test_explicit_gui_leaf_requests_normal_window_without_changing_arguments(self):
        from msplatform.applications.simion import open_prepared_model
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool = root/'simion.exe'
            tool.write_bytes(b'INERT_TOOL_NOT_EXECUTED')
            wb = root/'geometry.iob'
            wb.write_bytes(b'INERT_IOB')
            calls = []
            session = SimpleNamespace(artifact_run_dir=root, run_dir=root, operations=[],
                declare_file=lambda path, role: path, add_input=lambda *args: None)
            def run(operation_id, **options):
                calls.append(options)
                session.operations.append(dict(operation_id=operation_id,
                    observation=dict(exit_confirmed=True, returncode=0)))
            session.run_process = run
            view = dict(workbench_record=file_record(wb, 'solver_native_binary'),
                model_identity_sha256='a'*64, preparation_operations=[], source_reference={},
                path_policy={}, view_profile='raw_geometry_no_program_hook')
            with patch('msplatform.applications.simion._gui_inputs', return_value=[]):
                open_prepared_model(session, view=view, executable=tool, limits={})
            self.assertEqual(calls[0].get('window_style'), 'Normal')
            self.assertEqual(calls[0]['arguments'], [str(wb)])
            self.assertEqual(calls[0]['role'], 'SIMION')
            self.assertEqual(calls[0]['stage'], 'gui_review')

    def test_resolved_model_is_preserved_through_field_plan_and_new_view_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, assets, seed, _ = model_plan(root/'author')
            original = root/'original'
            product = model_product(original, model, assets, root/'author/clock-source')
            publish_terminal_state(original, {'status':'success'}, dict(schema_version=2, role='simulation_run_manifest',
                status='success', inputs={}, outputs=list(product['data'].values()), products={'model':product}))
            reference = dict(manifest=file_record(original/'run_manifest.json', 'required_evidence'), product_id='model')
            moved = root/'moved'
            shutil.move(str(original), moved)
            def resolver(record, _base):
                return moved/Path(record['path']).relative_to(original)
            opened = open_artifact(reference, expected_kind='prepared_model', resolver=resolver)
            self.assertFalse(original.exists())
            selected = load_field_model(opened)
            self.assertIs(selected.artifact, opened)
            for key in opened.data_records:
                self.assertTrue(Path(data_record(opened, key)['path']).is_relative_to(moved))
            # Field planning remains the unique scientific projection. Use the
            # existing fixture's actual numerical input, not a display voltage.
            from common.contracts.test_simion_prepared_model import model_inputs
            _, numerics, _, _ = model_inputs(root/'numerical')
            field_numerics = dict(frontend_domains=numerics['frontend_domains'], rf_reference_voltage_v=10000.)
            for value in field_numerics['frontend_domains'].values():
                value['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.001, pulse_delta=.001)
            self.assertEqual(plan_solve_fields(selected.model, numerics=field_numerics)['field_design']['schema_version'], 3)
            session = _InertModelSession(root/'view', moved)
            session.expected_operation_ids += ('view_model',)
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',
                       return_value=dict(run_directory=str(moved))):
                view = prepare_view(session, model_reference=opened, seed_record=seed, limits={},
                    materialize_geometry=_inert_small_materialization, materializer_record=file_record(Path(__file__).with_name('test_simion_model_execution.py'), 'required_evidence'))
            self.assertEqual([row['operation_id'] for row in view['preparation_operations']],
                ['materialize_geometry', 'build_model', 'verify_model'])
            self.assertEqual(view['model_identity_sha256'], model.document['model_identity_sha256'])
            self.assertFalse(view['original_iob_bytes_preserved'])
            self.assertTrue(all(Path(row['path']).is_relative_to(session.run_dir) for row in view['native_asset_records']))
            Path(opened.data_locations['compiled_model']).write_bytes(b'TAMPER')
            with self.assertRaises(AssertionError):
                load_field_model(opened)

    def test_gui_preflight_rejects_source_compute_hooks_and_missing_assets_without_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root/'run'
            run.mkdir()
            exe = root/'simion.exe'
            exe.write_bytes(b'INERT_TOOL_NOT_LAUNCHED')
            wb, raw, control = run/'geometry.iob', run/'parent.pa#', run/'geometry.fly2'
            for path, data in ((wb,b'INERT_IOB'), (raw,b'INERT_RAW'), (control,b'particles { coordinates=0 }')):
                path.write_bytes(data)
            records = {name:file_record(path, 'solver_native_binary' if name != 'control' else 'required_evidence')
                       for name,path in (('workbench', wb), ('raw', raw), ('control', control))}
            session = SimpleNamespace(artifact_run_dir=run, run_dir=run)
            view = dict(view_profile='raw_geometry_no_program_hook', workbench_record=records['workbench'],
                zero_control_record=records['control'], native_asset_records=[records['raw']], data_records=records)
            self.assertEqual(_gui_inputs(session, view, exe), list(records.values()))
            for kind in ('wgem', 'hook', 'startup', 'beam', 'missing'):
                with self.subTest(kind=kind), patch('subprocess.Popen', side_effect=AssertionError('GUI launched')):
                    bad = wb.with_suffix('.wgem' if kind == 'wgem' else '.lua') if kind in {'wgem','hook'} else root/'simion.lua'
                    if kind in {'wgem','hook','startup'}:
                        bad.write_bytes(b'FORBIDDEN')
                    elif kind == 'beam':
                        control.write_bytes(b'particles { standard_beam { mass=1 } }')
                    else:
                        raw.unlink()
                    with self.assertRaises(ValueError):
                        _gui_inputs(session, view, exe)
                    if kind in {'wgem','hook','startup'}:
                        bad.unlink()
                    elif kind == 'beam':
                        control.write_bytes(b'particles { coordinates=0 }')

    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows managed immutable inputs required')
    def test_actual_sole_owner_four_operations_and_before_gui_hook_failure_without_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, assets, seed, _ = model_plan(root/'author')
            tool = root/'simion.exe'
            tool.write_bytes(b'INERT_ARGV_TOOL_RECORD_NOT_EXECUTED')
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':tool},
                host_state_path=root/'private-host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            budget = root/'budget.json'
            budget.write_text('{"bytes":104857600}', encoding='utf-8')
            base = dict(descriptor=dict(project='instrument_assembly', mode='inert_simion_view', software=[]),
                payload={'scope':'INERT_PROTOCOL_ONLY'}, committed_new_bytes=104857600,
                commitment_inputs=[file_record(budget, 'required_evidence')],
                retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert model view software'),
                completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _:set()))
            def publish(session):
                product = model_product(session.run_dir, model, assets, root/'author/clock-source')
                for record in product['data'].values():
                    session.declare_file(record['path'], record['retention_role'])
                paths = [record['path'] for record in product['data'].values()]
                return dict(status='success', summary={'inert':True}, output_paths=paths, required_output_paths=paths,
                    retention_preserve_paths=[], manifest_extra_fields={'products':{'model':product}})
            limits = dict(wall_clock_seconds=60, transient_run_directory_bytes=104857600,
                process_tree_working_set_bytes=1073741824, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=104857600, automatic_retry_count=0)
            callback = partial(materialize_payloads, limits=limits)
            preparer = partial(prepare_view, seed_record=seed, limits=limits, materialize_geometry=callback,
                materializer_record=file_record(Path(inspect.getsourcefile(materialize_payloads)), 'required_evidence'))
            environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            original_process = RunSession.run_process
            proof = []
            phase = 'success'
            def inert_process(session, operation_id, **options):
                if operation_id in {'build_model','verify_model','view_model'}:
                    wb = session.run_dir/'simion/geometry/geometry.iob'
                    if operation_id == 'build_model':
                        code = 'from pathlib import Path;p=Path('+repr(str(wb))+');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT_NOT_IOB");p.with_suffix(".fly2").write_text("particles { coordinates=0 }");print("SINGLE_REFLECTION_MODEL_BUILD=PASS")'
                    elif operation_id == 'verify_model':
                        readback = session.result_dir/'model_drive_readback.txt'
                        code = 'from pathlib import Path;Path('+repr(str(readback))+').write_text("INERT_DRIVER_READBACK_NOT_NATIVE");print("SINGLE_REFLECTION_MODEL_READBACK=PASS")'
                        if phase == 'hook_failure':
                            session.declare_file(wb.with_suffix('.lua'), 'required_evidence')
                            code += ';Path('+repr(str(wb.with_suffix('.lua')))+').write_text("FORBIDDEN_INIT")'
                    else:
                        self.assertEqual(options['arguments'], [str(wb)])
                        self.assertEqual(options['window_style'], 'Normal')
                        self.assertTrue(options['immutable_input_records'])
                        code = 'from pathlib import Path;p=Path('+repr(str(wb))+');blocked=False\ntry:\n p.open("ab").close()\nexcept OSError:\n blocked=True\nassert blocked,"owned IOB is not guarded"\nprint("INERT_GUI_GUARD=PASS")'
                    # Real GATE transport of finite inert Python work, not a
                    # Python process falsely qualified as a vendor SIMION run.
                    options.update(executable=Path(sys.executable), arguments=['-I','-c',code], role='GATE', stage='inert_view_software')
                return original_process(session, operation_id, **options)
            with patch.dict(os.environ, environment), patch.object(owner, '_capacity_policy', return_value=policy), \
                    patch('msplatform.execution.capacity_admission._capacity_policy', return_value=policy), \
                    patch.object(RunSession, 'run_process', inert_process):
                producer = owner.run_managed_stage(context, run_id='20261104_000010__test__cad__inert-model-source',
                    expected_operation_ids=(), operation_dependencies={}, action=publish,
                    action_record=file_record(Path(__file__), 'required_evidence'), **base)
                reference = dict(manifest=producer['manifest'], product_id='model')
                source = open_artifact(reference, expected_kind='prepared_model')
                for index, phase in enumerate(('success','hook_failure'), 11):
                    action = partial(execute_simion_open_model, model_reference=source, prepare_view=preparer,
                        preparer_record=file_record(Path(inspect.getsourcefile(prepare_view)), 'required_evidence'), limits=limits)
                    run_id=f'20261104_0000{index}__test__cad__inert-model-view'
                    arguments = dict(context=context, run_id=run_id,
                        expected_operation_ids=('materialize_geometry','build_model','verify_model','view_model'),
                        operation_dependencies={'build_model':('materialize_geometry',),'verify_model':('build_model',),'view_model':('verify_model',)},
                        action=action, action_record=file_record(Path(inspect.getsourcefile(execute_simion_open_model)), 'required_evidence'),
                        source_references=[{'manifest_record':producer['manifest']}], **base)
                    if phase == 'success':
                        result = owner.run_managed_stage(**arguments)
                        self.assertEqual((result['status'],result['stage'],result['writers_confirmed']), ('success','complete',True))
                    else:
                        with self.assertRaisesRegex(ValueError, 'automatic build/source/Program'):
                            owner.run_managed_stage(**arguments)
                    run = context.workspace/'artifacts/projects/instrument_assembly/runs'/run_id
                    receipt = json.loads((run/'results/simion_view_receipt.json').read_text(encoding='utf-8'))
                    completion = json.loads((run/'results/execution_completion.json').read_text(encoding='utf-8'))
                    operations = completion['writer_completion']['operations']
                    self.assertEqual(len(operations), 4 if phase == 'success' else 3)
                    self.assertEqual(len(completion['writer_completion']['resource_releases']), len(operations))
                    self.assertEqual(receipt['native_requested'], phase == 'success')
                    self.assertEqual(receipt['status'], phase if phase == 'success' else 'failed')
                    self.assertEqual(receipt['refine_calls_requested'], 0)
                    self.assertEqual(receipt['fly_calls_requested'], 0)
                    self.assertEqual(source.data_path('compiled_model').read_text(encoding='utf-8'), json.dumps(model.document))
                    proof.append(dict(phase=phase, receipt=receipt, writer_completion=completion['writer_completion']))
            print('INERT_SIMION_VIEW_OWNER_PROOF='+json.dumps(proof, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    unittest.main()
