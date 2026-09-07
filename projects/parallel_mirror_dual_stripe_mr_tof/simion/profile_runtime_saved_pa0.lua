-- Timing control for a previously persisted static PA0 Workbench.
-- Intentionally omits segment.fast_adjust: this isolates saved-PA0 flight.
simion.workbench_program()
sim_segment_global = 0

local program_path = debug.getinfo(1, 'S').source:sub(2)
local point = assert(loadfile(assert(program_path:gsub('%.lua$', '.operating_point.lua'))))()
local cutoff_us = assert(point.runtime_profile_cutoff_us, 'runtime profile cutoff is required')
local steps, tstep_calls = 0, 0

function segment.initialize_run()
  sim_trajectory_quality = assert(point.trajectory_quality, 'trajectory quality is required')
  steps, tstep_calls = 0, 0
end

function segment.tstep_adjust()
  tstep_calls = tstep_calls + 1
  ion_time_step = math.min(ion_time_step, point.maximum_step_us)
end

function segment.other_actions()
  steps = steps + 1
  if ion_time_of_flight >= cutoff_us then ion_splat = 2 end
end

function segment.terminate()
  print(string.format('MRTOF_RUNTIME_PROFILE_SAVED_PA0 terminal ion=%d t_us=%.12g steps=%d tstep_calls=%d',
    ion_number, ion_time_of_flight, steps, tstep_calls))
end
