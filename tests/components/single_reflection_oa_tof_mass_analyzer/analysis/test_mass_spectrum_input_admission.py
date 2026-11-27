"""Mass-spectrum admission and public-owner lifecycle software tests."""

from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
from pathlib import Path
import atexit
import hashlib
import json
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[4] / "src/msplatform/components/single_reflection_oa_tof"
REPO = Path(__file__).resolve().parents[4]
_SUBPROCESS_RUN = subprocess.run


def _configure_original_cli(command, *args, **kwargs):
    """Supply explicit deployment and installed-owner inert native leaves."""
    env = kwargs.get('env')
    command = list(command)
    if kwargs.get('text'):
        kwargs.setdefault('errors', 'replace')
    owner_index = next((index for index, value in enumerate(command)
                        if str(value).endswith('run_mass_spectrum_candidate.ps1')), None)
    if owner_index is None or env is None or 'MASS_SPECTROMETRY_ARTIFACT_ROOT' not in env:
        return _SUBPROCESS_RUN(command, *args, **kwargs)
    owner = Path(command[owner_index])
    fixture = owner.parents[4]
    artifacts = Path(env['MASS_SPECTROMETRY_ARTIFACT_ROOT'])
    root = artifacts.parent
    formal = artifacts / f'components/{"single_reflection_oa_tof_mass_analyzer"}/formal'
    if (formal / 'simion/oatof_ideal_grounded.iob').is_file():
        mph = formal / 'comsol/single_reflection_oa_tof_mass_analyzer__model.mph'
        assets_path = fixture / 'src/msplatform/components/single_reflection_oa_tof/config/formal_assets.json'
        assets_path.parent.mkdir(parents=True, exist_ok=True)
        assets = json.loads((PROJECT / 'config/formal_assets.json').read_text(encoding='utf-8'))
        assets['comsol']['sha256'] = hashlib.sha256(mph.read_bytes()).hexdigest().upper()
        assets_path.write_text(json.dumps(assets), encoding='utf-8')
        iob = formal / 'simion/oatof_ideal_grounded.iob'
        payload = iob.read_bytes()
        (formal / 'asset_manifest.json').write_text(json.dumps(dict(
            schema_version=1, role='formal_asset_manifest', project="single_reflection_oa_tof_mass_analyzer",
            release_id=assets['release_id'], assets={'iob': dict(
                path='simion/oatof_ideal_grounded.iob', bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest().upper())})), encoding='utf-8')
    stage = root / 'stage-policy.json'
    stage.write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy', stages={
        'oa_tof_mass_spectrum': dict(limits=dict(wall_clock_seconds=120,
            transient_run_directory_bytes=268435456, process_tree_working_set_bytes=2147483648,
            minimum_system_available_memory_bytes=1073741824, compact_final_retained_bytes=67108864,
            automatic_retry_count=0), artifact_retention=dict(policy_version=1,
                **{'class': 'solver_review'}, reason='restored inert native regression'))})), encoding='utf-8')
    environment_path = root / 'execution-environment.json'
    environment_path.write_text(json.dumps(dict(schema_version=1, role='execution_environment',
        tools=dict(python=str(Path(sys.executable).resolve()), powershell=shutil.which('pwsh')),
        policy=dict(host_state_path=str(root/'host.sqlite3'),
            policy_path=str(fixture/'src/msplatform/execution/resources/host_resource_policy.json'),
            execution_root=env.get('MASS_SPECTROMETRY_EXECUTION_ROOT', str(root/'execution')),
            capacity_policy_path=str(fixture/'src/msplatform/execution/resources/artifact_capacity_policy.json')),
        profiles=dict(test=dict(stage_policy_path=str(stage))))), encoding='utf-8')
    sitecustomize = r'''
import csv,hashlib,json,os
from pathlib import Path
from msplatform.execution.run_session import RunSession
_original=RunSession.run_process

def _inert(session,operation_id,*,executable,arguments,**kwargs):
    env=dict(kwargs.get('environment') or {})
    ordinal=session.expected_operation_ids.index(operation_id)+1
    base=session.log_dir/f'operation_{ordinal:04d}'
    capture=os.environ.get('TEST_MASS_CAPTURE')
    if capture:
        Path(capture).write_text(json.dumps(dict(cwd=str(session.run_dir),argv=list(arguments),
            environment=dict(session.environment,**env),stdout=str(base.with_suffix('.stdout.log')),
            stderr=str(base.with_suffix('.stderr.log')))),encoding='utf-8')
    if operation_id == 'python-analysis':
        return _original(session,operation_id,executable=executable,arguments=arguments,**kwargs)
    if operation_id.startswith('comsol-'):
        report=Path(arguments[arguments.index('-ReportPath')+1])
        completion=Path(arguments[arguments.index('-CompletionPath')+1])
        output=Path(env['OATOF_COMSOL_OUTPUT_CSV']);ion=Path(env['OATOF_ION_TABLE'])
        record=dict(task_script=arguments[arguments.index('-TaskScript')+1],report_path=str(report),
            run_id=session.run_id,completion_path=str(completion),environment=env)
        with Path(os.environ['TEST_MASS_COMSOL_CAPTURE']).open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record)+'\n')
        argv=[str(Path(os.environ['TEST_MASS_LEAF'])),'comsol',str(report),str(output),str(ion)]
    else:
        transport=Path(os.environ['TEST_MASS_SIMON_CAPTURE'] if 'TEST_MASS_SIMON_CAPTURE' in os.environ
                       else os.environ['TEST_MASS_SIMION_CAPTURE'])
        transport.with_suffix('.arguments.json').write_text(json.dumps(list(arguments)),encoding='utf-8')
        transport.write_text(json.dumps(dict(arguments=list(arguments),cwd=str(session.run_dir),
            stdout=str(base.with_suffix('.stdout.log')))),encoding='utf-8')
        argv=[str(Path(os.environ['TEST_MASS_LEAF'])),'simion',str(transport.with_suffix('.arguments.json'))]
    try:
        result=_original(session,operation_id,executable=Path(os.environ['TEST_MASS_PYTHON']),
            arguments=argv,**{**kwargs,'environment':env})
    except Exception as error:
        if operation_id.startswith('comsol-') and getattr(error,'observed_process_exit_confirmed',False):
            observation=error.receipt['observation'];code=error.observed_process_returncode
            completion.write_text(json.dumps(dict(schema_version=1,role='comsol_launcher_completion',
                run_id=session.run_id,operations=[dict(operation_id='inert',observation=dict(
                    exit_confirmed=True,returncode=code,process_id=observation['root_process_id'],
                    process_started_at_utc_ticks=observation['root_process_started_at_utc_ticks']))],
                host_release=dict(inherited=True,token='inert',error=None))),encoding='utf-8')
            raise RuntimeError('INERT_COMSOL_FAILURE') from error
        raise
    if operation_id.startswith('comsol-'):
        code=result['observation']['exit_code']
        completion.write_text(json.dumps(dict(schema_version=1,role='comsol_launcher_completion',
            run_id=session.run_id,operations=[dict(operation_id='inert',observation=dict(
                exit_confirmed=True,returncode=code,process_id=result['observation']['root_process_id'],
                process_started_at_utc_ticks=result['observation']['root_process_started_at_utc_ticks']))],
            host_release=dict(inherited=True,token='inert',error=None))),encoding='utf-8')
        if os.environ.get('TEST_MASS_UNKNOWN_SPECIES')==ion.stem:
            with session._lock:
                session._completed.pop(operation_id,None);session._active.add(operation_id)
                session.operations[:]=[row for row in session.operations if row['operation_id']!=operation_id]
            raise RuntimeError('INERT_WRITER_OBSERVATION_UNKNOWN')
        if code:raise RuntimeError('INERT_COMSOL_FAILURE')
    return result
if os.environ.get('TEST_MASS_LEAF'):RunSession.run_process=_inert

if os.environ.get('TEST_MASS_CAPTURE') and not os.environ.get('TEST_MASS_LEAF'):
    _observe=RunSession.run_process
    def _capture(session,operation_id,*,arguments,**kwargs):
        ordinal=session.expected_operation_ids.index(operation_id)+1;base=session.log_dir/f'operation_{ordinal:04d}'
        Path(os.environ['TEST_MASS_CAPTURE']).write_text(json.dumps(dict(cwd=str(session.run_dir),
            argv=list(arguments),environment=session.environment,stdout=str(base.with_suffix('.stdout.log')),
            stderr=str(base.with_suffix('.stderr.log')))),encoding='utf-8')
        return _observe(session,operation_id,arguments=arguments,**kwargs)
    RunSession.run_process=_capture

if os.environ.get('TEST_MASS_RELEASE_SENTINEL'):
    import msplatform.execution.run_session as process_session
    _observed=process_session.run_observed_process
    def _release_failure(*args,**kwargs):
        try:
            result=_observed(*args,**kwargs)
        except Exception as error:
            if not getattr(error,'receipt',None):raise
            result=error.receipt
            with Path(os.environ['TEST_MASS_ROOT'],'release_calls.txt').open('a') as stream:stream.write('release\n')
            result['host_release']['error']=os.environ['TEST_MASS_RELEASE_SENTINEL']
            result['host_release']['result']=None
            raise
        with Path(os.environ['TEST_MASS_ROOT'],'release_calls.txt').open('a') as stream:stream.write('release\n')
        result['host_release']['error']=os.environ['TEST_MASS_RELEASE_SENTINEL']
        result['host_release']['result']=None
        return result
    process_session.run_observed_process=_release_failure

if os.environ.get('TEST_MASS_MUTATE'):
    from msplatform.workflows import single_reflection_mass_spectrum_study as study
    _freeze=study._freeze_code
    def _mutate(session,*args,**kwargs):
        result=_freeze(session,*args,**kwargs);package=result[0]
        relative=os.environ['TEST_MASS_MUTATE'];row=next(row for row in package['files']
            if row['relative_path']==relative);target=Path(row['path'])
        if os.environ.get('TEST_MASS_MISSING'):target.unlink()
        else:target.write_bytes(target.read_bytes()+b'\n# altered test fixture\n')
        Path(os.environ['MASS_SPECTROMETRY_ARTIFACT_ROOT']).parent.joinpath('mutation_calls').write_text(relative)
        return result
    study._freeze_code=_mutate

if os.environ.get('TEST_MASS_FINALIZATION_SENTINEL'):
    from msplatform.execution import owner
    def _held(*args,**kwargs):raise RuntimeError(os.environ['TEST_MASS_FINALIZATION_SENTINEL'])
    owner._finalize=_held
'''
    scoped = "import sys\nif '--code-root' not in sys.argv:\n" + '\n'.join(
        '    '+line for line in sitecustomize.splitlines())+'\n'
    (fixture/'sitecustomize.py').write_text(scoped, encoding='utf-8')
    isolated_root = root
    if len(str(root/'fixture-python')) > 180:
        isolated_root = Path(tempfile.mkdtemp(prefix='oa-fixture-python-'))
        atexit.register(shutil.rmtree, isolated_root, ignore_errors=True)
    isolated_python = isolated_root/'fixture-python'
    if not isolated_python.exists():
        _SUBPROCESS_RUN([sys.executable, '-B', '-m', 'venv', str(isolated_python)],
                        check=True, capture_output=True)
        selected = isolated_python/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        purelib = Path(_SUBPROCESS_RUN([str(selected), '-I', '-B', '-c',
            'import sysconfig;print(sysconfig.get_paths()["purelib"])'], check=True,
            capture_output=True, text=True).stdout.strip())
        import importlib
        import sysconfig
        dependency_roots = {str(Path(sysconfig.get_paths()['purelib']).resolve())}
        for name in ('numpy', 'scipy', 'pandas', 'matplotlib', 'openpyxl'):
            module = importlib.import_module(name)
            dependency_roots.add(str(Path(module.__file__).resolve().parent.parent))
        (purelib/'oa_test_fixture.pth').write_text(
            os.linesep.join((str(fixture), str(fixture/'src'), *sorted(dependency_roots)))+os.linesep,
            encoding='utf-8')
    else:
        selected = isolated_python/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    deployment = json.loads(environment_path.read_text(encoding='utf-8'))
    deployment['tools']['python'] = str(selected)
    environment_path.write_text(json.dumps(deployment), encoding='utf-8')
    env.pop('PYTHONPATH', None)
    env['SIMULATION_PYTHON_EXE'] = str(selected)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if '-PythonExe' in command:
        command[command.index('-PythonExe')+1] = str(selected)
    command += ['-Workspace', str(root), '-ExecutionEnvironment', str(environment_path),
                '-EngineeringProfile', 'test']
    if not any(option in command for option in ('-ReanalyzeOnly', '-ResumeFinalization')):
        command += ['-ArtifactRootPath', str(artifacts),
                    '-ScienceRoot', str(fixture/'src/msplatform/components/single_reflection_oa_tof')]
    completed = _SUBPROCESS_RUN(command, *args, **kwargs)
    if completed.stderr is not None:
        completed.stderr += f"\nTEST_DEPLOYMENT={root}; HOST={env['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']}"
    return completed


def sealed_mass_source(root):
    """Small real producer-shaped manifest and calibrated private capacity owner."""
    from msplatform.execution.capacity_ledger import initialize_capacity_ledger, record_capacity_object
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
    initialize_capacity_ledger(artifacts, objects=[])
    record_capacity_object(artifacts, path=source, object_class='light_evidence',
                           bytes_count=sum(p.stat().st_size for p in source.rglob('*') if p.is_file()),
                           owner='single_reflection_oa_tof_mass_analyzer')
    return artifacts, source, config, outputs


def assert_managed_terminal(test, result_path, status='success'):
    from msplatform.execution.capacity_protection import _lease_path
    receipt = json.loads(Path(result_path).read_text(encoding='utf-8-sig'))
    test.assertEqual(receipt['status'], status)
    test.assertEqual(receipt['stage'], 'complete')
    test.assertIsNone(receipt['resume_action'])
    test.assertTrue(Path(receipt['manifest']['path']).is_file())
    test.assertIn('capacity', receipt)
    capacity = receipt['capacity_session']
    test.assertFalse(_lease_path(Path(capacity['artifact_root']), capacity['lease_id']).exists())
    return receipt


def mass_analysis_fixture(root):
    """Real public owner, private machine policy; no Formal or native resources."""
    fixture = root / 'repo'
    selected = [p for p in (REPO/'tools/repository').rglob('*')
                if p.is_file() and p.suffix in ('.py', '.ps1', '.json')
                and not p.name.startswith('test_') and '__pycache__' not in p.parts]
    from tests.contracts.test_support.run_artifact_workflow import copy_scientific_core
    selected += [REPO/'src/msplatform/workflows/resources/run_mass_spectrum_candidate.ps1']
    for path in selected:
        target = fixture / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    copy_scientific_core(REPO, fixture)
    config = fixture/'src/msplatform/components/single_reflection_oa_tof/config'
    config.mkdir(parents=True, exist_ok=True)
    (config/'project.json').write_text(json.dumps({'project_id': 'single_reflection_oa_tof_mass_analyzer',
        'lifecycle_status': 'formal_revalidation_pending'}), encoding='utf-8')
    policy = fixture/'src/msplatform/execution/resources/artifact_capacity_policy.json'
    document = json.loads(policy.read_text(encoding='utf-8-sig'))
    document['minimum_free_gib'] = 0
    policy.write_text(json.dumps(document), encoding='utf-8')
    return fixture, fixture/'src/msplatform/workflows/resources/run_mass_spectrum_candidate.ps1'


def mass_native_fixture(root):
    """Original normal CLI with real public owners and inert native leaves."""
    fixture, owner = mass_analysis_fixture(root)
    project = fixture / 'src/msplatform/components/single_reflection_oa_tof'
    for relative in ('baseline.json', 'formal_solver_numerics.json', 'resolved_geometry.json',
                     'modes/formal.json', 'modes/mass_spectrum.json'):
        source = PROJECT/'config'/relative
        target = project/'config'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for source in (REPO/'src/msplatform/workflows/resources/oatof_lifecycle_preflight.ps1',
                   REPO/'src/msplatform/backends/simion/resources/generate_comsol_consistent_ions.ps1',
                   REPO/'src/msplatform/backends/simion/resources/analyze_ideal_field_log.ps1',
                   REPO/'src/msplatform/components/rf_multipole/grounded_shield.py',
                   REPO/'src/msplatform/components/rf_multipole/__init__.py',
                   REPO/'src/msplatform/contracts/particle_count_policy.json'):
        target = fixture/source.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (project/'config/project.json').write_text(json.dumps({
        'project_id': "single_reflection_oa_tof_mass_analyzer", 'lifecycle_status': 'prototype'}), encoding='utf-8')
    backend = fixture/'src/msplatform/backends/comsol/matlab'
    backend.mkdir(parents=True, exist_ok=True)
    from msplatform.workflows import single_reflection_mass_spectrum_study as study
    for relative in study.RETRACE_RESOURCES:
        source = REPO/'src/msplatform/backends/comsol/matlab'/relative
        target = backend/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (backend/'run_fixed_particle_retrace.m').write_text('% inert native fixture\n', encoding='utf-8')
    artifacts = root/'artifacts'
    formal = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/formal'
    (formal/'comsol').mkdir(parents=True, exist_ok=True)
    (formal/'simion').mkdir(parents=True, exist_ok=True)
    (formal/'comsol/single_reflection_oa_tof_mass_analyzer__model.mph').write_bytes(b'inert formal model')
    (formal/'simion/oatof_ideal_grounded.iob').write_bytes(b'inert formal IOB')
    from msplatform.execution.capacity_ledger import initialize_capacity_ledger
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
    rows = [(i, math.sqrt(mass) + (i-1)*.01, .1, .2, not failed)
            for i in range(1, count+1)]
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Ion', 'TofUs', 'XMm', 'YMm', 'Hit'])
        writer.writerows(rows)
    release_path = csv_path.with_name(f'{species}_fixedN{count}_selected_release_from_data_file.txt')
    release_path.write_text(ion_path.read_text(encoding='ascii'), encoding='ascii')
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
    (project/'analysis').mkdir(parents=True, exist_ok=True)
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


def _run_cli(command, *args, **kwargs):
    return _configure_original_cli(command, *args, **kwargs)


def run_mass_native(owner, fixture, env, run_id, simion, *extra, timeout=180):
    command = ['pwsh', '-NoProfile', '-File', str(owner), '-RunId', run_id,
               '-SimionExe', str(simion), *extra]
    try:
        return _run_cli(command, cwd=fixture, env=env, capture_output=True,
                        text=True, encoding='utf-8', timeout=timeout)
    except subprocess.TimeoutExpired as error:
        evidence_root = Path(env.get('OATOF_TEST_DIAGNOSTICS_ROOT',
                                    Path(tempfile.gettempdir()) / 'oatof_fixture_diagnostics'))
        evidence_root.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix='mass-native-timeout-', dir=evidence_root))
        try:
            shutil.copytree(fixture.parent, destination / 'fixture')
            for name, payload in (('stdout', error.output), ('stderr', error.stderr)):
                raw = payload.encode('utf-8') if isinstance(payload, str) else payload or b''
                (destination / f'{name}.bin').write_bytes(raw)
                (destination / f'{name}.utf8.txt').write_text(
                    raw.decode('utf-8', errors='replace'), encoding='utf-8')
            (destination / 'timeout.json').write_text(json.dumps(dict(
                argv=command, run_id=run_id, timeout_seconds=timeout,
                original_exception=type(error).__name__,
                evidence_includes=('run_config', 'operation/completion/capture',
                                   'process usage/wait receipts', 'cleanup and capacity receipts'))),
                encoding='utf-8')
            error.fixture_diagnostics = str(destination)
            error.add_note(f'Mass-native timeout evidence: {destination}')
        except Exception as diagnostic_error:
            error.add_note(f'Mass-native timeout evidence secondary failure: {diagnostic_error!r}')
        raise


class MassSpectrumReanalysisTests(unittest.TestCase):
    def test_consumed_projection_rejects_unsealed_tampered_and_incomplete_records(self):
        from msplatform.execution.capacity_ledger import record_capacity_object
        from msplatform.execution.manifest_publication import publish_run_manifest
        from msplatform.workflows.single_reflection_mass_spectrum_study import select_analysis_source as select_source

        with tempfile.TemporaryDirectory() as temporary:
            artifacts, source, config, outputs = sealed_mass_source(Path(temporary))
            selected = select_source(source, artifacts)
            self.assertEqual(len(selected['exports']), 11)
            self.assertEqual(selected['run_id'], source.name)
            for name, change, message in (
                ('hit', lambda: (source/'results/simion_summary.json').write_text('{"Hit":11}', encoding='utf-8'), 'full-mother'),
                ('report', lambda: (source/'logs/m100.report.txt').write_text('DETECTED=3/4', encoding='utf-8'), 'DETECTED'),
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
            run_id = '20261031_100100__analysis__python__mass-frozen-worker'
            result = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly',
                '-SourceRunPath', str(source), '-RunId', run_id, '-PythonExe', sys.executable,
                '-AnalysisNewBytes', str(8*1024*1024)], cwd=fixture, env=env,
                capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            child = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}'
            code = child/'inputs/code'
            inventory_path = child/'inputs/code_inventory.json'
            inventory = json.loads(inventory_path.read_text(encoding='utf-8-sig'))
            frozen_before = {str(p.relative_to(code)): p.read_bytes() for p in code.rglob('*') if p.is_file()}
            paths = [item['relative_path'] for item in inventory['files']]
            self.assertIn('msplatform/analysis/peak_metrics.py', paths)
            self.assertIn('msplatform/execution/inputs.py', paths)
            self.assertIn('msplatform/workflows/single_reflection_mass_spectrum.py', paths)
            self.assertIn('msplatform/results/single_reflection_particle_table.py', paths)
            self.assertEqual(paths.count('msplatform/analysis/peak_metrics.py'), 1)
            self.assertEqual(paths.count('msplatform/execution/inputs.py'), 1)
            for unused in ('reference_analysis.py', 'reference_analysis_core.py', 'solver_diagnostics.py', 'mass_spectrum.py'):
                self.assertNotIn(f'projects/{"single_reflection_oa_tof_mass_analyzer"}/analysis/{unused}', paths)
            schemas = {path.relative_to(REPO).as_posix(): path
                       for path in (REPO/'src/msplatform').rglob('*.schema.json')}
            frozen = {item['relative_path']: item for item in inventory['files']
                      if item['relative_path'].endswith('.schema.json')}
            self.assertTrue(schemas)
            expected_schemas = {key.removeprefix('src/') for key in schemas}
            self.assertEqual(set(frozen), expected_schemas)
            for relative, path in schemas.items():
                relative = relative.removeprefix('src/')
                with self.subTest(schema=relative):
                    original_bytes = path.read_bytes()
                    self.assertEqual((code/relative).read_bytes(), original_bytes)
                    self.assertEqual((code/relative).stat().st_size, len(original_bytes))
                    self.assertEqual(frozen[relative]['sha256'].upper(),
                                     hashlib.sha256(original_bytes).hexdigest().upper())
            selection = child/'inputs/source_selection.json'
            bootstrap = ("import runpy,sys;from pathlib import Path;root=Path(sys.argv[1]);"
                         "worker=root/'msplatform/workflows/single_reflection_mass_spectrum_worker.py';"
                         "worker.is_file() or (_ for _ in ()).throw(FileNotFoundError(f'Frozen worker is absent: {worker}'));"
                         "sys.path.insert(0,str(root));sys.argv=sys.argv[2:];"
                         "runpy.run_module('msplatform.workflows.single_reflection_mass_spectrum_worker',"
                         "run_name='__main__')")
            command = [sys.executable, '-I', '-B', '-c', bootstrap, str(code), 'mass-spectrum-analysis',
                       '--selection', str(selection), '--output', str(root/'second-output'),
                       '--code-root', str(code)]
            repeated = _run_cli(command, cwd=root, capture_output=True, text=True,
                                      encoding='utf-8', timeout=45)
            self.assertEqual(repeated.returncode, 0, repeated.stdout+repeated.stderr)
            output = root/'second-output'
            with (output/'mass_spectrum_particles.csv').open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(rows)
            self.assertTrue(all(abs(float(row['detector_x_mm'])-.1) < 1e-12 for row in rows))
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes()
                                        for p in source.rglob('*') if p.is_file()})
            self.assertFalse(list(code.rglob('__pycache__')))
            self.assertEqual(frozen_before, {str(p.relative_to(code)): p.read_bytes()
                                             for p in code.rglob('*') if p.is_file()})
            for index, relative in enumerate(('msplatform/workflows/single_reflection_mass_spectrum_worker.py',
                             'msplatform/workflows/single_reflection_mass_spectrum.py',
                             'msplatform/results/single_reflection_particle_table.py',
                             'src/msplatform/components/single_reflection_oa_tof/config/resolved_geometry.json')):
                target = code/relative
                original = target.read_bytes()
                try:
                    for missing in (True, False):
                        with self.subTest(relative=relative, missing=missing):
                            if missing:
                                target.unlink()
                            else:
                                target.write_bytes(original+b'\n# tampered\n')
                            failure_output = root/f'negative-{index}-{missing}'
                            failure_command = list(command)
                            failure_command[failure_command.index('--output')+1] = str(failure_output)
                            refused = subprocess.run(failure_command, cwd=root, capture_output=True,
                                                     text=True, encoding='utf-8', timeout=30)
                            self.assertNotEqual(refused.returncode, 0)
                            if missing:
                                self.assertRegex(refused.stderr, 'FileNotFoundError|ModuleNotFoundError|ImportError')
                                self.assertIn(Path(relative).stem, refused.stderr)
                            else:
                                self.assertIn(f'Frozen mass-spectrum source identity differs: {relative}', refused.stderr)
                            self.assertFalse(failure_output.exists())
                            target.write_bytes(original)
                finally:
                    target.write_bytes(original)
            csv_path = source/'results/simion_particles.csv'
            text = csv_path.read_text(encoding='utf-8').replace('1,100,1,', '99,100,1,', 1)
            csv_path.write_text(text, encoding='utf-8')
            bad = _run_cli(command, cwd=root, capture_output=True, text=True,
                                 encoding='utf-8', timeout=30)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('exceeds the mixed-species mother population', bad.stderr)
            output_before = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
            code.rename(root/'removed-core')
            missing = _run_cli(command, cwd=root, capture_output=True, text=True,
                                     encoding='utf-8', timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertNotIn('exceeds the mixed-species mother population', missing.stderr)
            self.assertRegex(missing.stderr, 'ModuleNotFoundError|ImportError|FileNotFoundError')
            self.assertIn(str(Path('inputs') / 'code'), missing.stderr)
            self.assertEqual(output_before, {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()})

    def test_public_reanalysis_refuses_changed_frozen_dependencies_before_analysis(self):
        cases = (
            ('missing_peak', 'msplatform/analysis/peak_metrics.py', True, 'Frozen Python dependency is missing'),
            ('tampered_peak', 'msplatform/analysis/peak_metrics.py', False, 'Frozen Python dependency hash differs'),
            ('tampered_helper', 'msplatform/execution/resources/frozen_python_package.ps1', False, 'Frozen Python dependency hash differs'),
        )
        for case, relative, missing, expected in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                artifacts, source, _, _ = sealed_mass_source(root)
                fixture, owner = mass_analysis_fixture(root)
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
                env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                           MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'),
                           MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'),
                           TEST_MASS_MUTATE=relative, TEST_MASS_MISSING='1' if missing else '')
                run_id = '20261031_100100__analysis__python__mass-child'
                command = ['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                           '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)]
                result = _run_cli(command, cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((root/'mutation_calls').is_file())
                self.assertIn(expected, result.stdout + result.stderr)
                result_dir = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}/results'
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
            result = _run_cli(command, cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            child = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}'
            result_path = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/scratch/workflow_results/{run_id}/result.json'
            assert_managed_terminal(self, result_path)
            completion = json.loads((child/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(len(completion['writer_completion']['operations']), 1)
            self.assertGreater(completion['writer_completion']['operations'][0]['observation']['process_id'], 0)
            self.assertEqual(completion['summary']['solver_native_calls'], 0)
            self.assertEqual(completion['summary']['pa_materializations'], 0)
            self.assertFalse(list(child.rglob('*.pa*')))
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            resumed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization', '-RunId', run_id,
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
                        env['TEST_MASS_FINALIZATION_SENTINEL'] = 'FINALIZATION_SENTINEL'
                    snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
                    command = ['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                               '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)]
                    failed = _run_cli(command, cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
                    self.assertNotEqual(failed.returncode, 0, failed.stdout+failed.stderr)
                    child = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}'
                    result_path = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/scratch/workflow_results/{run_id}/result.json'
                    receipt = json.loads(result_path.read_text(encoding='utf-8-sig'))
                    if case == 'analysis':
                        self.assertIn('reanalysis failed', receipt['exception']['message'])
                        assert_managed_terminal(self, result_path, status='failed')
                    else:
                        self.assertIn('FINALIZATION_SENTINEL', failed.stderr)
                        self.assertEqual(receipt['stage'], 'finalization')
                        self.assertEqual(receipt['resume_action'], 'resume_finalization')
                        completion_before = (child/'results/execution_completion.json').read_bytes()
                        env.pop('TEST_MASS_FINALIZATION_SENTINEL')
                        resumed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization',
                            '-RunId', run_id, '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                            cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
                        self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
                        self.assertEqual(completion_before, (child/'results/execution_completion.json').read_bytes())
                        assert_managed_terminal(self, result_path)
                    self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_resume_rejects_new_science_and_analysis_rejects_ambiguous_inputs(self):
        owner = PROJECT.parents[1]/'workflows/resources/run_mass_spectrum_candidate.ps1'
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
            result = _run_cli(['pwsh', '-NoProfile', '-File', str(script), str(owner), str(root/'cases.json')],
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
            csv_path = source/'results/simion_particles.csv'
            csv_path.write_text(csv_path.read_text(encoding='utf-8').replace('1,100,1,', '99,100,1,', 1), encoding='utf-8')
            (source/'run_manifest.json').unlink()
            publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=_manifest_retention_api)
            snapshot = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'), TEST_MASS_ROOT=str(root),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'),
                       TEST_MASS_RELEASE_SENTINEL='RELEASE_SECONDARY_SENTINEL')
            run_id = '20261031_100400__analysis__python__mass-release-failed'
            result = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                       '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)],
                       cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('mixed-species mother population', result.stderr)
            receipt = json.loads((artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/scratch/workflow_results/{run_id}/result.json').read_text(encoding='utf-8-sig'))
            self.assertIn('mixed-species mother population', receipt['exception']['message'])
            process = json.loads((artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}/logs/operation_0001.process.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(process['host_release']['error'], 'RELEASE_SECONDARY_SENTINEL')
            self.assertIn('Resource owner release is unconfirmed', '\n'.join(receipt['exception']['notes']))
            self.assertEqual(receipt['stage'], 'finalization')
            self.assertTrue(receipt['writers_confirmed'])
            self.assertEqual(receipt['resume_action'], 'inspect_writer_completion')
            self.assertEqual(json.loads((artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}/run_manifest.json').read_text(encoding='utf-8-sig'))['status'], 'checkpoint')
            self.assertEqual(json.loads((artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}/logs/capacity_session.json').read_text(encoding='utf-8-sig'))['status'], 'active')
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
            completed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly', '-SourceRunPath', str(source),
                       '-RunId', run_id, '-PythonExe', sys.executable, '-AnalysisNewBytes', str(8*1024*1024)],
                       cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr+
                (capture.read_text(encoding='utf-8-sig') if capture.is_file() else 'no observer'))
            child = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}'
            self.assertGreater(len(str(child/'inputs/code')), 259)
            observed = json.loads(capture.read_text(encoding='utf-8-sig'))
            self.assertLessEqual(len(observed['cwd']), 259)
            self.assertNotEqual(Path(observed['cwd']), child)
            self.assertEqual(Path(observed['environment']['MASS_SPECTROMETRY_RUN_DIRECTORY']), child)
            self.assertEqual(observed['environment']['MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY'], observed['cwd'])
            self.assertIn(observed['cwd'], observed['stdout'])
            self.assertIn(observed['cwd'], observed['stderr'])
            self.assertTrue((child/'inputs/code/msplatform/workflows/single_reflection_mass_spectrum_worker.py').is_file())
            self.assertFalse(Path(observed['cwd']).exists(), 'Public finalizer did not remove its disposable alias')
            completion = child/'results/execution_completion.json'
            completion_bytes = completion.read_bytes()
            details = json.loads(completion_bytes)
            self.assertGreater(details['summary']['native_path_preparation']['calls'], 0)
            self.assertEqual(details['summary']['solver_native_calls'], 0)
            self.assertEqual(details['summary']['pa_materializations'], 0)
            owner.write_text(original, encoding='utf-8')
            result_path = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/scratch/workflow_results/{run_id}/result.json'
            env['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(root/'different-current-root')
            resumed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization', '-RunId', run_id,
                       '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                       cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn('host ledger differs', resumed.stdout+resumed.stderr)
            self.assertEqual(completion_bytes, completion.read_bytes())
            env['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(artifacts)
            resumed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization', '-RunId', run_id,
                       '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                       cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            self.assertEqual(completion_bytes, completion.read_bytes())
            self.assertEqual(snapshot, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})


class MassSpectrumTestIsolationTests(unittest.TestCase):
    def test_repeated_import_preserves_subprocess_identity_and_strict_decoding(self):
        import importlib
        original = subprocess.run
        command = [sys.executable, '-c', 'import sys;sys.stdout.buffer.write(bytes([255]))']
        import threading
        thread_errors = []
        previous_hook = threading.excepthook
        def capture_thread_error(args):
            if isinstance(args.exc_value, UnicodeDecodeError):
                thread_errors.append(args.exc_value)
            else:
                previous_hook(args)
        threading.excepthook = capture_thread_error
        def assert_decode_failure():
            if os.name == 'nt':
                previous_error_count = len(thread_errors)
                completed = subprocess.run(command, capture_output=True, text=True,
                                           encoding='utf-8', errors='strict',
                                           cwd=Path(__file__).parent, timeout=10)
                self.assertEqual(completed.returncode, 0)
                self.assertGreater(len(thread_errors), previous_error_count)
                self.assertIsInstance(thread_errors[-1], UnicodeDecodeError)
            else:
                with self.assertRaises(UnicodeDecodeError):
                    subprocess.run(command, capture_output=True, text=True,
                                   encoding='utf-8', errors='strict',
                                   cwd=Path(__file__).parent, timeout=10)
        try:
            assert_decode_failure()
            for _ in range(2):
                importlib.reload(sys.modules[__name__])
                self.assertIs(subprocess.run, original)
                assert_decode_failure()
        finally:
            threading.excepthook = previous_hook
        self.assertIs(subprocess.run, original)

    def test_timeout_preserves_run_records_and_restores_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / 'fixture'
            run = fixture / 'artifacts/projects/x/runs/y'
            (run / 'logs').mkdir(parents=True)
            (run / 'run_config.json').write_text('{"run_id":"y"}', encoding='utf-8')
            (run / 'logs/operation_0001.usage.json').write_text('{"status":"running"}', encoding='utf-8')
            original = subprocess.run
            with patch(f'{__name__}._SUBPROCESS_RUN',
                       side_effect=subprocess.TimeoutExpired(['pwsh'], 120, output=b'\xff', stderr=b'stderr')):
                with self.assertRaises(subprocess.TimeoutExpired) as caught:
                    run_mass_native(fixture / 'owner.ps1', fixture, {}, 'y', 'simion')
            self.assertIs(subprocess.run, original)
            evidence = Path(caught.exception.fixture_diagnostics)
            self.assertEqual((evidence / 'stdout.bin').read_bytes(), b'\xff')
            self.assertEqual((evidence / 'stderr.bin').read_bytes(), b'stderr')
            self.assertEqual((evidence / 'fixture/fixture/artifacts/projects/x/runs/y/run_config.json').read_text(),
                             '{"run_id":"y"}')
            self.assertTrue((evidence /
                'fixture/fixture/artifacts/projects/x/runs/y/logs/operation_0001.usage.json').is_file())


class MassSpectrumNativeLifecycleTests(unittest.TestCase):
    def test_retired_mass_cli_run_and_resume_start_no_owner_or_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, owner, artifacts, simion, leaf = mass_native_fixture(root)
            env = mass_native_environment(root, fixture, artifacts, simion, leaf, Path(sys.executable))
            for index, options in enumerate(((), ('-ResumeAfterComsol',),
                                             ('-ResumeAfterComsol', '-SourceRunPath', str(root/'historical')))):
                run_id = f'20261116_10000{index}__sim__cross__mass-retired'
                with self.subTest(options=options):
                    result = run_mass_native(owner, fixture, env, run_id, simion, *options)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Legacy mass-spectrum run/resume is retired; use msplatform run with a mass_scan recipe',
                                  result.stdout+result.stderr)
                    self.assertFalse((artifacts/'components/single_reflection_oa_tof_mass_analyzer/runs'/run_id).exists())
                    self.assertFalse((root/'comsol-capture.jsonl').exists())
                    self.assertFalse((root/'simion-capture.json').exists())






class MassSpectrumInputAdmissionTests(unittest.TestCase):
    def test_workspace_context_and_final_publication_preserve_package_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts, source, _, _ = sealed_mass_source(root)
            fixture, owner = mass_analysis_fixture(root)
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('MASS_SPECTROMETRY_HOST_RESOURCE_') and key not in ('PYTHONPATH', 'SIMULATION_PYTHON_EXE')}
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root/'execution'),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root/'host.sqlite3'))
            run_id = '20261031_100100__analysis__python__mass-context'
            result_path = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/scratch/workflow_results/{run_id}/result.json'
            completed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ReanalyzeOnly',
                '-SourceRunPath', str(source), '-RunId', run_id, '-PythonExe', sys.executable,
                '-AnalysisNewBytes', str(8*1024*1024)], cwd=fixture, env=env, capture_output=True,
                text=True, encoding='utf-8', timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            child = artifacts/f'components/{"single_reflection_oa_tof_mass_analyzer"}/runs/{run_id}'
            config = json.loads((child/'run_config.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(config['schema_version'], 2)
            self.assertEqual(config['paths']['execution_root'], str(root/'execution'))
            self.assertEqual(config['paths']['host_resource_state_path'], str(root/'host.sqlite3'))
            self.assertEqual(config['capacity_ledger_lifecycle']['artifact_root'], config['paths']['artifact_root'])
            self.assertIn('execution_request', config['inputs'])
            completion = child/'results/execution_completion.json'
            completion_bytes = completion.read_bytes()
            missing = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization',
                '-RunId', 'missing-result', '-ResultPath', str(root/'absent-result.json'),
                '-PythonExe', sys.executable], cwd=fixture, env=env, capture_output=True,
                text=True, encoding='utf-8', timeout=45)
            self.assertNotEqual(missing.returncode, 0)
            env['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(root/'other-artifacts')
            env['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'] = str(root/'other-host.sqlite3')
            from msplatform.execution.context import load_environment
            from msplatform.workflows.single_reflection_mass_spectrum_study import resume_finalization
            other_environment = json.loads((root/'execution-environment.json').read_text(encoding='utf-8-sig'))
            other_environment['policy']['host_state_path'] = str(root/'other-host.sqlite3')
            (root/'other-environment.json').write_text(json.dumps(other_environment), encoding='utf-8')
            wrong_context = load_environment(root/'other-environment.json',
                workspace=root/'other-artifacts', profile='test')
            with self.assertRaisesRegex(ValueError, 'host ledger differs'):
                resume_finalization(wrong_context, run_id=run_id, result_path=result_path)
            env['MASS_SPECTROMETRY_ARTIFACT_ROOT'] = str(artifacts)
            env['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'] = str(root/'host.sqlite3')
            resumed = _run_cli(['pwsh', '-NoProfile', '-File', str(owner), '-ResumeFinalization',
                '-RunId', run_id, '-ResultPath', str(result_path), '-PythonExe', sys.executable],
                cwd=fixture, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            self.assertEqual(completion_bytes, completion.read_bytes())
            script = root/'ideal-publication.ps1'
            script.write_text(r'''param($Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'src/msplatform/execution/resources/run_artifact_support.ps1')
. (Join-Path $Repo 'src/msplatform/execution/resources/workspace_paths.ps1')
$ideal=Join-Path $Repo 'src/msplatform/backends/simion/resources/run_ideal_field_diagnostic.ps1'
$text=[IO.File]::ReadAllText($ideal);$ast=[Management.Automation.Language.Parser]::ParseFile($ideal,[ref]$null,[ref]$null)
$first=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-ceq'$finalConfig'},$true)
$last=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Write-RunJson'-and$n.Extent.Text.Contains('-Value $finalConfig ')},$true)
$block=$text.Substring($first.Extent.StartOffset,$last.Extent.EndOffset-$first.Extent.StartOffset)
$configFile=Join-Path $Root 'ideal.json'
$original=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot (Join-Path $Root 'publication-artifacts') -ExecutionRoot (Join-Path $Root 'publication-exec') -HostResourceStatePath (Join-Path $Root 'publication-host.sqlite3') -Python $Python
Write-RunJson -Path $configFile -Value @{schema_version=2;paths=$original;package_sentinel='keep';artifact_retention=@{class='solver_review'};capacity_ledger_lifecycle=@{artifact_root=$original.artifact_root}} -Depth 20
$runConfig=$configFile;$runInputs=@{science='source-record'};$N=2;$Seed=17;$AnalyzeOnly=$true
$mode=[pscustomobject]@{species=@()};$sourceProvenance=@();$ResumeAfterComsol=$false;$ReanalyzeOnly=$true;$simionMaxTofUs=80
Invoke-Expression $block
$result=Get-Content -LiteralPath $configFile -Raw|ConvertFrom-Json -AsHashtable
if($result.schema_version-ne2-or$result.package_sentinel-cne'keep'-or$result.paths.execution_root-cne$original.execution_root-or$result.paths.host_resource_state_path-cne$original.host_resource_state_path-or$result.capacity_ledger_lifecycle.artifact_root-cne$result.paths.artifact_root-or$result.inputs.science-cne'source-record'){throw 'Final scientific publication discarded package identity'}
'WORKSPACE_PUBLICATION=PASS'
''', encoding='utf-8', newline='\n')
            ideal_environment = dict(os.environ)
            ideal_environment.pop('MASS_SPECTROMETRY_HOST_CONTEXT_JSON', None)
            ideal = _run_cli(['pwsh','-NoProfile','-File',str(script),str(REPO),sys.executable,str(root)],
                cwd=root, env=ideal_environment, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(ideal.returncode, 0, ideal.stdout+ideal.stderr)
            self.assertIn('WORKSPACE_PUBLICATION=PASS', ideal.stdout)

    def test_guard_freshness_and_original_resume_inputs(self):
        from msplatform.workflows import single_reflection_mass_spectrum_study as study
        from tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_mass_spectrum_study import MassSpectrumStudyTests
        for scenario in ('normal', 'stale', 'pending', 'resume', 'foreign_resume'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.enterContext(patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_CONTEXT_JSON': json.dumps({
                    'workspace': str(root), 'python_executable': sys.executable,
                    'host_state_path': str(root/'host.sqlite3'),
                    'policy_path': str(REPO/'src/msplatform/execution/resources/host_resource_policy.json')})}))
                if scenario in ('resume', 'foreign_resume'):
                    artifacts, source, _, _ = sealed_mass_source(root)
                    before = {path.relative_to(source): path.read_bytes()
                              for path in source.rglob('*') if path.is_file()}
                    selected = study.select_analysis_source(source, artifacts)
                    self.assertEqual(Path(selected['inputs']['resolved_geometry']['path']),
                                     source/'inputs/resolved_geometry.json')
                    self.assertEqual(before, {path.relative_to(source): path.read_bytes()
                                              for path in source.rglob('*') if path.is_file()})
                    if scenario == 'foreign_resume':
                        manifest = json.loads((source/'run_manifest.json').read_text(encoding='utf-8-sig'))
                        config = json.loads((source/'run_config.json').read_text(encoding='utf-8-sig'))
                        config['inputs']['resolved_geometry'] = str(root/'outside-resolved.json')
                        with self.assertRaisesRegex(ValueError, 'input binding differs'):
                            study._selected_input(manifest, config, source, 'resolved_geometry')
                    continue
                values = MassSpectrumStudyTests().inputs(root)
                resolved = root/'resolved.json'
                resolved.write_bytes(values['resolved_geometry'].read_bytes())
                values['resolved_geometry'] = resolved
                if scenario == 'stale':
                    resolved.write_bytes(resolved.read_bytes()+b' ')
                if scenario == 'pending':
                    pending = root/'pending.json'
                    pending.write_text(json.dumps({'lifecycle_status': 'formal_revalidation_pending'}), encoding='utf-8')
                    values['project_config'] = pending
                arguments = dict(project_config=values['project_config'], formal_assets=values['formal_assets'],
                    formal_mph=values['formal_mph'], formal_asset_manifest=values['formal_asset_manifest'],
                    baseline=values['baseline'], formal_mode=values['formal_mode'],
                    solver_numerics=values['solver_numerics'], resolved_geometry=resolved)
                if scenario == 'normal':
                    study.validate_formal_inputs(**arguments)
                    self.assertEqual(resolved.read_bytes(), (PROJECT/'config/resolved_geometry.json').read_bytes())
                elif scenario == 'stale':
                    with self.assertRaisesRegex(ValueError, 'STALE=config/resolved_geometry.json'):
                        study.validate_formal_inputs(**arguments)
                else:
                    with self.assertRaisesRegex(ValueError, 'FORMAL_REVALIDATION_REQUIRED'):
                        study.validate_formal_inputs(**arguments)
