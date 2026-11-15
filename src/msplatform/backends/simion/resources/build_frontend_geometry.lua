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
-- Optional namespace witnesses use the native raw PA, never duplicate GEM/CSG.
-- Official SIMION2020 integer point() describes RAW metal/potential values.
-- electrode_numbers is fast-adjustable metadata, not a raw PA# namespace.
local samples={}
for _,sample in ipairs(spec.physical_samples) do samples[#samples+1]=sample end
if spec.electrode_witness_ids then
  local expected,remaining={},0
  for _,eid in ipairs(spec.electrode_witness_ids) do
    assert(type(eid)=='number' and eid==math.floor(eid) and eid>0 and not expected[eid],
      'electrode witness IDs must be distinct positive integers')
    expected[eid]=true;remaining=remaining+1
  end
  assert(remaining>0,'electrode witness IDs must not be empty')
  local actual={}
  local scanned,started=0,os.clock()
  for z=0,pa.nz-1 do
    for y=0,pa.ny-1 do
      for x=0,pa.nx-1 do
        local eid,metal=pa:point(x,y,z);scanned=scanned+1
        if metal then
          assert(expected[eid],'raw geometry has an undeclared electrode')
          if not actual[eid] then
            samples[#samples+1]={gu={x,y,z},electrode_id=eid,label='native-electrode-'..eid}
            actual[eid]=true;remaining=remaining-1
          end
        end
      end
    end
  end
  assert(remaining==0,'raw geometry has no integer witness for a declared electrode')
  print(string.format('GEOMETRY_NAMESPACE_SCAN=PASS NODES=%d CPU_SECONDS=%.17g',scanned,os.clock()-started))
end
for _,sample in ipairs(samples) do
  local potential,metal=pa:point(unpack(sample.gu))
  local expected=sample.metal~=false
  assert(metal==expected and (not expected or potential==sample.electrode_id),'raw physical electrode sample differs: '..sample.label)
end
if spec.fractional_surface then
  local companion=io.open(spec.fractional_surface,'rb')
  local empty=companion==nil
  if companion then local first=companion:read(1);companion:close();assert(first~=nil,'fractional surface companion empty') end
  local scanned,offsets=0,0
  if empty then
    assert(spec.surface_state,'fractional surface companion missing')
    for x,y,z in pa:points() do
      local sx,sy,sz=pa:surface_info(x,y,z)
      scanned=scanned+1
      if sx~=nil or sy~=nil or sz~=nil then offsets=offsets+1 end
    end
    assert(scanned==pa.nx*pa.ny*pa.nz and offsets==0,'missing companion with nonempty or incomplete fractional surface')
  end
  local output=assert(io.open(spec.surface_witnesses,'wb'))
  local witnessed=0
  for _,sample in ipairs(samples) do
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
  if spec.surface_state then
    local report=assert(io.open(spec.surface_state,'wb'))
    local scan_value=empty and tostring(scanned) or 'null'
    local offset_value=empty and '0' or 'null'
    assert(report:write(string.format('{"schema_version":1,"mode":"%s","grid":[%d,%d,%d],"pitch":[%.17g,%.17g,%.17g],"scanned_nodes":%s,"offset_nodes":%s}\n',
      empty and 'empty' or 'present',pa.nx,pa.ny,pa.nz,pa.dx_mm,pa.dy_mm,pa.dz_mm,scan_value,offset_value)))
    assert(report:close())
  end
end
pa:close()
print('BUILD_GEOMETRY=PASS ROLE='..spec.domain_id)
