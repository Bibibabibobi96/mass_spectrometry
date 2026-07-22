-- Sample one refined PA directly in its physical GEM coordinate system.
local pa = assert(simion.pas:open(assert(os.getenv('MULTIPOLE_SIMION_PA_PATH'))))
local x = assert(tonumber(os.getenv('MULTIPOLE_SAMPLE_X_MM')))
local y = assert(tonumber(os.getenv('MULTIPOLE_SAMPLE_Y_MM')))
local z = assert(tonumber(os.getenv('MULTIPOLE_SAMPLE_Z_MM')))
local origin = assert(tonumber(os.getenv('MULTIPOLE_SAMPLE_TRANSVERSE_ORIGIN_MM')))
local z_shift = assert(tonumber(os.getenv('MULTIPOLE_SAMPLE_AXIAL_SHIFT_MM')))
pa:fast_adjust{[1]=100,[2]=-100,[3]=0}
local xg, yg, zg = (origin+x)/pa.dx_mm, (origin+y)/pa.dy_mm, (z_shift+z)/pa.dz_mm
local ex, ey, ez = pa:field_vc(xg,yg,zg)
local potential = pa:potential_vc(xg,yg,zg)
print(string.format('MULTIPOLE_PA_FIELD x_mm=%.12g y_mm=%.12g z_mm=%.12g potential_V=%.12g Ex_V_per_mm=%.12g Ey_V_per_mm=%.12g Ez_V_per_mm=%.12g',
  x,y,z,potential or 0,(ex or 0)/pa.dx_mm,(ey or 0)/pa.dy_mm,(ez or 0)/pa.dz_mm))
