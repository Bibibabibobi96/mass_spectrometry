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
from msplatform.components.dual_pressure_rectilinear_ion_processor.cooled_buncher import build_cooled_buncher_contract, BUNCHER_ELECTRODE_NAMES
from msplatform.backends.simion.ip_frontend_geometry import render_cooled_buncher_gem_fragment
from msplatform.contracts.rigid_transform import RigidTransform
guide = export_guide_contract(dict(ip['model'], native_projection=projection), ip['identities'])
assert len(guide['rod_array']['rods']) == 8
registration = ip['registration']
pose = RigidTransform.from_contract(guide['coordinate_transform']).then(RigidTransform(guide['frame_id'], 'mrtof_global_cartesian', registration['rotation_upstream_to_downstream'], registration['translation_mm'])).to_contract()
cooled = build_cooled_buncher_contract(ip['model'], guide_contract=guide, native_to_assembly=pose, request=ip['request'], electrode_ids=ip['electrode_ids'])
assert len(cooled['native_projection_fragment']['electrodes']) == 7
assert hashlib.sha256(render_cooled_buncher_gem_fragment(cooled).encode()).hexdigest() == ip['cooled_gem_sha256']
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
    workflow_modes.append(case['kind'])
assert workflow_modes == ['recorded_birth','release_spec','recorded_pre_pulse_state']

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
            from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.uniform_gas_runtime import export_uniform_runtime
            cone_config = REPO_ROOT / 'projects/dual_cone_tandem_quadrupole_ion_interface/config'
            dual_cone = {name: json.loads((cone_config / filename).read_text(encoding='utf-8'))
                for name, filename in (('baseline', 'baseline.json'), ('resolved', 'resolved_geometry.json'),
                    ('numerics', 'simion_solver_numerics.json'), ('uniform_rear_gas_field', 'uniform_rear_gas_field.json'),
                    ('gas_field_interface', 'gas_field_interface.json'), ('ion_transport_science','ion_transport_science.json'),
                    ('gas_flow_science','gas_flow_science.json'), ('source_spec','cylindrical_ion_source.json'))}
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
            from msplatform.components.dual_pressure_rectilinear_ion_processor.guide_interface import export_guide_contract
            from msplatform.components.dual_pressure_rectilinear_ion_processor.cooled_buncher import build_cooled_buncher_contract, BUNCHER_ELECTRODE_NAMES
            from msplatform.backends.simion.ip_frontend_geometry import render_cooled_buncher_gem_fragment
            from msplatform.contracts.rigid_transform import RigidTransform
            ip['model'] = dict(baseline=ip['baseline'], numerics=ip['numerics'], source=ip['source'],
                               native_operating_point=ip['native_operating_point'])
            ip['identities'] = {name: dict(path='inputs/'+name, bytes=1, sha256='A'*64)
                                for name in ('resolved_model', 'source_spec', 'release_csv')}
            guide = export_guide_contract(dict(ip['model'], native_projection=native_projection(ip['baseline'], ip['numerics'])), ip['identities'])
            ip['registration'] = dict(rotation_upstream_to_downstream=[[0,-1,0],[0,0,1],[-1,0,0]], translation_mm=[0,-97,32])
            ip['request'] = dict(schema_version=1, role='ion_processor_hp_end_buncher_request', inner_center_inset_mm=5., inner_length_mm=2.5)
            ip['electrode_ids'] = dict(zip(BUNCHER_ELECTRODE_NAMES, range(40,47), strict=True))
            registration = ip['registration']
            pose = RigidTransform.from_contract(guide['coordinate_transform']).then(RigidTransform(guide['frame_id'], 'mrtof_global_cartesian', registration['rotation_upstream_to_downstream'], registration['translation_mm'])).to_contract()
            cooled = build_cooled_buncher_contract(ip['model'], guide_contract=guide, native_to_assembly=pose, request=ip['request'], electrode_ids=ip['electrode_ids'])
            ip['cooled_gem_sha256'] = hashlib.sha256(render_cooled_buncher_gem_fragment(cooled).encode()).hexdigest()
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
                                              single_reflection_workflow=self.single_reflection_workflow_probe_fixture(root),
                                              multipole_ip_request=self.multipole_ip_probe_fixture(),
                                              gas_field_reference=self.gas_field_probe_fixture(root),
                                              prepared_joint_admission=self.prepared_joint_admission_probe_fixture(root),
                                              single_reflection_collection=self.single_reflection_collection_probe_fixture(),
                                              single_reflection_continuation=self.single_reflection_continuation_probe_fixture(),
                                              prepared_joint_diagnostics=self.prepared_joint_diagnostics_probe_fixture(),
                                              comparison=self.comparison_probe_fixture(),
                                              oa_focus_analysis=self.oa_focus_analysis_probe_fixture(),
                                              additional_blocked_source_roots=json.loads(environment.get('MASS_SPECTROMETRY_INSTALLED_CORE_BLOCKED_SOURCE_ROOTS', '[]')),
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
                result = self.run_command([consumer_python, '-I', str(probe_path), str(fixture), str(index)],
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
