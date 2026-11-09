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
  local expected=sample.metal~=false
  assert(metal==expected and (not expected or potential==sample.electrode_id),'raw physical electrode sample differs: '..sample.label)
end
if spec.fractional_surface then
  local companion=assert(io.open(spec.fractional_surface,'rb'),'fractional surface companion missing')
  assert(companion:seek('end')>0,'fractional surface companion empty');companion:close()
  local output=assert(io.open(spec.surface_witnesses,'wb'))
  local witnessed=0
  for _,sample in ipairs(spec.physical_samples) do
    if sample.metal~=false then
      for axis=1,3 do
        for _,direction in ipairs({-1,1}) do
          local q={sample.gu[1],sample.gu[2],sample.gu[3]}
          local dimensions={pa.nx,pa.ny,pa.nz}
          while q[axis]+direction>=0 and q[axis]+direction<dimensions[axis] do
            local nextq={q[1],q[2],q[3]};nextq[axis]=nextq[axis]+direction
            local _,metal=pa:point(unpack(nextq))
            if metal~=true then
              if direction<0 then q=nextq end
              local sx,sy,sz=pa:surface_info(unpack(q))
              output:write(string.format('%d,%d,%d,%s,%s,%s\n',q[1],q[2],q[3],
                sx and string.format('%.17g',sx) or 'nil',sy and string.format('%.17g',sy) or 'nil',sz and string.format('%.17g',sz) or 'nil'))
              witnessed=witnessed+1;break
            end
            q=nextq
          end
        end
      end
    end
  end
  assert(witnessed>0);assert(output:close())
end
pa:close()
print('BUILD_GEOMETRY=PASS ROLE='..spec.domain_id)
