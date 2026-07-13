simion.command('"oatof_ideal_grounded.iob"')
local wb=simion.wb
for i=1,#wb.instances do
  local inst=wb.instances[i]
  local pa=inst.pa
  print(string.format('INSTANCE %d file=%s xyz=(%.6f,%.6f,%.6f) aer=(%.6f,%.6f,%.6f) scale=%.6f',i,inst.filename,inst.x,inst.y,inst.z,inst.az,inst.el,inst.rt,inst.scale))
  for _,k in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm','symmetry','potential_type'}) do
    local ok,v=pcall(function() return pa[k] end)
    print(string.format('  pa.%s=%s',k,ok and tostring(v) or ('ERR:'..tostring(v))))
  end
end
