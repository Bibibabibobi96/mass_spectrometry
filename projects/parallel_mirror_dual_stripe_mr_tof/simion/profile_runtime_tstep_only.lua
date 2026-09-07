-- Native SIMION timing control: same field and time-step cap, no per-segment
-- ``other_actions`` callback.  It is not a physics or performance run.
simion.workbench_program()
sim_segment_global = 0

local program_path = debug.getinfo(1, 'S').source:sub(2)
local point = assert(loadfile(assert(program_path:gsub('%.lua$', '.operating_point.lua'))))()
local voltage_map = assert(loadfile(program_path:gsub('%.lua$', '.voltage_map.lua')))()
local cutoff_us = assert(point.runtime_profile_cutoff_us, 'runtime profile cutoff is required')
local calls, min_step, max_step = 0, math.huge, 0

function segment.initialize_run()
  sim_trajectory_quality = assert(point.trajectory_quality, 'trajectory quality is required')
  calls, min_step, max_step = 0, math.huge, 0
end

function segment.fast_adjust()
  local values = voltage_map(point.mirror_voltages_v, point.stripe_biases_v,
    point.prism_voltages_v, point.accelerator_voltages_v, point.accelerator_ring_voltages_v,
    point.nonaccelerator_scale)
  simion.wb.instances[1].pa:fast_adjust(values.analyser)
  simion.wb.instances[2].pa:fast_adjust(values.accelerator)
end

function segment.tstep_adjust()
  calls = calls + 1
  min_step = math.min(min_step, ion_time_step)
  max_step = math.max(max_step, ion_time_step)
  ion_time_step = math.min(ion_time_step, point.maximum_step_us)
  if ion_time_of_flight >= cutoff_us then ion_splat = 2 end
end

function segment.terminate()
  print(string.format('MRTOF_RUNTIME_PROFILE_TSTEP_ONLY terminal ion=%d t_us=%.12g tstep_calls=%d proposed_dt_min_us=%.12g proposed_dt_max_us=%.12g',
    ion_number, ion_time_of_flight, calls, min_step, max_step))
end
