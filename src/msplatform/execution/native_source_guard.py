"""Protect a published native owner product during cross-stage consumption."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path, PurePosixPath
from typing import Any

from msplatform.execution.file_lock import shared_process_file_lock
from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import record_path, validate_file_record
from msplatform.results.artifacts import OpenedArtifact, open_artifact


class _HistoricalRun:
    def __init__(self, root, manifest, config, stack):
        self.root, self.manifest, self.config, self.stack = root, manifest, config, stack
        self.held = {}

    def _hold(self, record):
        record = validate_file_record(record, "historical run file")
        path = record_path(record, base_dir=self.root)
        if not path.is_relative_to(self.root):
            raise ValueError("historical run file escapes its run root")
        identity = (record["bytes"], str(record["sha256"]).upper())
        if path in self.held:
            if self.held[path] != identity:
                raise ValueError("historical run has conflicting file records")
        else:
            self.stack.enter_context(guarded_file_identity(path, expected_bytes=identity[0], expected_sha256=identity[1]))
            self.held[path] = identity
        return dict(record, path=str(path))

    def input(self, name: str):
        record = self.manifest.get("inputs", {}).get(name)
        declared = self.config.get("inputs", {}).get(name)
        if not isinstance(record, dict) or not isinstance(declared, str):
            raise ValueError("historical input is not declared")
        if record_path(record, base_dir=self.root) != record_path({"path": declared}, base_dir=self.root):
            raise ValueError("historical input does not match run configuration")
        return self._hold(record)

    def output(self, relative: str):
        if not isinstance(relative, str) or not relative:
            raise ValueError("historical output path is required")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("historical output escapes its run root")
        matches = [item for item in self.manifest.get("outputs", [])
                   if isinstance(item, dict) and record_path(item, base_dir=self.root) == path]
        if len(matches) != 1:
            raise ValueError("historical output is missing or ambiguous")
        return self._hold(matches[0])


class _OaFailedHistoricalRun(_HistoricalRun):
    def output(self, relative: str):
        if Path(relative).suffix.lower() == '.mph':
            if self.manifest.get('mode') != 'design_candidate':
                raise ValueError('OA cold child cannot claim an original model')
            context_record = super().output(relative + '.postprocess.json')
            context = json.loads(Path(context_record['path']).read_text(encoding='utf-8-sig'))
            if (context.get('schema_version') != 1 or context.get('role') != 'oatof_saved_particle_solution'):
                raise ValueError('OA saved model context identity differs')
            save_state = context.get('model_save_state')
            if save_state is None:
                report = super().output('logs/comsol_build.txt')
                if ('STATUS=PASS' not in Path(report['path']).read_text(encoding='utf-8-sig').splitlines()
                        or any(item['observation']['returncode'] != 0 for item in self.native_operations)):
                    raise ValueError('OA saved model lacks successful final-save evidence')
            elif save_state not in {'raw_complete', 'gui_update_complete'}:
                raise ValueError('OA saved model final-save state is unknown')
            record = super().output(relative)
            if context.get('saved_model_bytes') != record['bytes']:
                raise ValueError('OA saved model byte count differs from context')
            return record
        return super().output(relative)


@contextmanager
def guard_historical_run(manifest_record: Mapping[str, Any], *, expected_project: str, expected_mode: str):
    """Open one explicitly identified successful historical run without its old owner."""
    from msplatform.io.manifest_records import require_completed_terminal_publication
    record = validate_file_record(manifest_record, "historical run manifest")
    path = record_path(record)
    if not path.is_absolute() or path.name != "run_manifest.json":
        raise ValueError("historical run manifest identity differs")
    root = path.parent.resolve(strict=True)
    with ExitStack() as stack:
        stack.enter_context(guarded_file_identity(path, expected_bytes=record["bytes"], expected_sha256=record["sha256"]))
        require_completed_terminal_publication(path)
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(manifest, dict) or manifest.get("schema_version") not in (1, 2)
                or manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success"
                or manifest.get("project") != expected_project or manifest.get("mode") != expected_mode
                or manifest.get("run_id") != root.name):
            raise ValueError("historical run terminal identity differs")
        config_record = validate_file_record(manifest.get("run_config"), "historical run config")
        config_path = record_path(config_record, base_dir=root)
        if config_path != root / "run_config.json":
            raise ValueError("historical run configuration path differs")
        stack.enter_context(guarded_file_identity(config_path, expected_bytes=config_record["bytes"],
                                                   expected_sha256=config_record["sha256"]))
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if (config.get("run_id") != root.name or config.get("project") != expected_project
                or config.get("mode") != expected_mode):
            raise ValueError("historical run configuration identity differs")
        yield _HistoricalRun(root, manifest, config, stack)


@contextmanager
def _guard_historical_joint_writer(manifest_record: Mapping[str, Any], *, project: str, mode: str):
    """Hold one stopped historical run, never its old ledger.

    Every additional historical producer must be guarded independently; this
    context never infers a stopped writer from age or from a terminal label.
    """
    from msplatform.execution.owner import validate_writer_completion
    from msplatform.io.manifest_records import require_completed_terminal_publication
    record = validate_file_record(manifest_record, 'historical measured flight manifest')
    path = record_path(record)
    if not path.is_absolute() or path.name != 'run_manifest.json':
        raise ValueError('historical measured flight manifest identity differs')
    root = path.parent.resolve(strict=True)
    with ExitStack() as stack:
        stack.enter_context(guarded_file_identity(path, expected_bytes=record['bytes'], expected_sha256=record['sha256']))
        require_completed_terminal_publication(path)
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if (manifest.get('role') != 'simulation_run_manifest' or manifest.get('project') != project
                or manifest.get('mode') != mode or manifest.get('run_id') != root.name
                or manifest.get('status') not in {'success', 'failed'}):
            raise ValueError('historical measured flight identity differs')
        config_record = validate_file_record(manifest.get('run_config'), 'historical measured flight config')
        if record_path(config_record, base_dir=root) != root/'run_config.json':
            raise ValueError('historical measured flight config path differs')
        stack.enter_context(guarded_file_identity(root/'run_config.json', expected_bytes=config_record['bytes'],
                                                   expected_sha256=config_record['sha256']))
        config = json.loads((root/'run_config.json').read_text(encoding='utf-8-sig'))
        if (config.get('project') != project or config.get('mode') != mode
                or config.get('run_id') != root.name):
            raise ValueError('historical measured flight config differs')
        source = _HistoricalRun(root, manifest, config, stack)
        request_record = source.input('execution_request')
        request = json.loads(Path(request_record['path']).read_text(encoding='utf-8-sig'))
        package = request.get('package', {})
        if (request.get('role') != 'run_artifact_workflow_request' or request.get('schema_version') != 1
                or package.get('project') != project or package.get('mode') != mode
                or package.get('run_id') != root.name):
            raise ValueError('historical measured flight request differs')
        completion_record = source.output('results/execution_completion.json')
        completion = json.loads(Path(completion_record['path']).read_text(encoding='utf-8-sig'))
        def same(left, right):
            return all(left.get(key) == right.get(key) for key in ('path','exists','bytes','sha256'))
        if (completion.get('role') != 'run_artifact_workflow_completion' or completion.get('schema_version') != 1
                or completion.get('run_id') != root.name or completion.get('project') != project
                or completion.get('status') != manifest['status']
                or not same(completion.get('run_config', {}), config_record)
                or not same(completion.get('execution_request', {}), request_record)):
            raise ValueError('historical measured flight completion differs')
        summary_record = source.output('summary.json')
        summary = json.loads(Path(summary_record['path']).read_text(encoding='utf-8-sig'))
        if summary.get('status') != manifest['status'] or summary.get('writers_stopped') is not True:
            raise ValueError('historical measured flight writer stop is not confirmed')
        writer = completion.get('writer_completion', {})
        operations, releases = writer.get('operations'), writer.get('resource_releases')
        if not isinstance(operations, list) or not operations or not isinstance(releases, list):
            raise ValueError('historical measured flight writer evidence is unavailable')
        validate_writer_completion(writers_stopped=True, expected_operation_ids=tuple(x['operation_id'] for x in operations),
            operations=operations, resource_releases=releases, powershell_owner=True, require_process_identity=True)
        yield source


@contextmanager
def guard_historical_measured_flight(manifest_record: Mapping[str, Any]):
    """Protect a joint-flight source with its authenticated stopped writer."""
    with _guard_historical_joint_writer(manifest_record, project="instrument_assembly", mode="prepared_joint") as source:
        yield source


@contextmanager
def guard_historical_joint_component(manifest_record: Mapping[str, Any]):
    """Protect the explicitly supported IP native-electrode component source."""
    with _guard_historical_joint_writer(manifest_record, project="dual_pressure_rectilinear_ion_processor",
                                        mode="native_electrode_functional") as source:
        yield source


@contextmanager
def guard_oa_failed_historical_run(manifest_record: Mapping[str, Any]):
    """Protect a stopped historical OA Candidate or its COMSOL cold child.

    This is a read-only evidence guard, not a successful owner or scientific
    qualification. Callers hold each actually consumed input/output until done.
    """
    from msplatform.execution.owner import validate_writer_completion
    from msplatform.io.manifest_records import require_completed_terminal_publication
    record = validate_file_record(manifest_record, 'OA historical manifest')
    path = record_path(record)
    if not path.is_absolute() or path.name != 'run_manifest.json':
        raise ValueError('OA historical manifest identity differs')
    root = path.parent.resolve(strict=True)
    with ExitStack() as stack:
        stack.enter_context(guarded_file_identity(path, expected_bytes=record['bytes'], expected_sha256=record['sha256']))
        require_completed_terminal_publication(path)
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        project = 'single_reflection_oa_tof_mass_analyzer'
        mode = manifest.get('mode')
        if (manifest.get('role') != 'simulation_run_manifest' or manifest.get('status') != 'failed'
                or manifest.get('project') != project or mode not in {'design_candidate', 'candidate_comsol_postprocess'}
                or manifest.get('run_id') != root.name):
            raise ValueError('OA historical failed owner identity differs')
        config_record = validate_file_record(manifest.get('run_config'), 'OA historical run config')
        if record_path(config_record, base_dir=root) != root/'run_config.json':
            raise ValueError('OA historical config path differs')
        stack.enter_context(guarded_file_identity(root/'run_config.json', expected_bytes=config_record['bytes'],
                                                   expected_sha256=config_record['sha256']))
        config = json.loads((root/'run_config.json').read_text(encoding='utf-8-sig'))
        if config.get('run_id') != root.name or config.get('project') != project or config.get('mode') != mode:
            raise ValueError('OA historical run config identity differs')
        source = _OaFailedHistoricalRun(root, manifest, config, stack)
        request_record = source.input('execution_request')
        request = json.loads(Path(request_record['path']).read_text(encoding='utf-8-sig'))
        package = request.get('package', {})
        if (request.get('schema_version') != 1 or request.get('role') != 'run_artifact_workflow_request'
                or package.get('run_id') != root.name or package.get('project') != project or package.get('mode') != mode):
            raise ValueError('OA historical execution request identity differs')
        completion_record = source.output('results/execution_completion.json')
        completion = json.loads(Path(completion_record['path']).read_text(encoding='utf-8-sig'))
        def same(left, right):
            return all(left.get(key) == right.get(key) for key in ('path', 'bytes', 'sha256', 'exists'))
        if (completion.get('schema_version') != 1 or completion.get('role') != 'run_artifact_workflow_completion'
                or completion.get('run_id') != root.name or completion.get('project') != project
                or completion.get('status') != 'failed' or not same(completion.get('execution_request', {}), request_record)
                or not same(completion.get('run_config', {}), config_record)):
            raise ValueError('OA historical public completion differs')
        writer = completion['writer_completion']
        validate_writer_completion(writers_stopped=True, expected_operation_ids=tuple(x['operation_id'] for x in writer['operations']),
            operations=writer['operations'], resource_releases=writer['resource_releases'],
            powershell_owner=True, require_process_identity=False)
        receipt_name = 'comsol_build_completion.json' if mode == 'design_candidate' else 'cold_postprocess_completion.json'
        native_record = source.output('logs/'+receipt_name)
        native = json.loads(Path(native_record['path']).read_text(encoding='utf-8-sig'))
        if (native.get('schema_version') != 1 or native.get('role') != 'comsol_launcher_completion'
                or native.get('run_id') != root.name or not isinstance(native.get('operations'), list)
                or not native['operations']):
            raise ValueError('OA historical native completion differs')
        release_id = Path(receipt_name).stem
        operations = [{'operation_id': release_id+'.'+item['operation_id'],
            'observation': item['observation'], 'resource_release_id': release_id} for item in native['operations']]
        releases = [{'release_id': release_id, 'completion_receipt': native}]
        validate_writer_completion(writers_stopped=True, expected_operation_ids=tuple(x['operation_id'] for x in operations),
            operations=operations, resource_releases=releases, powershell_owner=True, require_process_identity=True)
        for item in operations:
            matching = [entry for entry in writer['operations'] if entry['operation_id'] == item['operation_id']]
            if (len(matching) != 1 or matching[0]['resource_release_id'] != release_id
                    or any(matching[0]['observation'].get(key) != item['observation'].get(key)
                           for key in ('exit_confirmed','returncode'))
                    or any(key in matching[0]['observation'] and matching[0]['observation'][key] != item['observation'].get(key)
                           for key in ('process_id','process_started_at_utc_ticks'))):
                raise ValueError('OA historical native operation is not bound by public completion')
        if releases[0] not in writer['resource_releases']:
            raise ValueError('OA historical native host release is not bound by public completion')
        source.native_operations = operations
        yield source


@contextmanager
def guard_formal_v1(manifest_record: Mapping[str, Any], *, project_id: str,
                    artifact_project_root: Path, include_all: bool = False,
                    asset_roles: tuple[str, ...] | None = None):
    """Hold the exact frozen v1 SIMION bundle without a legacy owner or writes.

    Callers supply the manifest's own bytes/SHA record and must keep this
    context open through copying and verification. A missing or changed file
    fails closed; all OS handles exclude writes and deletion on Windows.
    """
    if (not isinstance(project_id, str) or not project_id or type(include_all) is not bool
            or (asset_roles is not None and (include_all or not isinstance(asset_roles, tuple)
                or not asset_roles or any(not isinstance(role, str) or not role for role in asset_roles)
                or len(set(asset_roles)) != len(asset_roles)))):
        raise ValueError("historical project identity and selection are required")
    project_root = Path(artifact_project_root)
    if not project_root.is_absolute():
        raise ValueError("historical project root must be absolute")
    formal_root = (project_root / "formal").resolve(strict=True)
    manifest_record = validate_file_record(manifest_record, "historical asset manifest")
    manifest_path = record_path(manifest_record)
    if manifest_path != formal_root / "asset_manifest.json":
        raise ValueError("historical asset manifest path differs")
    with ExitStack() as stack:
        stack.enter_context(guarded_file_identity(manifest_path, expected_bytes=manifest_record["bytes"],
                                                   expected_sha256=manifest_record["sha256"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
                or manifest.get("role") != "formal_asset_manifest" or manifest.get("project") != project_id
                or not isinstance(manifest.get("assets"), dict)):
            raise ValueError("historical asset manifest identity differs")
        if asset_roles is not None and not set(asset_roles) <= set(manifest["assets"]):
            raise ValueError("selected historical asset role is unavailable")
        paths, guarded = {}, {}
        for role, record in manifest["assets"].items():
            if not isinstance(role, str) or not role or not isinstance(record, dict):
                raise ValueError("historical asset record differs")
            name = record.get("path")
            if not isinstance(name, str):
                raise ValueError("historical asset path is unavailable")
            if asset_roles is not None and role not in asset_roles:
                continue
            if asset_roles is None and not include_all and not name.startswith("simion/"):
                continue
            relative = PurePosixPath(name)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name
                    or len(relative.parts) < 2 or relative.parts[0] not in {"simion", "comsol", "cad", "results"}):
                raise ValueError("unsafe historical asset path")
            actual = (formal_root / Path(*relative.parts)).resolve(strict=True)
            if not actual.is_relative_to(formal_root / relative.parts[0]):
                raise ValueError("historical asset escapes its source root")
            expected = (record.get("bytes"), str(record.get("sha256", "")).upper())
            if actual in guarded:
                if guarded[actual] != expected:
                    raise ValueError("historical source has conflicting records")
            else:
                stack.enter_context(guarded_file_identity(actual, expected_bytes=expected[0], expected_sha256=expected[1]))
                guarded[actual] = expected
            paths[role] = actual
        if not paths:
            raise ValueError("historical manifest has no selected assets")
        yield manifest, paths


@contextmanager
def guard_stopped_store_evidence(store, manifest_record: Mapping[str, Any]):
    """Hold stopped failed/interrupted evidence and dynamically selected manifest records.

    Failed assets are not eligible for Store GC. This guard never promotes them
    to ready or treats its output as a successful result. The yielded selector
    accepts only exact manifest-bound inputs/outputs and holds them until exit.
    """
    from msplatform.execution.owner import validate_writer_completion
    from msplatform.execution.native_artifact_controls import validate_native_completion, validate_native_group_completion
    manifest_record = validate_file_record(manifest_record, 'failed stage manifest')
    path = record_path(manifest_record).resolve(strict=True)
    if not path.is_relative_to(store.root / 'assets' / 'native_stage') or path.name != 'run_manifest.json':
        raise ValueError('failed evidence is not a Store native stage')
    parts = path.relative_to(store.root).parts
    if len(parts) < 6:
        raise ValueError('failed Store stage path differs')
    with store._db() as db:
        row = db.execute('SELECT path,state,records,work,failure FROM assets WHERE id=?', (parts[3],)).fetchone()
    if row is None or row[1] != 'failed' or not row[3].startswith('inplace:') or not row[4]:
        raise ValueError('failed Store stage is not sealed evidence')
    asset = store.root / row[0]
    if asset != store.root.joinpath(*parts[:4]):
        raise ValueError('failed Store stage identity differs')
    sealed = json.loads(row[2])
    with ExitStack() as stack:
        held = set()
        def hold(record):
            value = validate_file_record(record, 'failed stage evidence')
            item = record_path(value).resolve(strict=True)
            if not item.is_relative_to(asset):
                raise ValueError('failed evidence escapes its Store stage')
            known = sealed.get(item.relative_to(asset).as_posix())
            if (not known or known['bytes'] != value['bytes']
                    or known['sha256'].upper() != value['sha256'].upper()):
                raise ValueError('failed evidence differs from its sealed identity')
            if item not in held:
                stack.enter_context(guarded_file_identity(item, expected_bytes=value['bytes'], expected_sha256=value['sha256']))
                held.add(item)
            return item
        hold(manifest_record)
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        status = manifest.get('status')
        if status not in {'failed', 'interrupted'}:
            raise ValueError('Store stage is not a stopped failed or interrupted terminal')
        outputs = manifest['outputs']
        inputs = manifest.get('inputs', {})
        if not isinstance(outputs, list) or not isinstance(inputs, dict):
            raise ValueError('stopped stage manifest records differ')
        def hold_records(records):
            if not isinstance(records, (list, tuple)) or not records:
                raise ValueError('explicit stopped-stage records are required')
            for record in records:
                if outputs.count(record) + list(inputs.values()).count(record) != 1:
                    raise ValueError('selected record is not uniquely bound by the stopped manifest')
                hold(record)
        for record in manifest.get('inputs', {}).values():
            if isinstance(record, dict) and isinstance(record.get('path'), str):
                item = record_path(record)
                if item.is_absolute() and item.resolve().is_relative_to(asset):
                    hold(record)
        def output(name):
            matches = [record for record in outputs if Path(record['path']).name == name]
            if len(matches) != 1:
                raise ValueError('failed stage lacks unique ' + name)
            return json.loads(hold(matches[0]).read_text(encoding='utf-8-sig'))
        completion = output('execution_completion.json')
        summary = output('summary.json')
        if (completion.get('status') != status or completion.get('run_id') != manifest.get('run_id')
                or summary.get('run_id') != manifest.get('run_id') or summary.get('writers_stopped') is not True
                or row[4] != str(completion.get('exception') or status)):
            raise ValueError('failed stage writer completion differs')
        writer = completion['writer_completion']
        operations = writer['operations']
        if not operations:
            raise ValueError('failed stage lacks an observed native operation')
        validate_writer_completion(writers_stopped=summary['writers_stopped'],
            expected_operation_ids=tuple(item['operation_id'] for item in operations),
            operations=operations, resource_releases=writer['resource_releases'])
        with store._db() as db:
            bindings = db.execute('''SELECT b.operation_id,b.state,b.worker_pid,b.worker_started,b.completion,
                b.host_token,b.host_state_path,b.host_file_id,b.id FROM native_bindings b
                JOIN native_binding_controls c ON c.binding_id=b.id WHERE c.control_id=?''', (row[3][8:],)).fetchall()
        if any(item[1] != 'complete' or not item[4] for item in bindings):
            raise ValueError('failed stage native binding proof differs')
        proven = {}
        for bound in bindings:
            proof = json.loads(bound[4])
            if bound[0] == 'group':
                with store._db() as db:
                    members = db.execute('SELECT operation_id,worker_pid,worker_started FROM native_group_workers WHERE binding_id=?', (bound[8],)).fetchall()
                    attempts = db.execute('SELECT operation_id,attempt,worker_pid,worker_started FROM native_group_attempts WHERE binding_id=?', (bound[8],)).fetchall()
                validate_native_group_completion(host_token=bound[5],host_state_path=bound[6],
                    host_file_id=json.loads(bound[7]),members=members,attempts=attempts,completion=proof)
                by_name = {}
                for item in proof['operations']:
                    if item['operation_id'] not in by_name or item['attempt'] > by_name[item['operation_id']]['attempt']:
                        by_name[item['operation_id']] = item
                selected = list(by_name.values())
            else:
                validate_native_completion({'operation_id': bound[0], 'worker_pid': bound[2], 'worker_started': bound[3],
                    'host_token': bound[5], 'host_state_path': bound[6], 'host_file_id': json.loads(bound[7])}, proof)
                selected = proof['operations']
            for item in selected:
                name = item['operation_id']
                if name in proven:
                    raise ValueError('failed stage native operation has multiple bindings')
                proven[name] = (item, proof)
        if {item['operation_id'] for item in operations} != set(proven):
            raise ValueError('failed stage native binding proof differs')
        for operation in operations:
            proof_operation, proof = proven[operation['operation_id']]
            observation = operation['observation']
            if proof_operation.get('observation') != observation:
                raise ValueError('failed stage native worker proof differs')
            release = next(item for item in writer['resource_releases'] if item['release_id'] == operation['resource_release_id'])
            proof_releases = [item for item in proof.get('resource_releases', [])
                              if item.get('release_id') == proof_operation.get('resource_release_id')]
            if (len(proof_releases) != 1 or proof_releases[0].get('completion_receipt', {}).get('host_release')
                    != release.get('completion_receipt', {}).get('host_release')):
                raise ValueError('failed stage host release proof differs')
        yield manifest, hold_records


@contextmanager
def guard_failed_store_evidence(store, manifest_record: Mapping[str, Any], selected_output: Mapping[str, Any]):
    """Hold one sealed failed stage and its selected manifest-bound output."""
    with guard_stopped_store_evidence(store, manifest_record) as (manifest, hold_records):
        if manifest['status'] != 'failed' or manifest['outputs'].count(selected_output) != 1:
            raise ValueError('selected output is not bound by the failed manifest')
        hold_records([selected_output])
        yield manifest


@contextmanager
def guard_tracking_recovery(store, manifest_record: Mapping[str, Any], *, raw_root: Path,
                            asset_ids: set[str] | None = None):
    """Hold a complete trajectory or exact stopped-unit inputs for recovery."""
    manifest = json.loads(Path(manifest_record['path']).read_text(encoding='utf-8-sig'))
    with ExitStack() as stack:
        if manifest.get('status') in {'failed', 'interrupted'}:
            sealed, hold_records = stack.enter_context(guard_stopped_store_evidence(store, manifest_record))
        else:
            stack.enter_context(guard_native_source({'manifest': manifest_record, 'product_id': 'trajectory'},
                expected_kind='trajectory_result', expected_artifact_root=raw_root,
                artifact_store=store, asset_ids=asset_ids))
            sealed = json.loads(Path(manifest_record['path']).read_text(encoding='utf-8-sig'))
            run_root = Path(manifest_record['path']).resolve(strict=True).parent
            bound = [*sealed.get('inputs', {}).values(), *sealed.get('outputs', [])]
            held = set()
            def hold_records(records):
                if not isinstance(records, (list, tuple)) or not records:
                    raise ValueError('explicit tracking records are required')
                for record in records:
                    input_count = sum(row == record for row in sealed.get('inputs', {}).values())
                    output_count = sum(row == record for row in sealed.get('outputs', []))
                    if (input_count, output_count) not in {(1, 0), (0, 1), (1, 1)}:
                        raise ValueError('tracking record must be bound once or shared by one input and one output')
                    value = validate_file_record(record, 'tracking predecessor evidence')
                    path = record_path(value, base_dir=run_root).resolve(strict=True)
                    if not path.is_relative_to(run_root):
                        raise ValueError('tracking predecessor external input requires its own source guard')
                    identity = (value['bytes'], value['sha256'].upper(), value.get('retention_role'))
                    for candidate in bound:
                        if not isinstance(candidate, Mapping) or not isinstance(candidate.get('path'), str):
                            continue
                        if record_path({'path': candidate['path']}, base_dir=run_root) != path:
                            continue
                        candidate = validate_file_record(candidate, 'tracking predecessor evidence')
                        candidate_identity = (candidate['bytes'], candidate['sha256'].upper(),
                                              candidate.get('retention_role'))
                        if candidate_identity != identity:
                            raise ValueError('tracking record path has conflicting file identity')
                    if path not in held:
                        stack.enter_context(guarded_file_identity(path, expected_bytes=value['bytes'],
                                                                   expected_sha256=value['sha256']))
                        held.add(path)
        records = [*sealed.get('inputs', {}).values(), *sealed.get('outputs', [])]
        indices = [row for row in records if isinstance(row, dict) and isinstance(row.get('path'), str)
                   and Path(row['path']).name == 'tracking_units.json' and Path(row['path']).parent.name == 'logs']
        if len(indices) != 1:
            raise ValueError('stopped predecessor requires one manifest-bound tracking unit index')
        hold_records(indices)
        index = json.loads(Path(indices[0]['path']).read_text(encoding='utf-8-sig'))
        immutable, units = index.get('immutable_inputs'), index.get('units')
        if not isinstance(immutable, list) or not immutable or not isinstance(units, list):
            raise ValueError('stopped predecessor lacks its explicit unit input closure')
        needed = list(immutable)
        for row in units:
            if not isinstance(row, dict) or type(row.get('complete')) is not bool:
                raise ValueError('stopped predecessor has invalid unit completion facts')
            if row['complete']:
                needed.extend([row['stdout_record'], row['process_record']])
        hold_records(needed)
        yield


@contextmanager
def guard_native_source(reference: Mapping[str, Any], *, expected_kind: str,
                        expected_artifact_root: Path, artifact_store=None,
                        asset_ids: set[str] | None = None, _retain: bool = True) -> Iterator[OpenedArtifact]:
    """Verify and hold precisely the declared product files until consumption ends.

    Store products retain a verified claim. Historical sources are opened
    read-only using their frozen manifest and exact file handles, without a
    legacy ledger. Keep this context alive through downstream admission and
    reads; native children must hold their own immutable input guards.
    """
    if not isinstance(reference, Mapping) or set(reference) != {"manifest", "product_id"}:
        raise ValueError("native source requires an explicit manifest reference and product_id")
    if asset_ids is not None and not isinstance(asset_ids, set):
        raise ValueError('native source asset collector must be a set')
    from msplatform.execution.owner import current_managed_native_store
    scope = current_managed_native_store()
    retain = bool(_retain and scope and scope["retain_source_assets"])
    collected = set() if asset_ids is not None or retain else None
    store = artifact_store if artifact_store is not None else (scope["store"] if scope else None)
    if retain and store is not scope['store']:
        raise ValueError('native source must use the retaining parent Store')
    candidate = record_path(validate_file_record(reference["manifest"], "native source manifest"))
    if store is not None and candidate.is_absolute() and candidate.resolve().is_relative_to(store.root / "assets"):
        resolved = candidate.resolve(strict=True)
        parts = resolved.relative_to(store.root).parts
        if len(parts) < 6 or parts[:2] != ("assets", "native_stage") or resolved.name != "run_manifest.json":
            raise ValueError("native Store source path differs")
        identity = parts[3]
        with ExitStack() as stack:
            asset_root = stack.enter_context(store.claim_verified(identity))
            if asset_root != store.root.joinpath(*parts[:4]) or not resolved.is_relative_to(asset_root):
                raise ValueError("native Store source identity differs")
            if collected is not None:
                collected.add(identity)
            stack.enter_context(shared_process_file_lock(resolved.parent / TERMINAL_LOCK_NAME))
            manifest = json.loads(resolved.read_text(encoding="utf-8-sig"))
            product = manifest.get("products", {}).get(reference["product_id"], {})
            origin_reference = product.get("metadata", {}).get("ground_source_reference")
            geometry_reference = product.get("metadata", {}).get("geometry_source_reference")
            stationary_source = product.get('metadata', {}).get('stationary_source')
            failed_source = product.get('metadata', {}).get('failed_source')
            scalar_original = product.get('metadata', {}).get('original_samples_reference')
            family_reference = product.get('metadata', {}).get('family_producer_reference')
            operating_reference = product.get('metadata', {}).get('operating_producer_reference')
            collision_reference = product.get('metadata', {}).get('collision_producer_reference')
            if (expected_kind == 'scalar_field_samples'
                    and product.get('metadata', {}).get('derivation') == 'offline_from_published_raw_samples'
                    and scalar_original is None):
                raise ValueError('derived scalar samples lack original source reference')
            if (expected_kind == 'prepared_model' and product.get('metadata', {}).get('backend') == 'comsol'
                    and product.get('metadata', {}).get('scope') == 'assembly_electrostatic_unsolved'
                    and geometry_reference is None):
                raise ValueError('COMSOL Store model lacks its geometry source reference')
            if (expected_kind == 'field_solution' and product.get('metadata', {}).get('backend') == 'comsol'
                    and product.get('metadata', {}).get('scope') == 'single_stationary_workpoint'
                    and stationary_source is None):
                raise ValueError('COMSOL Store field lacks its source reference')
            borrowed = {}
            if (family_reference is not None
                    and product.get('metadata', {}).get('field_representation') == 'producer_owned_dual_cone_fractional_family'):
                from msplatform.backends.simion.dual_cone_stages import require_fields_product
                family = stack.enter_context(guard_native_source(family_reference, expected_kind='field_bundle',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                _, producer = require_fields_product(reference)
                for name, record in producer.data_records.items():
                    borrowed[Path(producer.data_locations[name]).resolve()] = (
                        record['bytes'], str(record['sha256']).upper())
            if family_reference is not None and expected_kind == 'trajectory_result':
                family = stack.enter_context(guard_native_source(family_reference, expected_kind='field_bundle',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                for name, record in family.data_records.items():
                    borrowed[Path(family.data_locations[name]).resolve()] = (
                        record['bytes'], str(record['sha256']).upper())
            if (family_reference is not None and expected_kind != 'trajectory_result'
                    and product.get('metadata', {}).get('field_representation') != 'producer_owned_dual_cone_fractional_family'):
                metadata = product.get('metadata', {})
                if (expected_kind != 'field_bundle' or metadata.get('backend') != 'simion'
                        or metadata.get('field_representation') not in {
                            'producer_owned_rf_fractional_family', 'producer_owned_rf_ip_fractional_family',
                            'producer_owned_oa_fractional_family', 'producer_owned_oa_mirror_empty_surface_family'}):
                    raise ValueError('RF family producer identity differs')
                family = stack.enter_context(guard_native_source(family_reference, expected_kind='field_bundle',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                original_meta = family.metadata
                bindings = metadata.get('native_assets')
                if ('family_producer_reference' in original_meta or not isinstance(bindings, dict)
                        or not bindings or bindings != original_meta.get('native_assets')
                        or original_meta.get('backend') != 'simion'
                        or original_meta.get('field_status') != 'available'
                        or metadata.get('field_status') != 'available'
                        or metadata.get('field_representation') != original_meta.get('field_representation')
                        or metadata.get('spatial_identity') != original_meta.get('spatial_identity')):
                    raise ValueError('RF family producer closure differs')
                keys = {'field_native_receipts'}
                mirror = metadata.get('field_representation') == 'producer_owned_oa_mirror_empty_surface_family'
                for row in bindings.values():
                    if (not isinstance(row, dict) or set(row) != ({'carrier', 'family', 'surface_witnesses', 'surface_state'} if mirror else {'carrier', 'family', 'surface_witnesses'})
                            or not isinstance(row['family'], list) or not row['family']
                            or any(not isinstance(key, str) or not key for key in row['family'])
                            or not isinstance(row['carrier'], str) or row['carrier'] not in row['family']
                            or not isinstance(row['surface_witnesses'], str)
                            or (mirror and (not isinstance(row['surface_state'], str) or not row['surface_state']))):
                        raise ValueError('RF family member binding differs')
                    keys.update(row['family'])
                    keys.add(row['surface_witnesses'])
                    if mirror:
                        keys.add(row['surface_state'])
                for key in keys:
                    record = product.get('data', {}).get(key)
                    original = family.data_records.get(key)
                    if record != original:
                        raise ValueError('RF borrowed family record differs from original producer')
                    borrowed[Path(family.data_locations[key]).resolve()] = (record['bytes'], str(record['sha256']).upper())
                receipts = json.loads(family.data_path('field_native_receipts').read_text(encoding='utf-8'))
                expected = {'refine_' + name for name in bindings}
                if (not isinstance(receipts, list) or len(receipts) != len(expected)
                        or {row.get('operation_id') for row in receipts if isinstance(row, dict)} != expected
                        or any(not isinstance(row, dict) or row.get('observation', {}).get('exit_confirmed') is not True
                            or row['observation'].get('returncode') != 0
                            or type(row['observation'].get('process_id')) is not int or row['observation']['process_id'] <= 0
                            or type(row['observation'].get('process_started_at_utc_ticks')) is not int
                            or row['observation']['process_started_at_utc_ticks'] <= 0 for row in receipts)):
                    raise ValueError('RF original family lacks successful Refine receipts')
            if operating_reference is not None:
                from msplatform.backends.simion.rf_field_execution import require_static_world_reuse
                document = json.loads(Path(product['data']['compiled_model']['path']).read_text(encoding='utf-8-sig'))
                _, producer, _ = require_static_world_reuse(reference,
                    identity=product.get('metadata', {}).get('spatial_identity'), geometry=document['geometry']['frontend_geometry'])
                stack.enter_context(guard_native_source(operating_reference, expected_kind='field_bundle',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                borrowed.update({Path(producer.data_locations[name]).resolve(): (record['bytes'], str(record['sha256']).upper())
                                 for name, record in producer.data_records.items()})
            if collision_reference is not None:
                if expected_kind != 'field_bundle':
                    raise ValueError('collision producer is only valid for a field bundle')
                from msplatform.backends.simion.ip_mr_tracking_admission import _verify_original_collision_producer
                producer = stack.enter_context(guard_native_source(collision_reference, expected_kind='field_bundle',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                reused = open_artifact(reference, expected_kind=expected_kind)
                _verify_original_collision_producer(reused, producer.reference)
                borrowed.update({Path(producer.data_locations[name]).resolve(): (record['bytes'], str(record['sha256']).upper())
                                 for name, record in producer.data_records.items()})
            if origin_reference is not None:
                origin = stack.enter_context(guard_native_source(origin_reference, expected_kind="field_bundle",
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                borrowed = {Path(origin.data_locations[name]).resolve(): (record["bytes"], str(record["sha256"]).upper())
                            for name, record in origin.data_records.items()}
            if geometry_reference is not None:
                if expected_kind != 'prepared_model':
                    raise ValueError('geometry source is only valid for a prepared model')
                stack.enter_context(guard_native_source(geometry_reference, expected_kind='geometry_artifact',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
            if scalar_original is not None:
                if (expected_kind != 'scalar_field_samples'
                        or product.get('metadata', {}).get('derivation') != 'offline_from_published_raw_samples'):
                    raise ValueError('original scalar samples identity differs')
                original = stack.enter_context(guard_native_source(scalar_original, expected_kind='scalar_field_samples',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected, _retain=False))
                borrowed.update({Path(original.data_locations[name]).resolve(): (record['bytes'], str(record['sha256']).upper())
                                 for name, record in original.data_records.items()})
            elif (expected_kind == 'scalar_field_samples' and product.get('metadata', {}).get('backend') == 'comsol'
                    and product.get('metadata', {}).get('scope') == 'assembly_world_scalar_samples'):
                field_record = product.get('data', {}).get('field_solution_manifest')
                product_id = product.get('metadata', {}).get('field_solution_product_id')
                field = stack.enter_context(guard_native_source({'manifest': field_record, 'product_id': product_id},
                    expected_kind='field_solution', expected_artifact_root=expected_artifact_root,
                    artifact_store=store, asset_ids=collected, _retain=False))
                field_manifest_record = field.reference['manifest']
                borrowed[field.manifest_location.resolve()] = (field_manifest_record['bytes'], str(field_manifest_record['sha256']).upper())
            stationary_origin = None
            if stationary_source is not None:
                if (expected_kind != 'field_solution' or not isinstance(stationary_source, dict)
                        or set(stationary_source) != {'reference', 'kind'}
                        or stationary_source['kind'] not in {'prepared_model', 'field_solution'}):
                    raise ValueError('stationary source identity differs')
                stationary_origin = stack.enter_context(guard_native_source(stationary_source['reference'],
                    expected_kind=stationary_source['kind'], expected_artifact_root=expected_artifact_root,
                    artifact_store=store, asset_ids=collected, _retain=False))
            if failed_source is not None:
                if (expected_kind != 'field_solution' or not isinstance(failed_source, dict)
                        or set(failed_source) != {'manifest', 'selected_output'}):
                    raise ValueError('failed source identity differs')
                stack.enter_context(guard_failed_store_evidence(store, failed_source['manifest'], failed_source['selected_output']))
                selected = validate_file_record(failed_source['selected_output'], 'failed source output')
                borrowed[record_path(selected).resolve(strict=True)] = (selected['bytes'], str(selected['sha256']).upper())
            artifact = open_artifact(reference, expected_kind=expected_kind)
            if scalar_original is not None:
                from msplatform.results.scalar_sample_lineage import validate_original_sample_source
                validate_original_sample_source(artifact, original)
            if geometry_reference is not None:
                original = validate_file_record(geometry_reference['manifest'], 'geometry source manifest')
                local = validate_file_record(artifact.data_records.get('geometry_manifest'), 'frozen geometry manifest')
                if any(original[key] != local[key] for key in ('bytes', 'sha256')):
                    raise ValueError('frozen geometry manifest identity differs from its source')
            if stationary_origin is not None:
                prepared = (stationary_origin.reference['manifest'] if stationary_origin.kind == 'prepared_model'
                            else stationary_origin.data_records['prepared_manifest'])
                local = validate_file_record(artifact.data_records.get('prepared_manifest'), 'frozen prepared manifest')
                if any(prepared[key] != local[key] for key in ('bytes', 'sha256')):
                    raise ValueError('frozen prepared manifest identity differs from its source')
                if stationary_origin.kind == 'field_solution':
                    local_parent = validate_file_record(artifact.data_records.get('parent_field_manifest'), 'frozen parent field manifest')
                    if any(stationary_origin.reference['manifest'][key] != local_parent[key] for key in ('bytes', 'sha256')):
                        raise ValueError('frozen field manifest identity differs from its source')
            if failed_source is not None and artifact.data_records.get('model') != failed_source['selected_output']:
                raise ValueError('recovered field does not use the selected failed output')
            config_record = validate_file_record(manifest["run_config"], "native source run config")
            config_path = record_path(config_record, base_dir=resolved.parent)
            files = [(resolved, validate_file_record(reference["manifest"], "native source manifest")),
                     (config_path, config_record)]
            files.extend((artifact.data_locations[name], record) for name, record in artifact.data_records.items())
            guarded = {}
            for path, record in files:
                actual = Path(path).resolve(strict=True)
                identity_record = (record["bytes"], str(record["sha256"]).upper())
                if not actual.is_relative_to(asset_root):
                    if borrowed.get(actual) != identity_record:
                        raise ValueError("native Store product contains an unprotected external payload")
                    continue  # Exact origin guard already holds this file.
                if actual in guarded:
                    if guarded[actual] != identity_record:
                        raise ValueError("native source contains conflicting file identities")
                    continue
                stack.enter_context(guarded_file_identity(actual, expected_bytes=identity_record[0],
                                                           expected_sha256=identity_record[1]))
                guarded[actual] = identity_record
            if asset_ids is not None:
                asset_ids.update(collected)
            if retain:
                scope["required_source_assets"].update(collected)
            yield artifact
        return
    raw_root = Path(expected_artifact_root)
    if not raw_root.is_absolute():
        raise ValueError("native owner artifact root must be absolute")
    raw_root = raw_root.resolve(strict=True)
    manifest_record = validate_file_record(reference["manifest"], "native source manifest")
    manifest_path = record_path(manifest_record)
    if not manifest_path.is_absolute() or manifest_path.name != "run_manifest.json":
        raise ValueError("native source requires an absolute owner run manifest")
    manifest_path = manifest_path.resolve(strict=True)
    if not manifest_path.is_relative_to(raw_root):
        raise ValueError("native source manifest is outside the expected owner root")
    with ExitStack() as stack:
        # Freeze the manifest before resolving any paths. A concurrent legacy
        # deletion either loses this OS handle race or leaves a missing member;
        # neither case requires invoking the legacy ledger or creating a lock.
        stack.enter_context(guarded_file_identity(manifest_path, expected_bytes=manifest_record["bytes"],
                                                   expected_sha256=manifest_record["sha256"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        config_record = validate_file_record(manifest.get("run_config"), "native source run config")
        product = manifest.get("products", {}).get(reference["product_id"])
        if not isinstance(product, dict) or not isinstance(product.get("data"), dict):
            raise ValueError("native source product records are unavailable")
        files = [(record_path(config_record, base_dir=manifest_path.parent), config_record)]
        files.extend((record_path(validate_file_record(record, "native source data"), base_dir=manifest_path.parent), record)
                     for record in product["data"].values())
        guarded: dict[Path, tuple[int, str]] = {manifest_path: (manifest_record["bytes"], str(manifest_record["sha256"]).upper())}
        for path, record in files:
            actual = Path(path).resolve(strict=True)
            if not actual.is_relative_to(raw_root):
                raise ValueError("native source data is outside the expected owner root")
            identity = (record["bytes"], str(record["sha256"]).upper())
            if actual in guarded:
                if guarded[actual] != identity:
                    raise ValueError("native source contains conflicting file identities")
                continue
            stack.enter_context(guarded_file_identity(actual, expected_bytes=identity[0], expected_sha256=identity[1]))
            guarded[actual] = identity
        # Validate publication and manifest/product membership only after every
        # actual file is held; this opens no legacy owner or mutable ledger.
        artifact = open_artifact(reference, expected_kind=expected_kind)
        if (expected_kind == 'scalar_field_samples'
                and artifact.metadata.get('derivation') == 'offline_from_published_raw_samples'
                and artifact.metadata.get('original_samples_reference') is None):
            raise ValueError('derived scalar samples lack original source reference')
        if expected_kind == 'scalar_field_samples' and artifact.metadata.get('original_samples_reference') is not None:
            from msplatform.results.scalar_sample_lineage import validate_original_sample_source
            if artifact.metadata.get('derivation') != 'offline_from_published_raw_samples':
                raise ValueError('original scalar samples identity differs')
            original = stack.enter_context(guard_native_source(artifact.metadata['original_samples_reference'],
                expected_kind='scalar_field_samples', expected_artifact_root=raw_root, artifact_store=store, asset_ids=collected, _retain=False))
            validate_original_sample_source(artifact, original)
        if artifact.metadata.get('backend') == 'comsol':
            scope_name = artifact.metadata.get('scope')
            if expected_kind == 'prepared_model' and scope_name == 'assembly_electrostatic_unsolved':
                linked = artifact.metadata.get('geometry_source_reference') or {
                    'manifest': artifact.data_records.get('geometry_manifest'), 'product_id': 'geometry'}
                stack.enter_context(guard_native_source(linked, expected_kind='geometry_artifact',
                    expected_artifact_root=raw_root, artifact_store=store, asset_ids=collected, _retain=False))
            elif (expected_kind == 'field_solution' and scope_name == 'single_stationary_workpoint'
                    and artifact.data_records.get('prepared_manifest') is not None):
                linked = {'manifest': artifact.data_records['prepared_manifest'], 'product_id': 'model'}
                stack.enter_context(guard_native_source(linked, expected_kind='prepared_model',
                    expected_artifact_root=raw_root, artifact_store=store, asset_ids=collected, _retain=False))
        if asset_ids is not None:
            asset_ids.update(collected)
        if retain:
            scope["required_source_assets"].update(collected)
        yield artifact
