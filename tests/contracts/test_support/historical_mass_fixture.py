"""Small historical v1 scientific records, created without running a producer."""
import csv
import json
from pathlib import Path
from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
REPO = Path(__file__).resolve().parents[3]
PROJECT = REPO / "src/msplatform/components/single_reflection_oa_tof"

def sealed_mass_source(root):
    """Small real producer-shaped manifest and calibrated private capacity owner."""
    from msplatform.execution.manifest_publication import publish_run_manifest

    artifacts = root / 'artifacts'
    source = artifacts / 'components/single_reflection_oa_tof_mass_analyzer/runs/20261031_100000__sim__cross__mass-parent'
    for relative in ('inputs', 'results', 'logs', 'comsol'):
        (source / relative).mkdir(parents=True)
    mode = {'schema_version': 1, 'mode': 'mass_spectrum_candidate', 'role': 'oa_tof_candidate_mass_spectrum_mode', 'species': [
        {'species_id': f'm{mass}', 'mass_amu': mass, 'charge_state': 1,
         'mz': mass, 'particle_count': 4, 'relative_abundance': 1}
        for mass in (100, 400, 900)]}
    mode_path = source / 'inputs/mass_spectrum.json'
    mode_path.write_text(json.dumps(mode), encoding='utf-8')
    resolved = json.loads((PROJECT / 'config/resolved_geometry.json').read_text(encoding='utf-8-sig'))
    resolved['coordinate_convention']['detector_x'] = 123.0
    resolved_path = source / 'inputs/resolved_geometry.json'
    resolved_path.write_text(json.dumps(resolved), encoding='utf-8')
    simion = source / 'results/simion_particles.csv'
    with simion.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Ion', 'MassAmu', 'ChargeState', 'TofUs', 'XMm', 'YMm', 'Hit'])
        for species_index, mass in enumerate((100, 400, 900)):
            for index in range(4):
                writer.writerow([species_index*4+index+1, mass, 1, mass**0.5+index*.01, 123.1, .2, True])
    summary = source / 'results/simion_summary.json'
    summary.write_text(json.dumps({'Hit': 12}), encoding='utf-8')
    outputs = [simion, summary]
    for mass in (100, 400, 900):
        path = source / f'comsol/m{mass}.csv'
        path.write_text('Ion,TofUs,XMm,YMm,Hit\n'+''.join(
            f'{i+1},{mass**0.5+i*.01},123.1,.2,True\n' for i in range(4)), encoding='utf-8')
        report = source / f'logs/m{mass}.report.txt'
        report.write_text('DETECTED=4/4\n', encoding='utf-8')
        completion = source / f'logs/m{mass}.comsol_completion.json'
        completion.write_text(json.dumps(dict(schema_version=1, role='comsol_launcher_completion',
            run_id=source.name, operations=[dict(operation_id='fixture', observation=dict(
                exit_confirmed=True, returncode=0, process_id=101,
                process_started_at_utc_ticks=1))], host_release=dict(
                    inherited=True, token='fixture-child', error=None))), encoding='utf-8')
        outputs += [path, report, completion]
    config = {'schema_version': 2, 'role': 'oa_tof_mass_spectrum_run_config',
              'run_id': source.name, 'project': 'single_reflection_oa_tof_mass_analyzer',
              'mode': 'mass_spectrum_candidate', 'project_root': str(REPO),
              'inputs': {'mode_config': str(mode_path), 'resolved_geometry': str(resolved_path)},
              'artifact_retention': {'policy_version': 1, 'class': 'compact', 'reason': None},
              'capacity_ledger_lifecycle': {'schema_version': 1, 'enabled': True,
                                          'artifact_root': str(artifacts), 'light_evidence_budget_bytes': 26214400},
              'execution': {'simion': 'one mixed-species fly', 'clock_qualification': 'unspecified'},
              'particle_source_provenance': [{'origin': 'original_species_source'}]}
    config_path = source / 'run_config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    publish_run_manifest(config_path, 'success', output_paths=outputs, retention_api=_manifest_retention_api)
    return artifacts, source, config, outputs
