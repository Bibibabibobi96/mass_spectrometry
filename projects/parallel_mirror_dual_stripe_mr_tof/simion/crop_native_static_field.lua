-- Official post-Refine pa:crop(...,false), save and reload; never Refine here.
-- SIMION 2020 installed lua_simion.pas help: crop preserves fractional surfaces.
-- Same API sequence as the project's verified full-mirror crop/reload runs.
local path, csv_path, report_path = arg[1], arg[2], arg[3]
-- A sealed source is loaded read-only and saved under a distinct consumer path.
-- The original in-place mode remains for the private post-Refine working PA.
local output_path = arg[8] or path
local function triple(text)
  local result = {}
  for value in assert(text, 'grid argument required'):gmatch('[^,]+') do
    result[#result+1] = assert(tonumber(value), 'numeric grid argument required')
  end
  assert(#result == 3, 'three grid values required')
  return result
end
local full, pitch, start, width = triple(arg[4]), triple(arg[5]), triple(arg[6]), triple(arg[7])
assert(path and csv_path and report_path, 'PA, samples CSV and receipt required')
for axis=1,3 do
  assert(full[axis] == math.floor(full[axis]) and full[axis] > 4, 'full grid too small')
  assert(pitch[axis] > 0 and pitch[axis] < math.huge, 'positive finite pitch required')
  assert(start[axis] == 0, 'only origin-preserving x crop supported')
  assert(width[axis] == math.floor(width[axis]) and width[axis] >= 4 and width[axis] < full[axis], 'invalid crop width')
end
assert(width[1] < full[1]-1 and width[2] == full[2]-1 and width[3] == full[3]-1, 'only solved x support may be removed')
local consumer = {width[1]+1, width[2]+1, width[3]+1}
local function header(p, shape)
  assert(p.nx == shape[1] and p.ny == shape[2] and p.nz == shape[3], 'PA dimensions differ')
  assert(p.symmetry == '3dplanar[x]', 'x mirror differs')
  assert(p.dx_mm == pitch[1] and p.dy_mm == pitch[2] and p.dz_mm == pitch[3], 'PA pitch differs')
end
local pa = assert(simion.pas:open(path))
header(pa, full)
local before_refined, before_refinable = pa.refined, pa.refinable
local csv = assert(io.open(csv_path, 'w'))
csv:write('stage,kind,index,x_grid,y_grid,z_grid,node_potential_v,electrode,potential_vc_v,ex_v_per_mm,ey_v_per_mm,ez_v_per_mm,surface_x,surface_y,surface_z\n')
local function finite(v) return type(v) == 'number' and v == v and math.abs(v) < math.huge end
local function pack(v)
  if v == nil then return '' elseif type(v) == 'boolean' then return tostring(v) end
  return string.format('%.17g', v)
end
local function sample(p, xyz, field)
  local x,y,z = math.floor(math.abs(xyz[1])), math.floor(xyz[2]), math.floor(xyz[3])
  local v,e = p:point(x,y,z)
  assert(finite(v), 'nonfinite node potential')
  local sx,sy,sz
  if x < width[1] and y < width[2] and z < width[3] then sx,sy,sz = p:surface_info(x,y,z) end
  local pv,ex,ey,ez
  if field then
    pv = p:potential_vc(unpack(xyz))
    ex,ey,ez = p:field_vc(unpack(xyz))
    assert(finite(pv) and finite(ex) and finite(ey) and finite(ez), 'nonfinite native V/E')
    ex,ey,ez = ex/pitch[1], ey/pitch[2], ez/pitch[3]
  end
  return {v=v,e=e,pv=pv,ex=ex,ey=ey,ez=ez,sx=sx,sy=sy,sz=sz}
end
local function row(stage, kind, i, xyz, s)
  csv:write(table.concat({stage,kind,tostring(i),pack(xyz[1]),pack(xyz[2]),pack(xyz[3]),pack(s.v),pack(s.e),pack(s.pv),pack(s.ex),pack(s.ey),pack(s.ez),pack(s.sx),pack(s.sy),pack(s.sz)}, ',')..'\n')
end
-- Sparse original solve faces, including the removed face: provenance, not a bound.
for face=1,5 do for j=0,9 do
  local x = math.floor((j%5)*(full[1]-1)/4)
  local y,z = math.floor(j*(full[2]-1)/9), math.floor(j*(full[3]-1)/9)
  local xyz
  if face == 1 then xyz = {full[1]-1,y,z}
  elseif face == 2 then xyz = {x,0,z}
  elseif face == 3 then xyz = {x,full[2]-1,z}
  elseif face == 4 then xyz = {x,y,0}
  else xyz = {x,y,full[3]-1} end
  row('full_solved','original_face',(face-1)*10+j+1,xyz,sample(pa,xyz,false))
end end
local probes = {}
local function probe(xyz, field, kind)
  local item = {xyz=xyz,field=field,ref=sample(pa,xyz,field)}
  probes[#probes+1] = item
  row('before_crop',kind,#probes,xyz,item.ref)
end
for j=0,49 do
  local xyz = {math.floor((j%5)*width[1]/4),
    1+math.floor((j%10)*(width[2]-2)/9),1+math.floor(math.floor(j/10)*(width[3]-2)/4)}
  probe(xyz,xyz[1] <= width[1]-2,'retained_node')
end
for _,x in ipairs({-(width[1]-2),0,width[1]-2}) do
  for _,fraction in ipairs({1/3,2/3}) do
    probe({x,math.floor(width[2]/2),math.floor(width[3]*fraction)},true,'mirror_interior')
  end
end
-- Nine retained-cell lines only, not a full-volume surface scan.
local surfaces = {}
for _,x in ipairs({0,math.floor(width[1]/2),width[1]-2}) do
  for _,y in ipairs({1,math.floor(width[2]/2),width[2]-1}) do
    for z=0,width[3]-1 do
      local sx,sy,sz = pa:surface_info(x,y,z)
      if sx or sy or sz then surfaces[#surfaces+1] = {xyz={x,y,z},sx=sx,sy=sy,sz=sz} end
    end
  end
end
local function compare(p, stage)
  for i,item in ipairs(probes) do
    local s = sample(p,item.xyz,item.field)
    for _,key in ipairs({'v','e','pv','ex','ey','ez','sx','sy','sz'}) do
      assert(s[key] == item.ref[key], stage..' retained sample differs: '..i..' '..key)
    end
    row(stage,'retained_sample',i,item.xyz,s)
  end
  for i,item in ipairs(surfaces) do
    local sx,sy,sz = p:surface_info(unpack(item.xyz))
    assert(sx == item.sx and sy == item.sy and sz == item.sz, stage..' fractional witness differs')
    row(stage,'fractional_witness',i,item.xyz,sample(p,item.xyz,false))
  end
end
local clock = os.clock()
pa:crop(start[1],start[2],start[3],width[1],width[2],width[3],false)
header(pa,consumer)
compare(pa,'after_crop')
local after_refined, after_refinable = pa.refined, pa.refinable
local saved,message = pa:save(output_path)
assert(saved ~= false, message or 'crop save failed')
pa:close()
pa = assert(simion.pas:open(output_path))
header(pa,consumer)
compare(pa,'after_reload')
local report = assert(io.open(report_path,'w'))
report:write(string.format('{"status":"PASS","full_dimensions":[%d,%d,%d],"consumer_dimensions":[%d,%d,%d],"retained_sample_count":%d,"fractional_witness_count":%d,"cpu_seconds":%.17g,"before_refined":%s,"after_crop_refined":%s,"reloaded_refined":%s,"before_refinable":%s,"after_crop_refinable":%s,"reloaded_refinable":%s,"refine_after_crop":false,"qualification":false}\n',full[1],full[2],full[3],consumer[1],consumer[2],consumer[3],#probes,#surfaces,os.clock()-clock,tostring(before_refined),tostring(after_refined),tostring(pa.refined),tostring(before_refinable),tostring(after_refinable),tostring(pa.refinable)))
report:close(); csv:close(); pa:close()
print('OFFICIAL_FULL_REFINE_CROP_RELOAD PASS')
if #surfaces == 0 then print('FRACTIONAL_WITNESS unavailable: bounded scan found no offsets; no preservation qualification') end
