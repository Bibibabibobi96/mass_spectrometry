-- Passive extraction audit using official SIMION field_vc unit responses.
-- No particle state, timestep, random stream, q/m or field is modified here.
local M={}
local components={'x','y','z'}
local state_keys={'t','x','y','z','vx','vy','vz'}
local step_header='particle_id,step_index,start_t_us,end_t_us,start_x_mm,start_y_mm,start_z_mm,end_x_mm,end_y_mm,end_z_mm,start_post_vx_mm_us,start_post_vy_mm_us,start_post_vz_mm_us,end_pre_vx_mm_us,end_pre_vy_mm_us,end_pre_vz_mm_us,end_post_vx_mm_us,end_post_vy_mm_us,end_post_vz_mm_us,pressure_pa'
local impulse_header='particle_id,step_index,electrode_id,start_t_us,end_t_us,integral_ex_v_us_per_mm,integral_ey_v_us_per_mm,integral_ez_v_us_per_mm,fine_minus_coarse_ex_v_us_per_mm,fine_minus_coarse_ey_v_us_per_mm,fine_minus_coarse_ez_v_us_per_mm,max_reconstruction_error_v_per_mm,unit_integral_ex_us_per_mm,unit_integral_ey_us_per_mm,unit_integral_ez_us_per_mm'
M.step_header=step_header
M.impulse_header=impulse_header

local function finite(value)
 assert(type(value)=='number' and value==value and value~=math.huge and value~=-math.huge,'nonfinite force-audit value')
 return value
end
local function state_copy(state)
 local copy={}
 for _,key in ipairs(state_keys) do copy[key]=finite(state[key]) end
 return copy
end
local function write_row(stream,values)
 local fields={}
 for index,value in ipairs(values) do fields[index]=string.format('%.17g',finite(value)) end
 assert(stream:write(table.concat(fields,',')..'\n'))
end
local function vector(rotation,v,inverse)
 local result={0,0,0}
 for i=1,3 do for j=1,3 do
  result[i]=result[i]+(inverse and rotation[j][i] or rotation[i][j])*v[j]
 end end
 return result
end
local function left_limit(time)
 -- Previous IEEE-754 binary64 value; 53 is significand precision, not a
 -- physical switching tolerance. Only voltage evaluation is nudged.
 if time==0 then return -math.ldexp(1,-1074) end
 local mantissa,exponent=math.frexp(math.abs(time))
 local gap=math.ldexp(1,exponent-53)
 if time>0 and mantissa==.5 then gap=gap/2 end
 return time-gap
end
M.left_limit=left_limit

local function hermite(start,finish,time)
 local span=finish.t-start.t
 local u=(time-start.t)/span
 local u2,u3=u*u,u*u*u
 local position={}
 for i,axis in ipairs(components) do
  position[i]=(2*u3-3*u2+1)*start[axis]+(u3-2*u2+u)*span*start['v'..axis]+
   (-2*u3+3*u2)*finish[axis]+(u3-u2)*span*finish['v'..axis]
 end
 return position
end
M.hermite=hermite

function M.new(c,pa,drive,rf,directory)
 assert(pa and type(pa.field_vc)=='function' and type(pa.inside_vc)=='function',
  'force audit requires official PA field_vc and inside_vc')
 local projection,timing=c.native_projection,c.native_timing
 assert(#projection.electrode_ids==15,'force audit requires the declared 15-electrode basis')
 local rotation=c.coordinate_transform and c.coordinate_transform.rotation or {{1,0,0},{0,1,0},{0,0,1}}
 local translation=c.coordinate_transform and c.coordinate_transform.translation_mm or {0,0,0}
 local grid=finite(projection.grid_mm)
 assert(grid>0,'force audit PA grid must be positive')
 local basis={}
 for id=1,15 do
  assert(projection.electrode_ids[id]==id,'force audit electrode order differs')
  basis[id]={}
  for other=1,15 do basis[id][other]=other==id and 1 or 0 end
 end
 local function field(position,voltages)
  local local_position=vector(rotation,{position[1]-translation[1],position[2]-translation[2],position[3]-translation[3]},true)
  local gu={}
  for i=1,3 do gu[i]=(local_position[i]-projection.origin_mm[i])/grid end
  assert(pa:inside_vc(gu[1],gu[2],gu[3]),'force-audit Hermite query lies outside native PA')
  local ex,ey,ez=pa:field_vc(gu[1],gu[2],gu[3],voltages)
  return vector(rotation,{finite(ex)/grid,finite(ey)/grid,finite(ez)/grid},false)
 end
 -- Load the same native response family used by Fly before the first formal
 -- resource observation, without Fast Adjust, Save, Refine or particle calls.
 local warm=vector(rotation,{c.baseline.geometry.lp_center_mm,0,0},false)
 for i=1,3 do warm[i]=warm[i]+translation[i] end
 for id=1,15 do field(warm,basis[id]) end
 local steps=assert(io.open(directory..'extraction_steps.csv','w'))
 local impulses,message=io.open(directory..'extraction_impulses.csv','w')
 if not impulses then steps:close();error(message) end
 steps:write(step_header..'\n');impulses:write(impulse_header..'\n')
 local previous,indices={},{}
 local closed=false
 local boundaries={timing.primary_quench_us,timing.side_quench_us,timing.pulse_start_us}
 local function is_boundary(time)
  for _,boundary in ipairs(boundaries) do if time==boundary then return true end end
  return false
 end
 local function integrate(start,finish)
  local fine,coarse,unit={},{},{}
  for id=1,15 do fine[id]={0,0,0};coarse[id]={0,0,0};unit[id]={0,0,0} end
  local maximum_error=0
  if finish.t==start.t then return fine,coarse,unit,maximum_error end
  local cuts={start.t}
  for _,boundary in ipairs(boundaries) do
   if start.t<boundary and boundary<finish.t then cuts[#cuts+1]=boundary end
  end
  table.sort(cuts)
  -- Side quench and pulse deliberately share a boundary; integrate it once.
  local unique={cuts[1]}
  for i=2,#cuts do if cuts[i]~=unique[#unique] then unique[#unique+1]=cuts[i] end end
  unique[#unique+1]=finish.t
  local weights_fine,weights_coarse={1,4,2,4,1},{1,0,4,0,1}
  for cut=1,#unique-1 do
   local a,b=unique[cut],unique[cut+1]
   local duration=b-a
   for node=1,5 do
    local time=a+duration*(node-1)/4
    local voltage_time=(node==5 and is_boundary(b)) and left_limit(b) or time
    local voltages=drive.voltages(c,voltage_time,rf.differential_at(c.baseline.clock.epoch_us+voltage_time))
    assert(#voltages==15,'force audit voltage vector differs')
    local position=hermite(start,finish,time)
    local total=field(position,voltages)
    local reconstructed={0,0,0}
    for id=1,15 do
     local response=field(position,basis[id])
     for axis=1,3 do
      local weighted=response[axis]*finite(voltages[id])
      reconstructed[axis]=reconstructed[axis]+weighted
      fine[id][axis]=fine[id][axis]+duration*weights_fine[node]*weighted/12
      coarse[id][axis]=coarse[id][axis]+duration*weights_coarse[node]*weighted/6
      unit[id][axis]=unit[id][axis]+duration*weights_fine[node]*response[axis]/12
     end
    end
    for axis=1,3 do maximum_error=math.max(maximum_error,math.abs(total[axis]-reconstructed[axis])) end
   end
  end
  return fine,coarse,unit,maximum_error
 end
 local audit={}
 function audit:observe(id,pre,post,pressure)
  assert(not closed,'force audit is closed')
  assert(type(id)=='number' and id>=1 and id==math.floor(id),'invalid force-audit particle ID')
  pre,post=state_copy(pre),state_copy(post)
  assert(pre.t==post.t and pre.x==post.x and pre.y==post.y and pre.z==post.z,
   'HS1 audit must bracket velocity changes at the same time and position')
  assert(finite(pressure)>=0,'negative force-audit pressure')
  if pre.t<timing.primary_quench_us then previous[id]=post;return end
  local start=previous[id]
  if not indices[id] then
   -- Zero-duration anchor keeps any collision applied at the first audited
   -- boundary. Its start velocity is the pre-HS1 value, explicitly not an
   -- invented state before an unrecorded interval.
   start=pre
  end
  assert(start and pre.t>=start.t,'nonmonotone force-audit time')
  indices[id]=(indices[id] or 0)+1
  local index=indices[id]
  write_row(steps,{id,index,start.t,pre.t,start.x,start.y,start.z,pre.x,pre.y,pre.z,
   start.vx,start.vy,start.vz,pre.vx,pre.vy,pre.vz,post.vx,post.vy,post.vz,pressure})
  local fine,coarse,unit,reconstruction=integrate(start,pre)
  for electrode=1,15 do
   local f,k,u=fine[electrode],coarse[electrode],unit[electrode]
   write_row(impulses,{id,index,electrode,start.t,pre.t,f[1],f[2],f[3],f[1]-k[1],f[2]-k[2],f[3]-k[3],reconstruction,u[1],u[2],u[3]})
  end
  previous[id]=post
 end
 function audit:close()
  if not closed then steps:close();impulses:close();closed=true end
 end
 return audit
end
return M
