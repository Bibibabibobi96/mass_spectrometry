"""Explicit unsolved-model GUI leaf using the existing native process owner."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from msplatform.io.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_session import RunSession


def _gui_inputs(session: RunSession, view: Mapping[str, Any], executable: Path) -> list[dict]:
    """Check the prepared profile before the original owner guards exact bytes."""
    root = session.artifact_run_dir.resolve()
    if not executable.is_absolute() or executable.name.lower() != 'simion.exe' or not executable.is_file():
        raise ValueError('SIMION view requires its explicit available executable')
    if view.get('view_profile') != 'raw_geometry_no_program_hook':
        raise ValueError('SIMION view requires the prepared raw-geometry no-hook profile')
    wb, zero = view['workbench_record'], view['zero_control_record']
    workbench = Path(wb['path'])
    if workbench.suffix.lower() != '.iob' or Path(zero['path']) != workbench.with_suffix('.fly2'):
        raise ValueError('view requires its workbench-bound zero-particle companion')
    controls = Path(zero['path'])
    if not controls.is_file() or controls.stat().st_size > 4096:
        raise ValueError('view zero-particle native control is missing or exceeds its bounded profile')
    compact = ''.join(controls.read_text(encoding='utf-8-sig').split())
    if compact not in {'particles{coordinates=0,}', 'particles{coordinates=0}'}:
        raise ValueError('view refuses nonempty particles or executable source controls')
    assets = view['native_asset_records']
    if not isinstance(assets, list) or not assets or any(not row['path'].lower().endswith(('.pa#', '.pa-surf')) for row in assets):
        raise ValueError('view requires all actual unsolved raw geometry and surface records')
    records = list(view['data_records'].values())
    expected = {row['path']: row for row in records}
    if len(expected) != len(records) or any(expected.get(row['path']) != row for row in [wb, zero, *assets]):
        raise ValueError('view native assets differ from their complete prepared data closure')
    for row in records:
        path = Path(row['path'])
        if (not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(root)
                or row.get('exists') is not True or not path.is_file() or type(row.get('bytes')) is not int
                or path.stat().st_size != row['bytes'] or row.get('retention_role') not in {'required_evidence', 'solver_native_binary'}):
            raise ValueError('view input is missing or outside its owned immutable closure')
    for base in [workbench.with_suffix(''), *(Path(row['path']).with_suffix('') for row in assets)]:
        for suffix in ('.wgem', '.gem', '.lua', '.ion', '.con', '.rec', '.fly'):
            if Path(str(base)+suffix).exists():
                raise ValueError('view refuses an automatic build/source/Program companion: '+str(base)+suffix)
    for directory in {executable.parent, session.run_dir, workbench.parent}:
        if (directory/'simion.lua').exists():
            raise ValueError('view refuses an ambient SIMION startup script before native launch')
    return records


def open_prepared_model(session: RunSession, *, view: Mapping[str, Any], executable: Path,
                        limits: Mapping[str, Any]) -> dict:
    """Open the owned IOB and await the same native handle's natural exit.

    Complete immutable records are verified/guarded by process_owner.ps1 under
    the actual SIMION grant. No extra parent PA hash, Popen loop or GUI owner.
    Process completion is not evidence that a human inspected the geometry.
    """
    root = session.artifact_run_dir.resolve()
    paths = {name: root/directory/filename for name, directory, filename in (
        ('request', 'inputs', 'simion_view_request.json'), ('receipt', 'results', 'simion_view_receipt.json'))}
    for path in paths.values():
        if path.exists() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('SIMION view evidence must be new and owned by this run')
        session.declare_file(path, 'required_evidence')
    report = dict(schema_version=1, role='simion_model_view_receipt', status='failed', primary=None,
        request_record=None, native_requested=False, native_operation=None,
        gui_geometry_acceptance='not_inferred_from_process_exit', original_iob_bytes_preserved=False,
        refine_calls_requested=0, fly_calls_requested=0, save_calls_requested=0)
    failure = None
    try:
        records = _gui_inputs(session, view, executable)
        tool = file_record(executable, 'required_evidence')
        verify_record('SIMION viewer executable', tool)
        request = dict(schema_version=1, role='simion_model_view_request', executable_record=tool,
            workbench_record=view['workbench_record'], immutable_records=records,
            model_identity_sha256=view['model_identity_sha256'], lifecycle='application_exit',
            view_profile=view['view_profile'], preparation_operations=view['preparation_operations'],
            source_reference=view['source_reference'], path_policy=view['path_policy'], window_style='Normal')
        # Reuse the current run's existing execution spelling, whose lifetime
        # is owned through native exit. It is not a second short-path scheme.
        gui_path = session.run_dir/Path(view['workbench_record']['path']).relative_to(root)
        if gui_path.resolve() != Path(view['workbench_record']['path']).resolve():
            raise ValueError('GUI execution spelling differs from its owned workbench record')
        request['gui_workbench_path'] = str(gui_path)
        write_json_atomic(paths['request'], request)
        report['request_record'] = file_record(paths['request'], 'required_evidence')
        session.add_input('simion_view_request', report['request_record'])
        report['native_requested'] = True
        # Issue255's supported GUI file-open command. No --nogui/--noprompt,
        # --lua, fly, refine, save or automatic reconstructor is requested.
        session.run_process('view_model', executable=executable,
            arguments=[str(gui_path)], role='SIMION', stage='gui_review', limits=limits, window_style='Normal',
            immutable_input_records=[*records, report['request_record']])
        rows = [row for row in session.operations if row['operation_id'] == 'view_model']
        if (len(rows) != 1 or rows[0]['observation'].get('exit_confirmed') is not True
                or rows[0]['observation'].get('returncode') != 0):
            raise ValueError('view lacks its actual successful original native process observation')
        report['native_operation'] = rows[0]
        report['status'] = 'success'
    except BaseException as error:
        failure = error
        report['primary'] = repr(error)
        rows = [row for row in session.operations if row['operation_id'] == 'view_model']
        report['native_operation'] = rows[0] if len(rows) == 1 else None
    finally:
        try:
            write_json_atomic(paths['receipt'], report)
        except BaseException as secondary:
            if failure is None:
                raise
            failure.add_note('SIMION view receipt secondary: '+repr(secondary))
    if failure is not None:
        raise failure
    return dict(report=report, receipt_path=str(paths['receipt']), request_path=str(paths['request']))
