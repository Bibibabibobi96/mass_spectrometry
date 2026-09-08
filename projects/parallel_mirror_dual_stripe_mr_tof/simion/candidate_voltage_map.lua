-- Pure voltage-to-local-electrode mapping shared by flight and IOB assembly.
-- All physical values are explicit contract/adjustable inputs, in volts.
-- The zero values below preserve the Candidate's grounded topology.  This
-- mapper defines the static injection state; the flight program applies an
-- independently contracted P1/P2 extraction switch when one is requested.
local function finite(value,label)
  assert(type(value)=='number' and value==value and math.abs(value)<math.huge,
    label..' must be a finite number')
  return value
end
local function vector(values,count,label)
  assert(type(values)=='table' and #values==count,label..' has the wrong size')
  for index=1,count do finite(values[index],label..'['..index..']') end
end
return function(mirrors,stripes,prisms,endpoints,rings,scale)
  vector(mirrors,5,'mirror voltages')
  vector(stripes,2,'Stripe voltages')
  vector(prisms,2,'prism voltages')
  vector(endpoints,3,'accelerator endpoint voltages')
  vector(rings,5,'accelerator ring voltages')
  finite(scale,'nonaccelerator scale')
  assert(mirrors[1]==0,'mirror A must remain grounded')
  local analyser={}
  for index=1,5 do
    analyser[index]=finite(scale*mirrors[index],'scaled mirror voltage')
    analyser[index+5]=analyser[index]
  end
  for index=1,2 do
    local voltage=finite(scale*stripes[index],'scaled Stripe voltage')
    analyser[9+2*index]=voltage
    analyser[10+2*index]=voltage
  end
  analyser[15]=0
  analyser[16]=prisms[1]
  analyser[17]=prisms[2]
  analyser[18]=0
  analyser[20]=0
  -- Accelerator PA local IDs: ground/repeller/grid1/exit/rings = 1..9.
  local accelerator={[1]=0,[2]=endpoints[1],[3]=endpoints[2],[4]=endpoints[3]}
  for index,voltage in ipairs(rings) do accelerator[4+index]=voltage end
  return {analyser=analyser,accelerator=accelerator}
end
