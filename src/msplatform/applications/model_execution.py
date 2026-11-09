"""Explicit application viewing composed by the existing normal run owner."""
from __future__ import annotations

from functools import partial
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from msplatform.results.artifacts import OpenedArtifact, open_artifact
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
from msplatform.execution.run_session import RunSession


def _protected_source(session: RunSession, source: OpenedArtifact, step: Path) -> None:
    owner = resolve_consumed_run_capacity_owner(source.reference['manifest'], consumer_artifact_root=session.artifact_root)
    capacity = session.capacity_session
    if capacity.get('status') != 'active':
        raise ValueError('viewer requires its active original capacity owner')
    paths = list(capacity['protected_paths'])
    for lease in capacity['source_protection_leases']:
        if lease['status'] == 'active':
            paths.extend(lease['protected_paths'])
    for target in (Path(owner['run_directory']), step):
        if not any(target.resolve().is_relative_to(Path(path).resolve()) for path in paths):
            raise ValueError('viewer source has no active owner protection')


def _inspection_input(source: OpenedArtifact, checks):
    """Read the already published report; caller names cannot replace its facts."""
    from msplatform.applications.solidworks import validate_geometry_checks
    validate_geometry_checks(checks)
    path = source.data_path('report')
    report = json.loads(path.read_text(encoding='utf-8-sig'))
    validate_geometry_checks(checks, report)
    step = source.data_records['step']
    claimed = report.get('step_record', {})
    if (claimed.get('bytes') != step['bytes'] or claimed.get('exists') is not True
            or str(claimed.get('sha256', '')).lower() != step['sha256'].lower()):
        raise ValueError('CAD inspection report belongs to different STEP bytes')
    return report, dict(source.data_records['report'], path=str(path))


def execute_open_model(session: RunSession, *, model_reference: Mapping[str, Any] | OpenedArtifact,
                       application: str, limits: Mapping[str, Any], materialize_payloads: Callable,
                       materializer_record: Mapping[str, Any], application_settings: Mapping[str, Any], checks=None) -> dict:
    """Copy and view one STEP, awaiting natural document/application closure.

    The materializer is the existing admitted byte-copy callback. Readiness is
    evidence only; actual worker/native exit is necessary before publication.
    No SolidWorks save/conversion or implicit backend field action occurs.
    """
    if application != 'solidworks' or session.expected_operation_ids != ('materialize_view', 'view_model'):
        raise ValueError('this viewer action requires the exact SolidWorks two-operation graph')
    settings = dict(application_settings)
    if (set(settings) != {'com_class', 'part_template', 'assembly_template', 'lifecycle'}
            or settings['com_class'] != 'SldWorks.Application.30' or settings['lifecycle'] != 'document_close'):
        raise ValueError('SolidWorks viewer requires explicit2022 document_close settings')
    template = Path(settings['part_template'])
    assembly = Path(settings['assembly_template'])
    exe = session.context.tools.get('solidworks')
    if (not template.is_absolute() or not template.is_file() or template.suffix.lower() != '.prtdot'
            or not assembly.is_absolute() or not assembly.is_file() or assembly.suffix.lower() != '.asmdot' or exe is None
            or not exe.is_absolute() or not exe.is_file() or exe.name.lower() != 'sldworks.exe'):
        raise ValueError('SolidWorks viewer requires its explicit available executable and clean template pair')
    if not callable(materialize_payloads):
        raise ValueError('viewer requires the existing native payload materializer')
    verify_record('viewer materializer', dict(materializer_record))
    function = materialize_payloads.func if isinstance(materialize_payloads, partial) else materialize_payloads
    filename = inspect.getsourcefile(inspect.unwrap(function))
    if filename is None or Path(filename).resolve() != Path(materializer_record['path']).resolve():
        raise ValueError('viewer materializer source identity differs')
    source = model_reference if isinstance(model_reference, OpenedArtifact) else open_artifact(model_reference, expected_kind='cad_geometry')
    if source.kind != 'cad_geometry':
        raise ValueError('SolidWorks viewer requires a published CAD geometry artifact')
    step = source.data_path('step')
    if step.suffix.lower() not in {'.step', '.stp'}:
        raise ValueError('SolidWorks viewer supports the declared STEP member')
    inspection = _inspection_input(source, checks) if checks is not None else None
    _protected_source(session, source, step)
    root = session.artifact_run_dir.resolve()
    source_record = dict(source.data_records['step'], path=str(step))
    template_record = file_record(template, 'required_evidence')
    assembly_record = file_record(assembly, 'required_evidence')
    destinations = [root/'inputs/view/assembly.step', root/'inputs/view/part_template.prtdot',
                    root/'inputs/view/assembly_template.asmdot']
    copies = [dict(source_record=record, destination=str(target))
              for record, target in zip((source_record, template_record, assembly_record), destinations, strict=True)]
    actual = materialize_payloads(copies, session=session, operation_id='materialize_view')
    if not isinstance(actual, list) or len(actual) != 3:
        raise ValueError('viewer materialization omitted its STEP/part/assembly template closure')
    standard = {'path', 'exists', 'bytes', 'sha256', 'retention_role'}
    for record, requested in zip(actual, copies, strict=True):
        expected = dict(requested['source_record'], path=requested['destination'])
        path = Path(record.get('path', ''))
        if (set(record) != standard or record != expected or path.is_symlink()
                or not path.resolve().is_relative_to(root) or not path.is_file()
                or path.stat().st_size != record['bytes']):
            raise ValueError('viewer copied record differs from the admitted source/target')
        session.declare_file(path, record['retention_role'])
    observed = [row for row in session.operations if row['operation_id'] == 'materialize_view']
    if len(observed) != 1 or observed[0]['observation'].get('exit_confirmed') is not True or observed[0]['observation'].get('returncode') != 0:
        raise ValueError('viewer materializer did not complete its actual admitted process')
    paths = dict(request=root/'inputs/model_view_request.json', ready=root/'results/model_view_ready.json',
                 receipt=root/'results/model_view_receipt.json')
    for path in paths.values():
        if path.exists() or path.is_symlink():
            raise FileExistsError('viewer refuses existing request or evidence')
        session.declare_file(path, 'required_evidence')
    from msplatform.applications import solidworks, solidworks_worker
    worker_records = {name: file_record(Path(module.__file__).resolve(), 'required_evidence')
                      for name, module in (('viewer_adapter', solidworks), ('viewer_worker', solidworks_worker))}
    for name, record in worker_records.items():
        session.add_input(name, record)
    request = dict(schema_version=2, role='solidworks_model_view_request', run_directory=str(root),
        source_step=source_record, controlled_step=actual[0], executable_record=file_record(exe, 'required_evidence'),
        template_record=actual[1], assembly_template_record=actual[2],
        source_template_records=dict(part=template_record, assembly=assembly_record),
        com_class=settings['com_class'], lifecycle=settings['lifecycle'],
        ready_path=str(paths['ready']), receipt_path=str(paths['receipt']))
    if inspection is not None:
        from msplatform.execution.inputs import freeze_file
        report, source_report = inspection
        report_path = root/'inputs/view/cad_export_report.json'
        session.declare_file(report_path, 'required_evidence')
        frozen = freeze_file(Path(source_report['path']), report_path)
        report_record = file_record(report_path, 'required_evidence')
        if (frozen['sha256'], frozen['bytes']) != (source_report['sha256'], source_report['bytes']):
            raise ValueError('inspection report changed during freezing')
        session.add_input('model_view_inspection_report', report_record)
        request['geometry_inspection'] = dict(checks=checks, report_record=report_record)
    write_json_atomic(paths['request'], request)
    request_record = file_record(paths['request'], 'required_evidence')
    session.add_input('model_view_request', request_record)
    session.add_input('model_view_source_manifest', source.reference['manifest'])
    session.run_process('view_model', executable=session.context.python_executable,
        arguments=['-I', '-X', 'utf8', '-m', 'msplatform.applications.solidworks_worker', str(paths['request'])],
        role='GATE', stage='solidworks_gui_review', limits=limits)
    value = json.loads(paths['receipt'].read_text(encoding='utf-8-sig'))
    if (value.get('role') != 'solidworks_model_view_receipt' or type(value.get('schema_version')) is not int or value['schema_version'] != 2
            or value.get('request_record') != request_record or value.get('status') != 'success'
            or value.get('primary') is not None or value.get('secondary_errors') != []
            or value.get('native_child_started') is not True or type(value.get('native_pid')) is not int
            or value['native_pid'] <= 0 or value.get('native_exit_confirmed') is not True
            or value.get('native_returncode') != 0 or value.get('source_guards_released') is not True
            or value.get('document_close_observed') is not True or value.get('ready') is not True):
        raise ValueError('viewer completion lacks its request-bound native exit/document evidence')
    app = value.get('application')
    if (not isinstance(app, dict) or app.get('native_pid') != value['native_pid']
            or app.get('owned_documents_closed') is not True or app.get('template_preferences_restored') is not True
            or app.get('cleanup_errors') != [] or app.get('no_save_requested') is not True):
        raise ValueError('viewer application cleanup/restoration is unconfirmed')
    verify_record('viewer request', request_record)
    for name, record in worker_records.items():
        verify_record(name, record)
    summary = dict(application='solidworks', source_reference=source.reference, lifecycle='document_close',
        native_exit_confirmed=True, no_save_requested=True, refine_calls_requested=0, fly_calls_requested=0,
        scientific_qualification='not_granted', gui_geometry_acceptance='not_inferred_from_process_exit')
    outputs = [*map(str, destinations), str(paths['ready']), str(paths['receipt'])]
    return dict(status='success', summary=summary, output_paths=outputs, required_output_paths=outputs,
                retention_preserve_paths=[], manifest_extra_fields={})
