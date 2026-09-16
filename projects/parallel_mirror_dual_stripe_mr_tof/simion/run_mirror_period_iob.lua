local iob=assert(arg[1],'mirror period IOB required')
for _,suffix in ipairs({'.lua','.fly2','.local_refinement.lua','.probe.lua'}) do
  local path=iob:gsub('%.iob$',suffix)
  local handle=assert(io.open(path,'rb'),'missing mirror period companion: '..path)
  handle:close()
end
simion.command('fly "'..iob..'"')
print('MRTOF_MIRROR_PERIOD_IOB_FLIGHT=PASS')
