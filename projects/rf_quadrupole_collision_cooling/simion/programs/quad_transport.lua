-- Compatibility entry point for manual project workbenches.
-- Automated runs freeze common/multipole/simion_transport.lua directly.
local shared = assert(os.getenv('MULTIPOLE_SIMION_SHARED_PROGRAM_LUA'),
  'MULTIPOLE_SIMION_SHARED_PROGRAM_LUA is not set')
dofile(shared)
