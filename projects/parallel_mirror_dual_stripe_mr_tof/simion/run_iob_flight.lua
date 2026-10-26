-- Run one already-materialized MR-TOF Workbench through SIMION's Fly command.
-- Usage: simion.exe --nogui lua run_iob_flight.lua RUN.iob [PARTICLES.fly2]
local iob = assert(arg[1], 'usage: RUN.iob')
local particles = arg[2]
assert(iob:match('%.iob$'), 'flight input must be an IOB')
local program = iob:gsub('%.iob$', '.lua')
local fly2 = iob:gsub('%.iob$', '.fly2')
local operating_point = iob:gsub('%.iob$', '.operating_point.lua')
for _, path in ipairs({program, fly2, operating_point}) do
  local file = assert(io.open(path, 'rb'), 'missing run-local Workbench companion: '..path)
  file:close()
end
if particles then
  assert(particles:match('%.fly2$'), 'particle override must be a Fly2 file')
  local file = assert(io.open(particles, 'rb'), 'missing particle override: '..particles)
  file:close()
end
-- Headless analysis consumes explicit event output, not SIMION's replay cache.
-- Match the repository SIMION runner: avoid generating trj*.tmp files that
-- compact retention would immediately remove.  The IOB and Fly2 remain fully
-- usable for a later interactive GUI flight.
local particle_option = particles and (' --particles="'..particles..'"') or ''
local operating = assert(loadfile(operating_point), 'invalid operating point')()
local collision = operating.static_field and operating.static_field.collision_pa_path
local collisions = {}
if collision and collision:lower():match('%.pa$') then collisions[1] = collision end
local overlay = operating.static_field and operating.static_field.collision_overlay
if overlay then
  assert(operating.accelerator_provider == 'dual_pressure_rectilinear_ion_processor'
      and operating.field_assembly_verified == true and overlay.schema_version == 1
      and overlay.role == 'mrtof_analyzer_collision_overlay'
      and type(overlay.pa_path) == 'string' and overlay.pa_path:lower():match('%.pa$')
      and #collisions == 1, 'collision patch preload requires the verified IP overlay projection')
  collisions[2] = overlay.pa_path
end
-- The prepared IP binding names its additional collision/detector carriers.
-- Transport only: these paths do not select or modify the callback's E field.
for _, path in ipairs(operating.static_field and operating.static_field.collision_geometry_pa_paths or {}) do
  assert(type(path) == 'string' and path:lower():match('%.pa$'),
    'collision geometry preload requires standalone PA paths')
  collisions[#collisions+1] = path
end
local preload_option = ''
local preloaded = {}
for _, collision in ipairs(collisions) do
  local normalized = collision:gsub('\\','/'):lower()
  if not preloaded[normalized] then
    -- Official SIMION field_array examples use refinable=false to prevent IOB
    -- load auto-Refine. This PA supplies collisions only; the callback owns E.
    -- A same-process IOB builder may already own this PA. The official integer
    -- inventory exposes full pa.path (pa.filename is only the basename).
    -- Reopening the resident object would create two
    -- matching PAs and make Fly --remove-pas=0 reject the IOB before any ions.
    -- Use the same slash/case normalization as scalar_field_adapter.lua.
    local function same_path(path)
      return type(path)=='string' and path:gsub('\\','/'):lower()==collision:gsub('\\','/'):lower()
    end
    local pa
    for index=1,#simion.pas do
      local candidate=simion.pas[index]
      local matching=same_path(candidate.path)
      print('MRTOF_COLLISION_PA_INVENTORY index='..index..' filename='..tostring(candidate.filename)
        ..' path='..tostring(candidate.path)..' exact_match='..tostring(matching))
      if matching then
        assert(pa==nil, 'ambiguous collision PA inventory: '..collision)
        pa=candidate
      end
    end
    local reused=pa~=nil
    pa=pa or assert(simion.pas:open(collision), 'collision PA preload failed')
    pa.refinable = false
    print('MRTOF_COLLISION_PA_PRELOAD existing_pa_reused='..tostring(reused)..' path='..collision)
    -- Keep the RAM-only flag on IOB load; never save or claim this PA was solved.
    preload_option = ' --remove-pas=0'
    preloaded[normalized] = true
  end
end
simion.command('fly --retain-trajectories=0'..preload_option..particle_option..' "'..iob..'"')
print('IOB_FLIGHT: PASS iob='..iob)
