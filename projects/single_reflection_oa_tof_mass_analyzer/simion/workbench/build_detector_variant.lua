-- Build a size-guarded anisotropic detector-position marker PA.
-- Usage:
--   simion.exe --nogui lua build_detector_variant.lua source.gem output.pa#
--     xy_mm z_mm radius_mm absorber_thickness_mm
--     front_margin_z_mm back_margin_z_mm margin_xy_mm max_MiB

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
assert(arg[10], 'all detector geometry and mesh arguments are required')
local mmgu_xy = assert(tonumber(arg[3]), 'invalid xy cell size')
local mmgu_z = assert(tonumber(arg[4]), 'invalid z cell size')
local radius = assert(tonumber(arg[5]), 'invalid detector radius')
local absorber_thickness = assert(tonumber(arg[6]), 'invalid absorber thickness')
local front_margin_z = assert(tonumber(arg[7]), 'invalid front margin')
local back_margin_z = assert(tonumber(arg[8]), 'invalid back margin')
local margin_xy = assert(tonumber(arg[9]), 'invalid xy margin')
local max_mib = assert(tonumber(arg[10]), 'invalid memory limit')

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
  'refine --resume=0 --convergence=5e-7 %q',output))
simion.command(string.format('fastadj %q 1=0',output:gsub('#$','0')))
print('BUILD: PASS')
