-- The shared GEM preprocessing/build transport. No Refine, Fast Adjust or Fly.
local M={}
function M.gem2pa(source,output,variables)
  local staged_source=output:gsub('%.pa#$','.source.gem')
  assert(staged_source~=output,'raw geometry output must end in .pa#')
  local input=assert(io.open(source,'rb'))
  local content=input:read('*a');input:close()
  local staged=assert(io.open(staged_source,'wb'))
  assert(staged:write(content));assert(staged:close())
  local previous=_G.var
  _G.var=variables
  local okay,message=pcall(function()
    simion.command(string.format('gem2pa %q %q',staged_source,output))
  end)
  _G.var=previous
  -- Preserve the primary build error; cleanup never changes its identity.
  os.remove(staged_source)
  os.remove(staged_source:gsub('%.gem$','.processed.gem'))
  assert(okay,message)
end
return M
