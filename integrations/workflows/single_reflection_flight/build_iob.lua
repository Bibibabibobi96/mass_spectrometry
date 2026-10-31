-- Process-local paths are transport; the same core owns physical IOB controls.
-- Persistent build specs are never rewritten with this execution representation.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local root=assert(source:match('^(.*)/integrations/workflows/single_reflection_flight/build_iob%.lua$'),
  'builder must retain its frozen package and common native path companion')
local native_path=assert(loadfile(root..'/common/paths/native_run_path.lua'))()
local spec=dofile(native_path(assert(arg[1], 'frozen IOB build specification is required')))
local mode=arg[2] or 'build'
for _,key in ipairs({'seed_iob','output_iob'}) do
  if type(spec[key])=='string' then spec[key]=native_path(spec[key]) end
end
for _,key in ipairs({'instances','response_fields'}) do
  if type(spec[key])=='table' then
    for _,row in ipairs(spec[key]) do
      if type(row.path)=='string' then row.path=native_path(row.path) end
    end
  end
end
-- Program/FLY2 companions share the projected output stem. The locator remains
-- injected only for paths discovered while independently reopening an old IOB.
local core=assert(loadfile(root..'/integrations/workflows/single_reflection_flight/build_iob_core.lua'))()
return core(spec,mode,native_path)
