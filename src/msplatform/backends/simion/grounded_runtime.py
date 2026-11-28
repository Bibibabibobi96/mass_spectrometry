"""Managed analytic zero-ground carriers derived from a sealed SIMION field bundle."""
from __future__ import annotations

import copy
import json
from contextlib import ExitStack
from datetime import datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

from msplatform.execution.native_source_guard import guard_native_source
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact
from .artifacts import CompiledPreparedModel
from .field_closure import data_record, require_downstream_reuse
from .model import require_prepared_model
from .native_plans import plan_analytic_ground_carriers
from .resources import native_resource_path

BC = 'ground_dirichlet_zero_outer_homogeneous_neumann'
# Reviewed frozen original builder identities: no boundary override, SIMION
# default non-electrode boundary is homogeneous Neumann.
_REVIEWED_BUILDERS = {
    'build_flight_tube_variant.lua': '7CBFA69D88E198302406A1FF12C6ACE071D46261C578D6349F46DFD803023B62',
    'build_detector_variant.lua': '0C56AE83B69319BAD8E7F7E6CDEBE5FCF24C0FBBB21F2F553E34E06E56292DF4',
    'gem2pa_geometry.lua': 'FF9CB54315E1FFE9CC3DA0FC108A2E0EB4E4D192007537ED78B8878877080486',
}


def _admit(reference):
    source = open_artifact(reference, expected_kind='field_bundle')
    meta = source.metadata
    if (meta.get('backend') != 'simion' or meta.get('field_status') != 'available'
            or meta.get('source_status') != 'not_requested'):
        raise ValueError('analytic ground requires a sealed SIMION field bundle')
    model = CompiledPreparedModel(source.data_path('compiled_model').read_text(encoding='utf-8-sig'))
    document = require_prepared_model(model)
    if meta.get('model_identity_sha256') != document['model_identity_sha256'] or meta.get('clock') != document['drive']['clock']:
        raise ValueError('analytic ground source model or clock differs')
    _, assets = require_downstream_reuse(source, meta['downstream_identity'])
    # Only the exact frozen original builders with the known default Neumann
    # solver path qualify. A changed implementation requires fresh review.
    builders = meta['downstream_identity']['builder_identities']
    for name, reviewed_hash in _REVIEWED_BUILDERS.items():
        frozen = data_record(source, 'resource_'+name)
        current = file_record(native_resource_path(name), 'required_evidence')
        if (frozen['sha256'].upper() != reviewed_hash or current['sha256'].upper() != reviewed_hash
                or builders[name].upper() != reviewed_hash):
            raise ValueError('analytic ground source builder identity differs')
    return source, model, assets


def verified_ground_origin(source):
    """Authenticate every borrowed record against the declared sealed source."""
    meta = source.metadata
    if meta.get('ground_representation') != 'analytic_zero_on_native_geometry':
        raise ValueError('derived analytic ground source required')
    manifest = json.loads(Path(source.manifest_location).read_text(encoding='utf-8-sig'))
    if (manifest.get('project') != 'instrument_assembly' or manifest.get('mode') != 'fields_only'
            or manifest.get('status') != 'success'):
        raise ValueError('analytic ground requires its completed managed fields owner')
    request_record = manifest.get('inputs', {}).get('execution_request')
    if not isinstance(request_record, dict):
        raise ValueError('analytic ground managed request record is missing')
    verify_record('analytic ground managed request', request_record, base_dir=Path(source.manifest_location).parent)
    from msplatform.io.manifest_records import record_path
    request_path = record_path(request_record, base_dir=Path(source.manifest_location).parent)
    request = json.loads(request_path.read_text(encoding='utf-8-sig'))
    payload = request.get('payload', {})
    if payload.get('action') != 'prepare_grounded_runtime_fields' or payload.get('fields') != meta['ground_source_reference']:
        raise ValueError('analytic ground managed request source differs')
    for role in ('flight_tube', 'detector'):
        for mode in ('build', 'verify'):
            key = 'analytic_ground_'+mode+'_'+role+'_log'
            text = source.data_path(key).read_text(encoding='utf-8-sig')
            if 'ANALYTIC_ZERO_GROUND_'+mode.upper()+'=PASS' not in text:
                raise ValueError('analytic ground native proof is missing')
    origin, model, _ = _admit(meta['ground_source_reference'])
    if (meta.get('model_identity_sha256') != origin.metadata.get('model_identity_sha256')
            or meta.get('downstream_identity') != origin.metadata.get('downstream_identity')
            or meta.get('clock') != origin.metadata.get('clock')):
        raise ValueError('analytic ground source scientific identity differs')
    ground_keys = {key for role in ('flight_tube', 'detector')
                   for key in [meta['native_assets'][role]['carrier'], *meta['native_assets'][role]['family']]}
    for key in set(source.data_records) - ground_keys:
        if key.startswith('analytic_') and key.endswith('_log'):
            continue
        if key not in origin.data_records:
            raise ValueError('analytic ground has an unbound borrowed record')
        a, b = data_record(source, key), data_record(origin, key)
        if any(a[k] != b[k] for k in ('path','bytes','sha256')):
            raise ValueError('analytic ground borrowed record differs from source')
    return origin


def prepare_grounded_runtime_fields(fields, *, context, artifact_store=None):
    """Publish new zero-ground carriers under the existing managed owner."""
    from contextlib import nullcontext
    from msplatform.execution.owner import current_managed_native_store, standalone_native_store
    from . import native_completion
    if context is None or 'simion' not in context.tools or not context.tools['simion'].is_file():
        raise ValueError('analytic ground requires an explicit SIMION executable')
    stage, policy = read_stage_policy(context, 'prepare_grounded_runtime_fields', required_roles=('solver_native_binary',))
    runtime = stage.get('runtime', {})
    if (set(runtime) - {'simion_allow_asynchronous_io'}
            or ('simion_allow_asynchronous_io' in runtime and type(runtime['simion_allow_asynchronous_io']) is not bool)):
        raise ValueError('unsupported analytic ground runtime policy')
    parent = current_managed_native_store()
    if artifact_store is None and parent is None:
        raise ValueError('analytic ground requires an explicit ArtifactStore or protected parent scope')
    store = artifact_store if artifact_store is not None else parent['store']
    if parent is not None and parent['store'] is not store:
        raise ValueError('analytic ground must use the parent Store')
    reference = fields.reference if isinstance(fields, OpenedArtifact) else copy.deepcopy(fields)
    with ExitStack() as stack:
        source_assets = set()
        stack.enter_context(guard_native_source(reference, expected_kind='field_bundle',
            expected_artifact_root=context.workspace/'artifacts', artifact_store=store, asset_ids=source_assets))
        source, model, _ = _admit(reference)
        actual_tool = file_record(context.tools['simion'], 'required_evidence')
        tool_identity = source.metadata['downstream_identity']['tool_identity']
        if (tool_identity.get('release') != 'SIMION 2020'
                or actual_tool['bytes'] != tool_identity.get('executable_bytes')
                or actual_tool['sha256'].upper() != tool_identity.get('executable_sha256', '').upper()):
            raise ValueError('analytic ground SIMION tool identity differs from original field')
        planning = context.execution_root/'analytic-ground-plan'
        plan = plan_analytic_ground_carriers(model, boundary_conditions={'flight_tube':BC,'detector':BC},
            run_directory=planning, native_path_resource=planning/'inputs/native_sources/native_run_path.lua')
        ids = tuple(row['operation_id'] for row in plan.operations)
        action_record = file_record(Path(execute_grounded_runtime_fields.__code__.co_filename), 'required_evidence')
        scope = (standalone_native_store(store, task_key='standalone-grounded-fields',
                    budget=stage['limits']['transient_run_directory_bytes'], required_assets=tuple(sorted(source_assets)))
                 if parent is None else nullcontext())
        with scope:
            result = run_managed_stage(context, descriptor=dict(project='instrument_assembly',mode='fields_only',software=['SIMION']),
                run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'__sim__simion__ground-'+uuid4().hex[:12],
                payload=dict(action='prepare_grounded_runtime_fields', fields=source.reference, stage_policy=stage),
                committed_new_bytes=stage['limits']['transient_run_directory_bytes'],commitment_inputs=[policy],
                retention=stage['artifact_retention'],expected_operation_ids=ids,
                operation_dependencies={name:[ids[i-1]] for i,name in enumerate(ids) if i},
                action=partial(execute_grounded_runtime_fields, fields_reference=source.reference,limits=stage['limits'],
                    allow_asynchronous_io=runtime.get('simion_allow_asynchronous_io')), action_record=action_record,
                source_references=[dict(manifest_record=reference['manifest'])],use_short_execution_path=True,
                completion_api=lambda: native_completion, artifact_store=store)
        return open_artifact({'manifest':result['manifest'],'product_id':'fields'},expected_kind='field_bundle')


def _bind_retained_field_inputs(session, data):
    """Bind the exact borrowed product records to the new owner manifest."""
    session.add_inputs(('borrowed_field_'+str(index), record)
                       for index, record in enumerate(data.values(), 1))


def execute_grounded_runtime_fields(session, *, fields_reference, limits, allow_asynchronous_io=None):
    """Regenerate private geometry and cold-reopen analytically zero carriers."""
    from msplatform.execution.resources import resource_path
    from msplatform.execution.inputs import freeze_file
    from .native_io import apply_native_io_mode
    source, model, _ = _admit(fields_reference)
    root = session.run_dir
    frozen = session.input_dir/'native_sources'
    names = ('build_flight_tube_variant.lua','build_detector_variant.lua','gem2pa_geometry.lua','raw_collision_pa.lua')
    resources = {name:native_resource_path(name) for name in names}
    resources['native_run_path.lua'] = resource_path('native_run_path.lua')
    records = {}
    for name,path in resources.items():
        dest = frozen/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        session.declare_file(dest,'required_evidence')
        freeze_file(path,dest,retention_role='required_evidence')
        records[name] = file_record(session.canonical_path(dest),'required_evidence')
    plan = plan_analytic_ground_carriers(model,boundary_conditions={'flight_tube':BC,'detector':BC},
        run_directory=root,native_path_resource=frozen/'native_run_path.lua')
    if tuple(row['operation_id'] for row in plan.operations) != session.expected_operation_ids:
        raise ValueError('analytic ground graph differs from admitted graph')
    for path,text in plan.materializations.items():
        path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        session.declare_file(path,'required_evidence'); path.write_text(text,encoding='utf-8',newline='\n')
        records[str(path)] = file_record(session.canonical_path(path),'required_evidence')
    for operation in plan.operations:
        for output in operation['outputs']:
            path = Path(output); path.parent.mkdir(parents=True,exist_ok=True); session.declare_file(path,'solver_native_binary')
    for path in plan.declared_outputs:
        path = Path(path); path.parent.mkdir(parents=True,exist_ok=True); session.declare_file(path,'solver_native_binary')
    logs = {}
    for index,operation in enumerate(plan.operations,1):
        args = [str(frozen/Path(x).name) if Path(x).name in resources else x for x in operation['arguments']]
        argv = apply_native_io_mode([str(session.context.tools['simion']),*args],allow_asynchronous_io=allow_asynchronous_io)
        session.run_process(operation['operation_id'],executable=session.context.tools['simion'],arguments=argv[1:],
            role='SIMION',stage='prepare',limits=limits,immutable_input_records=list(records.values()))
        log = session.canonical_path(session.log_dir/f'operation_{index:04d}.stdout.log')
        if operation['success_marker'].encode('ascii') not in log.read_bytes():
            raise ValueError('analytic ground native completion marker missing')
        logs[operation['operation_id']] = file_record(log,'required_evidence')
        for path in operation['outputs']:
            record = file_record(session.canonical_path(path),'solver_native_binary')
            verify_record('analytic ground output',record)
            records[str(path)] = record
    data = {name:dict(source.data_records[name],path=str(source.data_locations[name])) for name in source.data_records}
    meta = copy.deepcopy(source.metadata)
    for role in ('flight_tube','detector'):
        keys = meta['native_assets'][role]
        for key in [keys['carrier'],*keys['family']]: data.pop(key,None)
    # Every retained borrowed product member must be bound by this run's
    # manifest inputs. Keep the original record, role, path and source owner.
    _bind_retained_field_inputs(session, data)
    for role in ('flight_tube','detector'):
        keys = meta['native_assets'][role]
        pa = session.canonical_path(root/'simion/ground_carriers'/(role+'.pa'))
        surf = pa.with_suffix('.pa-surf')
        carrier_key,surface_key = role+'_analytic_carrier',role+'_analytic_surface'
        data[carrier_key] = file_record(pa,'solver_native_binary')
        data[surface_key] = file_record(surf,'solver_native_binary')
        keys.update(carrier=carrier_key,family=[surface_key])
    data.update({'analytic_'+name+'_log':record for name,record in logs.items()})
    meta.update(ground_representation='analytic_zero_on_native_geometry',ground_source_reference=source.reference,
        ground_boundary_condition=BC,ground_refine_calls=0,ground_fly_calls=0,scientific_qualification='not_granted')
    outputs = [str(session.canonical_path(path)) for path in plan.declared_outputs] + [row['path'] for row in logs.values()]
    return dict(status='success',summary=meta,output_paths=outputs,required_output_paths=outputs,
        retention_preserve_paths=[],manifest_extra_fields={'products':{'fields':dict(schema_version=1,kind='field_bundle',
            status='complete',metadata=meta,data=data)}})
