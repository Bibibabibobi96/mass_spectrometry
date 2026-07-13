local template = [[template_random\random.iob]]
simion.command('"' .. template .. '"')
assert(simion.wb, 'Workbench did not load')
print('WB=' .. tostring(simion.wb))
local mt = getmetatable(simion.wb)
print('wb_metatable=' .. tostring(mt))
for k,v in pairs(mt or {}) do print('wb_mt.' .. tostring(k) .. '=' .. tostring(v)) end
print('instances=' .. tostring(#simion.wb.instances))
for i=1,#simion.wb.instances do
  local inst=simion.wb.instances[i]
  print('INSTANCE ' .. i .. '=' .. tostring(inst))
  for _,name in ipairs({'pa','x','y','z','az','el','rt','scale','filename','path','label','potential_type'}) do
    local ok,value=pcall(function() return inst[name] end)
    print('inst.' .. i .. '.' .. name .. '=' .. (ok and tostring(value) or ('ERR:' .. tostring(value))))
  end
end
