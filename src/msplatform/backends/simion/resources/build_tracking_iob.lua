-- Source-bearing saved-field workbench transport to the SAME canonical writer.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local directory=assert(source:match('^(.*)/'))
local native_path=assert(loadfile(assert(arg[3],'native path resource required')))()
local spec=dofile(native_path(assert(arg[1],'tracking IOB specification required')))
local mode=assert(arg[2],'tracking operation required')
assert(mode=='build' or mode=='verify','unsupported tracking workbench operation')
for _,key in ipairs({'seed_iob','output_iob'}) do spec[key]=native_path(spec[key]) end
for index,path in ipairs(spec.bootstrap_paths or {}) do spec.bootstrap_paths[index]=native_path(path) end
for _,row in ipairs(spec.instances) do row.path=native_path(row.path) end
for _,row in ipairs(spec.response_fields) do row.path=native_path(row.path) end
assert(loadfile(directory..'/iob_core.lua'))()(spec,mode,native_path)
if spec.role=='independent_rf_tracking_iob' then print(mode=='build' and 'INDEPENDENT_RF_TRACKING_IOB=PASS' or 'INDEPENDENT_RF_TRACKING_IOB_REOPEN=PASS') end

if spec.role=='dual_cone_tracking_iob' then print(mode=='build' and 'DUAL_CONE_TRACKING_IOB=PASS' or 'DUAL_CONE_TRACKING_IOB_REOPEN=PASS') end

if spec.role=='independent_oa_tracking_iob' then print(mode=='build' and 'INDEPENDENT_OA_TRACKING_IOB=PASS' or 'INDEPENDENT_OA_TRACKING_IOB_REOPEN=PASS') end

if spec.role=='rf_ip_tracking_iob' then print(mode=='build' and 'RF_IP_TRACKING_IOB=PASS' or 'RF_IP_TRACKING_IOB_REOPEN=PASS') end
