-- One-particle finite-3-D first-prism diagnostic for the MR-TOF Candidate.
--
-- This program intentionally stops at the first grounded-shield interface.
-- It is not a K=25 circulation run, a second-prism setting, or a resolution
-- calculation.  Every physical value comes from the run-local operating
-- point written by materialize_simion_prototype.py.
simion.workbench_program()
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local point_path = assert(program_path:gsub('%.lua$', '.operating_point.lua'))
local point = assert(loadfile(point_path), 'missing run-local operating-point sidecar: '..point_path)()
local map_path = program_path:gsub('%.lua$', '.voltage_map.lua')
local voltage_map = assert(loadfile(map_path), 'missing run-local voltage mapper: '..map_path)()
local prism = assert(point.first_prism_l0, 'operating point has no first-prism L0 interface')
assert(type(prism.target_plane_z_mm) == 'number' and type(prism.target_plane_x_mm) == 'number',
  'first-prism target plane is incomplete')
assert(type(prism.target_plane_y_acceptance_mm) == 'table' and #prism.target_plane_y_acceptance_mm == 2
  and prism.target_plane_y_acceptance_mm[1] < prism.target_plane_y_acceptance_mm[2],
  'first-prism target y acceptance is invalid')

adjustable trajectory_quality = assert(point.trajectory_quality, 'trajectory quality required')
adjustable maximum_step_us = assert(point.maximum_step_us, 'maximum step required')
-- The IOB builder applies this frozen first-prism point and saves both PA0
-- arrays before Fly starts.  The interface diagnostic is static, so replaying
-- Fast Adjust on every integration segment only recomputes the same large
-- basis-array sum.  Keep an explicit interactive debugging opt-in, but make
-- the saved-PA0 path the only normal execution path.
adjustable runtime_fast_adjust_enable = 0
local previous, reached, splat_code = {}, {}, {}

function segment.initialize_run()
  assert(simion.wb and #simion.wb.instances == 3,
    'first-prism L0 requires analyser, accelerator, and detector instances')
  previous, reached, splat_code = {}, {}, {}
  sim_trajectory_quality = trajectory_quality
  print('MRTOF_FIRST_PRISM_L0: status=prototype finite_3d_single_particle')
end

function segment.fast_adjust()
  if runtime_fast_adjust_enable == 0 then return end
  local values = voltage_map(assert(point.mirror_voltages_v), assert(point.stripe_biases_v),
    assert(point.prism_voltages_v), assert(point.accelerator_voltages_v),
    assert(point.accelerator_ring_voltages_v), assert(point.nonaccelerator_scale))
  simion.wb.instances[1].pa:fast_adjust(values.analyser)
  simion.wb.instances[2].pa:fast_adjust(values.accelerator)
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.initialize()
  previous[ion_number] = {x=ion_px_mm, y=ion_py_mm, z=ion_pz_mm, t=ion_time_of_flight}
end

function segment.other_actions()
  if ion_splat ~= 0 then
    splat_code[ion_number] = ion_splat
    return
  end
  local prior = previous[ion_number]
  if prior and not reached[ion_number] and prior.z > prism.target_plane_z_mm
    and ion_pz_mm <= prism.target_plane_z_mm then
    local fraction = (prism.target_plane_z_mm-prior.z)/(ion_pz_mm-prior.z)
    local x = prior.x + fraction*(ion_px_mm-prior.x)
    local y = prior.y + fraction*(ion_py_mm-prior.y)
    local t = prior.t + fraction*(ion_time_of_flight-prior.t)
    local accepted_y = y >= prism.target_plane_y_acceptance_mm[1]
      and y <= prism.target_plane_y_acceptance_mm[2]
    reached[ion_number] = true
    print(string.format(
      'MRTOF_FIRST_PRISM_EVENT interface ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g x_offset_mm=%.12g accepted_y=%s',
      ion_number,t,x,y,prism.target_plane_z_mm,x-prism.target_plane_x_mm,tostring(accepted_y)))
    splat_code[ion_number] = 1
    ion_splat = 1
  end
  previous[ion_number] = {x=ion_px_mm, y=ion_py_mm, z=ion_pz_mm, t=ion_time_of_flight}
end

function segment.terminate()
  print(string.format(
    'MRTOF_FIRST_PRISM_EVENT terminal ion=%d splat=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g interface_reached=%s',
    ion_number,splat_code[ion_number] or 0,ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,
    tostring(reached[ion_number] or false)))
end
