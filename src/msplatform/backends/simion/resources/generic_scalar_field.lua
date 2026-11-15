-- Generic admitted linear scalar composition driven by the canonical model consumer.
local M={}
function M.new(adapter,consumer,binding)
  assert(type(adapter)=='function' and type(consumer)=='table','actual adapter and model consumer required')
  local config=consumer.describe()
  assert(config.role=='simion_model_drive' and config.model_identity_sha256==binding.model_identity_sha256,'model identity differs')
  local expected={}
  for _,row in ipairs(config.groups) do
    expected[row.instance_id]=expected[row.instance_id] or {}
    assert(not expected[row.instance_id][row.electrode_group_id],'duplicate model group')
    expected[row.instance_id][row.electrode_group_id]=true
  end
  local bases={}
  for _,row in ipairs(binding.bases) do
    local seen={}
    for _,weight in ipairs(row.weights) do
      assert(expected[weight.instance_id] and expected[weight.instance_id][weight.electrode_group_id],'unknown weight group')
      seen[weight.instance_id]=seen[weight.instance_id] or {}
      assert(not seen[weight.instance_id][weight.electrode_group_id],'duplicate weight group')
      assert(type(weight.weight)=='number' and weight.weight==weight.weight and math.abs(weight.weight)<math.huge,'finite weight required')
      seen[weight.instance_id][weight.electrode_group_id]=true
    end
    for instance,groups in pairs(expected) do for group in pairs(groups) do
      assert(seen[instance] and seen[instance][group],'missing weight group')
    end end
    bases[#bases+1]={query=assert(adapter(row.binding)),weights=row.weights}
  end
  assert(#bases>0,'explicit scalar bases required')
  return function(instance,x,y,z,t)
    assert(instance~=nil and type(t)=='number' and t==t and math.abs(t)<math.huge,'finite instrument time required')
    local values={}
    for _,row in ipairs(consumer.evaluate_at(t)) do
      assert(expected[row.instance_id] and expected[row.instance_id][row.electrode_group_id],'unknown evaluated group')
      values[row.instance_id]=values[row.instance_id] or {}
      assert(values[row.instance_id][row.electrode_group_id]==nil,'duplicate evaluated group')
      assert(type(row.voltage_v)=='number' and row.voltage_v==row.voltage_v and math.abs(row.voltage_v)<math.huge,'finite group voltage required')
      values[row.instance_id][row.electrode_group_id]=row.voltage_v
    end
    for name,groups in pairs(expected) do for group in pairs(groups) do
      assert(values[name] and values[name][group]~=nil,'missing evaluated group')
    end end
    local ax,ay,az=0,0,0
    for _,base in ipairs(bases) do
      local coefficient=0
      for _,weight in ipairs(base.weights) do
        coefficient=coefficient+weight.weight*values[weight.instance_id][weight.electrode_group_id]
      end
      local ex,ey,ez=base.query(instance,x,y,z)
      ax,ay,az=ax+coefficient*ex,ay+coefficient*ey,az+coefficient*ez
    end
    assert(ax==ax and ay==ay and az==az and math.abs(ax)<math.huge and math.abs(ay)<math.huge and math.abs(az)<math.huge,'nonfinite composed gradient')
    return ax,ay,az
  end
end
return M
