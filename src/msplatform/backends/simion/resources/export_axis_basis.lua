-- Sample an ordered set of independent, owner-authenticated response PAs.
-- The caller supplies a frozen Lua spec and protects its input records throughout.
local spec=assert(dofile(assert(arg[1], 'sampling spec required')))
assert(type(spec.responses)=='table' and #spec.responses>0, 'ordered standalone responses required')
assert(type(spec.maximum_x_mm)=='number' and spec.maximum_x_mm==spec.maximum_x_mm and
  spec.maximum_x_mm>=0 and spec.maximum_x_mm<math.huge, 'invalid axial limit')
local existing=io.open(spec.output,'rb')
if existing then existing:close(); error('refusing to overwrite axis samples') end
simion.pas:close()
local arrays={}
for index,path in ipairs(spec.responses) do
  assert(type(path)=='string' and path:lower():match('%.pa$'), 'standalone .pa required')
  local pa=assert(simion.pas:open(path),'cannot open standalone response')
  assert(pa.refinable==false and pa.potential_type=='electric', 'invalid standalone response')
  assert(pa.symmetry==spec.symmetry, 'response symmetry differs')
  for key,value in pairs(spec.grid) do assert(pa[key]==value, 'response grid differs: '..key) end
  arrays[index]=pa
end
local reference=arrays[1]
assert(spec.maximum_x_mm <= (reference.nx-1)*reference.dx_mm, 'axis limit exceeds response grid')
local last_x=math.floor(spec.maximum_x_mm/reference.dx_mm+1e-9)
local stream=assert(io.open(spec.output,'w'))
stream:write('x_mm')
for index=1,#arrays do stream:write(',basis_'..index..'_V') end
stream:write('\n')
for x=0,last_x do
  stream:write(string.format('%.17g',x*reference.dx_mm))
  for _,pa in ipairs(arrays) do stream:write(string.format(',%.17g',pa:potential(x,0,0))) end
  stream:write('\n')
end
stream:close()
simion.pas:close()
print(string.format('AXIS_BASIS_EXPORT=PASS rows=%d electrodes=%d output=%s',last_x+1,#arrays,spec.output))
