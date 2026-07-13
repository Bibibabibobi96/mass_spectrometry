simion.command('"oatof_grounded_tube.iob"')
local wb=simion.wb
for _,name in ipairs({'user_program','program','program_filename','lua','lua_filename','filename','path'}) do
 local ok,v=pcall(function() return wb[name] end)
 print(name .. '=' .. (ok and tostring(v) or ('ERR:'..tostring(v))))
end
