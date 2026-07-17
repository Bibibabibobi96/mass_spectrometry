-- Build a size-guarded reflectron PA variant from the formal GEM.
-- Usage:
--   simion.exe --nogui lua build_reflectron_variant.lua source.gem output.pa#
--     [axial_mm_per_gu] [radial_mm_per_gu] [max_GiB]
--     [inner_radius_mm] [wall_mm] [backplate_front_mm]
--     [backplate_thickness_mm] [far_clearance_mm] [far_cap_mm]
--     [stage1_length_mm] [stage2_length_mm] [bore_radius_mm]
--     [ring_outer_radius_mm] [stage1_ring_count] [stage2_ring_count]
--     [midgrid_voltage_v] [backplate_voltage_v]

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local mmgu_axial = tonumber(arg[3] or '1')
local mmgu_radial = tonumber(arg[4] or tostring(mmgu_axial))
local max_gib = tonumber(arg[5] or '0.5')
local inner_radius = tonumber(arg[6] or '350')
local wall = tonumber(arg[7] or '10')
local backplate_front = tonumber(arg[8] or '206.8328')
local backplate_thickness = tonumber(arg[9] or '5')
local far_clearance = tonumber(arg[10] or '50')
local far_cap_thickness = tonumber(arg[11] or '10')
local stage1_length = tonumber(arg[12] or '120')
local stage2_length = tonumber(arg[13] or '86.8328')
local bore_radius = tonumber(arg[14] or '250')
local ring_outer_radius = tonumber(arg[15] or '300')
local stage1_ring_count = tonumber(arg[16] or '10')
local stage2_ring_count = tonumber(arg[17] or '5')
local midgrid_voltage = tonumber(arg[18] or '1600')
local backplate_voltage = tonumber(arg[19] or '2400')
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

local nx = math.ceil(axial_span/mmgu_axial) + 1
local ny = math.ceil(radial_span/mmgu_radial) + 1
-- Nineteen basis arrays plus PA0, PA# and fractional-surface metadata.
local estimated_gib = nx*ny*8*21.25/1024^3
print(string.format(
  'BUILD: dimensions=%dx%dx1 cell_mm=(%.12g,%.12g) span_mm=(%.12g,%.12g) bore_end_mm=%.12g estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,mmgu_axial,mmgu_radial,axial_span,radial_span,
  bore_end,estimated_gib,max_gib))
assert(estimated_gib <= max_gib,
  string.format('estimated PA set %.3f GiB exceeds limit %.3f GiB',
    estimated_gib,max_gib))

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
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
simion.command(string.format(
  'refine --resume=0 --convergence=5e-7 %q',output))
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
simion.command(string.format('fastadj %q %s',output:gsub('#$','0'),table.concat(voltage_assignments,',')))
print('BUILD: PASS')
