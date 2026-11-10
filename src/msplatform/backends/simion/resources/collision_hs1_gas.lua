-- Project gas-input binding to the unchanged official HS1 callback interface.
-- SIMION-2020 examples/collision_hs1/collision_hs1.lua:259-283: callback
-- positions are GU, but callers may use ion_*_mm; velocity is mm/us, not SDS m/s.
local M={}
function M.bind(hs,field,position,frame_id)
  local function sample()
    local x,y,z=position()
    local state=field.sample(x,y,z,frame_id)
    assert(state.status=='gas' or state.status=='vacuum',
      'gas field coverage lost: '..tostring(state.status))
    return state
  end
  hs.pressure=function() return sample().pressure_pa end
  hs.temperature=function() return sample().temperature_k end
  hs.velocity=function()
    local velocity=assert(sample().bulk_velocity_m_s,'HS1 gas velocity required')
    return velocity[1]/1000,velocity[2]/1000,velocity[3]/1000
  end
  return sample
end
return M
