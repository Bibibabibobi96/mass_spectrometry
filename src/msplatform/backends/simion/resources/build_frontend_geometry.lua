-- Build one actual frontend raw geometry; no fields, particles or flight.
local directory=assert(debug.getinfo(1,'S').source:sub(2):gsub('\\','/'):match('^(.*)/'))
local geometry=assert(loadfile(directory..'/gem2pa_geometry.lua'))()
local spec=dofile(assert(arg[1],'raw geometry specification required'))
assert(spec.role=='simion_frontend_raw_geometry' and spec.schema_version==1,'unsupported raw geometry spec')
local prior=io.open(spec.output,'rb')
if prior then prior:close();error('refusing to overwrite raw geometry') end
geometry.gem2pa(spec.gem,spec.output,nil)
simion.pas:close()
local pa=assert(simion.pas:open(spec.output))
for key,value in pairs(spec.grid) do assert(pa[key]==value,'raw geometry grid differs: '..key) end
assert(pa.potential_type=='electric','raw geometry must be electric')
for _,sample in ipairs(spec.physical_samples) do
  local potential,metal=pa:point(unpack(sample.gu))
  assert(metal==true and potential==sample.electrode_id,'raw physical electrode sample differs: '..sample.label)
end
pa:close()
print('BUILD_GEOMETRY=PASS ROLE='..spec.domain_id)
