-- Native fixed-field transverse L1 probe for the five-region bare-mirror IOB.
-- The companion source table and Fly2 are frozen by the owning run.  Stripe
-- and prism arrays are already grounded; this program never adjusts or saves
-- a PA.
simion.workbench_program()
simion.early_access(8.2)
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local local_refinement = assert(loadfile(program_path:gsub('%.lua$', '.local_refinement.lua')))()
local source_contract = assert(loadfile(program_path:gsub('%.lua$', '.native_l1.lua')))()
assert(local_refinement.enabled and #local_refinement.instances == 5,
  'native transverse L1 probe requires the five-region local replacement')

adjustable trajectory_quality = 8
adjustable maximum_step_us = 0.00002
local previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
local turns, first_returned, completed = {}, {}, {}

local function definition(instance_number)
  for _, item in ipairs(local_refinement.instances) do
    if item.instance == instance_number then return item end
  end
  return nil
end

function segment.instance_adjust()
  local item = definition(ion_instance)
  if item == nil then return end
  local lower = item.z_min_mm == nil or ion_pz_mm >= item.z_min_mm
  local upper = item.z_max_mm == nil or ion_pz_mm < item.z_max_mm
  if not (lower and upper) then ion_instance = 0 end
end

function segment.initialize()
  local ion = ion_number
  assert(source_contract[ion], 'native transverse L1 source contract lacks this ion')
  previous_x[ion], previous_y[ion], previous_z[ion] = ion_px_mm, ion_py_mm, ion_pz_mm
  previous_vx[ion], previous_vy[ion], previous_vz[ion] = ion_vx_mm, ion_vy_mm, ion_vz_mm
  previous_t[ion], turns[ion], first_returned[ion], completed[ion] = ion_time_of_flight, 0, false, false
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.other_actions()
  local ion = ion_number
  local source = source_contract[ion]
  local pz, pvz, pt = previous_z[ion], previous_vz[ion], previous_t[ion]
  if pz == nil then return end
  if pvz * ion_vz_mm < 0 then turns[ion] = turns[ion] + 1 end
  local direction = source.direction_z
  local first_crossed, full_crossed = false, false
  if direction > 0 then
    first_crossed = pz > 0 and ion_pz_mm <= 0 and ion_vz_mm < 0
    full_crossed = pz < 0 and ion_pz_mm >= 0 and ion_vz_mm > 0
  else
    first_crossed = pz < 0 and ion_pz_mm >= 0 and ion_vz_mm > 0
    full_crossed = pz > 0 and ion_pz_mm <= 0 and ion_vz_mm < 0
  end
  if turns[ion] >= 1 and first_crossed and not first_returned[ion] then
    local fraction = -pz / (ion_pz_mm - pz)
    local time = pt + fraction * (ion_time_of_flight - pt)
    local x = previous_x[ion] + fraction * (ion_px_mm - previous_x[ion])
    local y = previous_y[ion] + fraction * (ion_py_mm - previous_y[ion])
    local vx = previous_vx[ion] + fraction * (ion_vx_mm - previous_vx[ion])
    local vy = previous_vy[ion] + fraction * (ion_vy_mm - previous_vy[ion])
    local vz = previous_vz[ion] + fraction * (ion_vz_mm - previous_vz[ion])
    print(string.format(
      'MRTOF_NATIVE_L1 ion=%d direction_z=%d probe_kind=%s phase=first_return energy_ev=%.15g time_us=%.15g turns=%d x_mm=%.15g y_mm=%.15g vx_mm_us=%.15g vy_mm_us=%.15g vz_mm_us=%.15g',
      ion, direction, source.probe_kind, source.energy_ev, time, turns[ion], x, y, vx, vy, vz))
    first_returned[ion] = true
  elseif not completed[ion] and turns[ion] >= 2 and full_crossed then
    local fraction = -pz / (ion_pz_mm - pz)
    local time = pt + fraction * (ion_time_of_flight - pt)
    local x = previous_x[ion] + fraction * (ion_px_mm - previous_x[ion])
    local y = previous_y[ion] + fraction * (ion_py_mm - previous_y[ion])
    local vx = previous_vx[ion] + fraction * (ion_vx_mm - previous_vx[ion])
    local vy = previous_vy[ion] + fraction * (ion_vy_mm - previous_vy[ion])
    local vz = previous_vz[ion] + fraction * (ion_vz_mm - previous_vz[ion])
    print(string.format(
      'MRTOF_NATIVE_L1 ion=%d direction_z=%d probe_kind=%s phase=full_return energy_ev=%.15g time_us=%.15g turns=%d x_mm=%.15g y_mm=%.15g vx_mm_us=%.15g vy_mm_us=%.15g vz_mm_us=%.15g',
      ion, direction, source.probe_kind, source.energy_ev, time, turns[ion], x, y, vx, vy, vz))
    completed[ion] = true
    ion_splat = 1
  elseif ion_time_of_flight > 100 then
    print(string.format('MRTOF_NATIVE_L1_TIMEOUT ion=%d turns=%d t_us=%.15g', ion, turns[ion], ion_time_of_flight))
    ion_splat = -4
  end
  previous_x[ion], previous_y[ion], previous_z[ion] = ion_px_mm, ion_py_mm, ion_pz_mm
  previous_vx[ion], previous_vy[ion], previous_vz[ion] = ion_vx_mm, ion_vy_mm, ion_vz_mm
  previous_t[ion] = ion_time_of_flight
end

function segment.terminate()
  local ion = ion_number
  if not completed[ion] then
    print(string.format('MRTOF_NATIVE_L1_TERMINAL ion=%d splat=%d turns=%d t_us=%.15g',
      ion, ion_splat, turns[ion] or -1, ion_time_of_flight))
  end
end
