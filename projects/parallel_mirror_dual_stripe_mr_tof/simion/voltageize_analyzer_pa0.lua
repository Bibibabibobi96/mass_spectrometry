-- Save one voltage-adjusted analyser PA0 from a read-only refined PA family.
-- Usage: ... SOURCE_PA0 OUTPUT_PA0 V1 V2 ... V20
local source=assert(arg[1],'source analyser PA0 required')
local output=assert(arg[2],'output analyser PA0 required')
assert(source:match('%.pa0$') and output:match('%.pa0$'),'source/output must be PA0 files')
assert(source~=output,'voltage trial must not overwrite its source PA family')
local values={}
for electrode=1,20 do
  local value=assert(tonumber(arg[2+electrode]),string.format('electrode %d voltage required',electrode))
  assert(value==value and math.abs(value)<math.huge,string.format('electrode %d voltage must be finite',electrode))
  -- The manufactured analyser intentionally has no physical electrode 19.
  -- SIMION rejects a Fast Adjust entry for a missing electrode even when the
  -- requested value is zero.  Keep the 20-position external voltage contract
  -- stable, but preserve the native sparse PA-family identity here.
  if electrode~=19 then values[electrode]=value end
end
simion.pas:close()
local pa=assert(simion.pas:open(source),'cannot open source analyser PA family')
pa:fast_adjust(values)
pa:save(output)
pa:close()
print(string.format('MRTOF_ANALYZER_PA0_VOLTAGEIZE=PASS source=%s output=%s',source,output))
