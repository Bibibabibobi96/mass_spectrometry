-- Candidate extension for shared-clock RF handoff extraction.  The runtime
-- builder appends this file to the frozen Formal Program source so SIMION sees
-- exactly one workbench declaration and one auditable candidate Program.

adjustable handoff_pulse_mode = 1       -- 0=Formal always-on, 1=timed step, 2=held-off control
adjustable handoff_pulse_time_us = 0
adjustable handoff_pulse_width_us = 1
adjustable handoff_pulse_pre_all_v = 0

local base_initialize_run = segment.initialize_run
local base_tstep_adjust = segment.tstep_adjust
local base_other_actions = segment.other_actions
local base_terminate = segment.terminate
local pulse_reported = {}

function segment.initialize_run()
  base_initialize_run()
  assert(accelerator_ring_count == 5, 'pulse candidate expects the frozen five-ring accelerator')
  assert(handoff_pulse_mode == 0 or handoff_pulse_mode == 1 or handoff_pulse_mode == 2,
    'handoff_pulse_mode must be 0, 1 or 2')
  assert(handoff_pulse_time_us >= 0, 'handoff pulse time must be nonnegative')
  assert(handoff_pulse_width_us > 0, 'handoff pulse width must be positive')
  pulse_reported = {}
  if trajectory_log_enable ~= 0 then
    print(string.format('TRACE: handoff_pulse_contract mode=%d time_us=%.12g width_us=%.12g pre_all_v=%.12g post_repeller_v=%.12g grid1_v=%.12g',
      handoff_pulse_mode, handoff_pulse_time_us, handoff_pulse_width_us,
      handoff_pulse_pre_all_v, V_repeller, V_grid1))
  end
end

function segment.fast_adjust()
  if ion_instance ~= 3 or handoff_pulse_mode == 0 then return end
  local pulse_on = handoff_pulse_mode == 1
    and ion_time_of_flight >= handoff_pulse_time_us
    and ion_time_of_flight < handoff_pulse_time_us + handoff_pulse_width_us
  adj_elect01 = pulse_on and V_repeller or handoff_pulse_pre_all_v
  adj_elect02 = pulse_on and V_grid1 or handoff_pulse_pre_all_v
  adj_elect03 = pulse_on and V_grid1 * 5 / 6 or handoff_pulse_pre_all_v
  adj_elect04 = pulse_on and V_grid1 * 4 / 6 or handoff_pulse_pre_all_v
  adj_elect05 = pulse_on and V_grid1 * 3 / 6 or handoff_pulse_pre_all_v
  adj_elect06 = pulse_on and V_grid1 * 2 / 6 or handoff_pulse_pre_all_v
  adj_elect07 = pulse_on and V_grid1 * 1 / 6 or handoff_pulse_pre_all_v
  adj_elect08 = handoff_pulse_pre_all_v
  adj_elect09 = handoff_pulse_pre_all_v
end

function segment.tstep_adjust()
  base_tstep_adjust()
  if handoff_pulse_mode == 1 then
    local edge = nil
    if ion_time_of_flight < handoff_pulse_time_us then edge = handoff_pulse_time_us
    elseif ion_time_of_flight < handoff_pulse_time_us + handoff_pulse_width_us then
      edge = handoff_pulse_time_us + handoff_pulse_width_us
    end
    if edge then
      local remaining = edge - ion_time_of_flight
      if ion_time_step > remaining then ion_time_step = remaining end
    end
  end
end

function segment.other_actions()
  base_other_actions()
  if handoff_pulse_mode == 1 and not pulse_reported[ion_number]
      and ion_time_of_flight >= handoff_pulse_time_us then
    pulse_reported[ion_number] = true
    if trajectory_log_enable ~= 0 then
      print(string.format('TRACE: handoff_pulse_on ion=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
        ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
        ion_vx_mm, ion_vy_mm, ion_vz_mm))
    end
  end
end

function segment.terminate()
  if handoff_pulse_mode == 1 and trajectory_log_enable ~= 0 then
    print(string.format('TRACE: handoff_terminal_raw ion=%d instance=%d instrument_time_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_per_us=%.12g vy_mm_per_us=%.12g vz_mm_per_us=%.12g',
      ion_number, ion_instance, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
      ion_vx_mm, ion_vy_mm, ion_vz_mm))
  end
  base_terminate()
end
