"""Read sealed cooled-field probes and publish an unsealed owner's voltage proposal.

This workflow owns record/CSV I/O and the existing proposal adapter, not field
execution, a new run owner, capture/cooling qualification or trajectory physics.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from msplatform.io.file_identity import file_sha256
from msplatform.execution.retention import file_record
from msplatform.io.manifest_records import require_completed_terminal_publication
from msplatform.backends.simion.resources import native_resource_path
from msplatform.components.dual_pressure_rectilinear_ion_processor import cooled_field_design

KINDS = ("carrier_off", "rf_differential_unit", "entry_close_delta", "release_delta", "pulse_delta", "inner_auxiliary_unit", "hp_common_unit")


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



def _probe_owner(record: dict, workspace: Path) -> tuple[dict, Path]:
    path = _verified_small_record(record, workspace)
    require_completed_terminal_publication(path)
    owner = json.loads((path).read_text(encoding="utf-8-sig"))
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
    source = json.loads((run / 'inputs/cooled_experiment.json').read_text(encoding="utf-8-sig"))['field_source']
    if source is None:
        raise ValueError('no explicit sealed probe source')
    envelope = json.loads((_verified_small_record(source, run.parents[4])).read_text(encoding="utf-8-sig"))
    if envelope.get('schema_version') != 1 or envelope.get('role') != 'rf_oatof_cooled_frontend_field_source':
        raise ValueError('explicit cooled field-source envelope required')
    record = envelope['source_owner_manifest_record']
    owner, root = _probe_owner(record, run.parents[4])
    design_path = root / 'results/cooled_field_design/voltage_design.json'
    design = json.loads((_verified_small_record(
        _bound_probe_file(owner, design_path, run.parents[4], output=True))).read_text(encoding="utf-8-sig"))
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
    profile = json.loads((_verified_small_record(profile_record, workspace)).read_text(encoding="utf-8-sig"))
    if profile.get('native_executed') is not True or profile.get('fly_executed') is not False:
        raise ValueError('static probe lacks its real field-only producer profile')
    sampler_source = None
    canonical_sampler = "src/msplatform/backends/simion/resources/sample_cooled_field.lua"
    historical_sampler = "integrations/workflows/cooled_frontend/sample_field.lua"
    for key, name in (('probe_plan_record', 'cooled_probe_plan.json'),
                      ('probe_points_record', 'cooled_probe_points.csv')):
        original = profile[key]
        if _record_path(original, workspace) != root/'inputs'/name:
            raise ValueError('probe profile input is outside its original frozen owner')
        _bound_probe_file(owner, _record_path(original, workspace), workspace, output=False)
        current = file_record(run/'inputs'/name)
        if key == 'probe_plan_record':
            original_plan = json.loads((_verified_small_record(original, workspace)).read_text(encoding="utf-8-sig"))
            current_plan = json.loads((run/'inputs'/name).read_text(encoding="utf-8-sig"))
            sampler_source = original_plan.get('sampler_repository_path')
            if (sampler_source not in (historical_sampler, canonical_sampler)
                    or current_plan.get('sampler_repository_path') not in (historical_sampler, canonical_sampler)):
                raise ValueError('unknown frozen static sampler source path')
            # Only an explicit source-path relocation is equivalent. Original
            # plan and source records remain independently byte-verified below.
            if dict(original_plan, sampler_repository_path=canonical_sampler) != dict(current_plan, sampler_repository_path=canonical_sampler):
                raise ValueError('frozen static probe plan or points changed')
        elif (original['bytes'], original['sha256']) != (current['bytes'], current['sha256']):
            raise ValueError('frozen static probe plan or points changed')
    sampler = file_record(native_resource_path('sample_cooled_field.lua'))
    candidates = [row for row in owner.get('inputs', {}).values() if isinstance(row, dict)
                  and str(row.get('path', '')).replace('\\', '/').endswith('/'+sampler_source)]
    if not candidates or any((row['bytes'], row['sha256']) !=
                             (sampler['bytes'], sampler['sha256']) for row in candidates):
        raise ValueError('original frozen static sampler differs or is unknown')
    for candidate in candidates:
        if not _record_path(candidate, workspace).is_relative_to(root/'inputs'):
            raise ValueError('static sampler was not frozen by its original owner')
        _verified_small_record(candidate, workspace)
    native_record = profile['native_discovery_record']
    _bound_probe_file(owner, _record_path(native_record, workspace), workspace, output=False)
    native = json.loads((_verified_small_record(native_record, workspace)).read_text(encoding="utf-8-sig"))
    identity = json.loads((_verified_small_record(member['cache_identity_record'], workspace)).read_text(encoding="utf-8-sig"))['simion_identity']
    if (native['bytes'], native['sha256'], native['file_version']) != (
            identity['executable_bytes'], identity['executable_sha256'], identity['file_version']):
        raise ValueError('static probe solver identity differs from its raw generation')
    design_record = _bound_probe_file(owner, root/'results/cooled_field_design/voltage_design.json', workspace, output=True)
    design = json.loads((_verified_small_record(design_record, workspace)).read_text(encoding="utf-8-sig"))
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
    members = {row['kind']: row for row in json.loads((run/'inputs/cooled_frontend_field_stage_receipt.json').read_text(encoding="utf-8-sig"))['working_points']}
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
    costs = json.loads((costs_path).read_text(encoding="utf-8-sig")) if costs_path.exists() else {}
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



def analyze_field_run(run: Path) -> dict:
    """Analyze an unsealed caller-owned native field stage before publication."""
    run = Path(run).resolve(strict=True)
    def read(name):
        return json.loads((run/"inputs"/name).read_text(encoding="utf-8-sig"))
    manifest_path = run/"run_manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8-sig")).get("status") != "checkpoint":
        raise ValueError("field analysis must precede immutable owner publication")
    targets = read("cooled_design_targets.json")
    conditioner, guide = read("conditioner_contract.json"), read("guide_contract.json")
    source = pd.read_csv(run/"inputs/release_global.csv")
    if len(source[["mass_amu","charge_state"]].drop_duplicates()) != 1:
        raise ValueError("single-species curvature design required")
    # Native probes sample the actual immutable source member.  A proven
    # Laplace rescaling is a scientific projection, never a rewritten CSV.
    stage = read("cooled_frontend_field_stage_receipt.json")
    rows = stage["working_points"]
    actual_probes = static_probe_analysis_records(run, rows)
    probe_records = actual_probes["native_probe_records"]
    paths = {kind: Path(record["path"]) for kind, record in probe_records.items()}
    if tuple(row["kind"] for row in rows) != KINDS or set(paths) != set(KINDS):
        raise ValueError("complete ordered field member evidence required")
    responses = {}
    projections = {}
    for row in rows:
        kind = row["kind"]
        scale = row["field_scale"]
        responses[kind] = cooled_field_design.project_member_samples(pd.read_csv(paths[kind]), kind, scale)
        projections[kind] = dict(scale=scale, source_member=row,
                                raw_probe_record=probe_records[kind])
        if kind in actual_probes["probe_owner_manifest_records"]:
            projections[kind]["probe_owner_manifest_record"] = actual_probes["probe_owner_manifest_records"][kind]
    output = run/"results/cooled_field_design"
    output.mkdir(exist_ok=False)
    try:
        result = cooled_field_design.design_voltage_controls(responses,
            center_mr_mm=conditioner["geometry"]["trap_center_mr_mm"],
            mass_amu=float(source.mass_amu.iloc[0]), charge_state=int(source.charge_state.iloc[0]),
            temperature_k=conditioner["gas"]["parameters"]["temperature_k"],
            rf_frequency_hz=guide["drive"]["frequency_hz"],
            guide_rf_amplitude_v=guide["drive"]["rf_amplitude_v"],
            target_thermal_sigma_y_mm=targets["thermal_sigma_y_mm"],
            target_static_energy_gain_ev=targets["static_release_energy_gain_ev"],
            release_reference_name="well_62",oa_entry_reference_name="oa_side_entry")
        result["design_status"] = ("proposal_computed" if result["calibrated_closed_well"]["equilibrium_within_sample_bounds"]
                                    else "additional_actual_field_samples_required")
    except ValueError as error:
        result = dict(schema_version=1,role="cooled_frontend_actual_field_voltage_design",
                      design_status="target_not_identifiable_or_feasible",reason=str(error),
                      qualification="Native fields remain evidence; failed theory target does not qualify capture or focusing")
    result["native_probe_records"] = probe_records
    result["response_projections"] = projections
    result["target_record"] = file_record(run/"inputs/cooled_design_targets.json")
    (output/"voltage_design.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    return result



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    result = analyze_field_run(parser.parse_args().run)
    print(json.dumps(dict(role=result["role"],design_status=result["design_status"])))
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
