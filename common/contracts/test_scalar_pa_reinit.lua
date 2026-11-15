-- Portable API double: 51 scalar V/mask pairs, five unrelated workbench PAs.
simion={pas={},experimental={}}
function simion.early_access() end
local bad=false
local invalid_path=nil
function simion.pas:open(path)
  assert(#self<200,'200 PA container limit')
  local ismask=path:find('mask',1,true)~=nil
  local pa={path=path,saved=true,symmetry='3dplanar',nx=7,ny=7,nz=7,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,marked={}}
  function pa:potential(i,j,k) if ismask then return (bad or path==invalid_path) and 0 or 1 end return 2 end
  function pa:potential_vc() return 2 end
  function pa:electrode(i,j,k,value) assert(value==true);self.marked[i..','..j..','..k]=true;self.saved=false end
  self[#self+1]=pa;return pa
end
function simion.experimental.field_array() return {efield=function() return 1,2,3 end} end
for i=1,5 do simion.pas[i]={path='workbench'..i,unchanged='sentinel'} end
local adapter=assert(loadfile(arg[1]))()
local function level(name)
 return {mode='comsol_static_scalar_v',scalar_pa=name..'_V.pa',valid_pa=name..'_mask.pa',
   origin_mm={0,0,0},pitch_mm={1,1,1},dimensions={7,7,7},
   ideal_sheet_projection={}}
end
local bindings={}
for i=1,17 do
 local b=level('basis'..i..'_base')
 local a=level('basis'..i..'_a');a.name='a';a.active_box_mm={{2,3},{2,3},{2,3}}
 local c=level('basis'..i..'_b');c.name='b';c.active_box_mm={{3,4},{3,4},{3,4}}
 b.refinement_windows={a,c};bindings[i]=b
end
for pass=1,4 do
 for _,b in ipairs(bindings) do
  local q=adapter(b,'raw_sample')
  local v,x,y,z=q(2.5,2.5,2.5);assert(v==2 and x==1 and y==2 and z==3)
 end
 assert(#simion.pas==107,'reinitialization opened duplicate arrays')
end
local sheet=level('sheet')
sheet.ideal_sheet_projection={{k=2,i_min=2,i_max=2,j_min=2,j_max=2}}
adapter(sheet,'raw_sample');local marked=simion.pas[#simion.pas-1]
assert(marked.marked['2,2,2'] and not marked.saved,'sheet marker must dirty its PA')
local prior=#simion.pas
sheet.ideal_sheet_projection={};adapter(sheet,'raw_sample')
assert(#simion.pas==prior+1 and simion.pas[#simion.pas]~=marked and next(simion.pas[#simion.pas].marked)==nil,
  'empty binding reused a marked PA')
for i=1,5 do assert(simion.pas[i].unchanged=='sentinel' and simion.pas[i].marked==nil,'workbench modified') end
bad=true;local q=adapter(bindings[1],'raw_sample')
local ok,err=pcall(q,2.5,2.5,2.5);assert(not ok and tostring(err):find('V_SUPPORT_UNKNOWN',1,true))
bad=false
-- An incompatible object sharing a path must not be reused.
local old=simion.pas[6];old.nx=8
local before=#simion.pas;adapter(bindings[1],'raw_sample');assert(#simion.pas==before+1)
old.nx=7
local function displace(key,value)
 local changed={}
 for _,pa in ipairs(simion.pas) do if pa.path=='basis1_base_V.pa' then changed[#changed+1]={pa,pa[key]};pa[key]=value end end
 local count=#simion.pas;adapter(bindings[1],'raw_sample');assert(#simion.pas==count+1)
 for _,item in ipairs(changed) do item[1][key]=item[2] end
end
displace('dx_mm',2);displace('symmetry','3dplanar[x]')
local count
local distinct=level('different_path');count=#simion.pas;adapter(distinct,'raw_sample');assert(#simion.pas==count+2)
-- The actual composer must query a zero-coefficient unit's mask too.
local groups,units={},{}
for i=1,15 do
 groups[i]={kind='ip_schedule',instance_id='ip',electrode_group_id='g'..i}
 units[i]={instance_id='ip',electrode_group_id='g'..i,binding=bindings[i+1]}
end
local consumer={describe=function() return {schema_version=1,role='simion_model_drive',groups=groups} end,
 evaluate_at=function() local rows={} for i=1,15 do rows[i]={instance_id='ip',electrode_group_id='g'..i,voltage_v=0} end return rows end}
local composer=assert(loadfile(arg[2]))()
local query=composer.new(adapter,consumer,nil,{carrier=bindings[1],ip_unit_volt=units})
local inst={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1}}
function inst:wb_to_pa_orient(x,y,z) return x,y,z end
invalid_path='basis2_a_mask.pa'
local valid,why=pcall(query,inst,2.5,2.5,2.5,0)
assert(not valid and tostring(why):find('V_SUPPORT_UNKNOWN',1,true),'zero coefficient suppressed unknown support')
print('SCALAR_REINIT_PASS arrays=107 passes=4 invalid_refused=true wrong_shape_not_reused=true')
