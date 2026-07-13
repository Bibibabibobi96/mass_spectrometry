-- oa-TOF ideal-grid particle passage for SIMION 8.2.
--
-- This is a numerical zero-thickness interface: each grid remains an
-- electrode for the field solve, but an ion is moved from epsilon upstream
-- to epsilon downstream before SIMION can register an electrode splat.
-- The time of the traversed numerical buffer is added explicitly.  No
-- transmission loss, angular kick, or energy loss is applied.
--
-- IMPORTANT: This is the ideal-grid baseline only.  Its epsilon-convergence
-- test must pass before it is used for resolving-power results.

adjustable ideal_grid_epsilon_mm = 0.01

local grids = {
  {name='grid1',   z=3.0},
  {name='grid2',   z=19.83},
  {name='entgrid', z=619.83},
  {name='midgrid', z=739.83},
}

local last_z = {}
local jumped = {}

local function key(ion, grid) return tostring(ion) .. ':' .. grid.name end

function segment.initialize()
  last_z[ion_number] = ion_pz_mm
end

function segment.other_actions()
  local n = ion_number
  local z = ion_pz_mm
  local vz = ion_vz_mm
  local zprev = last_z[n] or z
  local eps = ideal_grid_epsilon_mm
  if eps <= 0 then error('ideal_grid_epsilon_mm must be positive') end

  for _,g in ipairs(grids) do
    local k = key(n,g)
    local dir = vz >= 0 and 1 or -1
    local pre  = g.z - dir*eps
    local post = g.z + dir*eps

    -- Arm again only after the ion has moved a finite distance away.  This
    -- supports the reflected return pass without a duplicate immediate jump.
    if jumped[k] and math.abs(z-g.z) > 4*eps then jumped[k] = nil end

    local crossed_pre = dir > 0 and zprev < pre and z >= pre
                     or dir < 0 and zprev > pre and z <= pre
    if not jumped[k] and crossed_pre then
      -- Advance from the current integration point to the matching point on
      -- the other side.  Adding this time prevents a shortened TOF path.
      -- With fractional surfaces and epsilon=0.01 mm, the omitted field
      -- impulse is then checked by epsilon convergence before publication.
      local dz = math.abs(post-z)
      if math.abs(vz) < 1e-12 then error('grid jump attempted with vz=0') end
      ion_time_of_flight = ion_time_of_flight + dz/math.abs(vz)
      ion_pz_mm = post
      jumped[k] = true
      break
    end
  end
  last_z[n] = ion_pz_mm
end
