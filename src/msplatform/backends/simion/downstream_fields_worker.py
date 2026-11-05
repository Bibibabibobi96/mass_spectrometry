"""One real private three-role downstream stage, using the original SIMION plans.

No cache, run owner or publication state is created here. Complete published
families may be transported by the original owner and checked for spatial reuse.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping, Any

from msplatform.execution.context import ExecutionContext
from msplatform.execution.processes import inherited_host_token
from msplatform.execution.file_identity import guarded_file_identity
from msplatform.execution.manifest_records import file_record, verify_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.io.file_identity import file_sha256
from .artifacts import CompiledPreparedModel
from .field_worker import _native_operation
from .model import require_prepared_model
from .native_plans import _plan_downstream_solve_with_assets
from .field_closure import downstream_identity


# All three real builders unconditionally load the adjacent GEM transport,
# including solve-only. One table owns freezing, worker admission and identity.
DOWNSTREAM_RESOURCES = ('build_flight_tube_variant.lua', 'build_detector_variant.lua',
    'build_reflectron_variant.lua', 'gem2pa_geometry.lua', 'export_standalone_pa.lua', 'audit_downstream_fields.lua')


def _owned_record(record: Mapping, root: Path) -> dict:
    """Check an actual admitted copy receipt without repeating its large-payload hash."""
    path = Path(record['path'])
    if (not path.is_absolute() or not path.resolve().is_relative_to(root.resolve())
            or path.is_symlink() or not path.is_file() or record.get('exists') is not True
            or path.stat().st_size != record['bytes']):
        raise ValueError('downstream payload is not an actual owned copy')
    return dict(record, path=str(path.resolve()))


def execute_downstream(context: ExecutionContext, *, compiled_model_record: dict,
                       raw_geometry_assets: dict, owned_geometry_records: list[dict],
                       run_directory: Path, working_directory: Path, log_directory: Path,
                       receipt_path: Path, convergence_v: dict, resources: dict,
                       spatial_identity: dict, limits: Mapping[str, Any],
                       reuse_assets: dict | None = None, reuse_identity: dict | None = None,
                       reuse_audit_record: dict | None = None,
                       allow_asynchronous_io: bool | None = None) -> dict:
    """Solve the original complete families or consume explicit verified owned copies.

    owned_geometry_records are actual records from the original payload worker.
    Reuse applicability and source manifests are frozen by the outer action;
    this worker checks their exact projection and never selects another source.
    """
    inherited_host_token(context, required=True)
    root, work, logs, receipt = map(Path, (run_directory, working_directory, log_directory, receipt_path))
    if (any(not path.is_absolute() for path in (root, work, logs, receipt))
            or any(not path.resolve().is_relative_to(root.resolve()) for path in (work, logs, receipt))):
        raise ValueError('downstream stage paths escape the original run')
    # The existing managed execution junction can spell this same owned run
    # differently. Check resolved ownership, but retain its native-safe working
    # spelling for the original plan; no new alias or cache transport is made.
    root, logs, receipt_path = root.resolve(), logs.resolve(), receipt.resolve()
    verify_record('downstream compiled model', compiled_model_record)
    document = json.loads(Path(compiled_model_record['path']).read_text(encoding='utf-8-sig'))
    model = CompiledPreparedModel(json.dumps(document, allow_nan=False))
    require_prepared_model(model)
    tool = spatial_identity['tool_identity']
    if tool.get('release') != 'SIMION 2020':
        raise ValueError('downstream worker requires the admitted SIMION2020 tool identity')
    verify_record('downstream executable', dict(path=str(context.tools['simion']), exists=True,
        bytes=tool['executable_bytes'], sha256=tool['executable_sha256'], retention_role='required_evidence'))
    if set(resources) != set(DOWNSTREAM_RESOURCES):
        raise ValueError('downstream worker requires the exact three builders, GEM transport, exporter and audit')
    builders = {name:file_sha256(resources[name]) for name in DOWNSTREAM_RESOURCES}
    actual_identity = downstream_identity(model, raw_assets=raw_geometry_assets, convergence_v=convergence_v,
        tool_identity=tool, builder_identities=builders)
    if actual_identity != spatial_identity:
        raise ValueError('downstream spatial identity differs from its actual model/tool/builder inputs')
    plan, asset_plan = _plan_downstream_solve_with_assets(model, raw_geometry_assets=raw_geometry_assets,
        working_directory=work, convergence_v=convergence_v,
        exporter_resource=Path(resources['export_standalone_pa.lua']),
        verifier_resource=Path(resources['audit_downstream_fields.lua']))
    copied = {str(Path(row['path']).resolve()):_owned_record(row, root) for row in owned_geometry_records}
    if len(copied) != len(owned_geometry_records):
        raise ValueError('downstream materialized records are duplicated')
    if reuse_assets is None:
        # Cold Refine needs all model raw/surface inputs. Published runtime
        # reflectron reuse is already detached and intentionally has no PA#;
        # its complete role/copy/audit/spatial identity is checked below.
        for copy in plan.input_copies:
            destination, source = str(Path(copy['destination']).resolve()), copy['source_record']
            if destination not in copied or any(str(copied[destination][key]).upper() != str(source[key]).upper()
                                               for key in ('bytes','sha256')):
                raise ValueError('downstream raw/surface copy differs from its model source: '+destination)
    observations = []
    report = dict(schema_version=1, role='simion_downstream_field_worker', status='failed',
        spatial_identity=spatial_identity, native_operations=observations, native_count=0,
        refine_calls=0, reused=reuse_assets is not None)
    primary = None
    logs.mkdir(parents=True, exist_ok=False)
    try:
        if reuse_assets is not None:
            if reuse_identity != spatial_identity or set(reuse_assets) != {'flight_tube','reflectron','detector'}:
                raise ValueError('downstream reuse differs from its exact spatial identity')
            verify_record('reused downstream native audit', reuse_audit_record)
            audit = json.loads(Path(reuse_audit_record['path']).read_text(encoding='utf-8-sig'))
            if audit.get('status') != 'success' or {row['role'] for row in audit.get('checked_assets', [])} != set(reuse_assets):
                raise ValueError('reused downstream audit is not complete')
            assets = []
            expected_assets = {row['role']:row for row in asset_plan}
            for role, value in reuse_assets.items():
                family = [_owned_record(record, root) for record in value['family_records']]
                carrier = _owned_record(value['carrier_record'], root)
                if role == 'reflectron':
                    if family or not carrier['path'].lower().endswith('.pa'):
                        raise ValueError('reused reflectron must remain detached')
                elif len(family) != 4 or carrier not in family:
                    raise ValueError('reused native fractional family is incomplete')
                expected = expected_assets[role]
                if (Path(carrier['path']).resolve() != Path(expected['carrier_path']).resolve()
                        or {Path(row['path']).resolve() for row in family} !=
                           {Path(path).resolve() for path in expected['family_paths']}):
                    raise ValueError('reused downstream role differs from its actual native asset plan')
                for row in [carrier,*family]:
                    if copied.get(row['path']) != row:
                        raise ValueError('reused downstream member has no matching admitted copy record')
                assets.append(dict(role=role, carrier_record=carrier, family_records=family))
            report.update(status='success', assets=assets, audit_record=reuse_audit_record)
            return report
        for path, content in plan.materializations.items():
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(content)
        for operation in plan.operations:
            arguments = [str(resources[Path(value).name]) if Path(value).name in resources else value
                         for value in operation['arguments']]
            actual = dict(operation, arguments=arguments)
            _native_operation(context, actual, executable=context.tools['simion'], run_directory=root,
                directory=work, logs=logs, limits=limits, observations=observations,
                allow_asynchronous_io=allow_asynchronous_io)
        audit_path = Path(plan.operations[-1]['outputs'][0])
        audit = json.loads(audit_path.read_text(encoding='utf-8-sig'))
        if audit.get('status') != 'success' or {row['role'] for row in audit.get('checked_assets', [])} != {'flight_tube','reflectron','detector'}:
            raise ValueError('downstream native audit did not check all three roles')
        assets = [dict(role=row['role'], carrier_record=file_record(Path(row['carrier_path']).resolve(), 'solver_native_binary'),
            family_records=[file_record(Path(path).resolve(), 'solver_native_binary') for path in row['family_paths']]) for row in asset_plan]
        report.update(status='success', assets=assets, audit_record=file_record(audit_path.resolve(), 'required_evidence'),
            refine_calls=sum(row['stage'] == 'pa_refine' for row in observations))
        return report
    except BaseException as failure:
        primary = failure
        report['exception'] = dict(type=type(failure).__name__, message=str(failure))
        raise
    finally:
        report['native_count'] = len(observations)
        try:
            write_json_atomic(Path(receipt_path), report)
        except BaseException as secondary:
            if primary is None:
                raise
            primary.add_note(f'Downstream receipt preservation failed: {secondary!r}')


def run_downstream(session, *, parameters: Mapping, limits: Mapping) -> dict:
    """Start the one declared downstream worker; RunSession owns its only host release."""
    operation = 'downstream_fields'
    parameters = dict(parameters)
    if set(parameters) & {'run_directory','log_directory','receipt_path','limits'}:
        raise ValueError('downstream caller cannot replace original owner paths')
    request = session.declare_file(session.input_dir/'downstream_fields.json', 'required_evidence')
    receipt = session.declare_file(session.result_dir/'downstream_fields.json', 'required_evidence')
    logs = session.log_dir/'downstream_fields'
    parameters.update(run_directory=str(session.artifact_run_dir), log_directory=str(session.canonical_path(logs)),
        receipt_path=str(session.canonical_path(receipt)), limits=dict(limits))
    parameters['resources'] = {name:str(path) for name,path in parameters['resources'].items()}
    parameters['working_directory'] = str(parameters['working_directory'])
    context = {name:str(getattr(session.context,name)) for name in ('workspace','python_executable',
        'powershell_executable','host_state_path','policy_path','execution_root')}
    context['tools'] = {name:str(path) for name,path in session.context.tools.items()}
    write_json_atomic(request, dict(schema_version=1, context=context, parameters=parameters))
    request_record = file_record(session.canonical_path(request), 'required_evidence')
    session.add_input('downstream_worker_request', request_record)
    try:
        session.run_process(operation, executable=session.context.python_executable,
            arguments=['-I','-B','-X','utf8','-m',__name__,str(request)], role='SIMION', stage='pa_refine', limits=limits)
    finally:
        for path in session.canonical_path(logs).rglob('*'):
            if path.is_file():
                session.declare_file(path, 'required_evidence')
    report = json.loads(Path(receipt).read_text(encoding='utf-8-sig'))
    if report.get('request') != request_record or report.get('status') != 'success':
        raise ValueError('downstream worker receipt differs from its frozen request or did not succeed')
    return report


def main() -> None:
    """Private installed request transport, never a second workflow owner."""
    if len(sys.argv) != 2:
        raise ValueError('downstream worker requires one frozen request')
    path = Path(sys.argv[1]).resolve(strict=True)
    with guarded_file_identity(path) as identity:
        request = json.loads(path.read_text(encoding='utf-8-sig'))
        if set(request) != {'schema_version','context','parameters'} or request['schema_version'] != 1:
            raise ValueError('downstream request fields differ')
        primary = None
        try:
            execute_downstream(ExecutionContext(**request['context']), **request['parameters'])
        except BaseException as failure:
            primary = failure
            raise
        finally:
            try:
                receipt = Path(request['parameters']['receipt_path'])
                report = json.loads(receipt.read_text(encoding='utf-8-sig'))
                report['request'] = dict(path=str(path), exists=True, bytes=identity.bytes_count,
                    sha256=identity.sha256, retention_role='required_evidence')
                write_json_atomic(receipt, report)
            except BaseException as secondary:
                if primary is None:
                    raise
                primary.add_note(f'Downstream request binding preservation failed: {secondary!r}')


if __name__ == '__main__':
    main()
