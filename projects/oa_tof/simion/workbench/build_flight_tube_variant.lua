-- Build the authoritative near-cap + field-free shield PA.
-- Usage:
--   simion.exe --nogui lua build_flight_tube_variant.lua source.gem output.pa#
--     [axial_mm_per_gu] [radial_mm_per_gu] [max_GiB]
--     [inner_radius_mm] [wall_mm] [near_cap_mm]
--     [near_outer_z_mm] [reflectron_interface_z_mm]

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local mmgu_axial = tonumber(arg[3] or '1')
local mmgu_radial = tonumber(arg[4] or '1')
local max_gib = tonumber(arg[5] or '0.1')
local inner_radius = tonumber(arg[6] or '350')
local wall = tonumber(arg[7] or '10')
local near_cap_thickness = tonumber(arg[8] or '10')
local near_outer_z = tonumber(arg[9] or '-40')
local reflectron_interface_z = tonumber(arg[10] or '619.83')
local outer_radius = inner_radius+wall
local axial_span = reflectron_interface_z-near_outer_z

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

_G.var={
  mmgu_axial=mmgu_axial,mmgu_radial=mmgu_radial,
  inner_radius=inner_radius,wall=wall,
  near_cap_thickness=near_cap_thickness,near_outer_z=near_outer_z,
  reflectron_interface_z=reflectron_interface_z
}
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
simion.command(string.format('refine --resume=0 --convergence=5e-7 %q',output))
simion.command(string.format('fastadj %q 1=0',output:gsub('#$','0')))
print('BUILD: PASS')
