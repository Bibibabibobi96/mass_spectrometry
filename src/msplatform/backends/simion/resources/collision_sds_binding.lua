-- Joint static gas input for the actual official SDS callbacks. No RNG,
-- supplier reset, trajectory advancement or cross-callback sample cache.
local binding={}
function binding.install(SDS,field,options)
  assert(type(field.sample)=='function','joint gas sample function required')
  assert(options.outside_domain_policy=='error' or options.outside_domain_policy=='coverage_loss',
    'explicit gas outside-domain policy required')
  assert(type(field._sample_sds)=='function','compiled numeric SDS gas projection required')
  local function query(channel,x,y,z)
    if options.is_support_lost() then return nil end
    local a,b,c=options.position(x,y,z)
    local status,v1,v2,v3=field._sample_sds(channel,a,b,c,options.frame_id)
    if status=='gas' or status=='vacuum' then return true,v1,v2,v3 end
    if status=='no_data' or (status=='outside_domain' and options.outside_domain_policy=='coverage_loss') then
      options.on_coverage_lost()
      return nil
    end
    if status=='outside_domain' then error('gas-field query outside governed domain') end
    error('unsupported gas query status: '..tostring(status))
  end
  SDS.pressure=function(x,y,z)
    local ok,value=query('pressure',x,y,z)
    return (ok and value or 0)*(760/101325)
  end
  SDS.temperature=function(x,y,z)
    local ok,value=query('temperature',x,y,z)
    return ok and value or 300
  end
  SDS.velocity=function(x,y,z)
    local ok,a,b,c=query('velocity',x,y,z)
    if not ok then a,b,c=0,0,0 end
    return options.velocity(a,b,c)
  end
  SDS.install()
end
return binding
