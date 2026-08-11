-- Usage: simion --nogui lua run_fast_adjust_basis_limit_probe.lua source.gem output.pa# count
local source=assert(arg[1], 'missing GEM source')
local output=assert(arg[2], 'missing output PA#')
local count=assert(tonumber(arg[3]), 'missing electrode count')
assert(count>=1 and count==math.floor(count), 'count must be a positive integer')
assert(output:match('%.pa#$'), 'output must end in .pa#')

_G.var={electrode_count=count}
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
simion.command(string.format('refine --resume=0 --convergence=5e-7 %q',output))

local assignments={}
for electrode=1,count do
  assignments[#assignments+1]=string.format('%d=%d',electrode,electrode)
end
simion.command(string.format(
  'fastadj %q %s',output:gsub('#$','0'),table.concat(assignments,',')))
print(string.format('FAST_ADJUST_BASIS_PROBE=PASS count=%d max_pa=pa%d',count,count))
