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
import copy, csv, hashlib, importlib, importlib.metadata, json, math, os, pathlib, shutil, subprocess, sys, sysconfig
import numpy as np
from urllib.parse import urljoin
from msplatform.ion_release.release import generate_release_states, materialize_release, validate_materialized_release
from msplatform.assembly.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from msplatform.workflows.connection_inputs import resolve_assembly_recipe, verify_composition_plan
from msplatform.analysis.peak_metrics import AnalysisSettings, compute_time_peak_metrics, half_height_width
from msplatform.analysis.peak_metrics import compute_nominal_mass_peak_metrics
from msplatform.analysis.particle_census import partition_cohort, subset_efficiency
from msplatform.analysis.pulse_selection import select_actual_occupancy_pulse
from msplatform.backends.simion.standalone_pa_composition import PaHeader, compose_standalone_pa, read_pa_header, validate_standalone_pa_payload
from msplatform.contracts.particle_state import write_component_particle_state_csv, load_component_particle_state_csv
from msplatform.assembly.electrode_binding import validate_electrode_bindings, ElectrodeKey
from msplatform.contracts import machine_contracts
from msplatform import execution
from msplatform.workflows.multipole_ip.prepare import prepare as prepare_multipole_ip, load_request as load_multipole_ip_request
from msplatform.backends.simion import rf_observations

root = pathlib.Path.cwd()

# Read the same explicit CSV ABI used by the installed local frontend runtime.
from msplatform.backends.simion.source import load_initial_state
source_record_probe = root / "installed_initial_state.csv"
source_record_probe.write_text("particle_id,instrument_time_us,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s\n"
                               "37,0,1000,-250,0\n7,12.5,-125,2000,3.5\n", encoding="utf-8-sig")
source_record_bytes = source_record_probe.read_bytes()
assert load_initial_state(source_record_probe) == ([0., 12.5], [37, 7], [[1., -.25, 0.], [-.125, 2., .0035]])
assert source_record_probe.read_bytes() == source_record_bytes
assert load_initial_state.__module__ == "msplatform.backends.simion.source"
deployment = dict(schema_version=1, role='execution_environment',
    tools={'python': sys.executable, 'powershell': 'explicit-pwsh.exe'},
    policy={'host_state_path': 'shared-host.sqlite3'},
    profiles={'standard': {'stage_policy_path': 'stages.json',
        'overrides': {'export_cad': {'limits': {'wall_clock_seconds': 700}}}}})
stage = dict(limits=dict(wall_clock_seconds=600, transient_run_directory_bytes=104857600,
    process_tree_working_set_bytes=4294967296, minimum_system_available_memory_bytes=1073741824,
    compact_final_retained_bytes=104857600, automatic_retry_count=0),
    artifact_retention={'policy_version': 1, 'class': 'solver_review', 'reason': 'Installed deployment probe'})
(root/'machine.json').write_text(json.dumps(deployment), encoding='utf-8')
(root/'stages.json').write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy',
    stages={'export_cad': stage})), encoding='utf-8')
environment = execution.load_environment(root/'machine.json', workspace=root/'machine-study',
    profile='standard', overrides={'export_cad': {'limits': {'wall_clock_seconds': 900}}})
from msplatform.execution.stage_policy import read_stage_policy
assert read_stage_policy(environment, 'export_cad')[0]['limits']['wall_clock_seconds'] == 900
assert environment.environment['profile'] == 'standard'
assert environment.host_state_path == root/'shared-host.sqlite3'
assert environment.powershell_executable == root/'explicit-pwsh.exe'
assert environment.workspace == root/'machine-study'
assert not environment.workspace.exists()
fixture = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
assert not root.is_relative_to(pathlib.Path(fixture['repo_root']))
blocked_source_roots = [pathlib.Path(fixture['repo_root']).resolve(),
                       (root/'source-offline').resolve(), (root/'sdist-offline').resolve()]
blocked_source_roots.extend(pathlib.Path(value).resolve() for value in fixture.get('additional_blocked_source_roots', []))
blocked_source_roots.extend(pathlib.Path(value).resolve() for value in fixture.get('author_source_roots', []))
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
# Recorded local analysis: synthetic logs, no solver or owner.
from msplatform.workflows.local_frontend import analyze as local_analyzer, focus as local_focus, figures as local_figures
from msplatform.workflows.single_reflection_flight import checkpoint_diagnostics
for analyzer_module in (local_analyzer, local_focus, local_figures, checkpoint_diagnostics):
    assert pathlib.Path(analyzer_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
analysis_round = sys.argv[2]
analyzer_results = []
for case_index, analysis_case in enumerate(fixture['recorded_frontend_analysis']):
    analysis_run = pathlib.Path(analysis_case['existing_run']) if 'existing_run' in analysis_case else root / ('recorded-analysis-' + analysis_round + '-' + str(case_index))
    if 'existing_run' not in analysis_case:
        analysis_run.mkdir()
        for relative, content in analysis_case['files'].items():
            target = analysis_run / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes.fromhex(content))
    analysis_log = analysis_run / analysis_case['log']
    before_analysis = {str(path):path.read_bytes() for path in analysis_run.rglob('*') if path.is_file()}
    assert analysis_case['kind'] == 'local', 'unsupported recorded analyzer case'
    analysis_summary = local_analyzer.analyze_local_frontend(analysis_run, [analysis_log],
        phase='discovery', shared_times_us=[0.,.5,1.,2.,3.])
    analysis_output = analysis_run/'results/local_frontend/discovery'
    expected_exit = analysis_case['expected_exit']
    assert (analysis_summary['mother_count'],analysis_summary['exit_count'],analysis_summary['loss_count']) == (3,expected_exit,3-expected_exit)
    assert analysis_summary['exit_efficiency']['denominator_particle_ids'] == [3,11,67]
    assert (analysis_output/'shared_time_distributions.png').is_file()
    assert before_analysis == {str(path):path.read_bytes() for path in analysis_run.rglob('*') if str(path) in before_analysis}
    if 'old_expected' in analysis_case:
        actual_records = {path.relative_to(analysis_run).as_posix():path.read_bytes().hex()
                          for path in (analysis_run/'results').rglob('*') if path.suffix in {'.json','.csv'}}
        assert actual_records == analysis_case['old_expected'], sorted(set(actual_records)^set(analysis_case['old_expected']))
    analyzer_results.append(dict(kind=analysis_case['kind'],mother=3,exit=expected_exit,non_exit=3-expected_exit))
for missing_analyzer in (local_analyzer,local_focus,local_figures,checkpoint_diagnostics):
    missing_path = pathlib.Path(missing_analyzer.__file__)
    missing_hold = missing_path.with_suffix('.analyzer-probe-held')
    missing_path.rename(missing_hold)
    try:
        fresh = subprocess.run([sys.executable,'-I','-B','-c',
            'import importlib,sys; importlib.import_module(sys.argv[1])', missing_analyzer.__name__],
            cwd=root,capture_output=True,text=True,timeout=30,check=False)
        assert fresh.returncode != 0 and missing_analyzer.__name__.split('.')[-1] in fresh.stderr
    finally:
        missing_hold.rename(missing_path)
# End recorded local analysis.

# The withdrawn cooled feature has no installed executable modules or resources.
from importlib.util import find_spec as installed_find_spec
for retired_module in (
    "msplatform.workflows.cooled_frontend",
    "msplatform.components.dual_pressure_rectilinear_ion_processor.cooled_buncher",
    "msplatform.components.dual_pressure_rectilinear_ion_processor.cooled_field_design",
    "msplatform.backends.simion.cooled_frontend_geometry",
    "msplatform.backends.simion.ip_frontend_geometry",
):
    assert installed_find_spec(retired_module) is None, retired_module
from msplatform.backends.simion.resources import NATIVE_RESOURCES as installed_native_resources
assert not {"cooled_frontend.lua", "sample_cooled_field.lua"} & installed_native_resources
from importlib.resources import files as installed_resource_files
for retired_resource in ("cooled_frontend.lua", "sample_cooled_field.lua"):
    assert not installed_resource_files("msplatform.backends.simion").joinpath("resources", retired_resource).is_file()

# IP exact CSG sections: pure installed geometry, not a renderer or native PA.
from msplatform.components.dual_pressure_rectilinear_ion_processor import section_geometry as ip_sections
assert pathlib.Path(ip_sections.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
ip_wedge = dict(shape='convex_polyhedron',vertices_mm=[[x,y,z] for x in (0,10) for y,z in ((0,0),(2,0),(0,2))])
ip_cut_metal = dict(solids=[dict(shape='box',min_mm=[0,-2,-2],max_mm=[10,2,2])],
                    cutouts=[dict(shape='box',min_mm=[3,-1,-3],max_mm=[7,1,3])])
ip_section_results = dict(
    bounds=ip_sections.world_bounds(ip_wedge,0),
    wedge=ip_sections.section(ip_wedge,'cross',5,0),
    centroid=ip_sections.section_centroid(*ip_sections.section(ip_wedge,'cross',5,0)),
    metal=ip_sections.parts(ip_cut_metal,'long',0,0),
    cylinder=ip_sections.section(dict(shape='cylinder_x',x_min_mm=0,x_max_mm=29,
        center_y_mm=0,center_z_mm=2.5,radius_mm=.5),'top',0,0),
    subtract=ip_sections.subtract((0,0,10,10),(3,2,7,8)))
assert ip_section_results['bounds'] == ([-2,0,-2],[0,10,0])
assert ip_section_results['centroid'] == (-2/3,-2/3)
assert sum((c-a)*(d-b) for kind,(a,b,c,d) in ip_section_results['metal']) == 32
assert ip_section_results['cylinder'] == ('rect',(0,-3.,29,-2.))
assert ip_section_results['subtract'] == [(0,0,3,10),(7,0,10,10),(3,0,7,2),(3,8,7,10)]
assert ip_sections.section(ip_wedge,'cross',11,0) is None
ip_module_path=pathlib.Path(ip_sections.__file__)
ip_module_hold=ip_module_path.with_suffix('.missing-test-held')
ip_module_path.rename(ip_module_hold)
try:
    ip_section_missing=subprocess.run([sys.executable,'-I','-B','-c',
        'from msplatform.components.dual_pressure_rectilinear_ion_processor import section_geometry'],
        cwd=root,capture_output=True,text=True,timeout=30,check=False)
    assert ip_section_missing.returncode!=0 and 'section_geometry' in ip_section_missing.stderr
finally:
    ip_module_hold.rename(ip_module_path)
# End installed IP CSG sections.

# G1 pure static gas: explicit inputs, actual installed API, no supplier/owner.
from dataclasses import replace as replace_gas
from msplatform.contracts.gas import (AxisymmetricRZData, BoxDomain, CylindricalDomain,
    GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState, UnboundedDomain)
from msplatform.gas import field as gas_field_api
from msplatform.contracts.rigid_transform import FramedPosition, RigidTransform
composition = (GasSpecies('N2', 28, 1),)
uniform_spec = GasFieldSpec('installed_uniform', 'gas_local', 'uniform', 'n2', composition,
    UnboundedDomain(), GasSource('prescribed','installed_explicit',()), GasState('gas',713,310,(100,0,0)))
placement = RigidTransform('gas_local','gas_world',((0,0,1),(1,0,0),(0,1,0)),(10,20,30))
uniform = gas_field_api.prepare_gas_field(uniform_spec)
posed = gas_field_api.sample_gas(uniform,FramedPosition('gas_world',(13,21,32)),placement=placement)
assert posed.state.pressure_pa == 713 and posed.state.bulk_velocity_m_s == (0,100,0)
assert uniform.spec.source.kind == 'prescribed' and uniform.spec.source.source_id == 'installed_explicit'
proxy = GasSource('prescribed_proxy','explicit_zero',('collisions omitted; not measured vacuum',))
published_source = GasSource('published_cfd','explicit_fixture_producer',(),fixture['gas_field_reference']['manifest'])
assert dict(published_source.reference) == {key:fixture['gas_field_reference']['manifest'][key] for key in ('path','exists','bytes','sha256')}
try: published_source.reference['bytes'] = 0
except TypeError: pass
else: raise AssertionError('published gas identity is mutable')
try: GasSource('published_cfd','missing_reference',())
except ValueError as error: assert 'existing complete source record' in str(error)
else: raise AssertionError('published source without identity was accepted')
assert gas_field_api.prepare_gas_field(replace_gas(uniform_spec,source=proxy,uniform_state=GasState('vacuum',0))).spec.source.assumptions == proxy.assumptions
bath = BoxDomain((30,-2,-2),(130,2,2),(True,False,False),(False,False,False))
valid = BoxDomain((0,-5,-5),(250,5,5),(True,)*3,(True,)*3)
piecewise_spec = replace_gas(uniform_spec,field_id='installed_bath',representation='piecewise_uniform',
    domain=valid,uniform_state=None,regions=(GasRegion('bath',bath,GasState('gas',1,300,(0,0,0))),),
    background_state=GasState('vacuum',0))
piecewise = gas_field_api.prepare_gas_field(piecewise_spec)
assert gas_field_api.sample_gas(piecewise,FramedPosition('gas_local',(30,0,0))).state.pressure_pa == 1
assert gas_field_api.sample_gas(piecewise,FramedPosition('gas_local',(130,0,0))).state.status == 'vacuum'
assert gas_field_api.sample_gas(piecewise,FramedPosition('gas_local',(50,2,0))).number_density_m3 == 0
assert gas_field_api.sample_gas(piecewise,FramedPosition('gas_local',(251,0,0))).state.status == 'outside_domain'
grid = AxisymmetricRZData((0,1),(0,1),(True,True,True,False),
    (100,200,300,None),(300,300,300,None),(0,10,0,None),(100,100,100,None))
grid_spec = replace_gas(uniform_spec,field_id='installed_rz',representation='axisymmetric_rz_grid',
    uniform_state=None,domain=CylindricalDomain(0,1,1),
    interpolation_policy='bilinear_fluid_corner_weight_renormalization_v1')
r_z = gas_field_api.prepare_gas_field(grid_spec,data=grid)
assert gas_field_api.sample_gas(r_z,FramedPosition('gas_local',(.5,0,.5))).state.pressure_pa == 200
assert gas_field_api.sample_gas(r_z,FramedPosition('gas_local',(1,0,1))).state.status == 'no_data'
assert gas_field_api.sample_gas(r_z,FramedPosition('gas_local',(0,0,.5))).state.bulk_velocity_m_s == (0,0,100)
from msplatform.backends.simion import gas_runtime as gas_runtime_api
generated_gas = gas_runtime_api.compile_gas_runtime(r_z)
assert "local nr,nz=2,2" in generated_gas and "geometry_support_not_separately_proved" in generated_gas
assert "function field.sample" in gas_runtime_api.compile_gas_runtime(uniform,placement=placement)
assert "local regions=" in gas_runtime_api.compile_gas_runtime(piecewise)
assert pathlib.Path(gas_runtime_api.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
from msplatform.components.rf_multipole.ideal_transport import rf_waveform_voltage_array, electric_field_xy
from msplatform.components.rf_multipole.family_contract import VoltageDrive
for waveform, expected in (('sine',0.),('cosine',83.)):
    assert float(rf_waveform_voltage_array(VoltageDrive(waveform,83.,0.,0.,1.2e6,0.),np.array([0.]))[0]) == expected
assert electric_field_xy(3,.002,0.,.0001,.0002) == (0.,0.)
assert pathlib.Path(sys.modules['msplatform.components.rf_multipole.ideal_transport'].__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
try: replace_gas(grid,radial_velocity_m_s=(10,10,0,None))
except ValueError as error: assert 'zero radial velocity at r=0' in str(error)
else: raise AssertionError('inconsistent axis data silently accepted')
for gas_module in ('msplatform.contracts.gas','msplatform.gas.field','msplatform.gas.thermodynamics'):
    assert pathlib.Path(sys.modules[gas_module].__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
# A new interpreter cannot satisfy this check from the current process module cache.
gas_field_path = pathlib.Path(gas_field_api.__file__).resolve()
gas_field_hidden = gas_field_path.with_name(gas_field_path.name+'.missing')
gas_field_path.rename(gas_field_hidden)
try:
    import subprocess
    missing_gas = subprocess.run([sys.executable,'-I','-B','-c','from msplatform.gas.field import sample_gas'],
        cwd=root,capture_output=True,text=True,timeout=30)
    assert missing_gas.returncode != 0 and 'msplatform.gas.field' in missing_gas.stderr
finally: gas_field_hidden.rename(gas_field_path)
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
assert {'msplatform.workflows.connection_inputs', 'msplatform.workflows.multipole_ip.prepare', 'msplatform.backends.simion.rf_observations',
        'msplatform.ion_release.release', 'msplatform.assembly.resolve_assembly',
        'msplatform.analysis.peak_metrics', 'msplatform.contracts.machine_contracts',
        'msplatform.analysis.particle_census', 'msplatform.analysis.pulse_selection',
        'msplatform.contracts.particle_state', 'msplatform.assembly.electrode_binding',
        'msplatform.execution.context', 'msplatform.backends.simion.standalone_pa_composition'} <= origins.keys()
for name, maximum, values in (('base', 10., [0., 1., 20., 3.]), ('response', 20., [1., 2., 42., 4.])):
    header = PaHeader(-2, 1, maximum, 2, 2, 1, 0, .1, .1, .1)
    with (root/(name+'-'+sys.argv[2]+'.pa')).open('wb') as stream:
        stream.write(header.pack())
        np.asarray(values, dtype='<f8').tofile(stream)
composed_path = root/('composed-'+sys.argv[2]+'.pa')
composed = compose_standalone_pa(root/('base-'+sys.argv[2]+'.pa'), composed_path,
    [(root/('response-'+sys.argv[2]+'.pa'), .5)], chunk_nodes=2)
assert composed['blocks'] == 2 and composed['refine_performed'] is False
assert read_pa_header(composed_path).max_voltage == 40.
assert validate_standalone_pa_payload(composed_path, chunk_nodes=3)['validated_nodes'] == 4
with composed_path.open('rb') as stream:
    stream.seek(56)
    np.testing.assert_array_equal(np.fromfile(stream, dtype='<f8'), [.5, 2., 81., 5.])
bounds = {axis: dict(minimum_mm=-1., maximum_mm=1., center_mm=0., full_width_mm=2.) for axis in 'xyz'}
observations = {0.: [dict(particle_id=1, x_mm=.9, y_mm=0., z_mm=0.)],
                1.: [dict(particle_id=1, x_mm=0., y_mm=0., z_mm=0.)]}
census = {time: [dict(particle_id=1, status='active')] for time in (0., 1.)}
selected = select_actual_occupancy_pulse(observations, census, [0., 1.], bounds, frame_id='installed')
assert selected['status'] == 'selected' and selected['selected_time_us'] == 1.
unsupported = select_actual_occupancy_pulse({0.: []}, {0.: [dict(particle_id=1, status='numerical_unsupported')]},
    [0.], bounds, frame_id='installed')
assert unsupported['status'] == 'no_supported_eligible_candidate' and unsupported['selected'] is None
for project_id, documents in fixture['standalone_contracts'].items():
    module_name = 'msplatform.components.' + project_id + '.resolve_contract'
    resolver = importlib.import_module(module_name)
    assert resolver.resolve_contract(documents['baseline'], documents['modes'], 'build_only_smoke', 1) == documents['expected']
    origin = pathlib.Path(resolver.__file__).resolve()
    assert origin.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
    origins[module_name] = str(origin)
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import resolve_geometry
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_uniform_rear_gas_field
from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
from msplatform.contracts.gas import GasSpecies
from msplatform.backends.simion.dual_cone_geometry import render_gem
cone = fixture['dual_cone']
assert resolve_geometry(cone['baseline']) == cone['resolved']
assert render_gem(cone['resolved'], cone['numerics']) == cone['gem']
for name in ('uniform_rear_gas_field', 'gas_field_interface'):
    (root/(name+'.json')).write_text(json.dumps(cone[name]), encoding='utf-8')
field, runtime_metadata = prepare_uniform_rear_gas_field(cone['uniform_rear_gas_field'],
    interface=cone['gas_field_interface'],
    composition=(GasSpecies(cone['gas_flow_science']['physics']['gas_species']['species_id'],
        cone['ion_transport_science']['gas']['collision_gas_mass_amu'],1.),),
    spec_record=cone['uniform_source_records']['spec'], interface_record=cone['uniform_source_records']['interface'])
manifest = materialize_gas_runtime(field,root/'uniform.lua',root/'uniform-manifest.json',manifest_metadata=runtime_metadata)
assert manifest['role'] == 'dual_cone_gas_field_export'
assert (root/'uniform.lua').read_bytes() == cone['uniform_lua'].encode()
import msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field as cone_gas_module
import msplatform.backends.simion.gas_runtime as joint_gas_module
assert pathlib.Path(cone_gas_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
assert pathlib.Path(joint_gas_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
for retired in ('gas_runtime.py','uniform_gas_runtime.py'):
    assert not pathlib.Path(cone_gas_module.__file__).with_name(retired).exists()
assert 'sample' in cone['gas_field_interface']['runtime_artifact_contract']['runtime_lua_required_functions']

from msplatform.backends.simion import dual_cone_transport
assert pathlib.Path(dual_cone_transport.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
cone_input = root / ('cone-input-' + sys.argv[2])
cone_input.mkdir()
for name in ('resolved','numerics','ion_transport_science','gas_field_interface','gas_flow_science','source_spec'):
    (cone_input/(name+'.json')).write_text(json.dumps(cone[name]), encoding='utf-8')
cone_outputs = []
for interval in (1,2):
    numerical = json.loads(json.dumps(cone['numerics']))
    numerical['trajectory']['sample_interval_us'] = interval
    numerical_path = cone_input/('numerics-'+str(interval)+'.json')
    numerical_path.write_text(json.dumps(numerical), encoding='utf-8')
    cone_output = root / ('cone-c0-'+sys.argv[2]+'-'+str(interval))
    receipt = dual_cone_transport.prepare_transport(cone_output, mode='c0_gem_smoke',
        resolved_path=cone_input/'resolved.json', numerics_path=numerical_path,
        science_path=cone_input/'ion_transport_science.json', interface_path=cone_input/'gas_field_interface.json',
        gas_science_path=cone_input/'gas_flow_science.json', source_spec_path=cone_input/'source_spec.json')
    assert receipt['qualified_evidence'] is False and receipt['collision_model']=='none'
    assert not list(cone_output.rglob('*.pa*'))
    for name in ('rf_drive_kernel','simion_program'):
        record=receipt['inputs'][name]
        assert pathlib.Path(record['source_path']).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
        assert pathlib.Path(record['frozen_path']).read_bytes()==pathlib.Path(record['source_path']).read_bytes()
    cone_outputs.append(cone_output)
configs=[(output/'solver/simion/run_config.lua').read_text().replace(str(output),'<RUN>') for output in cone_outputs]
assert configs[0].replace('trajectory_sample_interval_us=1,','trajectory_sample_interval_us=2,')==configs[1]
for name in ('dual_cone_tandem.gem','c0_smoke.fly2','source_states.lua','gas_assisted_transport.lua','simion_rf_drive.lua'):
    assert (cone_outputs[0]/'solver/simion'/name).read_bytes()==(cone_outputs[1]/'solver/simion'/name).read_bytes()
# Explicit installed projections; these are not completed native stages.
from msplatform.backends.simion import dual_cone_stages as dual_stage_api
from msplatform.workflows import dual_cone_transport as dual_stage_workflow
from msplatform.backends.simion.model import RF_PHYSICS as dual_stage_physics
from importlib.resources import files as dual_stage_files
assert pathlib.Path(dual_stage_api.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
assert pathlib.Path(dual_stage_workflow.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
dual_stage_numbers={key:copy.deepcopy(cone['numerics'][key]) for key in ('schema_version','role','pa','workbench')}
dual_stage_numbers['pa'].pop('refine_policy')
dual_stage_geometry=dual_stage_api.plan_geometry_stage(resolved=cone['resolved'],numerics=dual_stage_numbers)
assert dual_stage_geometry['sampled_particles']==0 and dual_stage_geometry['refine_calls']==0
assert dual_stage_geometry['fly_calls']==0 and dual_stage_geometry['native_status']=='not_executed'
dual_stage_authority=json.loads(dual_stage_files('msplatform.examples').joinpath('instrument_clock_authority_v1.json').read_text())
dual_stage_clock=dict(clock_epoch_id=dual_stage_authority['clock_epoch_id'],authority_sha256=dual_stage_authority['authority']['sha256'],phase_reference_instrument_time_us=0)
dual_stage_model=dual_stage_api.plan_model_stage(dual_stage_geometry['projection'],electric_field=cone['ion_transport_science']['electric_field'],clock=dual_stage_clock,physics=dual_stage_physics)
assert dual_stage_model['sampled_particles']==0 and dual_stage_model['refine_calls']==0
assert len(dual_stage_model['projection']['native_drive_rows'])==7
assert dual_stage_model['projection']['source_status']=='not_requested'
assert 'simion_model_drive' in dual_stage_api.render_model_stage_configuration(dual_stage_model['projection'])
# P11 uses the same installed proper transform authority, without author inputs.
from msplatform.contracts.rigid_transform import RigidTransform as DualPose, FramedPosition as DualPoint
local_frame=cone['resolved']['coordinate_frame']['frame_id']
placed_transform=DualPose(local_frame,'installed_lab',((0,1,0),(0,0,-1),(-1,0,0)),(12,-7,31))
placed_geometry=dual_stage_api.plan_geometry_stage(resolved=cone['resolved'],numerics=dual_stage_numbers,placement=placed_transform)
assert placed_geometry['projection']==dual_stage_geometry['projection']
placed_model=dual_stage_api.plan_model_stage(dual_stage_geometry['projection'],electric_field=cone['ion_transport_science']['electric_field'],clock=dual_stage_clock,physics=dual_stage_physics,placement=placed_transform)['projection']
assert placed_model['geometry']==dual_stage_model['projection']['geometry']
assert placed_model['identity_sha256']!=dual_stage_model['projection']['identity_sha256']
array_pose,native_pose=dual_stage_api.native_instance_pose(cone['resolved'],cone['numerics'],placed_transform)
array_transform=DualPose.from_contract(array_pose)
assert array_transform.transform_position(DualPoint(array_transform.from_frame_id,(26.5,27.5,5))).coordinates_mm==(14,-10,30)
registration=DualPose(cone['source_spec']['frame_id'],local_frame,((1,0,0),(0,1,0),(0,0,1)),(0,0,0))
try:
    dual_cone_transport.source_placement(cone['resolved'],cone['numerics'],cone['source_spec'],placement=placed_transform)
except ValueError as error:
    assert 'source frame' in str(error)
else:raise AssertionError('posed source accepted an unbound frame')
source_world,_=dual_cone_transport.source_placement(cone['resolved'],cone['numerics'],cone['source_spec'],placement=placed_transform,source_to_device=registration)
assert source_world.from_frame_id==cone['source_spec']['frame_id'] and source_world.to_frame_id=='installed_lab'
from msplatform import components as dual_components, assembly as dual_assembly
from msplatform.exporters.step import assembly_geometry_members as dual_cad_members, step_member_names as dual_cad_names
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface import geometry_members as dual_member_owner, assembly_interface as dual_port_owner
for module in (dual_member_owner,dual_port_owner):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
dual_component=dual_components.resolve_component(dict(provider_id='dual_cone_tandem_quadrupole',design=cone['baseline']))
assert dual_component.resolved_design==cone['resolved']
dual_recipe=dict(schema_version=1,role='assembly_recipe',integration_id='instrument_assembly',recipe_id='installed_dual_cone_cad',assembly_frame_id='installed_lab',position_tolerance_mm=1e-9,angular_tolerance_rad=1e-12,instances=[dict(instance_id='interface',project_id=dual_component.assembly_interface['project_id'],transform=placed_transform.to_contract())],connections=[])
dual_instrument=dual_assembly.assemble(dual_recipe,{'interface':dual_component})
dual_snapshot=dict(composition_plan=dual_instrument.composition_plan,components_resolved=dual_instrument.components_resolved,components_source=dual_instrument.components_source)
dual_members=dual_cad_members(dual_snapshot)
assert len(dual_members)==11 and len(dual_cad_names(dual_snapshot,dual_members))==11
assert {row['electrode_group_id']for row in dual_members}=={row['electrode_group_id']for row in placed_model['native_drive_rows']}
assert dual_component.port('axial_entry')['cross_section']['radius_mm']==1
assert dual_component.port('axial_exit')['center_mm']==[0,0,110.72]

rejected_c0=root/('cone-rejected-registration-'+sys.argv[2])
try:
    dual_cone_transport.prepare_transport(rejected_c0,mode='c0_gem_smoke',
        resolved_path=cone_input/'resolved.json',numerics_path=cone_input/'numerics.json',
        science_path=cone_input/'ion_transport_science.json',interface_path=cone_input/'gas_field_interface.json',
        gas_science_path=cone_input/'gas_flow_science.json',source_spec_path=cone_input/'source_spec.json',
        placement=placed_transform,source_to_device=registration)
except ValueError as error:
    assert 'fixed device-local C0 smoke source' in str(error)
else:raise AssertionError('fixed C0 source silently accepted an unused registration')
assert not rejected_c0.exists()
placed_c0=root/('cone-placed-c0-'+sys.argv[2])
dual_cone_transport.prepare_transport(placed_c0,mode='c0_gem_smoke',
    resolved_path=cone_input/'resolved.json',numerics_path=cone_input/'numerics.json',
    science_path=cone_input/'ion_transport_science.json',interface_path=cone_input/'gas_field_interface.json',
    gas_science_path=cone_input/'gas_flow_science.json',source_spec_path=cone_input/'source_spec.json',placement=placed_transform)
assert json.loads((placed_c0/'input/placement.json').read_text())==placed_transform.to_contract()
assert 'device_placement=' in (placed_c0/'solver/simion/run_config.lua').read_text()

assert callable(dual_stage_workflow.run_gas_assisted_transport)
from msplatform.workflows import dual_cone_stages as dual_managed_api
from msplatform.backends.simion import dual_cone_stage_execution as dual_managed_execution
for module in (dual_managed_api,dual_managed_execution):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
for name in ('build_geometry','prepare_model','solve_fields','track_fields'):
    assert callable(getattr(dual_managed_api,name))
# Named target planning uses the same installed stages, without owner or tools.
assert callable(dual_managed_api.plan_to) and callable(dual_managed_api.run_to)
dual_target_geometry=dual_managed_api.plan_to(target='geometry',request={
    'geometry':dict(resolved=cone['resolved'],numerics=dual_stage_numbers)})
assert dual_target_geometry['stages']==['geometry']
assert dual_target_geometry['request_authorities']==[]
try:dual_managed_api.run_to(dual_target_geometry)
except ValueError as error:assert 'execution context' in str(error)
else:raise AssertionError('native target accepted without execution context')
# Ordinary installed source-only preparation: explicit uniform control and inert
# external SDS files, never a vendor Fly or a claimed CFD/ion result.
dual_sds=root/('inert-sds-'+sys.argv[2]);dual_sds.mkdir()
for name in dual_cone_transport.SDS_FILES:
    (dual_sds/name).write_text('INERT_SDS_NOT_VENDOR')
dual_source_only=root/('cone-source-only-'+sys.argv[2])
dual_source_receipt=dual_cone_transport.prepare_transport(dual_source_only,mode='gas_assisted_transport',
    resolved_path=cone_input/'resolved.json',numerics_path=cone_input/'numerics.json',
    science_path=cone_input/'ion_transport_science.json',interface_path=cone_input/'gas_field_interface.json',
    gas_science_path=cone_input/'gas_flow_science.json',source_spec_path=cone_input/'source_spec.json',
    gas_field_manifest=root/'uniform-manifest.json',collision_sds_dir=dual_sds,
    materialize_geometry=False,model_projection=dual_stage_model['projection'])
assert 'gem' not in dual_source_receipt['inputs']
assert not list(dual_source_only.rglob('*.gem')) and not list(dual_source_only.rglob('*.pa*'))
import csv as dual_source_csv_reader
with (dual_source_only/'input/cylindrical_ion_source.csv').open(newline='') as stream:
    dual_source_rows=list(dual_source_csv_reader.DictReader(stream))
assert len(dual_source_rows)==100 and [int(row['particle_id']) for row in dual_source_rows]==list(range(1,101))
for name in ('model_drive.lua','single_flight_pulse_hook.lua','voltage_waveforms.lua'):
    record=dual_source_receipt['inputs']['model_resource_'+name]
    assert pathlib.Path(record['source_path']).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
    assert pathlib.Path(record['frozen_path']).read_bytes()==pathlib.Path(record['source_path']).read_bytes()
assert (dual_source_only/'solver/simion/model_drive_configuration.lua').is_file()
assert 'model_configuration=' in (dual_source_only/'solver/simion/run_config.lua').read_text()
placed_source_only=root/('cone-placed-source-only-'+sys.argv[2])
placed_receipt=dual_cone_transport.prepare_transport(placed_source_only,mode='gas_assisted_transport',
    resolved_path=cone_input/'resolved.json',numerics_path=cone_input/'numerics.json',
    science_path=cone_input/'ion_transport_science.json',interface_path=cone_input/'gas_field_interface.json',
    gas_science_path=cone_input/'gas_flow_science.json',source_spec_path=cone_input/'source_spec.json',
    gas_field_manifest=root/'uniform-manifest.json',collision_sds_dir=dual_sds,
    materialize_geometry=False,model_projection=placed_model,source_to_device=registration.to_contract())
assert (placed_source_only/'input/cylindrical_ion_source.csv').read_bytes()==(dual_source_only/'input/cylindrical_ion_source.csv').read_bytes()
assert json.loads((placed_source_only/'input/placement.json').read_text())==placed_transform.to_contract()
assert json.loads((placed_source_only/'input/source_to_device.json').read_text())==registration.to_contract()
assert 'device_placement=' in (placed_source_only/'solver/simion/run_config.lua').read_text()
assert not list(placed_source_only.rglob('*.gem')) and not list(placed_source_only.rglob('*.pa*'))


from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_voltage import candidate_authority
from msplatform.backends.comsol import corridor_field
assert callable(corridor_field.compile_request)
from msplatform.backends.comsol.resources import native_resource_directory, native_resource_path, native_resource_text
import msplatform.backends.comsol as comsol_backend
matlab_directory = native_resource_directory().resolve()
assert matlab_directory == pathlib.Path(comsol_backend.__file__).resolve().parent / "matlab"
assert matlab_directory.is_relative_to(pathlib.Path(sysconfig.get_path("purelib")).resolve())
from msplatform.backends.comsol.resources import LAUNCHER_RESOURCES, NATIVE_RESOURCES
from msplatform.backends.comsol.resources import native_resource_path as comsol_resource_path
assert {'ms_stage1_ei_source.m', 'load_ei_source_contract.m', 'comsolstartup.m'} <= NATIVE_RESOURCES
assert {'build_wehnelt_model.m', 'verify_wehnelt_model.m',
        'wehnelt_contract_parameter_bindings.m', 'verify_wehnelt_contract_parameters.m'} <= NATIVE_RESOURCES
assert callable(comsol_backend.build_ei_model) and callable(comsol_backend.build_wehnelt_model)
assert LAUNCHER_RESOURCES == frozenset({'run_comsol_r2025b.ps1', 'resolve_comsol_64.ps1',
    'livelink_environment.ps1', 'livelink_failure_classification.ps1'})
for name in NATIVE_RESOURCES | LAUNCHER_RESOURCES:
    resource = native_resource_path(name).resolve()
    directory = 'launcher' if name in LAUNCHER_RESOURCES else 'matlab'
    assert resource == pathlib.Path(comsol_backend.__file__).resolve().parent / directory / name
    assert resource.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
    assert resource.read_bytes() == native_resource_text(name).encode('utf-8')
    assert resource.stat().st_size > 0
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract
assert callable(load_contract)
candidate = candidate_authority({'analyzer_electrode_voltages_v': [0.]*20}, dict(s1=1., s2=2., p1=3., p2=4.))
assert [candidate['analyzer_electrode_voltages_v'][i-1] for i in (11,12,13,14,16,17)] == [1.,1.,2.,2.,3.,4.]
assert 'mphload' in native_resource_text('candidate_field.m')
assert 'SIMION' in native_resource_text('export_corridor_scalar_field.m')
for name in ('build_and_export_paired_accelerator_field.m', 'oatof_build_accelerator_geometry.m',
             'build_sectioned_geometry.m', 'build_accelerator_grids.m', 'run_paired_accelerator_pulse.m',
             'oatof_read_cartesian_release.m', 'oatof_cpt_solver_policy.m'):
    text = native_resource_text(name)
    assert native_resource_path(name).resolve() == matlab_directory / name
    assert native_resource_path(name).read_bytes() == text.encode('utf-8')
    assert text.startswith('function') and 'mfilename' not in text
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
from msplatform.backends.simion.ip_geometry import render_gem as render_ip_gem

# COOLING_DIAGNOSTICS_INSTALLED_BEGIN
from msplatform.analysis import cooling_diagnostics as cooling_diagnostics
assert pathlib.Path(cooling_diagnostics.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_paths()['purelib']).resolve())
cohort=np.array([[90.,0.,0.],[110.,0.,0.]])
population_diagnostic=cooling_diagnostics.velocity_population_diagnostics(cohort,mass_amu=100.,charge_state=-1,
    reference_velocity_m_s=(100.,0.,0.),relative_weights=None,frame_id='lab',sample_kind='time_snapshot',
    reference_label='explicit nominal bath, not actual sampled gas')
assert population_diagnostic['velocity_covariance_m2_s2'][0][0]==100.
assert population_diagnostic['mean_velocity_m_s']==[100.,0.,0.]
assert population_diagnostic['mean_laboratory_energy_ev']>population_diagnostic['mean_reference_relative_energy_ev']>0.
cooling_path=pathlib.Path(cooling_diagnostics.__file__);cooling_held=cooling_path.with_suffix('.missing-test-held')
cooling_path.rename(cooling_held)
try:
    cooling_missing=subprocess.run([sys.executable,'-I','-B','-c','import msplatform.analysis.cooling_diagnostics'],
        cwd=root,capture_output=True,text=True,timeout=30,check=False)
    assert cooling_missing.returncode!=0 and 'cooling_diagnostics' in cooling_missing.stderr
finally:cooling_held.rename(cooling_path)
# COOLING_DIAGNOSTICS_INSTALLED_END




ip = fixture['ip']
projection = native_projection(ip['baseline'], ip['numerics'])
assert len(projection['electrodes']) == 15
assert hashlib.sha256(render_ip_gem(projection).encode()).hexdigest() == ip['gem_sha256']
# Existing scientific source compiler and explicit unsolved input materializer.
# HS1 is an explicit source input (inert by default); no vendor/physics execution is claimed.
from msplatform.workflows.ion_processor import preparation as ip_preparation
from msplatform.backends.simion.collision_hs1 import adapt_hs1_for_repeat_fly
compiled_ip = ip_preparation.compile_source(ip['preparation_config'])
assert len(compiled_ip['states']) == ip['source']['particle_count']
assert hashlib.sha256(render_ip_gem(compiled_ip['config']['native_projection']).encode()).hexdigest() == ip['gem_sha256']
assert 'workbench_seed_path' not in compiled_ip['config'] and 'native_field' not in compiled_ip['config']
ip_authorities = {}
ip_input_root = root / ('explicit-ip-inputs-' + sys.argv[2])
ip_input_root.mkdir()
for key in ('baseline', 'numerics', 'source', 'acceptance', 'native_operating_point'):
    path = ip_input_root / (key + '.json')
    path.write_text(json.dumps(ip['preparation_config'][key]), encoding='utf-8')
    ip_authorities[key] = path
ip_hs1 = ip_input_root / 'selected_HS1_source.lua'
ip_hs1.write_bytes(bytes.fromhex(ip['hs1_input_bytes_hex']))
assert hashlib.sha256(ip_hs1.read_bytes()).hexdigest() == ip['hs1_input_sha256']
ip_output = root / ('unsolved-ip-inputs-' + sys.argv[2])
ip_output.mkdir()
ip_materialized = ip_preparation.materialize_inputs(ip_output, ip['preparation_config'], configuration_files=ip_authorities, hs1_source=ip_hs1)
assert (ip_output/'simion/processor.fly2').read_text() == compiled_ip['fly2']
assert (ip_output/'simion/source_states.lua').read_text() == compiled_ip['source_states']
assert (ip_output/'inputs/collision_hs1_original.lua').read_bytes() == ip_hs1.read_bytes()
assert (ip_output/'simion/collision_hs1.lua').read_text() == adapt_hs1_for_repeat_fly(ip_hs1.read_text(encoding='utf-8'))
assert not (ip_output/'simion/processor.iob').exists() and not list((ip_output/'simion').glob('*.pa*'))
assert not (ip_output/'simion/iob_seed').exists()
print('INSTALLED_IP_INPUTS=' + json.dumps(dict(hs1_input_kind=ip['hs1_input_kind'], hs1_sha256=ip['hs1_input_sha256'], particles=len(compiled_ip['states']), vendor_execution_count=0)))
from msplatform.backends.simion.resources import native_resource_path as ip_resource
for resource_name in ('runtime.lua', 'build_workbench.lua', 'probe_native_field.lua', 'extraction_force_audit.lua'):
    assert (ip_output/'simion'/resource_name).read_bytes() == ip_resource('ip_' + resource_name).read_bytes()
missing_ip_resource = ip_resource('ip_runtime.lua')
hidden_ip_resource = missing_ip_resource.with_name(missing_ip_resource.name + '.missing')
missing_ip_resource.rename(hidden_ip_resource)
try:
    ip_missing_output = root / ('missing-ip-inputs-' + sys.argv[2])
    ip_missing_output.mkdir()
    try: ip_preparation.materialize_inputs(ip_missing_output, ip['preparation_config'], configuration_files=ip_authorities, hs1_source=ip_hs1)
    except FileNotFoundError as error: assert 'ip_runtime.lua' in str(error)
    else: raise AssertionError('missing installed IP runtime was accepted')
    assert not list(ip_missing_output.iterdir())
finally: hidden_ip_resource.rename(missing_ip_resource)
# Actual canonical manifest-CLI projection of explicit inert owner records.
from msplatform.workflows.ion_processor import field_reference
ip_reference_child = root / ('ip-reference-child-' + sys.argv[2])
for directory in ('inputs', 'simion'):
    (ip_reference_child/directory).mkdir(parents=True, exist_ok=True)
ip_reference_parent = pathlib.Path(ip['field_reference_parent'])
shutil.copyfile(ip_reference_parent/'simion/processor.gem', ip_reference_child/'simion/processor.gem')
ip_reference_model = copy.deepcopy(ip['field_reference_model'])
reference_result = field_reference.bind_native_field(ip_reference_child, ip_reference_model, ip_reference_parent)
assert reference_result['native_field_manifest'] == str(ip_reference_parent/'run_manifest.json')
reference_receipt = json.loads((ip_reference_child/'inputs/native_field_consumption.json').read_text())
assert len(reference_receipt['family_records']) == 18
assert reference_receipt['payload_validation'] == 'launcher_immutable_source_guard_required_before_native_use'
assert not list((ip_reference_child/'simion').glob('*.pa*'))
(ip_reference_child/'inputs/resolved_model.json').write_text(json.dumps(ip['field_reference_model']), encoding='utf-8')
(ip_reference_child/'run_config.json').write_text('{"inputs":{"existing":"keep"}}', encoding='utf-8')
field_reference.adopt_native_field(ip_reference_child, ip_reference_parent)
assert json.loads((ip_reference_child/'run_config.json').read_text())['inputs']['existing'] == 'keep'
# The actual installed canonical verifier also rejects an incomplete owner publication.
reference_journal = ip_reference_parent / '.run_terminal_publication.json'
reference_journal_before = reference_journal.read_bytes() if reference_journal.exists() else None
reference_journal.write_text('{}', encoding='utf-8')
try:
    import subprocess
    try: field_reference.bind_native_field(ip_reference_child, copy.deepcopy(ip['field_reference_model']), ip_reference_parent)
    except ValueError as error:
        assert str(error) == 'run terminal publication is incomplete; replay its journal'
    else: raise AssertionError('incomplete owner publication was accepted')
finally:
    if reference_journal_before is None: reference_journal.unlink()
    else: reference_journal.write_bytes(reference_journal_before)
# Verify the actual typed verifier is installed and is the workflow's sole implementation.
from msplatform.execution import manifest_verification
assert field_reference.verify_run_manifest is manifest_verification.verify_run_manifest
assert reference_receipt['verification'].startswith('RUN_MANIFEST_VERIFY=PASS SCOPE=consumer_projection ')
assert reference_receipt['verification'].endswith('\n')
verifier_path = pathlib.Path(manifest_verification.__file__).resolve()
hidden_verifier = verifier_path.with_name(verifier_path.name+'.missing')
verifier_path.rename(hidden_verifier)
try:
    import subprocess
    missing_verifier = subprocess.run([sys.executable,'-I','-B','-c',
        'from msplatform.workflows.ion_processor.field_reference import bind_native_field'],
        cwd=root, capture_output=True, text=True, timeout=30)
    assert missing_verifier.returncode != 0 and 'manifest_verification' in missing_verifier.stderr
finally: hidden_verifier.rename(verifier_path)
# A missing canonical owner must not fall back to the retired repository body.
reference_module_path = pathlib.Path(field_reference.__file__)
hidden_reference_module = reference_module_path.with_name(reference_module_path.name+'.missing')
reference_module_path.rename(hidden_reference_module)
try:
    import subprocess
    missing_reference = subprocess.run([sys.executable,'-I','-c',
        'from msplatform.workflows.ion_processor.field_reference import bind_native_field'],
        cwd=root, capture_output=True, text=True, timeout=30)
    assert missing_reference.returncode != 0 and 'field_reference' in missing_reference.stderr
finally: hidden_reference_module.rename(reference_module_path)
from msplatform.components.dual_pressure_rectilinear_ion_processor.timing import derive_native_timing
from importlib.resources import files
from msplatform.backends.simion.resources import native_resource_path
timing = derive_native_timing(ip['baseline'])
assert math.isclose(timing['primary_quench_us'], 7500.)
assert math.isclose(timing['pulse_start_us'], 7500.135135135135)
assert files('msplatform.backends.simion').joinpath('resources', 'native_drive.lua').read_bytes() == ip['native_drive'].encode('utf-8')
for name, count, digest in (
    ('export_paired_accelerator_field.lua', 3746, 'ccf136da2821ec93c1cbcb6335863da1494e041b36860b3011a12cbc30919c29'),
    ('paired_accelerator_pulse.lua', 5516, '007c7847319ced4ebdaf99f0309e819d06c62a96607a1ed1808ce2352029aaf9'),
    ('scientific_event_csv.lua', 1688, '0f74fcbec8cf1a9035dfdd57c43bef85bf4af2a76a65c2813e8f2f02b3cf71c4'),
    ('voltage_waveforms.lua', 814, '7634929290f3e3b4f4c9df3c4559bbc15341d6c087b5363cea248324178f7c2f'),
    ('rf_drive.lua', 6741, '29955e8c9e00cec75d773446eae011d93990068bf2c5a45b6236aac35e86774c'),
    ('single_flight_frontend_hook.lua', 7918, 'aef4acfb520ae2cd73b66d43bf2e9369a049a66478e0d3dd8b4696ef3c85a24a'),
    ('single_flight_pulse_hook.lua', 3913, 'e3ef5a0b08b73e23c566df23f84102052b9f2d45f0ada9ae768094cc6c287d37'),
    ('audit_frontend_working_fields.lua', 5910, 'a3c07078e53a22cf741f3c3d1a415373c7b261b39dc3b89f7c3a345e8a63845f'),
    ('audit_downstream_fields.lua', 2335, '39ea50b054868d6940552b3c049ec8e407f6bd4cbc9ebd6156c70c874c101cdd'),
    ('build_iob.lua', 1260, 'ea609486410f5d8a388cc51a9df193625b8f00356b8a78ce354c222d9eff35d6'),
    ('build_dirichlet_patch_operating_pa.lua', 5359, 'ae69a4ebb153f21652d69a712cab9fe9a19fa4b70c03dfb343f8d169231ea7dd'),
    ('export_standalone_pa.lua', 2592, '2152afe2af738c9cf715518847617ce858fdaef2c874aa29f44fb1f5db93924b'),
    ('export_detached_standalone_pa.lua', 2813, '78985820fb41a696ad4097f973c5dd5888384683ad1551ba7b54bf9f66c9715b'),
):
    payload = native_resource_path(name).read_bytes()
    assert len(payload) == count and hashlib.sha256(payload).hexdigest() == digest
from msplatform.components.dual_pressure_rectilinear_ion_processor.guide_interface import export_guide_contract
from msplatform.contracts.rigid_transform import RigidTransform
guide = export_guide_contract(dict(ip['model'], native_projection=projection), ip['identities'])
assert len(guide['rod_array']['rods']) == 8
from msplatform.backends.comsol.paired_static_field import prepare as prepare_paired_field
paired = fixture['paired_static']
assert prepare_paired_field(root/'paired-request.json', root/'paired-installed') == paired['expected_plan']

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
connection_recipe, connection_components = root/'connection-recipe.json', root/'connection-components.json'
connection_recipe.write_text(json.dumps(recipe), encoding='utf-8')
connection_components.write_text(json.dumps(components), encoding='utf-8')
file_plan = resolve_assembly_recipe(connection_recipe, connection_components, root)
assert {key:value for key,value in file_plan.items() if key != 'input_files'} == parent
connection_plan = root/'connection-plan.json'
connection_plan.write_text(json.dumps(file_plan), encoding='utf-8')
verify_composition_plan(connection_plan, source_root=root)
connection_components.unlink()
try: verify_composition_plan(connection_plan, source_root=root)
except machine_contracts.ContractError as error: assert 'missing' in str(error)
else: raise AssertionError('missing connection provider file accepted')
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
assert [path.name for path in schemas] == fixture['contract_schemas']
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
from msplatform import assembly as assembly_api, components as component_api, examples as example_api
from msplatform import ion_release as ion_release_api
from msplatform.backends import simion as simion_api
with patch('subprocess.Popen', side_effect=AssertionError('hidden native action')), \
     patch.object(pathlib.Path, 'mkdir', side_effect=AssertionError('hidden workspace creation')), \
     patch.object(pathlib.Path, 'write_text', side_effect=AssertionError('hidden file write')):
    import importlib.util
    study = example_api.load_example('rf_oatof_functional_v1')
    release = ion_release_api.sample_release(study.release)
    assert len(release.rows) == 100 and isinstance(release, ion_release_api.ReleaseRealization)
    assert importlib.util.find_spec('msplatform.api') is None
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
                                               components_resolved=oa_assembly.components_resolved,
                                               components_source=oa_assembly.components_source))
    assert len(oa_members) == 30
    assert sum(member['representation_role']=='physical_solid' for member in oa_members) == 25
    from msplatform.backends.simion.oa_compiler import _extent
    from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
    oa_domains = {}
    for instance, design in oa_assembly.components_resolved.items():
        from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
        extents = [_extent(member['shape']) for member in iter_geometry_members(design)]
        bounds = {axis+suffix:fn(b[i][j] for b in extents)+margin for i,axis in enumerate('xyz')
                  for suffix,j,fn,margin in [('_min',0,min,-1.),('_max',1,max,1.)]}
        oa_domains[instance] = dict(cell_mm_xyz=dict(x=.25,y=.25,z=.1),pa_bounds_mm=bounds)
    oa_geometry = simion_api.compile_geometry(oa_assembly, numerics=dict(component_domains=oa_domains))
    oa_drive = dict(clock=dict(clock_epoch_id='installed-OA-model',authority_sha256='A'*64,
        phase_reference_instrument_time_us=0.),groups={instance:{group:dict(kind='static',
        voltage_v=0. if group=='grounded_shield' else 1234.+index) for index,group in enumerate(mapping)}
        for instance,mapping in oa_geometry.frontend_geometry['electrode_bindings'].items()})
    oa_model = compile_prepared_model(oa_geometry, oa_assembly.components_resolved, drive=oa_drive, physics=RF_PHYSICS)
    assert oa_model.document['field_status']=='not_solved' and oa_model.document['source_status']=='not_requested'
    assert set(oa_model.document['drive']['groups'])=={'two','three'} and 'downstream_geometry' not in oa_model.document
    assert not oa_model.document['geometry']['downstream_specs']
    from msplatform.backends.simion.field_execution import plan_fields_execution
    oa_field_graph=plan_fields_execution(oa_model,numerics=dict(refine_policy='vendor_default'))
    assert oa_field_graph['expected_operation_ids']==['materialize_geometry','refine_two','refine_three','audit_fields']
    assert plan_fields_execution(oa_model,numerics=dict(refine_policy='vendor_default'),reuse_fields_reference={})['expected_operation_ids']==['audit_fields']
    oa_invalid=copy.deepcopy(oa_drive);oa_invalid['groups']['two'].pop('repeller')
    try: compile_prepared_model(oa_geometry,oa_assembly.components_resolved,drive=oa_invalid,physics=RF_PHYSICS)
    except ValueError: pass
    else: raise AssertionError('installed OA model accepted a missing actual group')
    rf_only = assembly_api.assemble(actual_assembly.composition_plan['recipe'], actual_components,
        local_scope=dict(instance_ids=['multipole'], research_scope='installed independent RF only',
                         boundary_assumptions='explicit local scope; retain complete parent'))
    rf_geometry = simion_api.compile_geometry(rf_only, numerics=dict(component_domains={
        'multipole':dict(cell_mm_xyz=dict(x=.2,y=.2,z=.1))}))
    assert rf_geometry.frontend_geometry['role'] == 'simion_independent_rf_geometry'
    assert set(rf_geometry.frontend_gems) == {'multipole'} and not rf_geometry.downstream_specs
    from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive, RF_PHYSICS
    rf_model_components = {name:rf_geometry.components_resolved[name] for name in rf_geometry.frontend_geometry['composition_plan']['scope']['instance_ids']}
    rf_model_drive = project_resolved_drive(rf_geometry, rf_model_components,
        clock=dict(clock_epoch_id='installed-RF-model-fixture', authority_sha256='A'*64,
                   phase_reference_instrument_time_us=0.))
    rf_model = compile_prepared_model(rf_geometry, rf_model_components, drive=rf_model_drive, physics=RF_PHYSICS)
    assert 'pulse' not in rf_model.document['drive'] and 'downstream_geometry' not in rf_model.document
    assert rf_model.document['native_frame_id'] == rf_geometry.frontend_geometry['composition_plan']['assembly_frame_id']
    assert rf_model.document['field_status'] == 'not_solved' and rf_model.document['source_status'] == 'not_requested'
    from msplatform.capabilities import capabilities as query_capabilities
    rf_query = query_capabilities(dict(schema_version=1, operation='prepare_model', arguments=dict(
        compiled=rf_geometry, components_resolved=rf_model_components, drive=rf_model_drive, physics=RF_PHYSICS)))
    assert rf_query['contract_status'] == 'accepted' and rf_query['native_qualification'] == 'not_granted'
    assert rf_query['validator'] == 'msplatform.backends.simion.model.compile_prepared_model'
    from msplatform.backends.simion.native_plans import plan_model_preparation
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.execution.resources import resource_path
    from msplatform.io.manifest_records import file_record
    try:
        plan_model_preparation(rf_model, geometry_assets={name:dict(raw_record={},surface_records=[])
            for name in rf_geometry.frontend_gems}, run_directory=root/'RF-plan-only',
            seed_record=file_record(structural_seed_path(1),'required_evidence'),
            native_path_resource=resource_path('native_run_path.lua'))
    except ValueError as error:
        assert 'explicit raw and surface records' in str(error), str(error)
    else:
        raise AssertionError('installed RF model accepted a missing required surface witness')

    from msplatform.backends.simion.field_execution import plan_fields_execution
    rf_field_plan = plan_fields_execution(rf_model, numerics=dict(refine_policy='vendor_default'))
    assert rf_field_plan['expected_operation_ids'] == ['materialize_geometry','refine_multipole','audit_fields']
    rf_field_query = query_capabilities(dict(schema_version=1, operation='solve_fields', arguments=dict(
        model=rf_model, numerics=dict(refine_policy='vendor_default'))))
    assert rf_field_query['contract_status'] == 'accepted' and rf_field_query['native_qualification'] == 'not_granted'
    assert rf_field_query['validator'] == 'msplatform.backends.simion.field_execution.plan_fields_execution'
    assert plan_fields_execution(rf_model, numerics=dict(refine_policy='explicit_convergence',
        convergence_v={'multipole':.001}), reuse_fields_reference={})['expected_operation_ids'] == ['audit_fields']
    from msplatform.backends.simion.resources import native_resource_path
    import msplatform
    for name in ['refine_rf_field_family.lua','audit_rf_field_family.lua']:
        assert native_resource_path(name).is_file() and native_resource_path(name).is_relative_to(pathlib.Path(msplatform.__file__).parent)
    from msplatform.backends.simion.tracking_execution import plan_tracking_execution
    from msplatform.backends.simion.rf_tracking_program import render_rf_controls
    rf_state=copy.deepcopy(state_row)
    rf_state.update(parent_particle_id=None,source_component_id='multipole',target_component_id='multipole',
        frame_id=rf_geometry.frontend_geometry['composition_plan']['components']['multipole']['local_frame_id'],
        clock_epoch_id=rf_model_drive['clock']['clock_epoch_id'],state_event='source_birth',
        instrument_time_us=1.25,particle_birth_time_us=1.25,lineage_birth_time_us=1.25,
        particle_age_us=0.,lineage_age_us=0.,last_component_elapsed_time_us=0.,phase_reference_id=None,phase_rad=None)
    rf_packet=dict(schema_version=1,role='canonical_release_realization',state_kind='source_birth',rows=[rf_state],
        clock={k:rf_model_drive['clock'][k] for k in ('clock_epoch_id','authority_sha256')},
        mother=dict(records={rf_state['particle_id']:dict(rf_state,source_component_entry_time_us=1.25)},
                    fates=[dict(particle_id=rf_state['particle_id'],category='released')]),realization=dict(spec=dict(particle_count=1)))
    rf_tracking_args=dict(particles=rf_packet,clock_records={k:dict(path='C:/pure-fixture/'+k+'.json',exists=True,bytes=32,sha256='A'*64)
        for k in ('clock_authority','instrument_epoch')},propagation=dict(schema_version=1,scope='continuous_assembly',
        end_policy=dict(maximum_particle_age_us=2.),consumed_plane_events=[],stop=None,
        dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none')),
        observations=dict(plane_observations=[]),numerics=dict(maximum_step_us=.01,trajectory_quality=5,rf_steps_per_period=32,grouped=1))
    rf_tracking_plan=plan_tracking_execution(rf_model,**rf_tracking_args)
    assert rf_tracking_plan['flight']['tracking_kind']=='independent_rf' and 'pulse' not in rf_tracking_plan['flight']
    assert rf_tracking_plan['absolute_deadlines_us_by_particle_id']=={rf_state['particle_id']:3.25}
    rf_tracking_query=query_capabilities(dict(schema_version=1,operation='track',arguments=dict(model=rf_model,**rf_tracking_args)))
    assert rf_tracking_query['contract_status']=='accepted' and rf_tracking_query['native_qualification']=='not_granted'
    assert 'RF_DYNAMICS_V1' in render_rf_controls(rf_model,rf_tracking_plan,assets={},native_sources={})['program']
    assert native_resource_path('rf_tracking.lua').is_relative_to(pathlib.Path(msplatform.__file__).parent)
    oa_packet=copy.deepcopy(rf_packet)
    oa_packet['clock']={key:oa_drive['clock'][key] for key in ('clock_epoch_id','authority_sha256')}
    oa_state=oa_packet['rows'][0]
    oa_state.update(source_component_id='two',target_component_id='two',clock_epoch_id=oa_drive['clock']['clock_epoch_id'],
        frame_id=oa_geometry.frontend_geometry['composition_plan']['components']['two']['local_frame_id'])
    oa_packet['mother']['records']={oa_state['particle_id']:dict(oa_state,source_component_entry_time_us=1.25)}
    oa_args=dict(rf_tracking_args,particles=oa_packet,numerics=dict(maximum_step_us=.01,trajectory_quality=0))
    oa_tracking=plan_tracking_execution(oa_model,**oa_args)
    assert oa_tracking['flight']['tracking_kind']=='independent_oa'
    assert oa_tracking['source_provenance']['mother_particle_ids']==[oa_state['particle_id']]
    oa_controls=render_rf_controls(oa_model,oa_tracking,assets={},native_sources={})
    assert oa_controls['build_metadata']['component_kind']=='orthogonal_accelerator'
    assert 'oa_pulse_hook' in oa_controls['program'] and 'pulse' not in oa_tracking['flight']
    assert query_capabilities(dict(schema_version=1,operation='track',arguments=dict(model=oa_model,**oa_args)))['contract_status']=='accepted'

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
# Explicit inert RF wire fixture exercises the installed parser, not SIMION.
from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
wire_source=rf_tracking_plan['rows'][0]
rf_control=render_rf_controls(rf_model,rf_tracking_plan,assets={},native_sources={})
wire_birth=dict(event='source_release',reason='none',particle_id=wire_source['particle_id'],ion=1,
    instrument_time_us=wire_source['instrument_time_us'],mass_amu=wire_source['mass_amu'],charge_state=wire_source['charge_state'],instance=1)
wire_birth.update({a+'_mm':wire_source['position_'+a+'_mm'] for a in 'xyz'})
wire_birth.update({'v'+a+'_mm_per_us':wire_source['velocity_'+a+'_m_s']/1000 for a in 'xyz'})
wire_terminal=dict(wire_birth,event='terminal',reason='unknown',instrument_time_us=wire_source['instrument_time_us']+.5,instance=0)
wire_path=root/('installed-inert-rf-wire-'+sys.argv[2]+'.log')
def rf_wire_text(terminal):
    return '\n'.join(['RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}',
        'RF_NATIVE_STATE_V1: '+json.dumps(wire_birth),'RF_NATIVE_STATE_V1: '+json.dumps(terminal),'status,Fly completed. 1 splats'])+'\n'
wire_path.write_text(rf_wire_text(wire_terminal),encoding='utf-8')
rf_wire_args=dict(source_rows={wire_source['particle_id']:wire_source},source_provenance=rf_tracking_plan['source_provenance'],
    flight=rf_tracking_plan['flight'],batches=[dict(source_row_range=[1,1],expected_particle_ids=[wire_source['particle_id']],build_metadata=rf_control['build_metadata'])])
wire_collection=collect_rf_tracking_logs([wire_path],**rf_wire_args)
assert wire_collection['native_terminals'][0]['instance']==0
assert wire_collection['census']['terminal_taxonomy']['particle_outcomes'][0]['category']=='unknown_native_terminal'
assert wire_collection['census']['unknown_is_loss'] is False
wire_path.write_text(rf_wire_text(dict(wire_terminal,raw_ion_splat=4)),encoding='utf-8')
try:
    collect_rf_tracking_logs([wire_path],**rf_wire_args)
except ValueError as error:
    assert 'wire fields differ' in str(error), str(error)
else:
    raise AssertionError('installed RF wire accepted retired unavailable terminal scalar')
wire_path.write_text(rf_wire_text(wire_terminal),encoding='utf-8')
from msplatform.backends.simion.resources import gem_template_path, native_resource_path, structural_seed_path
from msplatform.execution.resources import resource_path
from msplatform.io.manifest_records import file_record
from msplatform.execution.terminal_publication import publish_terminal_state

# Explicit inert records exercise actual installed paired analysis and Cartesian CLI.
from msplatform.analysis.paired_accelerator_pulse import compare_paired_accelerator_pulse
from msplatform.backends.comsol.prepulse_replay import build_comsol_prepulse_replay
paired_fixture = fixture['paired_pulse_analysis']
paired_output = root/('paired-analysis-'+sys.argv[2])
paired_output.mkdir()
replay_metadata = build_comsol_prepulse_replay(pathlib.Path(paired_fixture['collection']),
    pathlib.Path(paired_fixture['geometry']), paired_output/'release.csv', paired_output/'metadata.json',
    mass_amu=100, charge_state=1, pulse_decision_path=pathlib.Path(paired_fixture['decision']))
assert (paired_output/'release.csv').read_text(encoding='utf-8') == paired_fixture['expected_release']
serialized_replay_metadata = json.loads((paired_output/'metadata.json').read_text(encoding='utf-8'))
for key in ('selection','clock_epoch_id','species','selection_basis','coordinate_frame',
            'maximum_energy_round_trip_error_eV','maximum_velocity_serialization_error_m_per_s'):
    assert serialized_replay_metadata[key] == paired_fixture['expected_metadata'][key], key
comparison_report = compare_paired_accelerator_pulse(pathlib.Path(paired_fixture['plan']),
    pathlib.Path(paired_fixture['comsol']), pathlib.Path(paired_fixture['simion']), paired_output/'comparison')
assert (paired_output/'comparison/paired_pulse_differences.csv').read_text(encoding='utf-8') == paired_fixture['expected_differences']
assert {k:v for k,v in comparison_report.items() if k!='differences_csv'} == {k:v for k,v in paired_fixture['expected_comparison'].items() if k!='differences_csv'}
assert comparison_report['qualification'] == 'diagnostic_only'
for module_name in ('msplatform.analysis.paired_accelerator_pulse','msplatform.backends.comsol.prepulse_replay'):
    assert pathlib.Path(sys.modules[module_name].__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
import subprocess
cli_bootstrap = """
import importlib.abc,json,pathlib,os,sys,runpy,sysconfig
blocked=[pathlib.Path(p).resolve() for p in json.loads(sys.argv.pop(1))]
def deny_author(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        candidate=pathlib.Path(os.fsdecode(args[0])).resolve()
        assert not any(candidate.is_relative_to(p) for p in blocked),'author source read: '+str(candidate)
sys.addaudithook(deny_author)
class RejectRepository(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        assert name.split('.')[0] not in {'common','projects','integrations'},name
sys.meta_path.insert(0,RejectRepository())
import msplatform.backends.comsol.prepulse_replay as replay
assert pathlib.Path(replay.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
sys.argv=['msplatform.backends.comsol.prepulse_replay',*sys.argv[1:]]
runpy.run_module(sys.argv[0],run_name='__main__')
"""
cli_result = subprocess.run([sys.executable,'-I','-c',cli_bootstrap,json.dumps([str(p) for p in blocked_source_roots]),
    '--collection',paired_fixture['collection'],'--geometry',paired_fixture['geometry'],
    '--release-output',str(paired_output/'cli-release.csv'),'--metadata-output',str(paired_output/'cli-metadata.json'),
    '--mass-amu','100','--charge-state','1','--pulse-decision',paired_fixture['decision']],
    cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
assert cli_result.returncode == 0,cli_result.stdout+cli_result.stderr
assert 'COMSOL_PREPULSE_REPLAY_INPUT=PASS PARTICLES=1' in cli_result.stdout
assert (paired_output/'cli-release.csv').read_bytes() == (paired_output/'release.csv').read_bytes()

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
    assert importlib.util.find_spec('msplatform.api') is None
    from msplatform.results.artifacts import open_artifact
    reopened = open_artifact(artifact_reference,expected_kind='trajectory_result')
    assert reopened.data_path('state') == (root/'neutral-state.csv').resolve()
    assert reopened.producer['status'] == 'failed'
import subprocess
read_only_probe = """
import importlib.abc,json,pathlib,sys,sysconfig
class RejectExecutionImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'msplatform.execution' or fullname.startswith('msplatform.execution.') or fullname.split('.')[0] in {'common','projects','integrations'}:
            raise AssertionError('installed data reader imported execution/repository code: '+fullname)
sys.meta_path.insert(0,RejectExecutionImports())
from msplatform import results
opened=results.open_artifact(json.loads(sys.argv[1]),expected_kind='trajectory_result')
assert opened.producer['status']=='failed'
assert opened.data_path('state').is_file()
purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
for name,module in tuple(sys.modules.items()):
    if name=='msplatform' or name.startswith('msplatform.'):
        assert pathlib.Path(module.__file__).resolve().is_relative_to(purelib),(name,module.__file__)
assert not any(name=='msplatform.execution' or name.startswith('msplatform.execution.') for name in sys.modules)
print('INSTALLED_READ_ONLY_RESULTS=PASS')
"""
read_only = subprocess.run([sys.executable,'-I','-B','-c',read_only_probe,json.dumps(artifact_reference)],
    cwd=read_root,capture_output=True,text=True,encoding='utf-8',timeout=30)
assert read_only.returncode==0,read_only.stdout+read_only.stderr
assert 'INSTALLED_READ_ONLY_RESULTS=PASS' in read_only.stdout
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
    from msplatform.backends.simion.trajectory_comparison import compare_published_trajectories
    from msplatform.results.artifacts import open_artifact
    described = compare_published_trajectories(open_artifact(comparison_ref, expected_kind='trajectory_result'),
        open_artifact(comparison_ref, expected_kind='trajectory_result'), selection=comparison['selection'],
        method=dict(schema_version=1,kind='event_time_position'))
    analyzed = simion_api.analyze(comparison_ref, selection=comparison['selection'],
        method=dict(schema_version=1,kind='time_peak',settings=None,
            time_reference=dict(clock_epoch_id=clock.clock_epoch_id,authority_sha256=clock.authority_sha256,
                                instrument_time_us=20.)))
assert analyzed['status']=='analysis_completed' and analyzed['selected_particle_ids']==[7,99,123]
assert described['status']=='comparison_completed' and described['matched_particle_ids']==[7,99,123]
assert described['coverage']['left']['denominator_count']==4
assert all(pair['right_minus_left']['instrument_time_us']==0. and
           pair['right_minus_left']['position_components_mm']==[0.,0.,0.] for pair in described['pairs'])
assert described['scientific_qualification']=='not_granted' and 'velocity' in described['unavailable_quantities']
print('INSTALLED_PUBLIC_COMPARISON=PASS')
import msplatform.examples
example_path = pathlib.Path(msplatform.examples.__file__).with_name('rf_oatof_functional_v1.json')
# Exercise the real installed workflow with three explicit outside-tree input bundles.
from msplatform.workflows.single_reflection_flight import prepare as sfi_prepare
workflow_modes = []
# Execute the actual installed handoff with explicit external producer data.
mpip_request = pathlib.Path(fixture['multipole_ip_request'])
mpip_run = root / ('multipole-ip-' + sys.argv[2])
(mpip_run/'inputs').mkdir(parents=True)
mpip_receipt = prepare_multipole_ip(mpip_request, mpip_run)
assert (mpip_receipt['mother_count'], mpip_receipt['exit_count']) == (2, 1)
assert mpip_receipt['execution_scope'] == 'prepare_only_no_solver'
mpip_states = load_component_particle_state_csv(mpip_run/'results/multipole_ip/source_states.csv')
assert len(mpip_states.rows) == 1 and mpip_states.rows[0]['particle_id'] == 2
assert mpip_states.rows[0]['particle_birth_time_us'] == 2 * 1e-7 * 1e6
assert mpip_states.rows[0]['particle_weight'] == 1.
assert rf_observations.PARTICLE_STATE_COLUMNS[0] == 'particle_id'
import msplatform.workflows.multipole_ip.prepare as mpip_module
assert pathlib.Path(mpip_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
assert mpip_module.SCHEMA.is_file()
mpip_schema_backup = mpip_module.SCHEMA.with_suffix('.missing')
mpip_module.SCHEMA.rename(mpip_schema_backup)
try:
    # The canonical validator caches previously loaded schemas; a fresh process
    # is the actual incomplete-installation boundary, before that cache exists.
    import subprocess
    missing = subprocess.run([sys.executable, '-I', '-c',
        'from pathlib import Path;import sys;from msplatform.workflows.multipole_ip.prepare import load_request;'
        'load_request(Path(sys.argv[1]))', str(mpip_request)], cwd=root, capture_output=True, timeout=30)
    assert missing.returncode != 0 and b'request.schema.json' in missing.stderr, missing.stderr
finally:
    mpip_schema_backup.rename(mpip_module.SCHEMA)

gas_reader_code = """
import sys,json,pathlib,sysconfig
class OfflineReader:
 def find_spec(self,name,path=None,target=None):
  if any(name==p or name.startswith(p+'.') for p in ('msplatform.components','msplatform.backends','msplatform.execution')):
   raise AssertionError('OFFLINE_GAS_READER_REVERSE_IMPORT:'+name)
sys.meta_path.insert(0,OfflineReader())
from msplatform.results.gas_field import read_gas_field
import msplatform.contracts.gas_field as contract
assert pathlib.Path(contract.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
opened_field=read_gas_field(json.loads(sys.argv[1]))
field=opened_field.artifact
assert field.kind=='gas_field' and 'model' not in field.data_locations
print('INSTALLED_OFFLINE_GAS_READER=PASS')
"""
import subprocess
gas_reference = json.dumps(fixture['gas_field_reference'])
gas_read = subprocess.run([sys.executable, '-I', '-c', gas_reader_code, gas_reference],
                          cwd=root, capture_output=True, timeout=30)
assert gas_read.returncode == 0 and b'INSTALLED_OFFLINE_GAS_READER=PASS' in gas_read.stdout, gas_read.stderr
gas_contract_path = pathlib.Path(sysconfig.get_path('purelib'))/'msplatform/contracts/gas_field.py'
gas_contract_backup = gas_contract_path.with_suffix('.absent')
gas_contract_path.rename(gas_contract_backup)
try:
    missing_gas = subprocess.run([sys.executable, '-I', '-c', gas_reader_code, gas_reference],
                                cwd=root, capture_output=True, timeout=30)
    assert missing_gas.returncode != 0 and b'gas_field' in missing_gas.stderr, missing_gas.stderr
finally:
    gas_contract_backup.rename(gas_contract_path)

gas_policy_code = """
import sys,json,pathlib,sysconfig,os
blocked = [pathlib.Path(value).resolve() for value in json.loads(sys.argv[2])]
def deny_source(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  path=pathlib.Path(os.fsdecode(args[0])).resolve()
  if any(path.is_relative_to(root) for root in blocked):
   raise AssertionError('GAS_POLICY_AUTHOR_READ:'+str(path))
sys.addaudithook(deny_source)
from msplatform.results.gas_field import read_gas_field
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface import gas_field_validation
opened=read_gas_field(json.loads(sys.argv[1]))
summary=gas_field_validation.validate_gas_field_data(opened.data)
assert summary['status']=='PASS'
assert all(pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
           for name,module in sys.modules.items() if (name=='msplatform' or name.startswith('msplatform.')) and getattr(module,'__file__',None))
print('INSTALLED_PROJECT_GAS_POLICY=PASS')
"""
gas_blocked_roots = json.dumps([str(path) for path in blocked_source_roots])
gas_policy = subprocess.run([sys.executable, '-I', '-c', gas_policy_code, gas_reference, gas_blocked_roots],
                            cwd=root, capture_output=True, timeout=30)
assert gas_policy.returncode == 0 and b'INSTALLED_PROJECT_GAS_POLICY=PASS' in gas_policy.stdout, gas_policy.stderr
gas_policy_path = pathlib.Path(sysconfig.get_path('purelib'))/'msplatform/components/dual_cone_tandem_quadrupole_ion_interface/gas_field_validation.py'
gas_policy_backup = gas_policy_path.with_suffix('.absent')
gas_policy_path.rename(gas_policy_backup)
try:
    missing_policy = subprocess.run([sys.executable, '-I', '-c', gas_policy_code, gas_reference, gas_blocked_roots],
                                    cwd=root, capture_output=True, timeout=30)
    assert missing_policy.returncode != 0 and b'gas_field_validation' in missing_policy.stderr, missing_policy.stderr
finally:
    gas_policy_backup.rename(gas_policy_path)

from msplatform.workflows.prepared_joint.analysis_inputs import prepare_analysis_inputs
import msplatform.workflows.prepared_joint.analysis_inputs as admission_module
import msplatform.contracts.trajectory_recording as recording_module
assert pathlib.Path(admission_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
assert pathlib.Path(recording_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
for admission_case in fixture['prepared_joint_admission']:
    source = pathlib.Path(admission_case['source'])
    author_contract = pathlib.Path(admission_case['contract'])
    original = {path: path.read_bytes() for path in source.rglob('*') if path.is_file()}
    output = root / ('admitted-' + admission_case['scenario'] + '-' + sys.argv[2])
    if admission_case['scenario'] in ('success', 'failed_analysis'):
        admitted = prepare_analysis_inputs(source, author_contract, output)
        assert (admitted['mother_particle_count'], admitted['launched_particle_count']) == (100, 97)
        assert admitted['preparation'] == str(source/'results/prepared_joint_trial.json')
        assert admitted['merged_log'] == str(source/'logs/native_two_prism_flight.log')
        assert pathlib.Path(admitted['analysis_contract']).read_bytes() == author_contract.read_bytes()
        assert {path.name for path in output.iterdir()} == {'source_run_manifest.json','analysis_contract.json'}
        cli_output = output.with_name(output.name + '-cli')
        admitted_cli = subprocess.run([sys.executable, '-I', '-m', 'msplatform.workflows.prepared_joint.analysis_inputs',
            '--source-run', str(source), '--contract', str(author_contract), '--output-inputs', str(cli_output)],
            cwd=root, capture_output=True, timeout=30)
        assert admitted_cli.returncode == 0, admitted_cli.stderr
        assert json.loads(admitted_cli.stdout)['mother_particle_count'] == 100
    else:
        try:
            prepare_analysis_inputs(source, author_contract, output)
        except ValueError as error:
            assert admission_case['error'] in str(error)
        else:
            raise AssertionError('invalid sealed source was admitted')
        assert not output.exists()
    assert all(path.read_bytes() == value for path,value in original.items())
recording_path = pathlib.Path(recording_module.__file__)
recording_backup = recording_path.with_suffix('.absent')
recording_path.rename(recording_backup)
try:
    missing_recording = subprocess.run([sys.executable, '-I', '-m', 'msplatform.contracts.trajectory_recording',
        '--contract', str(author_contract)], cwd=root, capture_output=True, timeout=30)
    assert missing_recording.returncode != 0 and b'trajectory_recording' in missing_recording.stderr
finally:
    recording_backup.rename(recording_path)

for case in fixture['single_reflection_workflow']:
    prepared_run = root / ('installed-sfi-' + case['kind'] + '-' + sys.argv[2])
    (prepared_run/'inputs').mkdir(parents=True)
    receipt = sfi_prepare.prepare(pathlib.Path(case['request']),prepared_run)
    assert receipt['particle_count'] == case['particle_count']
    projected = prepared_run/'inputs/projected_source.csv'
    assert hashlib.sha256(projected.read_bytes()).hexdigest() == case['projected_sha256']
    with projected.open(encoding='utf-8',newline='') as stream:
        assert [row['particle_id'] for row in csv.DictReader(stream)] == case['particle_ids']
    assert {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (prepared_run/'inputs').glob('*.gem')} == case['gem_sha256']
    provenance = json.loads((prepared_run/'inputs/source_provenance.json').read_text(encoding='utf-8'))
    assert {name:provenance[name] for name in case['provenance']} == case['provenance']
    assert json.loads((prepared_run/'inputs/request.json').read_text(encoding='utf-8'))['schema_version'] == case['version']
    from msplatform.workflows.single_reflection_flight import frontend_fields
    assert pathlib.Path(frontend_fields.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_paths()['purelib']).resolve())
    (prepared_run/'run_config.json').write_text('{}',encoding='utf-8')
    producer_stage=frontend_fields.prepare_stage(prepared_run/'inputs',pathlib.Path(sys.executable),prepared_run)
    producer_domain=frontend_fields.domain_members(producer_stage,0,[])
    assert producer_domain['domain_id']=='parent' and producer_domain['members']
    assert all(pathlib.Path(row['path']).is_relative_to(prepared_run/'inputs')
               for row in producer_stage['resources'].values())
    assert not (prepared_run/'simion').exists()
    assert hashlib.sha256(projected.read_bytes()).hexdigest()==case['projected_sha256']
    workflow_modes.append(case['kind'])
assert workflow_modes == ['recorded_birth','release_spec','recorded_pre_pulse_state']
producer_path=pathlib.Path(frontend_fields.__file__)
producer_backup=producer_path.with_suffix('.absent')
producer_path.rename(producer_backup)
try:
    missing_producer=subprocess.run([sys.executable,'-I','-c',
        'from msplatform.workflows.single_reflection_flight import frontend_fields'],
        cwd=root,capture_output=True,timeout=30)
    assert missing_producer.returncode!=0 and b'frontend_fields' in missing_producer.stderr
finally:
    producer_backup.rename(producer_path)

# Consume an explicit external native-log fixture through the actual installed CLI.
import subprocess
collection_case = fixture['single_reflection_collection']
collection_output = pathlib.Path(collection_case['run'])/('installed-collection-'+sys.argv[2])
collection_child = """import json,sys,pathlib,runpy,importlib.util,sysconfig
blocked=[pathlib.Path(value).resolve() for value in json.loads(sys.argv.pop(1))]
def reject_author_files(event,args):
    if event=='open' and isinstance(args[0],(str,bytes)):
        target=pathlib.Path(args[0]).resolve()
        if any(target.is_relative_to(path) for path in blocked):raise AssertionError('author source read: '+str(target))
sys.addaudithook(reject_author_files)
spec=importlib.util.find_spec('msplatform.workflows.single_reflection_flight.collect')
assert pathlib.Path(spec.origin).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
sys.argv=['collect',*sys.argv[1:]]
runpy.run_module('msplatform.workflows.single_reflection_flight.collect',run_name='__main__')
"""
collected = subprocess.run([sys.executable,'-I','-c',collection_child,json.dumps([str(value) for value in blocked_source_roots]),
    '--preparation',collection_case['preparation'],'--workbench',collection_case['workbench'],
    '--run',collection_case['run'],'--log',collection_case['log'],'--output',str(collection_output)],
    cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
assert collected.returncode == 0,collected.stdout+collected.stderr
collection_receipt=json.loads(collected.stdout)
actual_collection=json.loads((collection_output/'collection.json').read_text(encoding='utf-8'))
assert actual_collection == collection_case['expected']
assert collection_receipt['output_records']['collection.json']['sha256'].upper() == hashlib.sha256((collection_output/'collection.json').read_bytes()).hexdigest().upper()
assert actual_collection['native_complete'] is True and len(actual_collection['native_terminals']) == 100
assert actual_collection['claim'] == 'canonical census only; no peak/bootstrap or physical qualification'

# Plan whole-unit recovery from an explicit external predecessor; no native action.
from msplatform.workflows.single_reflection_flight.continuation import prepare_phase_continuation
from msplatform.backends.simion import particle_batching
continuation_case=fixture['single_reflection_continuation'][int(sys.argv[2])]
continuation=prepare_phase_continuation(continuation_case['preparation'],continuation_case['workbench'],pathlib.Path(continuation_case['run']),'baseline')
assert continuation == continuation_case['expected']
assert continuation['plan']['reusable_unit_count'] == 2 and continuation['plan']['replay_unit_count'] == 0
assert len(continuation['source_record']['sha256']) == 64
assert continuation_case['preparation']['default_replay_requested'] is False
assert prepare_phase_continuation(continuation_case['preparation'],continuation_case['workbench'],pathlib.Path(continuation_case['run']),'default_replay') is None
batching_output=root/('installed-batch-plan-'+sys.argv[2]+'.json')
batched=subprocess.run([sys.executable,'-I','-m','msplatform.backends.simion.particle_batching','--particle-count','100','--batch-count','3','--output',str(batching_output)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
assert batched.returncode == 0,batched.stdout+batched.stderr
assert json.loads(batching_output.read_text(encoding='utf-8')) == particle_batching.plan_single_wave_batches(100,3)

# Run the complete recorded MR analyzer through its installed CLI, with real
# sealed test metadata and actual source/clock/batch records, without PA payloads.
mr_child = """import sys,json,pathlib,runpy,importlib.util,sysconfig
# Initialize third-party platform probing before the scientific no-process boundary.
import platform
platform.uname()
blocked=[pathlib.Path(value).resolve() for value in json.loads(sys.argv.pop(1))]
def offline_only(event,args):
    if event=='subprocess.Popen':raise AssertionError('offline analyzer spawned a process')
    if event=='open' and isinstance(args[0],(str,bytes)):
        target=pathlib.Path(args[0]).resolve()
        if any(target.is_relative_to(path) for path in blocked):raise AssertionError('author source read: '+str(target))
sys.addaudithook(offline_only)
spec=importlib.util.find_spec('msplatform.workflows.prepared_joint.diagnostics')
assert pathlib.Path(spec.origin).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
sys.argv=['diagnostics',*sys.argv[1:]]
try:runpy.run_module('msplatform.workflows.prepared_joint.diagnostics',run_name='__main__')
except SystemExit as error:
    if error.code not in (0,None):raise
assert all(pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
    for name,module in sys.modules.items() if name.startswith('msplatform.') and getattr(module,'__file__',None))
print('INSTALLED_MR_ANALYSIS=PASS')
"""
for case in fixture['prepared_joint_diagnostics']:
    output = root / ('installed-mr-' + case['kind'] + '-' + sys.argv[2])
    arguments = [sys.executable,'-I','-c',mr_child,json.dumps([str(value) for value in blocked_source_roots]),
        'analyze-joint','--preparation',case['preparation'],'--log',case['log'],'--output',str(output)]
    completed = subprocess.run(arguments,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert completed.returncode==0 and 'INSTALLED_MR_ANALYSIS=PASS' in completed.stdout, completed.stdout+completed.stderr
    result=json.loads((output/'diagnostics_receipt.json').read_text(encoding='utf-8'))
    assert result['counts']['mother_source']==3 and result['counts']['detected']==1
    assert result['counts']['downstream_loss']==1 and result['counts']['upstream_not_transferred']==1
    assert result['prism_statistics']['p2_fixed_plane']['outside_aperture_ids']==[7]
    assert result['prism_statistics']['p2_fixed_plane']['missing_mother_particle_ids']==[9]
    assert result['birth_clock_projection']['projected_particle_ids']==[7]
    assert result['qualification']=='descriptive_diagnostics_only_no_whole_beam_acceptance_or_performance_pass'
    assert len(list(output.glob('*.png')))==4 and len(list(output.glob('*.svg')))==4
    with (output/'loss_acceptance.csv').open(newline='') as stream: rows=list(csv.DictReader(stream))
    assert {int(row['particle_id']) for row in rows}=={1,7,9}
    assert next(row for row in rows if row['particle_id']=='9')['source_position_x_mm']==''
    assert all(hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()==digest for path,digest in case['input_sha256'].items())
    binding=pathlib.Path(case['binding']); backup=binding.with_suffix('.absent')
    binding.rename(backup)
    try:
        failed=subprocess.run(arguments[:-1]+[str(output)+'-missing-binding'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert failed.returncode!=0 and not pathlib.Path(str(output)+'-missing-binding').exists()
    finally:backup.rename(binding)
    if case['kind']=='declared_csv':
        trajectory=pathlib.Path(case['trajectory']); backup=trajectory.with_suffix('.absent')
        trajectory.rename(backup)
        try:
            failed=subprocess.run(arguments[:-1]+[str(output)+'-missing-trajectory'],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert failed.returncode!=0 and not (pathlib.Path(str(output)+'-missing-trajectory')/'diagnostics_receipt.json').exists()
        finally:backup.rename(trajectory)

# Actual paired source generation and response readback from the installed owners.
from msplatform.ion_release import paired_mass_scan as paired_scan
from msplatform.analysis import mass_response as response_analysis
for module in (paired_scan,response_analysis):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
import tempfile
mass_scan_root=pathlib.Path(tempfile.mkdtemp(prefix='paired-mass-scan-',dir=root))
scan_source=mass_scan_root/'source.ion'
scan_source.write_text('0,100,1,0,0,0,0,0,1,0,1\n0,100,1,1,0,0,0,0,1,0,1\n0,100,1,2,0,0,0,0,1,0,1\n',encoding='utf-8')
scan_table=mass_scan_root/'scan.ion';scan_metadata=mass_scan_root/'scan.json'
scan=paired_scan.generate_paired_ion_table(scan_source,scan_table,scan_metadata,[96.,100.,104.],3,{'scope':'installed_software_fixture'})
scan_rows=paired_scan.load_ion_rows(scan_table)
assert scan['particles']==9 and scan['particles_per_mass']==3 and scan['charge_state']==1
assert scan['source_sha256']==hashlib.sha256(scan_source.read_bytes()).hexdigest().upper()
assert scan['particle_table_sha256']==hashlib.sha256(scan_table.read_bytes()).hexdigest().upper()
assert scan_rows[0][0]==scan_rows[3][0] and scan_rows[0][2:]==scan_rows[3][2:]
assert [float(scan_rows[index][1]) for index in (0,3,6)]==[96.,100.,104.]
scan_cases=paired_scan.generate_paired_case_tables(scan_source,mass_scan_root/'cases',[96.,100.,104.],3)
assert len(scan_cases)==3 and all(row['particles']==3 for row in scan_cases)
scan_terminal=mass_scan_root/'terminal.csv'
scan_terminal.write_text('particle_id,event,status\n'+''.join(f'{pid},terminal,{"transmitted" if 4<=pid<=6 else "lost"}\n' for pid in range(1,10)),encoding='utf-8')
scan_response=response_analysis.aggregate_response(response_analysis.load_ion_masses(scan_table),response_analysis.load_terminal_statuses(scan_terminal))
assert [row['particles'] for row in scan_response]==[3,3,3]
assert [row['transmission_fraction'] for row in scan_response]==[0.,1.,0.]
scan_analysis=response_analysis.prepare_response_analysis(scan_response)
assert scan_analysis['status']=='computed' and scan_analysis['observed_half_maximum_band_Th']==[100.,100.]
assert scan_analysis['interpolated_main_peak_fwhm_Th']==4. and scan_analysis['resolution_claim_allowed'] is False
response_analysis.write_response(mass_scan_root/'response.csv',scan_response)
assert len(list(csv.DictReader((mass_scan_root/'response.csv').open(encoding='utf-8'))))==3
try:response_analysis.aggregate_response({1:100.},{2:'transmitted'})
except ValueError as error:assert 'IDs differ' in str(error)
else:raise AssertionError('mass response accepted mismatched particle identities')
for module in (paired_scan,response_analysis):
    original=pathlib.Path(module.__file__);hidden=original.with_suffix('.missing');original.rename(hidden)
    try:
        absent=subprocess.run([sys.executable,'-I','-B','-c','import '+module.__name__],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert absent.returncode!=0 and module.__name__.split('.')[-1] in absent.stderr,absent.stdout+absent.stderr
    finally:hidden.rename(original)
print('INSTALLED_PAIRED_MASS_RESPONSE=PASS')

# Exercise installed recorded-beam APIs over sparse IDs, unequal weights and unknown samples.
from msplatform.analysis import population_moments as beam_moments, plane_crossings as beam_crossings, beam_focus_diagnostics as beam_focus
from msplatform.contracts.rigid_transform import PhaseSpaceState, PlaneSurface
for module in (beam_moments,beam_crossings,beam_focus):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
weighted=beam_moments.population_moments(np.array([[0.,1.],[2.,3.]]),np.array([1.,3.]))
assert weighted.mean.tolist()==[1.5,2.5] and weighted.covariance.tolist()==[[.75,.75],[.75,.75]]
assert weighted.weight_sum==4. and weighted.effective_sample_count==1.6
samples=[beam_crossings.CrossingSample(7,'birth',PhaseSpaceState('f',(0.,0.,2.),(0.,0.,-1000.),10.)),
         beam_crossings.CrossingSample(7,8,PhaseSpaceState('f',(2.,0.,0.),(0.,0.,-1000.),10.5))]
brackets=list(beam_crossings.iter_bounded_plane_crossings(samples,particle_ids=[7,19],
    planes={'exit':PlaneSurface('f',(0.,0.,1.),(0.,0.,-1.))},minimum_time_us=10.,maximum_gap_us=.5,gap_tolerance_us=0.,occurrence=None))
assert len(brackets)==1 and brackets[0].particle_id==7 and brackets[0].interpolation_alpha==.5
assert brackets[0].lower_anchor=='birth' and brackets[0].upper_anchor==8
rows=[dict(particle_id=pid,plane_z_mm=0.,status='alive',t_us=time,x_mm=x,y_mm=0.,z_mm=0.,vx_mm_us=0.,vy_mm_us=0.,vz_mm_us=-1.)
      for pid,time,x in ((7,1.,0.),(19,3.,2.))]
case=dict(label='installed',sources={7:{},19:{},41:{}},exits={7:{},19:{}},particle_weights={7:1.,19:3.,41:2.},states=rows)
prepared=beam_focus.prepare_focus_diagnostics([case],[0.],[7,19])
row=next(row for row in prepared['plane_statistics'] if row['cohort']=='common_extracted_ids')
assert row['available_ids']==[7,19] and row['mean_x_mm']==1.5 and row['weight_sum']==4.
assert np.isclose(row['sigma_x_mm'],np.sqrt(.75))
unknown=next(row for row in prepared['plane_statistics'] if row['cohort']=='all_available_alive')
assert unknown['missing_ids']==[41] and unknown['cohort_count']==3
focus=beam_focus.prepare_time_focus_diagnostics([case],[0.],[7,19],{'drift_lengths_mm':[0.,2.]})
assert focus['metadata']['scientific_qualification']=='not_assessed'
assert all(row['quantile_method']=='weighted_ecdf_left_inverse_v1' for row in focus['plane_time_statistics'])
# Fresh interpreters cannot recover a missing installed dependency from author checkouts.
for module in (beam_moments,beam_crossings,beam_focus):
    original=pathlib.Path(module.__file__);hidden=original.with_suffix('.missing');original.rename(hidden)
    try:
        absent=subprocess.run([sys.executable,'-I','-B','-c',
            'import '+module.__name__],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert absent.returncode!=0 and module.__name__.split('.')[-1] in absent.stderr, absent.stdout+absent.stderr
    finally:hidden.rename(original)
print('INSTALLED_RECORDED_BEAM=PASS')

missing_rejected = []
# TOF_KERNEL_INSTALLED_BEGIN
# Fresh process: this numerical boundary must not import execution or a backend.
tof_kernel_child = r"""import importlib.abc,json,math,os,sys
from pathlib import Path
request=json.load(sys.stdin)
blocked=[Path(value).resolve() for value in request['blocked_roots']]
def reject_author(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  path=Path(os.fsdecode(args[0])).resolve()
  if any(path.is_relative_to(root) for root in blocked):raise AssertionError('TOF read author tree: '+str(path))
sys.addaudithook(reject_author)
class PureKernelOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==name or fullname.startswith(name+'.') for name in ('projects','common','msplatform.execution','msplatform.backends')):
   raise AssertionError('TOF imported execution/backend/checkout: '+fullname)
sys.meta_path.insert(0,PureKernelOnly())
import numpy as np
from msplatform.components.orthogonal_accelerator.three_zone_ideal_theory import AffineSource,OuterGeometry,derive_three_zone_state
from msplatform.components.single_reflection_oa_tof import three_zone_ideal_theory as theory,three_zone_ideal_root_solver as roots
purelib=Path(request['purelib']).resolve()
origins={module.__name__:str(Path(module.__file__).resolve()) for module in (theory,roots)}
assert all(Path(value).is_relative_to(purelib) for value in origins.values()),origins
source=AffineSource(**request['source']);outer=OuterGeometry(**request['outer'])
mirror=theory.ReflectronGeometry(**request['reflectron']);inner=theory.InnerSolution(**request['inner'])
physics=theory.PhysicsGateLimits(**request['physics_limits'])
state=derive_three_zone_state(source,outer,inner.eta)
cohort=theory.build_exact_cohort(source,state,mirror,inner,width_mm=2.2,sample_count=1001)
assert abs(cohort.population_sigma_ns-0.0326914522181)<=2e-10
energy=outer.nominal_energy_per_charge_v+source.chi_center_sqrt_v**2
jacobian=roots.JacobianSettings(math.log(10.),1e-5,1e-5,1e-5,.5,1e-10)
limits=roots.JacobianLimits(1e-10,0.,1e12,1.,0.)
results=[]
for mode in (2,3):
 common=dict(convergence_tolerance=1e-10,maximum_iterations=80 if mode==2 else 2,
             maximum_backtracks=12 if mode==2 else 4,cluster_distance=1e-8,jacobian=jacobian,limits=limits)
 if mode==3:
  settings=roots.RootSearchSettings(seeds=(roots.RootSeed(2.,2.,2.),roots.RootSeed(inner.stage1_voltage_drop_v/energy,inner.stage2_field_v_per_mm*mirror.stage2_length_mm/energy,inner.eta/math.log(10.))),bounds=roots.RootBounds(.5,.99,.1,1.,-1.5,1.5),**common)
  result=roots.collect_three_zone_roots(source,outer,mirror,width_mm=2.2,cohort_sample_count=101,physics_limits=physics,settings=settings)
  assert result.attempts[0].reason=='seed_out_of_bounds' and result.attempts[1].converged
 else:
  bounds=request['two_zone_bounds']
  settings=roots.TwoZoneRootSearchSettings(seeds=tuple(roots.TwoZoneRootSeed(*seed) for seed in request['two_zone_seeds']),bounds=roots.TwoZoneRootBounds(bounds['u']['minimum'],bounds['u']['maximum'],bounds['f']['minimum'],bounds['f']['maximum']),**common)
  result=roots.collect_two_zone_roots(source,outer,mirror,width_mm=2.2,cohort_sample_count=101,physics_limits=physics,settings=settings)
 expected=request['expected_coordinates'][str(mode)]
 assert len(result.candidates)==len(expected)
 for candidate,coordinates in zip(result.candidates,expected,strict=True):
  assert np.linalg.norm(np.asarray(candidate.coordinates)-coordinates)<=settings.cluster_distance
 assert len(result.accepted_candidates)==request['expected_accepted'][str(mode)]
 results.append(dict(mode=mode,attempts=len(result.attempts),roots=len(result.candidates),accepted=len(result.accepted_candidates)))
print(json.dumps(dict(status='PASS',origins=origins,results=results,native=False)))
"""
tof_kernel_request = dict(fixture['tof_kernel'], purelib=sysconfig.get_paths()['purelib'],
    blocked_roots=[str(path) for path in blocked_source_roots])
tof_kernel_command = [sys.executable, '-I', '-B', '-c', tof_kernel_child]
tof_kernel_run = subprocess.run(tof_kernel_command, cwd=root, input=json.dumps(tof_kernel_request),
    capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
assert tof_kernel_run.returncode==0,tof_kernel_run.stdout+tof_kernel_run.stderr
tof_kernel_result=json.loads(tof_kernel_run.stdout)
assert tof_kernel_result['status']=='PASS'
for name,origin in tof_kernel_result['origins'].items():
    module_path=pathlib.Path(origin)
    assert module_path.is_relative_to(pathlib.Path(sysconfig.get_paths()['purelib']).resolve())
    held=module_path.with_suffix('.missing-test-held')
    assert not held.exists()
    module_path.rename(held)
    try:
        absent=subprocess.run(tof_kernel_command, cwd=root, input=json.dumps(tof_kernel_request),
            capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
        assert absent.returncode!=0 and name.rsplit('.',1)[-1] in absent.stderr,absent.stdout+absent.stderr
    finally:
        held.rename(module_path)
print('INSTALLED_TOF_KERNEL=PASS')
# TOF_KERNEL_INSTALLED_END

# TOF_SOURCE_ACCEPTANCE_INSTALLED_BEGIN
tof_source_child = r"""import importlib.abc,json,os,sys,sysconfig
from pathlib import Path
q=json.load(sys.stdin)
blocked=[Path(value).resolve() for value in q['blocked_roots']]
def refuse_author(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  path=Path(os.fsdecode(args[0])).resolve()
  if any(path.is_relative_to(root) for root in blocked):raise AssertionError('TOF source accessed author: '+str(path))
sys.addaudithook(refuse_author)
class PureSource(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==name or fullname.startswith(name+'.') for name in ('common','projects','integrations','msplatform.backends','msplatform.execution')):raise AssertionError('TOF source imported host/checkout: '+fullname)
sys.meta_path.insert(0,PureSource())
import numpy as np
from msplatform.components.single_reflection_oa_tof import ideal_source_comparison as source,ideal_acceptance_theory as acceptance
from msplatform.components.orthogonal_accelerator.three_zone_ideal_theory import AffineSource,ThreeZoneState
from msplatform.components.single_reflection_oa_tof.three_zone_ideal_theory import ReflectronGeometry,InnerSolution
from msplatform.analysis.peak_metrics import AnalysisSettings
purelib=Path(sysconfig.get_path('purelib')).resolve()
origins={module.__name__:str(Path(module.__file__).resolve()) for module in (source,acceptance)}
assert all(Path(path).is_relative_to(purelib) for path in origins.values()),origins
from copy import deepcopy
before=deepcopy(q['source_acceptance']);v=before['point'];golden=before['golden']
point=source.IdealWorkingPoint(AffineSource(**v['design_source']),ThreeZoneState(**v['state']),ReflectronGeometry(**v['reflectron']),InnerSolution(**v['inner']),v['focus_drift_mm'],None)
spec=source.NumericalSourceSpec(**before['spec'])
particles=source.build_numerical_source(spec,particle_count=31,seed=73,full_width_mm=1.,residual_sigma_m_per_s=3.)
result=source.propagate_ideal_source(particles,point,settings=AnalysisSettings(grid_points=201,standardized_grid_points=101))
for key in ('particle_id','source_x_mm','velocity_z_m_per_s','residual_m_per_s'):
 np.testing.assert_array_equal(getattr(particles,key),golden[key])
np.testing.assert_array_equal(result.tof_us,golden['tof_us'])
np.testing.assert_array_equal(result.classification,golden['classification'])
assert result.summary['mother_particle_count']==golden['mother_count']==31
assert result.summary['full_cohort_reachable']
np.testing.assert_array_equal(acceptance._quadratic_power(3.,2.,.1,.5,8),golden['quadratic'])
np.testing.assert_array_equal(acceptance.axial_time_coefficients(point,order=6),golden['coefficients'])
np.testing.assert_array_equal(acceptance.residual_time_sensitivity(point,np.array([-1.,0.,1.])),golden['residual_sensitivity'])
assert acceptance.uniform_polynomial_variance(np.array([1e12,0.,0.,0.,2.3]),2.8)==golden['variance']
assert acceptance.coefficient_report(point,full_width_mm=2.2,residual_sigma_m_per_s=10.,order=6,position_order=16)==golden['report']
assert q['source_acceptance']==before
print(json.dumps(dict(status='PASS',origins=origins,particle_count=31,native=False)))
"""
tof_source_request = dict(source_acceptance=fixture['tof_kernel']['source_acceptance'],
    blocked_roots=[str(path) for path in blocked_source_roots])
tof_source_arguments = [sys.executable, '-I', '-B', '-c', tof_source_child]
tof_source_result = subprocess.run(tof_source_arguments, cwd=root, input=json.dumps(tof_source_request),
    capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
assert tof_source_result.returncode==0,tof_source_result.stdout+tof_source_result.stderr
tof_source_report=json.loads(tof_source_result.stdout)
assert tof_source_report['status']=='PASS'
for name,origin in tof_source_report['origins'].items():
    original_path=pathlib.Path(origin)
    original_bytes=original_path.read_bytes()
    held=original_path.with_suffix('.tof-source-held')
    assert not held.exists()
    original_path.rename(held)
    try:
        absent=subprocess.run(tof_source_arguments, cwd=root, input=json.dumps(tof_source_request),
            capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
        assert absent.returncode!=0 and name.rsplit('.',1)[-1] in absent.stderr,absent.stdout+absent.stderr
    finally:
        held.rename(original_path)
    assert original_path.read_bytes()==original_bytes
print('INSTALLED_TOF_SOURCE_ACCEPTANCE=PASS')
# TOF_SOURCE_ACCEPTANCE_INSTALLED_END

# RF_PARTICLE_COMPARISON_INSTALLED_BEGIN
rf_comparison_child = r"""import importlib.abc,json,math,os,sys,sysconfig
from pathlib import Path
q=json.load(sys.stdin)
blocked=[Path(value).resolve() for value in q['blocked_roots']]
def refuse_author(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  path=Path(os.fsdecode(args[0])).resolve()
  if any(path.is_relative_to(root) for root in blocked):raise AssertionError('RF comparison accessed author: '+str(path))
sys.addaudithook(refuse_author)
class PureComparison(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==name or fullname.startswith(name+'.') for name in ('common','projects','integrations','msplatform.backends','msplatform.execution')):raise AssertionError('RF comparison imported host/checkout: '+fullname)
sys.meta_path.insert(0,PureComparison())
from msplatform.analysis import particle_state_comparison as comparison
origin=Path(comparison.__file__).resolve()
assert origin==Path(sysconfig.get_path('purelib')).resolve()/'msplatform/analysis/particle_state_comparison.py',origin
directory=Path(q['directory']);directory.mkdir()
header='particle_id,event,elapsed_time_us,radial_position_mm,divergence_angle_deg,kinetic_energy_eV,max_rod_radius_mm,transverse_x_mm,transverse_y_mm,velocity_axial_m_s,velocity_x_m_s,velocity_y_m_s,rf_phase_rad\n'
sources=''.join(str(i)+',source,0,0,0,0,0,0,0,0,0,0,0\n' for i in range(1,5))
left_text=header+sources+'1,handoff,10,5,2,7,0,3,4,10,3,4,3\n2,handoff,20,0,4,9,0,0,0,0,0,0,0\n'
right_text=header+sources+'1,handoff,8,1,2,9,0,0,0,-2,0,0,-3\n3,handoff,12,0,4,11,0,0,0,0,0,0,0\n'
left_path=directory/'left.csv';right_path=directory/'right.csv'
left_path.write_text(left_text,encoding='utf-8',newline='');right_path.write_text(right_text,encoding='utf-8',newline='')
left=comparison.load_event_table(left_path);right=comparison.load_event_table(right_path)
assert comparison.source_id_evidence(left,right,4)==dict(valid=True,expected_count=4,left_missing_ids=[],left_extra_ids=[],left_unexpected_event_ids=[],right_missing_ids=[],right_extra_ids=[],right_unexpected_event_ids=[])
census,residuals=comparison.pair_event_census(left,right,{1,2,3,4})
assert [row['pair_status'] for row in census]==['paired','left_only','right_only','neither']
wrapped=2*math.pi-6
assert residuals==[dict(particle_id=1,position_residual_mm=5.,velocity_residual_m_s=13.,tof_residual_us=2.,energy_residual_eV=-2.,rf_phase_residual_rad=wrapped)]
for row in census[1:]:
 assert all(row[key]=='' for key in ('position_residual_mm','velocity_residual_m_s','tof_residual_us','energy_residual_eV','rf_phase_residual_rad'))
left_metrics=comparison.aggregate_handoff(left,4);right_metrics=comparison.aggregate_handoff(right,4)
assert left_metrics==dict(handoff_particles=2,transmission=.5,mean_tof_us=15.,p95_tof_us=19.5,rms_radius_mm=math.sqrt(12.5),p95_radius_mm=4.75,rms_divergence_deg=math.sqrt(10.),p95_divergence_deg=3.9,mean_energy_eV=8.,max_rod_radius_mm=None)
assert right_metrics==dict(handoff_particles=2,transmission=.5,mean_tof_us=10.,p95_tof_us=11.8,rms_radius_mm=math.sqrt(.5),p95_radius_mm=.95,rms_divergence_deg=math.sqrt(10.),p95_divergence_deg=3.9,mean_energy_eV=10.,max_rod_radius_mm=None)
metrics=comparison.aggregate_comparison(left_metrics,right_metrics,residuals)
assert metrics['transmission_absolute_difference']==0
assert metrics['mean_tof_relative_difference']==.4
assert metrics['mean_energy_relative_difference']==2/9
assert metrics['rms_radius_relative_difference']==abs(math.sqrt(12.5)-math.sqrt(.5))/((math.sqrt(12.5)+math.sqrt(.5))/2)
assert metrics['rms_divergence_relative_difference']==0
assert [metrics[key] for key in ('paired_mean_position_residual_mm','paired_p95_position_residual_mm','paired_mean_velocity_residual_m_s','paired_p95_velocity_residual_m_s','paired_mean_absolute_tof_residual_us','paired_mean_absolute_energy_residual_eV','paired_mean_absolute_rf_phase_residual_rad')]==[5.,5.,13.,13.,2.,2.,wrapped]
empty=comparison.aggregate_handoff({key:row for key,row in left.items() if key[1]=='source'},4)
assert empty==dict(handoff_particles=0,transmission=0.,mean_tof_us=None,p95_tof_us=None,rms_radius_mm=None,p95_radius_mm=None,rms_divergence_deg=None,p95_divergence_deg=None,mean_energy_eV=None,max_rod_radius_mm=None)
census_path=directory/'census.csv';comparison.write_census(census_path,census,left_label='left',right_label='right')
expected=('particle_id,pair_status,left_event,right_event,position_residual_mm,velocity_residual_m_s,tof_residual_us,energy_residual_eV,rf_phase_residual_rad\r\n'
 +f'1,paired,1,1,5.0,13.0,2.0,-2.0,{wrapped}\r\n'
 +'2,left_only,1,0,,,,,\r\n3,right_only,0,1,,,,,\r\n4,neither,0,0,,,,,\r\n').encode('utf-8')
assert census_path.read_bytes()==expected
duplicate=directory/'duplicate.csv';duplicate.write_text(left_text+left_text.splitlines()[-1]+'\n',encoding='utf-8',newline='')
try:comparison.load_event_table(duplicate)
except ValueError as error:assert 'duplicate particle event' in str(error)
else:raise AssertionError('duplicate particle/event accepted')
assert left_path.read_bytes()==left_text.encode() and right_path.read_bytes()==right_text.encode()
print(json.dumps(dict(status='PASS',origin=str(origin),native=False)))
"""
rf_comparison_request=dict(directory=str(root/('rf-comparison-'+sys.argv[2])),
    blocked_roots=[str(path) for path in blocked_source_roots])
rf_comparison_command=[sys.executable,'-I','-B','-c',rf_comparison_child]
rf_comparison_run=subprocess.run(rf_comparison_command,cwd=root,input=json.dumps(rf_comparison_request),
    capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
assert rf_comparison_run.returncode==0,rf_comparison_run.stdout+rf_comparison_run.stderr
rf_comparison_report=json.loads(rf_comparison_run.stdout)
assert rf_comparison_report['status']=='PASS'
rf_comparison_path=pathlib.Path(rf_comparison_report['origin'])
rf_comparison_bytes=rf_comparison_path.read_bytes()
rf_comparison_held=rf_comparison_path.with_suffix('.rf-comparison-held')
assert not rf_comparison_held.exists()
rf_comparison_path.rename(rf_comparison_held)
try:
    rf_comparison_absent=subprocess.run(rf_comparison_command,cwd=root,input=json.dumps(rf_comparison_request),
        capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert rf_comparison_absent.returncode!=0 and 'particle_state_comparison' in rf_comparison_absent.stderr,rf_comparison_absent.stdout+rf_comparison_absent.stderr
finally:
    rf_comparison_held.rename(rf_comparison_path)
assert rf_comparison_path.read_bytes()==rf_comparison_bytes
print('INSTALLED_RF_PARTICLE_COMPARISON=PASS')
# RF_PARTICLE_COMPARISON_INSTALLED_END

# MR_INTERFACE_INSTALLED_BEGIN
from msplatform.components.parallel_mirror_dual_stripe_mr_tof import assembly_interface as mr_interface_owner
mr_owner_path = pathlib.Path(mr_interface_owner.__file__).resolve()
assert mr_owner_path.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
mr_cases = fixture['mr_interface']
assert len(mr_cases) == 16
mr_fixture_before = pathlib.Path(sys.argv[1]).read_bytes()
for mr_case in mr_cases:
    mr_before = copy.deepcopy(mr_case['source'])
    if 'error' in mr_case:
        try:
            mr_interface_owner.resolve_assembly_interface(mr_case['source'])
        except ValueError as mr_error:
            assert mr_case['error'] in str(mr_error), (mr_case['case'], str(mr_error))
        else:
            raise AssertionError('invalid installed MR interface accepted: ' + mr_case['case'])
    else:
        mr_actual = mr_interface_owner.resolve_assembly_interface(mr_case['source'])
        assert mr_actual == mr_case['expected'], mr_case['case']
        machine_contracts.validate_schema(mr_actual, 'component_geometry_interface.schema.json')
    assert mr_case['source'] == mr_before, mr_case['case']
mr_input_path = root / ('mr-interface-' + sys.argv[2] + '.json')
mr_input_path.write_text(json.dumps(mr_cases), encoding='utf-8')
mr_input_before = mr_input_path.read_bytes()
mr_negative_child = """import importlib.abc,json,os,pathlib,sys,sysconfig
blocked=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[2])]
def refuse_author(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        path=pathlib.Path(os.fsdecode(args[0])).resolve()
        if any(path.is_relative_to(root) for root in blocked):
            raise AssertionError('MR child accessed author source: '+str(path))
sys.addaudithook(refuse_author)
class DenyRepository(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'common','projects','integrations'}:
            raise AssertionError('MR child imported repository owner: '+fullname)
sys.meta_path.insert(0,DenyRepository())
from msplatform.components.parallel_mirror_dual_stripe_mr_tof import assembly_interface
from msplatform.contracts.machine_contracts import validate_schema
assert pathlib.Path(assembly_interface.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
case=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))[0]
actual=assembly_interface.resolve_assembly_interface(case['source'])
assert actual==case['expected']
validate_schema(actual,'component_geometry_interface.schema.json')
"""
mr_schema_path = machine_contracts.SCHEMA_DIR / 'component_geometry_interface.schema.json'
mr_fresh_arguments = [sys.executable, '-I', '-B', '-c', mr_negative_child,
    str(mr_input_path), json.dumps([str(path) for path in blocked_source_roots])]
mr_fresh = subprocess.run(mr_fresh_arguments, cwd=root, capture_output=True,
    text=True, encoding='utf-8', timeout=30, check=False)
assert mr_fresh.returncode == 0, mr_fresh.stdout + mr_fresh.stderr
for mr_label, mr_missing, mr_diagnostic in (
    ('mr_interface_owner', mr_owner_path, 'assembly_interface'),
    ('mr_interface_schema', mr_schema_path, 'component_geometry_interface.schema.json'),
):
    mr_resource_before = mr_missing.read_bytes()
    mr_hold = mr_missing.with_name(mr_missing.name + '.mr-interface-held')
    mr_missing.rename(mr_hold)
    try:
        mr_failure = subprocess.run(mr_fresh_arguments, cwd=root, capture_output=True,
            text=True, encoding='utf-8', timeout=30, check=False)
        assert mr_failure.returncode != 0 and mr_diagnostic in mr_failure.stderr, mr_failure.stderr
        missing_rejected.append(mr_label)
    finally:
        mr_hold.rename(mr_missing)
    assert mr_missing.read_bytes() == mr_resource_before
assert mr_input_path.read_bytes() == mr_input_before
assert pathlib.Path(sys.argv[1]).read_bytes() == mr_fixture_before
print('INSTALLED_MR_INTERFACE=PASS cases=16')
# MR_INTERFACE_INSTALLED_END

# MR_BACKEND_GEOMETRY_INSTALLED_BEGIN
from msplatform.backends.simion import mr_geometry as mr_gem_owner
assert pathlib.Path(mr_gem_owner.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
assert importlib.util.find_spec('msplatform.components.parallel_mirror_dual_stripe_mr_tof.analyzer_candidate_geometry') is None
mr_gem_fixture = fixture['mr_backend_geometry']
mr_gem_input_before = pathlib.Path(sys.argv[1]).read_bytes()
for mr_gem_case in mr_gem_fixture['cases']:
    mr_geometry_before = copy.deepcopy(mr_gem_case['geometry'])
    mr_gem_bytes = '\n'.join(mr_gem_owner._analyzer_geometry_lines(mr_gem_case['geometry'])).encode('utf-8')
    assert len(mr_gem_bytes) == mr_gem_case['expected_gem_bytes'], mr_gem_case['case']
    assert hashlib.sha256(mr_gem_bytes).hexdigest() == mr_gem_case['expected_gem_sha256'], mr_gem_case['case']
    assert mr_gem_case['geometry'] == mr_geometry_before
assert mr_gem_owner.validate_generation_grid_pitch(mr_gem_fixture['numerical_contract'], [.01,.02,.03]) == .01
assert mr_gem_owner.ordinary_pa_file_bytes([65,65,9], [1,1,1]) == 304232
assert mr_gem_owner.ordinary_pa_file_bytes([65,65,9], [1,1,.5]) == 304256
mr_gem_module = pathlib.Path(mr_gem_owner.__file__)
mr_gem_original_bytes = mr_gem_module.read_bytes()
mr_gem_held = mr_gem_module.with_name(mr_gem_module.name + '.missing-test-held')
mr_gem_module.rename(mr_gem_held)
try:
    mr_gem_missing = subprocess.run([sys.executable, '-I', '-B', '-c',
        'import msplatform.backends.simion.mr_geometry'], cwd=root, capture_output=True,
        text=True, encoding='utf-8', timeout=30, check=False)
    assert mr_gem_missing.returncode != 0 and 'mr_geometry' in mr_gem_missing.stderr, mr_gem_missing.stderr
    missing_rejected.append('mr_backend_geometry')
finally:
    mr_gem_held.rename(mr_gem_module)
assert mr_gem_module.read_bytes() == mr_gem_original_bytes
assert pathlib.Path(sys.argv[1]).read_bytes() == mr_gem_input_before
print('INSTALLED_MR_BACKEND_GEOMETRY=PASS cases=2')
# MR_BACKEND_GEOMETRY_INSTALLED_END

# MR_NEUTRAL_INSTALLED_BEGIN
mr_neutral_code = r"""import copy,hashlib,importlib,importlib.abc,json,pathlib,sys,sysconfig
purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
authors=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[2])]
def deny_author(event,args):
    if event=='open' and args and isinstance(args[0],str):
        p=pathlib.Path(args[0]).resolve()
        if any(p.is_relative_to(a) for a in authors):raise AssertionError('author read: '+str(p))
sys.addaudithook(deny_author)
class NeutralOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in ('common','projects','integrations','tools','msplatform.backends','msplatform.execution')):
            raise AssertionError('non-neutral import: '+fullname)
sys.meta_path.insert(0,NeutralOnly())
m=importlib.import_module('msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry')
assert pathlib.Path(m.__file__).resolve().is_relative_to(purelib)
payload=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
for case in payload['cases']:
    before=copy.deepcopy(case)
    resolved=m.resolve_geometry(case['contract'],**case['authority'])
    assert resolved.pop('schema_version')==2
    oa=resolved.pop('accelerator_component_geometry')
    assert 'accelerator_component_layout' not in resolved
    assert oa['geometry_profile_id']==case['authority']['geometry_profile_id']
    digest=hashlib.sha256(json.dumps(resolved,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')).hexdigest()
    assert digest==case['expected_physical_sha256'],case['case']
    for key in ('accelerator_requirements','geometry_profile','geometry_profile_id'):
        missing=dict(case['authority']);missing.pop(key)
        try:m.resolve_geometry(case['contract'],**missing)
        except TypeError:pass
        else:raise AssertionError('missing authority accepted: '+key)
    assert case==before
for name,module in tuple(sys.modules.items()):
    if name.startswith('msplatform') and getattr(module,'__file__',None):
        assert pathlib.Path(module.__file__).resolve().is_relative_to(purelib)
print('INSTALLED_MR_NEUTRAL_RESOLVER=PASS cases=2')
"""
mr_neutral_input=root/('mr-neutral-'+sys.argv[2]+'.json')
mr_neutral_input.write_text(json.dumps(fixture['mr_backend_geometry']),encoding='utf-8')
mr_neutral_before=mr_neutral_input.read_bytes()
mr_neutral_argv=[sys.executable,'-I','-B','-c',mr_neutral_code,str(mr_neutral_input),
                 json.dumps([str(p) for p in blocked_source_roots])]
mr_neutral_child=subprocess.run(mr_neutral_argv,cwd=root,capture_output=True,text=True,
                                encoding='utf-8',timeout=60,check=False)
assert mr_neutral_child.returncode==0,mr_neutral_child.stdout+mr_neutral_child.stderr
assert 'INSTALLED_MR_NEUTRAL_RESOLVER=PASS cases=2' in mr_neutral_child.stdout
import importlib.util as mr_neutral_util
mr_neutral_path=pathlib.Path(mr_neutral_util.find_spec('msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry').origin)
assert mr_neutral_path.resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
mr_neutral_original=mr_neutral_path.read_bytes()
mr_neutral_held=mr_neutral_path.with_name(mr_neutral_path.name+'.missing-test-held')
assert not mr_neutral_held.exists()
mr_neutral_path.rename(mr_neutral_held)
try:
    mr_neutral_missing=subprocess.run(mr_neutral_argv,cwd=root,capture_output=True,text=True,
                                      encoding='utf-8',timeout=30,check=False)
    assert mr_neutral_missing.returncode!=0 and 'ModuleNotFoundError' in mr_neutral_missing.stderr and 'resolved_geometry' in mr_neutral_missing.stderr,mr_neutral_missing.stderr
    missing_rejected.append('mr_neutral_geometry')
finally:mr_neutral_held.rename(mr_neutral_path)
assert mr_neutral_path.read_bytes()==mr_neutral_original
assert mr_neutral_input.read_bytes()==mr_neutral_before
# MR_NEUTRAL_INSTALLED_END

# TOF_BUDGET_INSTALLED_BEGIN
# Optional Gaussian planning only; never an accuracy or Case C gate.
tof_budget_code = r"""import importlib,importlib.abc,json,math,pathlib,runpy,sys,sysconfig
purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
authors=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[1])]
def deny_author(event,args):
    if event=='open' and args and isinstance(args[0],str):
        p=pathlib.Path(args[0]).resolve()
        if any(p.is_relative_to(a) for a in authors):raise AssertionError('author access: '+str(p))
sys.addaudithook(deny_author)
class PureOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in ('common','projects','integrations','msplatform.backends','msplatform.execution')):
            raise AssertionError(fullname)
sys.meta_path.insert(0,PureOnly())
m=importlib.import_module('msplatform.analysis.tof_error_budget')
assert pathlib.Path(m.__file__).resolve().is_relative_to(purelib)
f=json.loads(sys.argv[2]);r=m.calculate_tof_error_budget(**f['api']);e=f['expected']
assert r['role']=='tof_error_budget' and r['qualification'] is False
for k in ('reference_fwhm_s','maximum_fwhm_s','remaining_fwhm_margin_s'):
    assert math.isclose(r[k],e[k],rel_tol=1e-14,abs_tol=0)
assert math.isclose(r['common_bias']['maximum_absolute_bias_s'],e['maximum_bias_s'],rel_tol=1e-14)
g=r['gaussian_planning'];assert math.isclose(g['independent_zero_mean_sigma_limit_s']/g['worst_positive_correlation_sigma_limit_s'],3,rel_tol=1e-14)
if len(sys.argv)>3:
    sys.argv=['msplatform.analysis.tof_error_budget',*json.loads(sys.argv[3])]
    runpy.run_module('msplatform.analysis.tof_error_budget',run_name='__main__')
"""
tof_budget_fixture=fixture['tof_budget']
tof_budget_argv=[sys.executable,'-I','-B','-c',tof_budget_code,
                 json.dumps([str(p) for p in blocked_source_roots]),json.dumps(tof_budget_fixture)]
for tof_budget_index,tof_budget_cli in enumerate(tof_budget_fixture['cli']):
    tof_budget_child=subprocess.run([*tof_budget_argv,json.dumps(tof_budget_cli)],cwd=root,
        capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert tof_budget_child.returncode==0,tof_budget_child.stdout+tof_budget_child.stderr
    if tof_budget_index<2:
        assert '**Planning only; not qualification.**' in tof_budget_child.stdout
        assert 'RMS budgets are not per-particle maximum errors, dt or rtol.' in tof_budget_child.stdout
        if tof_budget_index==0:assert '| Reference FWHM | 500 | ps |' in tof_budget_child.stdout
        else:assert '| Flight time T | 71.3527985968 | us |' in tof_budget_child.stdout
    else:
        tof_budget_unmet=json.loads(tof_budget_child.stdout)
        assert tof_budget_unmet['qualification'] is False and tof_budget_unmet['reference_meets_target'] is False
        assert tof_budget_unmet['gaussian_planning']['independent_zero_mean_sigma_limit_s'] is None
        assert tof_budget_unmet['remaining_fwhm_margin_s']<0
import importlib.util as tof_budget_util
tof_budget_path=pathlib.Path(tof_budget_util.find_spec('msplatform.analysis.tof_error_budget').origin)
assert tof_budget_path.resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
tof_budget_original=tof_budget_path.read_bytes()
tof_budget_held=tof_budget_path.with_name(tof_budget_path.name+'.missing-test-held')
assert not tof_budget_held.exists()
tof_budget_path.rename(tof_budget_held)
try:
    tof_budget_missing=subprocess.run(tof_budget_argv,cwd=root,capture_output=True,text=True,
                                     encoding='utf-8',timeout=30,check=False)
    assert tof_budget_missing.returncode!=0 and 'ModuleNotFoundError' in tof_budget_missing.stderr and 'tof_error_budget' in tof_budget_missing.stderr,tof_budget_missing.stderr
    missing_rejected.append('tof_error_budget')
finally:
    tof_budget_held.rename(tof_budget_path)
assert tof_budget_path.read_bytes()==tof_budget_original
print('INSTALLED_TOF_PLANNING_BUDGET=PASS')
# TOF_BUDGET_INSTALLED_END

# FIELD_COMPARISON_INSTALLED_BEGIN
# Additive installed probe proposal; no shared file is replaced.
field_child = r"""import importlib.abc,json,os,sys,sysconfig
from pathlib import Path
blocked=[Path(value).resolve() for value in json.loads(sys.argv[1])]
def deny_author(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  path=Path(os.fsdecode(args[0])).resolve()
  if any(path.is_relative_to(root) for root in blocked):raise AssertionError('field read author source')
sys.addaudithook(deny_author)
class NoHost(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==name or fullname.startswith(name+'.') for name in ('common','projects','integrations','msplatform.backends','msplatform.execution')):raise AssertionError(fullname)
sys.meta_path.insert(0,NoHost())
import numpy as np
import pandas as pd
import importlib
field_comparison=importlib.import_module('msplatform.analysis.field_comparison')
origin=Path(field_comparison.__file__).resolve()
assert origin.is_relative_to(Path(sysconfig.get_path('purelib')).resolve())
a=pd.DataFrame({'id':[2,1],'value':[20.,10.]});b=pd.DataFrame({'id':[1,2],'value':[11.,22.]})
a_before=a.copy(deep=True);b_before=b.copy(deep=True)
actual=field_comparison.merge_complete_samples(a,b,keys=['id'],left_label='A',right_label='B',suffixes=('_a','_b'))
pd.testing.assert_frame_equal(actual,pd.DataFrame({'id':[1,2],'value_a':[10.,20.],'value_b':[11.,22.]}))
pd.testing.assert_frame_equal(a,a_before);pd.testing.assert_frame_equal(b,b_before)
r=field_comparison.normalized_rms_difference_pct(np.array([3.,4.]),np.array([6.,8.]))
assert r['relative_to_reference_rms_pct']==100. and r['symmetric_scale_pct']==50.
assert r['reference_rms_V_per_m']==float(np.sqrt(12.5))
assert field_comparison.normalized_rms_difference_pct(np.zeros(3),np.array([0.,1e-12,-1e-12]))['relative_to_reference_rms_pct'] is None
for invalid in (b.iloc[:1],pd.concat([b,b.iloc[:1]])):
 try:field_comparison.merge_complete_samples(a,invalid,keys=['id'],left_label='A',right_label='B')
 except ValueError:pass
 else:raise AssertionError('incomplete/duplicate coverage accepted')
print(json.dumps({'status':'PASS','origin':str(origin)}))
"""
field_arguments=[sys.executable,'-I','-B','-c',field_child,json.dumps([str(path) for path in blocked_source_roots])]
field_run=subprocess.run(field_arguments,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
assert field_run.returncode==0,field_run.stdout+field_run.stderr
field_report=json.loads(field_run.stdout)
field_path=pathlib.Path(field_report['origin']);field_bytes=field_path.read_bytes()
field_held=field_path.with_suffix('.field-comparison-held');assert not field_held.exists()
field_path.rename(field_held)
try:
    field_missing=subprocess.run(field_arguments,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert field_missing.returncode!=0 and 'ModuleNotFoundError' in field_missing.stderr and 'field_comparison' in field_missing.stderr,field_missing.stderr
finally:
    field_held.rename(field_path)
assert field_path.read_bytes()==field_bytes
missing_rejected.append('field_comparison')
print('INSTALLED_FIELD_COMPARISON=PASS')# FIELD_COMPARISON_INSTALLED_END


# Provider-specific recorded analysis: actual explicit fixture and its unchanged protocol2 report.
from msplatform.workflows import oa_focus_analysis as focus_analysis
focus_fixture=fixture['oa_focus_analysis']
focus_actual=focus_analysis.analyze(pathlib.Path(focus_fixture['events']),
    pathlib.Path(focus_fixture['release_receipt']),pathlib.Path(focus_fixture['campaign']),
    geometry_profile=focus_fixture['geometry_profile'])
assert focus_actual==focus_fixture['expected']
assert focus_actual['schema_version']==2 and focus_actual['focus_particle_count']==3
focus_contract=root/('focus-contract-'+sys.argv[2]+'.json')
focus_contract.write_text(json.dumps(focus_fixture['component_contract']),encoding='utf-8')
focus_output=root/('focus-analysis-'+sys.argv[2]+'.json')
focus_arguments=[sys.executable,'-I','-B','-m','msplatform.workflows.oa_focus_analysis',
    '--events',focus_fixture['events'],'--release-receipt',focus_fixture['release_receipt'],
    '--campaign',focus_fixture['campaign'],'--component-contract',str(focus_contract),'--output',str(focus_output)]
focus_cli=subprocess.run(focus_arguments,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
assert focus_cli.returncode==0,focus_cli.stdout+focus_cli.stderr
assert focus_output.read_bytes()==(json.dumps(focus_fixture['expected'],indent=2)+'\n').replace('\n',os.linesep).encode('utf-8')
focus_module=pathlib.Path(focus_analysis.__file__)
assert focus_module.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
focus_hidden=focus_module.with_name(focus_module.name+'.missing')
focus_bytes=focus_module.read_bytes()
focus_module.rename(focus_hidden)
try:
    focus_missing=subprocess.run([sys.executable,'-I','-B','-m',focus_analysis.__name__],cwd=root,
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert focus_missing.returncode!=0 and 'focus_analysis' in focus_missing.stderr,focus_missing.stderr
finally:focus_hidden.rename(focus_module)
assert focus_module.read_bytes()==focus_bytes
missing_rejected.append('oa_focus_analysis')
print('INSTALLED_OA_FOCUS_ANALYSIS=PASS')

for label, missing_path, action in (
    ('comsol_launcher', comsol_resource_path('run_comsol_r2025b.ps1'), lambda:comsol_resource_path('run_comsol_r2025b.ps1')),
    ('ei_builder', comsol_resource_path('ms_stage1_ei_source.m'), lambda:comsol_resource_path('ms_stage1_ei_source.m')),
    ('wehnelt_builder', comsol_resource_path('build_wehnelt_model.m'), lambda:comsol_resource_path('build_wehnelt_model.m')),
    ('example', example_path, lambda:example_api.load_example('rf_oatof_functional_v1')),
    ('gem', gem_template_path('reflectron'), lambda:simion_api.compile_geometry(actual_assembly,numerics=study.geometry_numerics)),
    ('powershell', resource_path('process_owner.ps1'), lambda:resource_path('process_owner.ps1')),
    ('lua', native_resource_path('build_geometry_iob.lua'), lambda:native_resource_path('build_geometry_iob.lua')),
    ('paired_pulse_lua', native_resource_path('paired_accelerator_pulse.lua'), lambda:native_resource_path('paired_accelerator_pulse.lua')),
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
workflow_schema = sfi_prepare.SCHEMA
hidden_workflow_schema = workflow_schema.with_name(workflow_schema.name+'.missing')
workflow_schema.rename(hidden_workflow_schema)
try:
    import subprocess
    failed = subprocess.run([sys.executable,'-I','-c',
        "import json,sys;from pathlib import Path;from msplatform.workflows.single_reflection_flight.prepare import validate_preparation_request;validate_preparation_request(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))",
        fixture['single_reflection_workflow'][1]['request']], cwd=root,capture_output=True,timeout=30)
    failed_output = (failed.stdout+failed.stderr).decode('utf-8',errors='backslashreplace')
    assert failed.returncode != 0 and workflow_schema.name in failed_output, failed_output
    missing_rejected.append('workflow_schema')
finally: hidden_workflow_schema.rename(workflow_schema)
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
# Actual canonical manifest CLI policy/projection, outside author roots.
from msplatform.execution import manifest_publication, manifest_verification
from msplatform.execution.retention import retention_api as generic_retention_api
from msplatform.backends.simion.native_completion import retention_api as native_retention_api
manifest_run = root/('manifest-policy-'+sys.argv[2])
(manifest_run/'logs').mkdir(parents=True)
manifest_trace = manifest_run/'logs/simion__batch01.trace.log'
manifest_trace.write_text('status,Fly completed.\n',encoding='utf-8')
(manifest_run/'retention_actions.json').write_text(json.dumps(dict(schema_version=1,role='artifact_retention_actions',retention_class='compact',status='complete',preserved=[dict(path='logs/simion__batch01.trace.log',bytes=manifest_trace.stat().st_size,retention_role='dense_trajectory',action='retained_completed_native_trace_for_recovery')])),encoding='utf-8')
manifest_config=manifest_run/'run_config.json'
manifest_config.write_text(json.dumps(dict(schema_version=2,run_id='20261110_120000__test__python__installed-manifest',project='installed_fixture',mode='test',inputs={},artifact_retention=dict(policy_version=1,**{'class':'compact'},reason=None))),encoding='utf-8')
try:
    manifest_publication.publish_run_manifest(manifest_config,'failed',retention_api=generic_retention_api)
except ValueError as error:
    assert 'explicit completion policy' in str(error)
else: raise AssertionError('generic policy accepted native recovery')
assert not (manifest_run/'run_manifest.json').exists()
manifest_publication.publish_run_manifest(manifest_config,'failed',retention_api=native_retention_api,output_paths=[manifest_trace])
manifest_cli='from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)'
manifest_verified=subprocess.run([sys.executable,'-I','-c',manifest_cli,str(manifest_run/'run_manifest.json'),'--require-status','failed'],cwd=root,capture_output=True,text=True,timeout=30)
assert manifest_verified.returncode==0 and 'SCOPE=full' in manifest_verified.stdout,manifest_verified.stderr
manifest_projected=subprocess.run([sys.executable,'-I','-c',manifest_cli,str(manifest_run/'run_manifest.json'),'--require-status','failed','--consumer-projection-id','installed_fixture_v1','--consumed-output',str(manifest_trace)],cwd=root,capture_output=True,text=True,timeout=30)
assert manifest_projected.returncode==0 and 'SCOPE=consumer_projection' in manifest_projected.stdout,manifest_projected.stderr
manifest_trace.write_text('status,Fly completEd.\n',encoding='utf-8')
manifest_rejected=subprocess.run([sys.executable,'-I','-c',manifest_cli,str(manifest_run/'run_manifest.json'),'--require-status','failed'],cwd=root,capture_output=True,text=True,timeout=30)
assert manifest_rejected.returncode!=0 and 'SHA-256 changed' in manifest_rejected.stderr,manifest_rejected.stderr
manifest_module=pathlib.Path(manifest_verification.__file__)
manifest_hidden=manifest_module.with_name(manifest_module.name+'.missing')
manifest_module.rename(manifest_hidden)
try:
    missing_manifest=subprocess.run([sys.executable,'-I','-c',manifest_cli,str(manifest_run/'run_manifest.json'),'--require-status','failed'],cwd=root,capture_output=True,text=True,timeout=30)
    assert missing_manifest.returncode!=0 and 'manifest_verification' in missing_manifest.stderr,missing_manifest.stderr
finally:manifest_hidden.rename(manifest_module)
missing_rejected.append('manifest_verification')

# Actual installed run-path owner, independent of checkout defaults and PATH.
from msplatform.execution.run_paths import project_run_path
from msplatform.execution.resources import resource_path as execution_resource_path
assert project_run_path(root/'run/input.lua', root/'run', root/'alias') == str(root/'alias/input.lua')
assert project_run_path(root/'external.lua', root/'run', root/'alias') == str(root/'external.lua')
path_resource = execution_resource_path('run_paths.ps1')
assert path_resource.is_relative_to(pathlib.Path(sysconfig.get_path('purelib')))
hidden_path_resource = path_resource.with_name(path_resource.name+'.missing')
path_resource.rename(hidden_path_resource)
try:
    try: execution_resource_path('run_paths.ps1')
    except FileNotFoundError: missing_rejected.append('run_paths_ps')
    else: raise AssertionError('missing installed run-path resource supplemented')
finally: hidden_path_resource.rename(path_resource)
if os.name == 'nt':
    path_pwsh = pathlib.Path(fixture['native_path_powershell'])
    assert path_pwsh.is_absolute() and path_pwsh.is_file()
    path_script = root/('installed-paths-'+sys.argv[2]+'.ps1')
    path_script.write_text(r"""param($Resource,$Root,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Resource
$deep=Join-Path (Join-Path (Join-Path $Root ('a'*90)) ('b'*90)) ('c'*90)
$file=Join-Path $deep 'inputs/control.lua'
New-Item -ItemType Directory -Path (Split-Path -Parent $file) -Force|Out-Null
[IO.File]::WriteAllText($file,'installed control input')
$package=[pscustomobject]@{artifact_run_dir=$deep;run_dir=$deep;execution_alias=$null;execution_path_capacity=$null;python=$Python;path_context=[pscustomobject]@{execution_root=(Join-Path $Root 'exec');artifact_root=(Join-Path $Root 'payload');host_resource_state_path=(Join-Path $Root 'unchanged-ledger.sqlite3')}}
try{
 $context=Get-RunNativeExecutionContext -Package $package -Paths @($file) -Tool 'installed fixture'
 if([IO.File]::ReadAllText($context.projected_paths[0])-cne'installed control input'){throw 'Installed path input changed'}
 if($context.environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH-cne$package.path_context.host_resource_state_path){throw 'Installed path ledger changed'}
 if(Test-Path -LiteralPath $package.path_context.host_resource_state_path){throw 'Path projection created a ledger'}
}finally{if($null-ne$package.execution_alias){Remove-ManagedExecutionAlias -ExecutionAlias $package.execution_alias -TargetDirectory $deep}}
if(-not(Test-Path -LiteralPath $file)){throw 'Installed path cleanup removed input'}
""", encoding='utf-8')
    path_args=[str(path_pwsh),'-NoProfile','-File',str(path_script),str(path_resource),str(root/('path-study-'+sys.argv[2])),sys.executable]
    actual_paths=subprocess.run(path_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert actual_paths.returncode==0,actual_paths.stdout+actual_paths.stderr
    from msplatform.execution import run_paths as installed_paths
    python_path_resource=pathlib.Path(installed_paths.__file__)
    hidden_python_path=python_path_resource.with_name(python_path_resource.name+'.missing')
    python_path_resource.rename(hidden_python_path)
    try:
        missing_paths=subprocess.run(path_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert missing_paths.returncode!=0 and 'Selected run-path Python resource is missing' in missing_paths.stderr,missing_paths.stdout+missing_paths.stderr
    finally: hidden_python_path.rename(python_path_resource)
    missing_rejected.append('run_paths_python')

# FROZEN_EXECUTOR_INSTALLED_BEGIN
# Initial installed bootstrap is trusted; only the subsequent selected copy is
# verified before dot-source by the existing public package assertion.
frozen_executor=execution_resource_path('frozen_python_package.ps1')
assert frozen_executor.resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
frozen_executor_original=frozen_executor.read_bytes()
frozen_executor_hidden=frozen_executor.with_name(frozen_executor.name+'.missing-test-held')
assert not frozen_executor_hidden.exists()
frozen_executor.rename(frozen_executor_hidden)
try:
    try:execution_resource_path('frozen_python_package.ps1')
    except FileNotFoundError:missing_rejected.append('frozen_executor_resource')
    else:raise AssertionError('missing installed frozen executor supplemented')
finally:
    frozen_executor_hidden.rename(frozen_executor)
assert frozen_executor.read_bytes()==frozen_executor_original
if os.name=='nt':
    frozen_root=root/('selected-executor-'+sys.argv[2])
    frozen_root.mkdir()
    frozen_code=frozen_root/'code'
    frozen_code.mkdir()
    # Real installed canonical core, selected/frozen by existing public primitives.
    # Keep src/msplatform inventory topology and its automatic required-origin guard.
    from msplatform.execution.inputs import enumerate_python_sources, freeze_file
    frozen_purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
    frozen_sources=enumerate_python_sources(frozen_purelib,package_roots=['msplatform'],
        resource_suffixes=['.json','.ps1','.lua','.gem','.m','.iob','.pa0','.pa'])
    assert 'msplatform/__init__.py' in frozen_sources
    assert 'msplatform/execution/resources/frozen_python_package.ps1' in frozen_sources
    frozen_records=[]
    for frozen_relative in frozen_sources:
        frozen_target=frozen_code/'src'/frozen_relative
        frozen_target.parent.mkdir(parents=True,exist_ok=True)
        frozen_record=freeze_file(frozen_purelib/frozen_relative,frozen_target)
        frozen_records.append(dict(path=frozen_record['path'],
            relative_path='src/'+frozen_relative,sha256=frozen_record['sha256'].upper()))
    frozen_selected=frozen_code/'src/msplatform/execution/resources/frozen_python_package.ps1'
    assert frozen_selected.read_bytes()==frozen_executor_original
    frozen_expected='OWNED_STDOUT_MARKER\n\n\u4e2d\u6587 trailing  \n\n'.encode('utf-8')
    frozen_analyzer=frozen_code/'owned_analyzer.py'
    frozen_analyzer.write_text(
        "import pathlib,sys\n"
        "sys.stdout.buffer.write(bytes.fromhex("+repr(frozen_expected.hex())+"))\n"
        "sys.stdout.flush()\n"
        "print('OWNED_STDERR_MARKER',file=sys.stderr,flush=True)\n"
        "pathlib.Path(sys.argv[2]).write_text(str(pathlib.Path(__file__).resolve()),encoding='utf-8')\n"
        "raise SystemExit(int(sys.argv[1]))\n",encoding='utf-8')
    frozen_records.append(dict(path=str(frozen_analyzer),relative_path='owned_analyzer.py',
        sha256=hashlib.sha256(frozen_analyzer.read_bytes()).hexdigest().upper()))
    frozen_package=dict(code_root=str(frozen_code),
        package_roots=[str(frozen_code/'src'),str(frozen_code)],files=frozen_records)
    frozen_package_path=frozen_root/'package.json'
    frozen_package_path.write_text(json.dumps(frozen_package),encoding='utf-8')
    frozen_report=frozen_root/'report.json'
    frozen_driver=frozen_root/'driver.ps1'
    frozen_driver.write_text(r"""param($Bootstrap,$Selected,$PackagePath,$Python,$Root,$Report,$ForbiddenJson)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
# Explicit installed bootstrap is trusted, not represented as prehashed execution.
. $Bootstrap
$package=Get-Content -LiteralPath $PackagePath -Raw|ConvertFrom-Json
Assert-FrozenPythonPackage -Package $package
. $Selected
foreach($name in @('Assert-FrozenPythonPackage','Invoke-IsolatedFrozenPythonModule')){
 if((Get-Command $name).ScriptBlock.File-cne$Selected){throw 'Selected executor origin differs'}
}
$forbidden=@($ForbiddenJson|ConvertFrom-Json)
$origin=Join-Path $Root 'probe.origin'
$probe=Invoke-IsolatedFrozenPythonModule -Python $Python -Package $package -Module owned_analyzer -Arguments @('0',$origin) -RequiredModuleNames @('owned_analyzer') -ForbiddenRoots $forbidden -ProbeOnly
if($probe.module_invoked-or(Test-Path -LiteralPath $origin)){throw 'Probe executed analyzer'}
if(-not$probe.python_no_user_site){throw 'User site enabled'}
$rows=@()
foreach($code in @(0,7)){
 $stdout=Join-Path $Root "$code.stdout";$origin=Join-Path $Root "$code.origin"
 $threw=$false;$exitCode=$null;$message='';$trim=$null
 try{
  $r=Invoke-IsolatedFrozenPythonModule -Python $Python -Package $package -Module owned_analyzer -Arguments @([string]$code,$origin) -RequiredModuleNames @('owned_analyzer') -ForbiddenRoots $forbidden -StdoutPath $stdout
  $trim=$r.module_stdout
 }catch{$threw=$true;$exitCode=$_.Exception.Data['exit_code'];$message=$_.Exception.Message}
 Assert-FrozenPythonPackage -Package $package
 $rows+=@{code=$code;threw=$threw;exit_code=$exitCode;message=$message;trim=$trim;origin=[IO.File]::ReadAllText($origin);stdout_hex=[Convert]::ToHexString([IO.File]::ReadAllBytes($stdout))}
}
$defaultOrigin=Join-Path $Root 'default.origin'
$default=Invoke-IsolatedFrozenPythonModule -Python $Python -Package $package -Module owned_analyzer -Arguments @('0',$defaultOrigin) -RequiredModuleNames @('owned_analyzer') -ForbiddenRoots $forbidden
$analyzer=Join-Path $package.code_root 'owned_analyzer.py';$original=[IO.File]::ReadAllBytes($analyzer)
$tamperOrigin=Join-Path $Root 'tamper.origin';$tamperRejected=$false
try{
 [IO.File]::AppendAllText($analyzer,"`n# changed")
 try{Invoke-IsolatedFrozenPythonModule -Python $Python -Package $package -Module owned_analyzer -Arguments @('0',$tamperOrigin) -ForbiddenRoots $forbidden|Out-Null}
 catch{if($_.Exception.Message-like'Frozen Python dependency hash differs:*'){$tamperRejected=$true}else{throw}}
}finally{[IO.File]::WriteAllBytes($analyzer,$original)}
if(-not$tamperRejected-or(Test-Path -LiteralPath $tamperOrigin)){throw 'Tampered package executed'}
Assert-FrozenPythonPackage -Package $package
@{rows=$rows;default_trim=$default.module_stdout;probe_modules=$probe.frozen_modules;tamper_rejected=$tamperRejected}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Report -Encoding utf8NoBOM
""",encoding='utf-8')
    frozen_pwsh=pathlib.Path(fixture['native_path_powershell'])
    frozen_result=subprocess.run([str(frozen_pwsh),'-NoProfile','-NonInteractive','-File',str(frozen_driver),
        str(frozen_executor),str(frozen_selected),str(frozen_package_path),sys.executable,str(frozen_root),
        str(frozen_report),json.dumps([str(p) for p in blocked_source_roots])],cwd=root,
        capture_output=True,text=True,encoding='utf-8',timeout=120,check=False)
    assert frozen_result.returncode==0,frozen_result.stdout+frozen_result.stderr
    frozen_proof=json.loads(frozen_report.read_text(encoding='utf-8-sig'))
    assert frozen_proof['tamper_rejected'] is True
    # PowerShell's no-sink Out-String uses platform newlines; raw sinks stay byte-exact.
    frozen_default_expected=frozen_expected.decode('utf-8').strip().replace('\n',os.linesep)
    assert frozen_proof['default_trim']==frozen_default_expected, (repr(frozen_proof['default_trim']),repr(frozen_default_expected))
    frozen_probe_origins={row['name']:pathlib.Path(row['origin']).resolve()
                          for row in frozen_proof['probe_modules']}
    assert frozen_probe_origins['owned_analyzer']==frozen_analyzer.resolve()
    assert frozen_probe_origins['msplatform']==(frozen_code/'src/msplatform/__init__.py').resolve()
    for frozen_row in frozen_proof['rows']:
        assert bytes.fromhex(frozen_row['stdout_hex'])==frozen_expected
        assert pathlib.Path(frozen_row['origin'])==frozen_analyzer
        assert frozen_row['threw']==(frozen_row['code']!=0)
        if frozen_row['code']==7:
            assert frozen_row['exit_code']==7 and 'exit code 7' in frozen_row['message']
        else:assert frozen_row['trim']==frozen_expected.decode('utf-8').strip()
    assert 'OWNED_STDERR_MARKER' in frozen_result.stderr
    frozen_missing_driver=frozen_root/'missing.ps1'
    frozen_missing_driver.write_text(r"""param($Selected)
$ErrorActionPreference='Stop'
if(-not(Test-Path -LiteralPath $Selected -PathType Leaf)){throw "Selected frozen Python execution resource is missing: $Selected"}
. $Selected
throw 'Missing selected resource accepted'
""",encoding='utf-8')
    frozen_selected_hidden=frozen_selected.with_name(frozen_selected.name+'.held')
    frozen_selected.rename(frozen_selected_hidden)
    try:
        frozen_missing=subprocess.run([str(frozen_pwsh),'-NoProfile','-NonInteractive','-File',
            str(frozen_missing_driver),str(frozen_selected)],cwd=root,capture_output=True,text=True,
            encoding='utf-8',timeout=30,check=False)
        assert frozen_executor.is_file()
        assert frozen_missing.returncode!=0 and 'Selected frozen Python execution resource is missing' in frozen_missing.stderr,frozen_missing.stderr
    finally:frozen_selected_hidden.rename(frozen_selected)
    for frozen_entry in frozen_package['files']:
        assert hashlib.sha256(pathlib.Path(frozen_entry['path']).read_bytes()).hexdigest().upper()==frozen_entry['sha256']
    missing_rejected.append('selected_frozen_executor')
print('INSTALLED_SELECTED_FROZEN_EXECUTOR=PASS')
# FROZEN_EXECUTOR_INSTALLED_END

# RF_MANAGED_L1_INSTALLED_BEGIN
from unittest.mock import patch as rf_l1_patch
from msplatform.workflows.rf_mass_filter import finite_length as rf_l1
from msplatform.components.rf_multipole import finite_length_transport as rf_l1_kernel
from msplatform.execution.context import load_environment as rf_l1_load_environment
from msplatform.execution.capacity_protection import load_capacity_protection_leases as rf_l1_capacity
from msplatform.execution.capacity_admission import capture_capacity_policy as rf_l1_capture_capacity
from msplatform.execution.completion import no_particle_batch_completion_api as rf_l1_completion
from msplatform.execution.owner import resume_finalization as rf_l1_resume
from msplatform.io.manifest_records import verify_record as rf_l1_verify
for rf_l1_module in (rf_l1,rf_l1_kernel):
    assert pathlib.Path(rf_l1_module.__file__).resolve().is_relative_to(pathlib.Path(sysconfig.get_path('purelib')).resolve())
rf_l1_fixture=fixture['rf_l1_managed']
assert hashlib.sha256(pathlib.Path(rf_l1.__file__).read_bytes()).hexdigest()==rf_l1_fixture['oracle_module_sha256']
rf_l1_science=root/('rf-l1-science-'+sys.argv[2]);rf_l1_science.mkdir()
rf_l1_paths={}
for rf_l1_name,rf_l1_record in rf_l1_fixture['inputs'].items():
    rf_l1_bytes=bytes.fromhex(rf_l1_record['bytes_hex'])
    assert len(rf_l1_bytes)==rf_l1_record['bytes'] and hashlib.sha256(rf_l1_bytes).hexdigest()==rf_l1_record['sha256']
    rf_l1_path=rf_l1_science/(rf_l1_name+'.json');rf_l1_path.write_bytes(rf_l1_bytes);rf_l1_paths[rf_l1_name]=rf_l1_path
rf_l1_policy=rf_l1_science/'host-policy.json';rf_l1_policy.write_bytes(bytes.fromhex(rf_l1_fixture['host_policy_hex']))
assert hashlib.sha256(rf_l1_policy.read_bytes()).hexdigest()==rf_l1_fixture['host_policy_sha256']
# Explicit TEST-only capacity deployment; canonical/default machine policy is unchanged.
rf_l1_capacity_resource=execution_resource_path('artifact_capacity_policy.json')
rf_l1_capacity_original=rf_l1_capacity_resource.read_bytes()
rf_l1_capacity_defaults=json.loads(rf_l1_capacity_original)
rf_l1_capacity_snapshot=dict(rf_l1_capacity_defaults,target_gib=1,minimum_free_gib=64 / 1024)
rf_l1_capacity_policy=rf_l1_science/'test-owned-capacity-policy.json'
rf_l1_capacity_policy.write_text(json.dumps(rf_l1_capacity_snapshot),encoding='utf-8')
rf_l1_capacity_selection=rf_l1_capture_capacity(rf_l1_capacity_policy)
assert rf_l1_capacity_selection['snapshot']==rf_l1_capacity_snapshot
assert pathlib.Path(rf_l1_capacity_selection['source_record']['path'])==rf_l1_capacity_policy
rf_l1_verify('installed TEST capacity policy',rf_l1_capacity_selection['source_record'])
assert rf_l1_capacity_resource.read_bytes()==rf_l1_capacity_original
rf_l1_competing=root/('rf-competing-'+sys.argv[2]);(rf_l1_competing/'msplatform').mkdir(parents=True)
(rf_l1_competing/'msplatform/__init__.py').write_text("raise RuntimeError('COMPETING_WORKER_PACKAGE_USED')\n",encoding='utf-8')
rf_l1_original_invoke=rf_l1._invoke_frozen_stage
rf_l1_cases=[]
rf_l1_inherited={key:os.environ.get(key) for key in ('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN',
    'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE')}
try:
    for rf_l1_key in rf_l1_inherited:os.environ[rf_l1_key]=''
    for rf_l1_case in ('positive','changed','missing'):
        rf_l1_workspace=root/('rf-l1-'+sys.argv[2]+'-'+rf_l1_case)
        rf_l1_stages=rf_l1_science/('stages-'+rf_l1_case+'.json')
        rf_l1_stages.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages={
            'rf_mass_filter_l1':dict(limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648,minimum_system_available_memory_bytes=1073741824,
                compact_final_retained_bytes=67108864,automatic_retry_count=0),
                artifact_retention={'policy_version':1,'class':'compact','reason':None})})),encoding='utf-8')
        rf_l1_machine=rf_l1_science/('environment-'+rf_l1_case+'.json')
        rf_l1_machine.write_text(json.dumps(dict(schema_version=1,role='execution_environment',
            tools=dict(python=sys.executable,powershell=rf_l1_fixture['powershell']),
            policy=dict(host_state_path=rf_l1_fixture['host_state_path'],policy_path=str(rf_l1_policy),
                capacity_policy_path=str(rf_l1_capacity_policy)),
            profiles={'rf_l1_test_only':dict(stage_policy_path=str(rf_l1_stages))})),encoding='utf-8')
        rf_l1_context=rf_l1_load_environment(rf_l1_machine,workspace=rf_l1_workspace,profile='rf_l1_test_only')
        assert rf_l1_context.capacity_policy_path==rf_l1_capacity_policy
        assert rf_l1_context.environment['policy']['capacity_policy_path']==str(rf_l1_capacity_policy)
        rf_l1_id='20261111_120000__test__python__installed-l1-'+sys.argv[2]+'-'+rf_l1_case
        rf_l1_seen={}
        def rf_l1_observe(session,request,stage,guards,limits):
            package_path=session.input_dir/'analysis_package.json'
            if not rf_l1_seen:
                rf_l1_seen.update(session=session,request=request.read_bytes(),package=package_path.read_bytes())
            assert request.read_bytes()==rf_l1_seen['request'] and package_path.read_bytes()==rf_l1_seen['package']
            if stage=='simulation' and rf_l1_case!='positive':
                package=json.loads(package_path.read_text(encoding='utf-8'))['package']
                row=next(row for row in package['files'] if row['relative_path'].endswith('/analysis/peak_metrics.py'))
                target=pathlib.Path(row['path']);raw=target.read_bytes()
                assert hashlib.sha256(raw).hexdigest().upper()==row['sha256']
                rf_l1_seen.update(target=target,original=raw,record=row)
                if rf_l1_case=='changed':target.write_bytes(raw+b'\n# changed frozen input\n')
                else:target.unlink()
            process=session.run_process
            def rf_l1_worker(*args,**kwargs):
                kwargs['environment']={**kwargs.get('environment',{}),'PYTHONPATH':str(rf_l1_competing)}
                arguments=list(kwargs['arguments']);arguments[-1]="[Console]::Out.WriteLine('INSTALLED_RF_WORKER=' + $env:PYTHONPATH)\n"+arguments[-1]
                kwargs['arguments']=arguments
                return process(*args,**kwargs)
            with rf_l1_patch.object(session,'run_process',side_effect=rf_l1_worker):
                receipt=rf_l1_original_invoke(session,request,stage,guards,limits)
            ordinal=session.expected_operation_ids.index(stage)+1
            assert 'INSTALLED_RF_WORKER='+str(rf_l1_competing) in (session.log_dir/f'operation_{ordinal:04d}.stdout.log').read_text(encoding='utf-8')
            assert request.read_bytes()==rf_l1_seen['request'] and package_path.read_bytes()==rf_l1_seen['package']
            return receipt
        rf_l1_error=None
        try:
            with rf_l1_patch.object(rf_l1,'_invoke_frozen_stage',side_effect=rf_l1_observe),\
                 rf_l1_patch.object(rf_l1_kernel,'simulate_mass',side_effect=RuntimeError('INSTALLED_LIVE_PARENT_KERNEL_USED')):
                rf_l1.run(rf_l1_context,baseline_path=rf_l1_paths['baseline'],resolved_path=rf_l1_paths['resolved'],
                    mode_path=rf_l1_paths['mode'],source_path=rf_l1_paths['source'],run_id=rf_l1_id)
        except RuntimeError as error:
            if 'session' not in rf_l1_seen:
                raise
            rf_l1_error=error
        session=rf_l1_seen['session'];project=rf_l1_workspace/'artifacts/projects/rf_multipole_ion_optics'
        result_path=project/'scratch/workflow_results'/rf_l1_id/'result.json'
        result=json.loads(result_path.read_text(encoding='utf-8'))
        assert result['writers_confirmed'] is True
        rf_l1_captured_capacity=result['capacity_session']['capacity_policy']
        assert rf_l1_captured_capacity['source_record']==rf_l1_capacity_selection['source_record']
        assert rf_l1_captured_capacity['snapshot']==rf_l1_capacity_selection['snapshot']
        assert rf_l1_captured_capacity['snapshot_sha256']==rf_l1_capacity_selection['snapshot_sha256']
        rf_l1_verify('owner frozen TEST capacity policy',rf_l1_captured_capacity['frozen_record'])
        assert pathlib.Path(rf_l1_captured_capacity['frozen_record']['path'])==session.input_dir/'capacity_policy.json'
        assert json.loads(pathlib.Path(rf_l1_captured_capacity['frozen_record']['path']).read_text(encoding='utf-8'))==rf_l1_capacity_snapshot
        assert (session.input_dir/'analysis_request.json').read_bytes()==rf_l1_seen['request']
        assert (session.input_dir/'analysis_package.json').read_bytes()==rf_l1_seen['package']
        if rf_l1_case=='positive':
            assert rf_l1_error is None,str(rf_l1_error)
            assert result['status']=='success' and result['resume_action'] is None
            assert [op['operation_id'] for op in session.operations]==['prepare','simulation','analysis']
            for op in session.operations:
                observation=op['observation']
                assert observation['exit_confirmed'] and observation['returncode']==0
                assert observation['process_id']>0 and observation['process_started_at_utc_ticks']>0
            assert (session.result_dir/'mass-response__finite-length.csv').read_bytes()==bytes.fromhex(rf_l1_fixture['expected_csv_hex'])
            rf_l1_metrics=json.loads((session.result_dir/'mass-filter__functional-metrics.json').read_text(encoding='utf-8'))
            for key,value in rf_l1_fixture['expected_metrics'].items():assert rf_l1_metrics[key]==value,key
            package=json.loads(rf_l1_seen['package'])['package']
            for row in package['files']:
                assert hashlib.sha256(pathlib.Path(row['path']).read_bytes()).hexdigest().upper()==row['sha256']
            assert any(row['relative_path']=='msplatform/execution/resources/frozen_python_package.ps1' for row in package['files'])
            request=json.loads(rf_l1_seen['request'])
            assert request['schema_version']==2
            assert pathlib.Path(request['forbidden_roots'][0]).resolve()==pathlib.Path(rf_l1.__file__).resolve().parents[2]
            rf_l1_verify('installed RF manifest',result['manifest'])
            manifest=json.loads(pathlib.Path(result['manifest']['path']).read_text(encoding='utf-8'))
            for row in manifest['outputs']:rf_l1_verify('installed RF output',row)
            releases={row['release_id']:row['completion_receipt']['host_release'] for row in session.resource_releases}
            for op in session.operations:
                release=releases[op['resource_release_id']]
                assert release['inherited'] is False and release['error'] is None
                assert release['result']=={'status':'released','token':release['token']}
            for stage in ('simulation','analysis'):
                receipt=json.loads((session.result_dir/(stage+'_execution.json')).read_text(encoding='utf-8'))
                assert receipt['schema_version']==2 and receipt['status']=='success'
                rf_l1_module_origins={row['name']:pathlib.Path(row['origin']) for row in receipt['environment']['frozen_modules']}
                assert 'msplatform.workflows.rf_mass_filter.finite_length' in rf_l1_module_origins
                assert 'msplatform.components.rf_multipole.finite_length_transport' in rf_l1_module_origins
                for row in receipt['environment']['frozen_modules']:
                    assert pathlib.Path(row['origin']).is_relative_to(session.input_dir/'analysis_code')
        else:
            assert rf_l1_error is not None and ('hash differs' if rf_l1_case=='changed' else 'missing') in str(rf_l1_error),str(rf_l1_error)
            assert result['status']=='failed' and [op['operation_id'] for op in session.operations]==['prepare']
            assert not (session.result_dir/'simulation_execution.json').exists()
            failure=session.result_dir/'failure_context.json';failure_before=failure.read_bytes()
            target=rf_l1_seen['target'];raw=rf_l1_seen['original'];record=rf_l1_seen['record']
            if rf_l1_case=='missing':
                assert not target.exists() and result['resume_action']=='resume_finalization'
                assert hashlib.sha256(raw).hexdigest().upper()==record['sha256']
                with target.open('xb') as stream:stream.write(raw)
                assert target.stat().st_size==len(raw)
                result=rf_l1_resume(rf_l1_context,result_path,completion_api=rf_l1_completion)
            else:target.write_bytes(raw)
            assert result['status']=='failed' and result['resume_action'] is None
            assert failure.read_bytes()==failure_before
            assert [op['operation_id'] for op in session.operations]==['prepare']
        assert result['capacity_session']['status']=='released'
        assert rf_l1_capacity(rf_l1_workspace/'artifacts')['audit']==[]
        rf_l1_cases.append(dict(case=rf_l1_case,status=result['status'],operations=len(session.operations)))
finally:
    for rf_l1_key,rf_l1_value in rf_l1_inherited.items():
        if rf_l1_value is None:os.environ.pop(rf_l1_key,None)
        else:os.environ[rf_l1_key]=rf_l1_value
for rf_l1_name,rf_l1_path in rf_l1_paths.items():
    assert hashlib.sha256(rf_l1_path.read_bytes()).hexdigest()==rf_l1_fixture['inputs'][rf_l1_name]['sha256']
assert len(rf_l1_cases)==3
assert rf_l1_capacity_resource.read_bytes()==rf_l1_capacity_original
rf_l1_verify('unchanged TEST capacity selection',rf_l1_capacity_selection['source_record'])
print('INSTALLED_RF_MANAGED_L1=PASS '+json.dumps(rf_l1_cases))
# RF_MANAGED_L1_INSTALLED_END

# MR_L0_INSTALLED_BEGIN
mr_l0_script=root/('installed-mr-l0-'+sys.argv[2]+'.py')
mr_l0_script.write_text(r"""import functools,hashlib,importlib,importlib.abc,json,math,os,pathlib,sys,sysconfig
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import patch
NAMES=('msplatform.components.parallel_mirror_dual_stripe_mr_tof.mirror_l0','msplatform.workflows.mr_design')
def guards(authors):
    roots=[pathlib.Path(p).resolve() for p in authors]
    def deny(event,args):
        if event=='open' and args and isinstance(args[0],str):
            p=pathlib.Path(args[0]).resolve()
            if any(p.is_relative_to(r) for r in roots):raise AssertionError('author read '+str(p))
    sys.addaudithook(deny)
    class NeutralOnly(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if any(fullname==p or fullname.startswith(p+'.') for p in ('common','projects','integrations','tools','msplatform.backends','msplatform.execution')):raise AssertionError(fullname)
    sys.meta_path.insert(0,NeutralOnly())
def origins(expected=None):
    purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
    rows={}
    for name in NAMES:
        module=importlib.import_module(name);path=pathlib.Path(module.__file__).resolve()
        assert path.is_relative_to(purelib)
        rows[name]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if expected is not None:assert rows==expected
    return rows
def worker_initializer(expected,authors,directory):
    # TEST-only constructor instrumentation; original worker/physics/RNG untouched.
    guards(authors);rows=origins(expected)
    path=pathlib.Path(directory)/('worker-'+str(os.getpid())+'.json')
    path.write_text(json.dumps(dict(pid=os.getpid(),origins=rows)),encoding='utf-8')
def main():
    authors=json.loads(sys.argv[1]);directory=pathlib.Path(sys.argv[2]);guards(authors)
    expected=origins()
    m=importlib.import_module(NAMES[0]);w=importlib.import_module(NAMES[1])
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError
    assert m.CandidateContractError is CandidateContractError and w.CandidateContractError is CandidateContractError
    assert m.step_response(0.)==.5 and m.step_response_derivative(0.)==.5
    design=m.MirrorL0Design(15.,(0.,164.5,226.5,258.5,288.5),(0.,-500.,2000.,3500.,7000.),320.,7000.)
    for z in (20.,164.5,250.,319.):
        difference=(m.axial_potential_v(z+1e-4,design)-m.axial_potential_v(z-1e-4,design))/(2e-4)
        gradient=m.axial_potential_gradient_v_per_mm(z,design)
        assert abs(gradient-difference)<.5e-6
        assert abs(m.axial_potential_gradient_v_per_mm(-z,design)+gradient)<.5e-12
    assert m.axial_potential_gradient_v_per_mm(0.,design)==0.
    assert abs(m.effective_axial_width_mm(4000.,641./math.sqrt(4000.))-641.)<.5e-7
    for call in (lambda:m.effective_axial_width_mm(4000.,0.),lambda:m.turning_point_mm(0.,design),
                 lambda:m.normalized_period_slope_per_v(design,4000.,0.)):
        try:call()
        except CandidateContractError:pass
        else:raise AssertionError('original invalid input accepted')
    slopes=m.three_point_normalized_period_slopes_per_v(design,(3900.,4000.,4100.),1.)
    assert len(slopes)==3 and all(math.isfinite(v) for v in slopes)
    assert abs(slopes[1]-m.normalized_period_slope_per_v(design,4000.,1.))<.5e-7
    turning=m.turning_point_mm(4000.,design)
    # First upward crossing: no earlier sampled upward bracket may be bypassed.
    points=[320.*i/256 for i in range(257)]
    earlier=[(lo,hi) for lo,hi in zip(points,points[1:]) if m.axial_potential_v(lo,design)<=4000.<=m.axial_potential_v(hi,design)]
    assert earlier and earlier[0][0]<=turning<=earlier[0][1]
    assert abs(m.axial_potential_v(turning,design)-4000.)<1e-7
    args=(15.,(0.,164.5,226.5,258.5,288.5),(-10000.,-10000.,-10000.,4100.001),
          (10000.,10000.,10000.,10000.),1.,1e-7,(3900.,4000.,4100.),7,1,1,1,1,1e-7,320.,20)
    # Real ProcessPoolExecutor and original map/work entry; only initializer added.
    with patch.object(w,'ProcessPoolExecutor',functools.partial(ProcessPoolExecutor,
            initializer=worker_initializer,initargs=(expected,authors,str(directory)))):
        result=w.parallel_global_l0_family_search(*args)
    search=result['parallel_restart_search']
    assert search['actual_workers']==1 and search['restart_count']==1
    assert len(result['restart_receipts'])==1
    receipt=result['restart_receipts'][0]
    assert receipt['transition_z_mm']==[0.,164.5,226.5,258.5,288.5]
    serial=w.global_l0_family_search(*args[:7],search['restart_seeds'][0],*args[10:])
    assert serial==receipt
    json.dumps(result,allow_nan=False)
    files=list(directory.glob('worker-*.json'));assert len(files)==1
    proof=json.loads(files[0].read_text(encoding='utf-8'))
    assert type(proof['pid']) is int and proof['pid']>0 and proof['pid']!=os.getpid()
    assert proof['origins']==expected
    assert origins()==expected
    print(json.dumps(dict(status='PASS',origins=expected,worker=proof,model='ideal mirror L0 only; not L1/native qualified')))
if __name__=='__main__':main()
""",encoding='utf-8')
mr_l0_worker_proof=root/('installed-mr-l0-workers-'+sys.argv[2]);mr_l0_worker_proof.mkdir()
mr_l0_args=[sys.executable,'-I','-B',str(mr_l0_script),
            json.dumps([str(p) for p in blocked_source_roots]),str(mr_l0_worker_proof)]
mr_l0_child=subprocess.run(mr_l0_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
assert mr_l0_child.returncode==0,mr_l0_child.stdout+mr_l0_child.stderr
mr_l0_report=json.loads(mr_l0_child.stdout)
assert mr_l0_report['status']=='PASS'
for mr_l0_name,mr_l0_record in mr_l0_report['origins'].items():
    mr_l0_path=pathlib.Path(mr_l0_record['path']);mr_l0_bytes=mr_l0_path.read_bytes()
    assert hashlib.sha256(mr_l0_bytes).hexdigest()==mr_l0_record['sha256']
    mr_l0_held=mr_l0_path.with_name(mr_l0_path.name+'.missing-test-held');assert not mr_l0_held.exists()
    mr_l0_path.rename(mr_l0_held)
    try:
        mr_l0_missing=subprocess.run(mr_l0_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
        assert mr_l0_missing.returncode!=0 and 'ModuleNotFoundError' in mr_l0_missing.stderr and mr_l0_name in mr_l0_missing.stderr,mr_l0_missing.stderr
        missing_rejected.append(mr_l0_name)
    finally:mr_l0_held.rename(mr_l0_path)
    assert mr_l0_path.read_bytes()==mr_l0_bytes
print('INSTALLED_MR_L0_DOMAIN_WORKFLOW=PASS')
# MR_L0_INSTALLED_END

# SCALAR_ADAPTER_INSTALLED_BEGIN
# Software-only PA API fixture; production compiler/resource own serialization/routing.
import msplatform.backends.comsol.static_field_binding as scalar_compiler
import msplatform.backends.simion.resources as scalar_resources
scalar_fixture=fixture['scalar_adapter']
scalar_purelib=pathlib.Path(sysconfig.get_paths()['purelib']).resolve()
scalar_module_path=pathlib.Path(scalar_compiler.__file__).resolve()
scalar_resources_module_path=pathlib.Path(scalar_resources.__file__).resolve()
scalar_resource_path=scalar_resources.native_resource_path('scalar_field_adapter.lua').resolve()
assert scalar_module_path==scalar_purelib/'msplatform/backends/comsol/static_field_binding.py'
assert scalar_resources_module_path==scalar_purelib/'msplatform/backends/simion/resources.py'
assert scalar_resource_path==scalar_purelib/'msplatform/backends/simion/resources/scalar_field_adapter.lua'
assert not (scalar_purelib/'msplatform/components/parallel_mirror_dual_stripe_mr_tof/resources/scalar_field_adapter.lua').exists()
for scalar_relative,scalar_path in (('backends/comsol/static_field_binding.py',scalar_module_path),
                                    ('backends/simion/resources.py',scalar_resources_module_path),
                                    ('backends/simion/resources/scalar_field_adapter.lua',scalar_resource_path)):
    scalar_content=scalar_path.read_bytes()
    assert len(scalar_content)==scalar_fixture['sources'][scalar_relative]['bytes']
    assert hashlib.sha256(scalar_content).hexdigest()==scalar_fixture['sources'][scalar_relative]['sha256']
scalar_executable=pathlib.Path(scalar_fixture['executable']['path'])
assert scalar_executable.is_absolute() and scalar_executable.is_file()
scalar_executable_bytes=scalar_executable.read_bytes()
assert len(scalar_executable_bytes)==scalar_fixture['executable']['bytes']
assert hashlib.sha256(scalar_executable_bytes).hexdigest()==scalar_fixture['executable']['sha256']
assert scalar_fixture['version_stdout'] or scalar_fixture['version_stderr']
scalar_directory=root/('installed-scalar-adapter-'+analysis_round)
scalar_directory.mkdir()
scalar_base={'sources':{'scalar_pa':'base V.pa','valid_pa':'base mask.pa'},
             'grid':{'origin_mm':[-4,-4,-4],'pitch_mm':[1,1,1]},'ideal_sheet_projection':[]}
scalar_first={'name':'first','sources':{'scalar_pa':'first V.pa','valid_pa':'first mask.pa'},
              'grid':{'origin_mm':[0,0,0],'pitch_mm':[.25,.125,.5]},
              'ideal_sheet_projection':[],'active_box_mm':[[.5,1],[.25,.5],[1,2]]}
scalar_second={'name':'second','sources':{'scalar_pa':'second V.pa','valid_pa':'second mask.pa'},
               'grid':{'origin_mm':[-.125,-.25,-.5],'pitch_mm':[.125,.25,.25]},
               'ideal_sheet_projection':[],'active_box_mm':[[.75,1.5],[.375,.75],[1.5,3]]}
scalar_ordered=dict(scalar_base,refinement_windows=[scalar_first,scalar_second])
scalar_reversed=dict(scalar_base,refinement_windows=[scalar_second,scalar_first])
scalar_samples=scalar_directory/'samples.csv'
scalar_samples.write_text('name,x_mm,y_mm,z_mm\nfirst_min,.5,.25,1\nfirst_max,1,.5,2\noverlap,.875,.4375,1.75\nsecond_max,1.5,.75,3\noutside,1.8,.8,3.2\nplain,.875,.4375,1.75\n',encoding='utf-8')
scalar_request=scalar_directory/'ordered.lua'
scalar_plain_request=scalar_directory/'plain.lua'
scalar_request.write_text(scalar_compiler.compile_sampling_request(scalar_ordered,scalar_reversed,scalar_samples,scalar_directory/'ordered.csv'),encoding='utf-8')
scalar_plain_request.write_text(scalar_compiler.compile_sampling_request(scalar_base,scalar_ordered,scalar_samples,scalar_directory/'plain.csv'),encoding='utf-8')
scalar_lua_source=scalar_directory/'fixture.lua'
scalar_lua_source.write_text("\nlocal unknown=false;local calls={base=0,first=0,second=0};local assets={}\nlocal specs={base={12,12,12,1,1,1},first={9,9,9,.25,.125,.5},second={17,9,17,.125,.25,.25}}\nfor name,s in pairs(specs) do\n local pa={name=name,symmetry='3dplanar',nx=s[1],ny=s[2],nz=s[3],dx_mm=s[4],dy_mm=s[5],dz_mm=s[6]}\n function pa:potential() return 2 end\n function pa:save() error('PA save forbidden') end\n local mask={symmetry=pa.symmetry,nx=pa.nx,ny=pa.ny,nz=pa.nz,dx_mm=pa.dx_mm,dy_mm=pa.dy_mm,dz_mm=pa.dz_mm}\n function mask:potential() return (name=='first' and unknown) and 0 or 1 end\n assets[name..' V.pa']=pa;assets[name..' mask.pa']=mask\nend\nsimion={early_access=function() end,pas={},experimental={}}\nfunction simion.pas:open(path) return assert(assets[path],'transported PA path differs') end\nfunction simion.experimental.field_array(t)\n assert(t.type=='V' and t.antimirror=='')\n return {efield=function(x,y,z)\n  calls[t.V.name]=calls[t.V.name]+1\n  -- Different origins/pitches survive transport; FA receives physical local mm.\n  if t.V.name=='base' then assert(x>=4 and y>=4 and z>=4);return 1,2,3\n  elseif t.V.name=='first' then assert(x>=.5 and x<=1 and y>=.25 and y<=.5 and z>=1 and z<=2);return 11,12,13\n  else assert(x>=.875 and x<=1.625 and y>=.625 and y<=1 and z>=2 and z<=3.5);return 21,22,23 end\n end}\nend\nfunction simion.experimental.make_efield_adjust(f) return f end\nlocal scalar_request=assert(loadfile(arg[1]))()\nlocal scalar_plain_request=assert(loadfile(arg[2]))()\nassert(scalar_request.schema_version==1 and scalar_plain_request.schema_version==1)\nassert(scalar_request.adapter==scalar_plain_request.adapter)\nassert(#scalar_request.samples==6 and #scalar_plain_request.samples==6)\nlocal apply=assert(loadfile(scalar_request.adapter))()\nlocal ordered_binding=scalar_request.a\nlocal reversed_binding=scalar_request.b\nlocal plain_binding=scalar_plain_request.a\n\nassert(ordered_binding.refinement_windows[1].name=='first' and ordered_binding.refinement_windows[2].name=='second')\nassert(ordered_binding.refinement_windows[1].pitch_mm[2]==.125 and ordered_binding.refinement_windows[2].pitch_mm[2]==.25)\nlocal function check(f,x,y,z,value)\n local ex,ey,ez=f(x,y,z);assert(ex==value and ey==value+1 and ez==value+2)\nend\ncheck(apply(plain_binding),.875,.4375,1.75,1)\nlocal field=apply(ordered_binding)\ncheck(field,.5,.25,1,11);check(field,1,.5,2,11) -- inclusive first-window corners\ncheck(field,.875,.4375,1.75,11) -- overlap goes to the first serialized window\ncheck(field,1.5,.75,3,21) -- inclusive second-window maximum with its own halo\ncheck(field,1.8,.8,3.2,1)\ncheck(apply(reversed_binding),.875,.4375,1.75,21)\nlocal beforeBase,beforeSecond=calls.base,calls.second\nunknown=true\nlocal ok,err=pcall(field,.875,.4375,1.75)\nassert(not ok and tostring(err):find('V_SUPPORT_UNKNOWN',1,true))\nassert(calls.base==beforeBase and calls.second==beforeSecond,'serialized window silently fell back')\nprint('GENERATED_SCALAR_TRANSPORT_FIXTURE_PASS')\n",encoding='utf-8')
scalar_child=subprocess.run([str(scalar_executable),str(scalar_lua_source),str(scalar_request),str(scalar_plain_request)],
                            cwd=scalar_directory,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=10,check=False)
assert scalar_child.returncode==0,scalar_child.stdout+scalar_child.stderr
assert 'GENERATED_SCALAR_TRANSPORT_FIXTURE_PASS' in scalar_child.stdout
scalar_resource_bytes=scalar_resource_path.read_bytes()
scalar_held=scalar_resource_path.with_name(scalar_resource_path.name+'.missing-test-held')
assert not scalar_held.exists()
scalar_resource_path.rename(scalar_held)
try:
    try:
        scalar_compiler.compile_sampling_request(scalar_ordered,scalar_reversed,scalar_samples,scalar_directory/'missing.csv')
    except FileNotFoundError as scalar_error:
        assert 'scalar_field_adapter.lua' in str(scalar_error)
        missing_rejected.append('scalar_field_adapter')
    else:raise AssertionError('missing selected scalar resource was accepted')
finally:scalar_held.rename(scalar_resource_path)
assert scalar_resource_path.read_bytes()==scalar_resource_bytes
assert scalar_executable.read_bytes()==scalar_executable_bytes
print('INSTALLED_SCALAR_ADAPTER_TRANSPORT=PASS')
# SCALAR_ADAPTER_INSTALLED_END

# MR_PRISM_PHASE_INSTALLED_BEGIN
# Ideal/reference scientific APIs only; finite-field calibration remains separate.
import unittest as prism_unittest
from msplatform.components.parallel_mirror_dual_stripe_mr_tof import prism_l0 as prism_l0_api
from msplatform.components.parallel_mirror_dual_stripe_mr_tof import prism_analytic as prism_analytic_api
from msplatform.components.parallel_mirror_dual_stripe_mr_tof import drift_phase_contract as prism_phase_api
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError as prism_contract_error
prism_fixture=fixture['mr_prism_phase']
prism_purelib=pathlib.Path(sysconfig.get_paths()['purelib']).resolve()
for prism_name,prism_module in (('prism_l0',prism_l0_api),('prism_analytic',prism_analytic_api),('drift_phase_contract',prism_phase_api)):
    prism_path=pathlib.Path(prism_module.__file__).resolve()
    assert prism_path==prism_purelib/'msplatform/components/parallel_mirror_dual_stripe_mr_tof'/(prism_name+'.py')
    prism_content=prism_path.read_bytes()
    assert len(prism_content)==prism_fixture['sources'][prism_name]['bytes']
    assert hashlib.sha256(prism_content).hexdigest()==prism_fixture['sources'][prism_name]['sha256']
    try:importlib.import_module('projects.parallel_mirror_dual_stripe_mr_tof.analysis.'+prism_name)
    except AssertionError as prism_error:
        assert 'installed action imported a repository owner' in str(prism_error)
    else:raise AssertionError('installed MR reference accepted a repository import')
prism_check=prism_unittest.TestCase()
prism_contract=copy.deepcopy(prism_fixture['contract'])
prism_result=prism_l0_api.derive_first_prism_l0(prism_contract)
assert (prism_result.total_kinetic_energy_ev,prism_result.drift_kinetic_energy_ev,prism_result.fast_kinetic_energy_ev)==(4005.,5.,4000.)
assert prism_result.entry_position_project_mm==(0.,-45.,0.)
assert prism_result.entry_unit_direction_project==(0.,0.,-1.)
assert prism_result.triangle_entry_project_mm==(0.,-45.,-62.828)
assert prism_result.triangle_exit_project_mm==(0.,-45.,-67.172)
assert prism_result.target_plane_z_mm==-101.
assert prism_result.target_plane_y_acceptance_mm==(-75.,-35.)
assert prism_result.second_prism_status=='low_field_angle_and_positive_mirror_turn_calibration_pending'
prism_check.assertAlmostEqual(prism_result.drift_angle_degrees,2.0248682972773406)
prism_check.assertAlmostEqual(prism_result.hard_boundary_seed_voltage_v,20000.**.5)
prism_parameterized=copy.deepcopy(prism_contract)
prism_parameterized['prism_transport']['energy_partition'].update(total_kinetic_energy_ev=4006,drift_kinetic_energy_ev=6,fast_reflection_kinetic_energy_ev=4000)
prism_parameterized['prism_transport']['first_prism']['target_interface']['coordinate_mm']=-100.5
prism_parameterized_result=prism_l0_api.derive_first_prism_l0(prism_parameterized)
assert (prism_parameterized_result.total_kinetic_energy_ev,prism_parameterized_result.drift_kinetic_energy_ev,prism_parameterized_result.fast_kinetic_energy_ev,prism_parameterized_result.target_plane_z_mm)==(4006.,6.,4000.,-100.5)
prism_check.assertAlmostEqual(prism_parameterized_result.hard_boundary_seed_voltage_v,(6.*4000.)**.5)
prism_bad_energy=copy.deepcopy(prism_contract)
prism_bad_energy['prism_transport']['energy_partition']['total_kinetic_energy_ev']=4000
with prism_check.assertRaises(prism_l0_api.PrismL0Error):prism_l0_api.derive_first_prism_l0(prism_bad_energy)
prism_bad_slot=copy.deepcopy(prism_contract)
prism_bad_slot['prism_transport']['first_prism']['target_interface']['ground_shield_id']=20
with prism_check.assertRaises(prism_l0_api.PrismL0Error):prism_l0_api.derive_first_prism_l0(prism_bad_slot)
prism_analytic=prism_fixture['analytic']
prism_bias=prism_analytic_api.hard_boundary_bias_v(prism_analytic['energy'],prism_analytic['alpha'],prism_analytic['beta'])
prism_check.assertAlmostEqual(prism_bias,-152.76516286150414)
prism_check.assertAlmostEqual(prism_analytic_api.hard_boundary_exit_angle_deg(4000.,4.,prism_bias),1.8)
prism_trace=prism_analytic_api.trace_triangular_hard_boundary_prism(prism_analytic['triangle'],prism_analytic['origin'],prism_analytic['direction'],prism_analytic['energy'],prism_bias,charge_sign=1)
assert (prism_trace.status,prism_trace.entry_edge_index,prism_trace.exit_edge_index)==('transmitted',0,2)
prism_check.assertAlmostEqual(prism_trace.resulting_kinetic_energy_per_charge_v,4000.)
prism_check.assertAlmostEqual(prism_trace.hamiltonian_residual_per_charge_v,0.)
prism_check.assertAlmostEqual(45.-math.degrees(math.acos(-prism_trace.resulting_unit_direction_yz[0])),prism_analytic['beta'],places=11)
prism_negative=prism_analytic_api.trace_triangular_hard_boundary_prism(prism_analytic['triangle'],prism_analytic['origin'],prism_analytic['direction'],prism_analytic['energy'],-prism_bias,charge_sign=-1)
assert prism_negative.status=='transmitted'
assert prism_negative.inside_kinetic_energy_per_charge_v==prism_trace.inside_kinetic_energy_per_charge_v
for prism_actual,prism_expected in zip(prism_negative.resulting_unit_direction_yz,prism_trace.resulting_unit_direction_yz):
    prism_check.assertAlmostEqual(prism_actual,prism_expected,places=12)
for prism_sign in (1,-1):
    prism_recovered=prism_analytic_api.hard_boundary_bias_for_face_order_and_target_direction_v(prism_analytic['triangle'],prism_analytic['direction'],prism_trace.resulting_unit_direction_yz,4000.,entry_edge_index=0,exit_edge_index=2,charge_sign=prism_sign)
    prism_check.assertAlmostEqual(prism_recovered,prism_sign*prism_bias,places=11)
with prism_check.assertRaisesRegex(prism_analytic_api.PrismAnalyticError,'does not leave'):
    prism_analytic_api.hard_boundary_bias_for_face_order_and_target_direction_v(prism_analytic['triangle'],prism_analytic['direction'],tuple(-prism_value for prism_value in prism_trace.resulting_unit_direction_yz),4000.,entry_edge_index=0,exit_edge_index=2,charge_sign=1)
with prism_check.assertRaisesRegex(prism_analytic_api.PrismAnalyticError,'charge_sign'):
    prism_analytic_api.trace_triangular_hard_boundary_prism(prism_analytic['triangle'],(.2,-1.),(0.,1.),10.,0.,charge_sign=0)
with prism_check.assertRaises(prism_analytic_api.PrismAnalyticError):prism_analytic_api.hard_boundary_bias_correction_v(0.,3.,2.)
for prism_phase_input,prism_ratio,prism_half in zip(prism_fixture['phases'],(25.5,31.5),(51,63)):
    prism_phase=prism_phase_api.resolve_drift_phase_contract(prism_phase_input)
    assert prism_phase.target_period_ratio==prism_ratio
    assert prism_phase.target_half_oscillation_count==prism_half
    assert (prism_phase.origin_mirror_side,prism_phase.return_mirror_side)==(1,-1)
assert prism_phase_api.resolve_drift_phase_contract(prism_fixture['phases'][0]).complete_oscillation_count==25
prism_integer_phase=copy.deepcopy(prism_fixture['phases'][0])
prism_integer_phase['nominal']['target_drift_period_ratio']=25
with prism_check.assertRaisesRegex(prism_contract_error,'half-integer'):prism_phase_api.resolve_drift_phase_contract(prism_integer_phase)
prism_bad_phase=copy.deepcopy(prism_fixture['phases'][0])
prism_bad_phase['nominal']['fast_path_symmetry']='same_positive_mirror_turn'
with prism_check.assertRaises(prism_contract_error):prism_phase_api.resolve_drift_phase_contract(prism_bad_phase)
print('INSTALLED_MR_PRISM_PHASE=PASS')
# MR_PRISM_PHASE_INSTALLED_END

# MR_STRIPE_INSTALLED_BEGIN
# Actual pure APIs and original bounded math oracles; no native execution.
stripe_script=root/('installed-mr-stripe-'+sys.argv[2]+'.py')
stripe_script.write_text(r"""import copy,hashlib,importlib,importlib.abc,json,math,pathlib,sys,sysconfig,unittest
from decimal import Decimal,localcontext

def main():
    stripe_authors=[pathlib.Path(value).resolve() for value in json.loads(sys.argv[1])]
    def stripe_deny_reads(event,args):
        if event=='open' and args and isinstance(args[0],str):
            stripe_open_path=pathlib.Path(args[0]).resolve()
            if any(stripe_open_path.is_relative_to(value) for value in stripe_authors):
                raise AssertionError('installed Stripe read author source '+str(stripe_open_path))
    sys.addaudithook(stripe_deny_reads)
    class StripePureOnly(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if any(fullname==value or fullname.startswith(value+'.') for value in
                   ('common','projects','integrations','tools','msplatform.backends','msplatform.execution')):
                raise AssertionError('installed Stripe imported forbidden owner '+fullname)
    sys.meta_path.insert(0,StripePureOnly())
    stripe_fixture=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))
    stripe_api=importlib.import_module('msplatform.components.parallel_mirror_dual_stripe_mr_tof.dual_stripe_l0')
    stripe_workflow=importlib.import_module('msplatform.workflows.mr_design')
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError as stripe_error
    stripe_check=unittest.TestCase()
    stripe_purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
    stripe_origins={}
    for stripe_name,stripe_module,stripe_relative in (
        ('dual_stripe_l0',stripe_api,'msplatform/components/parallel_mirror_dual_stripe_mr_tof/dual_stripe_l0.py'),
        ('mr_design',stripe_workflow,'msplatform/workflows/mr_design.py')):
        stripe_path=pathlib.Path(stripe_module.__file__).resolve()
        assert stripe_path==stripe_purelib/stripe_relative
        stripe_bytes=stripe_path.read_bytes()
        assert len(stripe_bytes)==stripe_fixture['sources'][stripe_name]['bytes']
        assert hashlib.sha256(stripe_bytes).hexdigest()==stripe_fixture['sources'][stripe_name]['sha256']
        stripe_origins[stripe_name]=str(stripe_path)
    with stripe_check.assertRaisesRegex(AssertionError,'forbidden owner projects'):
        importlib.import_module('projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0')
    stripe_response_results=[]
    for stripe_case in stripe_fixture['responses']:
        stripe_contract=copy.deepcopy(stripe_case['contract'])
        stripe_oa=copy.deepcopy(stripe_case['pure_geometry_inputs'])
        stripe_before=json.dumps(dict(contract=stripe_contract,oa=stripe_oa),sort_keys=True)
        stripe_kwargs={} if stripe_case['axial_energy_per_charge_v'] is None else {
            'axial_energy_per_charge_v':stripe_case['axial_energy_per_charge_v']}
        stripe_result=stripe_api.analyze_dual_stripe_l0(
            stripe_contract,(-40.,60.),**stripe_oa,**stripe_kwargs)
        stripe_expected_report=stripe_fixture['response_metadata']
        assert stripe_result.keys()==set(stripe_expected_report['keys'])
        for stripe_metadata_key in ('model','geometry_status','not_evaluated'):
            assert stripe_result[stripe_metadata_key]==stripe_expected_report[stripe_metadata_key]
        assert stripe_result['biases_v']==[-40.,60.]
        assert len(stripe_result['h_factors'])==2
        assert stripe_result['response_matrix']==[[1.,1.],stripe_result['h_factors']]
        assert stripe_result['physical_width_bounds_mm'].keys()=={'set_1','set_2'}
        assert stripe_result['theory_cad_component_mapping'].keys()=={'high_order_width_response','linear_width_response','linear_width_fit'}
        assert stripe_result['theory_cad_component_mapping']['linear_width_fit'].keys()=={
            'intercept_at_first_y_mm','slope_mm_per_mm','maximum_residual_mm'}
        stripe_selected_energy=(stripe_contract['nominal']['energy_per_charge_v']
                                if stripe_case['axial_energy_per_charge_v'] is None
                                else stripe_case['axial_energy_per_charge_v'])
        assert stripe_result['energy_per_charge_v']==stripe_selected_energy
        stripe_check.assertAlmostEqual(stripe_result['h_factors'][0],math.sqrt(stripe_selected_energy/(stripe_selected_energy+40.)))
        stripe_response_results.append(stripe_result)
        assert json.dumps(dict(contract=stripe_contract,oa=stripe_oa),sort_keys=True)==stripe_before
        assert stripe_result['response_matrix_determinant']!=0.
        assert math.isfinite(stripe_result['response_matrix_condition_number_2'])
        assert stripe_result['physical_width_bounds_mm']['set_1'][0]>0.
        assert stripe_result['physical_width_bounds_mm']['set_2'][0]>0.
        assert stripe_result['theory_cad_component_mapping']['high_order_width_response']=='set_1'
        assert stripe_result['theory_cad_component_mapping']['linear_width_response']=='set_2'
        assert stripe_result['theory_cad_component_mapping']['linear_width_fit']['maximum_residual_mm']<.002
    assert stripe_response_results[0]['h_factors']!=stripe_response_results[1]['h_factors']
    stripe_first=stripe_fixture['responses'][0]
    for stripe_biases in ((0.,60.),(-40.,-40.),(-40.,math.nan),(-40.,math.inf),(-40.,)):
        with stripe_check.assertRaises(stripe_error):
            stripe_api.analyze_dual_stripe_l0(stripe_first['contract'],stripe_biases,**stripe_first['pure_geometry_inputs'])
    with stripe_check.assertRaises(stripe_error):
        stripe_workflow.analyze_native_dual_stripe_l0(
            stripe_first['contract'],(0.,60.),accelerator_geometry_authority={})
    stripe_check.assertAlmostEqual(stripe_api.endpoint_regularized_kappa(lambda eta:eta),2.,places=8)
    stripe_check.assertAlmostEqual(stripe_api.endpoint_regularized_kappa_at_turn(lambda eta:eta,1.21),2.2,places=8)
    stripe_check.assertAlmostEqual(stripe_api.kappa_derivative_at_turn(lambda eta:eta,1.,step=1e-3),1.,places=5)
    stripe_check.assertAlmostEqual(stripe_api.endpoint_regularized_tau_g(lambda eta:eta,lambda eta:1.,1.),2.,places=8)
    stripe_check.assertAlmostEqual(stripe_api.tau_g_derivative_at_turn(lambda eta:eta,lambda eta:1.,1.,step=1e-3),1.,places=5)
    with stripe_check.assertRaises(stripe_error):stripe_api.endpoint_regularized_kappa(lambda eta:1.)
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry import compile_dual_stripe_path_length_evaluator
    stripe_shape_contract=stripe_first['contract']
    stripe_path_functions=tuple(compile_dual_stripe_path_length_evaluator(stripe_shape_contract,value)
                                for value in ('set_1','set_2'))
    stripe_basis=stripe_api.identify_manufactured_basis_path_scales(stripe_shape_contract,
        basis_coefficients_c0_to_c5=(.83999,.75160,-7.52535,14.0242,-9.17661,2.08613))
    stripe_count=stripe_api.derive_native_stripe_branch_validation_sample_count(stripe_shape_contract)
    assert stripe_count==176
    stripe_numerics=stripe_api.NativeStripeSpatialReturnNumerics(
        kappa_derivative_step=stripe_shape_contract['dual_stripe_l0']['operating_seed_search']['kappa_derivative_step'],
        branch_validation_sample_count=stripe_count,**stripe_fixture['shape_numerics'])
    stripe_shape=stripe_api.solve_native_stripe_spatial_shape_branch(stripe_path_functions,
        entry_y_mm=stripe_api.project_y_from_theory_drift_mm(stripe_shape_contract,0.),
        drift_length_l_mm=340.,drift_direction_sign=1.,
        reference_relative_action_weight_ratio=stripe_basis.reference_relative_action_weight_ratio,
        geometry_input_identity_source='config/simion_candidate_two_zone.json#dual_stripe.theory_profile',
        numerics=stripe_numerics)
    stripe_check.assertAlmostEqual(stripe_shape.relative_action_weight_ratio,-1.9981408612,places=8)
    stripe_check.assertAlmostEqual(stripe_shape.kappa_1,1.4889697387,places=8)
    assert abs(stripe_shape.kappa_prime)<2e-8
    assert stripe_shape.root_bracket[0]<=stripe_shape.relative_action_weight_ratio<=stripe_shape.root_bracket[1]
    stripe_materialized=stripe_api.materialize_native_stripe_spatial_return_root(stripe_shape,
        source_slow_energy_per_charge_v=5.,
        mirror_reduced_period_mm_per_sqrt_v=586.9264153996922/math.sqrt(4171.767483909065),
        axial_energy_per_charge_v=4171.767483909065)
    stripe_check.assertAlmostEqual(stripe_materialized.stripe_biases_v[0],-25.31809249,places=7)
    stripe_check.assertAlmostEqual(stripe_materialized.stripe_biases_v[1],50.35968780,places=7)
    for stripe_k in (25.5,31.5):
        stripe_period=8.913211876315327
        stripe_energy=stripe_api.exact_k_slow_energy_per_charge_v(stripe_shape,
            mirror_reduced_period_mm_per_sqrt_v=stripe_period,target_period_ratio=stripe_k)
        with localcontext() as stripe_decimal_context:
            stripe_decimal_context.prec=80
            stripe_expected=(Decimal(str(stripe_shape.drift_length_l_mm))*Decimal(str(stripe_shape.kappa_1))/
                             (Decimal(str(stripe_period))*Decimal(str(stripe_k))))**2
        stripe_check.assertAlmostEqual(stripe_energy,float(stripe_expected),places=12)
        stripe_return=stripe_api.materialize_native_stripe_spatial_return_root(stripe_shape,
            source_slow_energy_per_charge_v=stripe_energy,
            mirror_reduced_period_mm_per_sqrt_v=stripe_period,
            axial_energy_per_charge_v=4372.010347796059)
        stripe_check.assertAlmostEqual(stripe_return.continuous_oscillation_count,stripe_k,places=12)
        stripe_check.assertAlmostEqual(stripe_return.turning_pseudopotential_v,stripe_energy,places=12)
    for stripe_bad_k in (0.,-1.,math.nan,math.inf):
        with stripe_check.assertRaises(stripe_error):
            stripe_api.exact_k_slow_energy_per_charge_v(stripe_shape,
                mirror_reduced_period_mm_per_sqrt_v=8.913211876315327,target_period_ratio=stripe_bad_k)
    stripe_target_fixture=stripe_fixture['narrow_target']
    stripe_target=stripe_api.resolve_converging_prism_target(
        stripe_target_fixture['contract'],stripe_target_fixture['resolved'])
    assert stripe_target.keys()==set(stripe_target_fixture['expected_target_keys'])
    assert stripe_target['qualification']=='hard_boundary_clean_phase_engineering_target__not_3d_energy_or_field_qualification'
    assert stripe_target['width_contract']=={'dual_stripe':{'theory_profile':stripe_target_fixture['contract']['dual_stripe']['theory_profile']}}
    assert stripe_target['slow_energy_reference_per_charge_v']==5.374387143093758
    stripe_check.assertAlmostEqual(stripe_target['energy_tolerance_per_charge_v'],.05234301827329357)
    stripe_check.assertAlmostEqual(stripe_api.converging_design_potential_delta_v(
        stripe_target,-27.36410265968425,9.29765627041),.2053296122891533)
    assert stripe_api.converging_design_potential_delta_v(stripe_target,-27.36410265968425,0.)==0.
    print(json.dumps(dict(status='PASS',origins=stripe_origins,response_cases=len(stripe_fixture['responses']),
                         exact_k_cases=2,native_executions=0)))

if __name__=='__main__':main()
""",encoding='utf-8')
stripe_fixture_path=root/('installed-mr-stripe-fixture-'+sys.argv[2]+'.json')
stripe_fixture_path.write_text(json.dumps(fixture['mr_stripe']),encoding='utf-8')
stripe_args=[sys.executable,'-I','-B',str(stripe_script),
             json.dumps([str(value) for value in blocked_source_roots]),str(stripe_fixture_path)]
stripe_child=subprocess.run(stripe_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=90,check=False)
assert stripe_child.returncode==0,stripe_child.stdout+stripe_child.stderr
stripe_report=json.loads(stripe_child.stdout)
assert stripe_report['status']=='PASS' and stripe_report['response_cases']==3 and stripe_report['exact_k_cases']==2
assert stripe_report['native_executions']==0
stripe_selected_path=pathlib.Path(stripe_report['origins']['dual_stripe_l0'])
stripe_original_bytes=stripe_selected_path.read_bytes()
stripe_held=stripe_selected_path.with_name(stripe_selected_path.name+'.missing-test-held')
assert not stripe_held.exists()
stripe_selected_path.rename(stripe_held)
try:
    stripe_missing=subprocess.run(stripe_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert stripe_missing.returncode!=0 and 'ModuleNotFoundError' in stripe_missing.stderr and 'msplatform.components.parallel_mirror_dual_stripe_mr_tof.dual_stripe_l0' in stripe_missing.stderr,stripe_missing.stderr
    missing_rejected.append('mr_stripe_domain')
finally:stripe_held.rename(stripe_selected_path)
assert stripe_selected_path.read_bytes()==stripe_original_bytes
print('INSTALLED_MR_STRIPE_DOMAIN=PASS')
# MR_STRIPE_INSTALLED_END

# MR_OPERATING_PA_INSTALLED_BEGIN
# Actual installed identity/cache constructors; no SIMION execution or cache publication.
pa_operating_script=root/('installed-operating-pa-'+sys.argv[2]+'.py')
pa_operating_script.write_text(r"""import hashlib,importlib,importlib.abc,json,pathlib,sys,sysconfig
from unittest.mock import patch

def main():
    pa_authors=[pathlib.Path(value).resolve() for value in json.loads(sys.argv[1])]
    def pa_deny_reads(event,args):
        if event=='open' and args and isinstance(args[0],str):
            pa_open=pathlib.Path(args[0]).resolve()
            if any(pa_open.is_relative_to(value) for value in pa_authors):
                raise AssertionError('installed operating PA read author source '+str(pa_open))
    sys.addaudithook(pa_deny_reads)
    class PAInstalledOnly(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if any(fullname==value or fullname.startswith(value+'.') for value in ('common','projects','integrations','tools')):
                raise AssertionError('installed operating PA imported forbidden owner '+fullname)
    sys.meta_path.insert(0,PAInstalledOnly())
    pa_fixture=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))
    pa_api=importlib.import_module('msplatform.backends.simion.operating_pa_cache')
    pa_resources=importlib.import_module('msplatform.backends.simion.resources')
    pa_purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve()
    pa_module=pathlib.Path(pa_api.__file__).resolve()
    assert pa_module==pa_purelib/'msplatform/backends/simion/operating_pa_cache.py'
    pa_source=pa_module.read_bytes()
    assert len(pa_source)==pa_fixture['module_source']['bytes']
    assert hashlib.sha256(pa_source).hexdigest()==pa_fixture['module_source']['sha256']
    pa_root=pathlib.Path(sys.argv[3]);pa_root.mkdir(parents=True,exist_ok=False)
    pa_payload=bytes.fromhex(pa_fixture['payload_hex']);pa_base=pa_root/'base.pa';pa_base.write_bytes(pa_payload)
    pa_members=[]
    for pa_old_member in pa_fixture['expected_identity']['members']:
        pa_responses=[]
        for pa_index,pa_old_response in enumerate(pa_old_member['responses']):
            pa_input=pa_root/(pa_old_member['output_name']+'-response-'+str(pa_index)+'.pa')
            pa_input.write_bytes(pa_payload)
            pa_responses.append(dict(coordinate=pa_old_response['coordinate'],path=pa_input,
                basis_normalization_v=pa_old_response['basis_normalization_v'],applied_voltage_delta_v=pa_old_response['applied_voltage_delta_v']))
        pa_members.append(pa_api.operating_pa_member_identity(pa_old_member['output_name'],pa_base,pa_responses,pa_old_member['target_voltage_vector_v']))
    assert pa_members==pa_fixture['expected_identity']['members']
    pa_record=pa_fixture['expected_identity']['members'][0]['base_pa']
    # Already verified receipt metadata must not rehash even these tiny inputs.
    with patch.object(pa_api,'file_sha256',side_effect=AssertionError('unexpected PA rehash')):
        assert pa_api.content_identity_from_verified_record(pa_record,path=pa_base)==pa_record
    pa_explicit=pa_root/'explicit-composer.lua'
    pa_explicit.write_bytes(bytes.fromhex(pa_fixture['composer_hex']))
    pa_explicit_identity=pa_api.linear_basis_operating_pa_group_identity(pa_members,pa_format_version=2020,implementation_path=pa_explicit)
    assert pa_explicit_identity==pa_fixture['expected_identity']
    assert pa_api.canonical_operating_pa_cache_key(pa_explicit_identity)==pa_fixture['expected_cache_key']
    if sys.argv[4]=='missing':
        try:pa_api.linear_basis_operating_pa_group_identity(pa_members,pa_format_version=2020)
        except FileNotFoundError as pa_error:
            assert str(pa_error)=='installed SIMION native resource is missing: compose_standalone_pa.lua'
        else:raise AssertionError('default operating PA planning accepted missing selected Lua')
        print(json.dumps(dict(status='MISSING_REJECTED',explicit_path_works=True,module_origin=str(pa_module))))
        return
    pa_resource=pa_resources.native_resource_path('compose_standalone_pa.lua').resolve()
    assert pa_resource==pa_purelib/'msplatform/backends/simion/resources/compose_standalone_pa.lua'
    pa_body=pa_resource.read_bytes()
    assert pa_body==bytes.fromhex(pa_fixture['composer_hex'])
    assert len(pa_body)==pa_fixture['composer_bytes']
    assert hashlib.sha256(pa_body).hexdigest()==pa_fixture['composer_sha256']
    pa_default_identity=pa_api.linear_basis_operating_pa_group_identity(pa_members,pa_format_version=2020)
    assert pa_default_identity==pa_fixture['expected_identity']==pa_explicit_identity
    assert pa_api.canonical_operating_pa_cache_key(pa_default_identity)==pa_fixture['expected_cache_key']
    assert pa_base.read_bytes()==pa_payload and pa_explicit.read_bytes()==pa_body
    print(json.dumps(dict(status='PASS',module_origin=str(pa_module),resource=str(pa_resource),cache_key=pa_fixture['expected_cache_key'],members=len(pa_members),native_executions=0)))

if __name__=='__main__':main()
""",encoding='utf-8',newline='')
pa_operating_fixture_path=root/('installed-operating-pa-fixture-'+sys.argv[2]+'.json')
pa_operating_fixture_path.write_text(json.dumps(fixture['mr_operating_pa']),encoding='utf-8')
pa_operating_args=[sys.executable,'-I','-B',str(pa_operating_script),
    json.dumps([str(value) for value in blocked_source_roots]),str(pa_operating_fixture_path)]
pa_operating_positive=subprocess.run(pa_operating_args+[str(root/('operating-pa-positive-'+sys.argv[2])),'positive'],
    cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
assert pa_operating_positive.returncode==0,pa_operating_positive.stdout+pa_operating_positive.stderr
pa_operating_report=json.loads(pa_operating_positive.stdout)
assert pa_operating_report['status']=='PASS' and pa_operating_report['members']==2 and pa_operating_report['native_executions']==0
pa_operating_resource=pathlib.Path(pa_operating_report['resource'])
pa_operating_resource_before=pa_operating_resource.read_bytes()
pa_operating_held=pa_operating_resource.with_name(pa_operating_resource.name+'.missing-installed-test-held')
assert not pa_operating_held.exists()
pa_operating_resource.rename(pa_operating_held)
try:
    pa_operating_missing=subprocess.run(pa_operating_args+[str(root/('operating-pa-missing-'+sys.argv[2])),'missing'],
        cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
    assert pa_operating_missing.returncode==0,pa_operating_missing.stdout+pa_operating_missing.stderr
    pa_operating_missing_report=json.loads(pa_operating_missing.stdout)
    assert pa_operating_missing_report['status']=='MISSING_REJECTED' and pa_operating_missing_report['explicit_path_works']
    missing_rejected.append('operating_pa_default_composer')
finally:pa_operating_held.rename(pa_operating_resource)
assert pa_operating_resource.read_bytes()==pa_operating_resource_before
print('INSTALLED_MR_OPERATING_PA=PASS')
# MR_OPERATING_PA_INSTALLED_END

# TOF_ACCEPTANCE_KERNELS_INSTALLED_BEGIN
# Original portable math budgets, not universal full-vector/JSON bitwise goldens.
tof_acceptance_script=root/('installed-tof-acceptance-'+sys.argv[2]+'.py')
tof_acceptance_script.write_text(r"""import hashlib,importlib,importlib.abc,json,pathlib,sys,sysconfig,unittest
from dataclasses import replace
import numpy as np
from scipy.special import ndtri

def main():
    authors=[pathlib.Path(value).resolve() for value in json.loads(sys.argv[1])]
    def deny(event,args):
        if event=='open' and args and isinstance(args[0],str):
            path=pathlib.Path(args[0]).resolve()
            if any(path.is_relative_to(value) for value in authors):
                raise AssertionError('installed TOF acceptance read author source '+str(path))
    sys.addaudithook(deny)
    class PureOnly(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if any(fullname==value or fullname.startswith(value+'.') for value in
                   ('common','projects','integrations','tools','msplatform.backends','msplatform.execution')):
                raise AssertionError('installed TOF acceptance imported forbidden owner '+fullname)
    sys.meta_path.insert(0,PureOnly())
    fixture=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))
    names=('ideal_acceptance_design','ideal_acceptance_density','ideal_acceptance_linear_design','ideal_acceptance_experiment')
    modules={name:importlib.import_module('msplatform.components.single_reflection_oa_tof.'+name) for name in names}
    purelib=pathlib.Path(sysconfig.get_path('purelib')).resolve();origins={}
    for name,module in modules.items():
        path=pathlib.Path(module.__file__).resolve()
        assert path==purelib/'msplatform/components/single_reflection_oa_tof'/(name+'.py')
        content=path.read_bytes()
        assert len(content)==fixture['sources'][name]['bytes']
        assert hashlib.sha256(content).hexdigest()==fixture['sources'][name]['sha256']
        origins[name]=str(path)
    design,density,linear,population=(modules[name] for name in names)
    from msplatform.components.single_reflection_oa_tof.ideal_source_comparison import NumericalSourceSpec,IdealWorkingPoint
    from msplatform.components.single_reflection_oa_tof.three_zone_ideal_theory import ReflectronGeometry,InnerSolution,exact_total_normalized_time_from_state
    from msplatform.components.single_reflection_oa_tof.ideal_acceptance_theory import coefficient_report
    from msplatform.components.orthogonal_accelerator.three_zone_ideal_theory import OuterGeometry,derive_three_zone_state
    check=unittest.TestCase()
    spec=NumericalSourceSpec(**fixture['spec']);outer=OuterGeometry(**fixture['outer'])
    mirror=ReflectronGeometry(**fixture['mirror']);inner=InnerSolution(**fixture['inner']);affine=spec.affine()
    point=IdealWorkingPoint(affine,derive_three_zone_state(affine,outer,inner.eta),mirror,inner,fixture['focus_drift_mm'],None)
    q=design.prepare_source_quadrature(spec,**fixture['quadrature'])
    assert q.weights.size==96
    check.assertAlmostEqual(float(q.weights.sum()),1.,places=14)
    check.assertAlmostEqual(float(q.weights@q.position_offset_mm),0.,places=14)
    check.assertAlmostEqual(float(q.weights@q.position_offset_mm**2),2.8**2/12,places=14)
    check.assertAlmostEqual(float(q.weights@q.residual_m_per_s**2),100.,places=11)
    envelope=design.finite_source_envelope(spec,point,2.8,60.)
    y=np.linspace(-1.4,1.4,1001)[:,None];residual=np.linspace(-60.,60.,201)[None,:]
    velocity=spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*y+residual
    chi=velocity*affine.time_scale_s_sqrt_v_per_mm*1e3
    energy=point.state.repeller_v-point.state.field1_v_per_mm*(spec.center_x_mm+y)+chi**2
    check.assertAlmostEqual(envelope['energy_min_v'],float(energy.min()),places=10)
    check.assertAlmostEqual(envelope['energy_max_v'],float(energy.max()),places=10)
    assert envelope['minimum_repeller_turn_mm']>0
    with check.assertRaisesRegex(design.DesignDomainError,'first acceleration'):
        design.finite_source_envelope(spec,point,3.,60.)
    with check.assertRaisesRegex(design.DesignDomainError,'repeller'):
        design.finite_source_envelope(spec,point,2.8,100000.)
    with check.assertRaisesRegex(ValueError,'must match'):
        design.finite_source_envelope(replace(spec,center_x_mm=1.6),point,2.8,60.)
    offset=np.linspace(-1.4,1.4,17);residual=np.linspace(-50.,50.,17)
    def times(x,r):
        chi=(spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*x+r)*affine.time_scale_s_sqrt_v_per_mm*1e3
        return np.asarray(exact_total_normalized_time_from_state(point.state,mirror,inner,spec.center_x_mm+x,chi,point.focus_drift_mm))*affine.time_scale_s_sqrt_v_per_mm*1e6
    derivative=density.compute_residual_time_derivative(spec,point,offset,residual)
    np.testing.assert_allclose(derivative,(times(offset,residual+.02)-times(offset,residual-.02))/(2*.02),rtol=1e-6,atol=1e-11)
    settings=fixture['density_settings'];result=density.compute_population_density(spec,point,**settings)
    assert len(result.time_grid_us)==len(result.time_density_per_us)==len(result.mass_grid_da)==len(result.mass_density_per_da)==2001
    check.assertLess(abs(result.summary['probability_integration_error']),1e-7)
    check.assertAlmostEqual(float(np.trapezoid(result.mass_density_per_da,result.mass_grid_da)),result.summary['integrated_probability'],places=7)
    assert result.summary['minimum_absolute_residual_derivative_bound_us_per_m_per_s']>0
    assert result.summary['metric_kind']=='population_pushforward_density_not_finite_particle_kde'
    refined=density.compute_population_density(spec,point,**(settings|dict(position_order=128,grid_points=4001)))
    check.assertLess(abs(refined.summary['resolution_mass']/result.summary['resolution_mass']-1),1e-4)
    assert 40190.<refined.summary['resolution_mass']<40200.
    with check.assertRaises(ValueError):density.compute_population_density(spec,point,**(settings|dict(residual_sigma_m_per_s=0.)))
    with check.assertRaisesRegex(ArithmeticError,'root_iterations'):
        density.compute_population_density(spec,point,**(settings|dict(root_iterations=2)))
    blocked=replace(point,inner=replace(inner,stage2_field_v_per_mm=.1))
    with check.assertRaisesRegex(design.DesignDomainError,'backplate'):
        density.compute_population_density(spec,blocked,**settings)
    folded=replace(point,inner=replace(inner,stage2_field_v_per_mm=.01),reflectron=replace(mirror,stage2_length_mm=100000.))
    with check.assertRaisesRegex(design.DesignDomainError,'monotonicity'):
        density.compute_population_density(spec,folded,**settings)
    controls=fixture['linear_controls'];solved=linear.solve_linear_third_order_design(spec,mirror,**controls)
    np.testing.assert_allclose(solved.report['zone_lengths_mm'],[3.25,5.1,11.9],rtol=2e-8)
    np.testing.assert_allclose(solved.report['fields_v_per_mm'],[250/3.25,48.15003152685739,136.1087818397458,9.880402594970798],rtol=2e-8)
    assert solved.report['equation_closed'] and not solved.report['particle_peak_optimization_performed']
    check.assertAlmostEqual(solved.report['fourth_order_coefficient_ns_per_mm4'],.261432,places=5)
    with check.assertRaises(linear.LinearDesignError) as error:
        linear.solve_linear_third_order_design(spec,mirror,**(controls|dict(condition_limit=1.)))
    assert error.exception.reason=='SINGULAR_OR_ILL_CONDITIONED_EQUATION_MATRIX'
    with check.assertRaises(linear.LinearDesignError) as error:
        linear.solve_linear_third_order_design(spec,mirror,**(controls|dict(center_to_grid1_mm=10.,grid2_voltage_fraction=.5,reflectron_stage1_voltage_v=1200.)))
    assert error.exception.reason=='NO_POSITIVE_FIELD_SOLUTION'
    fixed={k:v for k,v in controls.items() if k!='reflectron_stage1_voltage_v'}
    fixed.update(total_accel_length_mm=20.25,length_tolerance_mm=1e-7,root_xtol_v=1e-10)
    roots=linear.find_fixed_length_designs(spec,mirror,**(fixed|dict(stage1_voltage_grid_v=list(np.arange(1690.,1711.,1.)))))
    assert roots
    closest=min(roots,key=lambda value:abs(value.point.inner.stage1_voltage_drop_v-controls['reflectron_stage1_voltage_v']))
    check.assertAlmostEqual(closest.point.inner.stage1_voltage_drop_v,controls['reflectron_stage1_voltage_v'],places=6)
    for root in roots:
        assert abs(sum(root.report['zone_lengths_mm'])-20.25)<1e-7
        assert not root.report['fixed_length_equation']['all_roots_in_continuous_domain_proved']
    multiple=linear.find_fixed_length_designs(replace(spec,center_x_mm=4.5),mirror,**(fixed|dict(field1_v_per_mm=50.,center_to_grid1_mm=4.5,grid2_voltage_fraction=.99,stage1_voltage_grid_v=list(np.arange(1300.,1950.,15.)))))
    assert len(multiple)==2
    np.testing.assert_allclose([v.point.inner.stage1_voltage_drop_v for v in multiple],[1765.1587877126208,1791.7631558603202],atol=1e-6)
    with check.assertRaises(ValueError):
        linear.find_fixed_length_designs(spec,mirror,**(fixed|dict(stage1_voltage_grid_v=[1700.,1700.])))
    # Same existing math composition used by acceptance workflow, without its owner/I/O shell.
    placed=population.source_at_point(spec,solved.point)
    assert placed.center_x_mm==solved.point.design_source.center_extraction_position_mm
    chain_q=design.prepare_source_quadrature(placed,**fixture['moments_controls'])
    chain=population.exact_population_moments(placed,solved.point,chain_q,envelope_sigma=6.)
    assert chain['node_count']==288 and not chain['fwhm_claim']
    # Original independent variance/decomposition budgets use the original fixture point.
    original_q=design.prepare_source_quadrature(spec,**fixture['moments_controls'])
    moments=population.exact_population_moments(spec,point,original_q,envelope_sigma=6.)
    exact_velocity=spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*original_q.position_offset_mm+original_q.residual_m_per_s
    exact_chi=exact_velocity*affine.time_scale_s_sqrt_v_per_mm*1e3
    exact=np.asarray(exact_total_normalized_time_from_state(point.state,mirror,inner,spec.center_x_mm+original_q.position_offset_mm,exact_chi,point.focus_drift_mm))*affine.time_scale_s_sqrt_v_per_mm*1e9
    mean=float(original_q.weights@exact);variance=float(original_q.weights@(exact-mean)**2)
    check.assertAlmostEqual(moments['variance_ns2'],variance,places=12)
    check.assertAlmostEqual(moments['conditional_mean_variance_ns2']+moments['conditional_thickness_variance_ns2'],variance,places=10)
    assert abs(moments['variance_decomposition_residual_ns2'])<1e-10
    assert moments['conditional_mean_variance_ns2']>0 and moments['conditional_thickness_variance_ns2']>0 and not moments['fwhm_claim']
    zero_q=design.prepare_source_quadrature(spec,**fixture['zero_controls'])
    zero=population.exact_population_moments(spec,point,zero_q,envelope_sigma=6.)
    assert zero['conditional_thickness_variance_ns2']<1e-20
    with check.assertRaisesRegex(ValueError,'field regions'):
        population.exact_population_moments(spec,replace(point,inner=replace(inner,stage1_voltage_drop_v=1999.)),zero_q,envelope_sigma=6.)
    midpoint=population.midpoint_population(spec,**fixture['midpoint_controls'])
    np.testing.assert_array_equal(midpoint.particle_id,np.arange(1,25))
    expected_x=np.repeat(np.array([-.75,-.25,.25,.75]),6)
    expected_r=np.tile(ndtri((np.arange(6)+.5)/6)*10.,4)
    np.testing.assert_allclose(midpoint.source_x_mm-spec.center_x_mm,expected_x)
    np.testing.assert_allclose(midpoint.residual_m_per_s,expected_r)
    np.testing.assert_allclose(midpoint.velocity_z_m_per_s,spec.center_velocity_m_per_s+spec.velocity_slope_m_per_s_per_mm*expected_x+expected_r)
    assert not hasattr(midpoint,'weights')
    with check.assertRaises(ValueError):population.midpoint_population(spec,full_width_mm=1.,residual_sigma_m_per_s=10.,position_order=2.5,residual_order=4)
    good=dict(full_cohort_reachable=True,peak_metrics=dict(mass_resolution=25000.))
    assert population.accepted(good,25000.)
    assert not population.accepted(good|dict(full_cohort_reachable=False),25000.)
    for value in (None,float('nan'),float('inf'),24999.):assert not population.accepted(good|dict(peak_metrics=dict(mass_resolution=value)),25000.)
    assert not population.accepted(dict(full_cohort_reachable=True),25000.)
    coefficients=coefficient_report(solved.point,full_width_mm=2.8,residual_sigma_m_per_s=10.,order=6,position_order=12)
    assert coefficients['coefficient_convention']=='Taylor coefficients = derivatives / factorial; a0 is center TOF'
    json.dumps(dict(density=result.summary,linear=solved.report,moments=moments,coefficients=coefficients),allow_nan=False)
    print(json.dumps(dict(status='PASS',origins=origins,source_nodes=96,density_points=2001,multiple_roots=len(multiple),midpoint_ids=midpoint.particle_id.tolist(),native_executions=0)))

if __name__=='__main__':main()
""",encoding='utf-8',newline='')
tof_acceptance_fixture_path=root/('installed-tof-acceptance-fixture-'+sys.argv[2]+'.json')
tof_acceptance_fixture_path.write_text(json.dumps(fixture['tof_acceptance_kernels']),encoding='utf-8')
tof_acceptance_args=[sys.executable,'-I','-B',str(tof_acceptance_script),
    json.dumps([str(value) for value in blocked_source_roots]),str(tof_acceptance_fixture_path)]
tof_acceptance_child=subprocess.run(tof_acceptance_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=90,check=False)
assert tof_acceptance_child.returncode==0,tof_acceptance_child.stdout+tof_acceptance_child.stderr
tof_acceptance_report=json.loads(tof_acceptance_child.stdout)
assert tof_acceptance_report['status']=='PASS' and tof_acceptance_report['native_executions']==0
assert tof_acceptance_report['source_nodes']==96 and tof_acceptance_report['density_points']==2001 and tof_acceptance_report['multiple_roots']==2
assert tof_acceptance_report['midpoint_ids']==list(range(1,25))
for tof_acceptance_name in ('ideal_acceptance_design','ideal_acceptance_density','ideal_acceptance_linear_design','ideal_acceptance_experiment'):
    tof_acceptance_selected=pathlib.Path(tof_acceptance_report['origins'][tof_acceptance_name])
    tof_acceptance_original=tof_acceptance_selected.read_bytes()
    tof_acceptance_held=tof_acceptance_selected.with_name(tof_acceptance_selected.name+'.missing-installed-test-held')
    assert not tof_acceptance_held.exists()
    tof_acceptance_selected.rename(tof_acceptance_held)
    try:
        tof_acceptance_missing=subprocess.run(tof_acceptance_args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
        assert tof_acceptance_missing.returncode!=0 and 'ModuleNotFoundError' in tof_acceptance_missing.stderr and ('msplatform.components.single_reflection_oa_tof.'+tof_acceptance_name) in tof_acceptance_missing.stderr,tof_acceptance_missing.stderr
        missing_rejected.append('tof_acceptance_'+tof_acceptance_name)
    finally:tof_acceptance_held.rename(tof_acceptance_selected)
    assert tof_acceptance_selected.read_bytes()==tof_acceptance_original
print('INSTALLED_TOF_ACCEPTANCE_KERNELS=PASS')
# TOF_ACCEPTANCE_KERNELS_INSTALLED_END

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
                     independent_rf_prepared_model_compile_only=True, independent_rf_missing_witness_rejected=True,
                     geometry_only_native_calls=0, release_independent_geometry=True,
                     prepared_model_compile_only=True, field_plan_only=True, field_execution_performed=False,
                     author_tree_reads_blocked=True,
                     single_reflection_preparation_modes=workflow_modes,
                     installed_single_reflection_collection=True,
                     installed_single_reflection_continuation=True,installed_particle_batching_cli=True,
                     missing_resources_rejected=missing_rejected)))
'''


class InstalledScientificCoreTests(unittest.TestCase):
    @staticmethod
    def tof_acceptance_kernels_probe_fixture():
        """Original explicit fixture inputs; portable assertions keep original budgets."""
        tof_acceptance_input=json.loads('{"spec":{"mass_to_charge_th":100.0,"center_x_mm":1.498375640839315,"center_velocity_m_per_s":-2.9323518410018137,"velocity_slope_m_per_s_per_mm":228.80604377795845,"velocity_quadratic_m_per_s_per_mm2":0.0},"outer":{"zone1_length_mm":3.25,"downstream_length_mm":17.0,"split_fraction":0.3,"zone1_voltage_drop_v":250.0,"nominal_energy_per_charge_v":2000.0},"mirror":{"stage1_length_mm":120.0,"stage2_length_mm":96.1563,"upstream_drift_mm":600.0,"downstream_drift_mm":600.0},"inner":{"stage1_voltage_drop_v":1701.7426470174573,"stage2_field_v_per_mm":9.880402594970798,"eta":-1.0391326394747527},"focus_drift_mm":42.742615461548496,"quadrature":{"full_width_mm":2.8,"residual_sigma_m_per_s":10.0,"position_order":12,"residual_order":8},"density_settings":{"full_width_mm":2.8,"residual_sigma_m_per_s":10.0,"grid_points":2001,"position_order":64,"envelope_sigma":6.0,"root_iterations":48,"residual_tolerance_m_per_s":1e-07,"monotonicity_subdivisions":32},"linear_controls":{"field1_v_per_mm":76.92307692307692,"center_to_grid1_mm":1.751624359160685,"grid2_voltage_fraction":0.868348002459428,"reflectron_stage1_voltage_v":1701.7426470174573,"nominal_energy_per_charge_v":2000.0,"focus_drift_mm":42.742615461548496,"characteristic_half_width_mm":1.4,"condition_limit":1000000000000.0,"coefficient_tolerance_ns":1e-06},"moments_controls":{"full_width_mm":2.2,"residual_sigma_m_per_s":10.0,"position_order":24,"residual_order":12},"zero_controls":{"full_width_mm":1.0,"residual_sigma_m_per_s":0.0,"position_order":8,"residual_order":4},"midpoint_controls":{"full_width_mm":2.0,"residual_sigma_m_per_s":10.0,"position_order":4,"residual_order":6},"envelope_sigma":6.0,"acceptance_threshold":25000.0}')
        tof_acceptance_input['sources']={}
        for tof_acceptance_name in ('ideal_acceptance_design','ideal_acceptance_density',
                                    'ideal_acceptance_linear_design','ideal_acceptance_experiment'):
            tof_acceptance_source=REPO_ROOT/'src/msplatform/components/single_reflection_oa_tof'/(tof_acceptance_name+'.py')
            tof_acceptance_body=tof_acceptance_source.read_bytes()
            tof_acceptance_input['sources'][tof_acceptance_name]=dict(bytes=len(tof_acceptance_body),sha256=hashlib.sha256(tof_acceptance_body).hexdigest())
        return tof_acceptance_input

    @staticmethod
    def operating_pa_probe_fixture():
        """Serialize the retained original path-free schema2 identity/key oracle."""
        pa_oracle=json.loads('{"expected_identity":{"schema_version":2,"role":"simion_standalone_operating_pa_group","members":[{"output_name":"field_v.pa","base_pa":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"responses":[{"coordinate":"whole_point_A_correction_scale","content":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"basis_normalization_v":1.0,"applied_voltage_delta_v":-2.5},{"coordinate":"whole_point_B_scale","content":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"basis_normalization_v":1.0,"applied_voltage_delta_v":0.5},{"coordinate":"whole_point_C_scale","content":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"basis_normalization_v":1.0,"applied_voltage_delta_v":2.0}],"target_voltage_vector_v":[0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,-26.95,-26.95,54.2,54.2,0.0,190.0,-190.0,0.0,0.0,0.0]},{"output_name":"window-001_v.pa","base_pa":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"responses":[{"coordinate":"whole_point_A_correction_scale","content":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"basis_normalization_v":1.0,"applied_voltage_delta_v":-2.5},{"coordinate":"whole_point_B_scale","content":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"basis_normalization_v":1.0,"applied_voltage_delta_v":0.5},{"coordinate":"whole_point_C_scale","content":{"bytes":8,"sha256":"93BFCC184130DE6DCC8480D17A473BCFE3042546D5BE50B0B8EEB71A3F94DBA7"},"basis_normalization_v":1.0,"applied_voltage_delta_v":2.0}],"target_voltage_vector_v":[0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,-26.95,-26.95,54.2,54.2,0.0,190.0,-190.0,0.0,0.0,0.0]}],"synthesis":{"algorithm_id":"standalone_linear_response_composition","algorithm_format_version":2,"implementation_sha256":"7EB04DF1A3A0F24023AAB9392D59C1F6BDC5B897D6FD73F3AE1D42E478300D00","pa_format_version":2020}},"expected_cache_key":"C0038832AB032E3A27C580CFD10FFFDC125CC1B8A09A336853D93BB870F6B792","payload_hex":"7363616c61722d56","composer_bytes":5579,"composer_sha256":"7eb04df1a3a0f24023aab9392d59c1f6bdc5b897d6fd73f3ae1d42e478300d00"}')
        pa_module=REPO_ROOT/'src/msplatform/backends/simion/operating_pa_cache.py'
        pa_module_bytes=pa_module.read_bytes()
        pa_composer=REPO_ROOT/'src/msplatform/backends/simion/resources/compose_standalone_pa.lua'
        pa_composer_bytes=pa_composer.read_bytes()
        assert len(pa_composer_bytes)==pa_oracle['composer_bytes']
        assert hashlib.sha256(pa_composer_bytes).hexdigest()==pa_oracle['composer_sha256']
        pa_oracle['composer_hex']=pa_composer_bytes.hex()
        pa_oracle['module_source']=dict(bytes=len(pa_module_bytes),sha256=hashlib.sha256(pa_module_bytes).hexdigest())
        return pa_oracle

    @staticmethod
    def stripe_probe_fixture():
        """Serialize explicit original Stripe cases; clients never read author inputs."""
        import copy
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import pure_geometry_inputs
        stripe_contract=load_contract(REPO_ROOT/'projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json')
        stripe_converging=copy.deepcopy(stripe_contract)
        stripe_converging['mirror']['convergence_transform']={'angle_deg':.025688744787259285,'pivot_y_mm':0.}
        stripe_converging['downstream_fixed_grid_workpoint_profile']['active_stripe_axes']=['stripe_1_voltage_v']
        stripe_converging['prism_transport']['handoff_target']={
            'mode':'converging_clean_phase_energy','axial_energy_per_charge_v':4371.97610111757,
            'mirror_axial_width_w_mm':590.519039985,'slow_energy_reference_per_charge_v':5.374387143093758,
            'total_energy_reference_per_charge_v':4377.32967207278,'clean_reference_slow_energy_per_charge_v':5.169057530804604}
        stripe_converging['downstream_fixed_grid_workpoint_profile']['automatic_iteration']['acceptance_tolerances']['P1_P2_P2_shield_low_field_angle_degrees']=.01
        stripe_responses=[dict(contract=copy.deepcopy(stripe_case),pure_geometry_inputs=pure_geometry_inputs(stripe_case),
                               axial_energy_per_charge_v=stripe_energy)
                          for stripe_case,stripe_energy in ((stripe_contract,None),(stripe_contract,4050.),(stripe_converging,None))]
        stripe_sources={}
        for stripe_name,stripe_relative in (
            ('dual_stripe_l0','components/parallel_mirror_dual_stripe_mr_tof/dual_stripe_l0.py'),
            ('mr_design','workflows/mr_design.py')):
            stripe_content=(REPO_ROOT/'src/msplatform'/stripe_relative).read_bytes()
            stripe_sources[stripe_name]=dict(bytes=len(stripe_content),sha256=hashlib.sha256(stripe_content).hexdigest())
        return dict(sources=stripe_sources,responses=stripe_responses,
                    response_metadata={'model': 'dual_stripe_nominal_response_l0',
 'geometry_status': 'positive B-spline-evaluated widths; central-ground opening and '
                    'three-dimensional clearance remain gated',
 'not_evaluated': ['target_psi_g_fit',
                   'voltage_inverse_solution',
                   'mirror_period',
                   'return_time',
                   'oscillation_count',
                   'time_platform'],
 'keys': ['model',
          'energy_per_charge_v',
          'biases_v',
          'h_factors',
          'response_matrix',
          'response_matrix_determinant',
          'response_matrix_condition_number_2',
          'physical_width_bounds_mm',
          'theory_cad_component_mapping',
          'geometry_status',
          'not_evaluated']},
                    shape_numerics=dict(initial_ratio_half_width=.004,search_expansion_factor=1.5,
                        maximum_search_expansions=12,root_absolute_tolerance=1e-11,
                        root_relative_tolerance=1e-11,maximum_root_iterations=80),
                    narrow_target=dict(contract=stripe_converging,
                        resolved=dict(mirror_convergence_transform=dict(angle_deg=.025688744787259285),
                                      metadata=dict(ion_foil_slot_bridge_from_min_y_mm=2.,ion_foil_slot_bridge_from_max_y_mm=5.)),
                        expected_target_keys=['mode', 'axial_energy_per_charge_v', 'mirror_axial_width_w_mm', 'slow_energy_reference_per_charge_v', 'total_energy_reference_per_charge_v', 'clean_reference_slow_energy_per_charge_v', 'angle_tolerance_degrees', 'single_mirror_angle_degrees', 'function_y_zero_project_y_mm', 'width_contract', 'energy_tolerance_per_charge_v', 'clean_y_interval_mm', 'qualification']))

    @staticmethod
    def prism_phase_probe_fixture():
        """Transport explicit original MR reference inputs, never author paths to clients."""
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract as prism_load_contract
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prism_analytic import PrismAnalyticTest as prism_reference
        prism_contract = prism_load_contract(REPO_ROOT/'projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json')
        prism_contract['accelerator']['focus_y_anchor']['project_y_mm'] = -45.0
        prism_trace, prism_direction, prism_beta = prism_reference._right_angle_trace()
        assert prism_trace.status == 'transmitted'
        prism_sources = {}
        for prism_name in ('prism_l0', 'prism_analytic', 'drift_phase_contract'):
            prism_content = (REPO_ROOT/'src/msplatform/components/parallel_mirror_dual_stripe_mr_tof'/(prism_name+'.py')).read_bytes()
            prism_sources[prism_name] = dict(bytes=len(prism_content),sha256=hashlib.sha256(prism_content).hexdigest())
        return dict(contract=prism_contract,sources=prism_sources,
                    analytic=dict(triangle=[[0.,0.],[1.,0.],[0.,1.]],
                        direction=list(prism_direction),
                        origin=[.2-prism_direction[0],-prism_direction[1]],
                        energy=4000.,alpha=4.,beta=prism_beta),
                    phases=[dict(nominal=dict(target_drift_period_ratio=prism_ratio,
                        fast_path_symmetry='opposite_mirror_turn__z_reflected_nonoverlapping'))
                        for prism_ratio in (25.5,31.5)])

    @staticmethod
    def scalar_adapter_probe_fixture():
        """Pin an explicit standalone Lua software provider and selected source bytes."""
        scalar_selected = os.environ.get('SIMION_LUA_EXE')
        if not scalar_selected:
            scalar_selected = shutil.which('lua') or shutil.which('lua5.1')
        if not scalar_selected:
            raise RuntimeError('scalar adapter software preflight requires SIMION_LUA_EXE or PATH lua/lua5.1')
        scalar_executable = Path(scalar_selected).resolve(strict=True)
        if not scalar_executable.is_file():
            raise RuntimeError('selected scalar Lua provider is not a file')
        scalar_provider_bytes = scalar_executable.read_bytes()
        scalar_version = subprocess.run([str(scalar_executable), '-v'], cwd=REPO_ROOT,
                                        capture_output=True, text=True, encoding='utf-8',
                                        errors='replace', timeout=10, check=True)
        scalar_provider_record = dict(path=str(scalar_executable), exists=True,
                                      bytes=len(scalar_provider_bytes),
                                      sha256=hashlib.sha256(scalar_provider_bytes).hexdigest())
        scalar_source_records = {}
        for scalar_relative in ('backends/comsol/static_field_binding.py', 'backends/simion/resources.py',
                                'backends/simion/resources/scalar_field_adapter.lua'):
            scalar_source_bytes = (REPO_ROOT/'src/msplatform'/scalar_relative).read_bytes()
            scalar_source_records[scalar_relative] = dict(bytes=len(scalar_source_bytes),
                sha256=hashlib.sha256(scalar_source_bytes).hexdigest())
        return dict(executable=scalar_provider_record,
                    version_stdout=scalar_version.stdout, version_stderr=scalar_version.stderr,
                    sources=scalar_source_records)

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

    def test_probe_author_guard_allows_hosted_stdlib_lazy_import_but_denies_checkout(self) -> None:
        import ast
        from types import SimpleNamespace
        from unittest.mock import patch

        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "test_wheel_and_sdist_install_and_compute_outside_worktree")
        keyword = next(node for node in ast.walk(method) if isinstance(node, ast.keyword)
                       and node.arg == "author_source_roots")
        global_site = Path(sys.base_prefix) / "Lib/site-packages"
        marker = global_site / "msplatform/__init__.py"
        original_is_file = Path.is_file
        # Model the hosted runner's installed core without writing its Python installation.
        with patch.object(Path, "is_file", lambda path: path == marker or original_is_file(path)):
            roots = eval(compile(ast.Expression(keyword.value), "<actual-author-roots>", "eval"),
                         dict(REPO_ROOT=REPO_ROOT, Path=Path,
                              sys=SimpleNamespace(path=[str(REPO_ROOT / "src"), str(global_site)])))
        statements = ast.parse(INSTALLED_PROBE).body
        start = next(index for index, node in enumerate(statements) if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "blocked_source_roots" for target in node.targets))
        end = next(index for index in range(start, len(statements)) if isinstance(statements[index], ast.Expr)
                   and isinstance(statements[index].value, ast.Call)
                   and isinstance(statements[index].value.func, ast.Attribute)
                   and statements[index].value.func.attr == "addaudithook")
        guard = ast.unparse(ast.Module(body=statements[start:end + 1], type_ignores=[]))
        program = "import json, pathlib, os, sys\nfixture=json.loads(sys.argv[1]);root=pathlib.Path.cwd()\n" + guard + "\n" + r'''
from email import message_from_string
assert message_from_string("Subject: lazy stdlib\n\nbody")["Subject"] == "lazy stdlib"
try:
    pathlib.Path(fixture["repo_root"], "README.md").read_bytes()
except AssertionError as failure:
    assert "installed action accessed an author tree" in str(failure)
else:
    raise AssertionError("actual author checkout was readable")
print("HOSTED_STDLIB_ALLOWED_AUTHOR_DENIED")
'''
        with tempfile.TemporaryDirectory() as directory:
            fixture = dict(repo_root=str(REPO_ROOT), author_source_roots=roots)
            result = subprocess.run([sys.executable, "-I", "-c", program, json.dumps(fixture)],
                cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("HOSTED_STDLIB_ALLOWED_AUTHOR_DENIED", result.stdout)

    def test_installed_rf_prehook_runtime_failure_preserves_primary_diagnostic(self) -> None:
        """Synthetic diagnostic branches; no owner, process or OS-cause claim."""
        import ast
        from types import SimpleNamespace
        from unittest.mock import patch

        tree = ast.parse(INSTALLED_PROBE)
        case = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                    and isinstance(node.target, ast.Name) and node.target.id == 'rf_l1_case')
        initialization = next(node for node in case.body if isinstance(node, ast.Assign)
                              and any(isinstance(target, ast.Name) and target.id == 'rf_l1_error' for target in node.targets))
        invocation = next(node for node in case.body if isinstance(node, ast.Try)
                          and any(isinstance(handler.type, ast.Name) and handler.type.id == 'RuntimeError'
                                  for handler in node.handlers))
        lookup = next(node for node in case.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'session' for target in node.targets))
        # Execute the actual invocation/handler and following mandatory lookup,
        # not a copied approximation of the exception-handling policy.
        code = compile(ast.Module(body=[initialization, invocation, lookup], type_ignores=[]),
                       '<actual-installed-rf-handler>', 'exec')
        primary = RuntimeError('CONTROLLED_PREHOOK_DIAGNOSTIC')
        primary.add_note('Synthetic diagnostic sentinel; not a measured OS failure')
        def fail_before_hook(*args, **kwargs):
            raise primary
        selected = SimpleNamespace(_invoke_frozen_stage=object(), run=fail_before_hook)
        seen = {}
        namespace = dict(rf_l1_patch=patch, rf_l1=selected, rf_l1_seen=seen,
            rf_l1_observe=lambda *args, **kwargs: None,
            rf_l1_kernel=SimpleNamespace(simulate_mass=object()), rf_l1_context=object(),
            rf_l1_paths={key: Path(key+'.json') for key in ('baseline','resolved','mode','source')},
            rf_l1_id='controlled-handler-only')
        with self.assertRaises(RuntimeError) as caught:
            exec(code, namespace)
        self.assertIs(caught.exception, primary)
        self.assertEqual(primary.__notes__, ['Synthetic diagnostic sentinel; not a measured OS failure'])
        self.assertNotIn('session', seen)
        # A missing hook without a primary RuntimeError is still a real failure.
        selected.run = lambda *args, **kwargs: None
        with self.assertRaisesRegex(KeyError, 'session'):
            exec(code, namespace)
        # The existing post-hook capture and positive control flow stay intact.
        marker = object()
        seen['session'] = marker
        selected.run = fail_before_hook
        exec(code, namespace)
        self.assertIs(namespace['rf_l1_error'], primary)
        self.assertIs(namespace['session'], marker)
        selected.run = lambda *args, **kwargs: None
        exec(code, namespace)
        self.assertIsNone(namespace['rf_l1_error'])
        self.assertIs(namespace['session'], marker)

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

        analysis_index = next(index for index, node in enumerate(statements)
                              if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                                  and target.id == "analysis_round" for target in node.targets))
        analysis_loop = next(node for node in statements if isinstance(node, ast.For)
                             and isinstance(node.iter, ast.Call)
                             and ast.unparse(node.iter) == "enumerate(fixture['recorded_frontend_analysis'])")
        paths = ast.Module(body=[statements[analysis_index],
            ast.For(target=analysis_loop.target, iter=analysis_loop.iter,
                    body=analysis_loop.body[:2], orelse=[])], type_ignores=[])
        code = compile(ast.fix_missing_locations(paths), "<actual-analyzer-probe-paths>", "exec")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def namespace(round_id):
                return dict(root=root, sys=SimpleNamespace(argv=['probe', 'fixture.json', round_id]),
                            pathlib=__import__('pathlib'), os=os,
                            fixture={'recorded_frontend_analysis': [{'files': {}, 'kind': 'local'}]})
            locations = []
            for round_id in ('0', '1'):
                selected = namespace(round_id)
                exec(code, selected)
                locations.append(selected['analysis_run'])
            self.assertNotEqual(*locations)
            self.assertEqual(len(list(root.iterdir())), 2)
            with self.assertRaises(FileExistsError):
                exec(code, namespace('0'))

    def test_actual_installed_comparison_probe_uses_manifest_bound_fixture(self) -> None:
        import ast
        import copy
        import importlib
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends import simion as simion_api
        from msplatform.io.manifest_records import file_record
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
                publish_terminal_state=publish_terminal_state,json=json,copy=copy,pathlib=__import__('pathlib'),patch=patch,
                simion_api=simion_api)
            # The real probe initializes stats in its earlier peak-metrics checks.
            # Preserve that prerequisite before guarding comparison execution.
            importlib.import_module('scipy.stats')
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

    def single_reflection_continuation_probe_fixture(self) -> list[dict]:
        from integrations.tests.test_single_reflection_continuation import SingleReflectionContinuationTests
        from msplatform.workflows.single_reflection_flight.continuation import prepare_phase_continuation
        cases=[]
        for _ in range(2):
            case=SingleReflectionContinuationTests()
            case.setUp()
            self.addCleanup(case.doCleanups)
            current=case._current_workbench()
            # Freeze the fixture's actual projection dependency before publishing
            # its predecessor; no installed action may read the author package.
            projection=Path(current['batches'][0]['program_path_projection_record']['path'])
            frozen_projection=case.workbench_fixture.root/'frozen-native-run-path.lua'
            shutil.copyfile(projection,frozen_projection)
            assert frozen_projection.read_bytes()==projection.read_bytes()
            def bind_projection(value):
                if isinstance(value,dict):
                    if value.get('path')==str(projection) and 'sha256' in value:
                        value['path']=str(frozen_projection)
                    for child in value.values():bind_projection(child)
                elif isinstance(value,list):
                    for child in value:bind_projection(child)
            bind_projection(current)
            case._parent(current)
            case.preparation['default_replay_requested']=False
            request_path=Path(case.preparation['input_records']['request']['path'])
            request=json.loads(request_path.read_text(encoding='utf-8'))
            request['verify_saved_workbench_replay']=False
            request_path.write_text(json.dumps(request),encoding='utf-8')
            from msplatform.io.manifest_records import file_record
            case.preparation['input_records']['request']=file_record(request_path)
            expected=prepare_phase_continuation(case.preparation,current,case.run,'baseline')
            # Remove only this fixture's just-created consumer planning outputs;
            # the installed call must construct its own plan from the bound parent.
            generated=case.run/'inputs/continuation'
            shutil.rmtree(generated)
            cases.append(dict(preparation=case.preparation,workbench=current,run=str(case.run),expected=expected))
        return cases

    def prepared_joint_diagnostics_probe_fixture(self) -> list[dict]:
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prepared_joint_diagnostics import PreparedJointDiagnosticsTests
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import merge_measured_event_logs
        result = []
        for structured in (False, True):
            case = PreparedJointDiagnosticsTests()
            case.setUp()
            self.addCleanup(case.doCleanups)
            fields, binding = case._prepare_sealed_native_binding()
            pairs = case._prepare_completed_source_batches(structured=structured)
            merge = merge_measured_event_logs(batches=pairs, preparation_path=case.preparation,
                output_path=case.log, receipt_path=case.root/'batch_log_merge_receipt.json')
            for path in fields.rglob('*'):
                if path.is_file() and path.name.endswith(('.pa','.pa-surf')):
                    path.rename(path.with_name(path.name+'.unavailable'))
            result.append(dict(kind='declared_csv' if structured else 'legacy_log',
                preparation=str(case.preparation), log=str(case.log), binding=str(binding),
                trajectory=merge.get('scientific_event_output',{}).get('trajectory_path'),
                input_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in case.root.rglob('*') if path.is_file()}))
        return result

    def single_reflection_collection_probe_fixture(self) -> dict:
        from integrations.tests.test_single_reflection_collection import SingleReflectionCollectionTests
        case = SingleReflectionCollectionTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        from msplatform.workflows.single_reflection_flight.collect import collect_log
        preparation = case.run/'collection-preparation.json'
        workbench = case.run/'collection-workbench.json'
        preparation.write_text(json.dumps(case.preparation),encoding='utf-8')
        workbench.write_text(json.dumps(case.workbench),encoding='utf-8')
        return dict(preparation=str(preparation),workbench=str(workbench),run=str(case.run),log=str(case.log),
                    expected=collect_log(case.preparation,case.workbench,case.run,case.log))

    def prepared_joint_admission_probe_fixture(self, root: Path) -> list[dict]:
        from integrations.tests.test_prepared_joint_execute import analysis_source_fixture
        result = []
        for scenario in ("success", "failed_analysis", "wrong_owner", "incomplete_native"):
            workspace = root / ("sealed-analysis-source-" + scenario)
            workspace.mkdir()
            source, contract = analysis_source_fixture(workspace,
                status="success" if scenario == "success" else "failed",
                owner="parallel_mirror_dual_stripe_mr_tof" if scenario == "wrong_owner" else "instrument_assembly",
                complete=scenario != "incomplete_native")
            result.append(dict(scenario=scenario, source=str(source), contract=str(contract),
                error="instrument_assembly/prepared_joint" if scenario == "wrong_owner" else "complete original-ID"))
        return result

    def gas_field_probe_fixture(self, root: Path) -> dict:
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import (
            PROJECT_ROOT, _write_fixture,
        )
        from msplatform.io.manifest_records import file_record
        producer = root / "published-gas-field"
        producer.mkdir()
        csv_path, metadata = _write_fixture(producer)
        inputs = {}
        for name in ("gas_flow_science", "comsol_solver_numerics", "resolved_geometry"):
            target = producer / (name + ".json")
            target.write_bytes((PROJECT_ROOT / "config" / target.name).read_bytes())
            inputs[name] = file_record(target)
        manifest = producer / "run_manifest.json"
        manifest.write_text(json.dumps(dict(schema_version=2, role="simulation_run_manifest",
            project="dual_cone_tandem_quadrupole_ion_interface", mode="axisymmetric_gas_flow_screening",
            run_id="installed-gas-reader", status="success", inputs=inputs,
            outputs=[file_record(csv_path), file_record(metadata)])), encoding="utf-8")
        return dict(manifest=file_record(manifest), product_id="gas_field")

    def multipole_ip_probe_fixture(self) -> str:
        from integrations.tests.test_multipole_ip_prepare import MultipoleIPPreparationTests, write_json
        fixture = MultipoleIPPreparationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        write_json(fixture.request_path, fixture.request)
        return str(fixture.request_path)

    def single_reflection_workflow_probe_fixture(self, root: Path) -> list[dict]:
        from msplatform.io.manifest_records import file_record
        from integrations.tests.test_single_reflection_preparation import (
            fixture, release_fixture, scientific_preparation_fixture, RecordedPrePulsePreparationTests, write_json,
        )
        from msplatform.workflows.single_reflection_flight.prepare import prepare
        cases = []
        for kind in ('recorded_birth', 'release_spec', 'recorded_pre_pulse_state'):
            case_root = root / ('workflow-input-' + kind)
            case_root.mkdir()
            if kind == 'recorded_birth':
                request_path, baseline_run, request = scientific_preparation_fixture(case_root, recorded_birth=True)
            elif kind == 'release_spec':
                request_path, baseline_run, request, _ = release_fixture(case_root)
            else:
                _, _, _, collection, decision, manifest = RecordedPrePulsePreparationTests()._winner(case_root)
                consumer = case_root / 'consumer'
                consumer.mkdir()
                request_path, baseline_run, request = fixture(consumer)
                request['source'] = dict(kind=kind, instance_id='oatof', frame_id='oatof_global',
                    pre_pulse_collection=file_record(collection), pulse_decision=file_record(decision),
                    producer_manifest=file_record(manifest),
                    **{name:request['source'][name] for name in ('clock_authority','instrument_epoch')})
                write_json(request_path, request)
            receipt = prepare(request_path, baseline_run)
            with (baseline_run/'inputs/projected_source.csv').open(encoding='utf-8',newline='') as stream:
                import csv
                rows = list(csv.DictReader(stream))
            provenance = json.loads((baseline_run/'inputs/source_provenance.json').read_text(encoding='utf-8'))
            cases.append(dict(kind=kind, request=str(request_path), version=request['schema_version'],
                particle_count=receipt['particle_count'], particle_ids=[row['particle_id'] for row in rows],
                projected_sha256=hashlib.sha256((baseline_run/'inputs/projected_source.csv').read_bytes()).hexdigest(),
                gem_sha256={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (baseline_run/'inputs').glob('*.gem')},
                provenance={name:provenance[name] for name in ('source_kind','population_policy','clock_epoch_id',
                    'state_time_semantics','original_mother_particle_count','continued_particle_ids','original_birth_times_us') if name in provenance}))
        return cases

    def tof_kernel_probe_fixture(self) -> dict:
        """Original high-contrast kernel fixture; no experiment/default selection."""
        from dataclasses import asdict
        from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_three_zone_ideal_theory import ThreeZoneIdealTheoryTests
        case = ThreeZoneIdealTheoryTests()
        from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_ideal_acceptance_theory import IdealAcceptanceTheoryTests
        acceptance_case = IdealAcceptanceTheoryTests()
        acceptance_case.setUp()
        acceptance_golden = json.loads(r'''{
  "particle_id": [
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31
  ],
  "source_x_mm": [
    1.491011830127508,
    1.2669434220431108,
    1.2182668895056232,
    1.8530727505469107,
    1.841738554735515,
    1.0775815382893024,
    1.4512842314682444,
    1.1143791373115217,
    1.7706171204943741,
    1.804406854987063,
    1.940569369756127,
    1.149065246161113,
    1.6749328054894028,
    1.0798631542706731,
    1.8701490883364094,
    1.3431770302289623,
    1.3970714543843965,
    1.822867830091762,
    1.0466796149819553,
    1.717340881736754,
    1.9341789219947632,
    1.1595050026054863,
    1.1660295259740423,
    1.9558459192958908,
    1.2808285989899604,
    1.4188471564409642,
    1.1704322883527076,
    1.245837018672979,
    1.1178248608526817,
    1.601316487934303,
    1.4480697933597515
  ],
  "velocity_z_m_per_s": [
    -6.16145470059825,
    -49.36266593172516,
    -72.57911769486189,
    75.37175544905125,
    77.40862438703552,
    -102.99572974121668,
    -11.749973154996274,
    -93.55520288866278,
    57.99352787267852,
    63.48622631570759,
    91.77266784868765,
    -87.19296877852565,
    41.167326432122984,
    -99.47919252682324,
    77.47274265245042,
    -39.2243241179563,
    -21.75585482428366,
    78.37031827689515,
    -106.75012530149687,
    48.64232296419626,
    97.10090209328095,
    -81.5225840621541,
    -83.23090433824093,
    101.77026387974392,
    -51.49693123632757,
    -14.520711155342703,
    -79.26991694199317,
    -59.45171919328155,
    -87.34992543018343,
    20.175197898430874,
    -19.7790357555022
  ],
  "residual_m_per_s": [
    -1.5442184634980922,
    6.522776294790983,
    -5.556190633614127,
    -2.8527351216184074,
    1.7774663193760207,
    -3.7831440506499714,
    1.9571777601284792,
    -2.762130250897697,
    -1.3646161984512999,
    -3.6032132250020608,
    -6.471578007189357,
    -4.33628748068722,
    3.702331928884546,
    -0.788654362374493,
    -4.658917210050455,
    -0.7815921833638326,
    4.355507137612695,
    7.056896058195955,
    -0.46699279384616044,
    1.474104310567459,
    0.31882930765135914,
    -1.0545821343581268,
    -4.255752789941122,
    0.03065116109560999,
    1.2114985858230038,
    6.608238568502851,
    -1.302144035250227,
    1.2629956867362524,
    2.654744836176227,
    -0.44593822752325374,
    -5.336401973804088
  ],
  "tof_us": [
    31.331344313206564,
    31.331236289033466,
    31.331399714317318,
    31.331367210044384,
    31.331304131556408,
    31.33138087436961,
    31.3312971395956,
    31.33136524857439,
    31.33134361710505,
    31.33137487832689,
    31.331424279687894,
    31.33138508374844,
    31.331273902758127,
    31.33134041027108,
    31.331392719665118,
    31.331334174966482,
    31.331264853495163,
    31.331232006496176,
    31.331338166823844,
    31.33130433682686,
    31.331331932633514,
    31.33134053366316,
    31.331383452616794,
    31.3313387980809,
    31.33130770031296,
    31.331234485856616,
    31.33134353707873,
    31.331307407240107,
    31.331292131786007,
    31.331329547553032,
    31.331395405558062
  ],
  "classification": [
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival",
    "detector_arrival"
  ],
  "mother_count": 31,
  "quadratic": [
    1.7320508075688772,
    0.5773502691896257,
    -0.06735753140545633,
    0.02245251046848544,
    -0.008793899933490132,
    0.003804453162715588,
    -0.0017556615824662917,
    0.0008471664829544272,
    -0.0004223055619656004
  ],
  "coefficients": [
    31331.323507445926,
    5.369737624127455e-14,
    -1.3769006289216122e-11,
    -3.3638518420215303e-12,
    0.261432398030247,
    0.16420282702811112,
    0.08216715832552902
  ],
  "residual_sensitivity": [
    -0.013465616932997781,
    -0.013473428768299264,
    -0.013491956735793594
  ],
  "variance": 5.5515904755484415,
  "report": {
    "coefficients_ns_per_mm_power": [
      31331.323507445926,
      5.369737624127455e-14,
      -1.3769006289216122e-11,
      -3.3638518420215303e-12,
      0.261432398030247,
      0.16420282702811112,
      0.08216715832552902
    ],
    "coefficient_convention": "Taylor coefficients = derivatives / factorial; a0 is center TOF",
    "full_width_mm": 2.2,
    "residual_sigma_m_per_s": 10.0,
    "polynomial_conditional_mean_variance_ns2": 0.024919927886677094,
    "linearized_conditional_thickness_variance_ns2": 0.018157307677396026,
    "linearized_total_sigma_ns": 0.207550561464124,
    "residual_sensitivity_center_ns_per_m_per_s": -0.013473428768299264,
    "scope": "local series and first-order residual projection; exact finite-width propagation must verify remainder"
  }
}''' )
        campaign = json.loads((REPO_ROOT / "projects/single_reflection_oa_tof_mass_analyzer/config/experiments/three_zone_solver_free_funnel_v2.json").read_text(encoding="utf-8"))
        return dict(source=asdict(case.source()), outer=asdict(case.outer()),
            reflectron=asdict(case.reflectron()), inner=asdict(case.candidate()),
            physics_limits=asdict(case.permissive_ideal_limits()),
            two_zone_seeds=campaign["root_policy"]["two_zone_seeds"],
            two_zone_bounds=campaign["root_policy"]["scaled_bounds"],
            # Root-set coordinates from the exact pre-move574 arithmetic proof.
            expected_coordinates={"2": [[0.7275719512760808, 0.40842784458225045]],
                                  "3": [[0.8812865043851961, 0.4992181711713726, -0.9622913764817468]]},
            expected_accepted={"2": 0, "3": 1},
            source_acceptance=dict(spec=asdict(acceptance_case.spec),
                point=asdict(acceptance_case.point), golden=acceptance_golden))

    def rf_l1_managed_probe_fixture(self, root: Path) -> dict:
        from msplatform.workflows.rf_mass_filter import finite_length
        project = REPO_ROOT / "projects/rf_multipole_ion_optics"
        selected = dict(baseline=project / "variants/quadrupole/config/baseline.json",
                        resolved=project / "variants/quadrupole/config/resolved_design_mass_filter.json",
                        mode=project / "config/modes/quadrupole_mass_filter_reference.json",
                        source=project / "variants/quadrupole/config/official_particle_source.json")
        records = {}
        for name, path in selected.items():
            raw = path.read_bytes()
            records[name] = dict(bytes_hex=raw.hex(), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        values = {name: json.loads(bytes.fromhex(row["bytes_hex"])) for name, row in records.items()}
        rows = finite_length.scan_response(values["baseline"], values["resolved"], values["mode"], values["source"])
        assert len(rows) == 29 and all(row["particles"] == 100 for row in rows)
        expected = root / "rf-l1-original-science.csv"
        finite_length.write_response_csv(expected, rows)
        derived = finite_length.validate_l1_contract(values["baseline"], values["mode"], values["source"])
        host = json.loads(os.environ["MASS_SPECTROMETRY_HOST_CONTEXT_JSON"])
        policy = Path(host["policy_path"]).read_bytes()
        return dict(inputs=records, expected_csv_hex=expected.read_bytes().hex(),
                    expected_metrics=finite_length.evaluate_response(rows, derived, values["mode"]),
                    host_policy_hex=policy.hex(), host_policy_sha256=hashlib.sha256(policy).hexdigest(),
                    oracle_module_sha256=hashlib.sha256(Path(finite_length.__file__).read_bytes()).hexdigest(),
                    host_state_path=os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"],
                    powershell=shutil.which("pwsh"))

    def tof_budget_probe_fixture(self) -> dict:
        # Original planning tests and the three pre-move documented CLI oracles.
        return dict(api=dict(flight_time_s=2.0, reference_resolution=10.0,
                             minimum_resolution=8.0, mass_bias_limit_ppm=210000.0),
                    expected=dict(reference_fwhm_s=0.1, maximum_fwhm_s=0.125,
                                  remaining_fwhm_margin_s=0.025, maximum_bias_s=0.2),
                    cli=[
                        ["--flight-time-us", "100", "--reference-resolution", "100000",
                         "--max-resolution-loss-pct", "1", "--mass-bias-ppm", "1", "--format", "markdown"],
                        ["--flight-time-us", "71.35279859675002", "--reference-resolution", "37054.74023592537",
                         "--max-resolution-loss-pct", "1", "--mass-bias-ppm", "1", "--format", "markdown"],
                        ["--flight-time-us", "100", "--reference-resolution", "100000",
                         "--minimum-resolution", "200000"]])

    def mr_backend_geometry_probe_fixture(self) -> dict:
        import copy
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry import (
            resolve_geometry, build_two_zone_accelerator_requirements)
        from msplatform.components.orthogonal_accelerator.two_zone_geometry import validate_geometry_profile
        from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract
        contract = load_contract(REPO_ROOT / "projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json")
        provider_path = REPO_ROOT / "projects/orthogonal_accelerator/config/component_contract.json"
        provider_bytes = provider_path.read_bytes()
        profile_id = "closed_two_zone_compact_mr_axial_r3_gap1_4mm"
        profile = dict(validate_geometry_profile(json.loads(provider_bytes)["geometry_profiles"][profile_id]))
        converging = copy.deepcopy(contract)
        converging["mirror"]["convergence_transform"] = {"angle_deg": 0.025688743, "pivot_y_mm": 0.0}
        cases = []
        # PRE-MOVE MR16 physical outputs; canonical JSON after ONLY schema/old OA-view exclusion.
        # Original/new OA view replacement is explicit; these are not full schema2 hashes.
        for name, request, size, gem_sha, physical_sha in (
            ("parallel", contract, 93548,
             "10fbab197ef4bf2193a7f1b694606ad2c48b3749c3a7e2039d1b9ac948a505af",
             "9e697a2ea3d2a209bffdb61080482cbf81ab11a8e2179434178004cb0f454b1b"),
            ("converging", converging, 97273,
             "bf5d3cc84247bd59c85b1e4a2f1fa47436c47b6b06d9f3ea317a45a5706eae99",
             "58d1994f052a876cdaf6eb03c95f0579e48be2613eae031f4b6d8ea364fb59f6"),
        ):
            authority = dict(accelerator_requirements=build_two_zone_accelerator_requirements(
                request, geometry_profile=profile), geometry_profile=copy.deepcopy(profile),
                geometry_profile_id=profile_id)
            cases.append(dict(case=name, contract=copy.deepcopy(request), authority=authority,
                              geometry=resolve_geometry(request, **authority), expected_gem_bytes=size,
                              expected_gem_sha256=gem_sha, expected_physical_sha256=physical_sha))
        assert provider_path.read_bytes() == provider_bytes
        return dict(numerical_contract=contract, cases=cases,
                    profile_source=dict(bytes=len(provider_bytes), sha256=hashlib.sha256(provider_bytes).hexdigest()))

    def mr_interface_probe_fixture(self) -> list[dict]:
        # Original six-parent physical fixture; expected complete results were
        # recorded from the retired original publisher at 574ae974 (8849a767...).
        # This is an explicit test oracle, not a second design/default authority.
        import copy
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_assembly_interface as fixtures
        baseline = json.loads(r'''{
  "schema_version": 1,
  "role": "component_geometry_interface",
  "project_id": "parallel_mirror_dual_stripe_mr_tof",
  "variant_id": "complete_mr_analyzer",
  "geometry_profile_id": null,
  "local_frame_id": "astral.xyz.reflection_z.drift_y.transverse_x.v2",
  "length_unit": "mm",
  "ports": {
    "accelerator_entry": {
      "surface_kind": "aperture_outer_face",
      "center_mm": [
        0.0,
        -55.0,
        -30.0
      ],
      "outward_normal": [
        0,
        0,
        1
      ],
      "wall_thickness_mm": null,
      "cross_section": {
        "shape": "rectangle",
        "width_mm": 4.0,
        "height_mm": 40.0,
        "width_axis": [
          1,
          0,
          0
        ],
        "height_axis": [
          0,
          1,
          0
        ]
      }
    }
  },
  "component_electrodes": [
    {
      "component_electrode_id": 1,
      "role": "mirror"
    },
    {
      "component_electrode_id": 2,
      "role": "mirror"
    },
    {
      "component_electrode_id": 3,
      "role": "mirror"
    },
    {
      "component_electrode_id": 4,
      "role": "mirror"
    },
    {
      "component_electrode_id": 5,
      "role": "mirror"
    },
    {
      "component_electrode_id": 6,
      "role": "mirror"
    },
    {
      "component_electrode_id": 7,
      "role": "mirror"
    },
    {
      "component_electrode_id": 8,
      "role": "mirror"
    },
    {
      "component_electrode_id": 9,
      "role": "mirror"
    },
    {
      "component_electrode_id": 10,
      "role": "mirror"
    },
    {
      "component_electrode_id": 11,
      "role": "stripe"
    },
    {
      "component_electrode_id": 12,
      "role": "stripe"
    },
    {
      "component_electrode_id": 13,
      "role": "stripe"
    },
    {
      "component_electrode_id": 14,
      "role": "stripe"
    },
    {
      "component_electrode_id": 15,
      "role": "central_ground"
    },
    {
      "component_electrode_id": 16,
      "role": "prism"
    },
    {
      "component_electrode_id": 17,
      "role": "prism"
    },
    {
      "component_electrode_id": 18,
      "role": "prism_ground_shield"
    },
    {
      "component_electrode_id": 20,
      "role": "prism_ground_shield"
    },
    {
      "component_electrode_id": 25,
      "role": "detector"
    }
  ]
}''')
        golden = [copy.deepcopy(baseline)]
        # Exact original-oracle port deltas; the 20-electrode inventory is shared.
        rectangular = copy.deepcopy(baseline)
        rectangular["ports"]["accelerator_entry"]["center_mm"] = [0.0, -55.0, 5.3]
        rectangular["ports"]["accelerator_entry"]["cross_section"]["width_mm"] = 4
        rectangular["ports"]["accelerator_entry"]["cross_section"]["height_mm"] = 40
        golden.append(rectangular)
        nondefault = copy.deepcopy(rectangular)
        nondefault["ports"]["accelerator_entry"]["center_mm"] = [2.0, -55.0, 5.3]
        nondefault["ports"]["accelerator_entry"]["cross_section"]["width_mm"] = 6
        golden.append(nondefault)
        cases = []
        for index, (label, resolved) in enumerate((
            ("complete", copy.deepcopy(fixtures.complete_geometry())),
            ("rectangular_slot", fixtures.geometry()),
            ("nondefault_slot", fixtures.geometry()),
        )):
            if label == "nondefault_slot":
                slot = resolved["prism_ground_shields"][0]["rectangular_slots_mm"][0]
                slot[0], slot[3] = -1, 5
            cases.append(dict(case=label, source=resolved, expected=golden[index]))
        for kind in ("missing", "closure", "duplicate", "noninteger", "ground", "detector"):
            resolved = copy.deepcopy(fixtures.complete_geometry())
            if kind == "missing":
                resolved["stripe_electrodes"] = []
            elif kind == "closure":
                resolved["mirror_e_closures"][0]["id"] = 25
            elif kind == "duplicate":
                resolved["stripe_electrodes"][0]["id"] = resolved["mirror_electrodes"][0]["id"]
            elif kind == "noninteger":
                resolved["stripe_electrodes"][0]["id"] = True
            elif kind == "ground":
                resolved["central_ground_electrodes"] = []
            else:
                resolved["detector"]["id"] = 15
            cases.append(dict(case="identity_" + kind, source=resolved, error="MR"))
        for kind in ("front", "back", "body", "clearance"):
            resolved = fixtures.geometry()
            shield = resolved["prism_ground_shields"][0]
            if kind == "front":
                shield["rectangular_slots_mm"][0][5] = 5.2
            elif kind == "back":
                shield["rectangular_slots_mm"][0][2] = -99
            elif kind == "body":
                shield["body_sections"][0]["polygon_yz_mm"][2][1] = 5.2
            else:
                shield["prism_clearance_polygon_yz_mm"][0][1] = 5.3
            cases.append(dict(case="slot_" + kind, source=resolved, error="MR E18"))
        for kind in ("missing", "duplicate", "frame"):
            resolved = fixtures.geometry()
            if kind == "missing":
                resolved["prism_ground_shields"] = []
            elif kind == "duplicate":
                resolved["prism_ground_shields"] *= 2
            else:
                resolved["frame_id"] = "ip_frame"
            cases.append(dict(case="frame_" + kind, source=resolved, error="MR accelerator_exit"))
        return cases

    def oa_focus_analysis_probe_fixture(self) -> dict:
        from projects.orthogonal_accelerator.tests.analysis import test_component_focus_analysis as fixtures
        from msplatform.workflows.oa_focus_analysis import analyze
        case = fixtures.ComponentFocusAnalysisTests()
        case.setUp()
        self.addCleanup(case.tearDown)
        events = case.write_events()
        profile = fixtures._geometry_profile()
        contract = json.loads((fixtures.ROOT / "config/component_contract.json").read_text(encoding="utf-8"))
        return dict(events=str(events), release_receipt=str(case.receipt), campaign=str(case.campaign),
                    geometry_profile=profile, component_contract=contract,
                    expected=analyze(events, case.receipt, case.campaign, geometry_profile=profile))

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
        # Only the ten reviewed, already tracked structural source templates
        # migrate into the wheel. Generated/native payloads remain forbidden.
        template = any(name == path or name.endswith('/' + path) for path in
            (f'msplatform/backends/simion/resources/{count}_instance_seed.iob' for count in range(1,11)))
        if not template:
            self.assertNotRegex(name, r'\.(pa\d*|pa#|pa-surf|mph|iob|dll|exe|pyc)$')

    def inspect_wheel(self, wheel: Path) -> list[str]:
        config = tomllib.loads((REPO_ROOT/'pyproject.toml').read_text(encoding='utf-8'))
        expected_resources = {
            path.relative_to(REPO_ROOT/'src').as_posix()
            for package,patterns in config['tool']['setuptools']['package-data'].items()
            for pattern in patterns
            for path in (REPO_ROOT/'src'/Path(*package.split('.'))).glob(pattern)
            if path.is_file()
        }
        expected_schemas = sorted(Path(name).name for name in expected_resources if name.endswith('.schema.json'))
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

    @staticmethod
    def recorded_frontend_analysis_probe_fixture(root: Path) -> list[dict]:
        from integrations.tests.test_local_frontend_analysis import fixture
        directory = root / "recorded-analyzer-fixture-0"
        directory.mkdir()
        log, _ = fixture(directory)
        cases = [dict(kind="local", expected_exit=1,
            log=log.relative_to(directory).as_posix(),
            files={path.relative_to(directory).as_posix():path.read_bytes().hex()
                   for path in directory.rglob('*') if path.is_file()})]
        return cases

    @staticmethod
    def paired_pulse_analysis_probe_fixture(root: Path) -> dict:
        from integrations.tests.test_comsol_prepulse_replay import ComsolPrePulseReplayTests
        from integrations.tests.test_paired_accelerator_pulse_comparison import PairedPulseComparisonTests
        source = root / 'paired-pulse-fixture'
        source.mkdir()
        collection, geometry, release, metadata, decision = ComsolPrePulseReplayTests()._write_source(source)
        comparison = PairedPulseComparisonTests()
        plan, _, comsol, simion = comparison.fixture(source)
        comparison.compare(source, plan, comsol, simion)
        return dict(collection=str(collection), geometry=str(geometry), decision=str(decision),
            expected_release=release.read_text(encoding='utf-8'),
            expected_metadata=json.loads(metadata.read_text(encoding='utf-8')),
            plan=str(plan), comsol=str(source/'comsol.csv'), simion=str(source/'simion.csv'),
            expected_differences=(source/'out/paired_pulse_differences.csv').read_text(encoding='utf-8'),
            expected_comparison=json.loads((source/'out/paired_pulse_comparison.json').read_text(encoding='utf-8')))





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
            for name in tuple(environment):
                if name.upper().startswith('GIT_'):
                    environment.pop(name)
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
            from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface
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
            from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_uniform_rear_gas_field
            from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
            from msplatform.contracts.gas import GasSpecies
            cone_config = REPO_ROOT / 'projects/dual_cone_tandem_quadrupole_ion_interface/config'
            dual_cone = {name: json.loads((cone_config / filename).read_text(encoding='utf-8'))
                for name, filename in (('baseline', 'baseline.json'), ('resolved', 'resolved_geometry.json'),
                    ('numerics', 'simion_solver_numerics.json'), ('uniform_rear_gas_field', 'uniform_rear_gas_field.json'),
                    ('gas_field_interface', 'gas_field_interface.json'), ('ion_transport_science','ion_transport_science.json'),
                    ('gas_flow_science','gas_flow_science.json'), ('source_spec','cylindrical_ion_source.json'))}
            dual_cone['gem'] = render_gem(dual_cone['resolved'], dual_cone['numerics'])
            for name in ('uniform_rear_gas_field', 'gas_field_interface'):
                (root/(name+'.json')).write_text(json.dumps(dual_cone[name]), encoding='utf-8')
            from msplatform.io.manifest_records import file_record as gas_file_record
            dual_cone['uniform_source_records'] = dict(
                spec=gas_file_record(root/'uniform_rear_gas_field.json','required_evidence'),
                interface=gas_file_record(root/'gas_field_interface.json','required_evidence'))
            field, runtime_metadata = prepare_uniform_rear_gas_field(dual_cone['uniform_rear_gas_field'],
                interface=dual_cone['gas_field_interface'],
                composition=(GasSpecies(dual_cone['gas_flow_science']['physics']['gas_species']['species_id'],
                    dual_cone['ion_transport_science']['gas']['collision_gas_mass_amu'],1.),),
                spec_record=dual_cone['uniform_source_records']['spec'],
                interface_record=dual_cone['uniform_source_records']['interface'])
            materialize_gas_runtime(field,root/'fixture-uniform.lua',root/'fixture-uniform-manifest.json',manifest_metadata=runtime_metadata)
            dual_cone['uniform_lua'] = (root/'fixture-uniform.lua').read_text(encoding='utf-8')
            from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
            from msplatform.backends.simion.ip_geometry import render_gem as render_ip_gem
            ip_config = REPO_ROOT / 'projects/dual_pressure_rectilinear_ion_processor/config'
            ip = {name: json.loads((ip_config/(name+'.json')).read_text(encoding='utf-8'))
                  for name in ('baseline', 'numerics', 'source', 'native_operating_point', 'acceptance')}
            from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import HS1_SOURCE_FIXTURE
            ip['preparation_config'] = {name: ip[name] for name in ('baseline', 'numerics', 'source', 'native_operating_point', 'acceptance')}
            ip['preparation_config'].update(source_profile='functional', source_authority_file='source.json')
            selected_hs1 = environment.get('MASS_SPECTROMETRY_INSTALLED_IP_HS1_SOURCE')
            hs1_bytes = Path(selected_hs1).read_bytes() if selected_hs1 else HS1_SOURCE_FIXTURE.encode('utf-8')
            ip['hs1_input_bytes_hex'] = hs1_bytes.hex()
            ip['hs1_input_kind'] = 'explicit_vendor_source' if selected_hs1 else 'inert_unit_fixture'
            ip['hs1_input_sha256'] = hashlib.sha256(hs1_bytes).hexdigest()
            from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import NativeFieldReferenceTests
            field_parent, _, field_model, field_family = NativeFieldReferenceTests().make_family_fixture(root / 'inert-ip-field-reference')
            ip['field_reference_parent'] = str(field_parent)
            ip['field_reference_model'] = field_model
            ip['gem_sha256'] = hashlib.sha256(render_ip_gem(native_projection(ip['baseline'], ip['numerics'])).encode()).hexdigest()
            ip['native_drive'] = (REPO_ROOT/'src/msplatform/backends/simion/resources/native_drive.lua').read_text(encoding='utf-8')
            ip['model'] = dict(baseline=ip['baseline'], numerics=ip['numerics'], source=ip['source'],
                               native_operating_point=ip['native_operating_point'])
            ip['identities'] = {name: dict(path='inputs/'+name, bytes=1, sha256='A'*64)
                                for name in ('resolved_model', 'source_spec', 'release_csv')}
            from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_paired_accelerator_static_field_prepare import PairedAcceleratorStaticFieldPrepareTests
            from msplatform.backends.comsol.paired_static_field import prepare as prepare_paired_field
            paired_request = PairedAcceleratorStaticFieldPrepareTests()._request(root)
            (root/'paired-request.json').write_text(json.dumps(paired_request), encoding='utf-8')
            paired = dict(expected_plan=prepare_paired_field(root/'paired-request.json', root/'paired-installed'))
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps(dict(repo_root=str(REPO_ROOT),
                                              author_source_roots=[str(REPO_ROOT)],
                                              recipe=recipe, components=components,
                                              distribution_version=config['project']['version'],
                                              source=spec, expected_states=generate_release_states(spec),
                                              schemas=expected_schemas,
                                              contract_schemas=sorted(path.name for path in (REPO_ROOT/'src/msplatform/contracts/schemas').glob('*.schema.json')),
                                              provider_layout=provider_layout,
                                              rf_oa_layout=rf_oa_layout, neutral_state=neutral_state,
                                              standalone_contracts=standalone_contracts, dual_cone=dual_cone, ip=ip,
                                              paired_static=paired,
                                              paired_pulse_analysis=self.paired_pulse_analysis_probe_fixture(root),
                                              recorded_frontend_analysis=self.recorded_frontend_analysis_probe_fixture(root),
                                              single_reflection_workflow=self.single_reflection_workflow_probe_fixture(root),
                                              multipole_ip_request=self.multipole_ip_probe_fixture(),
                                              gas_field_reference=self.gas_field_probe_fixture(root),
                                              prepared_joint_admission=self.prepared_joint_admission_probe_fixture(root),
                                              single_reflection_collection=self.single_reflection_collection_probe_fixture(),
                                              single_reflection_continuation=self.single_reflection_continuation_probe_fixture(),
                                              prepared_joint_diagnostics=self.prepared_joint_diagnostics_probe_fixture(),
                                              comparison=self.comparison_probe_fixture(),
                                              oa_focus_analysis=self.oa_focus_analysis_probe_fixture(),
                                              mr_interface=self.mr_interface_probe_fixture(),
                                              mr_backend_geometry=self.mr_backend_geometry_probe_fixture(),
                                              tof_budget=self.tof_budget_probe_fixture(),
                                              rf_l1_managed=self.rf_l1_managed_probe_fixture(root),
                                              tof_kernel=self.tof_kernel_probe_fixture(),
                                              additional_blocked_source_roots=json.loads(environment.get('MASS_SPECTROMETRY_INSTALLED_CORE_BLOCKED_SOURCE_ROOTS', '[]')),
                                              scalar_adapter=self.scalar_adapter_probe_fixture(),
                                              mr_prism_phase=self.prism_phase_probe_fixture(),
                                              mr_stripe=self.stripe_probe_fixture(),
                                              mr_operating_pa=self.operating_pa_probe_fixture(),
                                              tof_acceptance_kernels=self.tof_acceptance_kernels_probe_fixture(),
                                              native_path_powershell=shutil.which('pwsh'))), encoding='utf-8')
            consumer_python = str(consumer / python_name)
            probe_path = root / 'installed_scientific_probe.py'
            probe_path.write_text(INSTALLED_PROBE, encoding='utf-8')
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
                # SOFTWARE client only: prior ~61 s client + original ~110 s negative
                # parent + real three-stage owner/executor and shared-admission margin.
                # This 900 s harness bound does not change the stage's 120 s warning.
                result = self.run_command([consumer_python, '-I', str(probe_path), str(fixture), str(index)],
                                          cwd=root, environment=probe_environment, timeout=900)
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
