"""Direct-field planning, real Lua with PA doubles and inert native orchestration."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_single_reflection_preparation import fixture, release_fixture, rename_author_instances
from integrations.tests.test_single_reflection_fields import multipole_source
from integrations.workflows.single_reflection_flight.field_plan import (
    KINDS, bind_parent_fields, build_field_plan, field_bank, frontend_field_identity, audit_input_identity,
    validate_frozen_generation_metadata, write_audit_spec,
)
from integrations.workflows.single_reflection_flight.prepare import prepare
from common.contracts.file_identity import file_sha256
from common.contracts.write_run_manifest import file_record
from common.simion import pa_family_cache
from common.simion.pa_family_cache import canonical_pa_family_cache_key, publish_pa_family_cache

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / 'integrations/workflows/single_reflection_flight'
LUA = Path(shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe')


def prepared(root: Path, *, source=None, entrance_refinement=False, local=False) -> tuple[Path, dict]:
    if local:
        request, run, _, _ = release_fixture(root, local=True)
    else:
        request, run, _ = fixture(root, source=source, entrance_refinement=entrance_refinement)
    prepare(request, run)
    return run, build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'][0]


class DirectFieldPlanTests(unittest.TestCase):
    def test_instance_rename_and_reorder_preserve_full_and_local_native_plans(self):
        for local in (False, True):
            with self.subTest(local=local), tempfile.TemporaryDirectory() as directory:
                reference = None
                for renamed in (False, True):
                    case = Path(directory) / str(renamed)
                    case.mkdir()
                    path, run, request, _ = release_fixture(case, local=local)
                    if renamed:
                        rename_author_instances(path, request)
                    prepare(path, run)
                    inputs = run / 'inputs'
                    actual = ((inputs / 'frontend.gem').read_bytes(),
                              (inputs / 'projected_source.csv').read_bytes(),
                              build_field_plan(inputs, Path(sys.executable), ROOT))
                    if reference is None:
                        reference = actual
                    else:
                        self.assertEqual(actual, reference)

    def test_frozen_instance_binding_errors_fail_before_native_field_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            run, _ = prepared(Path(directory))
            path = run / 'inputs/frontend_geometry.json'
            original = json.loads(path.read_text())
            edge = original['composition_plan']['recipe']['connections'][0]
            first, second = edge['upstream']['instance_id'], edge['downstream']['instance_id']
            for change in ('missing_instance', 'unknown_instance', 'swapped_instances',
                           'missing_role', 'collision', 'duplicate_solver_id'):
                geometry = copy.deepcopy(original)
                bindings = geometry['electrode_bindings']
                if change == 'missing_instance': del bindings[first]
                elif change == 'unknown_instance': bindings['unselected'] = bindings.pop(first)
                elif change == 'swapped_instances': bindings[first], bindings[second] = bindings[second], bindings[first]
                elif change == 'missing_role': del bindings[second]['accelerator_repeller_id']
                elif change == 'collision': bindings[second]['grounded_shield_id'] = 1
                else: bindings[first]['2'] = bindings[first]['1']
                path.write_text(json.dumps(geometry), encoding='utf-8')
                with self.subTest(change=change), self.assertRaises(ValueError):
                    build_field_plan(run / 'inputs', Path(sys.executable), ROOT)
            # Physical rod groups are raw electrode sources now.  Reordering
            # their binding records is valid when their solver IDs remain
            # unique; this must not retain the removed PA+ mode restriction.
            valid = copy.deepcopy(original)
            valid_bindings = valid['electrode_bindings'][first]
            valid_bindings['1'], valid_bindings['2'] = valid_bindings['2'], valid_bindings['1']
            path.write_text(json.dumps(valid), encoding='utf-8')
            self.assertTrue(build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'])

    def test_downstream_moves_preserve_actual_frontend_inputs_and_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = None
            for case in ('baseline', 'detector', 'reflectron'):
                case_root = root / case
                case_root.mkdir()
                request_path, run, request = fixture(case_root)
                provider_path = request_path.parent / 'oatof.json'
                provider = json.loads(provider_path.read_text())
                if case == 'detector':
                    provider['coordinate_convention']['detector_x'] += 1.0
                elif case == 'reflectron':
                    provider['coordinate_convention']['reflectron_axis'][0] += 1.0
                provider_path.write_text(json.dumps(provider), encoding='utf-8')
                request['providers']['instances']['oatof']['resolved_design'] = file_record(provider_path, recorded_path=Path('oatof.json'))
                request_path.write_text(json.dumps(request), encoding='utf-8')
                prepare(request_path, run)
                inputs = run / 'inputs'
                actual = dict(geometry=json.loads((inputs / 'frontend_geometry.json').read_text()),
                    design=json.loads((inputs / 'frontend_field_design.json').read_text()),
                    gem=(inputs / 'frontend.gem').read_bytes(),
                    plan=build_field_plan(inputs, Path(sys.executable), ROOT))
                if baseline is None:
                    baseline = actual
                    continue
                with self.subTest(case=case):
                    self.assertEqual([key for key in baseline['geometry']
                        if baseline['geometry'][key] != actual['geometry'][key]], ['downstream_pa_instances'])
                    self.assertEqual(baseline['gem'], actual['gem'])
                    self.assertEqual(baseline['design'], actual['design'])
                    self.assertEqual(baseline['plan'], actual['plan'])

    def test_frontend_gem_mesh_domain_and_audit_samples_change_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run, baseline = prepared(Path(directory))
            inputs = run / 'inputs'
            design_path, geometry_path = inputs / 'frontend_field_design.json', inputs / 'frontend_geometry.json'
            original_design = json.loads(design_path.read_text())
            original_geometry = json.loads(geometry_path.read_text())
            gem_path = inputs / 'frontend.gem'
            original_gem = gem_path.read_bytes()
            for case in ('gem', 'mesh', 'domain', 'sample_position', 'sample_electrode'):
                design, geometry = copy.deepcopy(original_design), copy.deepcopy(original_geometry)
                gem_path.write_bytes(original_gem)
                if case == 'gem':
                    gem_path.write_bytes(original_gem.replace(b'e(1)', b'e(2)', 1))
                    self.assertNotEqual(gem_path.read_bytes(), original_gem)
                    design['domains'][0]['gem_sha256'] = file_sha256(gem_path)
                elif case == 'mesh':
                    design['domains'][0]['cell_mm_xyz']['x'] *= 2
                    geometry['numerical_domains']['parent']['cell_mm_xyz'] = design['domains'][0]['cell_mm_xyz']
                elif case == 'domain':
                    design['domains'][0]['dimensions']['nx'] += 1
                    geometry['numerical_domains']['parent']['dimensions'] = design['domains'][0]['dimensions']
                elif case == 'sample_position':
                    design['domains'][0]['physical_samples'][0]['gu'][0] += 1
                else:
                    samples = design['domains'][0]['physical_samples']
                    samples[0]['electrode_id'], samples[-1]['electrode_id'] = (
                        samples[-1]['electrode_id'], samples[0]['electrode_id'])
                design_path.write_text(json.dumps(design), encoding='utf-8')
                geometry_path.write_text(json.dumps(geometry), encoding='utf-8')
                with self.subTest(case=case):
                    assertion = self.assertEqual if case.startswith('sample_') else self.assertNotEqual
                    assertion([m['cache_key'] for m in baseline['members']],
                        [m['cache_key'] for m in build_field_plan(inputs, Path(sys.executable), ROOT)['domains'][0]['members']])

    def test_two_rf_sources_preserve_scope_and_bind_explicit_member_boundary(self):
        import hashlib
        from integrations.tests.test_single_reflection_geometry import multi_inputs, quadrupole_source, candidate_300mm_fixture
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        from integrations.workflows.single_reflection_flight.fields import prepare_field_design, POLICY
        from integrations.workflows.single_reflection_flight.field_plan import _check_source_physics, _member_projection, _parent_boundary
        sources = [quadrupole_source(r0=4., dc=1., frequency_hz=1e6, phase_rad=.1),
                   quadrupole_source(r0=4.5, dc=2., frequency_hz=1.1e6, phase_rad=.2)]
        oatof = candidate_300mm_fixture()
        arguments = multi_inputs(sources, oatof, names=['a', 'b'])
        arguments['numerical_domains']['entrance_refinement'] = copy.deepcopy(arguments['numerical_domains']['parent'])
        arguments['numerical_domains']['entrance_refinement']['guard_cells'] = 1
        gems, geometry = compile_frontend_geometry(dict(zip(['a','b'], sources, strict=True)), oatof, **arguments)
        convergence = dict(carrier_off=.1, rf_reference=.1, pulse_delta=.1)
        design = prepare_field_design(dict(zip(['a','b'], sources, strict=True)), oatof, geometry,
            variant_id='three_zone_square', pulse_voltage_policy_id=POLICY, boundary_policy='native_zero_neumann',
            rf_reference_voltage_v=10000., frontend_domains={
                name: dict(refine_convergence_v=convergence) for name in geometry['numerical_domains']})
        for domain in design['domains']:
            domain['gem_sha256'] = hashlib.sha256(gems[domain['domain_id']].encode()).hexdigest().upper()
        parents = {point.get('working_point_id') or point['kind']: dict(cache_key='A'*64,
            record=dict(kind=point['kind'], working_point_id=point.get('working_point_id'),
                path='frontend.'+(point.get('working_point_id') or point['kind'])+'.pa', bytes=10, sha256='B'*64))
            for point in design['working_points']}
        member_id = 'rf_reference_02'
        identity = dict(frontend_field_identity(design, 'parent', member_id=member_id),
            simion_identity={'pure': True}, builder_identity=dict(operating_builder='C'*64, exporter='D'*64))
        member = dict(member_id=member_id, identity=identity, frozen_field_source=dict(
            identity=copy.deepcopy(identity), physical_point=identity['working_points'][0], source_schema_version=3))
        _check_source_physics(member)
        # Each fine member consumes only its corresponding published parent field.
        boundary_identity = dict(identity, boundary_policy=_parent_boundary(
            design['domains'][0]['instance_origin_mm'], parents[member_id]))
        self.assertEqual(boundary_identity['boundary_policy']['parent_working_points'][0]['name'], 'frontend.rf_reference_02.pa')
        historical = copy.deepcopy(boundary_identity)
        historical['boundary_policy']['parent_working_points'].insert(0,
            dict(kind='rf_reference', working_point_id='rf_reference_01', name='frontend.rf_reference_01.pa',bytes=10,sha256='E'*64))
        self.assertEqual(_member_projection(historical, identity['working_points'][0], member_id=member_id), boundary_identity)
        member['frozen_field_source']['identity']['working_points'][0]['electrode_voltages_v']['1'] = 123.
        with self.assertRaisesRegex(ValueError, 'physical identity'):
            _check_source_physics(member)

    def test_actual_plan_has_only_three_operating_fields_and_no_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            self.assertEqual(len(plan['physical_samples']), 59)
            self.assertEqual([p['kind'] for p in plan['working_points']], list(KINDS))
            self.assertEqual(len(plan['members']), 3)
            self.assertTrue(all(len(member['filenames']) == 1 for member in plan['members']))
            self.assertEqual(set(plan['members'][1]['identity']), {'geometry', 'gem', 'working_points', 'mesh', 'grid_phase',
                'surface', 'boundary_policy', 'rf_reference_voltage_v', 'simion_identity', 'builder_identity'})
            self.assertFalse(any(name.endswith(('.pa0', '.pa#', '.pa+')) for member in plan['members'] for name in member['filenames']))
            (run / 'inputs/source.csv').write_text('unrelated source change')
            self.assertEqual(plan, build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'][0])
            bank = field_bank(json.loads((run/'inputs/frontend_field_design.json').read_text()), ['parent'])['dynamic_roles'][0]
            self.assertEqual(bank['instance_index'], 1)
            self.assertEqual(bank['rf_differential_pa_basenames'], ['frontend.rf_reference.pa'])
            path = run / 'audit.tsv'
            write_audit_spec(plan, run / 'raw.pa#', run, path)
            self.assertEqual(sum(line.startswith('physical\t') for line in path.read_text().splitlines()), 59)

    def test_actual_voltage_convergence_boundary_and_geometry_change_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            path = run / 'inputs/frontend_field_design.json'
            original = json.loads(path.read_text())
            for field in ('voltage', 'convergence', 'reference'):
                design = copy.deepcopy(original)
                if field == 'voltage': design['working_points'][0]['electrode_voltages_v']['1'] += 1
                elif field == 'convergence': design['domains'][0]['refine_convergence_v']['carrier_off'] *= 2
                else: design['rf_reference_voltage_v'] *= 2
                path.write_text(json.dumps(design))
                self.assertNotEqual([m['cache_key'] for m in plan['members']], [m['cache_key'] for m in build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'][0]['members']])
            for field in ('boundary', 'grid', 'missing_voltage', 'missing_sample', 'duplicate_sample', 'nonfinite'):
                design = copy.deepcopy(original)
                if field == 'boundary': design['domains'][0]['boundary_policy'] = 'zero_dirichlet'
                elif field == 'grid': design['domains'][0]['dimensions']['nx'] += 1
                elif field == 'missing_voltage': del design['working_points'][1]['electrode_voltages_v']['35']
                elif field == 'missing_sample': design['domains'][0]['physical_samples'].pop(0)
                elif field == 'duplicate_sample': design['domains'][0]['physical_samples'][-1] = design['domains'][0]['physical_samples'][0]
                else: design['domains'][0]['refine_convergence_v']['rf_reference'] = float('nan')
                path.write_text(json.dumps(design))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    build_field_plan(run / 'inputs', Path(sys.executable), ROOT)

    def test_gem_drift_rejected_and_actual_builder_changes_key(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            module = 'integrations.workflows.single_reflection_flight.field_plan.file_sha256'
            def changed_builder(path):
                return '0'*64 if Path(path).name == 'build_dirichlet_patch_operating_pa.lua' else file_sha256(path)
            with patch(module, side_effect=changed_builder):
                self.assertNotEqual([m['cache_key'] for m in plan['members']], [m['cache_key'] for m in build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'][0]['members']])
            with (run / 'inputs/frontend.gem').open('a') as stream:
                stream.write('\n; changed geometry\n')
            with self.assertRaisesRegex(ValueError, 'GEM identity'):
                build_field_plan(run / 'inputs', Path(sys.executable), ROOT)

    def test_local_plan_keeps_actual_11_to_35_namespace_and_only_off_pulse_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory), local=True)
            self.assertEqual(plan['physical_electrode_ids'], list(range(11, 36)))
            self.assertEqual(len(plan['physical_samples']), 25)
            self.assertEqual([row['kind'] for row in plan['working_points']], ['carrier_off','pulse_delta'])
            self.assertTrue(all('rf_reference_voltage_v' not in member['identity'] for member in plan['members']))
            for point in plan['working_points']:
                indexed = list(map(float, point['voltage_argument'].split(',')))
                self.assertEqual(len(indexed), 35)
                self.assertEqual(indexed[:10], [0.]*10)
                self.assertEqual(indexed[10:], [point['electrode_voltages_v'][str(i)] for i in range(11,36)])
            bank = field_bank(json.loads((run/'inputs/frontend_field_design.json').read_text()), ['parent'])['dynamic_roles'][0]
            self.assertNotIn('rf_reference_voltage_v', bank)
            self.assertNotIn('rf_differential_pa_basename', bank)
            design = json.loads((run/'inputs/frontend_field_design.json').read_text())
            for defect in ('invented_rf_reference','invented_electrode'):
                changed = copy.deepcopy(design)
                if defect == 'invented_rf_reference':
                    changed['rf_reference_voltage_v'] = 1.
                else:
                    changed['working_points'][0]['electrode_voltages_v']['1'] = 0.
                (run/'inputs/frontend_field_design.json').write_text(json.dumps(changed))
                with self.subTest(defect=defect), self.assertRaises(ValueError):
                    build_field_plan(run/'inputs', Path(sys.executable), ROOT)

    def test_fine_identity_uses_published_parent_and_guard_is_not_a_solve_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, run, _ = fixture(root, entrance_refinement=True)
            prepare(request, run)
            inputs = run / 'inputs'
            bundle = build_field_plan(inputs, Path(sys.executable), ROOT)
            parent, fine = bundle['domains']
            authority = {member['member_id']: dict(cache_key=member['cache_key'], record=dict(
                kind=member['working_points'][0]['kind'], path='frontend.'+member['member_id']+'.pa',
                bytes=100, sha256='A'*64)) for member in parent['members']}
            bound = bind_parent_fields(fine, authority)
            design = json.loads((inputs/'frontend_field_design.json').read_text())
            for member in bound['members']:
                projected = frontend_field_identity(design, 'entrance_refinement',
                    member_id=member['member_id'], parent_fields=authority)
                self.assertEqual(projected, {key: value for key, value in member['identity'].items()
                    if key not in ('simion_identity', 'builder_identity')})
                self.assertEqual(len(member['identity']['boundary_policy']['parent_working_points']), 1)
            drift = copy.deepcopy(authority)
            drift['rf_reference']['record']['sha256'] = 'B'*64
            changed = bind_parent_fields(fine, drift)
            self.assertEqual(bound['members'][0]['cache_key'], changed['members'][0]['cache_key'])
            self.assertNotEqual(bound['members'][1]['cache_key'], changed['members'][1]['cache_key'])
            self.assertEqual(bound['members'][2]['cache_key'], changed['members'][2]['cache_key'])

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_actual_lua_audit_opens_one_pa_and_rejects_wrong_ids_voltages_mask_and_grid(self):
        for project in ('rf_quadrupole_ion_optics', 'rf_hexapole_ion_optics', 'rf_octupole_ion_optics'):
            with self.subTest(project=project):
                self.check_lua_audit(multipole_source(project))

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_fine_lua_audit_accepts_actual_subset_but_checks_full_voltage_namespace(self):
        self.check_lua_audit(multipole_source('rf_octupole_ion_optics'), entrance_refinement=True)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_public_operating_builder_preserves_sparse_ids_and_does_not_create_padding_metal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root/'sparse.lua'
            harness.write_text(r"""
local helper=arg[1]
local store={};local refinements=0
local function clone(points)
 local result={};for k,v in pairs(points) do result[k]={v[1],v[2]} end;return result
end
store['raw.pa#']={['0,0,0']={11,true},['1,1,1']={12,true},['2,2,2']={35,true}}
simion={pas={}}
function simion.pas:close() end
function simion.pas:open(path)
 local points=clone(assert(store[path]))
 local pa={nx=3,ny=3,nz=3,dx_mm=.25,dy_mm=.25,dz_mm=.05}
 function pa:point(x,y,z,value,metal)
  local key=x..','..y..','..z
  if value~=nil then points[key]={value,metal};return end
  local item=points[key] or {0,false};return item[1],item[2]
 end
 function pa:save(name) store[name]=clone(points) end
 function pa:close() end
 function pa:refine(options)
  refinements=refinements+1;assert(options.convergence==.003)
  assert(points['0,0,0'][1]==0 and points['1,1,1'][1]==2140 and points['2,2,2'][1]==372)
 end
 return pa
end
local volts={};for i=1,35 do volts[i]=0 end;volts[12]=2140;volts[35]=372
arg={'raw.pa#','working.pa0','zero_neumann','0,0,0','0,0,0',table.concat(volts,','),'.003'}
dofile(helper)
assert(refinements==1)
local metal=0
for _,point in pairs(store['working.pa0']) do if point[2] then metal=metal+1 end end
assert(metal==3,'padding parameter slots must never create physical electrodes')
assert(store['raw.pa#']['1,1,1'][1]==12,'raw IDs changed')
""",encoding='utf-8',newline='\n')
            result = subprocess.run([str(LUA),str(harness),
                str(ROOT/'common/simion/build_dirichlet_patch_operating_pa.lua')],
                cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
    def test_local_lua_audit_uses_sparse_real_ids_without_a_zero_rf_member(self):
        self.check_lua_audit(None, local=True)

    def check_lua_audit(self, source, *, entrance_refinement=False, local=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, plan = prepared(root, source=source, entrance_refinement=entrance_refinement, local=local)
            if entrance_refinement:
                plan = build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'][1]
            spec = root / 'spec.tsv'
            write_audit_spec(plan, root / 'raw.pa#', root, spec)
            # Feed every actual provider piece / voltage table to a bounded PA double.
            rows = []
            for sample in plan['physical_samples']:
                rows.append("['"+','.join(map(str, sample['gu']))+"']="+str(sample['electrode_id']))
            tables = []
            for point in plan['working_points']:
                tables.append("['"+point['kind']+"']={"+point['voltage_argument']+"}")
            harness = root / 'audit.lua'
            harness.write_text("local ids={"+','.join(rows)+"}\nlocal volts={"+','.join(tables)+"}\n"+r'''
local helper,spec,report,fault=arg[1],arg[2],arg[3],arg[4]
local active=0
simion={pas={}}
function simion.pas:close() assert(active==0) end
function simion.pas:open(path)
 active=active+1;assert(active==1,'audit must not retain multiple fields')
 local kind=path:match('frontend[^/\\\\]*%.([^%.]+)%.pa$')
 local pa={potential_type='electric',nx=NX,ny=NY,nz=NZ,dx_mm=DX,dy_mm=DY,dz_mm=DZ}
 if fault=='grid' and kind then pa.nx=pa.nx+1 end
 function pa:point(x,y,z)
  local id=assert(ids[x..','..y..','..z])
  local value=kind and volts[kind][id] or id
  if fault=='roundoff' and kind then value=value+1e-12 end
  if fault=='id' and not kind then value=value+1 end
  if fault=='voltage' and kind then value=value+1 end
  if fault=='nonfinite' and kind then value=0/0 end
  return value,not(fault=='mask' and kind)
 end
 function pa:close() active=active-1 end
 return pa
end
arg={spec,report};dofile(helper);assert(active==0)
'''.replace('NX', str(plan['grid'][0])).replace('NY', str(plan['grid'][1])).replace('NZ', str(plan['grid'][2]))
                .replace('DX', repr(plan['grid'][3])).replace('DY', repr(plan['grid'][4])).replace('DZ', repr(plan['grid'][5])),
                encoding='utf-8', newline='\n')
            for point in plan['working_points']:
                single = dict(plan, working_points=[point])
                write_audit_spec(single, root/'raw.pa#', root, spec)
                for fault in ('none', 'roundoff', 'id', 'voltage', 'mask', 'grid', 'nonfinite'):
                    result = subprocess.run([str(LUA), str(harness), str(WORKFLOW / 'audit_frontend_working_fields.lua'),
                        str(spec), str(root / 'audit.json'), fault], cwd=root, capture_output=True,
                        text=True, encoding='utf-8', timeout=30, check=False)
                    with self.subTest(fault=fault):
                        self.assertEqual(result.returncode == 0, fault in ('none', 'roundoff'), result.stderr)
            self.assertEqual(json.loads((root / 'audit.json').read_text())['physical_samples'],
                             len(plan['physical_samples']))

    def test_held_off_to_timed_adds_only_pulse_cache_member(self):
        plans = []
        for held in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                path, run, request = fixture(Path(directory))
                request['flight'] = dict(pulse={'mode':'held_off'} if held else {'mode':'timed','time_us':10.,'width_us':3.},
                    maximum_flight_us=200.,maximum_step_us=.001,trajectory_quality=10,rf_steps_per_period=40)
                request['numerics']['frontend_domains']['parent']['refine_convergence_v']['pulse_delta'] = .9 if held else .003
                path.write_text(json.dumps(request))
                prepare(path,run)
                design=json.loads((run/'inputs/frontend_field_design.json').read_text())
                domain=build_field_plan(run/'inputs',Path(sys.executable),ROOT)['domains'][0]
                plans.append({m['member_id']:m['cache_key'] for m in domain['members']})
                row=field_bank(design,['parent'])['dynamic_roles'][0]
                self.assertEqual('pulse_delta_pa_basename' in row,not held)
        self.assertEqual(plans[0],{k:v for k,v in plans[1].items() if k!='pulse_delta'})
        self.assertEqual(set(plans[1])-set(plans[0]),{'pulse_delta'})


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell Core unavailable')
class FrozenFieldSourcePlanTests(unittest.TestCase):
    def _declare_frozen_parent_source(self, inputs: Path, plan: dict) -> dict:
        identity = copy.deepcopy(plan['members'][0]['identity'])
        identity['working_points'] = [member['identity']['working_points'][0] for member in plan['members']]
        if 'rf_reference_voltage_v' in plan['members'][1]['identity']:
            identity['rf_reference_voltage_v'] = plan['members'][1]['identity']['rf_reference_voltage_v']
        identity['geometry']['physical_samples'] = copy.deepcopy(plan['physical_samples'])
        identity['builder_identity'].update(field_plan='A'*64, field_stage='B'*64, audit='C'*64)
        filenames = [point['filename'] for point in plan['working_points']] + ['frontend_working_fields_audit.json']
        identity_path = inputs / 'frontend_field_source_parent_identity.json'
        identity_path.write_text(json.dumps(identity), encoding='utf-8')
        payload = inputs.parent.parent / 'source_payload'
        payload.mkdir()
        for index, filename in enumerate(filenames):
            (payload / filename).write_bytes(bytes([index]))
        publication = publish_pa_family_cache(inputs.parent.parent / 'source_cache', identity,
            payload, filenames, recovery_policy='none')
        inventory = {row['name']: row for row in publication.manifest['files']}
        records = [dict(kind=point['kind'], path=f'C:/producer/simion/frontend_working_fields/{point["filename"]}',
                        bytes=inventory[point['filename']]['bytes'], sha256=inventory[point['filename']]['sha256'], read_only=True)
                   for point in plan['working_points']]
        receipt = dict(schema_version=2, role='single_reflection_frontend_working_fields', status='success',
            **({'rf_reference_voltage_v': identity['rf_reference_voltage_v']} if 'rf_reference_voltage_v' in identity else {}), domains=[dict(domain_id='parent',
                cache_key=canonical_pa_family_cache_key(identity), generation_directory=str(publication.generation_directory),
                working_points=records, cache_identity_record=file_record(identity_path))])
        (inputs / 'frontend_field_source_receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        manifest_path = inputs / 'frontend_field_source_manifest.json'
        manifest_path.write_text(json.dumps(
            dict(role='simulation_run_manifest', outputs=[file_record(identity_path)])),
            encoding='utf-8')
        provenance_path = inputs / 'source_provenance.json'
        provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
        provenance.setdefault('input_records', {})['frontend_fields_manifest'] = {
            **file_record(manifest_path), 'source_path': 'C:/producer/run_manifest.json'}
        provenance_path.write_text(json.dumps(provenance), encoding='utf-8')
        request_path = inputs / 'request.json'
        request = json.loads(request_path.read_text())
        request['providers']['frontend_fields'] = {'path': 'declared-source.json', 'bytes': 1, 'sha256': 'E' * 64}
        request_path.write_text(json.dumps(request), encoding='utf-8')
        return identity

    def test_explicit_frozen_source_preserves_producer_identity_and_allows_orchestration_hash_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory))
            identity = self._declare_frozen_parent_source(run / 'inputs', plan)
            actual = build_field_plan(run / 'inputs', Path(sys.executable), ROOT)
            self.assertTrue(actual['frozen_field_source'])
            self.assertEqual(actual['domains'][0]['members'][0]['frozen_field_source']['identity'], identity)
            self.assertEqual(actual['domains'][0]['members'][0]['frozen_field_source']['cache_key'], canonical_pa_family_cache_key(identity))

    def test_explicit_members_reuse_exact_carrier_rf_but_never_changed_pulse(self):
        with tempfile.TemporaryDirectory() as directory:
            run, original = prepared(Path(directory))
            source_identity = self._declare_frozen_parent_source(run/'inputs', original)
            design_path = run/'inputs/frontend_field_design.json'
            design = json.loads(design_path.read_text())
            # Audit sample presentation and sampling do not change solved PA physics.
            design['domains'][0]['physical_samples'][0]['label'] += '_new'
            design['domains'][0]['physical_samples'][0]['gu'][0] += 1
            design['working_points'][2]['electrode_voltages_v']['17'] += 1e-12
            design_path.write_text(json.dumps(design))
            with self.assertRaisesRegex(ValueError, 'pulse_delta.*physical identity'):
                build_field_plan(run/'inputs', Path(sys.executable), ROOT)
            request_path = run/'inputs/request.json'
            request = json.loads(request_path.read_text())
            request['providers']['frontend_field_reuse_members'] = ['carrier_off', 'rf_reference']
            request_path.write_text(json.dumps(request))
            current = build_field_plan(run/'inputs', Path(sys.executable), ROOT)['domains'][0]
            for index in (0, 1):
                member = current['members'][index]
                source = member['frozen_field_source']
                self.assertEqual(source['cache_key'], canonical_pa_family_cache_key(source_identity))
                self.assertEqual(member['identity'], original['members'][index]['identity'])
            self.assertNotIn('frozen_field_source', current['members'][2])
            self.assertNotEqual(current['members'][2]['cache_key'], original['members'][2]['cache_key'])
            before = dict(original, identity=original['members'][0]['identity'], working_points=[original['working_points'][0]])
            after = dict(current, identity=current['members'][0]['identity'], working_points=[current['working_points'][0]])
            self.assertNotEqual(audit_input_identity(before), audit_input_identity(after))
            after['physical_samples'] = copy.deepcopy(before['physical_samples'])
            after['physical_samples'][0]['label'] += '_only_display'
            self.assertEqual(audit_input_identity(before), audit_input_identity(after))

    def test_frozen_source_is_selected_only_by_declared_provider_and_rejects_drift_or_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run, plan = prepared(Path(directory), local=True)
            inputs = run / 'inputs'
            # An undeclared stray receipt cannot change the route.
            (inputs / 'frontend_field_source_receipt.json').write_text('{}', encoding='utf-8')
            self.assertFalse(build_field_plan(inputs, Path(sys.executable), ROOT)['frozen_field_source'])
            identity = self._declare_frozen_parent_source(inputs, plan)
            identity['builder_identity']['operating_builder'] = 'F' * 64
            identity_path = inputs / 'frontend_field_source_parent_identity.json'
            identity_path.write_text(json.dumps(identity), encoding='utf-8')
            receipt_path = inputs / 'frontend_field_source_receipt.json'
            receipt = json.loads(receipt_path.read_text())
            receipt['domains'][0]['cache_key'] = canonical_pa_family_cache_key(identity)
            receipt['domains'][0]['cache_identity_record'] = file_record(identity_path)
            receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'cache key|physical identity'):
                build_field_plan(inputs, Path(sys.executable), ROOT)
            identity_path.unlink()
            with self.assertRaisesRegex(ValueError, 'identity copy differs'):
                build_field_plan(inputs, Path(sys.executable), ROOT)

    def test_frozen_generation_metadata_uses_public_metadata_without_reading_pa_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, plan = prepared(root)
            self._declare_frozen_parent_source(run / 'inputs', plan)
            source_plan = build_field_plan(run / 'inputs', Path(sys.executable), ROOT)['domains'][0]['members'][0]
            source_plan = dict(source_plan['frozen_field_source'], filenames=source_plan['frozen_field_source']['cache_filenames'],
                frozen_field_source=dict(working_points=[source_plan['frozen_field_source']['record']]))
            generation = Path(source_plan['generation_directory'])
            with patch.object(pa_family_cache, 'file_sha256', side_effect=AssertionError('PA payload read')):
                manifest = validate_frozen_generation_metadata(source_plan, generation)
            self.assertEqual(manifest['cache_key'], source_plan['cache_key'])


class DirectFieldStageTests(unittest.TestCase):
    def test_missing_member_topup_uses_exact_stage_floor_and_does_not_repeat_when_sufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'commitment.ps1'
            script.write_text(r'''
param($Source)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$blocks=@($ast.FindAll({param($node)
 $node-is[Management.Automation.Language.IfStatementAst]-and
 $node.Clauses[0].Item1.Extent.Text-eq'[long]$CapacitySession.Value.committed_new_bytes-lt$memberCommitment'
},$true))
if($blocks.Count-ne1){throw 'missing-member capacity boundary must be unique'}
$operation=[scriptblock]::Create($blocks[0].Extent.Text)
$script:renewals=@()
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
 $script:renewals+=,$RemainingCommittedNewBytes
 $Session.committed_new_bytes=$RemainingCommittedNewBytes
 [pscustomobject]@{session=$Session}
}
$Python='unused';$RepoRoot='unused'
# Observed N2 metadata-only accounting: two 56-byte PA headers, two
# generation manifests and their pointers, beyond the exact 8*N arrays.
[long]$array=679L*150L*6456L*8L
[long]$ReservedRunPayloadBytes=104060026
[long]$initial=$ReservedRunPayloadBytes+5L*$array
[long]$published=2L*$array+56L*2L+2830L+2929L+181L*2L
[long]$memberCommitment=$ReservedRunPayloadBytes+3L*$array
$session=[pscustomobject]@{committed_new_bytes=($initial-$published)}
$CapacitySession=[ref]$session
$shortfall=$memberCommitment-$session.committed_new_bytes
&$operation
if($shortfall-ne6233-or$script:renewals.Count-ne1-or$script:renewals[0]-ne15885106426L){throw 'incorrect real N2 topup'}
&$operation
if($script:renewals.Count-ne1){throw 'sufficient commitment was renewed again'}
[pscustomobject]@{shortfall=$shortfall;committed=$session.committed_new_bytes;updates=$script:renewals.Count}|ConvertTo-Json
''', encoding='utf-8', newline='\n')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(script), str(WORKFLOW / 'field_stage.ps1')],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(shortfall=6233, committed=15885106426, updates=1))

    def test_explicit_source_two_domains_reuses_six_members_without_probe_or_native(self):
        self.run_stage_fixture(recovery=False, fine=True, frozen_source=True)

    def test_legacy_source_reuses_exact_carrier_rf_and_builds_only_changed_pulse(self):
        self.run_stage_fixture(recovery=False, frozen_source=True, legacy_partial=True)

    def test_changed_audit_only_reserves_raw_before_native_and_releases_to_zero(self):
        self.run_stage_fixture(recovery=False, frozen_source=True, audit_refresh=True, reserve_failure=True)

    def test_miss_then_hit_real_public_transaction_without_private_copies(self):
        self.run_stage_fixture(recovery=False)

    def test_partial_export_stays_in_scratch_and_retry_rebuilds_only_missing_fields(self):
        self.run_stage_fixture(recovery=True)

    def test_two_ready_members_are_not_refined_when_only_last_member_needs_completion(self):
        self.run_stage_fixture(recovery=True, last_member_only=True)

    def test_failed_stage_accounting_defers_capacity_without_masking_native_error(self):
        self.run_stage_fixture(recovery=True, accounting_failure=True)

    def test_prepared_audit_failure_does_not_repeat_accounting_or_defer(self):
        self.run_stage_fixture(recovery=False, prepared_audit_failure=True)

    def test_complete_transaction_reentry_does_not_charge_existing_generation_twice(self):
        self.run_stage_fixture(recovery=False, prepared_resume=True)

    def test_two_domains_use_same_kind_common_parent_and_hit_without_native(self):
        self.run_stage_fixture(recovery=False, fine=True)

    def test_producer_handoff_routes_only_first_begin_with_current_lease(self):
        self.run_stage_fixture(recovery=False, producer_handoff=True)

    def test_handoff_conflict_is_not_masked_by_empty_domain_cleanup(self):
        self.run_stage_fixture(recovery=False, producer_handoff=True, handoff_conflict=True)

    def test_partial_fine_export_reuses_parent_and_complete_fine_members(self):
        self.run_stage_fixture(recovery=True, fine=True)

    def test_retry_rejects_damaged_common_parent_before_fine_native(self):
        self.run_stage_fixture(recovery=True, fine=True, private_damage=True)

    def test_local_two_fields_use_the_same_cache_and_have_zero_native_on_hit(self):
        self.run_stage_fixture(recovery=False, local=True)

    def test_parent_hit_fine_miss_preserves_parent_key_and_cumulative_capacity(self):
        self.run_stage_fixture(recovery=False, fine=True, fine_change=True)

    def test_capacity_topup_rejection_stops_before_any_native(self):
        self.run_stage_fixture(recovery=False, fine=True, budget_failure=True)

    def test_zero_private_reservation_publishes_common_fields(self):
        self.run_stage_fixture(recovery=False, fine=True, reserve_failure=True)

    def run_stage_fixture(self, *, recovery, prepared_resume=False, fine=False, fine_change=False,
                          budget_failure=False, reserve_failure=False, private_damage=False, local=False,
                          frozen_source=False, legacy_partial=False, audit_refresh=False, producer_handoff=False,
                          handoff_conflict=False, accounting_failure=False, prepared_audit_failure=False,
                          last_member_only=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = prepared(root, entrance_refinement=fine, local=local)
            (run / 'logs').mkdir(exist_ok=True)
            (run / 'run_config.json').write_text('{}')
            if producer_handoff:
                request_path = run / 'inputs/request.json'
                request = json.loads(request_path.read_text())
                request['continuation'] = dict(frontend_field_transactions=[
                    dict(domain_id='parent', member_id='pulse_delta')])
                request_path.write_text(json.dumps(request))
                provenance_path = run / 'inputs/source_provenance.json'
                provenance = json.loads(provenance_path.read_text())
                for name in ('continuation_parent_manifest', 'continuation_stopped_receipt', 'continuation_field_transaction_001'):
                    evidence = run / 'inputs' / (name + '.json')
                    evidence.write_text(json.dumps(dict(fixture=name)))
                    provenance['input_records'][name] = file_record(evidence)
                provenance_path.write_text(json.dumps(provenance))
            script = root / 'stage.ps1'
            script.write_text(r'''
param($Repo,$Python,$Run,$Cache,$Recovery,$PreparedResume,$FineChange,$BudgetFailure,$Fine,$PrivateDamage,$FrozenSource,$LegacyPartial,$AuditRefresh,$ProducerHandoff,$AccountingFailure,$PreparedAuditFailure,$LastMemberOnly)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
. (Join-Path $Repo 'integrations/workflows/single_reflection_flight/field_stage.ps1')
$script:native=@();$script:stages=@();$script:scopes=@();$script:injectedFailure=$false;$script:handoffSeen=0;$script:stageAccounting=0
$WarningPreference='SilentlyContinue'
function Invoke-RunToolRootContext {
 param($RepoRoot,$Operation)
 if($PreparedAuditFailure-eq'1'-and$Name-eq'parent_carrier_off_begin'){
   Push-Location $RepoRoot
   try { &$Operation } finally { Pop-Location }
   $prepared=Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json
   $prepared.status='prepared';$prepared.action_required='verify'
   [IO.File]::WriteAllText((Join-Path $prepared.build_directory 'frontend.carrier_off.pa'),'INERT_ALREADY_ACCOUNTED_PAYLOAD')
   [IO.File]::WriteAllText($stdout,($prepared|ConvertTo-Json -Depth 100))
   return
 }
 if($Arguments -contains '--record-stage-only'){
   $script:stageAccounting++
   if($AccountingFailure-eq'1'){
     [IO.File]::WriteAllText($stderr,'INERT accounting write failed')
     throw "Frontend field Python stage failed: $Name (see $stderr)"
   }
   # Transaction accounting itself is exercised with a real governed ledger in
   # common tests; this non-governed native double checks failure transport.
   [IO.File]::WriteAllText($stdout,'{"status":"building","action_required":"build"}')
   return
 }
 $handoffIndex=[array]::IndexOf($Arguments,'--producer-handoff')
 if($handoffIndex-ge0){
   if($ProducerHandoff-notin@('1','2')-or$Name-ne'parent_pulse_delta_begin'){throw 'handoff repeated outside selected first begin'}
   $handoff=Get-Content -LiteralPath $Arguments[$handoffIndex+1] -Raw|ConvertFrom-Json -AsHashtable
   $expected=@('schema_version','transaction_record','predecessor_manifest','stopped_receipt','capacity_lease_id','capacity_lease_owner')
   if($handoff.Count-ne6-or@($handoff.Keys|Where-Object{$_-notin$expected}).Count){throw 'handoff must have six transport keys'}
   if($handoff.schema_version-ne1-or$handoff.capacity_lease_id-ne$capacity.lease_id-or$handoff.capacity_lease_owner-ne$capacity.owner){throw 'handoff current lease differs'}
   if($key-notin$capacity.protected_cache_keys){throw 'handoff precedes current key protection'}
   if($Arguments[([array]::IndexOf($Arguments,'--owner'))+1]-ne[IO.Path]::GetFileName($Run)-or$Arguments[([array]::IndexOf($Arguments,'--producer-run-config'))+1]-ne(Join-Path $Run 'run_config.json')){throw 'handoff new producer differs'}
   foreach($record in @($handoff.transaction_record,$handoff.predecessor_manifest,$handoff.stopped_receipt)){
     if(-not([IO.Path]::GetFullPath($record.path).StartsWith((Join-Path $Run 'inputs')))){throw 'handoff evidence is not frozen input'}
   }
   $script:handoffSeen++
   if($ProducerHandoff-eq'2'){
     [IO.File]::WriteAllText($stderr,'PA producer handoff has another active consumer')
     throw "Frontend field Python stage failed: $Name (see $stderr)"
   }
   # The governed common handoff state machine has its own real transaction tests.
   # This inert native-stage fixture checks CLI transport, then uses its ordinary fixture cache.
   $plain=@($Arguments[0..($handoffIndex-1)])
   Push-Location $RepoRoot
   try { &$Python -B @plain 1>$stdout 2>$stderr; if($LASTEXITCODE-ne0){throw 'ordinary fixture begin failed'} }
   finally {Pop-Location}
   return
 }
 if($script:sourceOnly-and$Name-match'_(probe|begin|seal|publish)$'){throw 'explicit source reached cache discovery or transaction'}
 if($script:resumePrepared-and$Name-eq'parent_carrier_off_probe'){
   [IO.File]::WriteAllText($stdout,'{"disposition":"miss"}');return
 }
 if($script:resumePrepared-and$Name-eq'parent_carrier_off_begin'){
   [IO.File]::WriteAllText($stdout,(@{status='published';action_required='complete';generation_directory=$script:completedGeneration}|ConvertTo-Json));return
 }
 Push-Location $RepoRoot;try{&$Operation}finally{Pop-Location}
}
function Write-RunJson {param($Path,$Value,$Depth) [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth $Depth),[Text.UTF8Encoding]::new($false))}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedCacheKeys,$RemainingCommittedNewBytes)
 $Session.protected_cache_keys=@(@($Session.protected_cache_keys)+@($ProtectedCacheKeys)|Select-Object -Unique)
 $script:scopes+=,@($Session.protected_cache_keys)
 if($BudgetFailure-eq'1'-and$PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')-and$RemainingCommittedNewBytes-gt$Session.committed_new_bytes){throw 'INERT public capacity admission rejected'}
 if($PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')-and$RemainingCommittedNewBytes-lt$requiredReserve){throw 'cache handoff consumed reserved downstream/private payload'}
 if($PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')){$Session.committed_new_bytes=$RemainingCommittedNewBytes}
 [pscustomobject]@{session=$Session}
}
function Get-HostResourceBudget {param($Role,$Stage) @{} }
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) $script:stages+=$Stage;return $Lease}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError)
 $script:native+=,@($ArgumentList)
 if($PreparedAuditFailure-eq'1'-and$ArgumentList[3]-like'*audit_frontend_working_fields.lua'){
   return [pscustomobject]@{exit_code=1;resource_budget_exceeded=$false}
 }
 if($ArgumentList[2]-eq'gem2pa'){
   $currentPlan=Get-Content -LiteralPath (Join-Path $Run 'inputs/frontend_field_design.json') -Raw|ConvertFrom-Json -Depth 100
   $domainId=if($WorkingDirectory-like'*entrance_refinement*'){'entrance_refinement'}else{'parent'}
   $dimensions=@($currentPlan.domains|Where-Object{$_.domain_id-eq$domainId})[0].dimensions
   [long]$rawBytes=[long]$dimensions.nx*[long]$dimensions.ny*[long]$dimensions.nz*8
   if($capacity.committed_new_bytes-lt($requiredReserve+$rawBytes)){throw 'uncommitted raw PA write'}
   [IO.File]::WriteAllText($ArgumentList[4],'INERT_RAW')
 }
 elseif($ArgumentList[3].EndsWith('build_dirichlet_patch_operating_pa.lua')){
   if($ArgumentList[6]-ne'zero_neumann'){
     $parentName=[IO.Path]::GetFileName($ArgumentList[6])
     if($parentName-notmatch'^frontend\..+\.pa$'){throw 'fine must consume same-member parent'}
     if($ArgumentList[6]-notlike'*generations*'){throw 'fine must consume canonical standalone parent'}
     if(-not(Test-Path -LiteralPath $ArgumentList[6])){throw 'private parent absent'}
     $design=Get-Content -LiteralPath (Join-Path $Run 'inputs/frontend_field_design.json') -Raw|ConvertFrom-Json -Depth 100
     for($i=0;$i-lt2;$i++){
       $origin=(@('x','y','z')|ForEach-Object{([double]$design.domains[$i].instance_origin_mm.$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
       if($ArgumentList[7+$i]-ne$origin){throw 'parent/patch actual origin changed'}
     }
   }
   if($script:stages[-1]-ne'pa_refine'){throw 'refine lacks heavy stage'}
   [IO.File]::WriteAllText($ArgumentList[5],('INERT_WORKING:'+ $ArgumentList[9]))
 }
 elseif($ArgumentList[3].EndsWith('export_detached_standalone_pa.lua')){
   $failureName=if($LastMemberOnly-eq'1'){'frontend.pulse_delta.pa'}elseif($Fine-eq'1'){'frontend_entrance_refinement.rf_reference.pa'}else{'frontend.rf_reference.pa'}
   if($Recovery-eq'1'-and-not$script:injectedFailure-and$ArgumentList[5].EndsWith($failureName)){
     $script:injectedFailure=$true
     [IO.File]::WriteAllText($ArgumentList[5],'PARTIAL_EXPORT')
     return [pscustomobject]@{resource_budget_exceeded=$false;exit_code=1}
   }
   [IO.File]::Copy($ArgumentList[4],$ArgumentList[5])
 }
 elseif($ArgumentList[3].EndsWith('audit_frontend_working_fields.lua')){
   [IO.File]::WriteAllText($ArgumentList[5],'{"status":"pass","fixture":"not native evidence"}')
 }else{throw 'unexpected native invocation'}
 [pscustomobject]@{resource_budget_exceeded=$false;exit_code=0}
}
$hostLease=[pscustomobject]@{id='inert'};$capacity=[pscustomobject]@{committed_new_bytes=1TB;protected_cache_keys=@();lease_id='current-workflow-lease';owner='current-workflow-owner'}
$limits=[pscustomobject]@{wall_clock_seconds=120}
$script:resumePrepared=$false
$script:sourceOnly=$false
$elapsed=[Diagnostics.Stopwatch]::StartNew()
$failed=$false;$payloadAfterFailure=@();$nativeAfterFailure=@()
$requiredReserve=if($BudgetFailure-eq'2'){[long]0}else{[long](100GB)}
if($BudgetFailure-eq'1'){
 $capacity.committed_new_bytes=100GB
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
   throw 'expected admission rejection'
 }catch{
   $expected=if($BudgetFailure-eq'2'){'*below all required private fields*'}else{'*INERT public capacity admission rejected*'}
   if($_.Exception.Message-notlike$expected){throw}
   if($script:native.Count-ne0){throw 'budget rejection followed native invocation'}
 }
 [pscustomobject]@{budget_rejected=$true;native_count=$script:native.Count}|ConvertTo-Json
 exit 0
}

if($PreparedAuditFailure-eq'1'){
 try {
  $null=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
  throw 'expected prepared audit rejection'
 } catch {
  if($_.Exception.Message-notlike'*native stage failed: parent_carrier_off_audit'){throw}
  if($script:stageAccounting-ne0-or$capacity.PSObject.Properties['defer_capacity_finalization']){throw 'prepared audit repeated stage accounting'}
  [pscustomobject]@{prepared_audit_rejected=$true;stage_accounting=$script:stageAccounting}|ConvertTo-Json
  exit 0
 }
}
if($Recovery-eq'1'){
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -StageElapsed $elapsed
 }catch{
   $expectedExport=if($LastMemberOnly-eq'1'){'*export_frontend.pulse_delta.pa*'}else{'*export_frontend*.rf_reference.pa*'}
   if($_.Exception.Message-notlike$expectedExport){throw}
   $failed=$true
   if($AccountingFailure-eq'1'){
     if(-not$capacity.defer_capacity_finalization){throw 'accounting failure did not defer finalization'}
     [pscustomobject]@{deferred=$true;primary_error=$_.Exception.Message;stage_accounting=$script:stageAccounting;committed_bytes=$capacity.committed_new_bytes}|ConvertTo-Json
     exit 0
   }
   $payloadAfterFailure=@(Get-ChildItem -LiteralPath (Join-Path $Cache '.transactions') -Recurse -Filter '*.pa'|Where-Object{$_.Directory.Name-eq'payload'}|ForEach-Object{$_.Name})
   $nativeAfterFailure=@($script:native)
 }
 if(-not$failed){throw 'partial exporter failure was not propagated'}
}
if($PrivateDamage-eq'1'){
 $damaged=@(Get-ChildItem -LiteralPath $Cache -Recurse -Filter 'frontend.carrier_off.pa'|Where-Object{$_.FullName-like'*generations*'})[0].FullName
 [IO.File]::SetAttributes($damaged,[IO.FileAttributes]::Normal)
 [IO.File]::WriteAllText($damaged,'DAMAGED_PRIVATE_PARENT')
 [IO.File]::SetAttributes($damaged,[IO.FileAttributes]::ReadOnly)
 $before=$script:native.Count
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
   throw 'expected private parent rejection'
 }catch{
   if($_.Exception.Message-notmatch'length|identity|differs|corrupt'){throw}
   if($script:native.Count-ne$before){throw 'damaged private parent reached native'}
 }
 [pscustomobject]@{private_damage_rejected=$true}|ConvertTo-Json
 exit 0
}
if($ProducerHandoff-eq'2'){
 try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -StageElapsed $elapsed
   throw 'expected handoff rejection'
 }catch{
   if($_.Exception.Message-notlike'*Frontend field Python stage failed: parent_pulse_delta_begin*'){throw}
   $diagnostic=Get-Content -LiteralPath (Join-Path $Run 'logs/parent_pulse_delta_begin.stderr.log') -Raw
   if($diagnostic-notlike'*another active consumer*'){throw 'original handoff cause lost'}
 }
 [pscustomobject]@{handoff_conflict_retained=$true;empty_domain_exists=(Test-Path -LiteralPath (Join-Path $Run 'simion/frontend_working_fields/parent_audit_geometry'))}|ConvertTo-Json
 exit 0
}
$one=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $Run -PreparedDirectory $Run -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache -StageElapsed $elapsed
$firstCount=$script:native.Count
$secondRun=Join-Path (Split-Path $Run) 'hit'
New-Item -ItemType Directory -Path (Join-Path $secondRun 'inputs'),(Join-Path $secondRun 'logs')|Out-Null
[IO.File]::WriteAllText((Join-Path $secondRun 'run_config.json'),'{}')
$oneReceipt=Get-Content -LiteralPath $one.cache_receipt -Raw|ConvertFrom-Json -Depth 80
$oneDomain=$oneReceipt.domains[0].working_points[0]
$script:completedGeneration=$oneDomain.generation_directory
$script:resumePrepared=($PreparedResume-eq'1')
$secondPrepared=$Run
if($FrozenSource-eq'1'){
 Get-ChildItem -LiteralPath (Join-Path $Run 'inputs') -File|ForEach-Object{
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $secondRun 'inputs')
 }
 Copy-Item -LiteralPath (Join-Path $Run 'inputs/components') -Destination (Join-Path $secondRun 'inputs/components') -Recurse
 foreach($domain in $oneReceipt.domains){
  foreach($record in $domain.working_points){
   $member=if($record.PSObject.Properties.Name-contains'working_point_id'){$record.working_point_id}else{$record.kind}
   Copy-Item -LiteralPath $record.cache_identity_record.path -Destination (Join-Path $secondRun ('inputs/frontend_field_source_{0}_{1}_identity.json' -f $domain.domain_id,$member))
   $record.path=Join-Path $Run ('simion/frontend_working_fields/'+[IO.Path]::GetFileName([string]$record.path))
   if(Test-Path -LiteralPath $record.path){throw 'source fixture unexpectedly retained private PA'}
  }
 }
 Write-RunJson -Path (Join-Path $secondRun 'inputs/frontend_field_source_receipt.json') -Value $oneReceipt -Depth 100
 $producerOutputs=@(foreach($domain in $oneReceipt.domains){foreach($record in $domain.working_points){@{path=$record.path;bytes=$record.bytes;sha256=$record.sha256}}})
 Write-RunJson -Path (Join-Path $secondRun 'inputs/frontend_field_source_manifest.json') -Value @{role='simulation_run_manifest';outputs=$producerOutputs} -Depth 100
 $sourceManifest=Join-Path $secondRun 'inputs/frontend_field_source_manifest.json'
 $provenance=Get-Content -LiteralPath (Join-Path $secondRun 'inputs/source_provenance.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 $provenance.input_records.frontend_fields_manifest=@{path=$sourceManifest;bytes=(Get-Item -LiteralPath $sourceManifest).Length;sha256=(Get-FileHash -LiteralPath $sourceManifest -Algorithm SHA256).Hash;source_path=(Join-Path $Run 'run_manifest.json')}
 Write-RunJson -Path (Join-Path $secondRun 'inputs/source_provenance.json') -Value $provenance -Depth 100
 $request=Get-Content -LiteralPath (Join-Path $secondRun 'inputs/request.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 $request.providers.frontend_fields=@{path='explicit-producer-receipt'}
 Write-RunJson -Path (Join-Path $secondRun 'inputs/request.json') -Value $request -Depth 100
 $secondPrepared=$secondRun
 $script:sourceOnly=$LegacyPartial-ne'1'
 if($LegacyPartial-eq'1'){
  $legacyCode=@'
import json,sys,shutil
from pathlib import Path
from common.contracts.write_run_manifest import file_record
from common.simion.pa_family_cache import publish_pa_family_cache
run,prepared,cache=map(Path,sys.argv[1:])
receipt=json.loads((run/'inputs/frontend_working_field_stage_receipt.json').read_text(encoding='utf-8-sig'))
design=json.loads((prepared/'inputs/frontend_field_design.json').read_text(encoding='utf-8-sig'))
domain=receipt['domains'][0];points=domain['working_points']
identities=[json.loads(Path(point['cache_identity_record']['path']).read_text(encoding='utf-8-sig')) for point in points]
identity=dict(identities[0],working_points=[item['working_points'][0] for item in identities],
              rf_reference_voltage_v=identities[1]['rf_reference_voltage_v'])
identity['geometry']=dict(identity['geometry'],physical_samples=design['domains'][0]['physical_samples'])
identity['builder_identity']=dict(identity['builder_identity'],audit='A'*64,field_plan='B'*64,field_stage='C'*64)
payload=prepared/'legacy_fixture_payload';payload.mkdir()
for point in points: shutil.copyfile(point['path'],payload/Path(point['path']).name)
(payload/'frontend_working_fields_audit.json').write_text(json.dumps(dict(status='pass',fixture='legacy_native_boundary_is_inert')))
publication=publish_pa_family_cache(cache,identity,payload,
    [*[Path(point['path']).name for point in points],'frontend_working_fields_audit.json'],recovery_policy='none')
path=prepared/'inputs/frontend_field_source_parent_identity.json';path.write_text(json.dumps(identity))
old=dict(schema_version=2,role='single_reflection_frontend_working_fields',status='success',
    rf_reference_voltage_v=identity['rf_reference_voltage_v'],domains=[dict(domain_id='parent',
    cache_key=publication.manifest['cache_key'],generation_directory=str(publication.generation_directory),
    cache_identity_record=file_record(path),working_points=[{key:point[key] for key in ('path','kind','bytes','sha256','read_only')} for point in points])])
(prepared/'inputs/frontend_field_source_receipt.json').write_text(json.dumps(old))
request_path=prepared/'inputs/request.json';request=json.loads(request_path.read_text(encoding='utf-8-sig'))
request['providers']['frontend_field_reuse_members']=['carrier_off','rf_reference'];request_path.write_text(json.dumps(request))
design['working_points'][2]['electrode_voltages_v']['17']+=1e-12
design['domains'][0]['physical_samples'][0]['label']+='_new_audit'
(prepared/'inputs/frontend_field_design.json').write_text(json.dumps(design))
'@
  $null=& $Python -c $legacyCode $Run $secondRun $Cache
  if($LASTEXITCODE-ne0){throw 'legacy pure fixture construction failed'}
 }
}
if($AuditRefresh-eq'1'){
 $designPath=Join-Path $secondRun 'inputs/frontend_field_design.json'
 $design=Get-Content -LiteralPath $designPath -Raw|ConvertFrom-Json -Depth 100
 $design.domains[0].physical_samples[0].gu[0]+=1
 Write-RunJson -Path $designPath -Value $design -Depth 100
}
if($FineChange-eq'1'){
 foreach($name in @('frontend_field_design.json','frontend_geometry.json','frontend.gem','frontend_entrance_refinement.gem')){
  Copy-Item -LiteralPath (Join-Path (Join-Path $Run 'inputs') $name) -Destination (Join-Path (Join-Path $secondRun 'inputs') $name)
 }
 Copy-Item -LiteralPath (Join-Path $Run 'inputs/components') -Destination (Join-Path $secondRun 'inputs/components') -Recurse
 $secondPrepared=$secondRun
 $designPath=Join-Path $secondRun 'inputs/frontend_field_design.json'
 $design=Get-Content -LiteralPath $designPath -Raw|ConvertFrom-Json -Depth 100
 $design.domains[1].refine_convergence_v.pulse_delta*=2
 Write-RunJson -Path $designPath -Value $design -Depth 100
}
if($FineChange-eq'1'-or$LegacyPartial-eq'1'-or$PreparedResume-eq'1'){$capacity.committed_new_bytes=1TB}
$commitmentBefore=$capacity.committed_new_bytes
$copiesBeforeSecond=$global:MassSpectrometryShortPaCopies.Count
$two=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $secondRun -PreparedDirectory $secondPrepared -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
$copiesAfterSecond=$global:MassSpectrometryShortPaCopies.Count
$sourceMissingRejected=$false
if($FrozenSource-eq'1'-and$LegacyPartial-ne'1'-and$AuditRefresh-ne'1'){
 $manifestPath=Join-Path $oneDomain.generation_directory 'cache_manifest.json'
 $hiddenManifest=$manifestPath+'.fixture-hidden'
 Move-Item -LiteralPath $manifestPath -Destination $hiddenManifest
 try{
  try{
   $null=Invoke-SingleReflectionFrontendFieldStage -Python $Python -RepoRoot $Repo -RunDirectory $secondRun -PreparedDirectory $secondPrepared -SimionExe $Python -HostLease ([ref]$hostLease) -CapacitySession ([ref]$capacity) -Limits $limits -ReservedRunPayloadBytes $requiredReserve -CacheRoot $Cache
   throw 'missing explicit generation was accepted'
  }catch{
   if($_.Exception.Message-notmatch'Python stage failed: frontend_working_(source_generation|plan)'){throw}
   $failure=Get-Content -LiteralPath (Join-Path $secondRun 'logs/frontend_working_plan.stderr.log') -Raw
   if($failure-notlike'*PA cache manifest is missing*'){throw 'wrong source failure'}
   $sourceMissingRejected=$true
  }
 }finally{Move-Item -LiteralPath $hiddenManifest -Destination $manifestPath}
}
$transactions=@(Get-ChildItem -LiteralPath (Join-Path $Cache '.transactions') -Recurse -Filter transaction.json)
$transaction=Get-Content -LiteralPath $transactions[0].FullName -Raw|ConvertFrom-Json -Depth 80
$manifest=Get-Content -LiteralPath (Join-Path $oneDomain.generation_directory 'cache_manifest.json') -Raw|ConvertFrom-Json -Depth 80
[pscustomobject]@{first=$one;second=$two;native=$script:native;first_count=$firstCount;second_native_count=($script:native.Count-$firstCount);
 stages=$script:stages;scopes=$script:scopes;transaction=$transaction;manifest=$manifest;failed=$failed;payload_after_failure=$payloadAfterFailure;native_after_failure=$nativeAfterFailure;handoff_seen=$script:handoffSeen;stage_accounting=$script:stageAccounting;
 protected_keys=$capacity.protected_cache_keys;commitment_before_second=$commitmentBefore;commitment_after_second=$capacity.committed_new_bytes;
 source_missing_rejected=$sourceMissingRejected;copies_before_second=$copiesBeforeSecond;copies_after_second=$copiesAfterSecond;disposable_copies=$global:MassSpectrometryShortPaCopies.Count;guards=$global:MassSpectrometryShortPaSourceGuards.Count}|ConvertTo-Json -Depth 100
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(ROOT), sys.executable,
                str(run), str(root / 'cache'), '1' if recovery else '0', '1' if prepared_resume else '0', '1' if fine_change else '0', '2' if reserve_failure else ('1' if budget_failure else '0'), '1' if fine else '0', '1' if private_damage else '0', '1' if frozen_source else '0', '1' if legacy_partial else '0', '1' if audit_refresh else '0', '2' if handoff_conflict else ('1' if producer_handoff else '0'), '1' if accounting_failure else '0', '1' if prepared_audit_failure else '0', '1' if last_member_only else '0'], cwd=ROOT, capture_output=True, text=True,
                encoding='utf-8', timeout=180, check=False)
            diagnostics = '\n'.join(path.read_text(encoding='utf-8-sig', errors='replace')
                for path in root.rglob('*.stderr.log')) if result.returncode else ''
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr+'\n'+diagnostics)
            data = json.loads(result.stdout)
            if prepared_audit_failure:
                self.assertTrue(data['prepared_audit_rejected'])
                self.assertEqual(data['stage_accounting'], 0)
                return
            if accounting_failure:
                self.assertTrue(data['deferred'])
                self.assertEqual(data['stage_accounting'], 1)
                self.assertGreater(data['committed_bytes'], 0)
                self.assertIn('export_frontend.rf_reference.pa', data['primary_error'])
                return
            if handoff_conflict:
                self.assertTrue(data['handoff_conflict_retained'])
                self.assertTrue(data['empty_domain_exists'])
                return
            if private_damage:
                self.assertTrue(data['private_damage_rejected'])
                return
            if budget_failure:
                self.assertTrue(data['budget_rejected'])
                self.assertEqual(data['native_count'], 0)
                return
            self.assertEqual(data['handoff_seen'], int(producer_handoff))
            expected_first = (23 if fine else 13) if recovery else (20 if fine else (7 if local else 10))
            self.assertEqual(data['first_count'], expected_first)
            if recovery:
                self.assertEqual(data['stage_accounting'], 1)
                self.assertTrue(data['failed'])
                # Carrier belongs to its published single-member generation;
                # failed RF export never appears as a completed payload.
                self.assertEqual(data['payload_after_failure'], [])
                retries = [args for args in data['native'][len(data['native_after_failure']):]
                           if len(args)>9 and args[3].endswith('build_dirichlet_patch_operating_pa.lua')]
                self.assertEqual(len(retries), 1 if last_member_only else 2)
            self.assertEqual(data['copies_before_second'], data['copies_after_second'])
            self.assertEqual(data['second_native_count'], 6 if legacy_partial else 4 if fine_change or audit_refresh else 0)
            if frozen_source and not legacy_partial and not audit_refresh:
                self.assertTrue(data['source_missing_rejected'])
            self.assertEqual(data['commitment_after_second'], 0 if reserve_failure else 100*1024**3)
            if prepared_resume:
                self.assertEqual(len(list((root/'cache'/data['manifest']['cache_key']/'generations').iterdir())), 1)
            if fine_change:
                first = json.loads(Path(data['first']['cache_receipt']).read_text())
                second = json.loads(Path(data['second']['cache_receipt']).read_text())
                self.assertEqual([row['cache_key'] for row in first['domains'][0]['working_points']],
                                 [row['cache_key'] for row in second['domains'][0]['working_points']])
                for index in (0, 1):
                    self.assertEqual(first['domains'][1]['working_points'][index]['cache_key'],
                                     second['domains'][1]['working_points'][index]['cache_key'])
                self.assertNotEqual(first['domains'][1]['working_points'][2]['cache_key'],
                                    second['domains'][1]['working_points'][2]['cache_key'])
                self.assertGreater(data['commitment_before_second']-data['commitment_after_second'], 0)
            elif legacy_partial:
                second = json.loads(Path(data['second']['cache_receipt']).read_text())
                points = second['domains'][0]['working_points']
                self.assertEqual([point['refine_performed'] for point in points], [False,False,True])
                self.assertEqual([point['source_schema_version'] for point in points], [2,2,3])
                self.assertEqual(points[0]['generation_directory'], points[1]['generation_directory'])
                self.assertNotEqual(points[1]['generation_directory'], points[2]['generation_directory'])
                second_native = data['native'][data['first_count']:]
                refinements = [args for args in second_native if len(args)>9 and args[3].endswith('build_dirichlet_patch_operating_pa.lua')]
                self.assertEqual(len(refinements), 1)
                self.assertEqual(refinements[0][9], ','.join(format(value,'.17g') for value in json.loads(
                    (root/'hit/inputs/frontend_field_design.json').read_text())['working_points'][2]['electrode_voltages_v'].values()))
            elif audit_refresh:
                self.assertEqual(data['commitment_before_second'], data['commitment_after_second'])
                second_native = data['native'][data['first_count']:]
                self.assertFalse(any(len(args)>9 and args[3].endswith('build_dirichlet_patch_operating_pa.lua') for args in second_native))
            elif not prepared_resume:
                self.assertEqual(data['commitment_before_second']-data['commitment_after_second'], 0)
            self.assertEqual(data['disposable_copies'], 0)
            self.assertEqual(data['guards'], 0)
            self.assertEqual(len(data['manifest']['files']), 1)
            self.assertIsNotNone(data['transaction']['published_pin_reason'])
            for case in ('first', 'second'):
                receipt = json.loads(Path(data[case]['cache_receipt']).read_text())
                self.assertEqual(receipt['role'], 'single_reflection_frontend_working_fields')
                self.assertEqual(receipt['schema_version'], 3)
                self.assertEqual(len(receipt['domains']), 2 if fine else 1)
                for domain in receipt['domains']:
                    self.assertEqual([point['kind'] for point in domain['working_points']],
                                     ['carrier_off', 'pulse_delta'] if local else list(KINDS))
                    for point in domain['working_points']:
                        self.assertEqual(Path(point['path']).parent, Path(point['generation_directory']))
                        self.assertIn(Path(point['path']).name, point['cache_filenames'])
                        self.assertTrue(Path(point['path']).is_file())
                        self.assertTrue(point['read_only'])
                        audit = json.loads(Path(point['audit_record']['path']).read_text())
                        self.assertIn('audit_input_sha256', audit)
                        identity = json.loads(Path(point['cache_identity_record']['path']).read_text())
                        if point['source_schema_version']==3:
                            self.assertEqual(len(identity['working_points']), 1)
                            self.assertNotIn('physical_samples', identity['geometry'])
                from integrations.workflows.single_reflection_flight.runtime import _frontend_fields
                actual_design = json.loads((root/('hit' if fine_change or legacy_partial or audit_refresh else 'run')/'inputs/frontend_field_design.json').read_text())
                if case == 'first':
                    actual_design = json.loads((run/'inputs/frontend_field_design.json').read_text())
                _frontend_fields(Path(data[case]['cache_receipt']), actual_design)
                self.assertFalse(receipt['fly_performed'])
            self.assertFalse(any(path.name == 'build-scratch' for path in (root / 'cache/.transactions').rglob('*')))


if __name__ == '__main__':
    unittest.main()
