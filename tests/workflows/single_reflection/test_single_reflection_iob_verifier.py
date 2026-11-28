"""Current SIMION field validators and IOB verifier retain real Lua fixtures."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from msplatform.execution.resources import resource_path
from msplatform.backends.simion.source import lua_value as _lua_value
from msplatform.backends.simion.field_validation import interface_field_probes, native_priority_occupancy_probes
from tests.workflows.single_reflection.test_single_reflection_geometry import (
    candidate_300mm_fixture, multipole_source, scientific_inputs,
)

ROOT = Path(__file__).resolve().parents[3]
LUA = Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")
BUILDER = ROOT / "src/msplatform/backends/simion/resources/build_iob.lua"


class NativePriorityOccupancyProbeTests(unittest.TestCase):
    def setUp(self):
        self.geometry = dict(accelerator_projection=dict(negative_x_face_mm=1., shield_wall_mm=2.,
            port_center_y_mm=3., port_center_z_mm=2., numerical_port_width_mm=2., numerical_port_height_mm=2.))
        self.design = dict(surface="none", domains=[
            dict(domain_id="parent", instance_origin_mm=dict(x=0., y=0., z=0.),
                 cell_mm_xyz=dict(x=1., y=2., z=1.),
                 dimensions=dict(nx=11, ny=6, nz=11),
                 bounds_mm=dict(x_min=0., x_max=10., y_min=0., y_max=10., z_min=0., z_max=10.),
                 physical_samples=[dict(label="repeller_metal", kind="endpoint", electrode_id=12, gu=[3, 2, 2]),
                                   dict(label="ring_metal", kind="ring", electrode_id=16, gu=[3, 4, 7])]),
            dict(domain_id="entrance_refinement", instance_origin_mm=dict(x=0., y=2., z=0.),
                 cell_mm_xyz=dict(x=.5, y=.5, z=.5),
                 dimensions=dict(nx=21, ny=13, nz=11),
                 bounds_mm=dict(x_min=0., x_max=10., y_min=2., y_max=8., z_min=0., z_max=5.),
                 active_bounds_mm=dict(x_min=.5, x_max=9.5, y_min=2.5, y_max=7.5, z_min=.5, z_max=4.5),
                 physical_samples=[dict(label="repeller_metal", kind="endpoint", electrode_id=12, gu=[6, 2, 4])])])

    def test_frozen_named_samples_preserve_identity_and_numerical_transition_basis(self):
        probes = {row['label']: row for row in native_priority_occupancy_probes(self.geometry, self.design)}
        self.assertEqual(probes['parent:repeller_metal']['point_mm'], [3., 4., 2.])
        self.assertEqual(probes['parent:repeller_metal']['expected_instance'], 5)
        self.assertEqual(probes['parent:ring_metal']['expected_instance'], 3)
        fine = probes['entrance_refinement:repeller_metal']
        self.assertEqual(fine['point_mm'], [3., 3., 2.])
        self.assertEqual(fine['basis']['electrode_id'], 12)
        self.assertNotIn('expected_electrode', fine)
        self.assertTrue(fine['expected_adjacent_metal_cell'])
        self.assertTrue(fine['expected_node_electrode'])
        self.assertEqual(probes['fine_y_min_inside']['point_mm'], [5., 2.5, 2.5])
        self.assertEqual(probes['fine_y_min_outside']['point_mm'], [5., 1., 2.5])
        self.assertEqual(probes['fine_y_min_outside']['expected_instance'], 3)
        self.assertEqual(probes['fine_z_max_inside']['expected_instance'], 5)
        opening = probes['provider_side_opening_center']
        self.assertEqual(opening['point_mm'], [2., 3., 2.])
        self.assertNotIn('expected_electrode', opening)

    def test_ideal_sheets_keep_source_node_checks_and_boundary_world_queries_are_observations(self):
        parent, fine = self.design['domains']
        parent['physical_samples'] += [
            dict(label='ideal_grid', kind='ideal_sheet', electrode_id=13, gu=[3, 2, 3]),
            dict(label='exit_sheet', kind='ideal_sheet', electrode_id=15, gu=[3, 2, 10]),
            dict(label='fine_face_metal', kind='ring', electrode_id=17, gu=[3, 1, 2])]
        fine['physical_samples'].append(dict(label='outer_metal', kind='ground', electrode_id=11, gu=[0, 2, 4]))
        before = copy.deepcopy(self.design)
        probes = {row['label']: row for row in native_priority_occupancy_probes(self.geometry, self.design)}
        sheet = probes['parent:ideal_grid']
        self.assertNotIn('expected_electrode', sheet)
        self.assertNotIn('expected_adjacent_metal_cell', sheet)
        self.assertEqual(sheet['expected_instance'], 5)
        self.assertTrue(sheet['expected_node_electrode'])
        self.assertEqual(sheet['basis']['sample_kind'], 'ideal_sheet')
        for label in ('parent:exit_sheet', 'parent:fine_face_metal', 'entrance_refinement:outer_metal'):
            with self.subTest(label=label):
                probe = probes[label]
                self.assertTrue(probe['expected_node_electrode'])
                self.assertNotIn('expected_instance', probe)
                self.assertNotIn('expected_electrode', probe)
                self.assertEqual(probe['basis']['world_query_scope'], 'numerical_boundary_observation')
        self.assertEqual(len([row for row in probes.values() if row.get('expected_node_electrode')]), 7)
        self.assertEqual(self.design, before)

    def test_parent_volume_uses_active_coverage_but_raw_instance_query_keeps_raw_bounds(self):
        parent, fine = self.design['domains']
        for y, masked in ((4., True), (2., False), (2.5, False), (8., False)):
            with self.subTest(y=y):
                parent['cell_mm_xyz']['y'] = .5
                parent['dimensions']['ny'] = 21
                parent['physical_samples'][0]['gu'][1] = y / .5
                probes = {row['label']: row for row in native_priority_occupancy_probes(self.geometry, self.design)}
                probe = probes['parent:repeller_metal']
                self.assertEqual('expected_adjacent_metal_cell' not in probe, masked)
                if y == 2.5:
                    self.assertEqual(probe['expected_instance'], 5)
        parent['physical_samples'][0]['gu'][1] = 8
        for field, value in (('label', 'other'), ('kind', 'ideal_sheet'), ('electrode_id', 99)):
            changed = copy.deepcopy(self.design)
            changed['domains'][1]['physical_samples'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'lacks its fine physical sample'):
                native_priority_occupancy_probes(self.geometry, changed)
        fine['physical_samples'] = []
        with self.assertRaisesRegex(ValueError, 'lacks its fine physical sample'):
            native_priority_occupancy_probes(self.geometry, self.design)

    def test_fractional_surface_requires_its_own_volume_contract(self):
        self.design['surface'] = 'fractional'
        with self.assertRaisesRegex(ValueError, 'surface=none'):
            native_priority_occupancy_probes(self.geometry, self.design)

    def test_terminal_cell_neighbors_remain_observations_without_object_attribution(self):
        terminal = dict(particle_id=77, instance=5., x_mm=3., y_mm=3., z_mm=2., instrument_time_us=9.)
        original = dict(terminal)
        probes = native_priority_occupancy_probes(self.geometry, self.design, terminal_observations=[terminal])
        terminal_probes = [row for row in probes if row['label'].startswith('terminal_')]
        self.assertEqual(len(terminal_probes), 7)
        self.assertEqual(terminal_probes[0]['point_mm'], [3., 3., 2.])
        self.assertEqual(terminal_probes[1]['point_mm'], [2.5, 3., 2.])
        self.assertEqual(terminal_probes[-1]['point_mm'], [3., 3., 2.5])
        for row in terminal_probes:
            self.assertNotIn('expected_electrode', row)
            self.assertNotIn('expected_instance', row)
            self.assertNotIn('expected_node_electrode', row)
            self.assertEqual(row['basis']['particle_id'], 77)
        self.assertEqual(terminal, original)

@unittest.skipUnless(LUA.is_file(), "plain Lua interpreter unavailable")
class FourSlotIobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        from msplatform.backends.simion.geometry import compile_frontend_geometry
        self.interface_oatof = candidate_300mm_fixture()
        upstream = multipole_source('octupole')
        options, _ = scientific_inputs({'multipole':upstream}, self.interface_oatof, self.root/'providers')
        _, self.geometry = compile_frontend_geometry({'multipole':upstream}, self.interface_oatof, **options)
        self.rows = []
        domains = {"flight_tube" if r["role"] == "flight_tube_shield" else r["role"]: r
                   for r in self.geometry["downstream_pa_instances"]}
        for index, role in enumerate(("flight_tube", "reflectron", "accelerator", "detector"), 1):
            if role == "accelerator":
                grid = dict(self.geometry["numerical_domains"]["parent"]["dimensions"])
                grid.update({f"d{a}_mm": self.geometry["numerical_domains"]["parent"]["cell_mm_xyz"][a] for a in "xyz"})
                placement = {f"{a}_mm": self.geometry["numerical_domains"]["parent"]["instance_origin_mm"][a] for a in "xyz"}
                placement["az_deg"] = 0.
            else:
                row = domains[role]
                grid = {key: row[key] for key in ("nx", "ny", "nz")}
                numerical = row["grid_numerics"]
                pitches = ([numerical["cell_xy_mm"], numerical["cell_xy_mm"], numerical["cell_z_mm"]]
                           if role == "detector" else
                           [numerical["cell_axial_mm"], numerical["cell_radial_mm"], numerical["cell_radial_mm"]])
                grid.update(dict(zip(("dx_mm", "dy_mm", "dz_mm"), pitches, strict=True)))
                placement = {key: row[key] for key in ("x_mm", "y_mm", "z_mm", "az_deg")}
            placement.update(el_deg=0., rt_deg=0., scale=1.)
            self.rows.append(dict(role=role, instance_index=index, priority_number=index, path=(self.root / (role + ".pa")).as_posix(),
                                  grid=grid, placement=placement))
        self.output = self.root / "instrument.iob"
        self.program = self.output.with_suffix(".lua")
        self.particles = self.output.with_suffix(".fly2")
        self.program.write_bytes(b"EXACT_PREPARED_PROGRAM\n")
        self.particles.write_bytes(b"EXACT_PROJECTED_PARTICLES\n")

    def invoke(self, mode="success", *, execution_root=None):
        self._invocation_index = getattr(self, "_invocation_index", 0) + 1
        seed_directory = self.root / f"seed_{self._invocation_index}"
        seed_directory.mkdir()
        responses = [dict(domain="parent" if row["role"] == "accelerator" else row["role"],
                          kind=kind, path=(self.root / (row["role"] + "." + kind + ".pa")).as_posix(), grid=row["grid"])
                     for row in self.rows if row["role"] in {"accelerator", "entrance_refinement"}
                     for kind in ("rf_reference", "pulse_delta")]
        spec = dict(schema_version=1, role="single_reflection_iob_build", instances=self.rows,
                    response_fields=responses,
                    interface_field_probes=interface_field_probes(self.geometry, self.interface_oatof),
                    native_priority_occupancy_probes=[
                        dict(label="known_metal", point_mm=[0., 0., 0.], expected_instance=3, expected_electrode=True,
                             expected_node_electrode=True, expected_adjacent_metal_cell=True, basis=dict(kind='resolved_physical_sample',
                                 domain_id='parent', sample_kind='endpoint', gu=[7, 8, 9])),
                        dict(label="known_vacuum", point_mm=[1., 0., 0.], expected_instance=3, expected_electrode=False),
                        dict(label="terminal_observation", point_mm=[2., 0., 0.])],
                    seed_iob=(seed_directory / f"{len(self.rows)}_instance_seed.iob").as_posix(),
                    bootstrap_paths=[(seed_directory / f"iob_seed_placeholder_{i:02d}.pa0").as_posix()
                                     for i in range(1, len(self.rows) + 1)], output_iob=self.output.as_posix())
        self.bootstrap_paths = [Path(path) for path in spec["bootstrap_paths"]]
        if mode == "bootstrap_missing":
            spec.pop("bootstrap_paths")
        elif mode == "bootstrap_wrong_count":
            spec["bootstrap_paths"].pop()
        elif mode == "bootstrap_wrong_path":
            spec["bootstrap_paths"][0] = (self.root / "outside.pa0").as_posix()
        elif mode == "bootstrap_preexisting":
            self.bootstrap_paths[0].write_bytes(b"EXISTING_OWNED_FIXTURE_NOT_PA")
        elif mode == "bootstrap_ambient_hook":
            Path(spec["seed_iob"]).with_suffix(".lua").write_bytes(b"AMBIENT_HOOK_MUST_NOT_RUN")
        first_probe = spec['native_priority_occupancy_probes'][0]
        if mode in {'verify_source_fine', 'verify_crop_fine_layer'}:
            first_probe['basis']['domain_id'] = 'entrance_refinement'
        if mode in {'verify_source_sheet', 'verify_source_sheet_missing'}:
            first_probe['basis']['sample_kind'] = 'ideal_sheet'
            first_probe['expected_electrode'] = False
            first_probe.pop('expected_adjacent_metal_cell')
        if mode in {'verify_source_boundary', 'verify_source_boundary_missing'}:
            first_probe.pop('expected_instance')
            first_probe.pop('expected_electrode')
            first_probe['basis']['world_query_scope'] = 'numerical_boundary_observation'
        if mode == 'verify_crop_fine_layer':
            first_probe['expected_instance'] = 5
        if mode.startswith('verify_crop_'):
            # Exact 3x3x3 flag patterns observed in native 132337, with the
            # original world queries retained; different metal IDs are allowed.
            second = mode == 'verify_crop_e44'
            first_probe.update(point_mm=[-193.36362184380704 if second else -277.86362184380704,
                                         15.5 if second else 12.5, -18.429186803411028])
            first_probe.pop('expected_electrode')
            first_probe['basis']['gu'] = [3 if second else 2, 2, 2]
            g = first_probe['basis']['gu']
            spec['fixture_nodes'] = {}
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        metal = dx <= 0
                        if mode in {'verify_crop_layer', 'verify_crop_fine_layer'}:
                            metal = dx == 0
                        if mode == 'verify_crop_node_missing' and (dx,dy,dz) == (0,0,0):
                            metal = False
                        value = (10 if second and dx == -1 else 44 if second else 9) if metal else 0
                        spec['fixture_nodes'][f'n_{g[0]+dx}_{g[1]+dy}_{g[2]+dz}'] = [value, metal]
        if mode == 'verify_missing_probes':
            spec.pop('native_priority_occupancy_probes')
        if mode == 'verify_missing_interfaces':
            spec.pop('interface_field_probes')
        if mode in {'verify_interface_endpoint_roundoff', 'verify_interface_outside'}:
            # Exact frozen 093627 endpoint arithmetic: 1 ULP above nz-1.
            self.rows[2]['placement']['z_mm'] = -41.929186803411028
            self.rows[2]['grid'].update(nz=3201, dz_mm=.1)
            for point in spec['interface_field_probes'][0]['points_mm']:
                point[2] = 278.07081319658903 + (1e-6 if mode.endswith('outside') else 0.)
        spec_path = self.root / "build_spec.lua"
        spec_path.write_text("return " + _lua_value(spec) + "\n", encoding="utf-8")
        mock = self.root / "mock.lua"
        mock.write_text("""local spec=dofile(arg[1])
local builder,mode=arg[2],arg[3]
local projected=arg[4]~=nil
local canonical_paths={}
if projected then
 local native_path=assert(loadfile(arg[4]))()
 spec.seed_iob=native_path(spec.seed_iob);spec.output_iob=native_path(spec.output_iob)
 for i,path in ipairs(spec.bootstrap_paths) do spec.bootstrap_paths[i]=native_path(path) end
 for index,row in ipairs(spec.instances) do canonical_paths[index]=row.path;row.path=native_path(row.path) end
 for _,row in ipairs(spec.response_fields) do row.path=native_path(row.path) end
end
local calls=0
simion={wb={instances={}},pas={}}
local reference_closed=false
local response_active=false
local response_closed=0
local probe_calls=0
local bootstrap_created=0
local function fixture_pa_path(value)
   local parts={}
   for part in value:gsub('\\\\','/'):gmatch('[^/]+') do
    if part=='..' then assert(#parts>0);table.remove(parts)
    elseif part~='.' then parts[#parts+1]=part end
   end
   return (value:sub(1,1)=='/' and '/' or '')..table.concat(parts,'/')
end
function simion.wb:find_at(x,y,z)
 assert(calls==1 and reference_closed,'native points must query the independently reopened IOB')
 probe_calls=probe_calls+1
 local probe=assert(spec.native_priority_occupancy_probes[probe_calls])
 assert(x==probe.point_mm[1] and y==probe.point_mm[2] and z==probe.point_mm[3],'probe coordinates changed')
 if mode=='verify_outside' and probe_calls==2 then return end
 local electrode=probe_calls==1
 local instance=probe_calls==3 and 5 or 3
 if (mode=='verify_priority' or mode=='verify_crop_priority') and probe_calls==1 then instance=2 end
 if mode:match('^verify_crop_') and probe_calls==1 then electrode=false end
 if mode=='verify_crop_fine_layer' and probe_calls==1 then instance=5 end
 if mode=='verify_electrode' and probe_calls==2 then electrode=true end
 if mode=='verify_numeric_electrode' and probe_calls==1 then electrode=1 end
 if mode=='verify_observed_metal' and probe_calls==3 then electrode=true end
 if mode:match('^verify_source_') and probe_calls==1 then electrode=false;instance=2 end
 if mode=='verify_source_node_missing' and probe_calls==1 then electrode=true;instance=3 end
 if (mode=='verify_source_sheet' or mode=='verify_source_sheet_missing') and probe_calls==1 then electrode=false;instance=3 end
 if (mode=='verify_source_boundary' or mode=='verify_source_boundary_missing') and probe_calls==1 then electrode=false;instance=1 end
 return electrode,instance,nil
end
if mode=='verify_nil_point_hook' then simion.wb.find_at=nil end
function simion.pas:open(...)
 if not mode:match('^verify') and calls==0 and bootstrap_created<#spec.bootstrap_paths then
  local pa={}
  function pa:size(x,y,z) assert(x==3 and y==3 and z==3,'bootstrap dimensions changed');self.nx,self.ny,self.nz=x,y,z end
  function pa:save(path)
   bootstrap_created=bootstrap_created+1
   assert(path==spec.bootstrap_paths[bootstrap_created],'bootstrap path/order changed')
   assert(self.symmetry=='3dplanar' and self.potential_type=='electric','bootstrap type changed')
   assert(self.dx_mm==1 and self.dy_mm==1 and self.dz_mm==1,'bootstrap pitch changed')
   local f=assert(io.open(path,'wb'));f:write('INERT_NEUTRAL_BOOTSTRAP_NOT_NATIVE_PA');f:close()
  end
  function pa:close() end
  return pa
 end
 if select('#',...)==1 then
  assert(mode:match('^verify') and calls==0,'responses must load before the saved IOB')
  assert(not response_active,'responses must not coexist in memory')
  local path=...
  if mode=='verify_response_missing' then error('inert response path missing: '..path) end
  local row=assert(spec.response_fields[response_closed+1])
  assert(row.path==path,'actual response path changed')
  local pa={}
  for key,value in pairs(row.grid) do pa[key]=value end
  function pa:point() return 0,true end
  function pa:potential_vc(x,y,z)
   if mode=='verify_interface_endpoint_roundoff' or mode=='verify_interface_outside' then
    assert(z<=self.nz-1,'fixture z outside PA')
   end
   return mode=='verify_interface_response' and 1 or 0
  end
  function pa:inside_vc() return true end
  function pa:field_vc() return 0,0,17 end
  if mode=='verify_response_grid' then pa.dx_mm=pa.dx_mm*2 end
  response_active=true
  function pa:close() assert(response_active);response_active=false;response_closed=response_closed+1 end
  return pa
 end
 assert(select('#',...)==0,'path reference must be unloaded')
 local values={}
 local reference={}
 function reference:close() reference_closed=true end
 function reference:load() error('path comparison cannot load PA bytes') end
 return setmetatable(reference,{
  __newindex=function(_,key,value)
   assert(key=='path')
   values.path=fixture_pa_path(value)
  end,
  __index=values,
 })
end
function simion.pas:close() assert(calls==1,'bootstrap cleanup before saved workbench') end
function simion.command(command)
 print('FIXTURE_WORKBENCH_LOAD')
 calls=calls+1
 local verifying=mode:match('^verify')~=nil
 if verifying then assert(not response_active and response_closed==#spec.response_fields,'responses were not all closed') end
 assert(command=='"'..(verifying and spec.output_iob or spec.seed_iob)..'"','wrong workbench input')
 for index,row in ipairs(spec.instances) do
  local pa={}
  pa.path=fixture_pa_path(spec.bootstrap_paths[index])
  pa.nx,pa.ny,pa.nz=3,3,3
  if mode=='bootstrap_wrong_loaded_path' then pa.path='UNDECLARED_AUTHOR_PA' end
  if mode=='bootstrap_wrong_loaded_grid' then pa.nx=4 end
  function pa:load()
   print('FIXTURE_SLOT_LOAD')
   assert(self.filename==row.path,'wrong PA source')
   self.path=fixture_pa_path(self.filename)
   for k,v in pairs(row.grid) do self[k]=v end
   if mode=='wrong_grid' and index==2 then self.nx=self.nx+1 end
  end
  simion.wb.instances[index]={pa=pa,_debug_update_size=function() end}
  if verifying then
   pa.path=projected and canonical_paths[index] or row.path;pa.filename=row.path:match('[^/]+$')
   if mode=='verify_dot_path' then
    pa.path=row.path:gsub('/([^/]+)$','/extra/.././%1')
   end
   for k,v in pairs(row.grid) do pa[k]=v end
   local item=simion.wb.instances[index];local p=row.placement
   item.x,item.y,item.z=p.x_mm,p.y_mm,p.z_mm
   item.az,item.el,item.rt,item.scale=p.az_deg,p.el_deg,p.rt_deg,p.scale
   function pa:point(x,y,z)
    if z==1000 or index==2 then return 0,mode~='verify_interface_metal' end
    assert(index==((mode=='verify_source_fine' or mode=='verify_crop_fine_layer') and 5 or 3),'wrong physical-sample source instance')
    local probe=spec.native_priority_occupancy_probes[1]
    if spec.fixture_nodes then
     local value=assert(spec.fixture_nodes['n_'..x..'_'..y..'_'..z],'fixture queried beyond observed neighborhood')
     return value[1],value[2]
    end
    assert(x>=6 and x<=8 and y>=7 and y<=9 and z>=8 and z<=10,'source neighborhood changed')
    return 4372.125,not (mode=='verify_source_node_missing' or mode=='verify_source_sheet_missing' or mode=='verify_source_boundary_missing')
   end
   function item:wb_to_pa_coords(x,y,z)
    if z~=0 then return 1000,1000,1000 end
    if spec.fixture_nodes then return unpack(spec.native_priority_occupancy_probes[1].basis.gu) end
    assert(x==0 and y==0 and z==0,'diagnostic world point moved')
    return .25,-1.5,2.75
   end
   function item:pa_to_wb_coords(x,y,z)
    if spec.fixture_nodes then return unpack(spec.native_priority_occupancy_probes[1].point_mm) end
    assert(x==7 and y==8 and z==9,'diagnostic source node moved')
    return 17.125,18.25,19.5
   end
   function item:inside_wc(x,y,z)
    if spec.fixture_nodes then return true end
    assert(x==0 and y==0 and z==0,'inside query moved')
    return mode=='verify_source_parent'
   end
   function pa:load() error('verify cannot reload or replace a PA') end
   function pa:potential_vc() return mode=='verify_interface_potential' and 1 or 0 end
   function pa:inside_vc() return true end
   function pa:field_vc()
    if mode=='verify_interface_nonfinite' then return 0/0,0,0 end
    return index==2 and 2.5 or 0,0,index==3 and 23 or 0
   end
   function item:pa_to_wb_orient(x,y,z) if index==2 then return -z,y,x end return x,y,z end
   if index==5 and mode=='verify_fine_grid' then pa.nx=pa.nx+1 end
   if index==2 then
    if mode=='verify_grid' then pa.nx=pa.nx+1 end
    if mode=='verify_pose' then item.x=item.x+1 end
    if mode=='verify_path' then pa.path='C:/other.pa' end
    if mode=='verify_same_basename' then pa.path='C:/other/'..row.path:match('[^/]+$') end
   end
  end
 end
 if mode=='wrong_slots' then simion.wb.instances[#spec.instances+1]={} end
end
function simion.wb:load_particles(path)
 assert(path==spec.output_iob:gsub('%.iob$','.fly2'))
end
function simion.wb:save(path)
 assert(path==spec.output_iob and calls==1)
 for index,row in ipairs(spec.instances) do
  local item=self.instances[index];local p=row.placement
  assert(item.pa.filename==row.path)
  assert(item.x==p.x_mm and item.y==p.y_mm and item.z==p.z_mm)
  assert(item.az==p.az_deg and item.el==p.el_deg and item.rt==p.rt_deg and item.scale==p.scale)
  assert(item.nz_use==nil,'cylindrical PA must not acquire planar extrusion')
 end
 for _,extension in ipairs({'.lua','.fly2'}) do
  local f=assert(io.open(path:gsub('%.iob$',extension),'wb'));f:write('SEED_OVERWRITE');f:close()
 end
 if mode=='save_failure' then error('inert save failure') end
 local f=assert(io.open(path,'wb'));f:write('INERT_IOB_NOT_NATIVE');f:close()
end
arg={arg[1],mode:match('^verify') and 'verify' or nil}
dofile(builder)
if mode:match('^verify') then assert(reference_closed,'temporary path reference was not closed') end
""", encoding="utf-8", newline="\n")
        arguments = [str(LUA), str(mock), str(spec_path), str(BUILDER), mode]
        environment = None
        if execution_root is not None:
            arguments.append(str(resource_path("native_run_path.lua")))
            environment = dict(os.environ, MASS_SPECTROMETRY_RUN_DIRECTORY=str(self.root),
                MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=str(execution_root))
        return subprocess.run(arguments, env=environment,
                              cwd=self.root, capture_output=True, text=True, timeout=20)

    def test_declared_neutral_bootstrap_is_removed_only_after_successful_real_slot_binding(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.bootstrap_paths), 4)
        self.assertTrue(all(not path.exists() for path in self.bootstrap_paths))
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")
        self.output.unlink()
        failed = self.invoke("wrong_grid")
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertTrue(all(path.read_bytes() == b"INERT_NEUTRAL_BOOTSTRAP_NOT_NATIVE_PA" for path in self.bootstrap_paths))

    def test_bootstrap_count_path_and_ambient_payload_fail_before_workbench_load(self):
        for mode, message in (("bootstrap_missing", "explicit private bootstrap PA paths required"),
                              ("bootstrap_wrong_count", "explicit private bootstrap PA paths required"),
                              ("bootstrap_wrong_path", "distinct seed-local placeholder names"),
                              ("bootstrap_preexisting", "bootstrap placeholder already exists"),
                              ("bootstrap_ambient_hook", "seed has an unexpected source/Program companion")):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn("FIXTURE_WORKBENCH_LOAD", result.stdout)
                self.assertFalse(self.output.exists())
        for mode in ("bootstrap_wrong_loaded_path", "bootstrap_wrong_loaded_grid"):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FIXTURE_WORKBENCH_LOAD", result.stdout)
                self.assertNotIn("FIXTURE_SLOT_LOAD", result.stdout)
                self.assertFalse(self.output.exists())

    def test_missing_native_point_hook_rejects_verify_without_mutation_or_save(self):
        result = self.invoke("verify_nil_point_hook")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("find_at", result.stderr)
        self.assertNotIn("SINGLE_REFLECTION_IOB_REOPEN=PASS", result.stdout)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows execution junction required")
    def test_wrapper_projects_declared_paths_and_core_reopens_canonical_saved_paths(self):
        alias = self.root.parent / (self.root.name + "_execution")
        script = "& { param($Alias,$Target) New-Item -ItemType Junction -Path $Alias -Target $Target | Out-Null }"
        created = subprocess.run(["pwsh", "-NoProfile", "-Command", script, str(alias), str(self.root)],
            cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.addCleanup(alias.rmdir)
        external = (self.root.parent / "external_standalone.pa").as_posix()
        self.rows[1]["path"] = external
        built = self.invoke(execution_root=alias)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        self.output.unlink()  # Inert fixture IOB only; verify must never save one.
        reopened = self.invoke("verify_success", execution_root=alias)
        self.assertEqual(reopened.returncode, 0, reopened.stdout + reopened.stderr)
        self.assertIn("SINGLE_REFLECTION_IOB_REOPEN=PASS", reopened.stdout)
        self.assertFalse(self.output.exists())
        frozen_spec = (self.root / "build_spec.lua").read_text()
        self.assertNotIn(alias.name, frozen_spec)
        self.assertIn(external, frozen_spec)
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")


    def test_four_physical_slots_keep_provider_pose_and_prepared_companions(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INSTANCES=4", result.stdout)
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")

    def test_fifth_numerical_domain_uses_public_seed_and_reopens_exact_grid(self):
        fine = copy.deepcopy(self.rows[2])
        fine.update(role="entrance_refinement",instance_index=5,priority_number=5,
                    path=(self.root / "frontend_entrance_refinement.carrier_off.pa").as_posix())
        # Inert IOB API fixture: same envelope, finer cells; no native field claim.
        for axis in "xyz":
            fine["grid"]["n"+axis] = 2*fine["grid"]["n"+axis]-1
            fine["grid"]["d"+axis+"_mm"] /= 2
        self.rows.append(fine)
        result = self.invoke()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("INSTANCES=5",result.stdout)
        reopened = self.invoke("verify_success")
        self.assertEqual(reopened.returncode,0,reopened.stdout+reopened.stderr)
        self.assertIn("entrance_refinement FLY=False",reopened.stdout)
        wrong = self.invoke("verify_fine_grid")
        self.assertNotEqual(wrong.returncode,0)
        self.assertIn("saved PA grid differs: entrance_refinement",wrong.stdout+wrong.stderr)
        self.assertEqual(self.program.read_bytes(),b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(),b"EXACT_PROJECTED_PARTICLES\n")

    def test_failed_physical_sample_records_native_source_node_without_accepting_mismatch(self):
        fine = copy.deepcopy(self.rows[2])
        fine.update(role='entrance_refinement', instance_index=5, priority_number=5,
                    path=(self.root / 'fine.carrier_off.pa').as_posix())
        self.rows.append(fine)
        for mode, instance, inside in (('verify_source_parent', 3, 'true'),
                                       ('verify_source_fine', 5, 'false')):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('native priority/occupancy point mismatch: known_metal', result.stderr)
                self.assertNotIn('NATIVE_PRIORITY_OCCUPANCY=PASS', result.stdout)
                self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_POINT '), 3)
                self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_SOURCE_NODE '), 1)
                self.assertIn(f'source_instance={instance} gu_x=7 gu_y=8 gu_z=9', result.stdout)
                self.assertIn('node_voltage_v=4372.125 node_electrode=true', result.stdout)
                self.assertIn('world_to_pa_x_gu=0.25 world_to_pa_y_gu=-1.5 world_to_pa_z_gu=2.75', result.stdout)
                self.assertIn('node_world_x_mm=17.125 node_world_y_mm=18.25 node_world_z_mm=19.5', result.stdout)
                self.assertIn(f'inside_source={inside} selected_instance=2', result.stdout)
                self.assertIn('terminal_observation', result.stdout)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.program.read_bytes(), b'EXACT_PREPARED_PROGRAM\n')
                self.assertEqual(self.particles.read_bytes(), b'EXACT_PROJECTED_PARTICLES\n')

    def test_integer_nodes_remain_required_for_metal_ideal_sheets_and_boundary_observations(self):
        for mode, accepted in (('verify_source_node_missing', False),
                               ('verify_source_sheet', True), ('verify_source_sheet_missing', False),
                               ('verify_source_boundary', True), ('verify_source_boundary_missing', False)):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                line = next(row for row in result.stdout.splitlines()
                            if row.startswith('SINGLE_REFLECTION_NATIVE_POINT label="known_metal"'))
                self.assertIn(f'source_node_electrode={str(accepted).lower()} expected_node_electrode=true', line)
                self.assertIn('check=' + ('pass' if accepted else 'failed'), line)
                if 'boundary' in mode:
                    self.assertIn('electric_instance=1', line)
                    self.assertIn('expected_electrode=nil expected_instance=nil', line)
                if accepted:
                    self.assertIn('NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2 OBSERVED=1', result.stdout)
                    self.assertNotIn('SINGLE_REFLECTION_NATIVE_SOURCE_NODE', result.stdout)
                else:
                    self.assertIn('native priority/occupancy point mismatch: known_metal', result.stderr)
                    self.assertNotIn('NATIVE_PRIORITY_OCCUPANCY=PASS', result.stdout)
                self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_POINT '), 3)
                self.assertFalse(self.output.exists())

    def test_recorded_crop_nodes_require_adjacent_volume_without_moving_world_queries(self):
        for mode in ('verify_crop_e9','verify_crop_e44','verify_crop_layer',
                     'verify_crop_node_missing','verify_crop_priority'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                accepted = mode in {'verify_crop_e9','verify_crop_e44'}
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                line = next(row for row in result.stdout.splitlines()
                            if row.startswith('SINGLE_REFLECTION_NATIVE_POINT label="known_metal"'))
                self.assertIn('electrode=false', line)
                self.assertIn('expected_electrode=nil', line)
                self.assertIn('adjacent_metal_cells=' + ('4' if accepted or mode == 'verify_crop_priority' else '0'), line)
                self.assertIn('check=' + ('pass' if accepted else 'failed'), line)
                if accepted:
                    self.assertIn('SINGLE_REFLECTION_IOB_REOPEN=PASS',result.stdout)
                else:
                    self.assertIn('native priority/occupancy point mismatch',result.stderr)
                self.assertFalse(self.output.exists())

    def test_fine_nonideal_metal_cannot_use_an_isolated_node_sheet_as_volume(self):
        fine = copy.deepcopy(self.rows[2])
        fine.update(role='entrance_refinement', instance_index=5, priority_number=5,
                    path=(self.root / 'fine.carrier_off.pa').as_posix())
        self.rows.append(fine)
        result = self.invoke('verify_crop_fine_layer')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('source_instance=5', result.stdout)
        self.assertIn('adjacent_metal_cells=0', result.stdout)
        self.assertIn('native priority/occupancy point mismatch', result.stderr)

    def test_wrong_grid_or_seed_slot_count_fails_before_iob_save(self):
        for mode in ("wrong_grid", "wrong_slots"):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_failed_iob_save_restores_exact_program_and_particles(self):
        result = self.invoke("save_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inert save failure", result.stderr)
        self.assertEqual(self.program.read_bytes(), b"EXACT_PREPARED_PROGRAM\n")
        self.assertEqual(self.particles.read_bytes(), b"EXACT_PROJECTED_PARTICLES\n")

    def test_independent_reopen_verifies_saved_slots_without_mutating_pa_or_controls(self):
        for mode in ('verify','verify_dot_path','verify_grid','verify_pose','verify_path','verify_same_basename'):
            with self.subTest(mode=mode):
                result=self.invoke(mode)
                self.assertEqual(result.returncode==0,mode in {'verify','verify_dot_path'},result.stdout+result.stderr)
                if mode in {'verify','verify_dot_path'}:
                    self.assertIn('SINGLE_REFLECTION_IOB_REOPEN=PASS',result.stdout)
                self.assertEqual(self.program.read_bytes(),b'EXACT_PREPARED_PROGRAM\n')
                self.assertEqual(self.particles.read_bytes(),b'EXACT_PROJECTED_PARTICLES\n')
                self.assertFalse(self.output.exists(), 'read-only verify must never save a workbench')

    def test_response_paths_load_sequentially_and_grid_or_missing_path_fails_before_iob(self):
        for mode in ('verify_success', 'verify_response_grid', 'verify_response_missing'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result.returncode == 0, mode == 'verify_success', result.stdout + result.stderr)
                if mode == 'verify_success':
                    self.assertEqual(result.stdout.count('SINGLE_REFLECTION_RESPONSE_PATH_GRID=PASS'), 2)
                else:
                    self.assertNotIn('SINGLE_REFLECTION_IOB_REOPEN=PASS', result.stdout)
                    self.assertIn('response grid differs' if mode.endswith('grid') else 'response path missing',
                                  result.stdout + result.stderr)
                self.assertFalse(self.output.exists())

    def test_actual_point_api_checks_priority_and_occupancy_but_never_invents_terminal_expectations(self):
        for mode in ('verify_success', 'verify_observed_metal', 'verify_priority', 'verify_electrode', 'verify_numeric_electrode', 'verify_outside', 'verify_missing_probes'):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                accepted = mode in {'verify_success', 'verify_observed_metal'}
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                if accepted:
                    self.assertIn('NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2 OBSERVED=1 SCOPE=declared_points_only', result.stdout)
                elif mode != 'verify_missing_probes':
                    self.assertEqual(result.stdout.count('SINGLE_REFLECTION_NATIVE_POINT'), 3)
                    self.assertIn('terminal_observation', result.stdout)
                    self.assertIn('native priority/occupancy point mismatch', result.stderr)
                    self.assertNotIn('SINGLE_REFLECTION_IOB_REOPEN=PASS', result.stdout)
                self.assertFalse(self.output.exists())

if __name__ == "__main__":
    unittest.main()
