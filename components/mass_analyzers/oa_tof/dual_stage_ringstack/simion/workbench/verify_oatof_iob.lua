simion.command('"oatof_ideal.iob"')
local wb = simion.wb
assert(#wb.instances == 2, 'expected two PA instances')
for i=1,#wb.instances do
  local p = wb.instances[i]
  print(string.format('instance=%d file=%s xyz=(%.6f,%.6f,%.6f) aer=(%.6f,%.6f,%.6f) scale=%.6f',
    i, p.filename, p.x, p.y, p.z, p.az, p.el, p.rt, p.scale))
end
