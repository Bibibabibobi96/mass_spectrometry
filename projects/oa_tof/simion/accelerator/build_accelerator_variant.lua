-- Build a size-guarded accelerator PA variant from the formal parameterized GEM.
-- Usage:
--   simion.exe --nogui lua build_accelerator_variant.lua source.gem output.pa#
--     [xy_mm] [z_mm] [bore_half_mm] [ring_width_mm] [gap_mm]
--     [rear_gap_mm] [wall_mm] [vacuum_margin_mm] [max_GiB]
--     [back_domain_margin_mm] [front_domain_margin_mm] [grid_phase_z_mm]

local source = assert(arg[1], 'missing source GEM')
local output = assert(arg[2], 'missing output PA#')
local mmgu_xy = tonumber(arg[3] or '0.25')
local mmgu_z = tonumber(arg[4] or tostring(mmgu_xy))
local bore_half = tonumber(arg[5] or '5')
local ring_width = tonumber(arg[6] or '5')
local insulation_gap = tonumber(arg[7] or '5')
local rear_gap = tonumber(arg[8] or '5')
local shield_wall = tonumber(arg[9] or '4')
local vacuum_margin = tonumber(arg[10] or '0')
local max_gib = tonumber(arg[11] or '3.5')
local back_domain_margin = tonumber(arg[12] or '0')
local front_domain_margin = tonumber(arg[13] or '0')
local grid_phase_z = tonumber(arg[14] or '0')
local shield_outer_width = 2*(bore_half+ring_width+insulation_gap+shield_wall)
local xy_span = shield_outer_width+2*vacuum_margin
local geometry_z_min = -1-rear_gap-shield_wall
local z_min = geometry_z_min-back_domain_margin
local z_max = 20+front_domain_margin
local z_span = z_max-z_min
assert(source:match('^%a:[/\\]') or source:match('^/'), 'source GEM path must be absolute')
assert(output:match('^%a:[/\\]') or output:match('^/'), 'output PA# path must be absolute')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_xy and mmgu_xy > 0, 'mmgu_xy must be positive')
assert(mmgu_z and mmgu_z > 0, 'mmgu_z must be positive')
assert(bore_half and bore_half > 0, 'bore_half must be positive')
assert(ring_width and ring_width > 0, 'ring_width must be positive')
assert(insulation_gap and insulation_gap > 0, 'insulation_gap must be positive')
assert(rear_gap and rear_gap > 0, 'rear_gap must be positive')
assert(shield_wall and shield_wall > 0, 'shield_wall must be positive')
assert(vacuum_margin and vacuum_margin >= 0, 'vacuum_margin must be nonnegative')
assert(max_gib and max_gib > 0, 'max_GiB must be positive')
assert(back_domain_margin and back_domain_margin >= 0,
  'back_domain_margin must be nonnegative')
assert(front_domain_margin and front_domain_margin >= 0,
  'front_domain_margin must be nonnegative')
assert(grid_phase_z and grid_phase_z >= 0 and grid_phase_z < mmgu_z,
  'grid_phase_z must be in [0, mmgu_z)')

local nx = math.floor(xy_span/mmgu_xy + 0.5) + 1
local ny = nx
local nz = math.floor(z_span/mmgu_z + 0.5) + 1
-- Ten refined/adjusted arrays plus PA# and surface metadata. The 11.25 factor
-- slightly exceeds both measured diagnostic sets, so the limit covers files
-- actually written rather than only the ten voltage arrays.
local estimated_gib = nx*ny*nz*8*11.25/1024^3
print(string.format('BUILD: bore_half=%.12g ring_width=%.12g insulation_gap=%.12g rear_gap=%.12g wall=%.12g shield_outer=%.12g',
  bore_half,ring_width,insulation_gap,rear_gap,shield_wall,shield_outer_width))
print(string.format('BUILD: dimensions=%dx%dx%d cell_mm=(%.12g,%.12g,%.12g) span_mm=(%.12g,%.12g) origin_z=%.12g estimated_total_GiB=%.6f limit_GiB=%.6f',
  nx,ny,nz,mmgu_xy,mmgu_xy,mmgu_z,xy_span,z_span,z_min,estimated_gib,max_gib))
print(string.format('BUILD: domain_margin_back_front_mm=(%.12g,%.12g) grid_phase_z_mm=%.12g compensated_instance_z_mm=%.12g',
  back_domain_margin,front_domain_margin,grid_phase_z,z_min-grid_phase_z))
assert(estimated_gib <= max_gib, string.format('estimated PA set %.3f GiB exceeds limit %.3f GiB',estimated_gib,max_gib))

_G.var={mmgu_xy=mmgu_xy,mmgu_z=mmgu_z,xy_span=xy_span,z_min=z_min,z_span=z_span,
  bore_half=bore_half,ring_width=ring_width,insulation_gap=insulation_gap,
  rear_gap=rear_gap,shield_wall=shield_wall,grid_phase_z=grid_phase_z}
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
simion.command(string.format('refine --resume=0 --convergence=5e-7 %q',output))
simion.command(string.format('fastadj %q 1=2240,2=1760,3=1466.666667,4=1173.333333,5=880,6=586.666667,7=293.333333,8=0,9=0',output:gsub('#$','0')))
print('BUILD: PASS')
