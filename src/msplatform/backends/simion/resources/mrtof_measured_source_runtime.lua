-- Pure loader module: compose with the downstream workbench program.
local M = {}
function M.load(directory)
  local states = assert(loadfile(directory..'/source_states.lua'))()
  local point = assert(loadfile(directory..'/source_projection.lua'))()
  local runtime = {}
  local function source(ordinal)
    assert(type(ordinal)=='number' and ordinal%1==0, 'invalid SIMION ordinal')
    return assert(point.mapping[ordinal], 'unmapped SIMION ordinal')
  end
  function runtime.source_id(ordinal) return source(ordinal).particle_id end
  function runtime.instrument_time_us(solver_time_us)
    assert(type(solver_time_us)=='number' and solver_time_us>=0 and solver_time_us<math.huge,
      'invalid solver clock')
    return point.epoch_us + solver_time_us
  end
  function runtime.initialize(ordinal)
    -- Pure data boundary: ordinary loadfile does not inherit the workbench
    -- reserved-variable environment (SIMION manual L-31 / lua_scope.html).
    local mapping = source(ordinal)
    local state = assert(states[ordinal], 'missing measured source state')
    return {mass=mapping.mass_amu, charge=mapping.charge_state, t=state.t,
      x=state.x, y=state.y, z=state.z, vx=state.vx, vy=state.vy, vz=state.vz}
  end
  function runtime.restore_event_state(ordinal, solver_time_us, x,y,z,vx,vy,vz)
    local mapping = source(ordinal)
    assert(solver_time_us >= states[ordinal].t, 'event precedes measured handoff')
    local absolute_time = runtime.instrument_time_us(solver_time_us)
    return {particle_id=mapping.particle_id, clock_epoch_id=point.clock_epoch_id,
      instrument_time_us=absolute_time, frame_id=point.frame_id,
      particle_birth_time_us=mapping.particle_birth_time_us,
      lineage_birth_time_us=mapping.lineage_birth_time_us,
      particle_age_us=absolute_time-mapping.particle_birth_time_us,
      lineage_age_us=absolute_time-mapping.lineage_birth_time_us,
      last_component_elapsed_time_us=solver_time_us-states[ordinal].t,
      position_x_mm=x, position_y_mm=y, position_z_mm=z,
      velocity_x_m_s=vx*1000, velocity_y_m_s=vy*1000, velocity_z_m_s=vz*1000}
  end
  runtime.particle_count = #point.mapping
  runtime.clock_epoch_id, runtime.epoch_us = point.clock_epoch_id, point.epoch_us
  return runtime
end
return M
