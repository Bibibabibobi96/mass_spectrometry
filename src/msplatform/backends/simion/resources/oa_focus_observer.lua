-- Focus events retain native endpoint and interpolated plane state separately.
-- Caller provides the already frozen SIMION TestPlane implementation.
local M={}
function M.new(spec,TestPlane,clock,particle_id,emit)
  local previous,candidates,finished,invalid={},{},{},{}
  local planes={}
  for _,row in ipairs(spec.planes) do
    local c,n=row.center_mm,row.normal
    planes[#planes+1]={definition=row, test=TestPlane(c[1],c[2],c[3],n[1],n[2],n[3],function() end)}
  end
  local function state()
    return {t=clock(),x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm,instance=ion_instance}
  end
  local function dot(a,b) return a[1]*b[1]+a[2]*b[2]+a[3]*b[3] end
  local function serial_close(a,b)
    local scale=math.max(1,math.abs(a),math.abs(b))
    local _,exponent=math.frexp(scale)
    return math.abs(a-b)<=32*2^(exponent-53)
  end
  local function crossing(p,e,plane)
    if not p or e.t<=p.t then return nil end
    local n,c=plane.normal,plane.center_mm
    local d0=dot({p.x-c[1],p.y-c[2],p.z-c[3]},n)
    local d1=dot({e.x-c[1],e.y-c[2],e.z-c[3]},n)
    local v0=dot({p.vx,p.vy,p.vz},n);local v1=dot({e.vx,e.vy,e.vz},n)
    if d0>0 or d1<0 or d1<=d0 or v0<=0 or v1<=0 then return nil end
    local f=-d0/(d1-d0)
    return {t=p.t+f*(e.t-p.t),x=p.x+f*(e.x-p.x),y=p.y+f*(e.y-p.y),z=p.z+f*(e.z-p.z),
      vx=p.vx+f*(e.vx-p.vx),vy=p.vy+f*(e.vy-p.vy),vz=p.vz+f*(e.vz-p.vz),before=d0,after=d1,start=p,endpoint=e}
  end
  local function write(id,hit)
    local p,e=hit.start,hit.endpoint
    emit(string.format('PLANE_OBSERVATION_V1: observation_id=%s ion=%d particle_id=%.0f direction=outward occurrence=1 instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g step_start_instrument_time_us=%.17g step_end_instrument_time_us=%.17g signed_distance_before_mm=%.17g signed_distance_after_mm=%.17g step_start_x_mm=%.17g step_start_y_mm=%.17g step_start_z_mm=%.17g step_end_x_mm=%.17g step_end_y_mm=%.17g step_end_z_mm=%.17g step_start_vx_mm_per_us=%.17g step_start_vy_mm_per_us=%.17g step_start_vz_mm_per_us=%.17g step_end_vx_mm_per_us=%.17g step_end_vy_mm_per_us=%.17g step_end_vz_mm_per_us=%.17g method=accepted_step_linear_interpolation',
      id,ion_number,particle_id(),hit.t,hit.x,hit.y,hit.z,hit.vx,hit.vy,hit.vz,p.t,e.t,hit.before,hit.after,p.x,p.y,p.z,e.x,e.y,e.z,p.vx,p.vy,p.vz,e.vx,e.vy,e.vz))
  end
  return {
    initialize=function() previous[ion_number]=nil;candidates[ion_number]={};finished[ion_number]=false;invalid[ion_number]=false end,
    tstep_adjust=function()
      for _,plane in ipairs(planes) do
        local n=plane.definition.normal
        if not candidates[ion_number][plane.definition.observation_id] and dot({ion_vx_mm,ion_vy_mm,ion_vz_mm},n)>0 then plane.test.tstep_adjust() end
      end
    end,
    other_actions=function()
      local current=state();local p=previous[ion_number];local found=candidates[ion_number]
      for _,plane in ipairs(planes) do plane.test.other_actions() end
      if not p then previous[ion_number]=current;return end
      if p and current.t<p.t then invalid[ion_number]=true end
      if p and current.t==p.t then
        for _,key in ipairs({'x','y','z','vx','vy','vz','instance'}) do
          if current[key]~=p[key] then invalid[ion_number]=true end
        end
      end
      if ion_splat==0 and not finished[ion_number] then
        for _,plane in ipairs(planes) do
          local id=plane.definition.observation_id
          if not found[id] then found[id]=crossing(p,current,plane.definition) end
        end
        if found[spec.focus_id] then
          if not found[spec.exit_id] or found[spec.exit_id].t>found[spec.focus_id].t then invalid[ion_number]=true end
          finished[ion_number]=true;ion_splat=1
        end
      end
      previous[ion_number]=current
    end,
    terminate=function()
      local terminal=state();local found=candidates[ion_number]
      if invalid[ion_number] then
        emit(string.format('OA_FOCUS_INCOMPLETE_V1: ion=%d particle_id=%.0f reason=unresolved_callback_history',ion_number,particle_id()))
        return
      end
      if finished[ion_number] then
        local focus=found[spec.focus_id];local endpoint=focus.endpoint
        local endpoint_match,plane_match=true,true
        for _,key in ipairs({'t','x','y','z','vx','vy','vz','instance'}) do
          if endpoint[key]~=terminal[key] then endpoint_match=false end
          if key=='instance' then
            if endpoint[key]~=terminal[key] then plane_match=false end
          elseif not serial_close(focus[key],terminal[key]) then plane_match=false end
        end
        if not endpoint_match and not plane_match then
          emit(string.format('OA_FOCUS_INCOMPLETE_V1: ion=%d particle_id=%.0f reason=terminal_endpoint_mismatch',ion_number,particle_id()))
          return
        end
        emit(string.format('OA_FOCUS_STOP_V1: ion=%d particle_id=%.0f endpoint_time_us=%.17g terminal_mode=%s',ion_number,particle_id(),terminal.t,endpoint_match and 'action_endpoint' or 'plane_reconciled'))
      end
      for _,hit in pairs(found) do
        if terminal.t<hit.endpoint.t and (not finished[ion_number] or not serial_close(terminal.t,found[spec.focus_id].t) or (hit.t>terminal.t and not serial_close(hit.t,terminal.t))) then
          emit(string.format('OA_FOCUS_INCOMPLETE_V1: ion=%d particle_id=%.0f reason=terminal_before_candidate',ion_number,particle_id()))
          return
        end
        if terminal.t==hit.endpoint.t then
          for _,key in ipairs({'x','y','z','vx','vy','vz','instance'}) do
            if terminal[key]~=hit.endpoint[key] then
              emit(string.format('OA_FOCUS_INCOMPLETE_V1: ion=%d particle_id=%.0f reason=terminal_endpoint_mismatch',ion_number,particle_id()))
              return
            end
          end
        end
      end
      for _,plane in ipairs(planes) do
        local id=plane.definition.observation_id
        if found[id] then write(id,found[id]) end
      end
    end,
  }
end
return M
