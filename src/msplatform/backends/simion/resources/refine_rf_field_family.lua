-- SIMION2020 CHM lua_simion.html::simion.command and CLI::refine.
-- Fresh mutable producer only. No published family is ever passed here.
local spec=assert(dofile(assert(arg[1],'RF Refine spec required')))
assert(spec.input:match('%.pa#$'),'RF Refine requires the actual raw PA#')
local command='refine --resume=0'
if spec.convergence_v~=nil then
  assert(type(spec.convergence_v)=='number' and spec.convergence_v>0 and spec.convergence_v<math.huge,
    'explicit convergence must be positive finite')
  command=command..' --convergence='..string.format('%.17g',spec.convergence_v)
end
simion.command(command..' '..string.format('%q',spec.input))
simion.pas:close()
print('INDEPENDENT_RF_REFINE=PASS FLY=False SOURCE=False')
