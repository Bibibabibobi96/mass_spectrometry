-- Build the authoritative near-cap + field-free shield PA.
-- Usage:
--   simion.exe --nogui lua build_flight_tube_variant.lua source.gem output.pa#
--     frozen_oatof_resolved.lua

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local contract = dofile(assert(arg[3], 'missing frozen resolved Lua'))
local component = assert(contract.physical_geometry, 'missing provider physical geometry').simion.flight_tube
local mesh = contract.simion_geometry_build.flight_tube
local mmgu_axial, mmgu_radial, max_gib = mesh.cell_axial_mm, mesh.cell_radial_mm, mesh.max_gib
local axial_span, outer_radius = component.axial_span_mm, component.outer_radius_mm
local near_cap_thickness = component.electrodes[1].regions[1].axial_mm[2]
local inner_radius = component.electrodes[1].regions[2].radius_mm[1]
local wall = outer_radius-inner_radius
local near_outer_z = contract.geometry_mm.shield_outer_z_min
local reflectron_interface_z = contract.geometry_mm.L_flight

assert(source:match('^%a:[/\\]') or source:match('^/'),
  'source GEM path must be absolute')
assert(output:match('^%a:[/\\]') or output:match('^/'),
  'output PA# path must be absolute')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_axial>0 and mmgu_radial>0 and max_gib>0,
  'grid and size limit must be positive')
assert(inner_radius>0 and wall>0 and near_cap_thickness>0,
  'shield dimensions must be positive')
assert(axial_span>near_cap_thickness,
  'reflectron interface must lie beyond the near cap')

local nx=math.ceil(axial_span/mmgu_axial)+1
local ny=math.ceil(outer_radius/mmgu_radial)+1
-- One basis solution plus PA0, PA# and fractional-surface metadata.
local estimated_gib=nx*ny*8*3.25/1024^3
print(string.format(
  'BUILD: dimensions=%dx%dx1 cell_mm=(%.12g,%.12g) inner_outer_radius_mm=(%.12g,%.12g) global_z_mm=(%.12g,%.12g) cap_mm=%.12g estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,mmgu_axial,mmgu_radial,inner_radius,outer_radius,
  near_outer_z,reflectron_interface_z,near_cap_thickness,
  estimated_gib,max_gib))
assert(estimated_gib<=max_gib,
  string.format('estimated PA set %.3f GiB exceeds limit %.3f GiB',
    estimated_gib,max_gib))

local staged_source=output:gsub('%.pa#$','.source.gem')
local input=assert(io.open(source,'rb'))
local content=input:read('*a')
input:close()
local staged=assert(io.open(staged_source,'wb'))
staged:write(content)
staged:close()
_G.var={mmgu_axial=mmgu_axial, mmgu_radial=mmgu_radial,
  component=component}
simion.command(string.format('gem2pa %q %q',staged_source,output))
_G.var=nil
os.remove(staged_source)
os.remove(staged_source:gsub('%.gem$','.processed.gem'))
simion.command(string.format('refine --resume=0 %q',output))
simion.command(string.format('fastadj %q 1=0',output:gsub('#$','0')))
print('BUILD: PASS')
