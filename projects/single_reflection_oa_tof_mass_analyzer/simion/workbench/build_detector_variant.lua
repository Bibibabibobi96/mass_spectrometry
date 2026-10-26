-- Build a size-guarded anisotropic detector-position marker PA.
-- Usage:
--   simion.exe --nogui lua build_detector_variant.lua source.gem output.pa#
--     frozen_oatof_resolved.lua

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local contract = dofile(assert(arg[3], 'missing frozen resolved Lua'))
local marker = assert(contract.physical_geometry, 'missing provider physical geometry').simion.detector_marker
local mesh = contract.simion_geometry_build.detector
local mmgu_xy, mmgu_z = marker.cell_xy_mm, marker.cell_z_mm
local radius, absorber_thickness = marker.active_radius_mm, marker.absorber_thickness_mm
local front_margin_z, back_margin_z = marker.front_margin_z_mm, marker.back_margin_z_mm
local margin_xy, max_mib = mesh.margin_xy_mm, mesh.max_mib

assert(source:match('^%a:[/\\]') or source:match('^/'),
  'source GEM path must be absolute')
assert(output:match('^%a:[/\\]') or output:match('^/'),
  'output PA# path must be absolute')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_xy and mmgu_xy > 0, 'xy cell size must be positive')
assert(mmgu_z and mmgu_z > 0, 'z cell size must be positive')
assert(radius and radius > 0, 'radius must be positive')
assert(absorber_thickness and absorber_thickness >= 5*mmgu_z,
  'absorber thickness must span at least five z cells')
assert(front_margin_z and front_margin_z >= 10*mmgu_z,
  'front z margin must span at least ten z cells')
assert(back_margin_z and back_margin_z >= 5*mmgu_z,
  'back z margin must span at least five z cells')
assert(margin_xy and margin_xy >= mmgu_xy,
  'xy margin must span at least one xy cell')
assert(max_mib and max_mib > 0, 'max_MiB must be positive')

local xy_span = 2*(radius+margin_xy)
local z_span = front_margin_z+absorber_thickness+back_margin_z
local nx = math.floor(xy_span/mmgu_xy+0.5)+1
local ny = nx
local nz = math.floor(z_span/mmgu_z+0.5)+1
-- Electrode basis, adjusted PA0, PA# and fractional-surface metadata.
local estimated_mib = nx*ny*nz*8*3.25/1024^2
print(string.format(
  'BUILD: dimensions=%dx%dx%d cell_mm=(%.12g,%.12g,%.12g) span_mm=(%.12g,%.12g) estimated_total_MiB=%.6f limit_MiB=%.6f',
  nx,ny,nz,mmgu_xy,mmgu_xy,mmgu_z,xy_span,z_span,
  estimated_mib,max_mib))
assert(estimated_mib <= max_mib,
  string.format('estimated PA set %.3f MiB exceeds limit %.3f MiB',
    estimated_mib,max_mib))

local staged_source=output:gsub('%.pa#$','.source.gem')
local input=assert(io.open(source,'rb'))
local content=input:read('*a')
input:close()
local staged=assert(io.open(staged_source,'wb'))
staged:write(content)
staged:close()
_G.var={mmgu_xy=mmgu_xy,mmgu_z=mmgu_z,radius=radius,
  absorber_thickness=absorber_thickness,front_margin_z=front_margin_z,
  back_margin_z=back_margin_z,margin_xy=margin_xy}
simion.command(string.format('gem2pa %q %q',staged_source,output))
_G.var=nil
os.remove(staged_source)
os.remove(staged_source:gsub('%.gem$','.processed.gem'))
simion.command(string.format(
  'refine --resume=0 %q',output))
simion.command(string.format('fastadj %q 1=0',output:gsub('#$','0')))
print('BUILD: PASS')
