-- Callback-neutral scalar composition; no workbench or particle state is owned here.
local composer={}

local function finite(value,label)
  assert(type(value)=='number' and value==value and math.abs(value)<math.huge,label..' must be finite')
  return value
end

function composer.new(adapter,model_consumer,rf_kernel,bindings)
  assert(type(adapter)=='function','scalar adapter factory required')
  assert(type(model_consumer)=='table' and type(model_consumer.evaluate_at)=='function'
    and type(model_consumer.describe)=='function','actual model drive consumer required')
  assert(type(bindings)=='table' and bindings.carrier~=nil and type(bindings.ip_unit_volt)=='table',
    'carrier and explicit IP unit bindings required')
  local config=model_consumer.describe()
  assert(type(config)=='table' and config.schema_version==1 and config.role=='simion_model_drive',
    'invalid actual model drive description')
  local expected,count,rf_signature={},0,nil
  for _,row in ipairs(config.groups) do
    if row.kind=='ip_schedule' then
      assert(type(row.instance_id)=='string' and type(row.electrode_group_id)=='string','invalid IP group identity')
      expected[row.instance_id]=expected[row.instance_id] or {}
      assert(not expected[row.instance_id][row.electrode_group_id],'duplicate IP model group')
      expected[row.instance_id][row.electrode_group_id]=true;count=count+1
    elseif row.kind=='rf' then
      local signature={waveform=row.waveform,frequency_hz=row.frequency_hz,phase_rad=row.phase_rad}
      if rf_signature then
        assert(signature.waveform==rf_signature.waveform and signature.frequency_hz==rf_signature.frequency_hz
          and signature.phase_rad==rf_signature.phase_rad,'multiple external RF signatures are unsupported')
      else rf_signature=signature end
    end
  end
  assert(count==15,'actual model must contain fifteen IP groups')
  local carrier=adapter(bindings.carrier)
  assert(type(carrier)=='function','carrier scalar query required')
  local units,seen={},{}
  for index,row in ipairs(bindings.ip_unit_volt) do
    assert(type(row)=='table' and expected[row.instance_id] and expected[row.instance_id][row.electrode_group_id]
      and row.binding~=nil,'IP binding must identify an actual model group')
    seen[row.instance_id]=seen[row.instance_id] or {}
    assert(not seen[row.instance_id][row.electrode_group_id],'duplicate IP unit binding')
    seen[row.instance_id][row.electrode_group_id]=true
    local query=adapter(row.binding);assert(type(query)=='function','IP scalar query required')
    units[index]={instance_id=row.instance_id,electrode_group_id=row.electrode_group_id,query=query}
  end
  assert(#units==15,'all fifteen IP unit bindings required')
  local array_count=0
  for key in pairs(bindings.ip_unit_volt) do
    assert(type(key)=='number' and key==math.floor(key) and key>=1 and key<=15,'IP bindings must be contiguous')
    array_count=array_count+1
  end
  assert(array_count==15,'IP bindings must be contiguous')
  local reference,wave
  assert((rf_signature~=nil)==(bindings.rf_reference~=nil),'RF reference must match actual model RF groups')
  if bindings.rf_reference~=nil then
    assert(type(bindings.rf_reference)=='table' and bindings.rf_reference.binding~=nil
      and type(bindings.rf_reference.signature)=='table','explicit RF reference and signature required')
    assert(type(rf_kernel)=='table' and type(rf_kernel.compile_physical)=='function','RF kernel required')
    local s=bindings.rf_reference.signature
    assert(s.phase_reference_instrument_time_us==0,'RF phase reference must be instrument time zero')
    assert(type(config.clock)=='table' and config.clock.phase_reference_instrument_time_us==0,
      'model RF clock reference differs')
    assert(s.waveform==rf_signature.waveform and s.frequency_hz==rf_signature.frequency_hz
      and s.phase_rad==rf_signature.phase_rad,'RF reference signature differs from actual model')
    wave=rf_kernel.compile_physical{waveform=s.waveform,frequency_hz=s.frequency_hz,
      phase_rad=s.phase_rad,rf_amplitude_v=1,rf_scale=1}
    reference=adapter(bindings.rf_reference.binding)
    assert(type(reference)=='function','RF scalar query required')
  end
  return function(instance,x,y,z,instrument_time_us)
    assert(instance~=nil,'selected instance required')
    finite(instrument_time_us,'instrument time')
    local evaluated=model_consumer.evaluate_at(instrument_time_us)
    assert(type(evaluated)=='table','model drive result required')
    local values={}
    for _,row in ipairs(evaluated) do
      if expected[row.instance_id] and expected[row.instance_id][row.electrode_group_id] then
        values[row.instance_id]=values[row.instance_id] or {}
        assert(values[row.instance_id][row.electrode_group_id]==nil,'duplicate evaluated IP group')
        values[row.instance_id][row.electrode_group_id]=finite(row.voltage_v,'IP group voltage')
      end
    end
    local cx,cy,cz=carrier(instance,x,y,z)
    for _,unit in ipairs(units) do
      local group_values=values[unit.instance_id]
      assert(group_values and group_values[unit.electrode_group_id]~=nil,'missing evaluated IP group')
      local value=group_values[unit.electrode_group_id]
      -- Query every support even if its physical coefficient is zero.
      local ex,ey,ez=unit.query(instance,x,y,z)
      cx,cy,cz=cx+value*ex,cy+value*ey,cz+value*ez
    end
    if reference then
      local ex,ey,ez=reference(instance,x,y,z)
      local coefficient=finite(wave.differential_at(instrument_time_us),'RF waveform')
      cx,cy,cz=cx+coefficient*ex,cy+coefficient*ey,cz+coefficient*ez
    end
    return finite(cx,'composed x gradient'),finite(cy,'composed y gradient'),finite(cz,'composed z gradient')
  end
end

return composer
