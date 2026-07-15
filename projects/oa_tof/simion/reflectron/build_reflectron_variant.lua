-- Build a size-guarded reflectron PA variant from the formal GEM.
-- Usage:
--   simion.exe --nogui lua build_reflectron_variant.lua source.gem output.pa#
--     [axial_mm_per_gu] [radial_mm_per_gu] [max_GiB]

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local mmgu_axial = tonumber(arg[3] or '1')
local mmgu_radial = tonumber(arg[4] or tostring(mmgu_axial))
local max_gib = tonumber(arg[5] or '0.5')
local axial_span = 212
local radial_span = 355
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

local nx = math.floor(axial_span/mmgu_axial + 0.5) + 1
local ny = math.floor(radial_span/mmgu_radial + 0.5) + 1
-- Nineteen basis arrays plus PA0, PA# and fractional-surface metadata.
local estimated_gib = nx*ny*8*21.25/1024^3
print(string.format(
  'BUILD: dimensions=%dx%dx1 cell_mm=(%.12g,%.12g) span_mm=(%g,%g) estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,mmgu_axial,mmgu_radial,axial_span,radial_span,
  estimated_gib,max_gib))
assert(estimated_gib <= max_gib,
  string.format('estimated PA set %.3f GiB exceeds limit %.3f GiB',
    estimated_gib,max_gib))

_G.var={mmgu_axial=mmgu_axial,mmgu_radial=mmgu_radial}
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
simion.command(string.format(
  'refine --resume=0 --convergence=5e-7 %q',output))
simion.command(string.format(
  'fastadj %q 1=0,2=145.454545,3=290.909091,4=436.363636,5=581.818182,6=727.272727,7=872.727273,8=1018.181818,9=1163.636364,10=1309.090909,11=1454.545455,12=1600,13=1733.333333,14=1866.666667,15=2000,16=2133.333333,17=2266.666667,18=2400,19=0',
  output:gsub('#$','0')))
print('BUILD: PASS')
