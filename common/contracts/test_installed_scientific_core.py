"""Real wheel/sdist delivery acceptance, with offline build and consumption."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import unittest
import zipfile

from common.integration.test_resolve_assembly import direct_fixture
from common.ion_release.test_cylinder import halton_spec


REPO_ROOT = Path(__file__).resolve().parents[2]

# This runs with -I in a clean installed environment, without repository imports.
INSTALLED_PROBE = r'''
import copy, csv, hashlib, importlib, importlib.metadata, json, math, pathlib, shutil, sys, sysconfig
import numpy as np
from urllib.parse import urljoin
from msplatform.ion_release.release import generate_release_states, materialize_release, validate_materialized_release
from msplatform.assembly.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from msplatform.analysis.peak_metrics import AnalysisSettings, compute_time_peak_metrics, half_height_width
from msplatform.analysis.peak_metrics import compute_nominal_mass_peak_metrics
from msplatform.analysis.particle_census import partition_cohort, subset_efficiency
from msplatform.contracts.particle_state import write_component_particle_state_csv, load_component_particle_state_csv
from msplatform.assembly.electrode_binding import validate_electrode_bindings, ElectrodeKey
from msplatform.contracts import machine_contracts

root = pathlib.Path.cwd()
fixture = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
assert not root.is_relative_to(pathlib.Path(fixture['repo_root']))
assert sys.version_info[:2] == (3, 11)
assert sys.prefix != sys.base_prefix
assert all(shutil.which(tool) is None for tool in ('pwsh', 'powershell', 'simion', 'comsol', 'matlab'))
distribution = importlib.metadata.distribution('mass-spectrometry-analysis')
assert distribution.version == fixture['distribution_version']
origins = {}
for name, module in tuple(sys.modules.items()):
    if name.startswith('msplatform.') and getattr(module, '__file__', None):
        origin = pathlib.Path(module.__file__).resolve()
        assert origin.is_relative_to(pathlib.Path(sys.prefix).resolve()), (name, origin)
        assert origin.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve()), (name, origin)
        origins[name] = str(origin)
assert {'msplatform.ion_release.release', 'msplatform.assembly.resolve_assembly',
        'msplatform.analysis.peak_metrics', 'msplatform.contracts.machine_contracts',
        'msplatform.analysis.particle_census', 'msplatform.contracts.particle_state',
        'msplatform.assembly.electrode_binding'} <= origins.keys()

spec = fixture['source']
states = generate_release_states(spec)
assert states == fixture['expected_states']
assert [state['particle_id'] for state in states] == list(range(1, len(states) + 1))
csv_bytes = []
for index in range(2):
    table, receipt = root / f'states-{index}.csv', root / f'receipt-{index}.json'
    written = materialize_release(spec, table, receipt)
    assert validate_materialized_release(receipt) == written
    assert pathlib.Path(written['state_table']['path']) == table.resolve()
    assert written['state_table']['sha256'] == hashlib.sha256(table.read_bytes()).hexdigest().upper()
    rows = list(csv.DictReader(table.open(encoding='utf-8', newline='')))
    assert list(rows[0]) == ['particle_id','birth_time_s','x_mm','y_mm','z_mm',
                             'vx_m_s','vy_m_s','vz_m_s','mass_amu','charge_state']
    for row, state in zip(rows, states, strict=True):
        assert {key: float(value) for key, value in row.items()} == state
    csv_bytes.append(table.read_bytes())
assert csv_bytes[0] == csv_bytes[1]
for mutation in ('strategy', 'count'):
    invalid = copy.deepcopy(spec)
    if mutation == 'strategy': invalid['sampling']['strategy'] = 'unregistered_strategy'
    else: invalid['particle_count'] = 0
    try: generate_release_states(invalid)
    except ValueError: pass
    else: raise AssertionError('invalid source accepted')

recipe, components = fixture['recipe'], fixture['components']
before = copy.deepcopy((recipe, components))
parent = compile_assembly_layout(recipe, components)
assert (recipe, components) == before
check = parent['connection_checks'][0]
assert check['upstream_center_mm'] == [0, -68, 32]
assert check['downstream_center_mm'] == [0, -67, 32]
assert check['upstream_outward_normal'] == [0, 1, 0]
assert check['downstream_outward_normal'] == [0, -1, 0]
assert check['gap_mm'] == 1
snapshot = copy.deepcopy(parent)
declaration = dict(instance_ids=['guide'], research_scope='installed guide test',
                   boundary_assumptions='downstream metal omitted')
local = derive_assembly_scope(parent, local_scope=declaration)
assert parent == snapshot and local['recipe'] == parent['recipe']
provider = fixture['provider_layout']
actual = compile_assembly_layout(provider['recipe'], provider['components'])
assert actual == provider['expected_layout']
assert actual['connection_checks'][0]['gap_mm'] == 1.
assert {item['project_id'] for item in provider['components'].values()} == {'rf_multipole_ion_optics'}

real = fixture['rf_oa_layout']
assert {item['project_id'] for item in real['components'].values()} == {'rf_multipole_ion_optics', 'orthogonal_accelerator'}
assert all(item['schema_version'] == 3 for item in real['components'].values())
real_plan = compile_assembly_layout(real['recipe'], real['components'])
assert real_plan == real['expected_layout'] and real_plan['schema_version'] == 5
assert real_plan['connection_checks'][0]['gap_mm'] == 1.
for record in real['provider_inputs'].values():
    assert hashlib.sha256((root / record['path']).read_bytes()).hexdigest() == record['sha256']
bindings = dict(schema_version=2, role='backend_electrode_bindings', backend='simion',
                field_domain_id='installed_real_frontend', provider_inputs=real['provider_inputs'],
                bindings=[dict(instance_id=instance, electrode_group_id=row['electrode_group_id'], native_electrode_id=i)
                          for i, (instance, row) in enumerate(((key, row) for key, interface in real['components'].items()
                                                              for row in interface['component_electrodes']), 1)])
validate_electrode_bindings(real['components'], bindings, field_domain_id=bindings['field_domain_id'],
                            provider_inputs=real['provider_inputs'])
assert ElectrodeKey('oa', 'repeller') != ElectrodeKey('guide', 'repeller')
missing = copy.deepcopy(bindings); missing['bindings'].pop()
try: validate_electrode_bindings(real['components'], missing, field_domain_id=bindings['field_domain_id'], provider_inputs=real['provider_inputs'])
except ValueError: pass
else: raise AssertionError('incomplete installed binding accepted')

partition = partition_cohort([2,7,19], [(19,'exit'),(2,'unknown'),(7,'exit')],
                             categories=('exit','unknown'), relative_weights={2:1.,7:2.,19:3.})
assert partition['mother_particle_ids'] == [2,7,19]
assert partition['counts'] == {'exit':2,'unknown':1} and partition['weight_sums'] == {'exit':5.,'unknown':1.}
efficiency = subset_efficiency([2,7,19],[7,19],[2,7,19],relative_weights={2:1.,7:2.,19:3.})
assert efficiency['count_fraction'] == 2/3 and efficiency['relative_weight_fraction'] == 5/6
state_row = fixture['neutral_state']
state_report = write_component_particle_state_csv(root/'neutral-state.csv', [state_row])
neutral = load_component_particle_state_csv(root/'neutral-state.csv')
assert state_report == neutral.report and neutral.rows[0]['particle_id'] == 91
assert neutral.rows[0]['instrument_time_us'] == 12.5 and neutral.rows[0]['state_event'] == 'snapshot'
assert neutral.rows[0]['phase_rad'] is None

assert local['scope']['kind'] == 'local'
assert local['scope']['boundary_connection_ids'] == ['guide_to_oa']
declaration['instance_ids'] = ['guide', 'oa']
assert derive_assembly_scope(parent, local_scope=declaration)['scope']['kind'] == 'local'
invalid = copy.deepcopy(components)
invalid['guide']['ports']['exit']['outward_normal'] = [0, 0, 2]
try: compile_assembly_layout(recipe, invalid)
except ValueError: pass
else: raise AssertionError('non-unit normal accepted')

assert half_height_width(np.array([-1., 0., 1.]), np.array([0., 1., 0.])) == (1., -.5, .5, 1)
times = np.array([9.90, 9.95, 9.98, 10., 10.02, 10.05, 10.10])
settings = AnalysisSettings()
metrics, _ = compute_time_peak_metrics(times, settings)
assert math.isclose(metrics['mean_tof_us'], 10., rel_tol=0., abs_tol=2e-15)
assert math.isclose(metrics['std_tof_ns'], 65.57438524302, rel_tol=0., abs_tol=1e-10)
assert metrics['direct_fwhm_tof_ns'] > 0
metadata = metrics['analysis_metadata']
assert metadata['sample_sigma_ddof'] == 1
assert metadata['method_id'] == 'common_gaussian_kde_time_v2'
assert metadata['units'] == {'tof':'us', 'time_width':'ns', 'time_density':'1/us'}
assert metadata['settings'] == settings.to_dict()
assert metadata['weight_policy'] == 'equal_positive_relative_weights'
assert metadata['sample_count'] == 7 and metadata['effective_sample_count'] == 7.
assert metadata['scientific_qualification'] == 'not_assessed'
assert metadata['time_reference']['clock_qualification'] == 'unspecified'
assert metadata['mass_axis'] is None
strict, _ = compute_nominal_mass_peak_metrics(times, 100., settings)
strict_metadata = strict['analysis_metadata']
assert strict_metadata['schema_version'] == 2
assert strict_metadata['method_id'] == 'common_gaussian_kde_nominal_mass_v1'
assert strict_metadata['mass_axis']['absolute_calibration'] is False
assert strict_metadata['mass_axis']['mapping_method'] == 'nominal_mean_relative_square_v1'
assert strict_metadata['mass_axis']['nominal_mass_amu'] == 100.
assert strict_metadata['fwhm_definition']['interpolation'] == 'linear'
assert strict_metadata['time_reference']['clock_qualification'] == 'unspecified'
assert strict_metadata['sample_count'] == 7 and strict_metadata['weight_policy'] == 'equal_positive_relative_weights'
assert strict_metadata['scientific_qualification'] == 'not_assessed'
assert strict['nominal_mass_resolution_fwhm'] > 0 and 'mass_resolution' not in strict
try: compute_time_peak_metrics(times, settings, weights=np.arange(1., 8.))
except ValueError: pass
else: raise AssertionError('unequal weights accepted')

schemas = sorted(machine_contracts.SCHEMA_DIR.glob('*.schema.json'))
assert [path.name for path in schemas] == fixture['schemas']
registry = machine_contracts.schema_registry()
schema_ids = [json.loads(path.read_text(encoding='utf-8'))['$id'] for path in schemas]
assert len(schema_ids) == len(set(schema_ids))
reference_count = 0
def check_references(value, base_uri):
    global reference_count
    if isinstance(value, dict):
        if '$id' in value: base_uri = urljoin(base_uri, value['$id'])
        if '$ref' in value:
            registry.resolver(base_uri).lookup(value['$ref'])
            reference_count += 1
        for child in value.values(): check_references(child, base_uri)
    elif isinstance(value, list):
        for child in value: check_references(child, base_uri)
for path in schemas:
    schema = json.loads(path.read_text(encoding='utf-8'))
    check_references(schema, schema['$id'])
assert reference_count > 0
print(json.dumps(dict(executable=sys.executable, cwd=str(root), distribution=distribution.metadata['Name'],
                     version=distribution.version, module_origins=origins, schema_count=len(schemas),
                     schema_reference_count=reference_count, source_count=len(states),
                     mean_tof_us=metrics['mean_tof_us'], std_tof_ns=metrics['std_tof_ns'],
                     actual_providers=sorted({item['project_id'] for item in real['components'].values()}),
                     component_version=3, plan_version=real_plan['schema_version'], binding_version=bindings['schema_version'],
                     strict_peak_metadata_version=strict_metadata['schema_version'], neutral_state_count=state_report['particles'],
                     census_weight_fraction=efficiency['relative_weight_fraction'])))
'''


class InstalledScientificCoreTests(unittest.TestCase):
    def run_command(self, arguments: list[str], *, cwd: Path, environment: dict[str, str],
                    timeout: int = 120) -> str:
        started = time.perf_counter()
        result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                text=True, encoding='utf-8', timeout=timeout, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(f'INSTALLED_CORE_COMMAND_SECONDS={time.perf_counter() - started:.3f} COMMAND={arguments[:3]}')
        return result.stdout

    def assert_distribution_member(self, name: str) -> None:
        self.assertNotRegex(name, r'(^|/)(tests?|test_support|__pycache__|history|runs)(/|_)')
        self.assertNotRegex(name, r'\.(pa\d*|mph|iob|dll|exe|pyc)$')

    def inspect_wheel(self, wheel: Path) -> list[str]:
        expected_schemas = sorted(path.name for path in (REPO_ROOT / 'src/msplatform/contracts/schemas').glob('*.schema.json'))
        with zipfile.ZipFile(wheel) as archive:
            inventory = archive.namelist()
            actual_schemas = sorted(Path(name).name for name in inventory if name.endswith('.schema.json'))
            self.assertEqual(actual_schemas, expected_schemas)
            expected_sources = {
                path.relative_to(REPO_ROOT / 'src').as_posix()
                for path in (REPO_ROOT / 'src/msplatform').rglob('*.py')
            }
            actual_sources = set()
            for name in inventory:
                self.assert_distribution_member(name)
                if '.dist-info/' in name:
                    continue
                self.assertTrue(name.startswith('msplatform/'), name)
                self.assertTrue(name.endswith(('.py', '.schema.json')), name)
                if name.endswith('.py'):
                    actual_sources.add(name)
            self.assertEqual(actual_sources, expected_sources)
            print('INSTALLED_CORE_WHEEL_INVENTORY=' + json.dumps(inventory))
        return expected_schemas

    def rebuild_sdist(self, sdist: Path, wheel: Path, root: Path, build_python: str,
                      environment: dict[str, str]) -> Path:
        unpacked = root / 'sdist'
        unpacked.mkdir()
        with tarfile.open(sdist) as archive:
            for member in archive.getmembers():
                self.assert_distribution_member(member.name)
                self.assertFalse(member.issym() or member.islnk(), member.name)
                self.assertTrue((unpacked / member.name).resolve().is_relative_to(unpacked), member.name)
            archive.extractall(unpacked)
        unpacked_source, = unpacked.iterdir()
        rebuilt = root / 'rebuilt'
        rebuilt.mkdir()
        self.run_command([build_python, '-c', 'from setuptools.build_meta import build_wheel;import sys;build_wheel(sys.argv[1])',
                          str(rebuilt)], cwd=unpacked_source, environment=environment)
        rebuilt_wheel, = rebuilt.glob('*.whl')
        with zipfile.ZipFile(wheel) as original, zipfile.ZipFile(rebuilt_wheel) as reconstructed:
            self.assertEqual(sorted(original.namelist()), sorted(reconstructed.namelist()))
            for name in original.namelist():
                if name.startswith('msplatform/') or name.endswith('.dist-info/METADATA'):
                    self.assertEqual(original.read(name), reconstructed.read(name), name)
        return rebuilt_wheel

    def test_wheel_and_sdist_install_and_compute_outside_worktree(self) -> None:
        self.assertEqual(sys.version_info[:2], (3, 11), 'Python 3.11 is required')
        config = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(prefix='installed-scientific-core-') as directory:
            root = Path(directory).resolve()
            self.assertFalse(root.is_relative_to(REPO_ROOT))
            environment = {key: value for key, value in os.environ.items()
                           if key.upper() not in {'PYTHONPATH', 'PYTHONHOME'}}
            environment.update(PIP_DISABLE_PIP_VERSION_CHECK='1', PYTHONNOUSERSITE='1')
            wheelhouse = Path(environment.get('MASS_SPECTROMETRY_WHEELHOUSE', root / 'wheelhouse')).resolve()
            if 'MASS_SPECTROMETRY_WHEELHOUSE' not in environment:
                wheelhouse.mkdir()
                self.run_command([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
                                  '--dest', str(wheelhouse), '-c', str(REPO_ROOT / 'requirements-lock.txt'),
                                  *config['build-system']['requires'], *config['project']['dependencies']],
                                 cwd=root, environment=environment, timeout=300)
            self.assertTrue(wheelhouse.is_dir(), f'Offline wheelhouse missing: {wheelhouse}')
            environment['PIP_NO_INDEX'] = '1'
            source = root / 'source'
            source.mkdir()
            tracked = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=REPO_ROOT, timeout=30).decode('utf-8').split('\0')
            for name in filter(None, tracked):
                if not (REPO_ROOT / name).is_file():
                    continue
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO_ROOT / name, target)
            builder, consumer = root / 'builder', root / 'consumer'
            for location in (builder, consumer):
                self.run_command([sys.executable, '-m', 'venv', str(location)], cwd=root, environment=environment)
            python_name = Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python')
            build_python = str(builder / python_name)
            self.run_command([build_python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheelhouse),
                              *config['build-system']['requires']], cwd=root, environment=environment)
            tool_metadata = self.run_command([build_python, '-I', '-c',
                'import importlib.metadata,json,sys;print(json.dumps(dict(python=sys.executable,'
                'setuptools=importlib.metadata.version("setuptools"),wheel=importlib.metadata.version("wheel"))))'],
                cwd=root, environment=environment)
            self.assertEqual({key: value for key, value in json.loads(tool_metadata).items() if key != 'python'},
                             {'setuptools': '65.5.0', 'wheel': '0.38.4'})
            print('INSTALLED_CORE_BUILD_TOOLS=' + tool_metadata.strip())
            output = root / 'distribution'
            output.mkdir()
            hook = ('from setuptools.build_meta import build_wheel,build_sdist;'
                    'import sys;output=sys.argv[1];build_wheel(output);build_sdist(output)')
            self.run_command([build_python, '-c', hook, str(output)], cwd=source, environment=environment)
            wheel, = output.glob('*.whl')
            sdist, = output.glob('*.tar.gz')
            expected_schemas = self.inspect_wheel(wheel)
            rebuilt_wheel = self.rebuild_sdist(sdist, wheel, root, build_python, environment)
            recipe, components = direct_fixture()
            spec = halton_spec(7)
            from msplatform.ion_release.release import generate_release_states
            from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
            from projects.rf_multipole_ion_optics.core.component_port import build_assembly_interface
            from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request
            from msplatform.assembly.resolve_assembly import compile_assembly_layout
            request = design_request('octupole')
            resolved = compile_design_request(request, expected_identity=request['identity'])
            component = build_assembly_interface(resolved, geometry_profile_id=None)
            provider_recipe, _ = direct_fixture()
            provider_recipe['recipe_id'] = 'real_rf_faces'
            exit_port = component['ports']['mechanical_exit']
            self.assertEqual(exit_port['outward_normal'], [0., 0., 1.])
            for index, instance in enumerate(provider_recipe['instances']):
                instance['project_id'] = component['project_id']
                instance['transform'].update(from_frame_id=component['local_frame_id'],
                    rotation=[[1,0,0],[0,1,0],[0,0,1]] if index == 0 else [[1,0,0],[0,-1,0],[0,0,-1]],
                    translation_mm=[0,0,0] if index == 0 else [0,0,2*exit_port['center_mm'][2]+1])
            for endpoint in ('upstream', 'downstream'):
                provider_recipe['connections'][0][endpoint]['port_id'] = 'mechanical_exit'
            provider_components = {key: component for key in ('guide', 'oa')}
            provider_layout = dict(recipe=provider_recipe, components=provider_components,
                expected_layout=compile_assembly_layout(provider_recipe, provider_components))
            from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
            from projects.orthogonal_accelerator.tests.analysis.test_assembly_interface import two_zone_requirements, TWO_ZONE_PROFILE
            from common.contracts.test_component_particle_state import valid_row

            oa_requirements = two_zone_requirements()
            oa_component = resolve_assembly_interface(oa_requirements, geometry_profile_id=TWO_ZONE_PROFILE,
                                                      schema_version=3)
            real_recipe, _ = direct_fixture()
            real_recipe['recipe_id'] = 'installed_real_rf_to_oa'
            real_components = {'guide': component, 'oa': oa_component}
            exit_z = exit_port['center_mm'][2]
            side = oa_component['ports']['side_entry']['center_mm']
            for key, instance in zip(('guide', 'oa'), real_recipe['instances'], strict=True):
                interface = real_components[key]
                instance['project_id'] = interface['project_id']
                instance['transform'].update(from_frame_id=interface['local_frame_id'],
                    rotation=[[1,0,0],[0,0,1],[0,-1,0]] if key == 'guide' else [[1,0,0],[0,1,0],[0,0,1]],
                    translation_mm=[0,0,0] if key == 'guide' else [-side[0],exit_z+1-side[1],-side[2]])
            real_recipe['connections'][0]['upstream']['port_id'] = 'mechanical_exit'
            real_recipe['connections'][0]['downstream']['port_id'] = 'side_entry'
            provider_inputs = {}
            for key, document in (('guide', resolved), ('oa', oa_requirements)):
                frozen_input = root / f'{key}-provider-input.json'
                frozen_input.write_text(json.dumps(document), encoding='utf-8')
                provider_inputs[key] = dict(path=frozen_input.name,
                    sha256=hashlib.sha256(frozen_input.read_bytes()).hexdigest())
            rf_oa_layout = dict(recipe=real_recipe, components=real_components, provider_inputs=provider_inputs,
                                expected_layout=compile_assembly_layout(real_recipe, real_components))
            neutral_state = valid_row(91)
            neutral_state.update(state_event='snapshot', phase_reference_id='', phase_rad='')
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps(dict(repo_root=str(REPO_ROOT), recipe=recipe, components=components,
                                              distribution_version=config['project']['version'],
                                              source=spec, expected_states=generate_release_states(spec),
                                              schemas=expected_schemas, provider_layout=provider_layout,
                                              rf_oa_layout=rf_oa_layout, neutral_state=neutral_state)), encoding='utf-8')
            consumer_python = str(consumer / python_name)
            for index, candidate in enumerate((wheel, rebuilt_wheel)):
                # The rebuilt wheel has identical metadata and production bytes;
                # replace that distribution without reinstalling unchanged dependencies.
                replacement = ['--force-reinstall', '--no-deps'] if index else []
                self.run_command([consumer_python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheelhouse),
                                  *replacement, '-c', str(REPO_ROOT / 'requirements-lock.txt'), str(candidate)],
                                 cwd=root, environment=environment, timeout=300)
                probe_environment = dict(environment, PATH=str(Path(consumer_python).parent))
                result = self.run_command([consumer_python, '-I', '-c', INSTALLED_PROBE, str(fixture)],
                                          cwd=root, environment=probe_environment)
                print('INSTALLED_CORE_EVIDENCE=' + result.strip())


if __name__ == '__main__':
    unittest.main()
