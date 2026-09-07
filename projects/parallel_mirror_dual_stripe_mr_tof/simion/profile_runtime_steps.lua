-- Native SIMION timing probe for one frozen MR-TOF Workbench state.
-- This is a diagnostic program: it never reports transport or resolution.
simion.workbench_program()
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local point_path = assert(program_path:gsub('%.lua$', '.operating_point.lua'))
local point = assert(loadfile(point_path), 'missing run-local operating point')()
local map_path = program_path:gsub('%.lua$', '.voltage_map.lua')
local voltage_map = assert(loadfile(map_path), 'missing run-local voltage map')()
local steps, tstep_calls, min_step, max_step = 0, 0, math.huge, 0
local cutoff_us = assert(point.runtime_profile_cutoff_us, 'runtime profile cutoff is required')
assert(cutoff_us > 0, 'runtime profile cutoff must be positive')

function segment.initialize_run()
  sim_trajectory_quality = assert(point.trajectory_quality, 'trajectory quality is required')
  steps, tstep_calls, min_step, max_step = 0, 0, math.huge, 0
  print(string.format('MRTOF_RUNTIME_PROFILE start global=%d quality=%g max_step_us=%.12g cutoff_us=%.12g',
    sim_segment_global, sim_trajectory_quality, point.maximum_step_us, cutoff_us))
end

function segment.fast_adjust()
  local values = voltage_map(point.mirror_voltages_v, point.stripe_biases_v,
    point.prism_voltages_v, point.accelerator_voltages_v, point.accelerator_ring_voltages_v,
    point.nonaccelerator_scale)
  simion.wb.instances[1].pa:fast_adjust(values.analyser)
  simion.wb.instances[2].pa:fast_adjust(values.accelerator)
end

function segment.tstep_adjust()
  tstep_calls = tstep_calls + 1
  local proposed = ion_time_step
  if proposed < min_step then min_step = proposed end
  if proposed > max_step then max_step = proposed end
  ion_time_step = math.min(proposed, point.maximum_step_us)
end

function segment.other_actions()
  steps = steps + 1
  if ion_time_of_flight >= cutoff_us then ion_splat = 2 end
end

function segment.terminate()
  print(string.format('MRTOF_RUNTIME_PROFILE terminal ion=%d t_us=%.12g steps=%d tstep_calls=%d proposed_dt_min_us=%.12g proposed_dt_max_us=%.12g',
    ion_number, ion_time_of_flight, steps, tstep_calls, min_step, max_step))
end
