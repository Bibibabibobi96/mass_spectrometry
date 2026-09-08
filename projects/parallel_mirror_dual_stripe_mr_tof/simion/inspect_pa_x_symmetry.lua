-- Read-only grid-node symmetry diagnostic for one voltageized analyser PA0.
-- Usage: ... PA0 ORIGIN_X ORIGIN_Y ORIGIN_Z MMGU_X MMGU_Y MMGU_Z PROJECT_Y PROJECT_Z MAX_DX_GU
local path=assert(arg[1],'PA0 required')
local ox,oy,oz=assert(tonumber(arg[2])),assert(tonumber(arg[3])),assert(tonumber(arg[4]))
local sx,sy,sz=assert(tonumber(arg[5])),assert(tonumber(arg[6])),assert(tonumber(arg[7]))
local project_y,project_z=assert(tonumber(arg[8])),assert(tonumber(arg[9]))
local maximum=assert(tonumber(arg[10]))
local pa=assert(simion.pas:open(path))
local cx=(0-ox)/sx
local gy=(project_y-oy)/sy
local gz=(project_z-oz)/sz
assert(cx==math.floor(cx) and gy==math.floor(gy) and gz==math.floor(gz),'requested project section must lie on PA grid nodes')
local worst=0
for delta=0,maximum do
  local left,left_e=pa:point(cx-delta,gy,gz)
  local right,right_e=pa:point(cx+delta,gy,gz)
  local difference=right-left
  if math.abs(difference)>worst then worst=math.abs(difference) end
  print(string.format('PA_X_SYMMETRY dx_gu=%d project_x_mm=%.12g left_v=%.17g right_v=%.17g difference_v=%.17g left_e=%s right_e=%s',
    delta,delta*sx,left,right,difference,tostring(left_e),tostring(right_e)))
end
pa:close()
print(string.format('PA_X_SYMMETRY_RESULT=PASS worst_abs_difference_v=%.17g project_y_mm=%.12g project_z_mm=%.12g',worst,project_y,project_z))
