-- Bounded raw native callback evidence. This module does not infer a terminal cause.
local M = {}
local keys = {'schema_version','particle_id','ion','native_run','ion_run','capture_sequence','event',
  'raw_birth_us','raw_tof_us','raw_step_us','source_origin_us','pipeline_clock_us','instrument_time_us',
  'instance','x_mm','y_mm','z_mm','vx_mm_per_us','vy_mm_per_us','vz_mm_per_us','splat','grouped'}

local function json_value(value,key)
  local kind=type(value)
  if kind=='number' then
    assert(value==value and math.abs(value)<math.huge,'terminal recorder nonfinite field: '..key)
    return string.format('%.17g',value)
  end
  if kind=='boolean' then return value and 'true' or 'false' end
  if kind~='string' then return 'null' end
  return '"'..value:gsub('[%z\1-\31\\"]',function(c)
    if c=='\\' then return '\\\\' end
    if c=='"' then return '\\"' end
    return string.format('\\u%04x',string.byte(c))
  end)..'"'
end

local function encode(row)
  local parts={}
  for i,key in ipairs(keys) do parts[i]='"'..key..'":'..json_value(row[key],key) end
  return '{'..table.concat(parts,',')..'}'
end

local function pack(...) return {n=select('#',...),...} end

function M.install(segment, options)
  assert(type(segment)=='table' and type(options)=='table','terminal recorder requires segment and options')
  assert(type(options.native_run)=='string' and options.native_run~='', 'terminal recorder requires explicit native run token')
  for _,name in ipairs({'particle_id','source_origin_us','pipeline_clock_us','instrument_time_us'}) do
    assert(type(options[name])=='function','terminal recorder requires callback '..name)
  end
  local emit=options.emit or print
  assert(type(emit)=='function','terminal recorder emit must be callable')
  local original_run,original_init,original_actions,original_terminate=
    segment.initialize_run,segment.initialize,segment.other_actions,segment.terminate
  local states={}
  local function key()
    assert(type(ion_number)=='number' and ion_number>=1 and ion_number%1==0
      and type(ion_run)=='number' and ion_run>=1 and ion_run%1==0,
      'terminal recorder requires positive integer native ion and run IDs')
    return tostring(ion_run)..':'..tostring(ion_number)
  end
  local function capture(state,event,action)
    state.sequence=state.sequence+1
    local row={schema_version=1,particle_id=options.particle_id(),ion=ion_number,native_run=options.native_run,
      ion_run=ion_run,capture_sequence=state.sequence,event=event,raw_birth_us=ion_time_of_birth,
      raw_tof_us=ion_time_of_flight,source_origin_us=options.source_origin_us(),
      pipeline_clock_us=options.pipeline_clock_us(),instrument_time_us=options.instrument_time_us(),
      instance=ion_instance,x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
      vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,grouped=sim_grouped}
    if action then row.raw_step_us=ion_time_step;row.splat=ion_splat end
    return row
  end
  function segment.initialize_run(...)
    local result=original_run and pack(original_run(...)) or {n=0}
    states={}
    return unpack(result,1,result.n)
  end
  function segment.initialize(...)
    local result=original_init and pack(original_init(...)) or {n=0}
    local id=key()
    assert(states[id]==nil,'terminal recorder duplicate initialize')
    local state={sequence=0};states[id]=state
    state.initial=capture(state,'initialize',false)
    return unpack(result,1,result.n)
  end
  function segment.other_actions(...)
    local state=assert(states[key()],'terminal recorder action before initialize')
    state.before=capture(state,'other_actions_before',true)
    local result=original_actions and pack(original_actions(...)) or {n=0}
    state.after=capture(state,'other_actions_after',true)
    return unpack(result,1,result.n)
  end
  function segment.terminate(...)
    local id=key();local state=assert(states[id],'terminal recorder terminate before initialize')
    local terminal=capture(state,'terminate',false)
    local function write(row) if row then emit('SIMION_TERMINAL_V1:'..encode(row)) end end
    write(state.initial);write(state.before);write(state.after);write(terminal)
    states[id]=nil
    if original_terminate then return original_terminate(...) end
  end
end

return M
