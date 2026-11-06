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
import copy, csv, hashlib, importlib, importlib.metadata, json, math, os, pathlib, shutil, sys, sysconfig
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
from msplatform import execution

root = pathlib.Path.cwd()
environment = execution.load_environment(workspace=root/'machine-study',
    tools={'python': pathlib.Path(sys.executable), 'powershell': root/'explicit-pwsh.exe'},
    policy={'host_state_path': root/'shared-host.sqlite3'})
assert environment.workspace == root/'machine-study'
assert not environment.workspace.exists()
fixture = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
assert not root.is_relative_to(pathlib.Path(fixture['repo_root']))
blocked_source_roots = [pathlib.Path(fixture['repo_root']).resolve(),
                       (root/'source-offline').resolve(), (root/'sdist-offline').resolve()]
def reject_author_files(event, arguments):
    if event == 'open' and arguments and isinstance(arguments[0], (str, bytes)):
        candidate = pathlib.Path(os.fsdecode(arguments[0])).resolve()
        if any(candidate.is_relative_to(source) for source in blocked_source_roots):
            raise AssertionError('installed action accessed an author tree: ' + str(candidate))
sys.addaudithook(reject_author_files)
import importlib.abc
class RejectRepositoryImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'common','projects','integrations'}:
            raise AssertionError('installed action imported a repository owner: ' + fullname)
sys.meta_path.insert(0, RejectRepositoryImports())
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
        'msplatform.assembly.electrode_binding', 'msplatform.execution.context'} <= origins.keys()
for project_id, documents in fixture['standalone_contracts'].items():
    module_name = 'msplatform.components.' + project_id + '.resolve_contract'
    resolver = importlib.import_module(module_name)
    assert resolver.resolve_contract(documents['baseline'], documents['modes'], 'build_only_smoke', 1) == documents['expected']
    origin = pathlib.Path(resolver.__file__).resolve()
    assert origin.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
    origins[module_name] = str(origin)
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.uniform_gas_runtime import export_uniform_runtime
from msplatform.backends.simion.dual_cone_geometry import render_gem
cone = fixture['dual_cone']
assert resolve_geometry(cone['baseline']) == cone['resolved']
assert render_gem(cone['resolved'], cone['numerics']) == cone['gem']
for name in ('uniform_rear_gas_field', 'gas_field_interface'):
    (root/(name+'.json')).write_text(json.dumps(cone[name]), encoding='utf-8')
manifest = export_uniform_runtime(root/'uniform.lua', root/'uniform-manifest.json',
    spec_path=root/'uniform_rear_gas_field.json', interface_path=root/'gas_field_interface.json')
assert manifest['role'] == 'dual_cone_gas_field_export'
assert (root/'uniform.lua').read_bytes() == cone['uniform_lua'].encode()
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_voltage import candidate_authority
from msplatform.backends.comsol import corridor_field
assert callable(corridor_field.compile_request)
from msplatform.backends.comsol.resources import native_resource_text
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract
assert callable(load_contract)
candidate = candidate_authority({'analyzer_electrode_voltages_v': [0.]*20}, dict(s1=1., s2=2., p1=3., p2=4.))
assert [candidate['analyzer_electrode_voltages_v'][i-1] for i in (11,12,13,14,16,17)] == [1.,1.,2.,2.,3.,4.]
assert 'mphload' in native_resource_text('candidate_field.m')
assert 'SIMION' in native_resource_text('export_corridor_scalar_field.m')
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
from msplatform.backends.simion.ip_geometry import render_gem as render_ip_gem
ip = fixture['ip']
projection = native_projection(ip['baseline'], ip['numerics'])
assert len(projection['electrodes']) == 15
assert hashlib.sha256(render_ip_gem(projection).encode()).hexdigest() == ip['gem_sha256']

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

# The real new user slice runs from installed providers and package resources.
from unittest.mock import patch
from msplatform import api, assembly as assembly_api, components as component_api, examples as example_api
from msplatform.backends import simion as simion_api
with patch('subprocess.Popen', side_effect=AssertionError('hidden native action')), \
     patch.object(pathlib.Path, 'mkdir', side_effect=AssertionError('hidden workspace creation')), \
     patch.object(pathlib.Path, 'write_text', side_effect=AssertionError('hidden file write')):
    study = example_api.load_example('rf_oatof_functional_v1')
    actual_components = {name:component_api.resolve_component(request) for name,request in study.component_requests.items()}
    actual_assembly = assembly_api.assemble(study.recipe, actual_components)
    actual_geometry = simion_api.compile_geometry(actual_assembly, numerics=study.geometry_numerics)
    changed = study.to_dict()
    original_release = copy.deepcopy(changed['release'])
    changed['release'] = {'deliberately_invalid_release_not_a_geometry_input': True}
    independent = example_api.StudyDefinition(changed)
    independent_components = {name:component_api.resolve_component(request) for name,request in independent.component_requests.items()}
    independent_assembly = assembly_api.assemble(independent.recipe, independent_components)
    independent_geometry = simion_api.compile_geometry(independent_assembly, numerics=independent.geometry_numerics)
    assert independent_geometry == actual_geometry
    assert study.to_dict()['release'] == original_release
    oa_study = example_api.load_example('oa_two_three_geometric_v1')
    oa_components = {name:component_api.resolve_component(request)
                     for name,request in oa_study.component_requests.items()}
    oa_assembly = assembly_api.assemble(oa_study.recipe, oa_components)
    from msplatform.exporters.step import assembly_geometry_members
    oa_members = assembly_geometry_members(dict(composition_plan=oa_assembly.composition_plan,
                                               components_resolved=oa_assembly.components_resolved))
    assert len(oa_members) == 30
    assert sum(member['representation_role']=='physical_solid' for member in oa_members) == 25
    rf_only = assembly_api.assemble(actual_assembly.composition_plan['recipe'], actual_components,
        local_scope=dict(instance_ids=['multipole'], research_scope='installed independent RF only',
                         boundary_assumptions='explicit local scope; retain complete parent'))
    rf_geometry = simion_api.compile_geometry(rf_only, numerics=dict(component_domains={
        'multipole':dict(cell_mm_xyz=dict(x=.2,y=.2,z=.1))}))
    assert rf_geometry.frontend_geometry['role'] == 'simion_independent_rf_geometry'
    assert set(rf_geometry.frontend_gems) == {'multipole'} and not rf_geometry.downstream_specs
    from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive
    from msplatform.backends.simion.field_execution import plan_fields_execution
    selected = actual_geometry.frontend_geometry['composition_plan']['scope']['instance_ids']
    model_components = {name:actual_geometry.components_resolved[name] for name in selected}
    model_drive = project_resolved_drive(actual_geometry, model_components, pulse=study.drive['pulse'],
        clock=dict(clock_epoch_id='installed-software-fixture', authority_sha256='A'*64,
            phase_reference_instrument_time_us=0.))
    planned_model = compile_prepared_model(actual_geometry, model_components, drive=model_drive, physics=study.physics)
    planned_fields = plan_fields_execution(planned_model, numerics=study.field_numerics)
    assert len(planned_fields['expected_operation_ids']) == 8
    assert planned_fields['expected_operation_ids'][-2:] == ['build_fields','verify_fields']
assert len(actual_components['oatof'].assembly_interface['component_electrodes']) == 42
assert len(actual_geometry.downstream_specs) == 3 and all(actual_geometry.frontend_gems.values())
from msplatform.backends.simion.resources import gem_template_path, native_resource_path, structural_seed_path
from msplatform.execution.resources import resource_path
from msplatform.execution.manifest_records import file_record
from msplatform.execution.terminal_publication import publish_terminal_state
# A declared software data fixture checks installed reading, not native science.
read_root = root/('published_contract_fixture_' + sys.argv[2])
read_root.mkdir()
state_record = file_record(root/'neutral-state.csv')
read_manifest = dict(schema_version=2, role='simulation_run_manifest',
    run_id='installation-software-fixture', project='software_fixture', mode='data_reading', status='failed',
    inputs={}, outputs=[state_record], products={'contract':dict(schema_version=1, kind='trajectory_result',
        status='complete', metadata={'scope':'software_contract_fixture_not_native'}, data={'state':state_record})})
publish_terminal_state(read_root, {'status':'failed'}, read_manifest)
artifact_reference = dict(manifest=file_record(read_root/'run_manifest.json'),product_id='contract')
with patch('subprocess.Popen', side_effect=AssertionError('read started native action')), \
     patch.object(pathlib.Path, 'write_text', side_effect=AssertionError('read wrote data')):
    reopened = api.open_artifact(artifact_reference,expected_kind='trajectory_result')
    assert reopened.data_path('state') == (root/'neutral-state.csv').resolve()
    assert reopened.producer['status'] == 'failed'
# Reuse the repository's manifest-bound comparison fixture as plain data.
# All identities/records below are newly bound to consumer-owned small files.
comparison = fixture['comparison']
def comparison_mother_records(records):
    decoded = {}
    for key, row in records.items():
        if (not isinstance(key,str) or not key.isascii() or not key.isdecimal()
                or str(int(key)) != key or int(key) <= 0
                or type(row['particle_id']) is not int or row['particle_id'] != int(key)
                or int(key) in decoded):
            raise ValueError('installed fixture mother ID must be a canonical decimal key matching its original row')
        decoded[int(key)] = row
    return decoded
comparison_root = root/('comparison_fixture_' + sys.argv[2])
comparison_root.mkdir()
def comparison_write(name, value):
    path = comparison_root/name
    path.write_text(json.dumps(value),encoding='utf-8')
    return file_record(path)
comparison_write('clock_authority.json',comparison['authority'])
(comparison_root/'instrument_epoch_v1.json').write_bytes(bytes.fromhex(comparison['epoch_hex']))
clock_records = dict(clock_authority=file_record(comparison_root/'clock_authority.json'),
    instrument_epoch=file_record(comparison_root/'instrument_epoch_v1.json'))
from msplatform.assembly.handoff import HandoffMother
from msplatform.contracts.clock import ClockIdentity
from msplatform.backends.simion.source import project_source_states
clock = ClockIdentity(comparison['authority']['clock_epoch_id'],comparison['authority']['authority']['sha256'])
mother = HandoffMother(comparison_mother_records(comparison['mother_records']),comparison['mother_fates'])
_, provenance = project_source_states(comparison['states'],mother=mother,clock=clock,
    state_kind='time_snapshot',clock_records=clock_records)
data = dict(clock_records)
data['source_provenance'] = comparison_write('source_provenance.json',provenance)
data['canonical_source_states'] = comparison_write('canonical_source_states.json',comparison['states'])
field_manifest = comparison_write('field_manifest.json',{'role':'software_field_identity_fixture'})
field_reference = dict(manifest=field_manifest,product_id='fields')
data['field_reference'] = comparison_write('field_reference.json',field_reference)
collection = comparison['collection']
collection['source_provenance_record'] = data['source_provenance']
collection['field_reference'] = field_reference
collection['original_mother'] = {key:copy.deepcopy(provenance[key]) for key in
    ('mother_particle_ids','mother_records','mother_fates','clock_authority_sha256','clock_records')}
for event in collection['canonical_events']: event.update(x_mm=1.,y_mm=2.,z_mm=3.)
data['collection'] = comparison_write('collection.json',collection)
comparison_manifest = dict(schema_version=2,role='simulation_run_manifest',status='failed',inputs={},
    outputs=list(data.values()),products={'trajectory':dict(schema_version=1,kind='trajectory_result',status='complete',
        metadata=dict(backend='simion',clock=dict(clock_epoch_id=clock.clock_epoch_id,authority_sha256=clock.authority_sha256),
                      model_identity_sha256='B'*64),data=data)})
comparison_run = comparison_root/'publication';comparison_run.mkdir()
publish_terminal_state(comparison_run,{'status':'failed'},comparison_manifest)
comparison_ref = dict(manifest=file_record(comparison_run/'run_manifest.json'),product_id='trajectory')
with patch('subprocess.Popen',side_effect=AssertionError('comparison launched tool')), \
     patch.object(pathlib.Path,'mkdir',side_effect=AssertionError('comparison created workspace')), \
     patch.object(pathlib.Path,'write_text',side_effect=AssertionError('comparison wrote data')):
    described = api.compare_trajectories(comparison_ref,comparison_ref,selection=comparison['selection'],
        method=dict(schema_version=1,kind='event_time_position'))
assert described['status']=='comparison_completed' and described['matched_particle_ids']==[7,99,123]
assert described['coverage']['left']['denominator_count']==4
assert all(pair['right_minus_left']['instrument_time_us']==0. and
           pair['right_minus_left']['position_components_mm']==[0.,0.,0.] for pair in described['pairs'])
assert described['scientific_qualification']=='not_granted' and 'velocity' in described['unavailable_quantities']
print('INSTALLED_PUBLIC_COMPARISON=PASS')
import msplatform.examples
example_path = pathlib.Path(msplatform.examples.__file__).with_name('rf_oatof_functional_v1.json')
missing_rejected = []
for label, missing_path, action in (
    ('example', example_path, lambda:example_api.load_example('rf_oatof_functional_v1')),
    ('gem', gem_template_path('reflectron'), lambda:simion_api.compile_geometry(actual_assembly,numerics=study.geometry_numerics)),
    ('powershell', resource_path('process_owner.ps1'), lambda:resource_path('process_owner.ps1')),
    ('lua', native_resource_path('build_geometry_iob.lua'), lambda:native_resource_path('build_geometry_iob.lua')),
    ('execution_lua', resource_path('native_run_path.lua'), lambda:resource_path('native_run_path.lua')),
    ('policy', resource_path('host_resource_policy.json'), lambda:resource_path('host_resource_policy.json')),
    ('structural_seed', structural_seed_path(4), lambda:structural_seed_path(4)),
):
    assert missing_path.resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
    hidden_path = missing_path.with_name(missing_path.name+'.missing')
    missing_path.rename(hidden_path)
    try:
        try: action()
        except FileNotFoundError: missing_rejected.append(label)
        else: raise AssertionError('missing installed resource accepted: ' + label)
    finally: hidden_path.rename(missing_path)
schema_path = machine_contracts.SCHEMA_DIR/'multipole_design_request_v4.schema.json'
hidden_schema = schema_path.with_name(schema_path.name+'.missing')
schema_path.rename(hidden_schema)
try:
    import subprocess
    failed = subprocess.run([sys.executable,'-I','-c',
        "from msplatform import components as component_api, examples as example_api; component_api.resolve_component(example_api.load_example('rf_oatof_functional_v1').component_requests['multipole'])"],
        cwd=root, capture_output=True, timeout=30)
    failed_output = (failed.stdout+failed.stderr).decode('utf-8', errors='backslashreplace')
    assert failed.returncode != 0 and schema_path.name in failed_output, failed_output
    missing_rejected.append('schema')
finally: hidden_schema.rename(schema_path)
for name,module in tuple(sys.modules.items()):
    if name.startswith('msplatform.') and getattr(module,'__file__',None):
        origin = pathlib.Path(module.__file__).resolve()
        assert origin.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve()), (name,origin)
        origins[name] = str(origin)
print(json.dumps(dict(executable=sys.executable, cwd=str(root), distribution=distribution.metadata['Name'],
                     version=distribution.version, module_origins=origins, schema_count=len(schemas),
                     schema_reference_count=reference_count, source_count=len(states),
                     mean_tof_us=metrics['mean_tof_us'], std_tof_ns=metrics['std_tof_ns'],
                     actual_providers=sorted({item['project_id'] for item in real['components'].values()}),
                     component_version=3, plan_version=real_plan['schema_version'], binding_version=bindings['schema_version'],
                     strict_peak_metadata_version=strict_metadata['schema_version'], neutral_state_count=state_report['particles'],
                     census_weight_fraction=efficiency['relative_weight_fraction'],
                     installed_platform_components=sorted(actual_components), downstream_spec_count=3,
                     independent_oa_components=sorted(oa_components), independent_oa_member_count=len(oa_members),
                     independent_rf_instances=sorted(rf_geometry.frontend_gems), independent_rf_native_calls=0,
                     geometry_only_native_calls=0, release_independent_geometry=True,
                     prepared_model_compile_only=True, field_plan_only=True, field_execution_performed=False,
                     author_tree_reads_blocked=True,
                     missing_resources_rejected=missing_rejected)))
'''


class InstalledScientificCoreTests(unittest.TestCase):
    def run_command(self, arguments: list[str], *, cwd: Path, environment: dict[str, str],
                    timeout: int = 120) -> str:
        started = time.perf_counter()
        try:
            result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired as error:
            for name, payload in (("stdout", error.stdout), ("stderr", error.stderr)):
                if payload:
                    text = payload.decode('utf-8', errors='backslashreplace') if isinstance(payload, bytes) else payload
                    print(f'INSTALLED_CORE_TIMEOUT_{name.upper()}={text}', flush=True)
            raise
        stdout = result.stdout.decode('utf-8', errors='backslashreplace')
        stderr = result.stderr.decode('utf-8', errors='backslashreplace')
        self.assertEqual(result.returncode, 0, stdout + stderr)
        print(f'INSTALLED_CORE_COMMAND_SECONDS={time.perf_counter() - started:.3f} COMMAND={arguments[:3]}')
        return stdout

    def test_command_transport_preserves_non_utf8_diagnostics_and_failure_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            program = "import sys;sys.stdout.write('accepted');sys.stderr.buffer.write(bytes.fromhex('b5'))"
            output = self.run_command([sys.executable,'-I','-c',program], cwd=Path(directory),
                                      environment=dict(os.environ), timeout=30)
            self.assertEqual(output, 'accepted')
            with self.assertRaises(AssertionError) as failure:
                self.run_command([sys.executable,'-I','-c',program+';sys.exit(3)'], cwd=Path(directory),
                                 environment=dict(os.environ), timeout=30)
            self.assertIn('3 != 0', str(failure.exception))
            self.assertIn('\\xb5', str(failure.exception))

    def test_probe_published_fixture_isolates_both_installed_rounds(self) -> None:
        import ast
        from types import SimpleNamespace

        statements = ast.parse(INSTALLED_PROBE).body
        index = next(index for index, node in enumerate(statements)
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                         and target.id == 'read_root' for target in node.targets))
        # Execute the actual installed probe's path/mkdir statements, not a
        # second approximation or a whole new installation for this guard.
        code = compile(ast.Module(body=statements[index:index + 2], type_ignores=[]), '<actual-installed-probe>', 'exec')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locations = []
            for round_id in ('0', '1'):
                namespace = dict(root=root, sys=SimpleNamespace(argv=['probe', 'fixture.json', round_id]))
                exec(code, namespace)
                locations.append(namespace['read_root'])
            self.assertNotEqual(*locations)
            self.assertTrue(all(path.is_dir() and path.parent == root for path in locations))
            self.assertEqual(set(root.iterdir()), set(locations))
            with self.assertRaises(FileExistsError):
                exec(code, dict(root=root, sys=SimpleNamespace(argv=['probe', 'fixture.json', '0'])))

    def test_actual_installed_comparison_probe_uses_manifest_bound_fixture(self) -> None:
        import ast
        import copy
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform import api
        from msplatform.execution.manifest_records import file_record
        from msplatform.execution.terminal_publication import publish_terminal_state
        statements = ast.parse(INSTALLED_PROBE).body
        start = next(i for i,node in enumerate(statements) if isinstance(node,ast.Assign)
                     and any(isinstance(target,ast.Name) and target.id=='comparison' for target in node.targets))
        end = next(i for i,node in enumerate(statements[start:],start) if isinstance(node,ast.Import)
                   and any(alias.name=='msplatform.examples' for alias in node.names))
        code = compile(ast.Module(body=statements[start:end],type_ignores=[]),'<actual-installed-comparison-probe>','exec')
        with tempfile.TemporaryDirectory() as directory:
            namespace = dict(root=Path(directory),fixture=json.loads(json.dumps({'comparison':self.comparison_probe_fixture()})),
                sys=SimpleNamespace(argv=['probe','fixture.json','0']),file_record=file_record,
                publish_terminal_state=publish_terminal_state,json=json,copy=copy,pathlib=__import__('pathlib'),patch=patch,api=api)
            exec(code,namespace)
            self.assertEqual(namespace['described']['status'],'comparison_completed')
            self.assertTrue(all(type(pid) is int and pid==row['particle_id'] for pid,row in namespace['mother'].records.items()))

    def test_installed_comparison_fixture_id_decode_rejects_noncanonical_or_reshaped_ids(self) -> None:
        import ast
        tree = ast.parse(INSTALLED_PROBE)
        helper = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='comparison_mother_records')
        namespace = {}
        exec(compile(ast.Module(body=[helper],type_ignores=[]),'<actual-installed-fixture-ID-decoder>','exec'),namespace)
        decode = namespace['comparison_mother_records']
        original = {'7':{'particle_id':7},'9007199254740993':{'particle_id':9007199254740993}}
        self.assertEqual(decode(json.loads(json.dumps(original))),{int(key):row for key,row in original.items()})
        self.assertEqual(original,{'7':{'particle_id':7},'9007199254740993':{'particle_id':9007199254740993}})
        invalid = [{'07':{'particle_id':7}},{'+7':{'particle_id':7}},{'7.0':{'particle_id':7}},
                   {'0':{'particle_id':0}},{'-7':{'particle_id':-7}},{'７':{'particle_id':7}},
                   {'7':{'particle_id':'7'}},{'7':{'particle_id':7.0}},{'1':{'particle_id':True}},
                   {'7':{'particle_id':99}},{7:{'particle_id':7}}]
        for records in invalid:
            with self.subTest(records=records),self.assertRaisesRegex(ValueError,'canonical decimal key'):
                decode(records)

    def comparison_probe_fixture(self) -> dict:
        from common.contracts import test_simion_trajectory_analysis as fixtures
        case = fixtures.PublishedTrajectoryAnalysisTests()
        case.setUp()
        try:
            return dict(authority=case.contract,epoch_hex=(case.root/'instrument_epoch_v1.json').read_bytes().hex(),
                mother_records=dict(case.mother.records),mother_fates=list(case.mother.fates),states=case.states,
                collection=case.collection,selection=case.selection)
        finally:
            case.doCleanups()

    def assert_distribution_member(self, name: str) -> None:
        self.assertNotRegex(name, r'(^|/)(tests?|test_support|__pycache__|history|runs)(/|_)')
        # Only the two reviewed, already tracked structural source templates
        # migrate into the wheel. Generated/native payloads remain forbidden.
        template = any(name == path or name.endswith('/' + path) for path in (
            'msplatform/backends/simion/resources/4_instance_seed.iob',
            'msplatform/backends/simion/resources/5_instance_seed.iob'))
        if not template:
            self.assertNotRegex(name, r'\.(pa\d*|pa#|pa-surf|mph|iob|dll|exe|pyc)$')

    def inspect_wheel(self, wheel: Path) -> list[str]:
        expected_schemas = sorted(path.name for path in (REPO_ROOT / 'src/msplatform/contracts/schemas').glob('*.schema.json'))
        config = tomllib.loads((REPO_ROOT/'pyproject.toml').read_text(encoding='utf-8'))
        expected_resources = {
            path.relative_to(REPO_ROOT/'src').as_posix()
            for package,patterns in config['tool']['setuptools']['package-data'].items()
            for pattern in patterns
            for path in (REPO_ROOT/'src'/Path(*package.split('.'))).glob(pattern)
            if path.is_file()
        }
        with zipfile.ZipFile(wheel) as archive:
            inventory = archive.namelist()
            actual_schemas = sorted(Path(name).name for name in inventory if name.endswith('.schema.json'))
            self.assertEqual(actual_schemas, expected_schemas)
            expected_sources = {
                path.relative_to(REPO_ROOT / 'src').as_posix()
                for path in (REPO_ROOT / 'src/msplatform').rglob('*.py')
            }
            actual_sources = set()
            actual_resources = set()
            for name in inventory:
                self.assert_distribution_member(name)
                if '.dist-info/' in name:
                    continue
                self.assertTrue(name.startswith('msplatform/'), name)
                if name.endswith('.py'):
                    actual_sources.add(name)
                else:
                    self.assertIn(name, expected_resources)
                    actual_resources.add(name)
                    self.assertEqual(archive.read(name), (REPO_ROOT / 'src' / name).read_bytes(), name)
                    if name.endswith('_instance_seed.iob'):
                        from msplatform.backends.simion.resources import STRUCTURAL_SEEDS
                        payload = archive.read(name)
                        count = int(Path(name).name.split('_', 1)[0])
                        self.assertEqual((len(payload), hashlib.sha256(payload).hexdigest()), STRUCTURAL_SEEDS[count])
            self.assertEqual(actual_sources, expected_sources)
            self.assertEqual(actual_resources, expected_resources)
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
        retained = os.environ.get('MASS_SPECTROMETRY_INSTALLED_CORE_ARTIFACT_DIR')
        if retained:
            retained = Path(retained)
            self.assertTrue(retained.is_absolute(), 'Retained build directory must be explicit and absolute')
            self.assertFalse(retained.resolve().is_relative_to(REPO_ROOT), 'Retained builds must stay outside source')
            retained.mkdir(parents=True, exist_ok=False)
            (retained / 'acceptance.json').write_text(json.dumps(dict(status='not_completed',
                purpose='ordinary_installation_acceptance', test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())), encoding='utf-8')
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
            standalone_contracts = {}
            for project_id in ('apertured_tube_electron_impact_ion_source',
                               'transverse_helical_filament_wehnelt_electron_gun'):
                project_config = REPO_ROOT / 'projects' / project_id / 'config'
                standalone_contracts[project_id] = {
                    key: json.loads((project_config / filename).read_text(encoding='utf-8'))
                    for key, filename in (('baseline', 'baseline.json'), ('modes', 'numerical_modes.json'),
                                          ('expected', 'resolved_model.json'))}
            from msplatform.backends.simion.dual_cone_geometry import render_gem
            from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.uniform_gas_runtime import export_uniform_runtime
            cone_config = REPO_ROOT / 'projects/dual_cone_tandem_quadrupole_ion_interface/config'
            dual_cone = {name: json.loads((cone_config / filename).read_text(encoding='utf-8'))
                for name, filename in (('baseline', 'baseline.json'), ('resolved', 'resolved_geometry.json'),
                    ('numerics', 'simion_solver_numerics.json'), ('uniform_rear_gas_field', 'uniform_rear_gas_field.json'),
                    ('gas_field_interface', 'gas_field_interface.json'))}
            dual_cone['gem'] = render_gem(dual_cone['resolved'], dual_cone['numerics'])
            for name in ('uniform_rear_gas_field', 'gas_field_interface'):
                (root/(name+'.json')).write_text(json.dumps(dual_cone[name]), encoding='utf-8')
            export_uniform_runtime(root/'fixture-uniform.lua', root/'fixture-uniform-manifest.json',
                spec_path=root/'uniform_rear_gas_field.json', interface_path=root/'gas_field_interface.json')
            dual_cone['uniform_lua'] = (root/'fixture-uniform.lua').read_text(encoding='utf-8')
            from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
            from msplatform.backends.simion.ip_geometry import render_gem as render_ip_gem
            ip_config = REPO_ROOT / 'projects/dual_pressure_rectilinear_ion_processor/config'
            ip = {name: json.loads((ip_config/(name+'.json')).read_text(encoding='utf-8'))
                  for name in ('baseline', 'numerics')}
            ip['gem_sha256'] = hashlib.sha256(render_ip_gem(native_projection(ip['baseline'], ip['numerics'])).encode()).hexdigest()
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps(dict(repo_root=str(REPO_ROOT), recipe=recipe, components=components,
                                              distribution_version=config['project']['version'],
                                              source=spec, expected_states=generate_release_states(spec),
                                              schemas=expected_schemas, provider_layout=provider_layout,
                                              rf_oa_layout=rf_oa_layout, neutral_state=neutral_state,
                                              standalone_contracts=standalone_contracts, dual_cone=dual_cone, ip=ip,
                                              comparison=self.comparison_probe_fixture())), encoding='utf-8')
            consumer_python = str(consumer / python_name)
            # Remove both private author trees from their original locations;
            # the isolated probe also forbids reads from these and the live checkout.
            source.rename(root/'source-offline')
            (root/'sdist').rename(root/'sdist-offline')
            for index, candidate in enumerate((wheel, rebuilt_wheel)):
                # The rebuilt wheel has identical metadata and production bytes;
                # replace that distribution without reinstalling unchanged dependencies.
                replacement = ['--force-reinstall', '--no-deps'] if index else []
                self.run_command([consumer_python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheelhouse),
                                  *replacement, '-c', str(REPO_ROOT / 'requirements-lock.txt'), str(candidate)],
                                 cwd=root, environment=environment, timeout=300)
                probe_environment = dict(environment, PATH=str(Path(consumer_python).parent))
                result = self.run_command([consumer_python, '-I', '-c', INSTALLED_PROBE, str(fixture), str(index)],
                                          cwd=root, environment=probe_environment)
                print('INSTALLED_CORE_EVIDENCE=' + result.strip())
            if retained:
                files = []
                for label, artifact in (('wheel', wheel), ('sdist', sdist), ('sdist-rebuilt-wheel', rebuilt_wheel)):
                    destination = retained / label / artifact.name
                    destination.parent.mkdir()
                    shutil.copyfile(artifact, destination)
                    files.append(dict(kind=label, path=str(destination), bytes=destination.stat().st_size,
                        sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
                actual_source = root / 'source-offline'
                source_files = [actual_source / name for name in ('pyproject.toml', 'requirements-lock.txt',
                                'requirements-cad-step-lock.txt', 'README.md') if (actual_source / name).is_file()]
                source_files.extend(path for path in (actual_source / 'src').rglob('*') if path.is_file())
                source_records = [dict(path=path.relative_to(actual_source).as_posix(), bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(source_files)]
                report = dict(status='success', purpose='ordinary_installation_acceptance',
                    test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    artifacts=files, actual_build_source=source_records)
                (retained / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
                print('INSTALLED_CORE_RETAINED=' + json.dumps(report))


if __name__ == '__main__':
    unittest.main()
