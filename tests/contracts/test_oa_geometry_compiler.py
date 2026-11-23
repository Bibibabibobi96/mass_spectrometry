"""Standalone OA geometry compilation; no native solver is invoked."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tempfile
import unittest

from msplatform import assembly, components, examples
from msplatform.backends import simion
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.backends.simion.oa_compiler import _extent, _inside, _samples
from msplatform.backends.simion.resources import structural_seed_path
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
from msplatform.io.manifest_records import file_record
from msplatform.execution.inputs import enumerate_python_sources
from msplatform.backends.simion.source import lua_value


def oa_inputs():
    study = examples.load_example('oa_two_three_geometric_v1')
    parts = {name:components.resolve_component(request) for name,request in study.component_requests.items()}
    instrument = assembly.assemble(study.recipe,parts)
    domains = {}
    for name,design in instrument.components_resolved.items():
        extents = [_extent(member['shape']) for member in iter_geometry_members(design)]
        bounds = {axis+suffix:fn(b[i][j] for b in extents)+margin
                  for i,axis in enumerate('xyz')
                  for suffix,j,fn,margin in [('_min',0,min,-1.),('_max',1,max,1.)]}
        domains[name] = dict(cell_mm_xyz=dict(x=.25,y=.25,z=.1),pa_bounds_mm=bounds)
    return instrument,dict(component_domains=domains)


class OaGeometryCompilerTests(unittest.TestCase):
    def test_annular_metal_uses_actual_lattice_not_only_snapped_midpoints(self):
        shape = dict(kind='difference',base=dict(kind='cylinder',center_mm=[0,0,0],radius_mm=10,height_mm=2),
                     tools=[dict(kind='cylinder',center_mm=[0,0,0],radius_mm=9,height_mm=2)])
        member = dict(member_id='annulus',electrode_group_id='g',shape=shape)
        domain = dict(instance_origin_mm=dict(x=-11,y=-11,z=-2),cell_mm_xyz=dict(x=1,y=1,z=1),
                      dimensions=dict(nx=23,ny=23,nz=5))
        self.assertTrue(_inside(shape,[9,1,0]))
        self.assertFalse(_inside(shape,[9,0,0]))
        self.assertFalse(_inside(shape,[10,0,0]))
        result = _samples([member],dict(g=7),domain)
        metal = [row for row in result if row.get('metal') is not False]
        self.assertEqual(len(metal),1)
        self.assertEqual(metal[0]['electrode_id'],7)
        point = [domain['instance_origin_mm'][axis]+metal[0]['gu'][k] for k,axis in enumerate('xyz')]
        self.assertTrue(_inside(shape,point))
        self.assertEqual(domain['cell_mm_xyz'],dict(x=1,y=1,z=1))
        # This narrower annulus truly contains no strict integer lattice node.
        shape['tools'][0]['radius_mm'] = 9.999
        with self.assertRaisesRegex(ValueError,'no actual represented metal/sheet node'):
            _samples([member],dict(g=7),domain)

    def test_frozen_package_contains_real_moved_implementations_without_fallback(self):
        repo = Path(__file__).resolve().parents[2]
        selected = enumerate_python_sources(repo,package_roots=['src/msplatform'],
            provider_root='src/msplatform',resource_suffixes=('.schema.json',))
        names = ['two_zone_candidate','rectangular_accelerator','bare_three_zone_component']
        with tempfile.TemporaryDirectory(prefix='oa-frozen-') as directory:
            root = Path(directory)
            for relative in selected:
                destination = root/relative
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(repo/relative,destination)
            for name in names:
                relative = 'src/msplatform/backends/simion/'+name+'.py'
                self.assertIn(relative,selected)
                self.assertEqual((root/relative).read_bytes(),(repo/relative).read_bytes())
            code = """import importlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);sys.path[:0]=[str(root/'src'),*json.loads(sys.argv[2])]
for name in json.loads(sys.argv[3]):
 module=importlib.import_module('msplatform.backends.simion.'+name)
 assert pathlib.Path(module.__file__).resolve().is_relative_to(root.resolve()),module.__file__
print('FROZEN_OA_ORIGINS=PASS')
"""
            command = [sys.executable,'-I','-S','-B','-c',code,str(root),json.dumps(site.getsitepackages()),json.dumps(names)]
            completed = subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            self.assertIn('FROZEN_OA_ORIGINS=PASS',completed.stdout)
            (root/'src/msplatform/backends/simion/rectangular_accelerator.py').unlink()
            missing = subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertNotEqual(missing.returncode,0)
            self.assertIn('rectangular_accelerator',missing.stderr)

    def test_two_variants_compile_complete_groups_and_real_member_witnesses(self):
        instrument,numerics = oa_inputs()
        original = copy.deepcopy(((instrument.composition_plan,instrument.components_resolved),numerics))
        compiled = simion.compile_geometry(instrument,numerics=numerics)
        self.assertEqual(compiled.frontend_geometry['role'],'simion_independent_oa_geometry')
        self.assertEqual(set(compiled.frontend_gems),{'two','three'})
        self.assertEqual(compiled.downstream_specs,())
        for name,design in instrument.components_resolved.items():
            members = iter_geometry_members(design)
            samples = compiled.frontend_geometry['raw_physical_samples'][name]
            self.assertEqual({s['label'] for s in samples if s.get('metal') is not False},{m['member_id'] for m in members})
            self.assertEqual({s['electrode_id'] for s in samples if s.get('metal') is not False},set(compiled.frontend_geometry['electrode_bindings'][name].values()))
            self.assertEqual({s['label'] for s in samples if s.get('metal') is False},{'physical_cavity','physical_side_opening'})
            self.assertIn('planar,none,electrostatic',compiled.frontend_gems[name])
            self.assertIn('surface=fractional',compiled.frontend_gems[name])
            self.assertNotIn('mirror',compiled.frontend_gems[name])
        self.assertEqual(((instrument.composition_plan,instrument.components_resolved),numerics),original)

    def test_native_namespace_permutation_does_not_change_mechanics(self):
        instrument,numerics = oa_inputs()
        original = simion.compile_geometry(instrument,numerics=numerics)
        numerics['electrode_group_native_ids'] = {name:{group:200-i for i,group in enumerate(mapping)}
            for name,mapping in original.frontend_geometry['electrode_bindings'].items()}
        changed = simion.compile_geometry(instrument,numerics=numerics)
        self.assertEqual(original.components_resolved,changed.components_resolved)
        self.assertEqual(original.frontend_geometry['numerical_domains'],changed.frontend_geometry['numerical_domains'])
        self.assertNotEqual(original.frontend_gems,changed.frontend_gems)
        self.assertEqual(original.provider_content_identities,changed.provider_content_identities)

    def test_single_local_scope_retains_parent_and_uses_one_real_seed(self):
        instrument,numerics = oa_inputs()
        # The public local scope retains and revalidates the complete recipe.
        study = examples.load_example('oa_two_three_geometric_v1')
        parts = {n:components.resolve_component(r) for n,r in study.component_requests.items()}
        local = assembly.assemble(study.recipe,parts,local_scope=dict(instance_ids=['two'],research_scope='raw OA',boundary_assumptions='geometry only'))
        compiled = simion.compile_geometry(local,numerics=dict(component_domains={'two':numerics['component_domains']['two']}))
        self.assertEqual(set(compiled.frontend_gems),{'two'})
        self.assertEqual(len(compiled.frontend_geometry['composition_plan']['recipe']['instances']),2)
        root = Path('C:/oa-plan')
        plan = plan_geometry_build(compiled,run_directory=root,seed_record=file_record(structural_seed_path(1),'required_evidence'),native_path_resource=root/'native_run_path.lua')
        self.assertEqual([op['operation_id'] for op in plan.operations],['geometry_two','build_geometry','verify_geometry'])
        spec = plan.materializations[str(root/'inputs/geometry_iob.lua')]
        self.assertIn('independent_oa_geometry_iob_build',spec)
        self.assertIn('rotation=',spec)
        self.assertIn('fractional_surface=',spec)
        self.assertFalse(root.exists())

    def test_multi_instance_native_pose_translates_local_pa_origin_once(self):
        instrument,numerics = oa_inputs()
        compiled = simion.compile_geometry(instrument,numerics=numerics)
        root = Path('C:/oa-plan')
        plan = plan_geometry_build(compiled,run_directory=root,seed_record=file_record(structural_seed_path(2),'required_evidence'),native_path_resource=root/'native_run_path.lua')
        spec = plan.materializations[str(root/'inputs/geometry_iob.lua')]
        # Original three-zone example: R=[0,-1,0;0,0,1;-1,0,0],
        # t=[0,-2,-18], actual PA origin=[-18,-18,-5] mm.
        expected = dict(x_mm=18.,y_mm=-7.,z_mm=0.,az_deg=90.,el_deg=0.,rt_deg=-90.,scale=1.,ox=0.,oy=0.,oz=0.)
        self.assertIn('placement='+lua_value(expected),spec)
        self.assertEqual([row['operation_id'] for row in plan.operations],
                         ['geometry_two','geometry_three','build_geometry','verify_geometry'])
        self.assertEqual(sum('REFINE' in row['success_marker'] for row in plan.operations),0)

    def test_cylindrical_three_zone_keeps_existing_side_opening_and_ideal_sheets(self):
        study = examples.load_example('oa_two_three_geometric_v1')
        request = copy.deepcopy(study.component_requests['three'])
        request['design']['requirements']['geometry']['cross_section'] = 'cylindrical'
        parts = {name:components.resolve_component(request if name=='three' else source)
                 for name,source in study.component_requests.items()}
        instrument = assembly.assemble(study.recipe,parts)
        _,numerics = oa_inputs()
        compiled = simion.compile_geometry(instrument,numerics=numerics)
        self.assertIn('cylinder(',compiled.frontend_gems['three'].lower())
        self.assertIn('physical_side_opening',{row['label'] for row in compiled.frontend_geometry['raw_physical_samples']['three'] if row.get('metal') is False})
        self.assertEqual(len([m for m in iter_geometry_members(instrument.components_resolved['three'])
                             if m['representation_role']=='ideal_surface']),3)

    def test_grid_bounds_namespace_and_sheet_misalignment_fail_before_execution(self):
        instrument,numerics = oa_inputs()
        invalids = []
        bad = copy.deepcopy(numerics);bad['component_domains']['two']['pa_bounds_mm']['x_min']=0.;invalids.append(bad)
        bad = copy.deepcopy(numerics);bad['component_domains'].pop('three');invalids.append(bad)
        bad = copy.deepcopy(numerics);bad['electrode_group_native_ids']={'two':{'repeller':1}};invalids.append(bad)
        bad = copy.deepcopy(numerics);bad['component_domains']['two']['pa_bounds_mm']['z_min']+=.05;bad['component_domains']['two']['pa_bounds_mm']['z_max']+=.05;invalids.append(bad)
        for bad in invalids:
            with self.subTest(numerics=bad),self.assertRaises(ValueError):
                simion.compile_geometry(instrument,numerics=bad)
