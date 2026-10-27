-- Native loader-only fixture: one tiny collision PA, no field solve or flight.
local root, mode, seed, launcher = assert(arg[1]), assert(arg[2]), arg[3], arg[4]
local iob, collision = root..'/load.iob', root..'/collision.pa'
local function write(path, text)
  local file = assert(io.open(path, 'wb')); file:write(text); file:close()
end
if mode == 'prepare' then
  local pa = assert(simion.pas:open())
  pa:size(11,11,11)
  pa.potential_type = 'electric'
  pa.refined, pa.refinable = false, false
  pa:save(collision); pa:close()
  simion.wb:load(assert(seed))
  assert(#simion.wb.instances == 1)
  local instance = simion.wb.instances[1]
  instance.pa:load(collision); instance:_debug_update_size()
  instance.x, instance.y, instance.z = 0, 0, 0
  instance.az, instance.el, instance.rt, instance.scale = 0, 0, 0, 1
  simion.wb:save(iob)
  -- Deliberately persist a refinable, unsolved ordinary collision array,
  -- matching the historical file condition protected by the production loader.
  instance.pa.refined, instance.pa.refinable = false, true
  instance.pa:save(collision)
  write(root..'/load.lua', "simion.workbench_program()\nfunction segment.initialize_run() error('fixture must not Fly') end\n")
  write(root..'/load.fly2', 'particles { standard_beam { n=1,mass=100,charge=1,ke=1,position=vector(5,5,5),direction=vector(1,0,0) } }\n')
  write(root..'/load.operating_point.lua', 'return {static_field={collision_pa_path='..string.format('%q',collision)..'}}\n')
  print('WORKBENCH_LOAD_FIXTURE_PREPARE=PASS NODES=1331 REFINE=False FLY=False')
elseif mode == 'load' then
  local input = assert(simion.pas:open(collision))
  assert(input.refinable == true, 'fixture must start from a refinable file')
  input:close()
  arg = {iob, root..'/load.fly2', 'load-workbench'}
  dofile(assert(launcher))
  assert(#simion.wb.instances == 1 and simion.wb.instances[1].pa.refinable == false)
  assert(simion.wb.instances[1].pa.nx == 11 and simion.wb.instances[1].pa.ny == 11
    and simion.wb.instances[1].pa.nz == 11)
  print('WORKBENCH_LOAD_NATIVE=PASS INSTANCES=1 NODES=1331 REFINE=False FLY=False PA_SAVE=False')
else
  error('unknown loader fixture operation')
end
