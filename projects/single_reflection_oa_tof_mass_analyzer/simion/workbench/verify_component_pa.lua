-- Verify an owned native build against its newly exported standalone responses.
-- This runs before publication; published native .paN families are never inputs.
-- STEM STANDALONE_DIR COUNT NX NY NZ DX DY DZ SYMMETRY_TYPE [RESPONSE_ID PRIVATE_STANDALONE]
local stem = assert(arg[1], 'owned native family stem required')
local directory = assert(arg[2], 'standalone payload directory required')
local count = assert(tonumber(arg[3]), 'electrode count required')
local dimensions = {tonumber(arg[4]), tonumber(arg[5]), tonumber(arg[6])}
local cells = {tonumber(arg[7]), tonumber(arg[8]), tonumber(arg[9])}
local symmetry = assert(arg[10], 'provider symmetry type required')
local selected = arg[11] and tonumber(arg[11]) or nil
assert((#arg == 10 or #arg == 12) and count > 0 and count == math.floor(count), 'invalid verification arguments')
if #arg == 12 then
  assert(selected and selected == math.floor(selected) and selected >= 1 and selected <= count,
    'selected response ID is outside the complete namespace')
end
local basename = assert(stem:match('([^/\\]+)$'), 'family basename required')
local separator = package.config:sub(1, 1)
local function metadata(pa)
  assert(pa.nx == dimensions[1] and pa.ny == dimensions[2] and pa.nz == dimensions[3],
    'PA dimensions differ from the provider projection')
  assert(pa.symmetry_type == symmetry and pa.potential_type == 'electric',
    'PA symmetry or potential type differs')
  for index, actual in ipairs{pa.dx_mm, pa.dy_mm, pa.dz_mm} do
    assert(math.abs(actual - cells[index]) <= 1e-12, 'PA grid spacing differs')
  end
end
simion.pas:close()
local controller = assert(simion.pas:open(stem .. '.pa0'), 'cannot open owned controller')
metadata(controller)
local ids = assert(controller.electrode_numbers, 'controller has no adjustable namespace')
assert(#ids == count, 'controller electrode count differs')
local found = {}
for _, id in ipairs(ids) do
  assert(id == math.floor(id) and id >= 1 and id <= count and not found[id],
    'controller adjustable namespace differs')
  found[id] = true
end
controller:close()
for id = selected or 1, selected or count do
  simion.pas:close()
  local source = assert(simion.pas:open(stem .. '.pa' .. id), 'cannot open owned response')
  local output = assert(simion.pas:open(arg[12] or (directory .. separator .. basename .. '.response' .. id .. '.pa')),
    'cannot open standalone response')
  metadata(source); metadata(output)
  assert(output.refinable ~= true, 'standalone response is refinable')
  local nodes = 0
  for x, y, z in source:points() do
    local sv, se = source:point(x, y, z)
    local ov, oe = output:point(x, y, z)
    assert(sv == sv and math.abs(sv) < math.huge and sv == ov and se == oe,
      'standalone node potential or electrode mask differs')
    nodes = nodes + 1
  end
  assert(nodes == dimensions[1] * dimensions[2] * dimensions[3], 'incomplete node inventory')
  for _, fraction in ipairs{0.25, 0.5, 0.75} do
    local x, y, z = (dimensions[1]-1)*fraction, (dimensions[2]-1)*fraction, (dimensions[3]-1)*fraction
    local sv, ov = source:potential_vc(x,y,z), output:potential_vc(x,y,z)
    local sx,sy,sz = source:field_vc(x,y,z)
    local ox,oy,oz = output:field_vc(x,y,z)
    assert(sv == ov and sx == ox and sy == oy and sz == oz,
      'standalone interpolated potential or field differs')
  end
  output:close(); source:close()
  print(string.format('COMPONENT_RESPONSE_VERIFY=PASS response=%d nodes=%d samples=3', id, nodes))
end
if selected then
  print(string.format('COMPONENT_PA_RESPONSE_VERIFY=PASS response=%d total=%d', selected, count))
else
  print(string.format('COMPONENT_PA_VERIFY=PASS responses=%d', count))
end
