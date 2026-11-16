-- Generic scientific CSV callback reconciliation; no project geometry or taxonomy.
local M = {}

local function commit(self,context)
  for _,item in ipairs(context.rows) do
    self.write(item.kind,item.row,item.extra)
    self.committed(item,context)
  end
end

function M.new(options)
  assert(type(options)=='table' and type(options.write)=='function'
    and type(options.committed)=='function' and type(options.deferred_kinds)=='table',
    'scientific reconciliation requires write, committed and deferred kinds')
  local self={write=options.write,committed=options.committed,
    deferred_kinds=options.deferred_kinds,pending={},active=nil}

  function self.reset()
    self.pending,self.active={},nil
  end

  function self.record(kind,row,extra)
    if kind and self.active and self.deferred_kinds[kind] then
      self.active.rows[#self.active.rows+1]={kind=kind,row=row,extra=extra}
    else
      self.write(kind,row,extra)
    end
  end

  function self.confirm_advance(ion,time)
    local contexts=self.pending[ion]
    if not contexts then return end
    local remaining={}
    for _,context in ipairs(contexts) do
      if time>context.after.t_us then commit(self,context)
      else remaining[#remaining+1]=context end
    end
    self.pending[ion]=#remaining>0 and remaining or nil
  end

  function self.begin(context)
    assert(self.active==nil,'scientific reconciliation callback is already active')
    assert(type(context)=='table' and type(context.ion)=='number'
      and type(context.before)=='table' and type(context.after)=='table'
      and type(context.before.t_us)=='number' and type(context.after.t_us)=='number',
      'scientific reconciliation requires explicit bracket endpoints')
    context.rows={}
    self.active=context
  end

  function self.finish()
    local context=self.active
    if context and #context.rows>0 then
      local contexts=self.pending[context.ion] or {}
      contexts[#contexts+1]=context
      self.pending[context.ion]=contexts
    end
    self.active=nil
  end

  function self.reconcile_terminal(ion,terminal_time)
    assert(type(terminal_time)=='number' and terminal_time==terminal_time
      and math.abs(terminal_time)<math.huge,'terminal reconciliation requires finite time')
    local contexts=self.pending[ion] or {}
    local unconfirmed={}
    for _,context in ipairs(contexts) do
      if terminal_time>=context.after.t_us and terminal_time>=context.before.t_us then
        commit(self,context)
      else
        for _,item in ipairs(context.rows) do
          local raw={}
          for key,value in pairs(item.row) do raw[key]=value end
          if item.extra then for key,value in pairs(item.extra) do raw[key]=value end end
          raw.field=item.kind
          if raw.native_splat==nil then raw.native_splat=context.native_splat end
          raw.status=tonumber(item.row.t_us)>terminal_time and 'rejected' or 'unknown'
          raw.reason=raw.status=='rejected' and 'terminal_precedes_candidate_event'
            or 'terminal_precedes_candidate_interval_end'
          for boundary,sample in pairs({before=context.before,after=context.after}) do
            for _,key in ipairs({'t_us','x_mm','y_mm','z_mm','vx_mm_us','vy_mm_us','vz_mm_us'}) do
              raw[boundary..'_'..key]=string.format('%.17g',sample[key])
            end
          end
          self.write('observation_candidate',raw)
          unconfirmed[item.kind]=(unconfirmed[item.kind] or 0)+1
        end
      end
    end
    self.pending[ion]=nil
    return unconfirmed
  end

  return self
end

return M
