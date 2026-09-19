-- Conditional post-P2 replay.  Static, manifest-bound operating PAs only.
simion.workbench_program()
simion.early_access(8.2)
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local operating_point = assert(loadfile(program_path:gsub('%.lua$', '.operating_point.lua')),
  'missing post-P2 operating-point sidecar')()
local local_refinement = assert(loadfile(program_path:gsub('%.lua$', '.local_refinement.lua')),
  'missing immutable local-refinement sidecar')()
assert(local_refinement.enabled == true and #local_refinement.instances == 5,
  'post-P2 replay requires the retained eight-instance 0.25-mm workbench')

local detector_box = assert(operating_point.detector_box_mm)
local mirror_z = assert(operating_point.positive_mirror_z_mm)
local bridge = assert(operating_point.bridge_plane)
local replay_branch = assert(operating_point.replay_branch)
local transparent_planes = assert(operating_point.transparent_planes_z_mm)
assert(operating_point.accelerator_field_state == 'grounded_after_frozen_pulse',
  'post-P2 replay must preserve the original return-time accelerator-off field state')
local transparent_detector = replay_branch == 'transparent_planes'
assert(replay_branch == 'mechanical_detector' or transparent_detector,
  'post-P2 replay branch must be mechanical_detector or transparent_planes')
assert(#transparent_planes == 4 and transparent_planes[1] == 97
  and transparent_planes[2] == 72 and transparent_planes[3] == 26
  and transparent_planes[4] == 0,
  'transparent replay planes must be the reviewed z=97,72,26,0 sequence')
assert(#detector_box == 6 and detector_box[1] < detector_box[4]
  and detector_box[2] < detector_box[5] and detector_box[3] < detector_box[6])
assert(#mirror_z == 2 and mirror_z[1] < mirror_z[2])
assert(bridge.name == 'handoff_positive_bridge_to_mirror__z_plane'
  and bridge.z_mm == 105 and bridge.x_min_mm < bridge.x_max_mm
  and bridge.y_min_mm < bridge.y_max_mm)

adjustable trajectory_quality = assert(operating_point.trajectory_quality)
adjustable maximum_step_us = assert(operating_point.maximum_step_us)
local timeout_us = assert(operating_point.post_p2_timeout_us)
local detector_z = detector_box[6]
local tolerance = math.max(1e-9, 1e-9*math.max(
  math.abs(detector_box[1]),math.abs(detector_box[2]),math.abs(detector_box[3]),
  math.abs(detector_box[4]),math.abs(detector_box[5]),math.abs(detector_box[6])))

local previous_x,previous_y,previous_z = {},{},{}
local previous_vx,previous_vy,previous_vz,previous_t = {},{},{},{}
local stage,turn_count,bridge_count,detected,plane_emitted = {},{},{},{},{}
local splat_codes,splat_emitted = {},{}

local function local_instance_definition(instance_number)
  for _,definition in ipairs(local_refinement.instances) do
    if definition.instance == instance_number then return definition end
  end
end

function segment.instance_adjust()
  -- In the transparent branch, suppress only the independent, zero-voltage
  -- detector instance.  Official overlap fallback then selects the unchanged
  -- analyser/local PA below it.  Accelerator instance 7 remains physical and
  -- may collide with the replay before z=0.
  if transparent_detector and ion_instance == 8 then ion_instance = 0; return end
  local definition = local_instance_definition(ion_instance)
  if definition == nil then return end
  local lower_ok = definition.z_min_mm == nil or ion_pz_mm >= definition.z_min_mm
  local upper_ok = definition.z_max_mm == nil or ion_pz_mm < definition.z_max_mm
  if not (lower_ok and upper_ok) then ion_instance = 0 end
end

local function interpolate(fraction)
  return {
    t=previous_t[ion_number]+fraction*(ion_time_of_flight-previous_t[ion_number]),
    x=previous_x[ion_number]+fraction*(ion_px_mm-previous_x[ion_number]),
    y=previous_y[ion_number]+fraction*(ion_py_mm-previous_y[ion_number]),
    z=previous_z[ion_number]+fraction*(ion_pz_mm-previous_z[ion_number]),
    vx=previous_vx[ion_number]+fraction*(ion_vx_mm-previous_vx[ion_number]),
    vy=previous_vy[ion_number]+fraction*(ion_vy_mm-previous_vy[ion_number]),
    vz=previous_vz[ion_number]+fraction*(ion_vz_mm-previous_vz[ion_number])
  }
end

function segment.initialize_run()
  sim_trajectory_quality = trajectory_quality
  previous_x,previous_y,previous_z = {},{},{}
  previous_vx,previous_vy,previous_vz,previous_t = {},{},{},{}
  stage,turn_count,bridge_count,detected,plane_emitted = {},{},{},{},{}
  splat_codes,splat_emitted = {},{}
  assert(simion.wb and #simion.wb.instances == 8,
    'post-P2 replay requires exactly eight workbench instances')
  local names={{'iob_input_analyzer%.pa$','analyzer%.pa$'},
    {'iob_input_local_1%.pa$','local_negative_mirror%.pa0$'},
    {'iob_input_local_2%.pa$','local_negative_bridge%.pa0$'},
    {'iob_input_local_3%.pa$','local_central%.pa0$'},
    {'iob_input_local_4%.pa$','local_positive_bridge%.pa0$'},
    {'iob_input_local_5%.pa$','local_positive_mirror%.pa0$'},
    {'iob_input_accelerator%.pa$','accelerator%.pa$'},
    {'iob_input_detector%.pa$','detector%.pa$'}}
  for index,patterns in ipairs(names) do
    local filename=simion.wb.instances[index].filename
    assert(filename:match(patterns[1]) or filename:match(patterns[2]),
      string.format('post-P2 instance %d is not a private standalone PA',index))
  end
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step,maximum_step_us)
end

function segment.efield_adjust()
  -- The frozen full flight switches the accelerator off before target-K and
  -- never re-energizes it.  Retain instance 7 collision geometry but suppress
  -- only its electric field during this rebased-tob post-P2 replay.
  if ion_instance == 7 then
    ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu = 0,0,0
  end
end

function segment.initialize()
  if previous_z[ion_number] ~= nil then return end
  previous_x[ion_number],previous_y[ion_number],previous_z[ion_number] = ion_px_mm,ion_py_mm,ion_pz_mm
  previous_vx[ion_number],previous_vy[ion_number],previous_vz[ion_number] = ion_vx_mm,ion_vy_mm,ion_vz_mm
  previous_t[ion_number] = ion_time_of_flight
  stage[ion_number],turn_count[ion_number],bridge_count[ion_number] = 'awaiting_positive_turn',0,0
  plane_emitted[ion_number]={}
end

function segment.other_actions()
  if ion_time_of_flight >= timeout_us and ion_splat == 0 then
    splat_codes[ion_number]=2; ion_splat=2
  end
  local px,py,pz = previous_x[ion_number],previous_y[ion_number],previous_z[ion_number]
  local pvx,pvy,pvz,pt = previous_vx[ion_number],previous_vy[ion_number],previous_vz[ion_number],previous_t[ion_number]
  if pz ~= nil then
    local dz=ion_pz_mm-pz
    if stage[ion_number]=='awaiting_positive_turn' and pvz>0 and ion_vz_mm<=0 then
      local fraction=pvz/(pvz-ion_vz_mm)
      local event=interpolate(fraction)
      if event.z>=mirror_z[1] and event.z<=mirror_z[2] then
        stage[ion_number]='awaiting_bridge_exit'; turn_count[ion_number]=1
        print(string.format('MRTOF_EVENT return_positive_mirror_turn ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=0',
          ion_number,event.t,event.x,event.y,event.z,event.vx,event.vy))
      end
    end
    if stage[ion_number]=='awaiting_bridge_exit' and dz<0 and pz>bridge.z_mm and ion_pz_mm<=bridge.z_mm then
      local event=interpolate((bridge.z_mm-pz)/dz)
      if event.x>=bridge.x_min_mm and event.x<=bridge.x_max_mm
          and event.y>=bridge.y_min_mm and event.y<=bridge.y_max_mm then
        stage[ion_number]='awaiting_detector'; bridge_count[ion_number]=1
        print(string.format('MRTOF_EVENT patch_interface ion=%d name=%s region=%s face=%s n=1 direction=-1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number,bridge.name,bridge.region,bridge.face,event.t,event.x,event.y,event.z,event.vx,event.vy,event.vz))
      end
    end
    if transparent_detector and turn_count[ion_number]==1 and dz<0 then
      local labels={'detector_z97','handoff_z72','p2_near_z26','focus_z0'}
      for index,plane_z in ipairs(transparent_planes) do
        if not plane_emitted[ion_number][index] and pz>plane_z and ion_pz_mm<=plane_z then
          local event=interpolate((plane_z-pz)/dz)
          plane_emitted[ion_number][index]=true
          print(string.format('MRTOF_EVENT replay_plane ion=%d label=%s direction_z=-1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
            ion_number,labels[index],event.t,event.x,event.y,event.z,event.vx,event.vy,event.vz))
          if plane_z==0 and ion_splat==0 then
            splat_codes[ion_number]=3; splat_emitted[ion_number]=true
            print(string.format('MRTOF_EVENT splat ion=%d code=3 termination_kind=programmatic_plane_completion physical_collision=0 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=0 turns=1 central_crossings=0',
              ion_number,event.t,event.x,event.y))
            ion_splat=3
          end
        end
      end
    end
    local detector_contact_direction=0
    if ion_splat~=0 and ion_vz_mm<0 and math.abs(ion_pz_mm-detector_box[6])<=tolerance then
      detector_contact_direction=-1
    elseif ion_splat~=0 and ion_vz_mm>0 and math.abs(ion_pz_mm-detector_box[3])<=tolerance then
      detector_contact_direction=1
    end
    local crosses=(dz<0 and pz>detector_z and ion_pz_mm<=detector_z)
      or (dz>0 and pz<detector_z and ion_pz_mm>=detector_z)
    if not transparent_detector and (crosses or detector_contact_direction~=0) then
      local fraction=detector_contact_direction~=0 and 1 or (detector_z-pz)/dz
      if fraction>=0 and fraction<=1 then
        local event=interpolate(fraction)
        local direction=detector_contact_direction~=0 and detector_contact_direction or (dz<0 and -1 or 1)
        print(string.format('MRTOF_EVENT detector_plane ion=%d direction_z=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number,direction,event.t,event.x,event.y,detector_z,event.vx,event.vy,event.vz))
        if direction==-1 and stage[ion_number]=='awaiting_detector' and not detected[ion_number]
            and event.x>=detector_box[1] and event.x<=detector_box[4]
            and event.y>=detector_box[2] and event.y<=detector_box[5] then
          detected[ion_number]=true; stage[ion_number]='complete'
          print(string.format('MRTOF_EVENT detector ion=%d direction_z=-1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
            ion_number,event.t,event.x,event.y,detector_z))
          splat_codes[ion_number]=1; splat_emitted[ion_number]=true
          print(string.format('MRTOF_EVENT splat ion=%d code=1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=1 central_crossings=0',
            ion_number,event.t,event.x,event.y,detector_z))
          ion_splat=1
        end
      end
    end
  end
  if ion_splat~=0 and not splat_emitted[ion_number] then
    splat_codes[ion_number]=splat_codes[ion_number] or ion_splat
    splat_emitted[ion_number]=true
    print(string.format('MRTOF_EVENT splat ion=%d code=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=0',
      ion_number,splat_codes[ion_number],ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,turn_count[ion_number] or 0))
  end
  previous_x[ion_number],previous_y[ion_number],previous_z[ion_number] = ion_px_mm,ion_py_mm,ion_pz_mm
  previous_vx[ion_number],previous_vy[ion_number],previous_vz[ion_number] = ion_vx_mm,ion_vy_mm,ion_vz_mm
  previous_t[ion_number]=ion_time_of_flight
end

function segment.terminate()
  print(string.format('MRTOF_EVENT terminal ion=%d splat=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g turns=%d central_crossings=0',
    ion_number,splat_codes[ion_number] or ion_splat or 0,ion_time_of_flight,
    ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,turn_count[ion_number] or 0))
end
