-- Two actual world-potential workpoints; field adapter owns units and support.
local composer = {}

function composer.new(adapter, pulse, bindings)
  assert(type(adapter) == 'function', 'scalar adapter factory required')
  assert(type(pulse) == 'table' and type(pulse.is_active_at) == 'function', 'pulse hook required')
  assert(type(bindings) == 'table' and bindings.off ~= nil and bindings.on ~= nil,
    'OFF and ON scalar bindings required')
  local sharing = {}
  local off = adapter(bindings.off, nil, sharing)
  local on = adapter(bindings.on, nil, sharing)
  assert(type(off) == 'function' and type(on) == 'function', 'scalar query functions required')
  return function(instance, x, y, z, instrument_time_us)
    assert(instance ~= nil, 'selected instance required')
    -- Query both even when the gate is zero: invalid support is never hidden.
    local support = {}
    local ox, oy, oz = off(instance, x, y, z, support)
    local nx, ny, nz = on(instance, x, y, z, support)
    local active = pulse.is_active_at(instrument_time_us) and 1 or 0
    return ox + active * (nx - ox), oy + active * (ny - oy), oz + active * (nz - oz)
  end
end

return composer
