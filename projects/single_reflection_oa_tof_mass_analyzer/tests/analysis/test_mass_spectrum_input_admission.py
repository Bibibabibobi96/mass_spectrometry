"""Mass-spectrum admission and public-owner lifecycle software tests."""

from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
from pathlib import Path
import hashlib
import json
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


def sealed_mass_source(root):
    """Small real producer-shaped manifest and calibrated private capacity owner."""
    from common.contracts.capacity_ledger import initialize_capacity_ledger, record_capacity_object
    from msplatform.execution.manifest_publication import publish_run_manifest

    artifacts = root / 'artifacts'
    source = artifacts / 'projects/single_reflection_oa_tof_mass_analyzer/runs/20261031_100000__sim__cross__mass-parent'
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
        outputs += [path, report]
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
    initialize_capacity_ledger(artifacts, objects=[])
    record_capacity_object(artifacts, path=source, object_class='light_evidence',
                           bytes_count=sum(p.stat().st_size for p in source.rglob('*') if p.is_file()),
                           owner='single_reflection_oa_tof_mass_analyzer')
    return artifacts, source, config, outputs


def mass_analysis_fixture(root):
    """Real public owner, private machine policy; no Formal or native resources."""
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum_reanalysis import CODE_PATHS

    fixture = root / 'repo'
    selected = [p for p in (REPO/'common').rglob('*')
                if p.is_file() and p.suffix in ('.py', '.ps1', '.json')
                and not p.name.startswith('test_') and '__pycache__' not in p.parts]
    selected += [REPO / relative for relative in CODE_PATHS]
    from common.contracts.test_support.run_artifact_workflow import copy_scientific_core
    selected += [PROJECT/'workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1']
    for path in selected:
        target = fixture / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    copy_scientific_core(REPO, fixture)
    config = fixture/f'projects/{PROJECT.name}/config'
    config.mkdir(parents=True)
    (config/'project.json').write_text(json.dumps({'project_id': PROJECT.name,
        'lifecycle_status': 'formal_revalidation_pending'}), encoding='utf-8')
    policy = fixture/'src/msplatform/execution/resources/artifact_capacity_policy.json'
    document = json.loads(policy.read_text(encoding='utf-8-sig'))
    document['minimum_free_gib'] = 0
    policy.write_text(json.dumps(document), encoding='utf-8')
    return fixture, fixture/f'projects/{PROJECT.name}/workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1'


def mass_native_fixture(root):
    """Original normal CLI with real public owners and inert native leaves."""
    fixture, owner = mass_analysis_fixture(root)
    project = fixture / f'projects/{PROJECT.name}'
    for source in (PROJECT/'analysis').glob('*.py'):
        target = project/'analysis'/source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for relative in ('baseline.json', 'formal_solver_numerics.json', 'resolved_geometry.json',
                     'modes/formal.json', 'modes/mass_spectrum.json'):
        source = PROJECT/'config'/relative
        target = project/'config'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for source in (PROJECT/'oatof_lifecycle_preflight.ps1',
                   PROJECT/'simion/workbench/generate_comsol_consistent_ions.ps1',
                   PROJECT/'simion/workbench/analyze_ideal_field_log.ps1',
                   REPO/'projects/rf_multipole_ion_optics/core/grounded_shield.py',
                   REPO/'projects/rf_multipole_ion_optics/core/__init__.py',
                   REPO/'src/msplatform/contracts/particle_count_policy.json'):
        target = fixture/source.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (project/'config/project.json').write_text(json.dumps({
        'project_id': PROJECT.name, 'lifecycle_status': 'prototype'}), encoding='utf-8')
    (project/'comsol').mkdir(parents=True, exist_ok=True)
    (project/'comsol/run_fixed_particle_retrace.m').write_text('% inert native fixture\n', encoding='utf-8')
    artifacts = root/'artifacts'
    formal = artifacts/f'projects/{PROJECT.name}/formal'
    (formal/'comsol').mkdir(parents=True, exist_ok=True)
    (formal/'simion').mkdir(parents=True, exist_ok=True)
    (formal/'comsol/single_reflection_oa_tof_mass_analyzer__model.mph').write_bytes(b'inert formal model')
    (formal/'simion/oatof_ideal_grounded.iob').write_bytes(b'inert formal IOB')
    from common.contracts.capacity_ledger import initialize_capacity_ledger
    initialize_capacity_ledger(artifacts, objects=[])
    fake_simion = root/'inert-simion.exe'
    fake_simion.write_bytes(b'inert native selector')
    leaf = root/'native_leaf.py'
    leaf.write_text(r'''import csv, json, math, os, sys
from pathlib import Path

mode = sys.argv[1]
if mode == 'comsol':
    report, csv_path, ion_path = map(Path, sys.argv[2:5])
    species = ion_path.stem
    mass = float(species.split('_')[0][2:])
    count = sum(1 for _ in ion_path.open(encoding='ascii'))
    failed = os.environ.get('TEST_MASS_FAIL_SPECIES') == species
    rows = [] if failed else [(i, math.sqrt(mass) + (i-1)*.01, .1, .2, True)
                              for i in range(1, count+1)]
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Ion', 'TofUs', 'XMm', 'YMm', 'Hit'])
        writer.writerows(rows)
    report.write_text(('STATUS=FAIL\nDETECTED=0/%d\n' if failed else
                       'STATUS=PASS\nDETECTED=%d/%d\n') % ((count, count) if not failed else (count,)), encoding='utf-8')
    raise SystemExit(23 if failed else 0)
capture = Path(os.environ['TEST_MASS_SIMION_CAPTURE'])
arguments = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
ion_path = Path(arguments[arguments.index('--particles')+1])
count = sum(1 for _ in ion_path.open(encoding='ascii'))
capture.write_text(json.dumps({'arguments': arguments, 'cwd': os.getcwd(),
    'stdout': os.environ.get('TEST_MASS_SIMION_STDOUT', '')}), encoding='utf-8')
masses = (10, 100, 500, 1000, 2000)
for index in range(count):
    mass = masses[index // 100]
    print(f'TRACE: detector_crossing ion={index+1} t={math.sqrt(mass)+(index%100)*.01} x=.1 y=.2 z=0 r=.1 zmax=0')
''', encoding='utf-8')
    (project/'analysis/stage_formal_simion_runtime.py').write_text(r'''import argparse, json, shutil
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--artifact-root', type=Path, required=True)
parser.add_argument('--destination', type=Path, required=True)
parser.add_argument('--receipt', type=Path, required=True)
args = parser.parse_args()
args.destination.mkdir(parents=True)
shutil.copyfile(args.artifact_root/'formal/simion/oatof_ideal_grounded.iob', args.destination/'oatof_ideal_grounded.iob')
args.receipt.write_text(json.dumps({'role': 'inert_formal_runtime_receipt'}), encoding='utf-8')
''', encoding='utf-8')
    launcher = fixture/'src/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO/'src/msplatform/backends/comsol/launcher/resolve_comsol_64.ps1',
                    launcher.parent/'resolve_comsol_64.ps1')
    launcher.write_text(r'''param($HostContextJson,$WorkingDirectory,$TaskScript,$ReportPath,$RunId,$CompletionPath)
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
$hostContext=$HostContextJson|ConvertFrom-Json -AsHashtable
. (Join-Path $PSScriptRoot '../../../execution/resources/host_execution_lease.ps1') -HostContext $hostContext
$capture=@{task_script=$TaskScript;report_path=$ReportPath;run_id=$RunId;completion_path=$CompletionPath;
  environment=@{OATOF_SOURCE_MODEL_PATH=$env:OATOF_SOURCE_MODEL_PATH;OATOF_ION_TABLE=$env:OATOF_ION_TABLE;
  OATOF_COMSOL_OUTPUT_CSV=$env:OATOF_COMSOL_OUTPUT_CSV;OATOF_RUNTIME_DIR=$env:OATOF_RUNTIME_DIR;
  OATOF_RESULTS_DIR=$env:OATOF_RESULTS_DIR;OATOF_ACCELERATOR_HMAX_MM=$env:OATOF_ACCELERATOR_HMAX_MM;
  OATOF_REUSE_EXISTING_FIELD=$env:OATOF_REUSE_EXISTING_FIELD;OATOF_FINE_TSTEP_NS=$env:OATOF_FINE_TSTEP_NS;
  OATOF_DRIFT_TSTEP_NS=$env:OATOF_DRIFT_TSTEP_NS;OATOF_SEGMENTED_OUTPUT=$env:OATOF_SEGMENTED_OUTPUT;
  OATOF_USE_PARTICLE_STOP_TIME=$env:OATOF_USE_PARTICLE_STOP_TIME;
  OATOF_CLEAR_PARTICLE_SOLUTION_DATA=$env:OATOF_CLEAR_PARTICLE_SOLUTION_DATA;
  OATOF_APPLY_PARTICLE_PROPERTIES=$env:OATOF_APPLY_PARTICLE_PROPERTIES}}
[IO.File]::AppendAllText($env:TEST_MASS_COMSOL_CAPTURE,($capture|ConvertTo-Json -Depth 8 -Compress)+"`n")
$lease=Enter-HostResourceStage -Role COMSOL -Stage solver -RunId $RunId -Budget (Get-HostResourceBudget -Role COMSOL -Stage solver)
$started=[Diagnostics.Stopwatch]::StartNew()
$process=$null;$taskFailure=$null
try{
 $process=Invoke-ResourceBudgetedProcess -Limits $null -RunDir (Split-Path -Parent $ReportPath) `
   -UsagePath ($ReportPath+'.usage.json') -FilePath $env:TEST_MASS_PYTHON `
   -ArgumentList @('-B',$env:TEST_MASS_LEAF,'comsol',$ReportPath,$env:OATOF_COMSOL_OUTPUT_CSV,$env:OATOF_ION_TABLE) `
   -WorkingDirectory $WorkingDirectory
 if($process.exit_code-ne0){throw 'INERT_COMSOL_FAILURE'}
}catch{$taskFailure=$_}
$release=$null;$releaseError=$null
try{$release=Exit-HostResourceStage -Lease $lease -PassThru}catch{$releaseError=$_.Exception.Message}
$observation=@{exit_confirmed=($null-ne$process);returncode=$(if($null-ne$process){[int]$process.exit_code}else{$null});
  process_id=$(if($null-ne$process){[int]$process.root_process_id}else{$PID});
  process_started_at_utc_ticks=$(if($null-ne$process){[long]$process.root_process_started_at_utc_ticks}else{[long]$started.StartTicks})}
if($env:TEST_MASS_UNKNOWN_SPECIES-and[IO.Path]::GetFileNameWithoutExtension($env:OATOF_ION_TABLE)-ceq$env:TEST_MASS_UNKNOWN_SPECIES){
 $observation.exit_confirmed=$false;$observation.returncode=$null
}
$receipt=@{schema_version=1;role='comsol_launcher_completion';run_id=$RunId;
 operations=@(@{operation_id='launcher-attempt-1';observation=$observation});
 host_release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$release;error=$releaseError}}
Write-RunJson -Atomic -Path $CompletionPath -Value $receipt -Depth 30
if($taskFailure){throw $taskFailure}
''', encoding='utf-8')
    original = owner.read_text(encoding='utf-8')
    marker = "$hostRole = 'SIMION'"
    shim = r'''$realMassObserver=(Get-Command Invoke-ResourceBudgetedProcess).ScriptBlock
function Invoke-ResourceBudgetedProcess {
 param([AllowNull()]$Limits,$RunDir,$UsagePath,$FilePath,[string[]]$ArgumentList,$WorkingDirectory='',
  $RedirectStandardOutput='',$RedirectStandardError='',[hashtable]$Environment=@{},
  [switch]$RequireImmutableInputDrain,$WindowStyle='Hidden',$ProcessObservationMetadata=$null)
 if($FilePath-ceq$env:TEST_MASS_SIMION){
  $env:TEST_MASS_SIMION_STDOUT=$RedirectStandardOutput
  $PSBoundParameters['FilePath']=$env:TEST_MASS_PYTHON
  $argumentTransport=$env:TEST_MASS_SIMION_CAPTURE+'.arguments.json'
  [IO.File]::WriteAllText($argumentTransport,($ArgumentList|ConvertTo-Json -Compress))
  $PSBoundParameters['ArgumentList']=@('-B',$env:TEST_MASS_LEAF,'simion',$argumentTransport)
 }
 & $realMassObserver @PSBoundParameters
}
'''
    owner.write_text(original.replace(marker, shim+marker, 1), encoding='utf-8')
    return fixture, owner, artifacts, fake_simion, leaf


def mass_native_environment(root, fixture, artifacts, simion, leaf, python):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
    env.update(SIMULATION_PYTHON_EXE=str(python), MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
               MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'),
               MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'),
               TEST_MASS_PYTHON=str(python), TEST_MASS_LEAF=str(leaf), TEST_MASS_SIMION=str(simion),
               TEST_MASS_COMSOL_CAPTURE=str(root/'comsol-capture.jsonl'),
               TEST_MASS_SIMION_CAPTURE=str(root/'simion-capture.json'))
    return env


def run_mass_native(owner, fixture, env, run_id, simion, *extra, timeout=120):
    return subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-RunId', run_id,
                           '-SimionExe', str(simion), *extra], cwd=fixture, env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=timeout)


class MassSpectrumReanalysisTests(unittest.TestCase):
    def test_consumed_projection_rejects_unsealed_tampered_and_incomplete_records(self):
        from common.contracts.capacity_ledger import record_capacity_object
        from msplatform.execution.manifest_publication import publish_run_manifest
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum_reanalysis import select_source

        with tempfile.TemporaryDirectory() as temporary:
            artifacts, source, config, outputs = sealed_mass_source(Path(temporary))
            selected = select_source(source, artifacts)
            self.assertEqual(len(selected['exports']), 8)
            self.assertEqual(selected['run_id'], source.name)
            for name, change, message in (
                ('hit', lambda: (source/'results/simion_summary.json').write_text('{"Hit":11}', encoding='utf-8'), 'full-mother'),
                ('report', lambda: (source/'logs/m100.report.txt').write_text('DETECTED=3/4', encoding='utf-8'), 'complete detection'),
            ):
                with self.subTest(case=name):
                    target = source / ('results/simion_summary.json' if name == 'hit' else 'logs/m100.report.txt')
                    before = target.read_bytes()
                    change()
                    # New fixture owner publication, never a mutation of a real run.
                    (source/'run_manifest.json').unlink()
                    publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=_manifest_retention_api)
                    with self.assertRaisesRegex(ValueError, message):
                        select_source(source, artifacts)
                    target.write_bytes(before)
                    (source/'run_manifest.json').unlink()
                    publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=_manifest_retention_api)
            original = (source/'inputs/resolved_geometry.json').read_bytes()
            (source/'inputs/resolved_geometry.json').write_bytes(original+b' ')
            with self.assertRaisesRegex(AssertionError, 'changed'):
                select_source(source, artifacts)
            (source/'inputs/resolved_geometry.json').write_bytes(original)
            manifest_path = source/'run_manifest.json'
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            manifest['outputs'] = [r for r in manifest['outputs'] if not r['path'].endswith('m100.report.txt')]
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unique consumed output'):
                select_source(source, artifacts)
            manifest_path.write_bytes(manifest_bytes)
            journal = source/'.run_terminal_publication.json'
            journal.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'terminal publication is incomplete'):
                select_source(source, artifacts)
            journal.unlink()
            manifest = json.loads(manifest_bytes)
            manifest['status'] = 'checkpoint'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'explicit stopped payload receipt'):
                select_source(source, artifacts)
            manifest_path.write_bytes(manifest_bytes)
            record_capacity_object(artifacts, path=source, object_class='rebuildable_payload', bytes_count=1,
                                   status='writing', owner='single_reflection_oa_tof_mass_analyzer',
                                   recovery_reason='fixture writer', review_deadline='2099-01-01')
            with self.assertRaisesRegex(ValueError, 'not sealed'):
                select_source(source, artifacts)

    def test_frozen_actual_analyzer_uses_parent_geometry_and_preserves_acceptance(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum_reanalysis import freeze_analysis, select_source

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts, source, _, _ = sealed_mass_source(root)
            selected = select_source(source, artifacts)
            snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            code = root / 'inputs/code'
            inventory = freeze_analysis(REPO, code, selected)
            frozen_before = {str(p.relative_to(code)): p.read_bytes() for p in code.rglob('*') if p.is_file()}
            with self.assertRaises(FileExistsError):
                freeze_analysis(REPO, code, selected)
            self.assertEqual(frozen_before, {str(p.relative_to(code)): p.read_bytes() for p in code.rglob('*') if p.is_file()})
            self.assertIn('src/msplatform/analysis/peak_metrics.py', {item['relative_path'] for item in inventory['files']})
            paths = [item['relative_path'] for item in inventory['files']]
            for unused in ('reference_analysis.py', 'reference_analysis_core.py', 'solver_diagnostics.py', 'mass_spectrum.py'):
                self.assertNotIn(f'projects/{PROJECT.name}/analysis/{unused}', paths)
            self.assertEqual(paths.count('src/msplatform/analysis/peak_metrics.py'), 1)
            self.assertEqual(paths.count('src/msplatform/execution/inputs.py'), 1)
            for relative in ('src/msplatform/workflows/single_reflection_mass_spectrum.py',
                             'src/msplatform/results/single_reflection_particle_table.py'):
                self.assertIn(relative, {item['relative_path'] for item in inventory['files']})
            inventory_path = root / 'inputs/code_inventory.json'
            inventory_path.write_text(json.dumps(inventory), encoding='utf-8')
            schemas = {path.relative_to(REPO).as_posix(): path
                       for path in (REPO/'src/msplatform').rglob('*.schema.json')}
            frozen = {item['relative_path']: item for item in inventory['files']
                      if item['relative_path'].endswith('.schema.json')}
            self.assertTrue(schemas)
            self.assertEqual(set(frozen), set(schemas))
            self.assertEqual(len(frozen), sum(item['relative_path'].endswith('.schema.json')
                                             for item in inventory['files']))
            for relative, path in schemas.items():
                with self.subTest(schema=relative):
                    original_bytes = path.read_bytes()
                    self.assertEqual((code/relative).read_bytes(), original_bytes)
                    self.assertEqual((code/relative).stat().st_size, len(original_bytes))
                    self.assertEqual(frozen[relative]['sha256'].upper(),
                                     hashlib.sha256(original_bytes).hexdigest().upper())
            selection = root / 'inputs/source_selection.json'
            selection.write_text(json.dumps(selected), encoding='utf-8')
            output = root / 'analysis'
            # Obtain the same canonical invocation consumed by the public owner.
            helper = code/'src/msplatform/execution/resources/frozen_python_package.ps1'
            arguments = ['analyze', '--selection', str(selection), '--code-root', str(code),
                         '--output', str(output), '--inventory', str(inventory_path)]
            probe_args = root/'inputs/probe_args.json'
            probe_args.write_text(json.dumps(arguments), encoding='utf-8')
            probe = r"""
$ErrorActionPreference='Stop'
. 'HELPER'
$package=Get-Content -LiteralPath 'INVENTORY' -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable -Depth 100
$moduleArgs=@(Get-Content -LiteralPath 'ARGS' -Raw -Encoding UTF8 | ConvertFrom-Json)
$result=Invoke-IsolatedFrozenPythonModule -Python 'PYTHON' -Package $package `
  -Module 'projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum_reanalysis' `
  -Arguments $moduleArgs -ProbeOnly -WorkingDirectory 'WORK' `
  -RequiredModuleNames @('msplatform.workflows.single_reflection_mass_spectrum',
                         'msplatform.results.single_reflection_particle_table', 'msplatform.analysis.peak_metrics')
ConvertTo-Json -InputObject $result.invocation -Depth 100 -Compress
"""
            for key, value in {'HELPER': helper, 'INVENTORY': inventory_path, 'ARGS': probe_args,
                               'PYTHON': Path(sys.executable), 'WORK': root}.items():
                probe = probe.replace(key, str(value).replace("'", "''"))
            extracted = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', probe],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(extracted.returncode, 0, extracted.stdout + extracted.stderr)
            invocation = json.loads(extracted.stdout)
            command = [invocation['file_path'], *invocation['arguments']]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            with (output/'mass_spectrum_particles.csv').open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(rows)
            self.assertTrue(all(abs(float(row['detector_x_mm'])-.1) < 1e-12 for row in rows))
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            self.assertFalse(list(code.rglob('__pycache__')))
            # Each selected implementation must exist and match its own frozen bytes.
            for index, relative in enumerate(('src/msplatform/workflows/single_reflection_mass_spectrum.py',
                             'src/msplatform/results/single_reflection_particle_table.py',
                             'projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json')):
                target = code / relative
                original = target.read_bytes()
                try:
                    for missing in (True, False):
                        with self.subTest(relative=relative, missing=missing):
                            if missing:
                                target.unlink()
                            else:
                                target.write_bytes(original + b"\n# tampered\n")
                            failure_output = root / f"negative-{index}-{missing}"
                            failure_command = list(command)
                            failure_command[failure_command.index('--output') + 1] = str(failure_output)
                            refused = subprocess.run(failure_command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
                            self.assertNotEqual(refused.returncode, 0)
                            if missing:
                                self.assertIn('FileNotFoundError', refused.stderr)
                                self.assertIn(target.name, refused.stderr)
                            else:
                                self.assertIn(f'Frozen mass-spectrum source identity differs: {relative}', refused.stderr)
                            self.assertFalse(failure_output.exists())
                            target.write_bytes(original)
                finally:
                    target.write_bytes(original)
            # A scientifically invalid exact ID still fails inside the unchanged analyzer.
            csv_path = source/'results/simion_particles.csv'
            text = csv_path.read_text(encoding='utf-8').replace('1,100,1,', '99,100,1,', 1)
            csv_path.write_text(text, encoding='utf-8')
            bad = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('exceeds the mixed-species mother population', bad.stderr)
            output_before = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
            (code/'src').rename(root/'removed-core')
            missing = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertNotIn('exceeds the mixed-species mother population', missing.stderr)
            self.assertIn('FileNotFoundError', missing.stderr)
            self.assertIn(repr(str(code/'src/msplatform/workflows/single_reflection_mass_spectrum.py')), missing.stderr)
            self.assertEqual(output_before, {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()})

    def test_public_reanalysis_refuses_changed_frozen_dependencies_before_analysis(self):
        cases = (
            ('missing_peak', 'src/msplatform/analysis/peak_metrics.py', True, 'Frozen Python dependency is missing'),
            ('tampered_peak', 'src/msplatform/analysis/peak_metrics.py', False, 'Frozen Python dependency hash differs'),
            ('tampered_helper', 'src/msplatform/execution/resources/frozen_python_package.ps1', False, 'Frozen Python helper identity differs'),
        )
        for case, relative, missing, expected in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                artifacts, source, _, _ = sealed_mass_source(root)
                fixture, owner = mass_analysis_fixture(root)
                text = owner.read_text(encoding='utf-8')
                marker = "    $helperRelative='src/msplatform/execution/resources/frozen_python_package.ps1'"
                self.assertEqual(text.count(marker), 1)
                target = relative.replace('/', '\\')
                mutation = (f"    Remove-Item -LiteralPath (Join-Path $analysisCode '{target}')\n" if missing else
                    f"    Add-Content -LiteralPath (Join-Path $analysisCode '{target}') -Value '# altered test fixture'\n")
                owner.write_text(text.replace(marker, mutation + marker), encoding='utf-8')
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
                env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                           MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'),
                           MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'))
                run_id = '20261031_100100__analysis__python__mass-child'
                command = ['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                           '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)]
                result = subprocess.run(command, cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout + result.stderr)
                result_dir = artifacts/f'projects/{PROJECT.name}/runs/{run_id}/results'
                self.assertFalse((result_dir/'mass_spectrum_metrics.json').exists())
                self.assertTrue((fixture/'src/msplatform/analysis/peak_metrics.py').is_file())
                self.assertTrue((fixture/'src/msplatform/execution/resources/frozen_python_package.ps1').is_file())

    def test_original_cli_reanalysis_and_resume_use_public_owner_without_formal_or_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts, source, _, _ = sealed_mass_source(root)
            fixture, owner = mass_analysis_fixture(root)
            snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'))
            run_id = '20261031_100100__analysis__python__mass-child'
            command = ['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                       '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)]
            result = subprocess.run(command, cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            child = artifacts/f'projects/{PROJECT.name}/runs/{run_id}'
            result_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json'
            receipt = json.loads(result_path.read_text(encoding='utf-8-sig'))
            self.assertTrue(receipt['terminal_published'])
            self.assertTrue(receipt['capacity_finalized'])
            self.assertTrue(receipt['lease_released'])
            completion = json.loads((child/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(len(completion['writer_completion']['operations']), 1)
            self.assertGreater(completion['writer_completion']['operations'][0]['observation']['process_id'], 0)
            self.assertEqual(completion['summary']['solver_native_calls'], 0)
            self.assertEqual(completion['summary']['pa_materializations'], 0)
            self.assertFalse(list(child.rglob('*.pa*')))
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            env['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(root/'different-today-root')
            resumed = subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization', '-RunId', run_id,
                                      '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                                     cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_analysis_failure_is_sealed_and_finalization_failure_resumes_without_analysis(self):
        from msplatform.execution.manifest_publication import publish_run_manifest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts, source, _, outputs = sealed_mass_source(root)
            fixture, owner = mass_analysis_fixture(root)
            original = owner.read_text(encoding='utf-8')
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'))
            csv_path = source/'results/simion_particles.csv'
            source_bytes = csv_path.read_bytes()
            for case, run_id in (('analysis', '20261031_100200__analysis__python__mass-bad-data'),
                                 ('finalization', '20261031_100300__analysis__python__mass-recover')):
                with self.subTest(case=case):
                    if case == 'analysis':
                        csv_path.write_text(source_bytes.decode().replace('1,100,1,', '99,100,1,', 1), encoding='utf-8')
                        (source/'run_manifest.json').unlink()
                        publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=_manifest_retention_api)
                    else:
                        csv_path.write_bytes(source_bytes)
                        (source/'run_manifest.json').unlink()
                        publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=_manifest_retention_api)
                        # Fault only the public finalization invocation, after the
                        # real Complete adapter persists actual stopped writers.
                        marker='  if($ResumeFinalization){'
                        owner.write_text(original.replace(marker,
                            "  function Invoke-RunArtifactWorkflow {throw 'FINALIZATION_SENTINEL'}\n"+marker, 1), encoding='utf-8')
                    snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
                    command = ['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                               '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)]
                    failed = subprocess.run(command, cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
                    self.assertNotEqual(failed.returncode, 0, failed.stdout+failed.stderr)
                    child = artifacts/f'projects/{PROJECT.name}/runs/{run_id}'
                    result_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json'
                    receipt = json.loads(result_path.read_text(encoding='utf-8-sig'))
                    if case == 'analysis':
                        self.assertIn('reanalysis failed', receipt['exception']['message'])
                        self.assertTrue(receipt['terminal_published'])
                        self.assertEqual(receipt['status'], 'failed')
                    else:
                        self.assertIn('FINALIZATION_SENTINEL', failed.stderr)
                        self.assertEqual(receipt['stage'], 'completion')
                        completion_before = (child/'results/execution_completion.json').read_bytes()
                        owner.write_text(original, encoding='utf-8')
                        resumed = subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization',
                            '-RunId', run_id, '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                            cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
                        self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
                        self.assertEqual(completion_before, (child/'results/execution_completion.json').read_bytes())
                        self.assertTrue(json.loads(result_path.read_text(encoding='utf-8-sig'))['terminal_published'])
                    self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_resume_rejects_new_science_and_analysis_rejects_ambiguous_inputs(self):
        owner = PROJECT/'workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [dict(ResumeFinalization=True, SourceRunPath='absent'),
                     dict(ReanalyzeOnly=True, ResumeAfterComsol=True, SourceRunPath='absent', AnalysisNewBytes=1),
                     dict(ReanalyzeOnly=True, SourceRunPath='absent', AnalysisNewBytes=0)]
            (root/'cases.json').write_text(json.dumps(cases), encoding='utf-8')
            script = root/'binding.ps1'
            script.write_text(r'''param($Owner,$Cases)
$ErrorActionPreference='Stop'
$results=@(foreach($case in (Get-Content $Cases -Raw|ConvertFrom-Json -AsHashtable)){
 try{& $Owner @case;@{accepted=$true}}catch{@{accepted=$false;id=$_.FullyQualifiedErrorId}}
})
ConvertTo-Json -Depth 8 -InputObject $results
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(owner), str(root/'cases.json')],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            outcomes = json.loads(result.stdout)
            self.assertEqual(len(outcomes), 3)
            for index, outcome in enumerate(outcomes):
                with self.subTest(case=index):
                    self.assertFalse(outcome['accepted'])
                    self.assertTrue(outcome['id'].startswith(
                        'AmbiguousParameterSet' if index < 2 else 'ParameterArgumentValidationError'), outcome)

    def test_release_failure_keeps_actual_analysis_primary_and_required_protection(self):
        from msplatform.execution.manifest_publication import publish_run_manifest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts, source, _, outputs = sealed_mass_source(root)
            fixture, owner = mass_analysis_fixture(root)
            text = owner.read_text(encoding='utf-8')
            marker = '  if($ResumeFinalization){'
            owner.write_text(text.replace(marker, """  $actualStageExit=(Get-Command Exit-HostResourceStage).ScriptBlock
  function Exit-HostResourceStage {
    param($Lease,[switch]$PassThru)
    if($Lease.stage-ceq'postprocess'){
      [IO.File]::AppendAllText((Join-Path $env:TEST_MASS_ROOT 'release_calls.txt'),'release\n')
      throw 'RELEASE_SECONDARY_SENTINEL'
    }
    & $actualStageExit -Lease $Lease -PassThru:$PassThru
  }
"""+marker, 1), encoding='utf-8')
            csv_path = source/'results/simion_particles.csv'
            csv_path.write_text(csv_path.read_text(encoding='utf-8').replace('1,100,1,', '99,100,1,', 1), encoding='utf-8')
            (source/'run_manifest.json').unlink()
            publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=_manifest_retention_api)
            snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'), TEST_MASS_ROOT=str(root),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'))
            run_id = '20261031_100400__analysis__python__mass-release-failed'
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                       '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)],
                       cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('mixed-species mother population', result.stderr)
            receipt = json.loads((artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json').read_text(encoding='utf-8-sig'))
            self.assertIn('mixed-species mother population', receipt['exception']['message'])
            self.assertIn('RELEASE_SECONDARY_SENTINEL', receipt['secondary_errors'])
            self.assertEqual(receipt['failure_stage'], 'host_release')
            self.assertTrue(receipt['writers_confirmed'])
            self.assertFalse(receipt['terminal_published'])
            self.assertFalse(receipt['capacity_finalized'])
            self.assertFalse(receipt['lease_released'])
            self.assertEqual((root/'release_calls.txt').read_text(encoding='utf-8').splitlines(), ['release'])
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_deep_analysis_uses_public_execution_context_then_resumes_without_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deep = root
            while len(str(deep)) < 260:
                deep /= 'deep source and artifact segment'
            artifacts, source, _, _ = sealed_mass_source(deep)
            fixture, owner = mass_analysis_fixture(root)
            original = owner.read_text(encoding='utf-8')
            marker = '  if($ResumeFinalization){'
            owner.write_text(original.replace(marker, r'''  $actualObserver=(Get-Command Invoke-ResourceBudgetedProcess).ScriptBlock
  function Invoke-ResourceBudgetedProcess {
    param([AllowNull()]$Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList,$WorkingDirectory,
      $RedirectStandardOutput,$RedirectStandardError,$Environment)
    @{cwd=$WorkingDirectory;argv=$ArgumentList;environment=$Environment;stdout=$RedirectStandardOutput;stderr=$RedirectStandardError}|
      ConvertTo-Json -Depth 12|Set-Content -LiteralPath $env:TEST_MASS_CAPTURE -Encoding utf8
    & $actualObserver @PSBoundParameters
  }
'''+marker, 1), encoding='utf-8')
            snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
            capture = root/'observer.json'
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'), TEST_MASS_CAPTURE=str(capture),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'))
            run_id = '20261031_100500__analysis__python__mass-deep'
            completed = subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                       '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)],
                       cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            child = artifacts/f'projects/{PROJECT.name}/runs/{run_id}'
            self.assertGreater(len(str(child/'inputs/code')), 259)
            observed = json.loads(capture.read_text(encoding='utf-8-sig'))
            self.assertLessEqual(len(observed['cwd']), 259)
            self.assertNotEqual(Path(observed['cwd']), child)
            self.assertEqual(Path(observed['environment']['MASS_SPECTROMETRY_RUN_DIRECTORY']), child)
            self.assertEqual(observed['environment']['MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY'], observed['cwd'])
            self.assertIn(observed['cwd'], observed['stdout'])
            self.assertIn(observed['cwd'], observed['stderr'])
            self.assertIn(str(child/'inputs/code'), ' '.join(observed['argv']))
            self.assertFalse(Path(observed['cwd']).exists(), 'Public finalizer did not remove its disposable alias')
            completion = child/'results/execution_completion.json'
            completion_bytes = completion.read_bytes()
            details = json.loads(completion_bytes)
            self.assertGreater(details['summary']['native_path_preparation']['calls'], 0)
            self.assertEqual(details['summary']['solver_native_calls'], 0)
            self.assertEqual(details['summary']['pa_materializations'], 0)
            owner.write_text(original, encoding='utf-8')
            result_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json'
            env['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(root/'different-current-root')
            resumed = subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization', '-RunId', run_id,
                       '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                       cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            self.assertEqual(completion_bytes, completion.read_bytes())
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})



class MassSpectrumNativeLifecycleTests(unittest.TestCase):
    def test_original_cli_success_preserves_native_transport_and_rejects_legacy_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, owner, artifacts, simion, leaf = mass_native_fixture(root)
            env = mass_native_environment(root, fixture, artifacts, simion, leaf, Path(sys.executable))
            run_id = '20261116_100000__sim__cross__mass-owner-success'
            result = run_mass_native(owner, fixture, env, run_id, simion)
            child = artifacts/f'projects/{PROJECT.name}/runs/{run_id}'
            native_log = child/'logs/simion_stderr.log'
            diagnostic = native_log.read_text(encoding='utf-8', errors='replace') if native_log.is_file() else ''
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr+diagnostic)
            receipt_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
            self.assertTrue(receipt['terminal_published'])
            self.assertTrue(receipt['capacity_finalized'])
            self.assertTrue(receipt['lease_released'])
            completion = json.loads((child/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(len(completion['writer_completion']['operations']), 6)
            self.assertEqual(completion['summary']['status'], 'success')
            self.assertEqual(completion['summary']['run_id'], run_id)
            config = json.loads((child/'run_config.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(set(config['native_completion']),
                             {'mz10_z1', 'mz100_z1', 'mz500_z1', 'mz1000_z1', 'mz2000_z1'})
            captures = [json.loads(line) for line in (root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(captures), 5)
            expected_environment = {
                'OATOF_ACCELERATOR_HMAX_MM': '1', 'OATOF_REUSE_EXISTING_FIELD': '1',
                'OATOF_FINE_TSTEP_NS': '0.2', 'OATOF_DRIFT_TSTEP_NS': '50',
                'OATOF_SEGMENTED_OUTPUT': '1', 'OATOF_USE_PARTICLE_STOP_TIME': '0',
                'OATOF_CLEAR_PARTICLE_SOLUTION_DATA': '0', 'OATOF_APPLY_PARTICLE_PROPERTIES': '1'}
            for index, capture in enumerate(captures):
                self.assertEqual(capture['run_id'], run_id)
                self.assertTrue(capture['completion_path'].endswith('.comsol_completion.json'))
                self.assertEqual(capture['task_script'], str(fixture/f'projects/{PROJECT.name}/comsol/run_fixed_particle_retrace.m'))
                self.assertEqual({key: capture['environment'][key] for key in expected_environment}, expected_environment)
                self.assertEqual(capture['environment']['OATOF_ION_TABLE'], str(child/'ions'/f"{config['species'][index]['species_id']}.ion"))
            native = json.loads((root/'simion-capture.json').read_text(encoding='utf-8'))
            arguments = native['arguments']
            self.assertEqual(arguments[:13], ['--default-num-particles', '500', '--nogui', 'fly',
                '--trajectory-quality', '8', '--retain-trajectories', '0', '--particles', arguments[9],
                '--programs', '1', '--adjustable'])
            self.assertEqual(arguments[13:17], ['trajectory_quality=8', '--adjustable', 'trajectory_log_enable=1', '--adjustable'])
            self.assertTrue(arguments[17].startswith('diagnostic_max_tof_us='))
            self.assertTrue(arguments[18].endswith('oatof_ideal_grounded.iob'))
            legacy_id = '20261116_100001__sim__cross__mass-legacy-resume'
            legacy = artifacts/f'projects/{PROJECT.name}/runs/{legacy_id}'
            for relative in ('inputs', 'results', 'logs', 'ions', 'comsol'):
                (legacy/relative).mkdir(parents=True, exist_ok=True)
            legacy_config = dict(config)
            legacy_config['run_id'] = legacy_id
            legacy_config.pop('native_completion', None)
            (legacy/'run_config.json').write_text(json.dumps(legacy_config), encoding='utf-8')
            refused = run_mass_native(owner, fixture, env, legacy_id, simion, '-ResumeAfterComsol')
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('lacks its original public owner', refused.stdout+refused.stderr)
            self.assertEqual(len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()), 5)

    def test_authenticated_comsol_replay_rejects_tamper_and_reruns_only_incomplete_species(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, owner, artifacts, simion, leaf = mass_native_fixture(root)
            env = mass_native_environment(root, fixture, artifacts, simion, leaf, Path(sys.executable))
            original = owner.read_text(encoding='utf-8')
            hold = original.replace("$hostRole = 'SIMION'", "function Complete-RunArtifactPowerShellOwner {throw 'OWNER_HOLD_SENTINEL'}\n$hostRole = 'SIMION'", 1)
            owner.write_text(hold, encoding='utf-8')
            run_id = '20261116_100100__sim__cross__mass-owner-replay'
            env['TEST_MASS_FAIL_SPECIES'] = 'mz100_z1'
            failed = run_mass_native(owner, fixture, env, run_id, simion)
            self.assertNotEqual(failed.returncode, 0)
            child = artifacts/f'projects/{PROJECT.name}/runs/{run_id}'
            self.assertEqual(json.loads((child/'run_manifest.json').read_text(encoding='utf-8-sig'))['status'], 'checkpoint')
            self.assertEqual(len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()), 2)
            csv_path = child/'comsol/mz10_z1.csv'
            original_csv = csv_path.read_bytes()
            csv_path.write_bytes(original_csv+b' ')
            tampered = run_mass_native(owner, fixture, env, run_id, simion, '-ResumeAfterComsol')
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn('Workflow file identity differs', tampered.stdout+tampered.stderr)
            self.assertEqual(len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()), 2)
            csv_path.write_bytes(original_csv)
            owner.write_text(original, encoding='utf-8')
            env.pop('TEST_MASS_FAIL_SPECIES')
            resumed = run_mass_native(owner, fixture, env, run_id, simion, '-ResumeAfterComsol')
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            captures = [json.loads(line)['environment']['OATOF_ION_TABLE'] for line in
                        (root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(captures), 6)
            self.assertEqual(sum(path.endswith('mz10_z1.ion') for path in captures), 1)
            self.assertEqual(sum(path.endswith('mz100_z1.ion') for path in captures), 2)
            receipt = json.loads((artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json').read_text(encoding='utf-8-sig'))
            self.assertTrue(receipt['terminal_published'])
            self.assertEqual(len(json.loads((child/'results/execution_completion.json').read_text(encoding='utf-8-sig'))['writer_completion']['operations']), 6)

    def test_native_failure_seals_failed_run_and_unknown_writer_retains_hold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, owner, artifacts, simion, leaf = mass_native_fixture(root)
            env = mass_native_environment(root, fixture, artifacts, simion, leaf, Path(sys.executable))
            failed_id = '20261116_100200__sim__cross__mass-native-failed'
            env['TEST_MASS_FAIL_SPECIES'] = 'mz100_z1'
            failed = run_mass_native(owner, fixture, env, failed_id, simion)
            self.assertNotEqual(failed.returncode, 0)
            receipt_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{failed_id}/result.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
            self.assertEqual(receipt['status'], 'failed')
            self.assertTrue(receipt['terminal_published'], json.dumps(receipt)+failed.stdout+failed.stderr)
            self.assertTrue(receipt['capacity_finalized'])
            self.assertIn('INERT_COMSOL_FAILURE', receipt['exception']['message'])
            replay = run_mass_native(owner, fixture, env, failed_id, simion, '-ResumeAfterComsol')
            self.assertNotEqual(replay.returncode, 0)
            self.assertIn('ResumeFinalization', replay.stdout+replay.stderr)
            self.assertEqual(len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()), 2)
            env.pop('TEST_MASS_FAIL_SPECIES')
            unknown_id = '20261116_100201__sim__cross__mass-writer-unknown'
            env['TEST_MASS_UNKNOWN_SPECIES'] = 'mz10_z1'
            unknown = run_mass_native(owner, fixture, env, unknown_id, simion)
            self.assertNotEqual(unknown.returncode, 0)
            child = artifacts/f'projects/{PROJECT.name}/runs/{unknown_id}'
            retained_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{unknown_id}/result.json'
            retained = json.loads(retained_path.read_text(encoding='utf-8-sig'))
            self.assertFalse(retained['writers_confirmed'])
            self.assertEqual(retained['resume_action'], 'inspect_writer_completion')
            self.assertEqual(json.loads((child/'run_manifest.json').read_text(encoding='utf-8-sig'))['status'], 'checkpoint')
            hold_path = child/'logs/capacity_session.json'
            self.assertEqual(json.loads(hold_path.read_text(encoding='utf-8-sig'))['status'], 'active')
            protected = (retained_path, hold_path, child/'run_config.json')
            before = {path: path.read_bytes() for path in protected}
            launches_before = len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines())
            refused = run_mass_native(owner, fixture, env, unknown_id, simion, '-ResumeAfterComsol')
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('requires confirmed stopped native writers', refused.stdout+refused.stderr)
            self.assertEqual(len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()), launches_before)
            self.assertEqual(before, {path: path.read_bytes() for path in protected})

    def test_normal_finalization_resume_replays_no_native_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, owner, artifacts, simion, leaf = mass_native_fixture(root)
            env = mass_native_environment(root, fixture, artifacts, simion, leaf, Path(sys.executable))
            original = owner.read_text(encoding='utf-8')
            owner.write_text(original.replace("$hostRole = 'SIMION'", "function Invoke-RunArtifactWorkflow {throw 'NORMAL_FINALIZATION_SENTINEL'}\n$hostRole = 'SIMION'", 1), encoding='utf-8')
            run_id = '20261116_100300__sim__cross__mass-finalization-resume'
            failed = run_mass_native(owner, fixture, env, run_id, simion)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('NORMAL_FINALIZATION_SENTINEL', failed.stdout+failed.stderr)
            child = artifacts/f'projects/{PROJECT.name}/runs/{run_id}'
            completion_path = child/'results/execution_completion.json'
            completion = completion_path.read_bytes()
            receipt_path = artifacts/f'projects/{PROJECT.name}/scratch/workflow_results/{run_id}/result.json'
            self.assertEqual(json.loads(receipt_path.read_text(encoding='utf-8-sig'))['stage'], 'completion')
            owner.write_text(original, encoding='utf-8')
            resumed = subprocess.run(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization',
                '-RunId', run_id, '-ResultPath', str(receipt_path), '-PythonExe', sys.executable],
                cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            self.assertEqual(completion, completion_path.read_bytes())
            self.assertTrue(json.loads(receipt_path.read_text(encoding='utf-8-sig'))['terminal_published'])
            self.assertEqual(len((root/'comsol-capture.jsonl').read_text(encoding='utf-8').splitlines()), 5)
            self.assertTrue((root/'simion-capture.json').is_file())


class MassSpectrumInputAdmissionTests(unittest.TestCase):
    def test_workspace_context_and_final_publication_preserve_package_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root/'context.ps1'
            script.write_text(r'''param($Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
$mass=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1'
$ideal=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_ideal_field_diagnostic.ps1'
$text=[IO.File]::ReadAllText($mass);$ast=[Management.Automation.Language.Parser]::ParseFile($mass,[ref]$null,[ref]$null)
$first=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq'$python'},$true)
$last=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq'$environmentNames'},$true)
$prefix=$text.Substring($first.Extent.StartOffset,$last.Extent.StartOffset-$first.Extent.StartOffset)
$repoRoot=$Repo;$projectRoot=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer'
foreach($scenario in @('new','resume','missing_paths','root_mismatch')){
 $selected=Join-Path $Root ($scenario+'/configured-artifacts')
 $original=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot $selected -ExecutionRoot (Join-Path $Root ($scenario+'/original-exec')) -HostResourceStatePath (Join-Path $Root ($scenario+'/original-host.sqlite3')) -Python $Python
 $env:SIMULATION_PYTHON_EXE=$Python;$env:MASS_SPECTROMETRY_ARTIFACT_ROOT=$selected
 $env:MASS_SPECTROMETRY_EXECUTION_ROOT=Join-Path $Root 'today-exec';$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $Root 'today-host.sqlite3'
 $RunId='20261030_120600__sim__cross__mass-context';$ResumeAfterComsol=$scenario-ne'new';$ReanalyzeOnly=$false
 $expected=Join-Path $selected ('projects/single_reflection_oa_tof_mass_analyzer/runs/'+$RunId)
 if($ResumeAfterComsol){
  [IO.Directory]::CreateDirectory($expected)|Out-Null
  $record=@{run_id=$RunId;project='single_reflection_oa_tof_mass_analyzer';mode='mass_spectrum_candidate';paths=$original;capacity_ledger_lifecycle=@{artifact_root=$selected}}
  if($scenario-eq'missing_paths'){$record.Remove('paths')}
  if($scenario-eq'root_mismatch'){$record.paths=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot (Join-Path $Root 'other-artifacts') -Python $Python}
  Write-RunJson -Path (Join-Path $expected 'run_config.json') -Value $record -Depth 20
 }
 $caught=$null;try{Invoke-Expression $prefix}catch{$caught=$_.Exception.Message}
 if($scenario-eq'missing_paths'){
  if($caught-notlike'Resume lacks frozen path context. ACTION=*'){throw ('Missing frozen roots accepted: '+$caught)}
 }elseif($scenario-eq'root_mismatch'){
  if($caught-cne'Resume frozen run/root/capacity identity differs.'){throw ('Frozen root mismatch accepted: '+$caught)}
 }else{
  if($caught-or$artifactRoot-cne(Join-Path $selected 'projects/single_reflection_oa_tof_mass_analyzer')){throw ('Selected artifact root changed: '+$caught)}
  if($scenario-eq'resume'-and($pathContext.execution_root-cne$original.execution_root-or$pathContext.host_resource_state_path-cne$original.host_resource_state_path)){throw 'Resume followed today defaults'}
 }
}
foreach($entry in @(@{file=$ideal;variable='$finalConfig';pathVariable='$runConfig'},@{file=$mass;variable='$runConfig';pathVariable='$runConfigPath'})){
 $text=[IO.File]::ReadAllText($entry.file);$ast=[Management.Automation.Language.Parser]::ParseFile($entry.file,[ref]$null,[ref]$null)
 $variable=$entry.variable;$pathVariable=$entry.pathVariable
 $first=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq$variable},$true)
 $last=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Write-RunJson'-and$n.Extent.Text.Contains('-Value '+$variable+' ')},$true)
 $block=$text.Substring($first.Extent.StartOffset,$last.Extent.EndOffset-$first.Extent.StartOffset)
 $configFile=Join-Path $Root ([IO.Path]::GetFileName($entry.file)+'.json')
 $original=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot (Join-Path $Root 'publication-artifacts') -ExecutionRoot (Join-Path $Root 'publication-exec') -HostResourceStatePath (Join-Path $Root 'publication-host.sqlite3') -Python $Python
 Write-RunJson -Path $configFile -Value @{schema_version=2;paths=$original;package_sentinel='keep';artifact_retention=@{class='solver_review'};capacity_ledger_lifecycle=@{artifact_root=$original.artifact_root}} -Depth 20
 $runConfig=$configFile;$runConfigPath=$configFile;$runInputs=@{science='source-record'}
 $N=2;$Seed=17;$AnalyzeOnly=$true;$mode=[pscustomobject]@{species=@()};$sourceProvenance=@();$ResumeAfterComsol=$false;$ReanalyzeOnly=$true;$simionMaxTofUs=80
 Invoke-Expression $block
 $result=Get-Content -LiteralPath $configFile -Raw|ConvertFrom-Json -AsHashtable
 if($result.schema_version-ne2-or$result.package_sentinel-cne'keep'-or$result.paths.execution_root-cne$original.execution_root-or$result.paths.host_resource_state_path-cne$original.host_resource_state_path-or$result.capacity_ledger_lifecycle.artifact_root-cne$result.paths.artifact_root-or$result.inputs.science-cne'source-record'){throw 'Final scientific publication discarded package identity'}
}
'WORKSPACE_PUBLICATION=PASS'
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script),str(REPO),sys.executable,str(root)],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('WORKSPACE_PUBLICATION=PASS', result.stdout)

    def test_guard_freshness_and_original_resume_inputs(self):
        owner = PROJECT / "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1"
        for scenario in ("normal", "stale", "pending", "resume", "foreign_resume"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture_project = root / "project"
                (fixture_project / "config").mkdir(parents=True)
                lifecycle = "formal_revalidation_pending" if scenario == "pending" else "prototype"
                (fixture_project / "config/project.json").write_text(
                    json.dumps({"lifecycle_status": lifecycle}), encoding="utf-8")
                fixture = root / "admit.ps1"
                fixture.write_text(r'''param($Repo,$Python,$Owner,$Root,$Project,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1')
$realCopy=(Get-Command Copy-VerifiedRunInput).ScriptBlock
$script:copies=0
function Copy-VerifiedRunInput {param($Source,$Destination)
 $script:copies++
 $result=& $realCopy -Source $Source -Destination $Destination
 if($Scenario-eq'stale'-and$Destination.Replace('\','/').EndsWith('/config/resolved_geometry.json')){[IO.File]::AppendAllText($Destination,' ')}
 return $result
}
$repoRoot=$Repo;$python=$Python;$projectRoot=$Project;$runDir=$Root
[IO.File]::WriteAllText((Join-Path $runDir 'run_config.json'),'{"inputs":{},"parameters":{}}')
$inputDir=Join-Path $Root 'inputs';New-Item -ItemType Directory $inputDir|Out-Null
$modePath=Join-Path $inputDir 'mass_spectrum.json';$particleCountPolicyPath=Join-Path $inputDir 'particle_count_policy.json'
$resolvedPath=Join-Path $inputDir 'resolved_geometry.json';$recordedResolved=Join-Path $inputDir 'original_recorded_resolved.json'
$liveModePath=Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/config/modes/mass_spectrum.json'
$liveParticleCountPolicyPath=Join-Path $Repo 'src/msplatform/contracts/particle_count_policy.json'
$geometryFrozenInputs=[ordered]@{}
$resumeExisting=$Scenario-in@('resume','reanalyze','foreign_resume')
$existingLifecycle=[pscustomobject]@{inputs=[pscustomobject]@{resolved_geometry=$recordedResolved;geometry_freshness_baseline=(Join-Path $inputDir 'original_baseline.json')}}
if($Scenario-eq'foreign_resume'){$recordedResolved=Join-Path $Root 'outside_resolved.json';$existingLifecycle.inputs.resolved_geometry=$recordedResolved}
if($resumeExisting){foreach($p in @($modePath,$particleCountPolicyPath,$recordedResolved)){[IO.File]::WriteAllText($p,'{}')}}
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$prepare=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.Contains('$geometrySnapshotRoot = Join-Path')},$true)
if($null-eq$prepare){throw 'Actual prepare branch not found'}
$downstream=0;$caught=$null
try{
 Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot
 Invoke-Expression $prepare.Extent.Text
 $downstream++
}catch{$caught=$_.Exception.Message}
switch($Scenario){
 'pending' {if($caught-notlike'FORMAL_REVALIDATION_REQUIRED*'-or$script:copies-ne0-or$downstream-ne0){throw 'Formal guard was bypassed or did unnecessary geometry work'}}
 'foreign_resume' {if($caught-cne'Recorded geometry must remain within this run frozen inputs.'-or$script:copies-ne0-or$downstream-ne0){throw 'Foreign recorded input escaped the original frozen-input boundary'}}
 'stale' {if($caught-cne'Frozen mass-spectrum geometry input freshness failed.'-or$downstream-ne0){throw ('Stale prepare was accepted: '+$caught)};$record=Get-Content (Join-Path $runDir 'run_config.json') -Raw|ConvertFrom-Json;if($record.inputs.resolved_geometry-cne$resolvedPath-or$record.parameters.lifecycle_stage-cne'geometry_input_freshness'){throw 'Failed geometry input identity was lost'}}
 {$_-in@('resume','reanalyze')} {if($caught-or$script:copies-ne0-or$resolvedPath-cne$recordedResolved-or$downstream-ne1-or$geometryFrozenInputs.geometry_freshness_baseline-cne$existingLifecycle.inputs.geometry_freshness_baseline){throw 'Historical inputs rebound to current defaults'}}
 default {if($caught-or$script:copies-ne12-or$resolvedPath-cne$geometryFrozenInputs.geometry_freshness_published-or$downstream-ne1){throw ('Valid pure prepare failed: '+$caught)}}
}
'MASS_SPECTRUM_ADMISSION=PASS'
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture), str(REPO),
                                         sys.executable, str(owner), str(root), str(fixture_project), scenario],
                                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("MASS_SPECTRUM_ADMISSION=PASS", result.stdout)
                if scenario == "normal":
                    self.assertIn("RESOLVED_GEOMETRY=PASS", result.stdout)
                if scenario == "stale":
                    self.assertIn("STALE=config/resolved_geometry.json", result.stdout + result.stderr)
