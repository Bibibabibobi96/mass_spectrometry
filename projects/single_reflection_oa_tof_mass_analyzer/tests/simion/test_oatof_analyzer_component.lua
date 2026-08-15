-- Pure-Lua contract checks for the callback-neutral oaTOF Candidate component.
-- Run with SIMION's supported Lua CLI; no workbench, PA, Refine, or Fly is used.

local component_path = assert(arg[1], 'component path is required')
local component = assert(dofile(component_path), 'component did not return a module')

local function near(actual, expected, label)
  local tolerance = 1e-11 * math.max(1, math.abs(expected))
  assert(math.abs(actual - expected) <= tolerance,
    label .. ': expected ' .. expected .. ', got ' .. actual)
end

local function config()
  return {
    instance_roles={flight_tube=1, reflectron=2, accelerator=3, detector=4},
    instance_filenames={flight_tube='flight_tube_ground.pa0',
      reflectron='reflectron.pa0', accelerator='accelerator.pa0',
      detector='detector_ground.pa0'},
    geometry={
      accelerator_axis_x_mm=-48.8, accelerator_axis_y_mm=0,
      accelerator_instance_z_mm=-29.92918680341103,
      accelerator_repeller_front_z_mm=-19.92918680341103,
      accelerator_grid1_z_mm=-16.92918680341103,
      accelerator_grid2_z_mm=-0.12918680341102995,
      reflectron_axis_x_mm=0, reflectron_axis_y_mm=0,
      reflectron_entgrid_z_mm=600, reflectron_midgrid_z_mm=720,
      reflectron_backplate_z_mm=816.1563,
      detector_x_mm=48.8, detector_y_mm=0, detector_z_mm=0,
      detector_radius_mm=40, detector_marker_front_margin_z_mm=0.2,
      detector_marker_back_margin_z_mm=0.05,
      detector_marker_absorber_thickness_mm=0.1,
      diagnostic_return_plane_z_mm=20.5,
      flight_tube_near_outer_z_mm=-64.92918680341103,
      flight_tube_far_outer_z_mm=881.1563,
    },
    field_modes={ideal_accelerator=true, ideal_accelerator_axial=false,
      ideal_drift_axial=false, ideal_reflectron_stage1=false,
      ideal_reflectron_stage1_axial=false, ideal_reflectron_stage2=false,
      ideal_reflectron_stage2_axial=false},
    voltages={repeller_v=2240, grid1_v=1760, mid_v=1628.8001,
      backplate_v=2531.1999},
    accelerator_ring_count=5, reflectron_stage1_ring_count=10,
    reflectron_stage2_ring_count=5,
    electrode_ids={repeller=10, grid1=11, rings={12,13,14,15,16},
      grid2=17},
    detector={tstep_enabled=true, capture_arm_distance_mm=100,
      capture_depth_mm=0.02, marker_absorber_thickness_mm=0.1},
    diagnostics={max_tof_us=90, log_stride=1000},
  }
end

local analyzer = component.new(config())
local on = analyzer.accelerator_electrode_write_plan('on',
  {pre_all_v=0, repeller_v=2240, grid1_v=1760})
assert(#on == 8, 'oaTOF combined plan must contain eight electrodes')
for index=1,#on do
  assert(on[index].electrode_id == index + 9,
    'combined oaTOF electrode ID mapping changed')
end
near(on[1].voltage_v, 2240, 'repeller voltage')
near(on[2].voltage_v, 1760, 'grid1 voltage')
for index=1,5 do
  near(on[2 + index].voltage_v, 1760 * (6 - index) / 6,
    'accelerator ring voltage ' .. index)
end
near(on[8].voltage_v, 0, 'grid2 voltage')

local off = analyzer.accelerator_electrode_write_plan('off',
  {pre_all_v=7, repeller_v=2240, grid1_v=1760})
for index=1,#off do near(off[index].voltage_v, 7, 'off voltage ' .. index) end

local plans = analyzer.static_electrode_plans(nil)
assert(#plans.accelerator == 8, 'combined static accelerator plan changed')
assert(#plans.legacy_accelerator_characterization == 9,
  'legacy accelerator characterization plan changed')
for index=1,8 do
  assert(plans.legacy_accelerator_characterization[index].electrode_id == index,
    'legacy accelerator local electrode mapping changed')
  near(plans.legacy_accelerator_characterization[index].voltage_v,
    plans.accelerator[index].voltage_v,
    'legacy accelerator characterization voltage ' .. index)
end
assert(plans.legacy_accelerator_characterization[9].electrode_id == 9,
  'legacy accelerator local reference-ground mapping changed')
near(plans.legacy_accelerator_characterization[9].voltage_v, 0,
  'legacy accelerator reference-ground voltage')
assert(#plans.reflectron == 19, 'static reflectron plan changed')
near(plans.reflectron[1].voltage_v, 0, 'reflectron entrance voltage')
near(plans.reflectron[12].voltage_v, 1628.8001, 'reflectron middle-grid voltage')
near(plans.reflectron[18].voltage_v, 2531.1999, 'reflectron backplate voltage')
near(plans.reflectron[19].voltage_v, 0, 'reflectron shield voltage')

local workbench = analyzer.initialize_workbench({instances={
  {filename='flight_tube_ground.pa0',nx=1001,ny=501,nz=2,dx_mm=1,
    dy_mm=1,dz_mm=1,scale=1},
  {filename='reflectron.pa0',nx=401,ny=501,nz=2,dx_mm=1,
    dy_mm=1,dz_mm=1,scale=1},
  {filename='accelerator.pa0',nx=101,ny=101,nz=101,dx_mm=0.25,
    dy_mm=0.25,dz_mm=0.05,scale=1},
  {filename='detector_ground.pa0',nx=3,ny=3,nz=8,dx_mm=1,
    dy_mm=1,dz_mm=0.05,scale=1},
}})
near(workbench.placements.accelerator.x_mm, -61.3,
  'accelerator linked x placement')
near(workbench.placements.detector.z_mm, -0.15,
  'detector linked z placement')
near(workbench.placements.flight_tube.z_mm, -64.92918680341103,
  'flight-tube linked z placement')

local override_config = config()
override_config.instance_filenames.accelerator = 'frontend.pa0'
local override_analyzer = component.new(override_config)
override_analyzer.initialize_workbench({instances={
  {filename='flight_tube_ground.pa0',nx=1001,ny=501,nz=2,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='reflectron.pa0',nx=401,ny=501,nz=2,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='frontend.pa0',nx=101,ny=101,nz=101,dx_mm=0.25,dy_mm=0.25,dz_mm=0.05,scale=1},
  {filename='detector_ground.pa0',nx=3,ny=3,nz=8,dx_mm=1,dy_mm=1,dz_mm=0.05,scale=1},
}})

local function rejects_workbench(instances, expected)
  local ok, message = pcall(function()
    component.new(config()).initialize_workbench({instances=instances})
  end)
  assert(not ok, 'invalid workbench payload was accepted')
  assert(tostring(message):find(expected, 1, true),
    'unexpected workbench rejection: ' .. tostring(message))
end
rejects_workbench({
  {filename='reflectron.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='flight_tube_ground.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='accelerator.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='detector_ground.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
}, 'flight_tube payload filename differs')
rejects_workbench({
  {filename='flight_tube_ground.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='reflectron.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='wrong.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
  {filename='detector_ground.pa0',nx=1,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,scale=1},
}, 'accelerator payload filename differs')

local field = analyzer.efield_adjust({z_mm=-18, instance_id=3,
  instance_dx_mm=0.25, instance_dz_mm=0.05, instance_scale=1})
assert(field.replace_all == true, 'ideal accelerator must replace all derivatives')
near(field.dvoltsz_gu, -(2240-1760)/3*0.05,
  'ideal accelerator stage-one derivative')

-- Canonical birth epoch belongs to the assembler.  Changing it must not alter
-- this component's solver-local timeout or detector interpolation.
local birth_epoch_a_us = 0.25
local birth_epoch_b_us = 1000.25
assert(birth_epoch_a_us ~= birth_epoch_b_us)
analyzer.initialize_particle({particle_id=1,elapsed_us=0,x_mm=48.8,y_mm=0,z_mm=1})
local cap = analyzer.tstep_adjust({x_mm=48.8,y_mm=0,z_mm=1,
  vx_mm_per_us=0,vy_mm_per_us=0,vz_mm_per_us=-2,
  detector_cell_dx_mm=1})
near(cap, 0.51, 'detector capture timestep')
local action = analyzer.other_actions({particle_id=1,elapsed_us=0.5,
  x_mm=48.8,y_mm=0,z_mm=0.01,vz_mm_per_us=-2})
assert(action.splat == false, 'valid particle was timed out')
local hit = analyzer.terminate({particle_id=1,instance_id=4,elapsed_us=0.5,
  x_mm=48.8,y_mm=0,z_mm=-0.01,vx_mm_per_us=0,vy_mm_per_us=0,
  vz_mm_per_us=-2,detector_cell_dx_mm=1})
assert(hit.kind == 'detector_crossing', 'detector termination role changed')
near(hit.elapsed_us, 0.495, 'detector local-elapsed crossing interpolation')

local epoch_independent = component.new(config())
epoch_independent.initialize_particle({particle_id=1,elapsed_us=0,
  x_mm=48.8,y_mm=0,z_mm=1})
local before_timeout = epoch_independent.other_actions({particle_id=1,
  elapsed_us=89.999,x_mm=48.8,y_mm=0,z_mm=1,vz_mm_per_us=-2})
local at_timeout = epoch_independent.other_actions({particle_id=1,
  elapsed_us=90,x_mm=48.8,y_mm=0,z_mm=1,vz_mm_per_us=-2})
assert(before_timeout.splat == false and at_timeout.splat == true,
  'birth epoch changed the solver-local timeout boundary')

local function rejects(mutator, expected)
  local value = config()
  mutator(value)
  local ok, message = pcall(component.new, value)
  assert(not ok, 'invalid component contract was accepted')
  assert(tostring(message):find(expected, 1, true),
    'unexpected rejection message: ' .. tostring(message))
end
rejects(function(value) value.electrode_ids.grid2 = 12 end,
  'oaTOF electrode IDs must be unique')
rejects(function(value) value.instance_roles.detector = 3 end,
  'instance roles must be unique')
rejects(function(value) value.unofficial = true end, 'unknown field')

print('OATOF_ANALYZER_COMPONENT_TEST=PASS')
