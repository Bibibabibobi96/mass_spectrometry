-- Refine exactly one initialized PA in a fresh SIMION process.
-- Usage: simion --nogui lua refine_single_pa.lua absolute.paN convergence
local path = assert(arg[1], 'missing PA path')
local convergence = assert(tonumber(arg[2]), 'invalid convergence objective')
assert(path:match('^%a:[/\\]') or path:match('^/'),
  'PA path must be absolute')
assert(convergence > 0, 'convergence objective must be positive')

simion.pas:close()
local pa = simion.pas:open(path)
pa:refine{convergence=convergence}
pa:save()
simion.pas:close()
print('REFINE_SINGLE_PA=PASS ' .. path)
