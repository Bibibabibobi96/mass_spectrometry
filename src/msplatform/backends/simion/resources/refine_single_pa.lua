-- Refine exactly one initialized PA in a fresh SIMION process.
-- Usage: simion --nogui lua refine_single_pa.lua absolute.paN
local path = assert(arg[1], 'missing PA path')
assert(path:match('^%a:[/\\]') or path:match('^/'),
  'PA path must be absolute')

simion.pas:close()
local pa = simion.pas:open(path)
pa:refine{}
pa:save()
simion.pas:close()
print('REFINE_SINGLE_PA=PASS ' .. path)
