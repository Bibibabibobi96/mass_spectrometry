"""Thin normal/resume geometry admission; does not grant Formal access."""
from pathlib import Path
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
    from common.contracts.write_run_manifest import publish_run_manifest

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
    publish_run_manifest(config_path, 'success', output_paths=outputs)
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
    selected += [PROJECT/'workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1']
    for path in selected:
        target = fixture / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    config = fixture/f'projects/{PROJECT.name}/config'
    config.mkdir(parents=True)
    (config/'project.json').write_text(json.dumps({'project_id': PROJECT.name,
        'lifecycle_status': 'formal_revalidation_pending'}), encoding='utf-8')
    policy = fixture/'common/contracts/artifact_capacity_policy.json'
    document = json.loads(policy.read_text(encoding='utf-8-sig'))
    document['minimum_free_gib'] = 0
    policy.write_text(json.dumps(document), encoding='utf-8')
    return fixture, fixture/f'projects/{PROJECT.name}/workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1'


class MassSpectrumReanalysisTests(unittest.TestCase):
    def test_consumed_projection_rejects_unsealed_tampered_and_incomplete_records(self):
        from common.contracts.capacity_ledger import record_capacity_object
        from common.contracts.write_run_manifest import publish_run_manifest
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
                    publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs)
                    with self.assertRaisesRegex(ValueError, message):
                        select_source(source, artifacts)
                    target.write_bytes(before)
                    (source/'run_manifest.json').unlink()
                    publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs)
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
            freeze_analysis(REPO, code, selected)
            selection = root / 'inputs/source_selection.json'
            selection.write_text(json.dumps(selected), encoding='utf-8')
            output = root / 'analysis'
            launch = ('import sys;sys.path.insert(0,sys.argv[1]);'
                      'from projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum_reanalysis import run_analysis;'
                      'from pathlib import Path;run_analysis(Path(sys.argv[2]),Path(sys.argv[1]),Path(sys.argv[3]))')
            command = [sys.executable, '-I', '-B', '-c', launch, str(code), str(selection), str(output)]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            with (output/'mass_spectrum_particles.csv').open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(rows)
            self.assertTrue(all(abs(float(row['detector_x_mm'])-.1) < 1e-12 for row in rows))
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            self.assertFalse(list(code.rglob('__pycache__')))
            # A scientifically invalid exact ID still fails inside the unchanged analyzer.
            csv_path = source/'results/simion_particles.csv'
            text = csv_path.read_text(encoding='utf-8').replace('1,100,1,', '99,100,1,', 1)
            csv_path.write_text(text, encoding='utf-8')
            bad = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('exceeds the mixed-species mother population', bad.stderr)

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
        from common.contracts.write_run_manifest import publish_run_manifest

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
                        publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs)
                    else:
                        csv_path.write_bytes(source_bytes)
                        (source/'run_manifest.json').unlink()
                        publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs)
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
        from common.contracts.write_run_manifest import publish_run_manifest

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
            publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs)
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
$liveParticleCountPolicyPath=Join-Path $Repo 'common/contracts/particle_count_policy.json'
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
