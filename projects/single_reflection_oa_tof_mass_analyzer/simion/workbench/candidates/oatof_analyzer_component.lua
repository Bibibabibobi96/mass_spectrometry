-- Callback-neutral oaTOF analyzer behavior for assembled Candidate Programs.
-- The caller owns SIMION callbacks, the unique clock, and application of plans.

local component = {}

local function finite(value, name)
  assert(type(value) == 'number' and value == value and
    value ~= math.huge and value ~= -math.huge, name .. ' must be finite')
  return value
end

local function positive(value, name)
  value = finite(value, name)
  assert(value > 0, name .. ' must be positive')
  return value
end

local function integer(value, name)
  value = finite(value, name)
  assert(value == math.floor(value), name .. ' must be an integer')
  return value
end

local function exact_keys(value, expected, name)
  assert(type(value) == 'table', name .. ' must be a table')
  for key in pairs(value) do
    assert(expected[key], name .. ' contains unknown field: ' .. tostring(key))
  end
  for key in pairs(expected) do
    assert(value[key] ~= nil, name .. ' is missing field: ' .. tostring(key))
  end
end

local function validate_electrode_ids(ids, ring_count, three_zone)
  local expected = {repeller=true, grid1=true, rings=true, grid2=true}
  if three_zone then expected.intermediate2 = true end
  exact_keys(ids, expected, 'electrode_ids')
  assert(type(ids.rings) == 'table' and #ids.rings == ring_count,
    'electrode_ids.rings must match accelerator_ring_count')
  local seen = {}
  local function accept(value, name)
    value = integer(value, name)
    assert(value > 0, name .. ' must be positive')
    assert(not seen[value], 'oaTOF electrode IDs must be unique')
    seen[value] = true
    return value
  end
  local validated = {
    repeller=accept(ids.repeller, 'electrode_ids.repeller'),
    grid1=accept(ids.grid1, 'electrode_ids.grid1'),
    rings={},
    grid2=accept(ids.grid2, 'electrode_ids.grid2'),
  }
  if three_zone then
    validated.intermediate2=accept(ids.intermediate2,
      'electrode_ids.intermediate2')
  end
  for index, value in ipairs(ids.rings) do
    validated.rings[index] = accept(value,
      'electrode_ids.rings[' .. index .. ']')
  end
  return validated
end

local function exact_basename(value, role)
  assert(type(value) == 'string',
    'workbench ' .. role .. ' payload filename must be a string')
  local basename = value:gsub('\\', '/'):match('([^/]+)$')
  assert(basename and basename ~= '',
    'workbench ' .. role .. ' payload basename is missing')
  return basename
end

local function filename_matches(value, expected, role)
  assert(type(expected) == 'string' and expected ~= '' and
      not expected:find('/', 1, true) and not expected:find('\\', 1, true),
    'instance_filenames.' .. role .. ' must be an exact basename')
  assert(exact_basename(value, role) == expected,
    'workbench ' .. role .. ' payload filename differs')
end

function component.new(config)
  exact_keys(config, {instance_roles=true, instance_filenames=true,
    geometry=true, field_modes=true, accelerator_topology_id=true,
    voltages=true, accelerator_ring_count=true, electrode_ids=true,
    reflectron_stage1_ring_count=true, reflectron_stage2_ring_count=true,
    detector=true, diagnostics=true}, 'config')
  exact_keys(config.instance_roles, {flight_tube=true, reflectron=true,
    accelerator=true, detector=true}, 'instance_roles')
  exact_keys(config.instance_filenames, {flight_tube=true, reflectron=true,
    accelerator=true, detector=true}, 'instance_filenames')
  local three_zone = config.accelerator_topology_id == 'three_zone_frontend_v1'
  assert(three_zone or config.accelerator_topology_id == 'two_zone_frontend_v1',
    'accelerator_topology_id is not published')
  local geometry_keys = {accelerator_axis_x_mm=true,
    accelerator_axis_y_mm=true, accelerator_instance_z_mm=true,
    accelerator_repeller_front_z_mm=true, accelerator_grid1_z_mm=true,
    accelerator_grid2_z_mm=true, reflectron_axis_x_mm=true,
    reflectron_axis_y_mm=true, reflectron_entgrid_z_mm=true,
    reflectron_midgrid_z_mm=true, reflectron_backplate_z_mm=true,
    detector_x_mm=true, detector_y_mm=true, detector_z_mm=true,
    detector_radius_mm=true, detector_marker_front_margin_z_mm=true,
    detector_marker_back_margin_z_mm=true,
    detector_marker_absorber_thickness_mm=true,
    diagnostic_return_plane_z_mm=true, flight_tube_near_outer_z_mm=true,
    flight_tube_far_outer_z_mm=true}
  if three_zone then
    geometry_keys.accelerator_intermediate2_z_mm = true
    geometry_keys.accelerator_ring_z_mm = true
  end
  exact_keys(config.geometry, geometry_keys, 'geometry')
  exact_keys(config.field_modes, {ideal_accelerator=true,
    ideal_accelerator_axial=true, ideal_drift_axial=true,
    ideal_reflectron_stage1=true, ideal_reflectron_stage1_axial=true,
    ideal_reflectron_stage2=true, ideal_reflectron_stage2_axial=true},
    'field_modes')
  local voltage_keys = {repeller_v=true, grid1_v=true, mid_v=true,
    backplate_v=true}
  if three_zone then voltage_keys.intermediate2_v=true; voltage_keys.exit_v=true end
  exact_keys(config.voltages, voltage_keys, 'voltages')
  exact_keys(config.detector, {tstep_enabled=true,
    capture_arm_distance_mm=true, capture_depth_mm=true,
    marker_absorber_thickness_mm=true}, 'detector')
  exact_keys(config.diagnostics, {max_tof_us=true, log_stride=true},
    'diagnostics')

  local roles = config.instance_roles
  local payload_filenames = config.instance_filenames
  local role_seen = {}
  for name, value in pairs(roles) do
    value = integer(value, 'instance_roles.' .. name)
    assert(value > 0 and not role_seen[value],
      'instance roles must be unique positive integers')
    role_seen[value] = true
  end
  local g, modes, volts = config.geometry, config.field_modes, config.voltages
  for name, value in pairs(g) do
    if name ~= 'accelerator_ring_z_mm' then finite(value, 'geometry.' .. name) end
  end
  for name, value in pairs(modes) do
    assert(value == true or value == false, 'field_modes.' .. name .. ' must be boolean')
  end
  for name, value in pairs(volts) do finite(value, 'voltages.' .. name) end
  local ring_count = integer(config.accelerator_ring_count,
    'accelerator_ring_count')
  assert(ring_count > 0, 'accelerator_ring_count must be positive')
  local reflectron_stage1_count = integer(config.reflectron_stage1_ring_count,
    'reflectron_stage1_ring_count')
  local reflectron_stage2_count = integer(config.reflectron_stage2_ring_count,
    'reflectron_stage2_ring_count')
  assert(reflectron_stage1_count > 0 and reflectron_stage2_count > 0,
    'reflectron ring counts must be positive')
  local ids = validate_electrode_ids(config.electrode_ids, ring_count, three_zone)
  if three_zone then
    assert(type(g.accelerator_ring_z_mm) == 'table' and
      #g.accelerator_ring_z_mm == ring_count,
      'geometry.accelerator_ring_z_mm must match accelerator_ring_count')
    local previous = g.accelerator_grid1_z_mm
    for index, value in ipairs(g.accelerator_ring_z_mm) do
      value=finite(value, 'geometry.accelerator_ring_z_mm[' .. index .. ']')
      assert(value > previous and value < g.accelerator_grid2_z_mm,
        'accelerator ring z positions must be strictly increasing inside grid1..grid2')
      previous=value
    end
  end
  local detector = config.detector
  assert(detector.tstep_enabled == true or detector.tstep_enabled == false,
    'detector.tstep_enabled must be boolean')
  positive(detector.capture_arm_distance_mm,
    'detector.capture_arm_distance_mm')
  positive(detector.capture_depth_mm, 'detector.capture_depth_mm')
  positive(detector.marker_absorber_thickness_mm,
    'detector.marker_absorber_thickness_mm')
  assert(detector.capture_depth_mm < detector.marker_absorber_thickness_mm,
    'detector capture depth must lie inside the numerical absorber')
  positive(config.diagnostics.max_tof_us, 'diagnostics.max_tof_us')
  local log_stride = integer(config.diagnostics.log_stride,
    'diagnostics.log_stride')
  assert(log_stride > 0, 'diagnostics.log_stride must be positive')

  assert(g.accelerator_repeller_front_z_mm < g.accelerator_grid1_z_mm and
    g.accelerator_grid1_z_mm < g.accelerator_grid2_z_mm,
    'accelerator planes must be strictly increasing')
  if three_zone then
    assert(g.accelerator_grid1_z_mm < g.accelerator_intermediate2_z_mm and
      g.accelerator_intermediate2_z_mm < g.accelerator_grid2_z_mm,
      'three-zone accelerator planes must be strictly increasing')
  end
  assert(g.reflectron_entgrid_z_mm < g.reflectron_midgrid_z_mm and
    g.reflectron_midgrid_z_mm < g.reflectron_backplate_z_mm,
    'reflectron planes must be strictly increasing')

  local particles = {}

  local function accelerator_plan(pulse_state, pulse_voltages)
    assert(pulse_state == 'on' or pulse_state == 'off',
      'pulse_state must be on or off')
    local pulse_keys={pre_all_v=true, repeller_v=true, grid1_v=true}
    if three_zone then pulse_keys.intermediate2_v=true; pulse_keys.exit_v=true end
    exact_keys(pulse_voltages, pulse_keys, 'pulse_voltages')
    for name, value in pairs(pulse_voltages) do
      finite(value, 'pulse_voltages.' .. name)
    end
    local pre = pulse_voltages.pre_all_v
    local repeller = pulse_state == 'on' and pulse_voltages.repeller_v or pre
    local grid1 = pulse_state == 'on' and pulse_voltages.grid1_v or pre
    local plan = {{electrode_id=ids.repeller, voltage_v=repeller},
      {electrode_id=ids.grid1, voltage_v=grid1}}
    for index, electrode_id in ipairs(ids.rings) do
      local ring_voltage
      if three_zone and pulse_state == 'on' then
        local z=g.accelerator_ring_z_mm[index]
        local z0, z1, v0, v1
        if z <= g.accelerator_intermediate2_z_mm then
          z0, z1 = g.accelerator_grid1_z_mm, g.accelerator_intermediate2_z_mm
          v0, v1 = pulse_voltages.grid1_v, pulse_voltages.intermediate2_v
        else
          z0, z1 = g.accelerator_intermediate2_z_mm, g.accelerator_grid2_z_mm
          v0, v1 = pulse_voltages.intermediate2_v, pulse_voltages.exit_v
        end
        ring_voltage=v0+(v1-v0)*(z-z0)/(z1-z0)
      else
        ring_voltage=pulse_state == 'on' and
          pulse_voltages.grid1_v * (ring_count + 1 - index) /
          (ring_count + 1) or pre
      end
      plan[#plan + 1] = {electrode_id=electrode_id,
        voltage_v=ring_voltage}
    end
    if three_zone then
      plan[#plan + 1] = {electrode_id=ids.intermediate2,
        voltage_v=pulse_state == 'on' and pulse_voltages.intermediate2_v or pre}
    end
    plan[#plan + 1] = {electrode_id=ids.grid2,
      voltage_v=three_zone and pulse_state == 'on' and pulse_voltages.exit_v or pre}
    return plan
  end

  local function static_electrode_plans(reflectron_profile)
    if reflectron_profile ~= nil then
      exact_keys(reflectron_profile, {stage1_ring_voltages_v=true,
        stage2_ring_voltages_v=true}, 'reflectron_profile')
    end
    local pulse_voltages={pre_all_v=0,
      repeller_v=volts.repeller_v, grid1_v=volts.grid1_v}
    if three_zone then
      pulse_voltages.intermediate2_v=volts.intermediate2_v
      pulse_voltages.exit_v=volts.exit_v
    end
    local accelerator = accelerator_plan('on', pulse_voltages)
    local legacy_accelerator = {}
    if not three_zone then
      for index, item in ipairs(accelerator) do
        legacy_accelerator[index] = {electrode_id=index, voltage_v=item.voltage_v}
      end
      legacy_accelerator[#legacy_accelerator + 1] = {
        electrode_id=ring_count + 4, voltage_v=0}
    end
    local reflectron = {{electrode_id=1, voltage_v=0}}
    local stage1_count = reflectron_stage1_count
    local stage2_count = reflectron_stage2_count
    local stage1 = reflectron_profile and
      reflectron_profile.stage1_ring_voltages_v or nil
    local stage2 = reflectron_profile and
      reflectron_profile.stage2_ring_voltages_v or nil
    if stage1 then assert(#stage1 == stage1_count,
      'reflectron stage1 profile ring count mismatch') end
    if stage2 then assert(#stage2 == stage2_count,
      'reflectron stage2 profile ring count mismatch') end
    local previous = 0
    for index=1,stage1_count do
      local voltage = stage1 and stage1[index] or
        volts.mid_v * index / (stage1_count + 1)
      finite(voltage, 'reflectron stage1 voltage')
      assert(voltage + 1e-9 >= previous and voltage >= -1e-9 and
        voltage <= volts.mid_v + 1e-9, 'reflectron stage1 profile must be monotone')
      reflectron[#reflectron + 1] = {electrode_id=1 + index,
        voltage_v=voltage}
      previous = voltage
    end
    local middle_id = 2 + stage1_count
    reflectron[#reflectron + 1] = {electrode_id=middle_id,
      voltage_v=volts.mid_v}
    previous = volts.mid_v
    for index=1,stage2_count do
      local voltage = stage2 and stage2[index] or volts.mid_v +
        (volts.backplate_v - volts.mid_v) * index / (stage2_count + 1)
      finite(voltage, 'reflectron stage2 voltage')
      assert(voltage + 1e-9 >= previous and voltage >= volts.mid_v - 1e-9 and
        voltage <= volts.backplate_v + 1e-9,
        'reflectron stage2 profile must be monotone')
      reflectron[#reflectron + 1] = {electrode_id=middle_id + index,
        voltage_v=voltage}
      previous = voltage
    end
    reflectron[#reflectron + 1] = {electrode_id=middle_id + stage2_count + 1,
      voltage_v=volts.backplate_v}
    reflectron[#reflectron + 1] = {electrode_id=middle_id + stage2_count + 2,
      voltage_v=0}
    return {accelerator=accelerator,
      legacy_accelerator_characterization=legacy_accelerator,
      reflectron=reflectron,
      flight_tube={{electrode_id=1, voltage_v=0}},
      detector={{electrode_id=1, voltage_v=0}}}
  end

  local function initialize_workbench(state)
    local active_scope = state.active_scope or 'full_flight'
    if active_scope == 'full_flight' then
      exact_keys(state, {instances=true}, 'workbench_state')
    else
      exact_keys(state, {instances=true, active_scope=true}, 'workbench_state')
      assert(active_scope == 'pre_pulse_frontend_accelerator',
        'workbench active scope is unsupported')
    end
    assert(type(state.instances) == 'table', 'workbench_state.instances must be a table')
    if active_scope == 'pre_pulse_frontend_accelerator' then
      local accelerator = state.instances[roles.accelerator]
      assert(type(accelerator) == 'table',
        'pre-pulse workbench accelerator instance is missing')
      filename_matches(accelerator.filename, payload_filenames.accelerator,
        'accelerator')
      exact_keys(accelerator, {filename=true, nx=true, ny=true, nz=true,
        dx_mm=true, dy_mm=true, dz_mm=true, scale=true},
        'workbench instance accelerator')
      positive(accelerator.nx, 'accelerator.nx')
      positive(accelerator.ny, 'accelerator.ny')
      positive(accelerator.nz, 'accelerator.nz')
      positive(accelerator.dx_mm, 'accelerator.dx_mm')
      positive(accelerator.dy_mm, 'accelerator.dy_mm')
      positive(accelerator.dz_mm, 'accelerator.dz_mm')
      positive(accelerator.scale, 'accelerator.scale')
      local half_x =
        (accelerator.nx - 1) * accelerator.dx_mm * accelerator.scale / 2
      local half_y =
        (accelerator.ny - 1) * accelerator.dy_mm * accelerator.scale / 2
      return {placements={accelerator={
        x_mm=g.accelerator_axis_x_mm - half_x,
        y_mm=g.accelerator_axis_y_mm - half_y,
        z_mm=g.accelerator_instance_z_mm,
        az_deg=0, el_deg=0, rt_deg=0, scale=accelerator.scale,
      }}, static_electrode_plans=static_electrode_plans(nil),
        active_scope=active_scope}
    end
    local max_role = math.max(roles.flight_tube, roles.reflectron,
      roles.accelerator, roles.detector)
    assert(#state.instances >= max_role,
      'workbench does not contain every required instance role')
    local flight = state.instances[roles.flight_tube]
    local reflectron = state.instances[roles.reflectron]
    local accelerator = state.instances[roles.accelerator]
    local detector_instance = state.instances[roles.detector]
    filename_matches(flight.filename, payload_filenames.flight_tube, 'flight_tube')
    filename_matches(reflectron.filename, payload_filenames.reflectron, 'reflectron')
    filename_matches(accelerator.filename, payload_filenames.accelerator, 'accelerator')
    filename_matches(detector_instance.filename, payload_filenames.detector, 'detector')
    for role, instance in pairs({flight_tube=flight, reflectron=reflectron,
        accelerator=accelerator, detector=detector_instance}) do
      exact_keys(instance, {filename=true, nx=true, ny=true, nz=true,
        dx_mm=true, dy_mm=true, dz_mm=true, scale=true},
        'workbench instance ' .. role)
      positive(instance.nx, role .. '.nx'); positive(instance.ny, role .. '.ny')
      positive(instance.nz, role .. '.nz'); positive(instance.dx_mm, role .. '.dx_mm')
      positive(instance.dy_mm, role .. '.dy_mm'); positive(instance.dz_mm, role .. '.dz_mm')
      positive(instance.scale, role .. '.scale')
    end
    local accelerator_half_x = (accelerator.nx - 1) * accelerator.dx_mm * accelerator.scale / 2
    local accelerator_half_y = (accelerator.ny - 1) * accelerator.dy_mm * accelerator.scale / 2
    local detector_half_x = (detector_instance.nx - 1) * detector_instance.dx_mm * detector_instance.scale / 2
    local detector_half_y = (detector_instance.ny - 1) * detector_instance.dy_mm * detector_instance.scale / 2
    local detector_span_z = (detector_instance.nz - 1) * detector_instance.dz_mm * detector_instance.scale
    local expected_detector_span = g.detector_marker_front_margin_z_mm +
      g.detector_marker_absorber_thickness_mm + g.detector_marker_back_margin_z_mm
    assert(math.abs(detector_span_z - expected_detector_span) < 1e-9,
      'detector marker PA z span does not match linked numerical parameters')
    local flight_axial_span = (flight.nx - 1) * flight.dx_mm * flight.scale
    local reflectron_axial_span = (reflectron.nx - 1) * reflectron.dx_mm * reflectron.scale
    assert(flight_axial_span + 1e-9 >=
      g.reflectron_entgrid_z_mm - g.flight_tube_near_outer_z_mm,
      'flight-tube PA does not reach the reflectron interface')
    assert(reflectron_axial_span + 1e-9 >=
      g.flight_tube_far_outer_z_mm - g.reflectron_entgrid_z_mm,
      'reflectron PA does not contain the far shield end cap')
    return {placements={
      accelerator={x_mm=g.accelerator_axis_x_mm - accelerator_half_x,
        y_mm=g.accelerator_axis_y_mm - accelerator_half_y,
        z_mm=g.accelerator_instance_z_mm, az_deg=0, el_deg=0, rt_deg=0, scale=accelerator.scale},
      reflectron={x_mm=g.reflectron_axis_x_mm, y_mm=g.reflectron_axis_y_mm,
        z_mm=g.reflectron_entgrid_z_mm, az_deg=-90, el_deg=0, rt_deg=0, scale=1},
      flight_tube={x_mm=0, y_mm=0, z_mm=g.flight_tube_near_outer_z_mm,
        az_deg=-90, el_deg=0, rt_deg=0, scale=1},
      detector={x_mm=g.detector_x_mm - detector_half_x,
        y_mm=g.detector_y_mm - detector_half_y,
        z_mm=g.detector_z_mm - g.detector_marker_back_margin_z_mm -
          g.detector_marker_absorber_thickness_mm, az_deg=0, el_deg=0, rt_deg=0,
          scale=detector_instance.scale},
    }, static_electrode_plans=static_electrode_plans(nil)}
  end

  local function efield_adjust(state)
    exact_keys(state, {z_mm=true, instance_id=true, instance_dx_mm=true,
      instance_dz_mm=true, instance_scale=true}, 'efield_state')
    local z = finite(state.z_mm, 'efield_state.z_mm')
    local field, axis, replace_all = nil, nil, false
    if modes.ideal_accelerator or modes.ideal_accelerator_axial then
      if z >= g.accelerator_repeller_front_z_mm and z < g.accelerator_grid1_z_mm then
        field = (volts.repeller_v - volts.grid1_v) /
          (g.accelerator_grid1_z_mm - g.accelerator_repeller_front_z_mm)
        axis = 'z'
      elseif z >= g.accelerator_grid1_z_mm and z < g.accelerator_grid2_z_mm then
        field = volts.grid1_v /
          (g.accelerator_grid2_z_mm - g.accelerator_grid1_z_mm)
        axis = 'z'
      end
      replace_all = modes.ideal_accelerator
    end
    if modes.ideal_drift_axial and z >= g.accelerator_grid2_z_mm and
        z < g.reflectron_entgrid_z_mm then
      field = 0
      axis = (state.instance_id == roles.flight_tube or
        state.instance_id == roles.reflectron) and 'x' or 'z'
      replace_all = false
    end
    if (modes.ideal_reflectron_stage1 or modes.ideal_reflectron_stage1_axial) and
        z >= g.reflectron_entgrid_z_mm and z < g.reflectron_midgrid_z_mm then
      field = -volts.mid_v / (g.reflectron_midgrid_z_mm - g.reflectron_entgrid_z_mm)
      axis = 'x'; replace_all = modes.ideal_reflectron_stage1
    end
    if (modes.ideal_reflectron_stage2 or modes.ideal_reflectron_stage2_axial) and
        z >= g.reflectron_midgrid_z_mm and z < g.reflectron_backplate_z_mm then
      field = -(volts.backplate_v - volts.mid_v) /
        (g.reflectron_backplate_z_mm - g.reflectron_midgrid_z_mm)
      axis = 'x'; replace_all = modes.ideal_reflectron_stage2
    end
    if field == nil then return nil end
    local result = {replace_all=replace_all}
    if axis == 'x' then
      result.dvoltsx_gu = -field * positive(state.instance_dx_mm,
        'efield_state.instance_dx_mm') * positive(state.instance_scale,
        'efield_state.instance_scale')
    else
      result.dvoltsz_gu = -field * positive(state.instance_dz_mm,
        'efield_state.instance_dz_mm') * positive(state.instance_scale,
        'efield_state.instance_scale')
    end
    return result
  end

  local function initialize_particle(state)
    exact_keys(state, {particle_id=true, elapsed_us=true, x_mm=true, y_mm=true,
      z_mm=true}, 'particle_state')
    local id = integer(state.particle_id, 'particle_state.particle_id')
    assert(id > 0, 'particle ID must be positive')
    particles[id] = {last_elapsed_us=finite(state.elapsed_us,
      'particle_state.elapsed_us'),
      last_x_mm=finite(state.x_mm, 'particle_state.x_mm'),
      last_y_mm=finite(state.y_mm, 'particle_state.y_mm'),
      last_z_mm=finite(state.z_mm, 'particle_state.z_mm'),
      max_z_mm=state.z_mm, step_count=0, detector_crossed=false, timed_out=false}
    return {}
  end

  local function tstep_adjust(state)
    exact_keys(state, {x_mm=true, y_mm=true, z_mm=true, vx_mm_per_us=true,
      vy_mm_per_us=true, vz_mm_per_us=true, detector_cell_dx_mm=true},
      'tstep_state')
    if not detector.tstep_enabled or state.vz_mm_per_us >= -1e-12 then return nil end
    local dz = state.z_mm - g.detector_z_mm
    if dz <= 0 or dz > detector.capture_arm_distance_mm then return nil end
    local dt = dz / -state.vz_mm_per_us
    local dx = state.x_mm + state.vx_mm_per_us * dt - g.detector_x_mm
    local dy = state.y_mm + state.vy_mm_per_us * dt - g.detector_y_mm
    local radial_limit = g.detector_radius_mm +
      positive(state.detector_cell_dx_mm, 'tstep_state.detector_cell_dx_mm')
    if dx * dx + dy * dy > radial_limit * radial_limit then return nil end
    return (dz + detector.capture_depth_mm) / -state.vz_mm_per_us
  end

  local function other_actions(state)
    exact_keys(state, {particle_id=true, elapsed_us=true, x_mm=true, y_mm=true,
      z_mm=true, vz_mm_per_us=true}, 'action_state')
    local record = assert(particles[state.particle_id], 'particle was not initialized')
    record.step_count = record.step_count + 1
    record.max_z_mm = math.max(record.max_z_mm, state.z_mm)
    local events = {}
    if record.last_z_mm > g.diagnostic_return_plane_z_mm and
        state.z_mm <= g.diagnostic_return_plane_z_mm and state.vz_mm_per_us < 0 then
      events[#events + 1] = {kind='diagnostic_return_plane',
        elapsed_us=state.elapsed_us, max_z_mm=record.max_z_mm}
    end
    record.last_elapsed_us, record.last_x_mm, record.last_y_mm, record.last_z_mm =
      state.elapsed_us, state.x_mm, state.y_mm, state.z_mm
    local splat = state.elapsed_us >= config.diagnostics.max_tof_us
    if splat then record.timed_out = true end
    return {splat=splat, events=events}
  end

  local function terminate(state)
    exact_keys(state, {particle_id=true, instance_id=true, elapsed_us=true,
      x_mm=true, y_mm=true, z_mm=true, vx_mm_per_us=true,
      vy_mm_per_us=true, vz_mm_per_us=true, detector_cell_dx_mm=true},
      'terminate_state')
    local record = assert(particles[state.particle_id], 'particle was not initialized')
    if record.timed_out or record.detector_crossed then return nil end
    if state.instance_id ~= roles.detector then
      return {kind='non_detector_splat', max_z_mm=record.max_z_mm}
    end
    record.detector_crossed = true
    local dt = 0
    if math.abs(state.vz_mm_per_us) > 1e-12 then
      dt = (g.detector_z_mm - state.z_mm) / state.vz_mm_per_us
    end
    local x = state.x_mm + state.vx_mm_per_us * dt
    local y = state.y_mm + state.vy_mm_per_us * dt
    local dx, dy = x - g.detector_x_mm, y - g.detector_y_mm
    local radius = math.sqrt(dx * dx + dy * dy)
    assert(radius <= g.detector_radius_mm + positive(state.detector_cell_dx_mm,
      'terminate_state.detector_cell_dx_mm'),
      'detector PA splat lies outside the physical disk')
    return {kind='detector_crossing', elapsed_us=state.elapsed_us + dt,
      x_mm=x, y_mm=y, z_mm=g.detector_z_mm, radius_mm=radius,
      max_z_mm=record.max_z_mm}
  end

  return {initialize_workbench=initialize_workbench,
    static_electrode_plans=static_electrode_plans,
    accelerator_electrode_write_plan=accelerator_plan,
    efield_adjust=efield_adjust, initialize_particle=initialize_particle,
    tstep_adjust=tstep_adjust, other_actions=other_actions,
    terminate=terminate}
end

return component
