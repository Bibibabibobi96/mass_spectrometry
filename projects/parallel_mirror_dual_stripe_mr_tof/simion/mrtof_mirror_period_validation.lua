-- Finite-3-D bare-mirror period probe. Stripe and prism voltages are already
-- grounded in the five standalone local PAs supplied by the owning runner.
simion.workbench_program()
simion.early_access(8.2)
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local local_refinement = assert(loadfile(program_path:gsub('%.lua$', '.local_refinement.lua')))()
local source_contract = assert(loadfile(program_path:gsub('%.lua$', '.probe.lua')))()
assert(local_refinement.enabled and #local_refinement.instances == 5,
  'mirror period probe requires the five-region local replacement')

adjustable trajectory_quality = 8
adjustable maximum_step_us = 0.00002
local previous_z, previous_vz, previous_t = {}, {}, {}
local turns = {}
local completed = {}

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
  previous_z[ion], previous_vz[ion], previous_t[ion] = ion_pz_mm, ion_vz_mm, ion_time_of_flight
  turns[ion], completed[ion] = 0, false
  assert(source_contract[ion], 'probe contract lacks this ion')
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.other_actions()
  local ion = ion_number
  local pz, pvz, pt = previous_z[ion], previous_vz[ion], previous_t[ion]
  if pz == nil then return end
  if pvz * ion_vz_mm < 0 then turns[ion] = turns[ion] + 1 end
  if not completed[ion] and turns[ion] >= 2 and pz < 0 and ion_pz_mm >= 0 and ion_vz_mm > 0 then
    local fraction = -pz / (ion_pz_mm - pz)
    local time = pt + fraction * (ion_time_of_flight - pt)
    local x = ion_px_mm -- sub-step spatial residuals are diagnostic only
    local y = ion_py_mm
    local vz = pvz + fraction * (ion_vz_mm - pvz)
    print(string.format(
      'MRTOF_MIRROR_PERIOD ion=%d target_energy_ev=%.15g period_us=%.15g turns=%d x_mm=%.15g y_mm=%.15g z_mm=0 vx_mm_us=%.15g vy_mm_us=%.15g vz_mm_us=%.15g',
      ion, source_contract[ion], time, turns[ion], x, y, ion_vx_mm, ion_vy_mm, vz))
    completed[ion] = true
    ion_splat = 1
  elseif ion_time_of_flight > 100 then
    print(string.format('MRTOF_MIRROR_PERIOD_TIMEOUT ion=%d turns=%d t_us=%.15g',
      ion, turns[ion], ion_time_of_flight))
    ion_splat = -4
  end
  previous_z[ion], previous_vz[ion], previous_t[ion] = ion_pz_mm, ion_vz_mm, ion_time_of_flight
end

function segment.terminate()
  local ion = ion_number
  if not completed[ion] then
    print(string.format('MRTOF_MIRROR_PERIOD_TERMINAL ion=%d splat=%d turns=%d t_us=%.15g',
      ion, ion_splat, turns[ion] or -1, ion_time_of_flight))
  end
end
