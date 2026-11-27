"""Author a reflectron compensation study for the existing public recipe runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from msplatform.analysis.reflectron_compensation import compile_compensated_study
from msplatform.recipes import load_recipe


def write_compensated_author(recipe_path: str | Path, *, instance_id: str, fit: Mapping[str, Any],
                             recipe_name: str, study_name: str,
                             provenance: Mapping[str, Any] | None = None,
                             include_ideal: bool = False) -> dict[str, Any]:
    """Create new author files beside their originals so relative resources retain their meaning.

    The input author must select producer-backed SIMION fields without an old
    field reference. The new author requests the ordinary public field producer;
    this function does not claim a compensated field has already been built.
    """
    source = Path(recipe_path).resolve(strict=True)
    for name, suffix in ((recipe_name, '.toml'), (study_name, '.json')):
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(suffix):
            raise ValueError('output names must be simple filenames with the declared suffix')
    loaded = load_recipe(source)
    resolved = loaded.to_dict()
    if resolved['schema_version'] != 2 or resolved['particle_tracer'] != 'simion':
        raise ValueError('compensation author requires a native SIMION recipe')
    if 'compensation_provenance' in resolved['study']['document']['model_input_sources']:
        raise ValueError('chained compensation authors are not yet supported')
    if resolved['field_source'].get('kind') != 'simion_native' or 'reference' in resolved['field_source']:
        raise ValueError('compensation requires a producer-backed source without an old field reference')
    original = tomllib.loads(loaded.source_bytes.decode('utf-8'))
    if type(include_ideal) is not bool:
        raise ValueError('ideal case selection must be explicit')
    if include_ideal and ({'field_intervention', 'field_interventions'} & original['recording'].keys()):
        raise ValueError('compensation author cannot replace existing field interventions')
    study_reference = original['study']
    old_study = source.parent / study_reference['path']
    study_target = old_study.parent / study_name
    recipe_target = source.parent / recipe_name
    if recipe_target.exists() or study_target.exists():
        raise FileExistsError('compensation author outputs must be new files')
    document = compile_compensated_study(resolved['study']['document'], instance_id=instance_id, fit=fit)
    provenance_path = study_target.parent / (study_name + '.fit.json') if provenance is not None else None
    provenance_bytes = None
    if provenance_path is not None:
        if provenance_path.exists():
            raise FileExistsError('fit provenance output must be a new file')
        provenance_bytes = (json.dumps(dict(provenance), ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
        document['model_input_sources']['compensation_provenance'] = {
            'path': provenance_path.name, 'sha256': hashlib.sha256(provenance_bytes).hexdigest()}
    payload = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    relative_study = study_target.relative_to(source.parent).as_posix()
    text = loaded.source_bytes.decode('utf-8')
    sections = list(re.finditer(r'(?m)^[ \t]*\[study\][ \t]*(?:\#.*)?$', text))
    if len(sections) != 1:
        raise ValueError('author requires one explicit [study] table')
    start = sections[0].end()
    next_header = re.search(r'(?m)^[ \t]*\[', text[start:])
    end = start + next_header.start() if next_header else len(text)
    block = text[start:end]
    for key, value in (('path', relative_study), ('sha256', digest)):
        pattern = rf'(?m)^([ \t]*{key}[ \t]*=[ \t]*)[^\r\n]+$'
        block, count = re.subn(pattern, lambda match: match.group(1) + json.dumps(value), block)
        if count != 1:
            raise ValueError('study binding must have one explicit ' + key + ' line')
    author_text = text[:start] + block + text[end:]
    if include_ideal:
        headers = list(re.finditer(r'(?m)^[ \t]*\[recording\][ \t]*(?:\#.*)?$', author_text))
        if len(headers) != 1:
            raise ValueError('author requires one explicit [recording] table')
        position = headers[0].end()
        cases = ('\nfield_interventions = [{id="compensated", selector="real"}, '
                 '{id="ideal_reflectron", selector="ideal:reflectron.full"}]')
        author_text = author_text[:position] + cases + author_text[position:]
    author_bytes = author_text.encode('utf-8')
    if provenance_path is not None:
        with provenance_path.open('xb') as stream:
            stream.write(provenance_bytes)
    with study_target.open('xb') as stream:
        stream.write(payload)
    with recipe_target.open('xb') as stream:
        stream.write(author_bytes)
    verified = load_recipe(recipe_target).to_dict()
    if verified['study']['document'] != document:
        raise ValueError('new author did not resolve to its compiled Study')
    result = {'recipe_path': str(recipe_target), 'study_path': str(study_target),
              'study_sha256': digest, 'recipe_id': verified['recipe_id']}
    if provenance_path is not None:
        result.update(fit_provenance_path=str(provenance_path),
                      fit_provenance_sha256=hashlib.sha256(provenance_bytes).hexdigest())
    return result


def compare_compensated_runs(*, artifact_root: str | Path, baseline_run_id: str, compensated_run_id: str,
                             species_id: str, detector_surface_id: str, nominal_mass_da: float) -> dict[str, Any]:
    """Reread two published SI cohorts and compare their detector peak metrics."""
    import math
    import numpy as np
    from msplatform.analysis.peak_metrics import compute_peak_metrics
    from msplatform.results.particle_data import read_particle_data
    from msplatform.storage import ArtifactStore

    if not all(isinstance(v, str) and v for v in
               (baseline_run_id, compensated_run_id, species_id, detector_surface_id)):
        raise ValueError('explicit run, species and detector identities are required')
    if (type(nominal_mass_da) not in (int, float) or not math.isfinite(nominal_mass_da)
            or nominal_mass_da <= 0):
        raise ValueError('nominal mass must be explicit, finite and positive')
    store = ArtifactStore(artifact_root)
    for run_id in (baseline_run_id, compensated_run_id):
        if store.run_status(run_id)['publication_status'] != 'ready':
            raise ValueError('both comparison runs must be published')
    baseline_path = store.inspect_run(baseline_run_id)
    compensated_path = store.inspect_run(compensated_run_id)
    if (baseline_path / 'collection.json').exists():
        raise ValueError('baseline must be one explicit real-field run')
    from msplatform.workflows.tracing import inspect_results
    inspection = inspect_results(compensated_run_id, artifact_root=artifact_root)
    cases = inspection['summary']['cases']
    if [(case['id'], case['selector']) for case in cases] != [
            ('compensated', 'real'), ('ideal_reflectron', 'ideal:reflectron.full')]:
        raise ValueError('compensated run must contain the real and full ideal reflectron cases')
    data = [read_particle_data(baseline_path), read_particle_data(compensated_path / 'cases/0000'),
            read_particle_data(compensated_path / 'cases/0001')]
    for item in data:
        coverage = item['data_integrity'].get('detector_observation', {})
        if (item['execution_status'] != 'succeeded' or item['data_integrity']['status'] != 'complete'
                or coverage.get('status') != 'complete'):
            raise ValueError('complete native detector observation is required for comparison')
        if data[0]['metadata'] != item['metadata'] or data[0]['initial_states'] != item['initial_states']:
            raise ValueError('comparison requires the identical frozen mother population, frame and clock')
    initial = {row['particle_id']: row for row in data[0]['initial_states'] if row['species_id'] == species_id}
    if not initial:
        raise ValueError('selected species is absent from the mother population')
    metrics = []
    for item in data:
        first = {}
        for event in item['events']:
            pid = event['particle_id']
            if (pid in initial and event['event_kind'] == 'detector'
                    and event['surface_id'] == detector_surface_id and pid not in first):
                first[pid] = event['time_s']
        ids = sorted(first)
        times = np.asarray([(first[pid] - initial[pid]['time_s']) * 1e6 for pid in ids])
        weights = np.asarray([initial[pid]['weight'] for pid in ids])
        try:
            peak, _ = compute_peak_metrics(times, nominal_mass_da, weights=weights)
            resolution = peak.get('mass_resolution')
            if (type(resolution) not in (int, float) or not math.isfinite(resolution) or resolution <= 0):
                raise ValueError('peak mass resolution is not finite and positive')
            metrics.append({'status': 'available', 'reason': None, 'detected_particles': len(ids), 'metrics': peak})
        except ValueError as exc:
            metrics.append({'status': 'unavailable', 'reason': str(exc), 'detected_particles': len(ids), 'metrics': None})
    gain_available = all(metrics[index]['status'] == 'available' for index in (0, 1))
    gap_available = all(metrics[index]['status'] == 'available' for index in (1, 2))
    return {'schema_version': 1, 'role': 'reflectron_compensation_comparison',
            'baseline_run_id': baseline_run_id, 'compensated_run_id': compensated_run_id,
            'species_id': species_id, 'detector_surface_id': detector_surface_id,
            'baseline': metrics[0], 'compensated': metrics[1], 'ideal_reflectron': metrics[2],
            'ideal_selector': 'ideal:reflectron.full',
            'resolution_gain_ratio': (metrics[1]['metrics']['mass_resolution'] / metrics[0]['metrics']['mass_resolution'])
                                     if gain_available else None,
            'remaining_gap_ratio_to_ideal_reflectron': ((metrics[2]['metrics']['mass_resolution'] -
                metrics[1]['metrics']['mass_resolution']) / metrics[2]['metrics']['mass_resolution']) if gap_available else None}


def prepare_compensated_author(recipe_path: str | Path, samples: Any, *, instance_id: str,
                               recipe_name: str, study_name: str, context: Any,
                               artifact_store: Any) -> dict[str, Any]:
    """Bind an authenticated axis fit to its exact original recipe and new author."""
    from msplatform.backends.simion.reflectron_response_binding import fit_sampled_axis
    from msplatform.execution.native_source_guard import guard_native_source
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.workflows.native_tracing import compile_simion_model

    if not isinstance(samples, OpenedArtifact) or samples.kind != 'axis_response_samples':
        raise ValueError('an authenticated axis sample product is required')
    if artifact_store is None:
        raise ValueError('the source ArtifactStore must be explicit')
    original = load_recipe(recipe_path).to_dict()
    model = compile_simion_model(original)
    expected_id = model.document['model_identity_sha256']
    with guard_native_source(samples.reference, expected_kind='axis_response_samples',
                             expected_artifact_root=context.workspace / 'artifacts',
                             artifact_store=artifact_store) as protected:
        from msplatform.io.file_identity import canonical_json_sha256
        binding = protected.metadata['binding']
        if binding['model_identity_sha256'] != expected_id:
            raise ValueError('axis response model differs from the original author')
        fit = fit_sampled_axis(protected)
        expected_study = compile_compensated_study(original['study']['document'], instance_id=instance_id, fit=fit)
        provenance = dict(schema_version=1, role='reflectron_compensation_provenance',
            original_recipe_id=original['recipe_id'], original_resolved_recipe=original,
            original_model_identity_sha256=expected_id, axis_samples_reference=protected.reference,
            original_field_reference=binding['field_reference'], fit=fit, instance_id=instance_id,
            resulting_drive_sha256=canonical_json_sha256(expected_study['drive']))
        created = write_compensated_author(recipe_path, instance_id=instance_id, fit=fit,
            recipe_name=recipe_name, study_name=study_name, provenance=provenance, include_ideal=True)
        actual_study = load_recipe(created['recipe_path']).to_dict()['study']['document']
        actual_study['model_input_sources'].pop('compensation_provenance')
        if actual_study != expected_study:
            raise ValueError('author inputs changed during compensation compilation')
    return {**created, 'fit': fit}


def run_compensation_study(recipe_path: str | Path, samples: Any, *, baseline_run_id: str,
                           instance_id: str, recipe_name: str, study_name: str,
                           species_id: str, detector_surface_id: str, nominal_mass_da: float,
                           context: Any, artifact_store: Any, reserve_bytes: int,
                           source_revision: str | None = None) -> dict[str, Any]:
    """Fit, author, execute via the public recipe runner, and reread a baseline comparison.

    The new author requests the normal field producer. Until compensated field
    reuse is admitted, this can require a new field solve. The fit sidecar is
    returned separately and is not yet an input to the tracing run manifest.
    """
    import math
    from msplatform.workflows.tracing import run_recipe
    from msplatform.results.particle_data import read_particle_data

    if artifact_store is None:
        raise ValueError('an explicit ArtifactStore is required')
    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError('a positive explicit run reservation is required')
    if (not all(isinstance(value, str) and value for value in (baseline_run_id, species_id, detector_surface_id))
            or type(nominal_mass_da) not in (int, float) or not math.isfinite(nominal_mass_da)
            or nominal_mass_da <= 0):
        raise ValueError('baseline, species, detector and positive nominal mass must be explicit')
    if artifact_store.run_status(baseline_run_id)['publication_status'] != 'ready':
        raise ValueError('baseline run must be published before compensation')
    baseline = read_particle_data(artifact_store.inspect_run(baseline_run_id))
    if (baseline['execution_status'] != 'succeeded' or baseline['data_integrity']['status'] != 'complete'
            or baseline['data_integrity'].get('detector_observation', {}).get('status') != 'complete'
            or not any(row['species_id'] == species_id for row in baseline['initial_states'])):
        raise ValueError('baseline requires a complete observed cohort containing the selected species')
    authored = prepare_compensated_author(recipe_path, samples, instance_id=instance_id,
        recipe_name=recipe_name, study_name=study_name, context=context, artifact_store=artifact_store)
    run = run_recipe(authored['recipe_path'], artifact_root=artifact_store.root,
                     high_water_bytes=artifact_store.high, low_water_bytes=artifact_store.low,
                     safety_bytes=artifact_store.safety, reserve_bytes=reserve_bytes,
                     source_revision=source_revision, context=context)
    comparison = compare_compensated_runs(artifact_root=artifact_store.root, baseline_run_id=baseline_run_id,
        compensated_run_id=run['run_id'], species_id=species_id, detector_surface_id=detector_surface_id,
        nominal_mass_da=nominal_mass_da)
    return {'schema_version': 1, 'role': 'reflectron_compensation_study_result',
            'author': authored, 'run': run, 'comparison': comparison}


def recover_compensation_stage(*, artifact_store: Any, native_stage_asset_id: str, context: Any) -> dict[str, Any]:
    """Recover one explicitly identified terminal native Store stage, without replaying Fly."""
    from msplatform.execution.owner import recover_managed_native_store_stage

    if artifact_store is None or not isinstance(native_stage_asset_id, str) or not native_stage_asset_id:
        raise ValueError('the Store and exact native stage asset ID are required')
    recovered = recover_managed_native_store_stage(artifact_store, native_stage_asset_id, context=context)
    return {'schema_version': 1, 'role': 'reflectron_compensation_stage_recovery',
            'native_stage_asset_id': native_stage_asset_id, 'recovered': recovered}
