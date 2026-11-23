-- Long-term native regression fixture, not a production flight workflow.
-- Usage: simion --nogui --noprompt lua THIS context.lua validate|query|prepare|fly [ordinal]
-- Public orchestration owns directories, immutable PA copies, leases and scheduling.
-- Official collision semantics: https://simion.com/info/faq.html (Modify/View sizes)
-- Fractional surfaces affect Refine, not exact Fly collision:
-- https://simion.com/info/surface_enhancement.html
-- Coordinate conversions: installed examples/collision_sds/collision_sds.lua.
local context_path=assert(arg[1],'fixture context required')
local stage=assert(arg[2],'fixture stage required')
local c=assert(loadfile(context_path))()
local function finite(x) return type(x)=='number' and x==x and math.abs(x)<math.huge end
local function vector(v,n)
 assert(type(v)=='table' and #v==n,'invalid vector')
 for _,x in ipairs(v) do assert(finite(x),'nonfinite vector') end
end
local function read(path)
 local f=assert(io.open(path,'rb'));local s=f:read('*a');f:close();return s
end
local function write(path,s)
 local f=assert(io.open(path,'wb'));f:write(s);f:close()
end
local function serial(v)
 if type(v)=='string' then return string.format('%q',v)
 elseif type(v)=='number' then assert(finite(v));return string.format('%.17g',v)
 elseif type(v)=='boolean' then return tostring(v)
 elseif type(v)=='table' then
  local parts={};for k,x in pairs(v) do parts[#parts+1]='['..serial(k)..']='..serial(x) end
  table.sort(parts);return '{'..table.concat(parts,',')..'}'
 end
 error('unsupported context value')
end
local function csv(v)
 if type(v)=='number' then return string.format('%.17g',v) end
 if type(v)=='boolean' then return v and '1' or '0' end
 return '"'..tostring(v):gsub('"','""')..'"'
end
local function row(f,values)
 local cells={};for i,v in ipairs(values) do cells[i]=csv(v) end
 f:write(table.concat(cells,',')..'\n')
end
local function normalized(path) return path:gsub('\\','/'):gsub('/+$',''):lower() end
local function child(path)
 assert(type(path)=='string' and not path:find('%.%.'),'invalid fixture child path')
 local base=normalized(c.output_directory)..'/'
 assert(normalized(path):sub(1,#base)==base,'fixture writes must stay in output_directory')
end
assert(c.schema_version==1 and c.role=='mrtof_native_collision_fixture','wrong fixture contract')
assert(stage=='validate' or stage=='query' or stage=='prepare' or stage=='fly','unknown fixture stage')
for _,key in ipairs({'output_directory','private_iob','private_pa','seed_iob','production_driver','recording_path'}) do
 assert(type(c[key])=='string' and #c[key]>0,'missing fixture path '..key)
end
assert(c.trajectory_quality==8,'declare Q8 identically for program on/off')
assert(type(c.fields)=='table' and #c.fields>0 and type(c.cases)=='table' and #c.cases>0,'empty matrix')
assert(type(c.paths)=='table' and #c.paths==3,'three declared straight paths required')
local fields,ids,directories={},{ },{}
for _,f in ipairs(c.fields) do
 assert(type(f.field_id)=='string' and not fields[f.field_id],'duplicate field')
 fields[f.field_id]=f;child(f.directory)
 assert(not directories[normalized(f.directory)],'duplicate output directory');directories[normalized(f.directory)]=true
 vector(f.box_mm,6);vector(f.pitch_mm,3)
 assert(f.box_mm[1]==0 and f.voltage_v==0,'fixture requires x mirror and exact zero field')
 assert(f.kind=='rod' or f.kind=='solid_block' or f.kind=='vacuum','unknown fixture field')
 for a=1,3 do
  local span=f.box_mm[a+3]-f.box_mm[a]
  local n=span/f.pitch_mm[a]
  assert(f.pitch_mm[a]>0 and n>=4 and math.abs(n-math.floor(n+.5))<1e-7,'grid does not align')
 end
 if f.kind=='rod' then
  vector(f.center_mm,3)
  assert(f.center_mm[1]==0 and finite(f.radius_mm) and f.radius_mm>0 and finite(f.length_mm) and f.length_mm>0,'invalid rod')
 elseif f.kind=='solid_block' then vector(f.block_box_mm,6) end
end
for _,case in ipairs(c.cases) do
 assert(type(case.case_id)=='string' and not ids[case.case_id],'duplicate case')
 ids[case.case_id]=true;child(case.directory)
 assert(not directories[normalized(case.directory)],'duplicate output directory');directories[normalized(case.directory)]=true
 assert(fields[case.field_id],'unknown field reference')
 assert(case.program_mode=='off' or case.program_mode=='logging_only','invalid program control')
end
for i,p in ipairs(c.paths) do
 vector(p.position_mm,3)
 assert(p.particle_id==i and finite(p.mass_amu) and p.mass_amu>0 and p.charge_state==1 and finite(p.ke_ev) and p.ke_ev>0,'invalid particle')
 assert(p.time_us==0,'fixture clock must be explicit zero')
end
assert(finite(c.stop_z_mm) and finite(c.nominal_y_mm),'missing fixture observation position')
for _,points in ipairs({c.probe_points,c.paths_for_query}) do
 assert(type(points)=='table' and #points>0,'missing query points')
 for _,p in ipairs(points) do assert(type(p.name)=='string');vector(p.position_mm,3) end
end
for _,f in ipairs(c.fields) do
 for _,p in ipairs(c.paths) do
  for a=1,3 do assert(p.position_mm[a]>f.box_mm[a] and p.position_mm[a]<f.box_mm[a+3],'source outside fixture PA') end
 end
 assert(c.stop_z_mm>f.box_mm[3]+f.pitch_mm[3] and c.stop_z_mm<f.box_mm[6]-f.pitch_mm[3],'observation must be inside stop plates')
end
if stage=='validate' then print('COLLISION_FIXTURE_CONTEXT=PASS cases='..#c.cases);return end

local function query(wb,points,prefix)
 local report=assert(io.open(prefix..'_points.csv','wb'))
 report:write('name,selected_instance,find_at_value_type,find_at_value,world_x_mm,world_y_mm,world_z_mm,pa_x_gu,pa_y_gu,pa_z_gu,array_x_gu,array_y_gu,array_z_gu,roundtrip_x_mm,roundtrip_y_mm,roundtrip_z_mm,nearest_electrode\n')
 local corners=assert(io.open(prefix..'_corners.csv','wb'))
 corners:write('name,ix,iy,iz,electrode,potential_v,node_x_mm,node_y_mm,node_z_mm\n')
 for _,p in ipairs(points) do
  local x,y,z=unpack(p.position_mm)
  local electrode,index=wb:find_at(x,y,z)
  assert(type(index)=='number' and index>=1,'query point outside all PA instances')
  local instance=assert(wb.instances[index]);local pa=instance.pa
  local px,py,pz=instance:wb_to_pa_coords(x,y,z)
  local ax,ay,az=instance:pa_to_array_coords(px,py,pz)
  local rx,ry,rz=instance:pa_to_wb_coords(px,py,pz)
  assert(math.abs(rx-x)<1e-9 and math.abs(ry-y)<1e-9 and math.abs(rz-z)<1e-9,'coordinate roundtrip differs')
  row(report,{p.name,index,type(electrode),tostring(electrode),x,y,z,px,py,pz,ax,ay,az,rx,ry,rz,pa:electrode(math.floor(ax+.5),math.floor(ay+.5),math.floor(az+.5))})
  local ix,iy,iz=math.floor(ax),math.floor(ay),math.floor(az)
  for dx=0,1 do for dy=0,1 do for dz=0,1 do
   local nx,ny,nz=ix+dx,iy+dy,iz+dz
   -- Canonical positive-x image; mirror sign remains in pa_* versus array_*.
   local wx,wy,wz=instance:pa_to_wb_coords(nx,ny,nz)
   row(corners,{p.name,nx,ny,nz,pa:electrode(nx,ny,nz),pa:potential(nx,ny,nz),wx,wy,wz})
  end end end
 end
 report:close();corners:close()
end
if stage=='query' then
 simion.pas:close();local wb=simion.wb;wb:load(c.private_iob)
 assert(#wb.instances==1,'actual diagnostic expects one declared local instance')
 assert(normalized(wb.instances[1].pa.path)==normalized(c.private_pa),'actual IOB resolves outside private PA')
 query(wb,c.probe_points,c.output_directory..'/actual')
 print('COLLISION_FIXTURE_QUERY=PASS');return
end

local function nums(v)
 local values={};for i,x in ipairs(v) do values[i]=string.format('%.17g',x) end
 return table.concat(values,',')
end
local logging_program=[[
simion.workbench_program()
local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])'))
local stream
local function emit(event)
 stream:write(string.format('%s,%d,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%d,%d,%.17g,%.17g,%.17g\n',event,ion_number,ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_splat,ion_instance,ion_px_abs_gu,ion_py_abs_gu,ion_pz_abs_gu))
end
function segment.initialize_run()
 stream=assert(io.open(directory..'callbacks.csv','wb'))
 stream:write('event,particle_id,time_us,x_mm,y_mm,z_mm,vx_mm_per_us,vy_mm_per_us,vz_mm_per_us,ion_splat,ion_instance,px_abs_gu,py_abs_gu,pz_abs_gu\n')
end
function segment.initialize() emit('birth') end
function segment.other_actions() emit('sample') end
function segment.terminate() emit('terminal');stream:flush() end
function segment.terminate_run() if stream then stream:close();stream=nil end end
]]
if stage=='prepare' then
 for _,f in ipairs(c.fields) do
  local pitch,box=f.pitch_mm,f.box_mm;local dims={}
  for a=1,3 do dims[a]=math.floor((box[a+3]-box[a])/pitch[a]+.5)+1 end
  local lines={'pa_define('..nums(dims)..',planar,x,electrostatic,,'..nums(pitch)..',surface=fractional)',
   'locate('..nums({-box[1],-box[2],-box[3]})..') {','e(0) {'}
  -- Two-node-layer physical stop plates, pitch-derived, not epsilon masks.
  lines[#lines+1]='fill { within { box3d('..nums({box[1],box[2],box[3],box[4],box[5],box[3]+pitch[3]})..') } }'
  lines[#lines+1]='fill { within { box3d('..nums({box[1],box[2],box[6]-pitch[3],box[4],box[5],box[6]})..') } }'
  if f.kind=='rod' then
   local x,y,z=unpack(f.center_mm)
   lines[#lines+1]='fill { within { cylinder3d('..nums({x,y,z-f.length_mm/2,x,y,z+f.length_mm/2,f.radius_mm})..') } }'
  elseif f.kind=='solid_block' then lines[#lines+1]='fill { within { box3d('..nums(f.block_box_mm)..') } }' end
  lines[#lines+1]='} }';write(f.directory..'/field.gem',table.concat(lines,'\n')..'\n')
  simion.pas:close()
  simion.command(string.format('gem2pa %q %q',f.directory..'/field.gem',f.directory..'/field.pa'))
  local pa=assert(simion.pas:open(f.directory..'/field.pa'))
  for iz=0,dims[3]-1 do for iy=0,dims[2]-1 do for ix=0,dims[1]-1 do
   assert(pa:potential(ix,iy,iz)==0,'zero-field fixture contains nonzero potential')
  end end end
  pa.refined,pa.refinable=true,false;pa:save(f.directory..'/field.pa');pa:close()
 end
 local receipt=assert(io.open(c.output_directory..'/prepared_cases.csv','wb'))
 receipt:write('case_id,field_id,program_mode,iob,field_pa,particles\n')
 for _,case in ipairs(c.cases) do
  local f=fields[case.field_id];local source,beams={},{}
  for _,p in ipairs(c.paths) do
   local x,y,z=unpack(p.position_mm)
   -- FLY2 is the source authority; program only records actual vendor births.
   beams[#beams+1]=string.format('standard_beam { n=1,mass=%.17g,charge=%d,ke=%.17g,tob=0,position=vector(%.17g,%.17g,%.17g),direction=vector(0,0,-1) }',p.mass_amu,p.charge_state,p.ke_ev,x,y,z)
   source[#source+1]={particle_id=p.particle_id,x_mm=x,y_mm=y,z_mm=z}
  end
  local config={case_id=case.case_id,field_path=f.directory..'/field.pa',workbench_seed_path=c.seed_iob,
   box_mm=f.box_mm,pitch_mm=f.pitch_mm,source=source,exit_z_mm=c.paths[1].position_mm[3],
   observation_planes={{name='fixture_stop',z_mm=c.stop_z_mm}},probe_step_mm=f.pitch_mm[3],
   nominal_y_mm=c.nominal_y_mm,trajectory_quality=c.trajectory_quality,convergence_v=1e-6}
  write(case.directory..'/case_config.lua','return '..serial(config)..'\n')
  write(case.directory..'/local.lua',logging_program)
  write(case.directory..'/local.fly2','particles {\n'..table.concat(beams,',\n')..'\n}\n')
  write(case.directory..'/run_case.lua',read(c.production_driver))
  assert(loadfile(case.directory..'/run_case.lua'))('assemble')
  query(simion.wb,c.paths_for_query,case.directory..'/initial_grid')
  row(receipt,{case.case_id,case.field_id,case.program_mode,case.directory..'/local.iob',f.directory..'/field.pa',case.directory..'/local.fly2'})
 end
 receipt:close();print('COLLISION_FIXTURE_PREPARE=PASS refine=0 fly=0');return
end
local ordinal=assert(tonumber(arg[3]),'fly ordinal required')
assert(ordinal==math.floor(ordinal),'integer fly ordinal required')
local case=assert(c.cases[ordinal],'fly ordinal outside declared matrix')
local enabled=case.program_mode=='logging_only' and 1 or 0
-- Official installed examples/tof/README.html steps 8-9 document tof.rec as
-- impact-time recording. Its immutable bytes are an explicit context input.
-- Native Fly --help documents all three recording options. Never decode or
-- synthesize the proprietary REC format here; preserve raw vendor output.
print('COLLISION_FIXTURE_FLY_BEGIN '..case.case_id..' programs='..enabled)
simion.command(string.format('fly --programs=%d --trajectory-quality=%d --retain-trajectories=0 --recording=%q --recording-enable=1 --recording-output=%q --particles=%q %q',enabled,c.trajectory_quality,c.recording_path,case.directory..'/native_recording.txt',case.directory..'/local.fly2',case.directory..'/local.iob'))
print('COLLISION_FIXTURE_FLY_RETURN '..case.case_id)
