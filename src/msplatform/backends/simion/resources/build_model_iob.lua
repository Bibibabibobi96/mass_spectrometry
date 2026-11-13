-- Explicit unsolved-model entry: no same-stem Program, particle or field hook.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local directory=assert(source:match('^(.*)/'))
local native_path=assert(loadfile(assert(arg[3],'native path resource required')))()
local spec=dofile(native_path(assert(arg[1],'model IOB specification required')))
local mode=assert(arg[2],'model operation required')
local marker=spec.role=='rf_ip_geometry_iob_build' and 'RF_IP_MODEL_' or
  spec.role=='dual_cone_geometry_iob' and 'DUAL_CONE_MODEL_' or
  spec.role=='independent_oa_geometry_iob_build' and 'INDEPENDENT_OA_MODEL_' or
  spec.role=='independent_rf_geometry_iob_build' and 'INDEPENDENT_RF_MODEL_' or 'SINGLE_REFLECTION_MODEL_'
assert(mode=='build_model' or mode=='verify_model','unsupported model operation')
for _,key in ipairs({'seed_iob','output_iob'}) do spec[key]=native_path(spec[key]) end
for index,path in ipairs(spec.bootstrap_paths) do spec.bootstrap_paths[index]=native_path(path) end
for _,row in ipairs(spec.instances) do row.path=native_path(row.path) end
for key,path in pairs(spec.model) do spec.model[key]=native_path(path) end
assert(loadfile(directory..'/iob_core.lua'))()(spec,mode,native_path)
if mode=='build_model' then
  print(marker..'BUILD=PASS FLY=False SOURCE=False REFINE=False')
  io.stdout:flush()
  return
end
local config=dofile(spec.model.configuration)
local consumer=dofile(spec.model.consumer).new(config,dofile(spec.model.rf_drive),
  dofile(spec.model.pulse_hook),dofile(spec.model.waveforms),
  spec.model.native_drive and assert(loadfile(spec.model.native_drive)) or nil)
local description=consumer.describe()
assert(description.model_identity_sha256==config.model_identity_sha256,'model consumer identity differs')
local times,seen={0},{[0]=true}
local function time(value)
  assert(type(value)=='number' and value==value and math.abs(value)<math.huge,'nonfinite model readback time')
  if not seen[value] then times[#times+1]=value;seen[value]=true end
end
local domains={}
for _,row in ipairs(spec.instances) do
  domains[spec.role=='single_reflection_iob_build' and row.role=='accelerator' and 'parent' or row.role]=true
end
local bound={}
for _,row in ipairs(description.groups) do
  assert(type(row.instance_id)=='string' and type(row.electrode_group_id)=='string','model scientific identity missing')
  assert(type(row.native_targets)=='table' and #row.native_targets>0,'model native member mapping missing')
  for _,target in ipairs(row.native_targets) do
    assert(domains[target.domain],'model target domain is not in the saved geometry')
    assert(type(target.electrode_id)=='number' and target.electrode_id%1==0
      and target.electrode_id>=1 and target.electrode_id<=1000,'model native label invalid')
    local key=target.domain..':'..target.electrode_id
    assert(not bound[key],'model scientific groups alias a native label');bound[key]=true
  end
  if row.kind=='rf' then time(1e6/row.frequency_hz/4);time(1e6/row.frequency_hz/2) end
end
if config.ip_schedule then
  local s=config.ip_schedule.baseline.schedule
  local n=config.ip_schedule.native_timing
  for _,value in ipairs({s.capture_end_us,s.transfer_end_us,s.lift_end_us,n.primary_quench_us,n.pulse_start_us}) do time(value) end
end
if config.pulse and config.pulse.mode=='timed' then
  time(config.pulse.time_us);time(config.pulse.time_us+config.pulse.width_us)
end
table.sort(times)
local output=assert(io.open(spec.model.report,'wb'))
local okay,message=pcall(function()
  output:write('SIMION_MODEL_DRIVE_READBACK schema=1 field_status=not_solved source_status=not_requested\n')
  output:write('model_identity_sha256='..config.model_identity_sha256..'\n')
  if config.native_frame_id then output:write('native_frame_id='..config.native_frame_id..'\n') end
  output:write('clock_epoch_id='..config.clock.clock_epoch_id..' authority_sha256='..config.clock.authority_sha256..'\n')
  output:write('PA_ELECTRODE_LABELS_ARE_NOT_VOLTAGES=True\n')
  for _,t in ipairs(times) do
    local values=consumer.evaluate_at(t)
    assert(#values==#description.groups,'model consumer group coverage differs')
    for index,value in ipairs(values) do
      local row=description.groups[index]
      assert(value.instance_id==row.instance_id and value.electrode_group_id==row.electrode_group_id,
        'model consumer reordered scientific identities')
      assert(type(value.voltage_v)=='number' and value.voltage_v==value.voltage_v
        and math.abs(value.voltage_v)<math.huge,'model consumer voltage nonfinite')
      for _,target in ipairs(row.native_targets) do
        output:write(string.format('group=%q instance=%q domain=%q native_label=%d time_us=%.17g voltage_v=%.17g kind=%q',
          row.electrode_group_id,row.instance_id,target.domain,target.electrode_id,t,value.voltage_v,row.kind))
        if row.kind=='rf' then
          output:write(string.format(' waveform=%q frequency_hz=%.17g phase_rad=%.17g amplitude_v=%.17g polarity=%d common_v=%.17g dc_v=%.17g',
            row.waveform,row.frequency_hz,row.phase_rad,row.rf_amplitude_v,row.polarity,row.common_mode_v,row.dc_v))
        elseif row.kind=='pulse' then
          output:write(string.format(' pulse_mode=%q off_v=%.17g on_v=%.17g',config.pulse.mode,row.off_voltage_v,row.on_voltage_v))
          if config.pulse.mode=='timed' then output:write(string.format(' start_us=%.17g width_us=%.17g',config.pulse.time_us,config.pulse.width_us)) end
        end
        output:write('\n')
      end
    end
  end
end)
output:close()
assert(okay,message)
print(marker..'READBACK=PASS GROUPS='..#description.groups..' FIELD_STATUS=not_solved FLY=False SOURCE=False REFINE=False')
io.stdout:flush()
