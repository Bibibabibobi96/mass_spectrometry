"""Prepare the supported COMSOL assembly pulse inputs, without starting a solver.

COMSOL 6.4/R2025b references consulted 2026-11-27: Electric Force
https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_acdc.07.22.html
and withsol https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_definitions.21.039.html.
withsol accesses sequences in one model, not two separately saved MPH files.
The current single-workpoint producer therefore cannot yet supply this contract.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.model import Assembly
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.contracts.clock import ClockIdentity
from msplatform.contracts.particle_state import validate_component_particle_state_rows
from msplatform.physics import CONSTANTS
from msplatform.results.artifacts import OpenedArtifact


def _workpoint(artifact: OpenedArtifact) -> dict:
    if not isinstance(artifact, OpenedArtifact) or artifact.kind != 'field_solution':
        raise ValueError('a field_solution artifact is required')
    meta = artifact.metadata
    if (meta.get('backend') != 'comsol' or meta.get('field_status') != 'solved'
            or meta.get('native_reopen_verified') is not True):
        raise ValueError('a verified solved COMSOL field is required')
    # Access only small previously published records here. The model itself is
    # already sealed by the original owner and is not rehashed by this planner.
    records = artifact.data_records
    model = records.get('model')
    if not isinstance(model, dict) or model.get('exists') is not True or not model.get('sha256'):
        raise ValueError('sealed COMSOL model identity is required')
    projection = json.loads(artifact.data_path('projection').read_text(encoding='utf-8-sig'))
    descriptor = json.loads(artifact.data_path('descriptor').read_text(encoding='utf-8-sig'))
    request = json.loads(artifact.data_path('request').read_text(encoding='utf-8-sig'))
    geometry_validation = json.loads(artifact.data_path('geometry_validation').read_text(encoding='utf-8-sig'))
    solution = meta.get('solution')
    if not isinstance(solution, dict) or not isinstance(solution.get('solution_tag'), str):
        raise ValueError('native solution tag readback is required')
    return {'model': model, 'projection': projection, 'descriptor': descriptor, 'request': request,
            'solution_tag': solution['solution_tag'], 'reference': artifact.reference, 'geometry_validation': geometry_validation}


def _rows(request: dict) -> dict[tuple[str, str], float]:
    result = {}
    for row in request['group_voltages']:
        key = (row['instance_id'], row['electrode_group_id'])
        value = row['voltage_v']
        if key in result or type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('voltage groups must be unique and finite')
        result[key] = value
    return result


def _require_tools(context: Any) -> None:
    for name in ('comsol_launcher', 'matlab_root'):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == 'matlab_root' else path.is_file()):
            raise ValueError('explicit available COMSOL execution tool required: ' + name)


def _authored_detector_face(assembly: Assembly, projection: Mapping[str, Any], geometry_validation: Any) -> dict | None:
    """Freeze the detector face from the same validated Assembly as the field geometry.

    This identifies the authored surface; native boundary membership remains
    unqualified until the complete geometry/mesh verification has succeeded.
    """
    from msplatform.components.single_reflection_tof.geometry import resolve_downstream_geometry
    from msplatform.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform
    from msplatform.io.file_identity import canonical_json_sha256

    layout = assembly.composition_plan
    selected = layout['scope']['instance_ids']
    names = [name for name in selected if layout['components'][name]['project_id'] == 'single_reflection_tof']
    if not names:
        return None
    if len(names) != 1:
        raise ValueError('COMSOL detector observation requires exactly one selected TOF component')
    if (not isinstance(geometry_validation, Mapping) or set(geometry_validation) != {'position_mm', 'normal_abs'}
            or geometry_validation['position_mm'] != 1e-6):
        raise ValueError('detector observation requires frozen 1e-6 mm geometry validation')
    name = names[0]
    design = assembly.components_resolved[name]
    face = resolve_downstream_geometry(design['geometry_mm'], design['coordinate_convention'],
                                       design['rings'], design['electrodes_v'])['detector_active_face']
    instances = [row for row in layout['recipe']['instances'] if row['instance_id'] == name]
    members = [row for row in projection['members'] if row['instance_id'] == name and row['member_id'] == 'detector']
    if len(instances) != 1 or len(members) != 1 or members[0]['representation_role'] != 'physical_solid':
        raise ValueError('authored detector requires one projected physical detector member')
    transform = instances[0]['transform']
    if members[0]['transform'] != transform:
        raise ValueError('detector geometry transform differs from the frozen Assembly')
    pose = RigidTransform.from_contract(transform)
    frame = layout['components'][name]['local_frame_id']
    if pose.from_frame_id != frame or pose.to_frame_id != projection['assembly_frame_id']:
        raise ValueError('detector frame does not match the field projection')
    center = pose.transform_position(FramedPosition(frame, tuple(face['center_mm']))).coordinates_mm
    normal = pose.transform_vector(FramedVector(frame, tuple(face['normal']))).components
    return {'surface_id': 'detector_active_face', 'instance_id': name, 'member_id': 'detector',
            'frame_id': pose.to_frame_id, 'center_mm': list(center), 'normal': list(normal),
            'radius_mm': face['radius_mm'], 'geometry_validation': dict(geometry_validation),
            'component_resolved_sha256': canonical_json_sha256(design),
            'component_interface_sha256': canonical_json_sha256(layout['components'][name]),
            'qualification': 'authored_surface_native_boundary_unverified'}


def prepare_assembly_pulse(assembly: Assembly, background: OpenedArtifact, on: OpenedArtifact, *,
                           pulse_groups: list[dict], drive: Mapping[str, Any],
                           source: Mapping[str, Any], numerics: Mapping[str, Any],
                           observation_times_us: list[float]) -> dict:
    """Validate co-resident off/on bases and explicit continuous-flight controls.

    This is a scientific check, not authentication of an OpenedArtifact: its
    public constructor can be called directly. The execution owner must verify
    manifests and hold source claims for the entire native process lifetime.
    Current producer emits separate MPH models, so it fails here until a
    manifest-backed co-resident basis product is actually available.
    """
    if not isinstance(assembly, Assembly):
        raise ValueError('a validated Assembly is required')
    off, active = _workpoint(background), _workpoint(on)
    if (off['model']['sha256'], off['model']['bytes']) != (active['model']['sha256'], active['model']['bytes']):
        raise ValueError('withsol requires off and on sequences in one sealed model; independent MPH unsupported')
    if off['solution_tag'] == active['solution_tag']:
        raise ValueError('off and on must identify distinct stored solution sequences')
    if off['projection'] != active['projection'] or off['descriptor'] != active['descriptor']:
        raise ValueError('field bases have different assembly geometry or frame')
    members = off['descriptor'].get('members')
    projected = off['projection'].get('members')
    if not isinstance(members, list) or not isinstance(projected, list) or len(members) != len(projected):
        raise ValueError('geometry descriptor must cover every assembly member')
    for member, projected_member in zip(members, projected, strict=True):
        if (any(member.get(key) != projected_member.get(key) for key in ('instance_id', 'member_id', 'electrode_group_id', 'representation_role'))
                or not isinstance(member.get('feature_tag'), str)
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', member['feature_tag'])):
            raise ValueError('geometry descriptor member identity differs from the frozen projection')
    snapshot = {'composition_plan': assembly.composition_plan, 'components_resolved': assembly.components_resolved,
                'components_source': assembly.components_source}
    if project_assembly_geometry(snapshot, outer_box_mm=off['projection']['outer_box_mm']) != off['projection']:
        raise ValueError('field basis does not match the selected Assembly')
    if off.get('geometry_validation') != active.get('geometry_validation'):
        raise ValueError('field bases have different geometry validation')
    r0, r1 = off['request'], active['request']
    if any(r0[key] != r1[key] for key in ('relative_permittivity', 'exterior', 'mesh', 'study')):
        raise ValueError('field workpoints differ beyond electrode voltages')
    a, b = _rows(r0), _rows(r1)
    if set(a) != set(b) or not isinstance(pulse_groups, list) or not pulse_groups:
        raise ValueError('explicit pulse electrode groups and complete voltage coverage required')
    keys = [(item['instance_id'], item['electrode_group_id']) for item in pulse_groups]
    if len(set(keys)) != len(keys) or not set(keys) <= a.keys():
        raise ValueError('pulse electrode groups must be unique existing groups')
    if any(a[key] != b[key] for key in a.keys() - set(keys)) or any(a[key] != 0 for key in keys):
        raise ValueError('only pulse groups may change and their OFF voltages must be zero')
    if all(a[key] == b[key] for key in keys):
        raise ValueError('pulse field must have an actual nonzero voltage change')
    if not isinstance(drive, Mapping) or set(drive) != {'on_us', 'off_us'}:
        raise ValueError('pulse requires explicit on_us/off_us')
    if any(type(drive[k]) not in (int, float) or not math.isfinite(drive[k]) for k in drive) or drive['on_us'] >= drive['off_us']:
        raise ValueError('pulse times must be finite and ordered')
    required = {'maximum_step_us', 'relative_tolerance', 'absolute_tolerance'}
    if not isinstance(numerics, Mapping) or set(numerics) != required or any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in numerics.values()):
        raise ValueError('explicit positive step, relative and absolute tolerances required')
    times = observation_times_us
    if (not isinstance(times, list) or len(times) < 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in times)
            or any(a >= b for a, b in zip(times, times[1:]))):
        raise ValueError('observation times must be finite and strictly increasing')
    # A producer must explicitly bind frozen scientific constants and actual
    # original-birth inputs before any native launcher can consume this plan.
    if not isinstance(source, Mapping) or set(source) != {'rows', 'clock', 'constants_version'}:
        raise ValueError('original source rows, clock and selected constants version required')
    if source['constants_version'] != CONSTANTS['version']:
        raise ValueError('only the explicitly selected public reference constants are supported')
    rows = validate_component_particle_state_rows(source['rows']).rows
    if not rows or any(row['state_event'] != 'source_birth' or row['parent_particle_id'] is not None for row in rows):
        raise ValueError('original primary birth rows are required')
    first = rows[0]
    if (not isinstance(source['clock'], Mapping) or set(source['clock']) != {'clock_epoch_id', 'authority_sha256'}
            or any(row['clock_epoch_id'] != source['clock']['clock_epoch_id'] for row in rows)
            or any(row['frame_id'] != off['projection']['assembly_frame_id'] for row in rows)):
        raise ValueError('source clock and assembly frame must be explicit and consistent')
    ClockIdentity(**source['clock'])
    if any((row['instrument_time_us'], row['mass_amu'], row['charge_state'], row['species_id']) !=
           (first['instrument_time_us'], first['mass_amu'], first['charge_state'], first['species_id']) for row in rows):
        raise ValueError('one species and one common birth time are required per native batch')
    if times[0] != first['instrument_time_us'] or times[-1] <= drive['off_us'] or drive['on_us'] < times[0]:
        raise ValueError('observations must start at birth and span the declared pulse')
    source_plan = dict(source, rows=rows, source_time_us=first['instrument_time_us'],
                       mass_kg=float(first['mass_amu']) * CONSTANTS['atomic_mass_constant_kg'],
                       charge_state=first['charge_state'], particle_ids=[row['particle_id'] for row in rows])
    return {'schema_version': 1, 'role': 'comsol_assembly_pulse_plan', 'field_status': 'prepared_not_executed',
            'background': off, 'on': active, 'pulse_groups': pulse_groups, 'drive': dict(drive),
            'source': source_plan, 'numerics': dict(numerics), 'observation_times_us': list(times),
            'detector_active_face': _authored_detector_face(assembly, off['projection'], off.get('geometry_validation')),
            'native': {'background_solution_tag': off['solution_tag'], 'on_solution_tag': active['solution_tag'],
                       'vacuum_selection': 'assembly_reference_vacuum', 'members': members}}


def _native_exact_count(value: Any) -> int:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 2**53 or value != int(value):
        raise ValueError('native mesh count must be an exact positive integer')
    return int(value)


def _basis_mesh_limit(stage: Mapping[str, Any]) -> int:
    runtime = stage.get('runtime')
    if (not isinstance(runtime, dict) or set(runtime) != {'maximum_mesh_elements'}
            or type(runtime['maximum_mesh_elements']) is not int or runtime['maximum_mesh_elements'] <= 0):
        raise ValueError('basis stage requires an explicit positive maximum mesh element count')
    return runtime['maximum_mesh_elements']


def prepare_basis_model(model: Mapping[str, Any] | OpenedArtifact, *, on_request: Mapping[str, Any],
                        context: Any) -> tuple[OpenedArtifact, OpenedArtifact]:
    """Compute and cold-reopen two workpoints in one managed COMSOL model.

    Requires the existing unsolved Assembly model and an explicit stage policy;
    this path is implemented but has not yet been validated in native COMSOL.
    """
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record
    from msplatform.results.artifacts import open_artifact

    source = open_artifact(model, expected_kind='prepared_model')
    from msplatform.backends.comsol.assembly_native_scope import require_supported_artifact
    require_supported_artifact(source)
    if (source.metadata.get('backend') != 'comsol' or source.metadata.get('scope') != 'assembly_electrostatic_unsolved'
            or source.metadata.get('native_reopen_verified') is not True):
        raise ValueError('verified unsolved Assembly electrostatic model required')
    projection = json.loads(source.data_path('projection').read_text(encoding='utf-8-sig'))
    old = json.loads(source.data_path('request').read_text(encoding='utf-8-sig'))
    off, on = validate_request(projection, old), validate_request(projection, on_request)
    if off != old or any(off[key] != on[key] for key in ('relative_permittivity', 'exterior', 'mesh', 'study')):
        raise ValueError('two basis workpoints may differ only in group voltages')
    stage, authority = read_stage_policy(context, 'solve_assembly_pulse_basis', required_roles=('solver_native_binary',))
    _require_tools(context)
    maximum_mesh_elements = _basis_mesh_limit(stage)
    manifest = dict(source.reference['manifest'], path=str(source.manifest_location))
    result = run_managed_stage(context,
        descriptor={'project': 'instrument_assembly', 'mode': 'pulse_basis', 'software': ['COMSOL', 'MATLAB']},
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__sim__comsol__pulse-basis-' + uuid4().hex[:12],
        payload={'action': 'solve_assembly_pulse_basis', 'on_request': on, 'maximum_mesh_elements': maximum_mesh_elements, 'stage_policy': stage},
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], source_references=[{'manifest_record': manifest}],
        expected_operation_ids=('solve_pulse_basis', 'reopen_pulse_basis'),
        operation_dependencies={'reopen_pulse_basis': ['solve_pulse_basis']},
        action=partial(_execute_basis, source=source, off=off, on=on, projection=projection, maximum_mesh_elements=maximum_mesh_elements, limits=stage['limits']),
        action_record=file_record(Path(__file__), 'required_evidence'), use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api)
    return tuple(open_artifact({'manifest': result['manifest'], 'product_id': name}, expected_kind='field_solution')
                 for name in ('background', 'on'))


def _execute_basis(session: Any, *, source: OpenedArtifact, off: dict, on: dict,
                   projection: dict, maximum_mesh_elements: int, limits: dict) -> dict:
    from msplatform.backends.comsol.native_execution import declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.io.manifest_records import file_record, verify_record

    launcher, frozen = freeze_native_sources(session, ('comsolstartup.m', 'solve_assembly_pulse_basis.m',
        'read_assembly_stationary_solution.m', 'verify_assembly_electrostatic_bindings.m',
        'read_comsol_mesh_size_controls.m', 'assembly_mesh_identity.m'))
    manifest = dict(source.reference['manifest'], path=str(source.manifest_location))
    session.add_input('prepared_manifest', manifest)
    model = dict(source.data_records['model'], path=str(source.data_locations['model']))
    session.add_input('prepared_model', model)
    paths, records = {}, {}
    descriptor = json.loads(source.data_path('descriptor').read_text(encoding='utf-8-sig'))
    reopen_geometry = json.loads(source.data_path('reopen_geometry').read_text(encoding='utf-8-sig'))
    geometry_validation = json.loads(source.data_path('geometry_validation').read_text(encoding='utf-8-sig'))
    for name, value in (('projection', projection), ('descriptor', descriptor), ('reopen_geometry', reopen_geometry),
                        ('geometry_validation', geometry_validation), ('off_request', off), ('on_request', on)):
        path = session.declare_file(session.input_dir / (name + '.json'), 'required_evidence')
        write_json_atomic(path, value)
        paths[name] = path
        records[name] = file_record(path, 'required_evidence')
        session.add_input(name, records[name])
    output = session.declare_file(session.run_dir / 'assembly-pulse-basis.mph', 'solver_native_binary')
    mesh_facts = session.declare_file(session.result_dir / 'mesh_facts.json', 'required_evidence')
    host = json.dumps({name: str(getattr(session.context, name)) for name in
                       ('workspace', 'python_executable', 'host_state_path', 'policy_path')})
    reports, saved, first = {}, [], None
    for operation, mode in (('solve_pulse_basis', 'compute'), ('reopen_pulse_basis', 'reopen')):
        report = session.declare_file(session.result_dir / (operation + '.json'), 'required_evidence')
        bootstrap = session.declare_file(session.log_dir / (operation + '.bootstrap.log'), 'required_evidence')
        completion = session.declare_file(session.log_dir / (operation + '.launcher.json'), 'required_evidence')
        task = session.declare_file(session.input_dir / (operation + '.m'), 'required_evidence')
        runtime = session.run_dir / 'comsol_runtime' / operation
        runtime.mkdir(parents=True)
        call = 'solve_assembly_pulse_basis(' + ','.join(map(matlab_text, (paths['projection'], paths['off_request'],
            paths['on_request'], model['path'], output, mode))) + ',' + str(maximum_mesh_elements) + ',' + matlab_text(mesh_facts) + ')'
        task.write_text('addpath(' + matlab_text(launcher.parent.parent / 'matlab') + ');\nresult=' + call +
                        ";\nfid=fopen(" + matlab_text(report) + ",'w','n','UTF-8'); assert(fid>=0); "
                        "c=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n", encoding='utf-8', newline='\n')
        guards = [*frozen, *records.values(), file_record(task, 'required_evidence'), *saved]
        if mode == 'compute':
            guards.append(model)
        args = ['-NoProfile', '-File', str(launcher), '-HostContextJson', host, '-WorkingDirectory', str(session.run_dir),
                '-ComsolLauncherPath', str(session.context.tools['comsol_launcher']), '-MatlabRootPath',
                str(session.context.tools['matlab_root']), '-TaskScript', str(task), '-ReportPath', str(bootstrap),
                '-StartupAttempts', '1', '-RunId', session.run_id, '-RunDir', str(runtime), '-CompletionPath', str(completion)]
        primary = None
        try:
            session.run_process(operation, executable=session.context.powershell_executable, arguments=args,
                                role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
        except BaseException as error:
            primary = error
            if mesh_facts.is_file():
                error.failure_output_paths = [*getattr(error, 'failure_output_paths', ()), mesh_facts]
            raise
        finally:
            try:
                declare_runtime_files(session, runtime, bootstrap=bootstrap)
            except BaseException as error:
                if primary is None:
                    raise
                primary.add_note('COMSOL diagnostic preservation failed: ' + repr(error))
        for record in guards:
            verify_record('COMSOL basis immutable input', record)
        require_launcher_completion(completion, session.run_id)
        if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
            raise ValueError('COMSOL basis bootstrap failed')
        row = json.loads(report.read_text(encoding='utf-8-sig'))
        if (row.get('operation') != mode or row.get('compute_calls') != (2 if mode == 'compute' else 0)
                or row.get('model_path') != str(output) or row.get('maximum_mesh_elements') != maximum_mesh_elements
                or not 0 < _native_exact_count(row.get('mesh_element_count')) <= maximum_mesh_elements
                or row['off_solution']['solution_tag'] == row['on_solution']['solution_tag']):
            error = ValueError('COMSOL basis report differs from requested operation')
            error.failure_output_paths = [path for path in (mesh_facts, report, output) if path.is_file()]
            raise error
        if first is None:
            first = row
            saved = [file_record(output, 'solver_native_binary')]
        elif any(first[key] != row[key] for key in ('off_solution', 'on_solution', 'mesh_identity', 'mesh_element_count', 'maximum_mesh_elements', 'group_keys', 'off_voltages_v', 'on_voltages_v', 'vacuum_domains')):
            raise ValueError('COMSOL basis cold reopen differs from computed model')
        reports[operation] = file_record(report, 'required_evidence')
    products = {}
    workpoint_reports = []
    for name, request_key, solution_key in (('background', 'off_request', 'off_solution'), ('on', 'on_request', 'on_solution')):
        workpoint_report = session.declare_file(session.result_dir / ('reopen_' + name + '_solution.json'), 'required_evidence')
        write_json_atomic(workpoint_report, {'solution': first[solution_key], 'co_resident_workpoint': name})
        workpoint_reports.append(str(workpoint_report))
        products[name] = {'schema_version': 1, 'kind': 'field_solution', 'status': 'complete',
            'metadata': {'backend': 'comsol', 'scope': 'co_resident_stationary_workpoint', 'field_status': 'solved',
                         'native_reopen_verified': True, 'solution': first[solution_key], 'co_resident_workpoint': name,
                         'scientific_qualification': 'not_granted'},
            'data': {'model': saved[0], 'projection': records['projection'], 'descriptor': records['descriptor'],
                     'reopen_geometry': records['reopen_geometry'], 'geometry_validation': records['geometry_validation'],
                     'request': records[request_key], 'reopen_solution': file_record(workpoint_report, 'required_evidence'),
                     'prepared_manifest': manifest, 'mesh_facts': file_record(mesh_facts, 'required_evidence'), **reports}}
    outputs = [str(output), str(mesh_facts), *(row['path'] for row in reports.values()), *workpoint_reports]
    return {'status': 'success', 'summary': {'scope': 'co_resident_stationary_workpoints', 'compute_calls': 2},
            'output_paths': outputs, 'required_output_paths': outputs, 'retention_preserve_paths': [],
            'manifest_extra_fields': {'products': products}}


def trace_assembly_pulse(assembly: Assembly, background: Mapping[str, Any], on: Mapping[str, Any], *,
                         pulse_groups: list[dict], drive: Mapping[str, Any], source: Mapping[str, Any],
                         numerics: Mapping[str, Any], observation_times_us: list[float],
                         epoch_record: Mapping[str, Any], position_atol_m: float, velocity_atol_m_s: float,
                         context: Any) -> OpenedArtifact:
    """Run a managed COMSOL CPT batch; numerical/native qualification is separate."""
    from datetime import datetime
    from functools import partial
    from pathlib import Path
    from uuid import uuid4
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.io.manifest_records import file_record, verify_record
    from msplatform.results.artifacts import open_artifact

    # The public boundary authenticates the incoming artifacts. Their owners'
    # references are then held by run_managed_stage while native children run.
    from msplatform.backends.comsol.assembly_native_scope import require_supported_artifact, require_supported_assembly
    require_supported_assembly(assembly)
    background = open_artifact(background, expected_kind='field_solution')
    on = open_artifact(on, expected_kind='field_solution')
    require_supported_artifact(background)
    require_supported_artifact(on)
    plan = prepare_assembly_pulse(assembly, background, on, pulse_groups=pulse_groups,
        drive=drive, source=source, numerics=numerics, observation_times_us=observation_times_us)
    epoch = dict(epoch_record, retention_role='required_evidence')
    verify_record('instrument epoch', epoch)
    if epoch['sha256'].upper() != source['clock']['authority_sha256'].upper():
        raise ValueError('epoch bytes differ from the original source clock authority')
    epoch_us = json.loads(Path(epoch['path']).read_text(encoding='utf-8-sig'))['instrument_time_us']
    if type(epoch_us) not in (int, float) or not math.isfinite(epoch_us):
        raise ValueError('instrument epoch must be finite')
    # MATLAB jsondecode represents integers as double; reject identities that
    # cannot be transported exactly until a string-ID bridge is implemented.
    if any(pid > 2**53 for pid in plan['source']['particle_ids']):
        raise ValueError('COMSOL JSON transport currently supports particle IDs up to 2**53')
    for value in (position_atol_m, velocity_atol_m_s):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('explicit positive SI birth comparison tolerances required')
    stage, authority = read_stage_policy(context, 'trace_assembly_particles', required_roles=('solver_native_binary',))
    _require_tools(context)
    if stage.get('runtime'):
        raise ValueError('particle stage does not accept implicit runtime overrides')
    refs = [{'manifest_record': dict(item.reference['manifest'], path=str(item.manifest_location))}
            for item in (background, on)]
    result = run_managed_stage(context,
        descriptor={'project': 'instrument_assembly', 'mode': 'comsol_assembly_pulse', 'software': ['COMSOL', 'MATLAB']},
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__sim__comsol__pulse-' + uuid4().hex[:12],
        payload={'action': 'trace_assembly_particles', 'plan': plan, 'stage_policy': stage},
        committed_new_bytes=stage['limits']['transient_run_directory_bytes'], commitment_inputs=[authority],
        retention=stage['artifact_retention'], source_references=refs,
        expected_operation_ids=('trace_assembly_particles',), operation_dependencies={},
        action=partial(_execute_particle_trace, background=background, plan=plan, epoch_record=epoch,
                       epoch_us=float(epoch_us), position_atol_m=position_atol_m,
                       velocity_atol_m_s=velocity_atol_m_s, limits=stage['limits']),
        action_record=file_record(Path(__file__), 'required_evidence'), use_short_execution_path=True,
        completion_api=_comsol_batch_completion_api)
    return open_artifact({'manifest': result['manifest'], 'product_id': 'trajectory'}, expected_kind='trajectory_result')


def _comsol_batch_completion_api():
    """COMSOL launcher evidence is atomic; no partial SIMION batches are recoverable."""
    from pathlib import Path

    class Completion:
        @staticmethod
        def recoverable_batch_log_kind(path):
            return None

        @staticmethod
        def has_recoverable_batch_completion(path):
            return False

        @staticmethod
        def recoverable_batch_logs(run_dir):
            logs = Path(run_dir) / 'logs'
            if logs.is_dir() and any(path.match('simion__batch*.trace.log') or path.match('simion__batch*.stdout.log')
                                     for path in logs.iterdir() if path.is_file()):
                raise ValueError('unexpected SIMION batch evidence in COMSOL particle operation')
            return set()

    return Completion


def _freeze_particle_epoch(session: Any, original: Mapping[str, Any]) -> dict:
    """Bind and copy the small source epoch to stable native-owner storage."""
    from msplatform.execution.inputs import freeze_file
    from msplatform.io.manifest_records import file_record, verify_record
    source = dict(original, retention_role='required_evidence')
    verify_record('particle epoch source', source)
    session.add_input('clock_epoch_source', source)
    target = session.declare_file(session.input_dir / 'instrument_epoch.json', 'required_evidence')
    freeze_file(Path(source['path']), target, retention_role='required_evidence')
    frozen = file_record(target, 'required_evidence')
    if any(frozen[key] != source[key] for key in ('bytes', 'sha256')):
        raise ValueError('frozen particle epoch differs from original source')
    verify_record('particle epoch source after freeze', source)
    session.add_input('clock_epoch', frozen)
    return frozen


def _comsol_version_label(value: Any) -> str:
    """Accept only COMSOL 6.4 version strings, preserving actual build text."""
    if not isinstance(value, str) or not re.fullmatch(r'(?:COMSOL Multiphysics )?6\.4(?: \(Build: [0-9]+\))?', value):
        raise ValueError('unsupported COMSOL native version')
    return value if value.startswith('COMSOL ') else 'COMSOL ' + value


def _execute_particle_trace(session: Any, *, background: OpenedArtifact, plan: dict, epoch_record: dict,
                            epoch_us: float, position_atol_m: float, velocity_atol_m_s: float,
                            limits: dict) -> dict:
    import csv
    from msplatform.backends.comsol.native_execution import declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion
    from msplatform.backends.comsol.particle_data import read_observations
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.io.manifest_records import file_record, verify_record
    from msplatform.physics import CONSTANTS
    from msplatform.results.particle_data import write_particle_data, read_particle_data, summarize_particle_data

    launcher, code = freeze_native_sources(session, ('comsolstartup.m', 'trace_assembly_particles.m', 'oatof_cpt_solver_policy.m'))
    model = dict(background.data_records['model'], path=str(background.data_locations['model']))
    session.add_input('field_model', model)
    frozen_epoch = _freeze_particle_epoch(session, epoch_record)
    plan_path = session.declare_file(session.input_dir / 'particle_plan.json', 'required_evidence')
    write_json_atomic(plan_path, plan)
    plan_record = file_record(plan_path, 'required_evidence')
    session.add_input('particle_plan', plan_record)
    release = session.declare_file(session.input_dir / 'birth_6d.csv', 'required_evidence')
    initial = []
    with release.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        for row in plan['source']['rows']:
            position = [row[f'position_{axis}_mm'] for axis in 'xyz']
            velocity = [row[f'velocity_{axis}_m_s'] for axis in 'xyz']
            writer.writerow(position + velocity)
            initial.append({'particle_id': row['particle_id'], 'species_id': row['species_id'],
                'position_m': [v * 1e-3 for v in position], 'velocity_m_s': velocity,
                'time_s': (row['instrument_time_us'] - epoch_us) * 1e-6,
                'mass_kg': plan['source']['mass_kg'], 'charge_state': row['charge_state'],
                'charge_c': row['charge_state'] * CONSTANTS['elementary_charge_c'], 'weight': row['particle_weight'],
                'parent_particle_id': None, 'lineage_status': 'primary_birth'})
    release_record = file_record(release, 'required_evidence')
    session.add_input('birth_6d', release_record)
    runtime = session.run_dir / 'comsol_runtime' / 'trace_assembly_particles'
    runtime.mkdir(parents=True)
    report = session.declare_file(session.log_dir / 'particle.bootstrap.log', 'required_evidence')
    completion = session.declare_file(session.log_dir / 'particle.launcher.json', 'required_evidence')
    task = session.declare_file(session.input_dir / 'particle_task.m', 'required_evidence')
    output = session.declare_file(session.result_dir / 'assembly_particles.csv', 'required_evidence')
    facts = session.declare_file(session.result_dir / 'assembly_particle_facts.json', 'required_evidence')
    native_release = session.declare_file(session.result_dir / 'assembly_release.txt', 'required_evidence')
    call = 'trace_assembly_particles(' + ','.join(map(matlab_text, (plan_path, model['path'], release, session.result_dir))) + ')'
    task.write_text('addpath(' + matlab_text(launcher.parent.parent / 'matlab') + ');\n' + call + ';\n', encoding='utf-8', newline='\n')
    host = json.dumps({name: str(getattr(session.context, name)) for name in
                       ('workspace', 'python_executable', 'host_state_path', 'policy_path')})
    args = ['-NoProfile', '-File', str(launcher), '-HostContextJson', host, '-WorkingDirectory', str(session.run_dir),
            '-ComsolLauncherPath', str(session.context.tools['comsol_launcher']), '-MatlabRootPath',
            str(session.context.tools['matlab_root']), '-TaskScript', str(task), '-ReportPath', str(report),
            '-StartupAttempts', '1', '-RunId', session.run_id, '-RunDir', str(runtime), '-CompletionPath', str(completion)]
    guards = [*code, model, epoch_record, frozen_epoch, plan_record, release_record, file_record(task, 'required_evidence')]
    primary = None
    try:
        session.run_process('trace_assembly_particles', executable=session.context.powershell_executable,
                            arguments=args, role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
    except BaseException as error:
        primary = error
        error.failure_output_paths = [*getattr(error, 'failure_output_paths', ()),
            *(path for path in (output, facts, native_release) if path.is_file())]
        raise
    finally:
        try:
            declare_runtime_files(session, runtime, bootstrap=report)
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note('COMSOL diagnostic preservation failed: ' + repr(error))
    try:
        for record in guards:
            verify_record('COMSOL particle immutable input', record)
        require_launcher_completion(completion, session.run_id)
        if 'STATUS=PASS' not in report.read_text(encoding='utf-8-sig'):
            raise ValueError('COMSOL particle launcher failed')
        native_facts = json.loads(facts.read_text(encoding='utf-8-sig'))
        version = native_facts.get('comsol_version')
        if (not isinstance(version, str) or not re.fullmatch(r'(?:COMSOL Multiphysics )?6\.4(?: \(Build: [0-9]+\))?', version) or native_facts.get('study_completed') is not True
                or native_facts.get('particle_count') != len(initial)
                or native_facts.get('stored_times_us') != plan['observation_times_us']
                or native_facts.get('boundary_policy') != 'metal_and_outer_freeze_ideal_pass'):
            raise ValueError('COMSOL native facts differ from the frozen plan or supported version')
        detector = plan.get('detector_active_face')
        detector_faces = native_facts.get('detector_faces')
        if detector is not None:
            if (native_facts.get('detector_observation_native') is not True or
                    not isinstance(detector_faces, (int, list)) or isinstance(detector_faces, bool)):
                raise ValueError('native detector boundary evidence is missing')
            if isinstance(detector_faces, int):
                detector_faces = [detector_faces]
            if (not detector_faces or any(type(face) is not int or face <= 0 for face in detector_faces)
                    or len(set(detector_faces)) != len(detector_faces)):
                raise ValueError('native detector boundary evidence is invalid')
        elif native_facts.get('detector_observation_native') not in (None, False):
            raise ValueError('native detector evidence has no frozen authored surface')
        result = read_observations(output, initial_states=initial, epoch_us=epoch_us,
            backend_version=_comsol_version_label(version), observation_times_us=plan['observation_times_us'],
            position_atol_m=position_atol_m, velocity_atol_m_s=velocity_atol_m_s,
            boundary_policy=native_facts['boundary_policy'], detector_contract=detector)
        write_particle_data(session.result_dir, result, metadata={'schema_version': 2,
            'initial_state_basis': 'native_birth_verified', 'frame_id': plan['background']['projection']['assembly_frame_id'],
            'clock': {'basis': 'experiment_relative', 'unit': 's', **plan['source']['clock']}})
        canonical = read_particle_data(session.result_dir)
        summary = session.declare_file(session.result_dir / 'particle_integrity.json', 'required_evidence')
        write_json_atomic(summary, {'execution_status': result.execution_status, 'data_integrity': result.data_integrity,
                                    'statistics': summarize_particle_data(canonical)})
        records = {'observations': file_record(output, 'required_evidence'), 'integrity': file_record(summary, 'required_evidence'),
                   'native_facts': file_record(facts, 'required_evidence'),
                   'plan': plan_record, 'release': release_record, 'clock_epoch': frozen_epoch}
        for name in ('initial_states.parquet', 'terminal_states.parquet', 'events.parquet', 'trajectories.h5', 'execution.json'):
            records['particle_data_' + name.replace('.', '_')] = file_record(session.result_dir / name, 'required_evidence')
        products = [str(output), str(summary), str(facts), str(native_release)] + [str(session.result_dir / name) for name in
            ('initial_states.parquet', 'terminal_states.parquet', 'events.parquet', 'trajectories.h5', 'execution.json')]
        return {'status': 'success', 'summary': {'native_execution': 'succeeded', 'data_integrity': result.data_integrity},
                'output_paths': products, 'required_output_paths': products,
                'retention_preserve_paths': [], 'manifest_extra_fields': {'products': {'trajectory': {
                    'schema_version': 1, 'kind': 'trajectory_result', 'status': 'complete',
                    'metadata': {'backend': 'comsol', 'data_integrity': result.data_integrity}, 'data': records}}}}
    except BaseException as error:
        error.failure_output_paths = [*getattr(error, 'failure_output_paths', ()),
            *(path for path in (output, facts, native_release) if path.is_file())]
        raise


def _validate_failed_basis_evidence(manifest: Mapping[str, Any], summary: Mapping[str, Any],
                                    completion: Mapping[str, Any], run_dir: Path,
                                    model_path: Path, report_path: Path) -> None:
    """Reject arbitrary or unfinished sources before any new identity capture."""
    from msplatform.execution.process_transport import _host_release
    run_dir = run_dir.resolve(strict=True)
    expected_model = run_dir / 'assembly-pulse-basis.mph'
    expected_report = run_dir / 'results' / 'solve_pulse_basis.json'
    if model_path.resolve(strict=True) != expected_model or report_path.resolve(strict=True) != expected_report:
        raise ValueError('basis recovery files must be the exact declared source paths')
    run_id = manifest.get('run_id')
    if (manifest.get('status') != 'failed' or summary.get('status') != 'failed'
            or summary.get('run_id') != run_id or summary.get('writers_stopped') is not True
            or completion.get('status') != 'failed' or completion.get('run_id') != run_id):
        raise ValueError('basis recovery requires a stopped failed source run')
    roles = completion.get('file_roles', {})
    if roles.get(str(expected_model)) != 'solver_native_binary' or roles.get(str(expected_report)) != 'required_evidence':
        raise ValueError('basis recovery requires both exact source file roles')
    writers = completion['writer_completion']
    operations = writers['operations']
    if (len(operations) != 1 or operations[0].get('operation_id') != 'solve_pulse_basis'
            or operations[0]['observation'].get('exit_confirmed') is not True
            or type(operations[0]['observation'].get('returncode')) is not int
            or operations[0]['observation']['returncode'] != 0):
        raise ValueError('basis native compute writer must have exited successfully')
    releases = writers['resource_releases']
    if len(releases) != 1 or releases[0]['release_id'] != operations[0]['resource_release_id']:
        raise ValueError('basis native host release differs')
    host = _host_release(releases[0]['completion_receipt'])
    if host['error'] is not None or host['inherited'] or host['result'] != {'status': 'released', 'token': host['token']}:
        raise ValueError('basis native host release must be confirmed')


def recover_basis_model(failed_manifest: Mapping[str, Any], *, context: Any) -> tuple[OpenedArtifact, OpenedArtifact]:
    """Capture stopped unmanifested outputs now, cold-reopen only, and publish both workpoints.

    The original failed manifest did not seal these outputs. Their identities
    are newly captured under write exclusion after verified writer exit.
    """
    from contextlib import ExitStack
    from datetime import datetime, timezone
    from functools import partial
    from uuid import uuid4
    from msplatform.execution.capacity_protection import capacity_decision_lock
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.file_lock import shared_process_file_lock
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
    from msplatform.io.file_identity import guarded_file_identity
    from msplatform.io.manifest_records import file_record, record_path, require_completed_terminal_publication, verify_record
    from msplatform.results.artifacts import open_artifact

    verify_record('failed basis manifest', failed_manifest)
    manifest_path = record_path(failed_manifest).resolve(strict=True)
    raw_root = (context.workspace / 'artifacts').resolve(strict=True)
    if manifest_path.name != 'run_manifest.json' or not manifest_path.is_relative_to(raw_root):
        raise ValueError('failed basis source must be in this native owner root')
    run_dir = manifest_path.parent
    with ExitStack() as stack:
        stack.enter_context(shared_process_file_lock(run_dir / TERMINAL_LOCK_NAME))
        with capacity_decision_lock(raw_root):
            require_completed_terminal_publication(manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            def retained(name):
                matches = [item for item in manifest['outputs'] if Path(item['path']).name == name]
                if len(matches) != 1:
                    raise ValueError('missing unique failed basis evidence: ' + name)
                verify_record(name, matches[0])
                return json.loads(record_path(matches[0]).read_text(encoding='utf-8-sig'))
            summary, completion = retained('summary.json'), retained('execution_completion.json')
            model_path = run_dir / 'assembly-pulse-basis.mph'
            report_path = run_dir / 'results' / 'solve_pulse_basis.json'
            _validate_failed_basis_evidence(manifest, summary, completion, run_dir, model_path, report_path)
            model_guard = stack.enter_context(guarded_file_identity(model_path))
            report_guard = stack.enter_context(guarded_file_identity(report_path))
            model = {'path': str(model_path), 'exists': True, 'bytes': model_guard.bytes_count,
                     'sha256': model_guard.sha256, 'retention_role': 'solver_native_binary'}
            report = {'path': str(report_path), 'exists': True, 'bytes': report_guard.bytes_count,
                      'sha256': report_guard.sha256, 'retention_role': 'required_evidence'}
            captured_at = datetime.now(timezone.utc).isoformat()
            identity_dir = context.workspace / 'artifacts' / 'platform' / 'basis_identity_captures'
            identity_dir.mkdir(parents=True, exist_ok=True)
            identity_path = identity_dir / (uuid4().hex + '.json')
            from msplatform.execution.recorded_file_removal import write_json_atomic
            write_json_atomic(identity_path, {'schema_version': 1, 'role': 'basis_source_identity_capture',
                'identity_basis': 'identity_captured_after_failed_python_validation', 'captured_at_utc': captured_at,
                'failed_manifest': dict(failed_manifest), 'model': model, 'report': report})
            identity_record = file_record(identity_path, 'required_evidence')
            inputs = manifest['inputs']
            names = ('prepared_manifest', 'projection', 'descriptor', 'reopen_geometry', 'geometry_validation', 'off_request', 'on_request')
            for name in names:
                verify_record('failed basis frozen ' + name, inputs[name])
            source = open_artifact({'manifest': inputs['prepared_manifest'], 'product_id': 'model'}, expected_kind='prepared_model')
            if (source.metadata.get('backend') != 'comsol' or source.metadata.get('scope') != 'assembly_electrostatic_unsolved'
                    or source.metadata.get('native_reopen_verified') is not True):
                raise ValueError('basis recovery requires verified original prepared model')
            if inputs['off_request']['sha256'] != source.data_records['request']['sha256']:
                raise ValueError('basis recovery OFF request differs from original prepared model')
            for name in ('projection', 'descriptor', 'reopen_geometry', 'geometry_validation'):
                if json.loads(Path(inputs[name]['path']).read_text(encoding='utf-8-sig')) != json.loads(source.data_path(name).read_text(encoding='utf-8-sig')):
                    raise ValueError('failed basis frozen source differs: ' + name)
            computed = json.loads(report_path.read_text(encoding='utf-8-sig'))
            if computed.get('operation') != 'compute' or computed.get('compute_calls') != 2 or Path(computed.get('model_path', '')).resolve() != model_path:
                raise ValueError('failed source does not contain the completed two-workpoint report')
            _native_exact_count(computed.get('mesh_element_count'))
            _require_tools(context)
            stage, authority = read_stage_policy(context, 'recover_assembly_pulse_basis', required_roles=('solver_native_binary',))
            if stage.get('runtime'):
                raise ValueError('basis recovery has no runtime overrides')
        result = run_managed_stage(context,
            descriptor={'project': 'instrument_assembly', 'mode': 'pulse_basis_recovery', 'software': ['COMSOL', 'MATLAB']},
            run_id=datetime.now().strftime('%Y%m%d_%H%M%S') + '__analysis__comsol__basis-recovery-' + uuid4().hex[:12],
            payload={'action': 'recover_assembly_pulse_basis', 'identity_basis': 'identity_captured_after_failed_python_validation',
                     'identity_captured_at_utc': captured_at, 'failed_run_id': manifest['run_id'], 'stage_policy': stage},
            committed_new_bytes=stage['limits']['transient_run_directory_bytes'],
            commitment_inputs=[authority, failed_manifest, identity_record, report, *(inputs[name] for name in names)],
            retention=stage['artifact_retention'],
            source_references=[{'manifest_record': failed_manifest}, {'manifest_record': inputs['prepared_manifest']}],
            expected_operation_ids=('reopen_pulse_basis',), operation_dependencies={},
            action=partial(_execute_basis_recovery, source=source, inputs=inputs, model=model, report=report,
                           computed=computed, limits=stage['limits'], failed_manifest=failed_manifest),
            action_record=file_record(Path(__file__), 'required_evidence'),
            use_short_execution_path=True, completion_api=no_particle_batch_completion_api)
        model_guard.assert_matches(model_path, expected_bytes=model['bytes'], expected_sha256=model['sha256'])
        report_guard.assert_matches(report_path, expected_bytes=report['bytes'], expected_sha256=report['sha256'])
        return tuple(open_artifact({'manifest': result['manifest'], 'product_id': name}, expected_kind='field_solution')
                     for name in ('background', 'on'))


def _execute_basis_recovery(session: Any, *, source: OpenedArtifact, inputs: dict, model: dict,
                            report: dict, computed: dict, limits: dict, failed_manifest: dict) -> dict:
    from msplatform.backends.comsol.native_execution import declare_runtime_files, freeze_native_sources, matlab_text, require_launcher_completion
    from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
    from msplatform.backends.comsol.assembly_field_solution import validate_solution_readback
    from msplatform.execution.recorded_file_removal import write_json_atomic
    from msplatform.io.manifest_records import file_record, verify_record

    launcher, frozen = freeze_native_sources(session, ('comsolstartup.m', 'solve_assembly_pulse_basis.m',
        'read_assembly_stationary_solution.m', 'verify_assembly_electrostatic_bindings.m',
        'read_comsol_mesh_size_controls.m', 'assembly_mesh_identity.m'))
    names = ('projection', 'descriptor', 'reopen_geometry', 'geometry_validation', 'off_request', 'on_request')
    records = {name: inputs[name] for name in names}
    for name, record in {'failed_manifest': failed_manifest, 'captured_model': model,
                         'captured_compute_report': report, **records}.items():
        session.add_input(name, record)
    paths = {name: Path(record['path']) for name, record in records.items()}
    projection = json.loads(paths['projection'].read_text(encoding='utf-8-sig'))
    off, on = (json.loads(paths[key].read_text(encoding='utf-8-sig')) for key in ('off_request', 'on_request'))
    if validate_request(projection, off) != off or validate_request(projection, on) != on:
        raise ValueError('basis recovery workpoint requests differ from frozen geometry')
    if any(off[k] != on[k] for k in ('relative_permittivity', 'exterior', 'mesh', 'study')):
        raise ValueError('basis recovery workpoints change non-voltage parameters')
    keys = [x['instance_id'] + '/' + x['electrode_group_id'] for x in projection['electrode_groups']]
    if (computed.get('group_keys') != keys or computed.get('off_voltages_v') != [x['voltage_v'] for x in off['group_voltages']]
            or computed.get('on_voltages_v') != [x['voltage_v'] for x in on['group_voltages']]
            or not computed.get('mesh_identity') or not computed.get('vacuum_domains')):
        raise ValueError('basis compute evidence differs from frozen physics or geometry')
    for item in ('off_solution', 'on_solution'):
        row = computed[item]
        validate_solution_readback(row, study_tag=row['study_tag'], solution_tag=row['solution_tag'], dataset_tag=row['dataset_tag'])
    if computed['off_solution']['solution_tag'] == computed['on_solution']['solution_tag']:
        raise ValueError('basis recovery requires distinct solution sequences')
    output = session.declare_file(session.result_dir / 'reopen_pulse_basis.json', 'required_evidence')
    bootstrap = session.declare_file(session.log_dir / 'reopen_pulse_basis.bootstrap.log', 'required_evidence')
    completion = session.declare_file(session.log_dir / 'reopen_pulse_basis.launcher.json', 'required_evidence')
    task = session.declare_file(session.input_dir / 'reopen_pulse_basis.m', 'required_evidence')
    unused_mesh_facts = session.declare_file(session.result_dir / 'unused_mesh_facts.json', 'required_evidence')
    runtime = session.run_dir / 'comsol_runtime' / 'reopen_pulse_basis'; runtime.mkdir(parents=True)
    call = 'solve_assembly_pulse_basis(' + ','.join(map(matlab_text, (paths['projection'], paths['off_request'],
        paths['on_request'], source.data_locations['model'], model['path'], 'reopen'))) + ',' + str(_native_exact_count(computed['maximum_mesh_elements'])) + ',' + matlab_text(unused_mesh_facts) + ')'
    task.write_text('addpath(' + matlab_text(launcher.parent.parent / 'matlab') + ');\nresult=' + call +
        ";\nfid=fopen(" + matlab_text(output) + ",'w','n','UTF-8'); assert(fid>=0); c=onCleanup(@() fclose(fid)); fprintf(fid,'%s',jsonencode(result));\n", encoding='utf-8', newline='\n')
    host = json.dumps({name: str(getattr(session.context, name)) for name in ('workspace', 'python_executable', 'host_state_path', 'policy_path')})
    guards = [*frozen, *records.values(), failed_manifest, model, report, file_record(task, 'required_evidence')]
    args = ['-NoProfile', '-File', str(launcher), '-HostContextJson', host, '-WorkingDirectory', str(session.run_dir),
            '-ComsolLauncherPath', str(session.context.tools['comsol_launcher']), '-MatlabRootPath', str(session.context.tools['matlab_root']),
            '-TaskScript', str(task), '-ReportPath', str(bootstrap), '-StartupAttempts', '1', '-RunId', session.run_id,
            '-RunDir', str(runtime), '-CompletionPath', str(completion)]
    primary = None
    try:
        session.run_process('reopen_pulse_basis', executable=session.context.powershell_executable, arguments=args,
                            role='COMSOL', stage='solver', limits=limits, immutable_input_records=guards)
    except BaseException as error:
        primary = error; raise
    finally:
        try:
            declare_runtime_files(session, runtime, bootstrap=bootstrap)
        except BaseException as error:
            if primary is None: raise
            primary.add_note('Recovery diagnostic preservation failed: ' + repr(error))
    for item in guards:
        verify_record('basis recovery immutable input', item)
    require_launcher_completion(completion, session.run_id)
    if 'STATUS=PASS' not in bootstrap.read_text(encoding='utf-8-sig'):
        raise ValueError('basis recovery native bootstrap failed')
    reopened = json.loads(output.read_text(encoding='utf-8-sig'))
    if reopened.get('operation') != 'reopen' or reopened.get('compute_calls') != 0 or Path(reopened.get('model_path', '')).resolve() != Path(model['path']).resolve():
        raise ValueError('basis recovery unexpectedly changed the native model or ran Compute')
    for key in ('off_solution', 'on_solution', 'mesh_identity', 'mesh_element_count', 'maximum_mesh_elements', 'group_keys', 'off_voltages_v', 'on_voltages_v', 'vacuum_domains'):
        if reopened[key] != computed[key]:
            raise ValueError('basis recovery cold read differs: ' + key)
    products, paths_out = {}, [str(output)]
    for name, request_key, solution_key in (('background', 'off_request', 'off_solution'), ('on', 'on_request', 'on_solution')):
        fact = session.declare_file(session.result_dir / ('reopen_' + name + '_solution.json'), 'required_evidence')
        write_json_atomic(fact, {'solution': reopened[solution_key], 'co_resident_workpoint': name})
        products[name] = {'schema_version': 1, 'kind': 'field_solution', 'status': 'complete',
            'metadata': {'backend': 'comsol', 'scope': 'co_resident_stationary_workpoint', 'field_status': 'solved',
                         'native_reopen_verified': True, 'solution': reopened[solution_key], 'co_resident_workpoint': name,
                         'scientific_qualification': 'not_granted', 'identity_basis': 'identity_captured_after_failed_python_validation'},
            'data': {'model': model, 'projection': records['projection'], 'descriptor': records['descriptor'],
                     'reopen_geometry': records['reopen_geometry'], 'geometry_validation': records['geometry_validation'],
                     'request': records[request_key], 'reopen_solution': file_record(fact, 'required_evidence'),
                     'prepared_manifest': inputs['prepared_manifest'], 'solve_pulse_basis': report,
                     'reopen_pulse_basis': file_record(output, 'required_evidence')}}
        paths_out.append(str(fact))
    return {'status': 'success', 'summary': {'scope': 'co_resident_stationary_workpoints', 'compute_calls': 0,
            'identity_basis': 'identity_captured_after_failed_python_validation'}, 'output_paths': paths_out,
            'required_output_paths': paths_out, 'retention_preserve_paths': [], 'manifest_extra_fields': {'products': products}}
