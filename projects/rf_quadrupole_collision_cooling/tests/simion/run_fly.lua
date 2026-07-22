-- Compatibility entry point; automated runs use common/multipole/simion_run_fly.lua.
local shared = assert(os.getenv('MULTIPOLE_SIMION_RUN_FLY_LUA'),
  'MULTIPOLE_SIMION_RUN_FLY_LUA is not set')
dofile(shared)
