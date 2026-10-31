-- Caller-owned CSV columns, precision and flushing; no physical event policy.
local M={}
local function quote(value)
 local text=tostring(value)
 if text:find('[,"\r\n]') then return '"'..text:gsub('"','""')..'"' end
 return text
end
function M.open(path,columns,precision)
 assert(type(precision)=='number' and precision%1==0 and precision>=1 and precision<=17,'CSV precision must be explicit')
 assert(type(columns)=='table' and #columns>0,'scientific CSV columns required')
 local names,header={},{}
 for i,column in ipairs(columns) do
  assert(type(column)=='string' and #column>0 and not names[column],'scientific CSV columns must be unique nonempty strings')
  names[column]=true;header[i]=quote(column)
 end
 local stream=assert(io.open(path,'w'),'scientific CSV cannot be opened: '..path)
 local writer={}
 local numeric_format='%.'..precision..'g'
 local function write(text)
  local ok,reason=stream:write(text)
  assert(ok,'scientific CSV write failed: '..tostring(reason))
 end
 write(table.concat(header,',')..'\n')
 function writer:write(values)
  assert(#values==#columns,'scientific CSV row width differs')
  local rendered={}
  for i=1,#columns do
   local value=values[i]
   assert(value~=nil,'scientific CSV row contains nil')
   if type(value)=='number' then rendered[i]=string.format(numeric_format,value)
   else rendered[i]=quote(value) end
  end
  write(table.concat(rendered,',')..'\n')
 end
 function writer:flush() local ok,reason=stream:flush();assert(ok,'scientific CSV flush failed: '..tostring(reason)) end
 function writer:close() local ok,reason=stream:close();assert(ok,'scientific CSV close failed: '..tostring(reason)) end
 return writer
end
return M
