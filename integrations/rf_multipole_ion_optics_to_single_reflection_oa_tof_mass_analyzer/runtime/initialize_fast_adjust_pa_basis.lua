-- Materialize a complete fast-adjust PA basis family from an initialized .pa#.
-- Usage: simion --nogui lua initialize_fast_adjust_pa_basis.lua absolute.pa#
--
-- A .pa# is a SIMION fast-adjust template, not a readable .pa0.  Calling the
-- PA API Refine method once materializes .pa0 through the highest electrode
-- basis using SIMION's official default convergence objective.  Each member can then
-- be refined independently and retained for Dirichlet boundary transfer.

local path = assert(arg[1], 'missing fast-adjust PA path')
assert(path:match('%.pa#$'), 'fast-adjust PA path must end in .pa#')

simion.pas:close()
local pa = simion.pas:open(path)
pa:refine{}
simion.pas:close()
print('INITIALIZE_FAST_ADJUST_PA_BASIS=PASS ' .. path)
