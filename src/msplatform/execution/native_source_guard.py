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
def guard_failed_store_evidence(store, manifest_record: Mapping[str, Any], selected_output: Mapping[str, Any]):
    """Hold one sealed failed stage and its exact stopped-worker evidence.

    Failed assets are not eligible for Store GC. This guard never promotes them
    to ready or treats the selected output as a successful result.
    """
    from msplatform.execution.owner import validate_writer_completion
    from msplatform.execution.host_resource_scheduler import _same_creation_time
    from msplatform.execution.native_artifact_controls import validate_native_completion
    manifest_record = validate_file_record(manifest_record, 'failed stage manifest')
    selected_output = validate_file_record(selected_output, 'failed stage output')
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
        hold(selected_output)
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if manifest.get('status') != 'failed' or manifest.get('outputs', []).count(selected_output) != 1:
            raise ValueError('selected output is not bound by the failed manifest')
        outputs = manifest['outputs']
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
        if (completion.get('status') != 'failed' or completion.get('run_id') != manifest.get('run_id')
                or summary.get('run_id') != manifest.get('run_id') or summary.get('writers_stopped') is not True
                or row[4] != str(completion.get('exception') or 'failed')):
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
                b.host_token,b.host_state_path,b.host_file_id FROM native_bindings b
                JOIN native_binding_controls c ON c.binding_id=b.id WHERE c.control_id=?''', (row[3][8:],)).fetchall()
        if any(item[1] != 'complete' for item in bindings) or {item['operation_id'] for item in operations} != {item[0] for item in bindings}:
            raise ValueError('failed stage native binding proof differs')
        for operation in operations:
            matching = [item for item in bindings if item[0] == operation['operation_id']]
            if len(matching) != 1 or not matching[0][4]:
                raise ValueError('failed stage native completion is unavailable')
            bound = matching[0]
            observation = operation['observation']
            if (observation['process_id'] != bound[2] or not _same_creation_time(
                    str(observation['process_started_at_utc_ticks']), str(bound[3]))):
                raise ValueError('failed stage native worker identity differs')
            proof = json.loads(bound[4])
            validate_native_completion({'operation_id': bound[0], 'worker_pid': bound[2], 'worker_started': bound[3],
                'host_token': bound[5], 'host_state_path': bound[6], 'host_file_id': json.loads(bound[7])}, proof)
            proof_operations = [item for item in proof.get('operations', []) if item.get('operation_id') == operation['operation_id']]
            if len(proof_operations) != 1 or proof_operations[0].get('observation') != observation:
                raise ValueError('failed stage native worker proof differs')
            release = next(item for item in writer['resource_releases'] if item['release_id'] == operation['resource_release_id'])
            proof_releases = [item for item in proof.get('resource_releases', [])
                              if item.get('release_id') == proof_operations[0].get('resource_release_id')]
            if (len(proof_releases) != 1 or proof_releases[0].get('completion_receipt', {}).get('host_release')
                    != release.get('completion_receipt', {}).get('host_release')):
                raise ValueError('failed stage host release proof differs')
        yield manifest


@contextmanager
def guard_native_source(reference: Mapping[str, Any], *, expected_kind: str,
                        expected_artifact_root: Path, artifact_store=None,
                        asset_ids: set[str] | None = None) -> Iterator[OpenedArtifact]:
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
    collected = set() if asset_ids is not None else None
    from msplatform.execution.owner import current_managed_native_store
    scope = current_managed_native_store()
    store = artifact_store if artifact_store is not None else (scope["store"] if scope else None)
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
            if (expected_kind == 'prepared_model' and product.get('metadata', {}).get('backend') == 'comsol'
                    and product.get('metadata', {}).get('scope') == 'assembly_electrostatic_unsolved'
                    and geometry_reference is None):
                raise ValueError('COMSOL Store model lacks its geometry source reference')
            if (expected_kind == 'field_solution' and product.get('metadata', {}).get('backend') == 'comsol'
                    and product.get('metadata', {}).get('scope') == 'single_stationary_workpoint'
                    and stationary_source is None):
                raise ValueError('COMSOL Store field lacks its source reference')
            borrowed = {}
            if origin_reference is not None:
                origin = stack.enter_context(guard_native_source(origin_reference, expected_kind="field_bundle",
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected))
                borrowed = {Path(origin.data_locations[name]).resolve(): (record["bytes"], str(record["sha256"]).upper())
                            for name, record in origin.data_records.items()}
            if geometry_reference is not None:
                if expected_kind != 'prepared_model':
                    raise ValueError('geometry source is only valid for a prepared model')
                stack.enter_context(guard_native_source(geometry_reference, expected_kind='geometry_artifact',
                    expected_artifact_root=expected_artifact_root, artifact_store=store, asset_ids=collected))
            stationary_origin = None
            if stationary_source is not None:
                if (expected_kind != 'field_solution' or not isinstance(stationary_source, dict)
                        or set(stationary_source) != {'reference', 'kind'}
                        or stationary_source['kind'] not in {'prepared_model', 'field_solution'}):
                    raise ValueError('stationary source identity differs')
                stationary_origin = stack.enter_context(guard_native_source(stationary_source['reference'],
                    expected_kind=stationary_source['kind'], expected_artifact_root=expected_artifact_root,
                    artifact_store=store, asset_ids=collected))
            if failed_source is not None:
                if (expected_kind != 'field_solution' or not isinstance(failed_source, dict)
                        or set(failed_source) != {'manifest', 'selected_output'}):
                    raise ValueError('failed source identity differs')
                stack.enter_context(guard_failed_store_evidence(store, failed_source['manifest'], failed_source['selected_output']))
                selected = validate_file_record(failed_source['selected_output'], 'failed source output')
                borrowed[record_path(selected).resolve(strict=True)] = (selected['bytes'], str(selected['sha256']).upper())
            artifact = open_artifact(reference, expected_kind=expected_kind)
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
        if artifact.metadata.get('backend') == 'comsol':
            scope_name = artifact.metadata.get('scope')
            if expected_kind == 'prepared_model' and scope_name == 'assembly_electrostatic_unsolved':
                linked = artifact.metadata.get('geometry_source_reference') or {
                    'manifest': artifact.data_records.get('geometry_manifest'), 'product_id': 'geometry'}
                stack.enter_context(guard_native_source(linked, expected_kind='geometry_artifact',
                    expected_artifact_root=raw_root, artifact_store=store, asset_ids=collected))
            elif expected_kind == 'field_solution' and scope_name == 'single_stationary_workpoint':
                linked = {'manifest': artifact.data_records.get('prepared_manifest'), 'product_id': 'model'}
                stack.enter_context(guard_native_source(linked, expected_kind='prepared_model',
                    expected_artifact_root=raw_root, artifact_store=store, asset_ids=collected))
        if asset_ids is not None:
            asset_ids.update(collected)
        yield artifact
