"""Installed STEP viewer worker; the existing process owner admits this tree.

The original native child handle remains live through document cleanup and
actual exit. This worker is not another scheduler or persistent GUI session.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from msplatform.applications import solidworks
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic


def _paths(path: Path, request: dict) -> tuple[Path, Path]:
    root = Path(request['run_directory'])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('STEP viewer requires its existing absolute run directory')
    root = root.resolve()
    if path.resolve() != root/'inputs/model_view_request.json':
        raise ValueError('STEP viewer request is outside its owned inputs')
    for key, name in (('ready_path', 'model_view_ready.json'), ('receipt_path', 'model_view_receipt.json')):
        value = Path(request[key])
        if not value.is_absolute() or value.resolve() != root/'results'/name or value.is_symlink() or value.exists():
            raise ValueError('STEP viewer output differs from its new owned destination: '+key)
    controlled = Path(request['controlled_step']['path'])
    if not controlled.is_absolute() or controlled.resolve() != root/'inputs/view/assembly.step' or controlled.is_symlink():
        raise ValueError('STEP viewer controlled input is outside its owned copy')
    for key, filename in (('template_record', 'part_template.prtdot'),
                          ('assembly_template_record', 'assembly_template.asmdot')):
        target = Path(request[key]['path'])
        if not target.is_absolute() or target.resolve() != root/'inputs/view'/filename or target.is_symlink():
            raise ValueError('STEP viewer template is outside its controlled copy: '+key)
    return Path(request['ready_path']), Path(request['receipt_path'])


def _connect_child(process: subprocess.Popen, client: Any, pc: Any, com_class: str) -> None:
    while process.poll() is None:
        try:
            app = client.GetActiveObject(com_class)
        except pc.com_error:
            time.sleep(1)
            continue
        if int(solidworks._value(app, 'GetProcessID')) != process.pid:
            raise ValueError('COM application is not the explicitly launched native child')
        return
    raise ValueError('owned SolidWorks process exited before exposing its COM object')


def view_step(path: str | Path) -> dict:
    """Wait for the imported document to close, then for actual native exit.

    No save/convert calls or ACK controller. Failures still emit their bound
    receipt after the child exits; invalid external output paths never write.
    """
    path = Path(path).resolve()
    request = json.loads(path.read_text(encoding='utf-8-sig'))
    fields = {'schema_version', 'role', 'run_directory', 'source_step', 'controlled_step',
              'executable_record', 'template_record', 'assembly_template_record', 'source_template_records',
              'com_class', 'lifecycle', 'ready_path', 'receipt_path'}
    if (not isinstance(request, dict) or not fields <= set(request) or set(request)-fields-{'geometry_inspection'}
            or type(request['schema_version']) is not int
            or request['schema_version'] != 2 or request['role'] != 'solidworks_model_view_request'):
        raise ValueError('unsupported STEP viewer request')
    ready, receipt_path = _paths(path, request)
    report = dict(schema_version=2, role='solidworks_model_view_receipt', request_record=file_record(path, 'required_evidence'),
        status='failed', primary=None, secondary_errors=[], application=None, ready=False,
        native_child_started=False, native_pid=None, native_exit_confirmed=False, native_returncode=None,
        source_guards_released=False, document_close_observed=False, no_save_requested=True,
        refine_calls_requested=0, fly_calls_requested=0, save_calls_requested=0)
    failure = None
    process = None
    stack = ExitStack()
    pc = None
    com_initialized = False
    try:
        if request['com_class'] != 'SldWorks.Application.30' or request['lifecycle'] != 'document_close':
            raise ValueError('viewer requires explicit2022 document_close lifecycle')
        if not isinstance(request['source_template_records'], dict) or set(request['source_template_records']) != {'part', 'assembly'}:
            raise ValueError('viewer requires both explicit template source records')
        for name in ('source_step', 'controlled_step', 'executable_record', 'template_record', 'assembly_template_record'):
            record = request[name]
            if name in {'executable_record', 'template_record', 'assembly_template_record'} and record.get('retention_role') != 'required_evidence':
                raise ValueError('application tool/template require explicit evidence role')
            verify_record('STEP viewer '+name, record)
        for kind, key in (('part', 'template_record'), ('assembly', 'assembly_template_record')):
            source = request['source_template_records'][kind]
            controlled = request[key]
            if (source.get('retention_role') != 'required_evidence' or not Path(source['path']).is_absolute()
                    or Path(source['path']).resolve() == Path(controlled['path']).resolve()
                    or (source.get('bytes'), source.get('sha256')) != (controlled['bytes'], controlled['sha256'])):
                raise ValueError('viewer template copy differs from its explicit source: '+kind)
            verify_record('STEP viewer source '+kind+' template', source)
        inspection = request.get('geometry_inspection')
        export_report = None
        if 'geometry_inspection' in request:
            if not isinstance(inspection, dict) or set(inspection) != {'checks', 'report_record'}:
                raise ValueError('unsupported geometry inspection request')
            record = inspection['report_record']
            target = Path(record['path'])
            root = Path(request['run_directory']).resolve()
            if (not target.is_absolute() or target.is_symlink()
                    or target.resolve() != root/'inputs/view/cad_export_report.json'
                    or record.get('retention_role') != 'required_evidence'):
                raise ValueError('inspection report outside its owned frozen input')
            verify_record('geometry inspection report', record)
            export_report = json.loads(target.read_text(encoding='utf-8-sig'))
            solidworks.validate_geometry_checks(inspection['checks'], export_report)
            if (export_report['step_record']['bytes'] != request['controlled_step']['bytes']
                    or export_report['step_record']['sha256'].lower() != request['controlled_step']['sha256'].lower()):
                raise ValueError('inspection report STEP identity differs')
        exe = Path(request['executable_record']['path'])
        if exe.name.lower() != 'sldworks.exe' or not exe.is_absolute():
            raise ValueError('viewer requires the explicitly configured SolidWorks executable')
        if Path(request['source_step']['path']).resolve() == Path(request['controlled_step']['path']).resolve():
            raise ValueError('viewer requires an independent controlled STEP copy')
        guarded = [request[name] for name in ('source_step', 'controlled_step', 'template_record', 'assembly_template_record')]
        guarded.extend(request['source_template_records'].values())
        if inspection is not None:
            guarded.append(inspection['report_record'])
        for record in guarded:
            stack.enter_context(guarded_file_identity(record['path'], expected_bytes=record['bytes'],
                                                      expected_sha256=record['sha256']))
        pc, client = solidworks._com_modules()
        pc.CoInitialize()
        com_initialized = True
        try:
            client.GetActiveObject(request['com_class'])
        except pc.com_error:
            pass
        else:
            raise ValueError('cold owned viewer refuses an already active SolidWorks application')
        process = subprocess.Popen([str(exe)], cwd=exe.parent)
        report.update(native_child_started=True, native_pid=process.pid)
        print('SOLIDWORKS_NATIVE_CHILD_STARTED='+str(process.pid), flush=True)
        _connect_child(process, client, pc, request['com_class'])
        def observe_original_exit(*, wait=False):
            if wait:
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print('SOLIDWORKS_CLOSING_WAIT=original_handle_live_after5s; continuing original wait with guards',
                          file=sys.stderr, flush=True)
                    code = process.wait()
            else:
                code = process.poll()
            return dict(pid=process.pid, returncode=code)

        with solidworks.open_step_session(request['controlled_step']['path'], executable=exe,
                com_class=request['com_class'], part_template=request['template_record']['path'],
                assembly_template=request['assembly_template_record']['path'],
                session_mode='owned_child', owned_process_id=process.pid, visible=True,
                owned_process_exit_observer=observe_original_exit, display_owned_document=True) as session:
            report['application'] = session.receipt
            inspected = (session.inspect(checks=inspection['checks'], export_report=export_report)
                         if inspection is not None else session.inspect())
            report['ready'] = True
            write_json_atomic(ready, dict(schema_version=2, role='solidworks_model_view_ready',
                request_record=report['request_record'], native_pid=process.pid, application=inspected,
                lifecycle='document_close', no_save_requested=True))
            print('SOLIDWORKS_VIEW_READY='+str(process.pid), flush=True)
            while process.poll() is None:
                if not session.document_is_open():
                    report['document_close_observed'] = True
                    break
                time.sleep(1)
            if process.poll() is not None:
                report['document_close_observed'] = not session.document_is_open()
    except BaseException as error:
        failure = error
        report['primary'] = repr(error)
        report['application'] = getattr(error, 'solidworks_receipt', report['application'])
    finally:
        # Do not unwind guards while any healthy original child may still live.
        if process is not None:
            while not report['native_exit_confirmed']:
                try:
                    code = process.wait()
                    report.update(native_exit_confirmed=True, native_returncode=code)
                except BaseException as error:
                    if failure is None:
                        failure = error
                        report['primary'] = repr(error)
                    elif len(report['secondary_errors']) < 16:
                        report['secondary_errors'].append('original child wait: '+repr(error))
                    print('SOLIDWORKS_NATIVE_EXIT_UNCONFIRMED='+repr(error), file=sys.stderr, flush=True)
                    time.sleep(1)
            if report['native_returncode'] != 0 and failure is None:
                failure = RuntimeError('SolidWorks child returned '+str(report['native_returncode']))
                report['primary'] = repr(failure)
        for label, cleanup in [('COM uninitialize', pc.CoUninitialize if com_initialized else None),
                               ('source guard release', stack.close)]:
            if cleanup is None:
                continue
            try:
                cleanup()
                if label == 'source guard release':
                    report['source_guards_released'] = True
            except BaseException as error:
                report['secondary_errors'].append(label+': '+repr(error))
                if failure is None:
                    failure = error
                    report['primary'] = repr(error)
                else:
                    failure.add_note(label+': '+repr(error))
        report['status'] = 'success' if failure is None else 'failed'
        try:
            write_json_atomic(receipt_path, report)
        except BaseException as error:
            if failure is None:
                raise
            failure.add_note('viewer receipt secondary: '+repr(error))
    if failure is not None:
        raise failure
    print('SOLIDWORKS_MODEL_VIEW=PASS', flush=True)
    return report


if __name__ == '__main__':
    view_step(sys.argv[1])
