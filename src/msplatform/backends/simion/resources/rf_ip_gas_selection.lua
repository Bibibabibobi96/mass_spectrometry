-- Select the explicit finite IP bath before the independently supplied outer field.
-- Each field retains its own placement, endpoint ownership and coverage errors.
local M={}
function M.new(bath,outer)
  assert(type(bath)=='table' and type(bath.sample)=='function','explicit IP bath required')
  assert(type(outer)=='table' and type(outer.sample)=='function','explicit outer gas field required')
  return {sample=function(x,y,z,frame)
    local state=bath.sample(x,y,z,frame)
    assert(type(state)=='table' and type(state.status)=='string','invalid IP bath result')
    if state.status~='outside_domain' then return state end
    local outside=outer.sample(x,y,z,frame)
    assert(type(outside)=='table' and type(outside.status)=='string','invalid outer gas result')
    return outside
  end}
end
return M
