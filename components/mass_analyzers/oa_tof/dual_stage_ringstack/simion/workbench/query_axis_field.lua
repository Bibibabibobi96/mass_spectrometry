simion.command('"oatof_ideal.iob"')
local wb = simion.wb
local zlist = {-0.5, 1.5, 3, 19.83, 30, 100, 619.0, 619.83, 630.0, 739.83}
for _,z in ipairs(zlist) do
  local ok, ex, ey, ez = pcall(function() return wb:efield(0,0,z) end)
  if ok then
    print(string.format('z_mm=%.3f Ex=%.9g Ey=%.9g Ez=%.9g', z, ex or 0, ey or 0, ez or 0))
  else
    print(string.format('z_mm=%.3f ERROR=%s', z, tostring(ex)))
  end
end
