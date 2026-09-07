-- Save one voltage-adjusted PA0 from a read-only refined accelerator family.
-- Usage: ... SOURCE_PA0 OUTPUT_PA0 V1 V2 ... V9
local source=assert(arg[1],'source accelerator PA0 required')
local output=assert(arg[2],'output accelerator PA0 required')
assert(source:match('%.pa0$') and output:match('%.pa0$'),'source/output must be PA0 files')
assert(source~=output,'voltage trial must not overwrite its source PA family')
local values={}
for electrode=1,9 do
  local value=assert(tonumber(arg[2+electrode]),string.format('electrode %d voltage required',electrode))
  assert(value==value and math.abs(value)<math.huge,string.format('electrode %d voltage must be finite',electrode))
  values[electrode]=value
end
simion.pas:close()
local pa=assert(simion.pas:open(source),'cannot open source accelerator PA family')
pa:fast_adjust(values)
pa:save(output)
pa:close()
print(string.format('MRTOF_ACCELERATOR_PA0_VOLTAGEIZE=PASS source=%s output=%s',source,output))
