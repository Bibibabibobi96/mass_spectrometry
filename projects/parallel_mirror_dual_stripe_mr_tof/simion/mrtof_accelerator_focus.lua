-- Independent first-time-focus diagnostic for the already assembled MR-TOF IOB.
-- It stops each ion at project z=0, before either prism can alter the result.
simion.workbench_program()
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local operating_point = assert(loadfile(program_path:gsub('%.lua$', '.operating_point.lua')))()
adjustable trajectory_quality = operating_point.trajectory_quality
adjustable maximum_step_us = operating_point.maximum_step_us
local timeout_us = operating_point.full_path_timeout_us
local previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
local source_z, reached_focus, terminal_code = {}, {}, {}

function segment.initialize_run()
  sim_trajectory_quality = trajectory_quality
  previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
  source_z, reached_focus, terminal_code = {}, {}, {}
  assert(simion.wb and #simion.wb.instances == 3, 'accelerator focus requires the reviewed three-component IOB')
  assert(simion.wb.instances[2].filename:match('mrtof_accelerator%.pa0$'), 'instance 2 must be accelerator PA0')
  print('MRTOF_ACCELERATOR_FOCUS: status=prototype target_plane_z_mm=0')
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.initialize()
  if previous_z[ion_number] == nil then
    previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
    previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight
    source_z[ion_number] = ion_pz_mm
    print(string.format('MRTOF_ACCELERATOR_FOCUS_EVENT source ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
      ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm))
  end
end

function segment.other_actions()
  if ion_time_of_flight >= timeout_us and ion_splat == 0 then
    terminal_code[ion_number] = 2
    ion_splat = 2
    return
  end
  if ion_splat ~= 0 then terminal_code[ion_number] = ion_splat end
  local px, py, pz = previous_x[ion_number], previous_y[ion_number], previous_z[ion_number]
  local pvx, pvy, pvz, pt = previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number]
  local dz = pz and ion_pz_mm - pz or 0
  if not reached_focus[ion_number] and pz and pz > 0 and ion_pz_mm <= 0 and dz < 0 then
    local fraction = -pz / dz
    reached_focus[ion_number] = true
    terminal_code[ion_number] = 1
    print(string.format('MRTOF_ACCELERATOR_FOCUS_EVENT focus ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=0 vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
      ion_number, pt + fraction*(ion_time_of_flight-pt),
      px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py),
      pvx + fraction*(ion_vx_mm-pvx), pvy + fraction*(ion_vy_mm-pvy), pvz + fraction*(ion_vz_mm-pvz)))
    ion_splat = 1
    return
  end
  previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
  previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight
end

function segment.terminate()
  print(string.format('MRTOF_ACCELERATOR_FOCUS_EVENT terminal ion=%d code=%d reached_focus=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
    ion_number, terminal_code[ion_number] or 0, reached_focus[ion_number] and 1 or 0,
    ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm))
end
