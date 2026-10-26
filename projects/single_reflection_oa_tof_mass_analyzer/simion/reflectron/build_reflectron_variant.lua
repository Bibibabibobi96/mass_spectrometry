-- Build a size-guarded reflectron PA variant from the formal GEM.
-- Usage:
--   simion.exe --nogui lua build_reflectron_variant.lua source.gem output.pa#
--     frozen_oatof_resolved.lua build_mode

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local contract = dofile(assert(arg[3], 'missing frozen resolved Lua'))
local component = assert(contract.physical_geometry, 'missing provider physical geometry').simion.reflectron
local mesh = contract.simion_geometry_build.reflectron
local mmgu_axial, mmgu_radial, max_gib = mesh.cell_axial_mm, mesh.cell_radial_mm, mesh.max_gib
local axial_span, radial_span = component.axial_span_mm, component.outer_radius_mm
local build_mode = assert(arg[4], 'missing build mode')
local electrodes = component.electrodes
local function timed_stage(name,action)
  local started=os.time()
  print(string.format('BUILD_TIMING: stage=%s event=start utc=%s',name,os.date('!%Y-%m-%dT%H:%M:%SZ',started)))
  action()
  local finished=os.time()
  print(string.format('BUILD_TIMING: stage=%s event=complete utc=%s wall_seconds=%d',name,os.date('!%Y-%m-%dT%H:%M:%SZ',finished),finished-started))
end
assert(build_mode == 'refine-all' or build_mode == 'initialize-only' or
  build_mode == 'alignment-only' or build_mode == 'adjust-only',
  'build mode must be refine-all, initialize-only, alignment-only or adjust-only')
assert(source:match('^%a:[/\\]') or source:match('^/'),
  'source GEM path must be absolute')
assert(output:match('^%a:[/\\]') or output:match('^/'),
  'output PA# path must be absolute')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_axial and mmgu_axial > 0,
  'axial_mm_per_gu must be positive')
assert(mmgu_radial and mmgu_radial > 0,
  'radial_mm_per_gu must be positive')
assert(max_gib and max_gib > 0, 'max_GiB must be positive')
local function fast_adjust()
  local values={}
  for _, electrode in ipairs(electrodes) do
    values[electrode.local_electrode_id]=electrode.voltage_v
  end
  local controller=output:gsub('#$','0')
  simion.pas:close()
  local pa=assert(simion.pas:open(controller))
  pa:fast_adjust(values)
  pa:save(controller)
  pa:close()
end
if build_mode == 'adjust-only' then
  fast_adjust()
  print('BUILD: PASS')
  return
end

-- surface=none snaps ordinary thick geometry to raw nodes, so discretization
-- remains visible in the log. Zero-width ideal grids must align exactly.
local aligned_edge_count,off_grid_edge_count,max_abs_offset=0,0,0
local function report_edge(axis,label,value,cell)
  local grid_coordinate=value/cell
  local nearest_grid_coordinate=math.floor(grid_coordinate+0.5)
  local offset=value-nearest_grid_coordinate*cell
  max_abs_offset=math.max(max_abs_offset,math.abs(offset))
  if math.abs(grid_coordinate-nearest_grid_coordinate)<=1e-8 then
    aligned_edge_count=aligned_edge_count+1
  else
    off_grid_edge_count=off_grid_edge_count+1
    print(string.format(
      'WARNING: reflectron_geometry_edge_not_on_grid_node axis=%s label=%s value_mm=%.12g cell_mm=%.12g grid_coordinate=%.12g nearest_node_mm=%.12g offset_mm=%+.12g surface=none action=continue',
      axis,label,value,cell,grid_coordinate,nearest_grid_coordinate*cell,offset))
  end
end
local grids={}
for _, electrode in ipairs(electrodes) do
  for index, region in ipairs(electrode.regions) do
    local label='electrode_'..electrode.local_electrode_id..'_part_'..index
    report_edge('radial',label..'_inner',region.radius_mm[1],mmgu_radial)
    report_edge('radial',label..'_outer',region.radius_mm[2],mmgu_radial)
    report_edge('axial',label..'_front',region.axial_mm[1],mmgu_axial)
    report_edge('axial',label..'_back',region.axial_mm[2],mmgu_axial)
    if region.axial_mm[1] == region.axial_mm[2] then
      local coordinate=region.axial_mm[1]/mmgu_axial
      assert(math.abs(coordinate-math.floor(coordinate+0.5))<=1e-8,
        'zero-width ideal grid must lie on a raw PA row')
      grids[#grids+1]={electrode_id=electrode.local_electrode_id,row=math.floor(coordinate+0.5)}
    end
  end
end
print(string.format(
  'BUILD: grid_alignment aligned_edges=%d off_grid_edges=%d max_abs_offset_mm=%.12g policy=warn_and_continue surface=none',
  aligned_edge_count,off_grid_edge_count,max_abs_offset))
if build_mode == 'alignment-only' then
  print('BUILD: ALIGNMENT_CHECK_PASS')
  return
end

local nx = math.ceil(axial_span/mmgu_axial) + 1
local ny = math.ceil(radial_span/mmgu_radial) + 1
-- Dynamic basis-array estimate including the independent grounded shield.
local estimated_array_factor=#electrodes+2.25
local estimated_gib = nx*ny*8*estimated_array_factor/1024^3
print(string.format(
  'BUILD: dimensions=%dx%dx1 cell_mm=(%.12g,%.12g) span_mm=(%.12g,%.12g) bore_end_mm=%.12g estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,mmgu_axial,mmgu_radial,axial_span,radial_span,
  component.electrodes[#electrodes].regions[2].axial_mm[1],estimated_gib,max_gib))
assert(estimated_gib <= max_gib,
  string.format('estimated PA set %.3f GiB exceeds limit %.3f GiB',
    estimated_gib,max_gib))

local staged_source=output:gsub('%.pa#$','.source.gem')
local input=assert(io.open(source,'rb'))
local content=input:read('*a')
input:close()
local staged=assert(io.open(staged_source,'wb'))
staged:write(content)
staged:close()
_G.var={mmgu_axial=mmgu_axial,mmgu_radial=mmgu_radial,component=component}
timed_stage('gem2pa',function()
  simion.command(string.format('gem2pa %q %q',staged_source,output))
end)
_G.var=nil
os.remove(staged_source)
os.remove(staged_source:gsub('%.gem$','.processed.gem'))
local function audit_raw_grid(electrode_id,label,expected_row)
  simion.pas:close()
  local pa=assert(simion.pas:open(output))
  local rows,point_count={},0
  for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
    local potential,is_electrode=pa:point(x,y,z)
    if is_electrode and math.abs(potential-electrode_id)<1e-9 then
      rows[x]=true; point_count=point_count+1
    end
  end end end
  local row_count,actual_row=0,nil
  for row in pairs(rows) do row_count=row_count+1; actual_row=row end
  pa:close()
  assert(point_count>0,string.format('%s electrode %d has zero raw PA points',label,electrode_id))
  assert(row_count==1,string.format('%s electrode %d occupies %d raw PA rows',label,electrode_id,row_count))
  assert(actual_row==expected_row,string.format('%s electrode %d raw row %d differs from expected %d',label,electrode_id,actual_row,expected_row))
  print(string.format('BUILD: native_grid_raw_pa grid=%s electrode=%d row=%d points=%d',label,electrode_id,actual_row,point_count))
end
timed_stage('raw_grid_audit',function()
  for index, grid in ipairs(grids) do
    audit_raw_grid(grid.electrode_id,index == 1 and 'entgrid' or 'midgrid',grid.row)
  end
end)
if build_mode == 'initialize-only' then
  simion.pas:close()
  local pa=simion.pas:open(output)
  -- Materialize PA0 and every basis PA using SIMION's official default.
  pa:refine{}
  simion.pas:close()
  print('BUILD: INITIALIZED')
  return
end
timed_stage('refine',function()
  simion.command(string.format(
    'refine --resume=0 %q',output))
end)
timed_stage('fastadj',fast_adjust)
print('BUILD: PASS')
