-- Build a size-guarded reflectron PA variant from the formal GEM.
-- Usage:
--   simion.exe --nogui lua build_reflectron_variant.lua source.gem output.pa#
--     axial_mm_per_gu radial_mm_per_gu max_GiB
--     inner_radius_mm wall_mm backplate_front_mm
--     backplate_thickness_mm far_clearance_mm far_cap_mm
--     stage1_length_mm stage2_length_mm bore_radius_mm
--     ring_outer_radius_mm stage1_ring_count stage2_ring_count
--     midgrid_voltage_v backplate_voltage_v

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
assert(arg[19], 'all reflectron geometry, mesh and voltage arguments are required')
local mmgu_axial = assert(tonumber(arg[3]), 'invalid axial cell size')
local mmgu_radial = assert(tonumber(arg[4]), 'invalid radial cell size')
local max_gib = assert(tonumber(arg[5]), 'invalid memory limit')
local inner_radius = assert(tonumber(arg[6]), 'invalid inner radius')
local wall = assert(tonumber(arg[7]), 'invalid wall thickness')
local backplate_front = assert(tonumber(arg[8]), 'invalid backplate front')
local backplate_thickness = assert(tonumber(arg[9]), 'invalid backplate thickness')
local far_clearance = assert(tonumber(arg[10]), 'invalid far clearance')
local far_cap_thickness = assert(tonumber(arg[11]), 'invalid far-cap thickness')
local stage1_length = assert(tonumber(arg[12]), 'invalid stage-1 length')
local stage2_length = assert(tonumber(arg[13]), 'invalid stage-2 length')
local bore_radius = assert(tonumber(arg[14]), 'invalid bore radius')
local ring_outer_radius = assert(tonumber(arg[15]), 'invalid ring outer radius')
local stage1_ring_count = assert(tonumber(arg[16]), 'invalid stage-1 ring count')
local stage2_ring_count = assert(tonumber(arg[17]), 'invalid stage-2 ring count')
local midgrid_voltage = assert(tonumber(arg[18]), 'invalid midgrid voltage')
local backplate_voltage = assert(tonumber(arg[19]), 'invalid backplate voltage')
local build_mode = arg[20] or 'refine-all'
local function timed_stage(name,action)
  local started=os.time()
  print(string.format('BUILD_TIMING: stage=%s event=start utc=%s',name,os.date('!%Y-%m-%dT%H:%M:%SZ',started)))
  action()
  local finished=os.time()
  print(string.format('BUILD_TIMING: stage=%s event=complete utc=%s wall_seconds=%d',name,os.date('!%Y-%m-%dT%H:%M:%SZ',finished),finished-started))
end
assert(build_mode == 'refine-all' or build_mode == 'initialize-only' or
  build_mode == 'alignment-only',
  'build mode must be refine-all, initialize-only or alignment-only')
local bore_end = backplate_front+backplate_thickness+far_clearance
local axial_span = bore_end+far_cap_thickness
local radial_span = inner_radius+wall
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
assert(inner_radius>0 and wall>0 and backplate_front>0 and
  backplate_thickness>0 and far_clearance>0 and far_cap_thickness>0,
  'shield dimensions and clearances must be positive')
assert(math.abs(backplate_front-stage1_length-stage2_length)<1e-9,
  'backplate_front must equal stage1_length+stage2_length')
assert(bore_radius>0 and ring_outer_radius>bore_radius and
  inner_radius>ring_outer_radius, 'reflectron radii must be ordered')
assert(stage1_ring_count>=1 and stage1_ring_count==math.floor(stage1_ring_count),
  'stage1_ring_count must be a positive integer')
assert(stage2_ring_count>=1 and stage2_ring_count==math.floor(stage2_ring_count),
  'stage2_ring_count must be a positive integer')

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
report_edge('radial','axis',0,mmgu_radial)
report_edge('radial','bore_radius',bore_radius,mmgu_radial)
report_edge('radial','ring_outer_radius',ring_outer_radius,mmgu_radial)
report_edge('radial','shield_inner_radius',inner_radius,mmgu_radial)
report_edge('radial','shield_outer_radius',inner_radius+wall,mmgu_radial)
report_edge('axial','entrance_grid',0,mmgu_axial)
assert(math.abs(0/mmgu_axial-math.floor(0/mmgu_axial+0.5))<=1e-8,
  'entrance-grid zero-width sheet must lie on a raw PA row')
local ring_thickness=backplate_thickness
for ring_index=1,stage1_ring_count do
  local center=ring_index*stage1_length/(stage1_ring_count+1)
  report_edge('axial','stage1_ring_'..ring_index..'_front',center-ring_thickness/2,mmgu_axial)
  report_edge('axial','stage1_ring_'..ring_index..'_back',center+ring_thickness/2,mmgu_axial)
end
report_edge('axial','midgrid',stage1_length,mmgu_axial)
assert(math.abs(stage1_length/mmgu_axial-math.floor(stage1_length/mmgu_axial+0.5))<=1e-8,
  'midgrid zero-width sheet must lie on a raw PA row')
for ring_index=1,stage2_ring_count do
  local center=stage1_length+ring_index*stage2_length/(stage2_ring_count+1)
  report_edge('axial','stage2_ring_'..ring_index..'_front',center-ring_thickness/2,mmgu_axial)
  report_edge('axial','stage2_ring_'..ring_index..'_back',center+ring_thickness/2,mmgu_axial)
end
report_edge('axial','backplate_front',backplate_front,mmgu_axial)
report_edge('axial','backplate_back',backplate_front+backplate_thickness,mmgu_axial)
report_edge('axial','shield_far_cap_front',bore_end,mmgu_axial)
report_edge('axial','shield_far_cap_back',axial_span,mmgu_axial)
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
local estimated_array_factor=stage1_ring_count+stage2_ring_count+6.25
local estimated_gib = nx*ny*8*estimated_array_factor/1024^3
print(string.format(
  'BUILD: dimensions=%dx%dx1 cell_mm=(%.12g,%.12g) span_mm=(%.12g,%.12g) bore_end_mm=%.12g estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,mmgu_axial,mmgu_radial,axial_span,radial_span,
  bore_end,estimated_gib,max_gib))
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
_G.var={
  mmgu_axial=mmgu_axial,mmgu_radial=mmgu_radial,
  inner_radius=inner_radius,wall=wall,
  backplate_front=backplate_front,
  backplate_thickness=backplate_thickness,
  far_clearance=far_clearance,far_cap_thickness=far_cap_thickness,
  stage1_length=stage1_length,stage2_length=stage2_length,
  bore_radius=bore_radius,ring_outer_radius=ring_outer_radius,
  stage1_ring_count=stage1_ring_count,stage2_ring_count=stage2_ring_count
}
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
  audit_raw_grid(1,'entgrid',0)
  audit_raw_grid(2+stage1_ring_count,'midgrid',math.floor(stage1_length/mmgu_axial+0.5))
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
local voltage_assignments={'1=0'}
for ring_index=1,stage1_ring_count do
  voltage_assignments[#voltage_assignments+1]=string.format('%d=%.12g',1+ring_index,
    midgrid_voltage*ring_index/(stage1_ring_count+1))
end
local midgrid_electrode=2+stage1_ring_count
voltage_assignments[#voltage_assignments+1]=string.format('%d=%.12g',midgrid_electrode,midgrid_voltage)
for ring_index=1,stage2_ring_count do
  voltage_assignments[#voltage_assignments+1]=string.format('%d=%.12g',midgrid_electrode+ring_index,
    midgrid_voltage+(backplate_voltage-midgrid_voltage)*ring_index/(stage2_ring_count+1))
end
voltage_assignments[#voltage_assignments+1]=string.format('%d=%.12g',midgrid_electrode+stage2_ring_count+1,backplate_voltage)
voltage_assignments[#voltage_assignments+1]=string.format('%d=0',midgrid_electrode+stage2_ring_count+2)
timed_stage('fastadj',function()
  simion.command(string.format('fastadj %q %s',output:gsub('#$','0'),table.concat(voltage_assignments,',')))
end)
print('BUILD: PASS')
