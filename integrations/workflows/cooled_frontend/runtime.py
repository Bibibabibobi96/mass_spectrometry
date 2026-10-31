"""Freeze cooled-field receipts and materialize scheduler-owned local flights."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import stat
from dataclasses import asdict
import shutil

from common.contracts.file_identity import file_sha256
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.simion.pa_family_cache import (
    advance_pa_family_cache_transaction, canonical_pa_family_cache_key,
    load_pa_family_cache_transaction, validate_pa_family_cache_generation,
)
from integrations.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION, _resolve_standalone_dynamic_field_bank,
)
from integrations.workflows.local_frontend import runtime as shared
from integrations.workflows.single_reflection_flight.field_plan import laplace_member_identity


FIELD_ROLE = "rf_oatof_cooled_frontend_field_stage"
_FIELD_PUBLICATION_PIN_REASON = (
    "Retained canonical standalone cooled frontend fields for saved workbenches and explicit field-source consumers; "
    "rebuildable from frozen inputs."
)
KINDS = ("carrier_off", "rf_differential_unit", "entry_close_delta", "release_delta", "pulse_delta", "inner_auxiliary_unit", "hp_common_unit")


def field_member_plans(run: Path, *, cache_root: Path | None = None, freeze: bool = True,
                       solver_identity: dict | None = None,
                       verified_gem_sha256: str | None = None) -> dict:
    """Freeze seven independent Laplace identities, never source/analysis bytes."""
    run = Path(run).resolve(strict=True)
    inputs = run / 'inputs'
    front = shared._load(inputs / 'frontend_contract.json')
    plan = shared._load(inputs / 'cooled_field_plan.json')
    if (plan['role'] != 'rf_oatof_cooled_frontend_laplace_endpoints'
            or plan['boundary_policy'] != 'explicit_zero_dirichlet_far_faces_not_mechanical_metal'
            or tuple(point['kind'] for point in plan['working_points']) != KINDS):
        raise ValueError('exact seven ordinary cooled working members required')
    if solver_identity is None:
        native = shared._load(inputs / 'native_discovery.json')
        solver_identity = dict(release='SIMION 2020', executable_bytes=native['bytes'],
            executable_sha256=native['sha256'], file_version=native['file_version'])
    elif set(solver_identity) != {'release','executable_bytes','executable_sha256','file_version'}:
        raise ValueError('complete original frozen solver identity required')
    repository = Path(__file__).resolve().parents[3]
    builders = {'operating_builder': repository / 'common/simion/build_dirichlet_patch_operating_pa.lua',
                'exporter': repository / 'common/simion/export_detached_standalone_pa.lua'}
    authority = dict(simion_identity=solver_identity,
        builder_identity={name: file_sha256(path) for name, path in builders.items()})
    dimensions, mesh, origin = front['dimensions'], front['cell_mm_xyz'], front['instance_origin_mm']
    bounds = {a+'_'+side: origin[a] + (0 if side == 'min' else (dimensions['n'+a]-1)*mesh[a])
              for a in 'xyz' for side in ('min', 'max')}
    gem = file_sha256(inputs / 'frontend.gem') if verified_gem_sha256 is None else verified_gem_sha256
    members = []
    identifiers = {str(i) for i in range(1,max(front['physical_electrode_ids'])+1)}
    if plan['physical_electrode_ids'] != front['physical_electrode_ids']:
        raise ValueError('field namespace differs from the actual frozen provider geometry')
    for point in plan['working_points']:
        if (set(point['electrode_voltages_v']) != identifiers
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in point['electrode_voltages_v'].values())
                or type(plan['refine_convergence_v']) not in (int,float)
                or not math.isfinite(plan['refine_convergence_v']) or plan['refine_convergence_v'] <= 0):
            raise ValueError('complete finite voltage namespace and positive explicit convergence required')
        physical = dict(point, kind='rf_reference' if point['kind'] == 'rf_differential_unit' else point['kind'])
        identity = dict(laplace_member_identity(dimensions=dimensions, bounds_mm=bounds, gem_sha256=gem,
            cell_mm_xyz=mesh, instance_origin_mm=origin, surface='none', boundary_policy=plan['boundary_policy'],
            point=physical, refine_convergence_v=plan['refine_convergence_v'], rf_reference_voltage_v=1.), **authority)
        identity_path = inputs / ('cooled_member_'+point['kind']+'_identity.json')
        if freeze:
            shared._json_once(identity_path, identity)
        members.append(dict(member_id=point['kind'], identity=identity,
            identity_path=str(identity_path), cache_key=canonical_pa_family_cache_key(identity),
            filenames=[point['output_basename']], working_points=[point]))
    root = cache_root if cache_root is not None else run.parents[3] / 'common/simion/pa_family_cache'
    return dict(cache_root=str(root), domains=[dict(domain_id='parent', boundary_policy=plan['boundary_policy'],
        grid=[dimensions['n'+a] for a in 'xyz']+[mesh[a] for a in 'xyz'], members=members)],
        verifier_path=str(Path(__file__).with_name('verify_cooled_fields.lua')))


def pulse_reuse_scale(requested: dict, source: dict) -> float | None:
    """Prove exact proportional boundary voltages for the same linear operator.

    No tolerance or current default repairs old evidence. Other members only
    reuse identical solves; only the explicitly linear pulse has a coefficient.
    """
    if requested == source:
        return 1.
    target, original = requested['working_points'], source['working_points']
    if (requested['boundary_policy'] != 'explicit_zero_dirichlet_far_faces_not_mechanical_metal'
            or len(target) != 1 or len(original) != 1 or target[0]['kind'] != 'pulse_delta'
            or original[0]['kind'] != 'pulse_delta'
            or target[0]['refine_convergence_v'] != original[0]['refine_convergence_v']
            or {k:v for k,v in requested.items() if k != 'working_points'}
                != {k:v for k,v in source.items() if k != 'working_points'}):
        return None
    values, previous = target[0]['electrode_voltages_v'], original[0]['electrode_voltages_v']
    if values.keys() != previous.keys():
        return None
    nonzero = next((key for key,value in previous.items() if value != 0), None)
    if nonzero is None:
        return 1. if all(value == 0 for value in values.values()) else None
    scale = values[nonzero]/previous[nonzero]
    if not math.isfinite(scale) or any(values[key] != scale*value for key,value in previous.items()):
        return None
    return scale


def field_cache_plan(run: Path, *, cache_root: Path | None = None) -> dict:
    """Plan the existing public transaction separately for each working member."""
    plan = field_member_plans(run, cache_root=cache_root)
    experiment = shared._load(Path(run)/'inputs/cooled_experiment.json')
    source = published_members(run)[0] if experiment['field_source'] is not None else {}
    for member in plan['domains'][0]['members']:
        member.update(cache_root=plan['cache_root'], verifier_path=plan['verifier_path'])
        candidate = source.get(member['member_id'])
        scale = pulse_reuse_scale(member['identity'],candidate['raw_identity']) if candidate is not None else None
        if scale is not None:
            member.update(frozen_field_source=candidate, field_scale=scale)
    return plan


def _legacy_member_identity(identity: dict, point: dict) -> dict:
    """Derive one physical solve only from the complete old frozen operator.

    This is a read-only schema2 projection, never a rewrite of its cache key or
    a new generation certificate. Unknown old fields are not silently dropped.
    """
    expected = {'geometry','gem','working_points','mesh','grid_phase','surface','boundary_policy',
                'rf_reference_voltage_v','simion_identity','builder_identity'}
    if (set(identity) != expected or set(identity['geometry']) != {'dimensions'}
            or set(identity['builder_identity']) != {'operating_point','standalone_export'}
            or set(point) != {'kind','output_basename','electrode_voltages_v','refine_convergence_v'}):
        raise ValueError('legacy cooled member lacks an exact frozen operator projection')
    dimensions, mesh, origin = identity['geometry']['dimensions'], identity['mesh'], identity['grid_phase']
    bounds = {a+'_'+side: origin[a] + (0 if side == 'min' else (dimensions['n'+a]-1)*mesh[a])
              for a in 'xyz' for side in ('min','max')}
    projected = laplace_member_identity(dimensions=dimensions, bounds_mm=bounds, gem_sha256=identity['gem'],
        cell_mm_xyz=mesh, instance_origin_mm=origin, surface=identity['surface'],
        boundary_policy=identity['boundary_policy'], point=point,
        refine_convergence_v=point['refine_convergence_v'], rf_reference_voltage_v=identity['rf_reference_voltage_v'])
    return dict(projected, simion_identity=identity['simion_identity'], builder_identity={
        'operating_builder':identity['builder_identity']['operating_point'],
        'exporter':identity['builder_identity']['standalone_export']})


def field_verification_spec(run: Path, directory: Path, *, member_id: str) -> Path:
    """Sample provider metal and real working voltages, without a basis model."""
    from integrations.runtime.frontend_field_plan import _bare_samples, sample_node
    from integrations.runtime.single_flight_electrode_contract import require_pa_plus_solution_model
    from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import contains_shape, shape_bounds

    run = Path(run)
    front = shared._load(run / "inputs/frontend_contract.json")
    plan = shared._load(run / "inputs/cooled_field_plan.json")
    _, samples = _bare_samples(front, require_pa_plus_solution_model(front["pa_plus_solution_model"]))
    conditioner = front["conditioner_contract"]
    pose = conditioner["native_to_mr"]
    # Provider CSG is only used to choose bounded audit nodes. It is never
    # redrawn or used as a second field/electrode authority.
    for electrode in conditioner["native_projection_fragment"]["electrodes"]:
        anchor = None
        for solid in electrode["solids"]:
            lower, upper = shape_bounds(solid)
            for fraction in (.5, .25, .75):
                point = [lo + fraction * (hi - lo) for lo, hi in zip(lower, upper)]
                gu, body = sample_node(point, pose["rotation"], pose["translation_mm"],
                                       front["instance_origin_mm"], front["cell_mm_xyz"], front["dimensions"])
                if contains_shape(solid, body) and not any(contains_shape(cut, body) for cut in electrode["cutouts"]):
                    anchor = gu
                    break
            if anchor is not None:
                break
        if anchor is None:
            raise ValueError(f"no represented metal audit node for conditioner electrode {electrode['name']}")
        samples.append(dict(label=electrode["name"], electrode_id=electrode["electrode_id"], gu=anchor))
    lines = ["cooled_working_field_verification_v1", "\t".join(map(str, ["grid", *[front["dimensions"]["n" + a] for a in "xyz"],
                       *[front["cell_mm_xyz"][a] for a in "xyz"]]))]
    selected = [point for point in plan["working_points"] if point['kind'] == member_id]
    if len(selected) != 1:
        raise ValueError('verification requires one exact declared working member')
    for point in selected:
        lines.append("\t".join(["field", point["kind"], str(directory / point["output_basename"])]))
        for sample in samples:
            voltage = point["electrode_voltages_v"][str(sample["electrode_id"])]
            lines.append("\t".join(map(str, ["metal", point["kind"], sample["label"], *sample["gu"], format(voltage, ".17g")])))
    path = run / "inputs" / ("cooled_field_"+member_id+"_verification.tsv")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def advance_field_cache(run: Path, plan: dict, verification_output: Path | None = None) -> dict:
    """Continue the original public transaction; never adopt it as a new owner."""
    run = Path(run).resolve(strict=True)
    transaction_path = Path(plan["cache_root"]) / ".transactions" / plan["cache_key"] / "transaction.json"
    transaction = load_pa_family_cache_transaction(plan["cache_root"], plan["cache_key"]) if transaction_path.exists() else None
    arguments = dict(published_pin_reason=transaction["published_pin_reason"] if transaction else _FIELD_PUBLICATION_PIN_REASON)
    if transaction is None:
        arguments.update(owner=str(run), producer_run_config=run / "run_config.json")
    elif transaction.get("producer"):
        producer_config = Path(transaction["producer"]["run_config_path"])
        producer = producer_config.parent.resolve(strict=True)
        if producer != run:
            manifest_path = producer / "run_manifest.json"
            require_completed_terminal_publication(manifest_path)
            manifest = shared._load(manifest_path)
            if manifest["status"] not in ("success", "failed"):
                raise ValueError("field transaction producer is not terminal")
            if _verified_small_record(manifest["run_config"]) != producer_config.resolve(strict=True):
                raise ValueError("field transaction producer config binding differs")
            identity_source = producer / 'inputs' / Path(plan['identity_path']).name
            if not any(_record_path(row, strict=False) == identity_source for row in manifest.get("inputs",{}).values()):
                raise ValueError("field transaction producer identity is not manifest-bound")
            # Creation-time config SHA is an audit record, not an immutable
            # config claim: the owner's normal finalization updates this file.
            for name, source in (("manifest", manifest_path), ("run_config", producer_config),
                                 ("identity", identity_source)):
                target = run / "inputs" / ("cooled_field_" + plan['member_id'] + "_producer_" + name + ".json")
                if not target.exists():
                    shutil.copyfile(source, target)
                if target.read_bytes() != source.read_bytes():
                    raise ValueError("frozen original field producer evidence changed")
            if shared._load(identity_source) != plan["identity"]:
                raise ValueError("original field producer scientific identity differs")
    if verification_output is not None:
        if transaction is None or transaction["status"] != "building" or not transaction["inventory_sha256"]:
            raise ValueError("field verification requires the public prepared inventory")
        arguments["verification_evidence"] = dict(
            schema_version=1, role="simion_pa_family_verification", status="pass",
            cache_key=plan["cache_key"], inventory_sha256=transaction["inventory_sha256"],
            solver_release="SIMION 2020", verifier_path=plan["verifier_path"],
            verifier_sha256=file_sha256(plan["verifier_path"]),
            verification_output_path=str(verification_output), verification_output_sha256=file_sha256(verification_output),
        )
    result = advance_pa_family_cache_transaction(plan["cache_root"], plan["identity"], plan["filenames"],
                                                recovery_policy="none", **arguments)
    return json.loads(json.dumps(asdict(result), default=str))


def _probe_owner(record: dict, workspace: Path) -> tuple[dict, Path]:
    path = _verified_small_record(record, workspace)
    require_completed_terminal_publication(path)
    owner = shared._load(path)
    if owner.get('status') not in ('success', 'failed'):
        raise ValueError('probe owner is not terminal')
    config = _verified_small_record(owner['run_config'], workspace)
    if config != path.parent / 'run_config.json':
        raise ValueError('probe owner configuration differs')
    return owner, path.parent


def _bound_probe_file(owner: dict, path: Path, workspace: Path, *, output: bool) -> dict:
    records = owner.get('outputs', []) if output else owner.get('inputs', {}).values()
    found = [row for row in records if isinstance(row, dict) and 'path' in row
             and _record_path(row, workspace, strict=False) == path.resolve()]
    if not found or any((row.get('bytes'), row.get('sha256')) !=
                        (found[0].get('bytes'), found[0].get('sha256')) for row in found):
        raise ValueError('probe file is not bound by its sealed original owner')
    _verified_small_record(found[0], workspace)
    return dict(found[0], path=str(path.resolve()))


def _probe_source(run: Path) -> tuple[dict, dict, Path]:
    source = shared._load(run / 'inputs/cooled_experiment.json')['field_source']
    if source is None:
        raise ValueError('no explicit sealed probe source')
    envelope = shared._load(_verified_small_record(source, run.parents[4]))
    if envelope.get('schema_version') != 1 or envelope.get('role') != 'rf_oatof_cooled_frontend_field_source':
        raise ValueError('explicit cooled field-source envelope required')
    record = envelope['source_owner_manifest_record']
    owner, root = _probe_owner(record, run.parents[4])
    design_path = root / 'results/cooled_field_design/voltage_design.json'
    design = shared._load(_verified_small_record(
        _bound_probe_file(owner, design_path, run.parents[4], output=True)))
    return design, record, root


def static_probe_source_references(run: Path) -> list[dict]:
    """Discover original CSV owners before the caller acquires their public guards."""
    run = Path(run).resolve(strict=True)
    try:
        design, immediate, _ = _probe_source(run)
    except (ValueError, KeyError, OSError, TypeError):
        return []
    references = {}
    for kind in KINDS:
        probe = design.get('native_probe_records', {}).get(kind)
        if probe is None:
            continue
        projection = design.get('response_projections', {}).get(kind, {})
        owner = projection.get('probe_owner_manifest_record', immediate)
        key = str(_record_path(owner, run.parents[4], strict=False))
        references.setdefault(key, dict(manifest_record=owner, protected_paths=[]))
        references[key]['protected_paths'].append(str(_record_path(probe, run.parents[4], strict=False)))
    return list(references.values())


def _raw_probe_member(row: dict) -> dict:
    """A raw generation identity: requested voltage scale is deliberately excluded."""
    keys = ('kind', 'cache_key', 'generation_sha256', 'bytes', 'sha256')
    result = {key: row[key] for key in keys}
    result.update(path=str(Path(row['path']).resolve()),
                  generation_directory=str(Path(row['generation_directory']).resolve()))
    return result


def _validate_probe_rows(path: Path, points: Path) -> int:
    import csv
    with points.open(encoding='utf-8-sig', newline='') as handle:
        expected = list(csv.DictReader(handle))
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ['name', 'x_mm', 'y_mm', 'z_mm', 'potential_v',
                                  'ex_v_per_mm', 'ey_v_per_mm', 'ez_v_per_mm']:
            raise ValueError('static probe columns differ')
        rows = list(reader)
    if not expected or len(rows) != len(expected):
        raise ValueError('static probe population differs from its frozen points')
    for actual, target in zip(rows, expected, strict=True):
        if actual['name'] != target['name'] or any(
                float(actual[axis+'_mm']) != float(target[axis+'_mm']) for axis in 'xyz'):
            raise ValueError('static probe point order or coordinates differ')
        if any(not math.isfinite(float(value)) for key, value in actual.items() if key != 'name'):
            raise ValueError('static probe contains unknown nonfinite values')
    return len(rows)


def validate_static_probe_reference(run: Path, kind: str, record: dict,
                                    owner_record: dict, member: dict) -> dict:
    """Validate one sealed raw measurement using small original-owner evidence only."""
    import re
    run = Path(run).resolve(strict=True)
    workspace = run.parents[4]
    owner, root = _probe_owner(owner_record, workspace)
    path = _record_path(record, workspace)
    if path != root / 'results/cooled_field_probe' / (kind+'.csv'):
        raise ValueError('static probe CSV is outside its actual original owner')
    bound = _bound_probe_file(owner, path, workspace, output=True)
    if not _same_identity(bound, record, workspace):
        raise ValueError('static probe record differs from its original output')
    profile_record = _bound_probe_file(owner, root/'inputs/cooled_field_design_profile.json', workspace, output=False)
    profile = shared._load(_verified_small_record(profile_record, workspace))
    if profile.get('native_executed') is not True or profile.get('fly_executed') is not False:
        raise ValueError('static probe lacks its real field-only producer profile')
    for key, name in (('probe_plan_record', 'cooled_probe_plan.json'),
                      ('probe_points_record', 'cooled_probe_points.csv')):
        original = profile[key]
        if _record_path(original, workspace) != root/'inputs'/name:
            raise ValueError('probe profile input is outside its original frozen owner')
        _bound_probe_file(owner, _record_path(original, workspace), workspace, output=False)
        current = file_record(run/'inputs'/name)
        if (original['bytes'], original['sha256']) != (current['bytes'], current['sha256']):
            raise ValueError('frozen static probe plan or points changed')
    sampler = file_record(Path(__file__).with_name('sample_field.lua'))
    candidates = [row for row in owner.get('inputs', {}).values() if isinstance(row, dict)
                  and str(row.get('path', '')).replace('\\', '/').endswith(
                      '/integrations/workflows/cooled_frontend/sample_field.lua')]
    if not candidates or any((row['bytes'], row['sha256']) !=
                             (sampler['bytes'], sampler['sha256']) for row in candidates):
        raise ValueError('original frozen static sampler differs or is unknown')
    for candidate in candidates:
        if not _record_path(candidate, workspace).is_relative_to(root/'inputs'):
            raise ValueError('static sampler was not frozen by its original owner')
        _verified_small_record(candidate, workspace)
    native_record = profile['native_discovery_record']
    _bound_probe_file(owner, _record_path(native_record, workspace), workspace, output=False)
    native = shared._load(_verified_small_record(native_record, workspace))
    identity = shared._load(_verified_small_record(member['cache_identity_record'], workspace))['simion_identity']
    if (native['bytes'], native['sha256'], native['file_version']) != (
            identity['executable_bytes'], identity['executable_sha256'], identity['file_version']):
        raise ValueError('static probe solver identity differs from its raw generation')
    design_record = _bound_probe_file(owner, root/'results/cooled_field_design/voltage_design.json', workspace, output=True)
    design = shared._load(_verified_small_record(design_record, workspace))
    projection = design['response_projections'][kind]
    if (_raw_probe_member(projection['source_member']) != _raw_probe_member(member)
            or not _same_identity(design['native_probe_records'][kind], record, workspace)
            or not _same_identity(projection['raw_probe_record'], record, workspace)):
        raise ValueError('static probe is not bound to the selected raw generation')
    count = _validate_probe_rows(path, run/'inputs/cooled_probe_points.csv')
    log_record = _bound_probe_file(owner, root/'logs'/('field_probe_'+kind+'.stdout.log'), workspace, output=True)
    lines = _verified_small_record(log_record, workspace).read_text(encoding='utf-8-sig').splitlines()
    if len([line for line in lines if re.fullmatch(r'COOLED_FIELD_PROBE=PASS samples='+str(count), line)]) != 1:
        raise ValueError('original successful static probe completion is missing')
    return bound


def static_probe_reuse_plan(run: Path) -> dict:
    """Choose reusable raw CSVs; insufficient legacy evidence only requests that probe."""
    run = Path(run).resolve(strict=True)
    result = dict(native_probe_records={}, probe_owner_manifest_records={}, missing_members=[], reuse_reasons={})
    try:
        design, immediate, _ = _probe_source(run)
    except (ValueError, KeyError, OSError, TypeError) as error:
        result['missing_members'] = list(KINDS)
        result['reuse_reasons'] = {kind: str(error) for kind in KINDS}
        return result
    members = {row['kind']: row for row in shared._load(run/'inputs/cooled_frontend_field_stage_receipt.json')['working_points']}
    for kind in KINDS:
        try:
            projection = design['response_projections'][kind]
            if _raw_probe_member(projection['source_member']) != _raw_probe_member(members[kind]):
                raise ValueError('selected raw member changed')
            owner = projection.get('probe_owner_manifest_record', immediate)
            record = validate_static_probe_reference(run, kind, design['native_probe_records'][kind], owner, members[kind])
            result['native_probe_records'][kind] = record
            result['probe_owner_manifest_records'][kind] = owner
        except (ValueError, KeyError, OSError, TypeError) as error:
            result['missing_members'].append(kind)
            result['reuse_reasons'][kind] = str(error)
    return result


def complete_static_probe_records(run: Path, selection: dict) -> dict:
    """Bind actual newly sampled outputs and retain reused original records verbatim."""
    run = Path(run).resolve(strict=True)
    records = dict(selection['native_probe_records'])
    for kind in selection['missing_members']:
        path = run/'results/cooled_field_probe'/(kind+'.csv')
        _validate_probe_rows(path, run/'inputs/cooled_probe_points.csv')
        records[kind] = file_record(path)
    if set(records) != set(KINDS):
        raise ValueError('complete seven-member static probe evidence required')
    return dict(native_probe_records=records,
                probe_owner_manifest_records=selection['probe_owner_manifest_records'])


def static_probe_analysis_records(run: Path, members: list[dict]) -> dict:
    """Actual analyzer consumer: originals need their sealed owner, never path-only trust."""
    run = Path(run).resolve(strict=True)
    costs_path = run/'results/cooled_static_probe_costs.json'
    costs = shared._load(costs_path) if costs_path.exists() else {}
    records = costs.get('native_probe_records')
    owners = costs.get('probe_owner_manifest_records', {})
    if records is None:
        # Original unsealed local analysis remains supported; never invent reuse.
        records = {kind: file_record(run/'results/cooled_field_probe'/(kind+'.csv')) for kind in KINDS}
    if set(records) != set(KINDS):
        raise ValueError('complete seven-member static probe evidence required')
    for member in members:
        kind = member['kind'];record = records[kind]
        expected = run/'results/cooled_field_probe'/(kind+'.csv')
        if _record_path(record) == expected:
            _verified_small_record(record)
            if (run/'inputs/cooled_probe_points.csv').exists():
                _validate_probe_rows(expected, run/'inputs/cooled_probe_points.csv')
        else:
            validate_static_probe_reference(run, kind, record, owners[kind], member)
    return dict(native_probe_records=records, probe_owner_manifest_records=owners)


def _records(records: list[dict]) -> dict:
    """Recheck immutable field handles without rescanning large solved payloads."""
    if not isinstance(records, list) or len(records) != len(KINDS) or {r["kind"] for r in records} != set(KINDS):
        raise ValueError("exactly seven unique real-field records required")
    for row in records:
        path = Path(row["path"]).resolve(strict=True)
        if path.suffix.lower() != ".pa" or not path.is_file() or row.get("read_only") is not True or path.stat().st_mode & stat.S_IWRITE or path.stat().st_size != row["bytes"] or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise ValueError("solved ordinary PA identity/stat/read-only differs")
    return {r["kind"]: dict(r) for r in records}


def finalize_field_stage(run: Path, cache: dict, progress: dict) -> dict:
    """Bind actual member generations; never copy a solved PA to an aggregate."""
    run = shared._owner(run,'discovery')
    records = []
    for member in cache['domains'][0]['members']:
        kind = member['member_id']; source = member.get('frozen_field_source')
        if source is not None:
            generation = Path(source['generation_directory'])
            identity = shared._load(_verified_small_record(source['cache_identity_record']))
            key = source['cache_key']; names = source['cache_filenames']
            version = source['source_schema_version']; scale = member['field_scale']
            refined = False
        else:
            status = progress[kind]
            if status['status'] != 'published' or status['action_required'] != 'complete':
                raise ValueError('every missing member must finish its existing public transaction')
            generation = Path(status['generation_directory'])
            identity = member['identity']; key = member['cache_key']; names = member['filenames']
            version = 3; scale = 1.; refined = bool(status['refine_performed'])
        manifest = validate_pa_family_cache_generation(generation,expected_cache_key=key,
            expected_filenames=names,verify_payload=False)
        if manifest['identity'] != identity:
            raise ValueError('actual member identity differs from its generation')
        filename = member['filenames'][0]
        entries = [row for row in manifest['files'] if row['name'] == filename]
        if len(entries) != 1:
            raise ValueError('the actual immutable generation lacks its exact member')
        pa_identity = run/'inputs'/('cooled_member_'+kind+'_pa_identity.json')
        shared._json_once(pa_identity,identity)
        transaction = load_pa_family_cache_transaction(generation.parents[2],key)
        if transaction['status'] != 'published' or transaction['generation_sha256'] != manifest['generation_sha256']:
            raise ValueError('member publication is not complete')
        verification = transaction['verification']
        if verification is None:
            raise ValueError('member has no original native verification')
        record = dict(entries[0],path=str(generation/filename),kind=kind,read_only=True,
            cache_key=key,generation_directory=str(generation),generation_sha256=manifest['generation_sha256'],
            cache_filenames=names,cache_identity_record=file_record(pa_identity),
            requested_identity_record=file_record(Path(member['identity_path'])),
            source_schema_version=version,field_scale=scale,refine_performed=refined,
            verification_record=dict(path=verification['verification_output_path'],exists=True,
                bytes=Path(verification['verification_output_path']).stat().st_size,
                sha256=verification['verification_output_sha256']))
        if source is not None:
            record['source'] = dict(cache_key=source['cache_key'],generation_directory=source['generation_directory'],
                cache_identity_record=source['cache_identity_record'])
        records.append(record)
    indexed = _records(records)
    bank = dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
        runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,dynamic_roles=[dict(
            role='coarse_frontend',instance_index=1,carrier_pa_basename=Path(indexed['carrier_off']['path']).name,
            rf_differential_pa_basenames=[Path(indexed['rf_differential_unit']['path']).name],rf_reference_voltage_v=1.,
            pulse_delta_pa_basename=Path(indexed['pulse_delta']['path']).name,
            pulse_delta_scale=indexed['pulse_delta']['field_scale'])])
    path = run/'inputs/cooled_field_bank.json';shared._json_once(path,bank)
    receipt = dict(schema_version=3,role=FIELD_ROLE,status='success',working_points=records,
        field_bank_path=str(path),field_bank_record=file_record(path),
        field_plan_record=file_record(run/'inputs/cooled_field_plan.json'),geometry_record=file_record(run/'inputs/frontend.gem'),
        identity_validation='per_member_public_generation__exact_operator_and_scaling__runtime_stat_recheck',
        actual_refine_count=sum(row['refine_performed'] for row in records),aggregate_pa_copy_bytes=0,
        generation_directories=sorted({row['generation_directory'] for row in records}),
        protected_cache_keys=sorted({row['cache_key'] for row in records}))
    receipt_path = run/'inputs/cooled_frontend_field_stage_receipt.json';shared._json_once(receipt_path,receipt)
    return dict(receipt_path=str(receipt_path),receipt=receipt,working_points=records)


def _record_path(record: dict,workspace_root: Path | None = None, *, strict: bool = True) -> Path:
    path=Path(record["path"])
    if not path.is_absolute():
        if workspace_root is None:
            raise ValueError("relative file identity requires an explicit workspace root")
        path=Path(workspace_root).resolve(strict=True)/path
    return path.resolve(strict=strict)


def _verified_small_record(record: dict,workspace_root: Path | None = None) -> Path:
    path=_record_path(record,workspace_root)
    if path.stat().st_size != record["bytes"] or file_sha256(path) != record["sha256"]:
        raise ValueError("frozen small-file identity differs")
    return path


def _same_identity(left: dict,right: dict,workspace_root: Path | None = None) -> bool:
    return _record_path(left,workspace_root,strict=False)==_record_path(right,workspace_root,strict=False) and left.get("bytes")==right.get("bytes") and left.get("sha256")==right.get("sha256")


def _field_stage(run: Path) -> tuple[dict, dict]:
    """Read the current owner or one explicitly sealed source, never latest."""
    workspace = run.parents[4]
    local = run/'inputs/cooled_frontend_field_stage_receipt.json'
    if local.is_file():
        return shared._load(local), file_record(local)
    source = shared._load(run/'inputs/cooled_experiment.json')['field_source']
    if source is None:
        raise ValueError('a completed local or explicit sealed field bank is required')
    envelope = shared._load(_verified_small_record(source, workspace))
    if envelope.get('schema_version') != 1 or envelope.get('role') != 'rf_oatof_cooled_frontend_field_source':
        raise ValueError('sealed field-source envelope required')
    owner_record = envelope['source_owner_manifest_record']
    owner_path = _record_path(owner_record, workspace)
    require_completed_terminal_publication(owner_path)
    owner = shared._load(_verified_small_record(dict(owner_record,
        path=str(run/'inputs/cooled_field_source_manifest.json')), workspace))
    if owner.get('status') not in ('success','failed'):
        raise ValueError('field source owner is not terminal')
    if _record_path(owner['run_config'],workspace) != owner_path.parent/'run_config.json':
        raise ValueError('field source config is outside its managed owner')
    _verified_small_record(dict(owner['run_config'],path=str(run/'inputs/cooled_field_source_run_config.json')),workspace)
    reference = envelope['field_stage_receipt_record']
    if not any(_same_identity(reference,row,workspace) for row in [*owner.get('inputs',{}).values(),*owner.get('outputs',[])]):
        raise ValueError('field receipt is not bound by its original owner')
    path = _verified_small_record(reference,workspace)
    stage = shared._load(path)
    required = [stage['geometry_record'],stage['field_plan_record']]
    if stage.get('schema_version') == 2:
        required.append(stage['cache_identity_record'])
    elif stage.get('schema_version') == 3:
        required.extend(row['requested_identity_record'] for row in stage['working_points'])
    else:
        raise ValueError('unsupported source field bank; frozen evidence conversion is required')
    for record in required:
        if not any(_same_identity(record,row,workspace) for row in owner.get('inputs',{}).values()):
            raise ValueError('field scientific evidence is not bound by its original owner')
    return stage, dict(reference,path=str(path))


def published_members(run: Path, *, source_stage: tuple[dict, dict] | None = None) -> tuple[dict, dict]:
    """Validate every generation and derive old evidence without reading PA bytes."""
    run = Path(run).resolve(strict=True)
    workspace = run.parents[4]
    stage, receipt = _field_stage(run) if source_stage is None else source_stage
    if stage.get('role') != FIELD_ROLE or stage.get('status') != 'success' or stage.get('schema_version') not in (2,3):
        raise ValueError('a completed cooled working-field bank is required')
    points = shared._load(_verified_small_record(stage['field_plan_record'],workspace))
    if tuple(point['kind'] for point in points['working_points']) != KINDS:
        raise ValueError('source bank lacks its exact seven frozen endpoint definitions')
    _verified_small_record(stage['geometry_record'],workspace)
    rows = _records(stage['working_points'])
    result = {}
    for point in points['working_points']:
        kind = point['kind']; record = rows[kind]
        info = stage if stage['schema_version'] == 2 else record
        identity_record = info['cache_identity_record']
        identity = shared._load(_verified_small_record(identity_record,workspace))
        generation = _record_path(dict(path=info['generation_directory']),workspace)
        names = ([p['output_basename'] for p in points['working_points']]
                 if stage['schema_version'] == 2 else info['cache_filenames'])
        manifest = validate_pa_family_cache_generation(generation,expected_cache_key=info['cache_key'],
            expected_filenames=names,verify_payload=False)
        transaction = load_pa_family_cache_transaction(generation.parents[2],info['cache_key'])
        if (manifest['identity'] != identity or transaction['status'] != 'published'
                or transaction['generation_sha256'] != manifest['generation_sha256']
                or generation != generation.parents[2]/info['cache_key']/'generations'/manifest['generation_sha256']):
            raise ValueError('field member is not its exact published immutable generation')
        inventory = {entry['name']:entry for entry in manifest['files']}
        name = Path(record['path']).name
        if (_record_path(record,workspace) != generation/name or name not in inventory
                or any(record[key] != inventory[name][key] for key in ('bytes','sha256'))):
            raise ValueError('field member differs from its complete published inventory')
        source_version = 2 if stage['schema_version'] == 2 else record['source_schema_version']
        if source_version == 2:
            candidates = [row for row in identity['working_points'] if row.get('output_basename') == name]
            if len(candidates) != 1:
                raise ValueError('old field generation does not bind an unambiguous physical member')
            raw_identity = _legacy_member_identity(identity,candidates[0])
        elif source_version == 3:
            if len(identity['working_points']) != 1:
                raise ValueError('one physical solve per current member required')
            raw_identity = identity
        else:
            raise ValueError('field member lacks its frozen identity version')
        if raw_identity['gem'].upper() != stage['geometry_record']['sha256'].upper():
            raise ValueError('field source geometry differs from the frozen solve')
        requested_record = record.get('requested_identity_record')
        requested = shared._load(_verified_small_record(requested_record,workspace)) if requested_record else raw_identity
        scale = record.get('field_scale',1.)
        if (type(scale) not in (int,float) or not math.isfinite(scale)
                or pulse_reuse_scale(requested,raw_identity) != scale):
            raise ValueError('field member scaling lacks an exact same-operator proof')
        requested_point = requested['working_points'][0]
        expected_kind = 'rf_reference' if kind == 'rf_differential_unit' else kind
        if (requested_point['kind'] != expected_kind
                or requested_point['electrode_voltages_v'] != point['electrode_voltages_v']
                or requested_point['refine_convergence_v'] != points['refine_convergence_v']
                or requested['boundary_policy'] != points['boundary_policy']):
            raise ValueError('requested member differs from its frozen endpoint plan')
        # The original public transaction already validates the small verifier
        # and report identities; retain them as source evidence, not a new PASS.
        verification = transaction.get('verification')
        if verification is None:
            raise ValueError('published field lacks its original native verification')
        result[kind] = dict(record,path=str(generation/name),raw_identity=raw_identity,
            cache_identity_record=identity_record,cache_key=info['cache_key'],generation_directory=str(generation),
            generation_sha256=manifest['generation_sha256'],cache_filenames=names,
            source_schema_version=source_version,verification=verification,field_scale=scale)
    return result, receipt


def fields(run: Path) -> dict:
    """Require seven complete target members while allowing multiple generations."""
    run = Path(run).resolve(strict=True)
    stage, receipt = _field_stage(run)
    records, receipt = published_members(run,source_stage=(stage,receipt))
    # A read-only consumer asks for an explicitly selected solved field. Its
    # solver authority is that field's frozen producer, not today's installed
    # executable; no native discovery or PA materialization is needed here.
    geometry = stage['geometry_record']
    same_geometry = _record_path(geometry,run.parents[4]) == run/'inputs/frontend.gem'
    source_plan = stage['field_plan_record']
    target_plan = run/'inputs/cooled_field_plan.json'
    if (_record_path(source_plan,run.parents[4]) != target_plan
            and (target_plan.stat().st_size != source_plan['bytes']
                 or file_sha256(target_plan) != source_plan['sha256'])):
        raise ValueError('frozen small-file identity differs for the complete target field plan')
    plan = field_member_plans(run,freeze=False,
        solver_identity=records['carrier_off']['raw_identity']['simion_identity'],
        verified_gem_sha256=geometry['sha256'] if same_geometry else None)
    for member in plan['domains'][0]['members']:
        row = records[member['member_id']]
        scale = pulse_reuse_scale(member['identity'],row['raw_identity'])
        if scale is None or scale != row['field_scale']:
            raise ValueError('field bank does not completely match the requested seven-member operator')
    pulse_scale = records['pulse_delta']['field_scale']
    bank = dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
        runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,dynamic_roles=[dict(
            role='coarse_frontend',instance_index=1,carrier_pa_basename=Path(records['carrier_off']['path']).name,
            rf_differential_pa_basenames=[Path(records['rf_differential_unit']['path']).name],
            rf_reference_voltage_v=1.,pulse_delta_pa_basename=Path(records['pulse_delta']['path']).name,
            pulse_delta_scale=pulse_scale)])
    actual = shared._load(_verified_small_record(stage['field_bank_record'],run.parents[4]))
    # The original schema2 has the original unit pulse coefficient; derive
    # that fact from equal target/source vectors, never today's defaults.
    expected = bank if stage['schema_version'] == 3 else dict(bank,dynamic_roles=[{
        k:v for k,v in bank['dynamic_roles'][0].items() if k != 'pulse_delta_scale'}])
    if actual != expected:
        raise ValueError('field bank role/member projection differs from its verified records')
    _resolve_standalone_dynamic_field_bank(bank,{'coarse_frontend':1})
    return dict(records=records,bank=bank,receipt=receipt,
        identity_validation='per_member_public_generation__exact_operator_and_scaling__runtime_stat_recheck')


def context(run: Path, *, reference_phase: dict | None = None, shared_context: dict | None = None) -> dict:
    """Add the physical adapter, reusing a context verified in this same call."""
    run=Path(run).resolve(strict=True)
    workspace=run.parents[4]
    result=shared._context(run,field_provider=fields) if shared_context is None else shared_context
    inputs=run/"inputs"
    result.update(conditioner=shared._load(inputs/"conditioner_contract.json"),
                  cooled_drive=shared._load(inputs/"cooled_drive.json"), experiment=shared._load(inputs/"cooled_experiment.json"))
    decision_record=result["experiment"]["common_pulse_decision"]
    if reference_phase is not None:
        if result["experiment"]["pressure_scale"] != 0 or decision_record is not None:
            raise ValueError("reference calibration requires explicit vacuum and no production decision")
        if reference_phase.get("role") != "cooled_reference_phase" or reference_phase.get("pulse_mode") not in (1, 2):
            raise ValueError("explicit reference phase and pulse mode required")
        decision=reference_phase
        mode=decision["pulse_mode"]
        if mode == 2 and decision["pulse_time_us"] is not None:
            raise ValueError("held-OFF reference has no applied pulse clock")
    else:
        if decision_record is None or result["experiment"]["field_source"] is None:
            raise ValueError("population dispatch requires sealed fields and a shared actual-field pulse decision")
        decision_path=_verified_small_record(decision_record,workspace)
        decision=shared._load(decision_path)
        if decision.get("schema_version") != 1 or decision.get("role") != "actual_field_reference_exit_centering":
            raise ValueError("unsupported actual-field pulse decision")
        mode=1
        result["decision"]=decision
    identity_record=decision.get("field_identity",{}).get("field_stage_receipt_record")
    if identity_record is None or not _same_identity(identity_record,result["fields"]["receipt"],workspace):
        raise ValueError("calibration is bound to different actual fields")
    release=decision["release_start_us"]
    if reference_phase is not None:
        result["flight_horizon_us"]=release+result["numerics"]["maximum_flight_us"]
    pulse=decision["pulse_time_us"] if reference_phase is not None else decision["actual_pulse_time_us"]
    if not result["cooled_drive"]["entrance_close_us"] < release < result["flight_horizon_us"]:
        raise ValueError("reference release lies outside the ordered physical horizon")
    if mode == 1 and (isinstance(pulse,bool) or not isinstance(pulse,(int,float)) or not math.isfinite(pulse)
                      or not release < pulse < result["flight_horizon_us"]):
        raise ValueError("common calibrated clocks lie outside the ordered physical horizon")
    calibration=decision["voltage_calibration"]
    for key in ("inner_correction_v","release_hp_common_correction_v"):
        value=calibration.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError("explicit finite actual-field voltage calibration required")
    result["voltage_calibration"]=calibration
    result["cooled_drive"]=dict(result["cooled_drive"],release_start_us=release)
    hs1_path=inputs/"cooled_collision_hs1.lua"
    identity=shared._load(inputs/"cooled_hs1_identity.json")
    if _verified_small_record(identity["adapted"],workspace) != hs1_path.resolve(strict=True):
        raise ValueError("frozen official HS1 adapter identity differs")
    result["hs1_source"]=hs1_path.read_text(encoding="utf-8")
    module=Path(__file__).resolve().with_name("cooled_frontend.lua")
    result["cooled_module_source"]=module.read_text(encoding="utf-8")
    result["code_records"]["cooled_module"]=file_record(module)
    result["code_records"]["hs1"]=dict(path=str(hs1_path),exists=True,
        bytes=identity["adapted"]["bytes"],sha256=identity["adapted"]["sha256"])
    if decision_record is not None:
        result["code_records"]["common_pulse_decision"]=dict(path=str(decision_path),exists=True,
            bytes=decision_record["bytes"],sha256=decision_record["sha256"])
    for name in ("program.py","runtime.py"):
        source=Path(__file__).resolve().with_name(name)
        result["code_records"]["cooled_"+name]=file_record(source)
    for name in ("cooled_experiment.json","cooled_drive.json","conditioner_contract.json","cooled_field_plan.json"):
        result["code_records"][name]=file_record(inputs/name)
    return result


def prepare_dispatch_request(run: Path,phase: str,pulse: float,times: list[float]) -> dict:
    run=shared._owner(run,phase)
    ctx=context(run)
    if pulse != ctx["decision"]["actual_pulse_time_us"]:
        raise ValueError("both pressure arms must use the exact common OA pulse clock")
    shared._phase(run,phase,pulse,times)
    return shared.prepare_dispatch_request(run,phase,context=ctx,workload_topology_id="cooled_frontend_one_carrier_six_readonly_responses_v1")


def materialize_batches(run: Path,phase: str,plan: dict,pulse: float,times: list[float]) -> dict:
    from integrations.workflows.cooled_frontend.program import build_program
    ctx=context(run)
    if pulse != ctx["decision"]["actual_pulse_time_us"]:
        raise ValueError("both pressure arms must use the exact common OA pulse clock")
    gas = ctx["conditioner"]["gas"]
    parameters = gas["parameters"]
    scale = ctx["experiment"]["pressure_scale"]
    pressure = parameters["hp_pressure_pa"]*scale
    collision_active = scale > 0 and pressure > 0 and (
        parameters["cross_section_m2"] > 0 or parameters["mean_free_path_mm"] > 0)
    policy = dict(
        requested=ctx["verify_saved_workbench_replay"],
        comparison_policy="independent_stochastic_collisions" if collision_active else "deterministic_trajectory_parity",
        scope=("saved_controls_only" if collision_active else
               "fresh_process" if ctx["verify_saved_workbench_replay"] else "not_requested"),
        collision_active=collision_active, pressure_scale=scale, effective_hp_pressure_pa=pressure,
        gas_parameters={key: parameters[key] for key in ("cross_section_m2", "mean_free_path_mm")},
        gas_domain_native_mm=gas["domain_native_mm"],
    )
    for generation in {Path(row['generation_directory']) for row in ctx['fields']['records'].values()}:
        validate_pa_family_cache_generation(generation,verify_payload=False,require_publication_pin=True)
    return shared.materialize_batches(run,phase,plan,pulse,times,context=ctx,program_builder=build_program,
                                      default_replay_policy=policy)


def materialize_reference_case(run: Path,ctx: dict,phase_input: dict) -> dict:
    """Build the already validated one-ID reference phase, never an N=100 cohort."""
    from integrations.workflows.cooled_frontend.program import build_program
    run=shared._owner(run,"extraction")
    reference_rows=ctx["rows"]
    if len(reference_rows)!=1 or set(reference_rows[0])!=set(shared.GLOBAL_COLUMNS) or int(reference_rows[0]["particle_id"])!=1 or any(not math.isfinite(float(v)) for v in reference_rows[0].values()):
        raise ValueError("cold reference requires exactly one explicit GLOBAL_COLUMNS state with ID1")
    suffix="__"+phase_input["phase"]
    reference_phase=dict(role="cooled_reference_phase",pulse_mode=phase_input["pulse_mode"],
        pulse_time_us=phase_input["pulse_time_us"],release_start_us=ctx["cooled_drive"]["release_start_us"],
        voltage_calibration=ctx["voltage_calibration"],
        field_identity=dict(field_stage_receipt_record=ctx["fields"]["receipt"]))
    role=dict(schema_version=1,role="rf_oatof_cooled_frontend_cold_reference",particle_count=1,
              reference_rows=reference_rows,reference_phase=reference_phase,
              qualification="independent_actual_field_calibration__not_mother_population_evidence")
    shared._json_once(run/"inputs"/("cooled_reference_role"+suffix+".json"),role)
    # The common FLY2 renderer consumes CSV-shaped strings. Preserve the
    # supplied binary64 state exactly while keeping this adapter typed numeric.
    case_rows=[{key:format(float(value),".17g") for key,value in row.items()} for row in reference_rows]
    for generation in {Path(row['generation_directory']) for row in ctx['fields']['records'].values()}:
        validate_pa_family_cache_generation(generation,verify_payload=False,require_publication_pin=True)
    result=shared._case(run,"extraction","cold_reference"+suffix,case_rows,ctx,phase_input,program_builder=build_program)
    result.update(role=role["role"],qualification=role["qualification"],mother_population_flight=False)
    shared._json_once(run/"inputs"/("cooled_reference_case"+suffix+".json"),result)
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    for command in ("prepare-dispatch", "materialize-batches"):
        item=sub.add_parser(command)
        item.add_argument("--run",type=Path,required=True)
        item.add_argument("--phase",choices=shared.PHASES,required=True)
        item.add_argument("--pulse-time-us",type=float,required=True)
        item.add_argument("--shared-times-json",type=Path,required=True)
        if command=="materialize-batches":
            item.add_argument("--batch-plan",type=Path,required=True)
    args=parser.parse_args()
    times=json.loads(args.shared_times_json.read_text(encoding="utf-8-sig"))
    if args.command=="prepare-dispatch":
        result=prepare_dispatch_request(args.run,args.phase,args.pulse_time_us,times)
    else:
        result=materialize_batches(args.run,args.phase,shared._load(args.batch_plan),args.pulse_time_us,times)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
