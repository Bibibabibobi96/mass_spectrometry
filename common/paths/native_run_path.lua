-- Process-local native spelling. Persistent identities remain canonical.
return function(path)
  assert(type(path)=='string','native path must be a string')
  local persistent=os.getenv('MASS_SPECTROMETRY_RUN_DIRECTORY')
  local execution=os.getenv('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
  if persistent==nil and execution==nil then return path end
  assert(persistent and persistent~='' and execution and execution~='',
    'native run projection requires both canonical and execution directories')
  local root=persistent:gsub('\\','/'):gsub('/+$','')
  local candidate=path:gsub('\\','/')
  local compare_root,compare_candidate=root,candidate
  if root:match('^%a:/') or root:sub(1,2)=='//' then
    compare_root=root:lower();compare_candidate=candidate:lower()
  end
  if compare_candidate~=compare_root and compare_candidate:sub(1,#compare_root+1)~=compare_root..'/' then
    return path
  end
  local relative=candidate:sub(#root+1):gsub('^/','')
  for part in relative:gmatch('[^/]+') do
    assert(part~='..','native run projection requires a normalized contained path')
  end
  if relative=='' then return execution end
  return execution:gsub('[/\\]+$','')..'/'..relative
end
