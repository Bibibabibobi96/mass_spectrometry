-- Save a voltage-adjusted PA0 from one already refined PA family.
-- Geometry, electrode grouping, and voltages remain caller-owned.
-- Usage: simion --nogui lua voltageize_pa0.lua SOURCE_PA0 OUTPUT_PA0 ID=V [ID=V ...]

local source=assert(arg[1],'source PA0 required')
local output=assert(arg[2],'output PA0 required')
assert(source:match('%.pa0$') and output:match('%.pa0$'),'source/output must be PA0 files')
assert(source~=output,'voltageization must not overwrite its source PA family')
local values={}
local count=0
for index=3,#arg do
  local identifier_text,value_text=arg[index]:match('^(%d+)=(.*)$')
  local identifier=assert(tonumber(identifier_text),'voltage assignment must use ID=V')
  local value=assert(tonumber(value_text),'voltage assignment value must be numeric')
  assert(identifier>0 and identifier==math.floor(identifier),'electrode ID must be a positive integer')
  assert(values[identifier]==nil,'electrode ID is duplicated')
  assert(value==value and math.abs(value)<math.huge,'electrode voltage must be finite')
  values[identifier]=value
  count=count+1
end
assert(count>0,'at least one electrode voltage is required')
simion.pas:close()
local pa=assert(simion.pas:open(source),'cannot open source PA family')
pa:fast_adjust(values)
pa:save(output)
pa:close()
print(string.format('PA0_VOLTAGEIZE=PASS electrodes=%d source=%s output=%s',count,source,output))
