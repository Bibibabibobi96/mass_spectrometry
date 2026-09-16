-- Independent accelerator-exit diagnostic for a pre-voltageized standalone PA.
-- This program ends at the first verified negative-project-z PA-volume exit.  It
-- does not enter P1 and does not qualify the complete MR-TOF transport.
simion.workbench_program()
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local operating_point = assert(loadfile(program_path:gsub('%.lua$', '.operating_point.lua')))()
adjustable trajectory_quality = assert(operating_point.trajectory_quality,
  'operating point has no trajectory quality')
adjustable maximum_step_us = assert(operating_point.maximum_step_us,
  'operating point has no maximum time step')
local timeout_us = assert(operating_point.full_path_timeout_us,
  'operating point has no full-path timeout')
assert(trajectory_quality > 0 and maximum_step_us > 0 and timeout_us > 0,
  'accelerator-exit numerical controls must be positive')

local accelerator_instance, accelerator_painstance
local negative_z_axis, negative_z_face_gu, negative_z_direction
local previous, selected_instance, outcome, failure_reason, terminal_splat = {}, {}, {}, {}, {}
local success_count, failure_count = 0, 0

local function state()
  return {
    t_us=ion_time_of_flight,
    x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm,
    vx_mm_us=ion_vx_mm, vy_mm_us=ion_vy_mm, vz_mm_us=ion_vz_mm,
  }
end

local function local_coordinates(sample)
  return accelerator_painstance:wb_to_pa_coords(sample.x_mm, sample.y_mm, sample.z_mm)
end

local function axis_coordinate(x, y, z)
  if negative_z_axis == 'x' then return x end
  if negative_z_axis == 'y' then return y end
  return z
end

local function emit_failure(reason, splat)
  if outcome[ion_number] ~= nil then return end
  outcome[ion_number], failure_reason[ion_number] = 'failed', reason
  terminal_splat[ion_number] = splat or ion_splat or 0
  failure_count = failure_count + 1
  print(string.format('MRTOF_ACCELERATOR_EXIT_FAILURE ion=%d reason=%s splat=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
    ion_number, reason, terminal_splat[ion_number], ion_time_of_flight,
    ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm))
end

local function interpolate(a, b, fraction)
  return {
    t_us=a.t_us + fraction*(b.t_us-a.t_us),
    x_mm=a.x_mm + fraction*(b.x_mm-a.x_mm),
    y_mm=a.y_mm + fraction*(b.y_mm-a.y_mm),
    z_mm=a.z_mm + fraction*(b.z_mm-a.z_mm),
    vx_mm_us=a.vx_mm_us + fraction*(b.vx_mm_us-a.vx_mm_us),
    vy_mm_us=a.vy_mm_us + fraction*(b.vy_mm_us-a.vy_mm_us),
    vz_mm_us=a.vz_mm_us + fraction*(b.vz_mm_us-a.vz_mm_us),
  }
end

local function derive_negative_z_face(instance)
  local pa = assert(instance.pa, 'accelerator instance has no PA')
  assert(pa.nx and pa.ny and pa.nz and pa.nx > 1 and pa.ny > 1 and pa.nz > 1,
    'accelerator PA dimensions are invalid')
  local ox, oy, oz = instance:pa_to_wb_coords(0, 0, 0)
  local _, _, xz = instance:pa_to_wb_coords(1, 0, 0)
  local _, _, yz = instance:pa_to_wb_coords(0, 1, 0)
  local _, _, zz = instance:pa_to_wb_coords(0, 0, 1)
  local changes = {x=xz-oz, y=yz-oz, z=zz-oz}
  local axis, magnitude = 'x', math.abs(changes.x)
  for _,candidate in ipairs({'y','z'}) do
    if math.abs(changes[candidate]) > magnitude then
      axis, magnitude = candidate, math.abs(changes[candidate])
    end
  end
  assert(magnitude > 0, 'accelerator PA has no project-z orientation')
  local tolerance = 64 * 2^-52 * math.max(1, magnitude)
  for _,candidate in ipairs({'x','y','z'}) do
    if candidate ~= axis then
      assert(math.abs(changes[candidate]) <= tolerance,
        'accelerator PA project-z direction is not aligned to one PA axis')
    end
  end
  local maximum = axis == 'x' and pa.nx-1 or (axis == 'y' and pa.ny-1 or pa.nz-1)
  local direction = changes[axis] > 0 and -1 or 1
  local face = direction < 0 and 0 or maximum
  return axis, face, direction
end

function segment.initialize_run()
  sim_trajectory_quality = trajectory_quality
  previous, selected_instance, outcome, failure_reason, terminal_splat = {}, {}, {}, {}, {}
  success_count, failure_count = 0, 0
  assert(simion.wb and simion.wb.instances, 'accelerator-exit diagnostic requires a Workbench')
  local matches = {}
  for index=1,#simion.wb.instances do
    local instance = simion.wb.instances[index]
    local filename = string.lower(tostring(instance.filename or ''))
    if filename:match('iob_input_accelerator%.pa$') then matches[#matches+1] = index end
  end
  assert(#matches == 1, 'accelerator-exit diagnostic requires exactly one bound standalone accelerator PA')
  accelerator_instance = matches[1]
  accelerator_painstance = simion.wb.instances[accelerator_instance]
  negative_z_axis, negative_z_face_gu, negative_z_direction =
    derive_negative_z_face(accelerator_painstance)
  print(string.format('MRTOF_EVENT accelerator_layout accelerator_instance=%d', accelerator_instance))
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.initialize()
  if previous[ion_number] ~= nil then return end
  local sample = state()
  local speed_mm_us = math.sqrt(
    ion_vx_mm^2 + ion_vy_mm^2 + ion_vz_mm^2)
  local kinetic_energy_ev_native = speed_to_ke(speed_mm_us, ion_mass)
  assert(kinetic_energy_ev_native == kinetic_energy_ev_native
      and math.abs(kinetic_energy_ev_native) < math.huge
      and kinetic_energy_ev_native >= 0,
    'SIMION returned invalid native source kinetic energy')
  previous[ion_number] = sample
  selected_instance[ion_number] = ion_instance
  local lx, ly, lz = local_coordinates(sample)
  print(string.format('MRTOF_EVENT accelerator_source ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g mass_th=%.12g charge_state=%.12g kinetic_energy_ev_native=%.12g',
    ion_number, ion_time_of_flight,
    ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm,
    ion_mass, ion_charge, kinetic_energy_ev_native))
  if ion_instance ~= accelerator_instance
      or not accelerator_painstance.pa:inside_vc(lx, ly, lz) then
    emit_failure('source_accelerator_instance_mismatch', 4)
    ion_splat = 4
  end
end

function segment.other_actions()
  if outcome[ion_number] ~= nil then return end
  if ion_splat ~= 0 then
    emit_failure('electrode_collision', ion_splat)
    return
  end
  if ion_time_of_flight >= timeout_us then
    emit_failure('timeout', 2)
    ion_splat = 2
    return
  end

  local current = state()
  local prior = previous[ion_number]
  local from_instance = selected_instance[ion_number]
  if from_instance ~= ion_instance then
    if from_instance == accelerator_instance and ion_instance ~= accelerator_instance then
      local plx, ply, plz = local_coordinates(prior)
      local clx, cly, clz = local_coordinates(current)
      local before = axis_coordinate(plx, ply, plz)
      local after = axis_coordinate(clx, cly, clz)
      local denominator = after-before
      local crossed = (negative_z_direction < 0
          and before >= negative_z_face_gu and after <= negative_z_face_gu
          and denominator < 0)
        or (negative_z_direction > 0
          and before <= negative_z_face_gu and after >= negative_z_face_gu
          and denominator > 0)
      if not crossed or denominator == 0 then
        emit_failure('non_negative_z_face_exit', 3)
        ion_splat = 3
        return
      end
      local fraction = (negative_z_face_gu-before)/denominator
      if fraction < 0 or fraction > 1 then
        emit_failure('invalid_negative_z_face_intersection', 3)
        ion_splat = 3
        return
      end
      local exit = interpolate(prior, current, fraction)
      if exit.vz_mm_us >= 0 then
        emit_failure('nonnegative_project_z_exit_velocity', 3)
        ion_splat = 3
        return
      end
      outcome[ion_number], terminal_splat[ion_number] = 'success', 1
      success_count = success_count + 1
      print(string.format('MRTOF_EVENT accelerator_safe_exit ion=%d t_us=%.12g from_instance=%d to_instance=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, exit.t_us, from_instance, ion_instance,
        exit.x_mm, exit.y_mm, exit.z_mm,
        exit.vx_mm_us, exit.vy_mm_us, exit.vz_mm_us))
      ion_splat = 1
      return
    end
  end
  previous[ion_number] = current
  selected_instance[ion_number] = ion_instance
end

function segment.terminate()
  if outcome[ion_number] == nil then emit_failure('terminated_without_safe_exit', ion_splat) end
  print(string.format('MRTOF_EVENT terminal ion=%d splat=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g turns=0 central_crossings=0',
    ion_number, terminal_splat[ion_number] or ion_splat or 0, ion_time_of_flight,
    ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm))
end

function segment.terminate_run()
  local status = failure_count == 0 and success_count == 1 and 'PASS' or 'FAIL'
  print(string.format('MRTOF_ACCELERATOR_EXIT=%s success_count=%d failure_count=%d',
    status, success_count, failure_count))
end
