-- Build a size-guarded accelerator PA variant from the formal parameterized GEM.
-- Usage:
--   simion.exe --nogui lua build_accelerator_variant.lua source.gem output.pa# [xy_mm] [z_mm] [xy_span_mm] [max_GiB]

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local mmgu_xy = tonumber(arg[3] or '0.25')
local mmgu_z = tonumber(arg[4] or tostring(mmgu_xy))
local xy_span = tonumber(arg[5] or '90')
local max_gib = tonumber(arg[6] or '3.5')
local z_span = 35
assert(source:match('^%a:[/\\]') or source:match('^/'), 'source GEM path must be absolute')
assert(output:match('^%a:[/\\]') or output:match('^/'), 'output PA# path must be absolute')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_xy and mmgu_xy > 0, 'mmgu_xy must be positive')
assert(mmgu_z and mmgu_z > 0, 'mmgu_z must be positive')
assert(xy_span and xy_span >= 78, 'xy_span must retain the 78 mm grounded shield')
assert(max_gib and max_gib > 0, 'max_GiB must be positive')

local nx = math.floor(xy_span/mmgu_xy + 0.5) + 1
local ny = nx
local nz = math.floor(z_span/mmgu_z + 0.5) + 1
-- Ten refined/adjusted arrays plus PA# and surface metadata. The 11.25 factor
-- slightly exceeds both measured diagnostic sets, so the limit covers files
-- actually written rather than only the ten voltage arrays.
local estimated_gib = nx*ny*nz*8*11.25/1024^3
print(string.format('BUILD: dimensions=%dx%dx%d cell_mm=(%.12g,%.12g,%.12g) estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,nz,mmgu_xy,mmgu_xy,mmgu_z,estimated_gib,max_gib))
assert(estimated_gib <= max_gib, string.format('estimated PA set %.3f GiB exceeds limit %.3f GiB',estimated_gib,max_gib))

_G.var={mmgu_xy=mmgu_xy,mmgu_z=mmgu_z,xy_span=xy_span,z_min=-15,z_span=z_span}
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
simion.command(string.format('refine --resume=0 --convergence=5e-7 %q',output))
simion.command(string.format('fastadj %q 1=2240,2=1760,3=1466.666667,4=1173.333333,5=880,6=586.666667,7=293.333333,8=0,9=0',output:gsub('#$','0')))
print('BUILD: PASS')
