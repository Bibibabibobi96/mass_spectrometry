-- Project electrode schedule [V], using an injected shared RF kernel value.
-- No PA field or particle integration is implemented here.
local M={}
function M.pulse_start_us(c)
 return c.baseline.schedule.extraction_start_us+
  c.baseline.electric.rf_quench_delay_cycles*1e6/c.baseline.electric.rf_frequency_hz
end
function M.voltages(c,t,rf)
 local p,s=c.native_operating_point,c.baseline.schedule
 local transferred=t>=s.capture_end_us
 local hp=transferred and p.hp_transfer_offset_v or p.capture_hp_offset_v
 local guide_rf=rf*c.baseline.electric.guide_rf_peak_to_peak_v/c.baseline.electric.rf_peak_to_peak_v
 local lp=p.capture_lp_offset_v
 if t>=s.transfer_end_us then
  local u=math.min(1,(t-s.transfer_end_us)/(s.lift_end_us-s.transfer_end_us))
  lp=lp+(p.lift_v-lp)*u*u*(3-2*u)
 end
 local quenching=t>=s.extraction_start_us
 local extraction=t>=M.pulse_start_us(c)
 local lp_rf=quenching and 0 or rf
 local up=extraction and p.extraction_pull_relative_v or lp_rf
 local down=extraction and p.extraction_push_relative_v or lp_rf
 -- Published sequence: primary pair quenches first, split side pair half an
 -- RF cycle later; upper/lower halves receive the same pulse as Pull/Push.
 return {p.guide_offset_v+guide_rf,p.guide_offset_v-guide_rf,hp+rf,hp-rf,
  lp+up,lp+down,lp+(extraction and p.extraction_pull_relative_v or -rf),
  lp+(extraction and p.extraction_push_relative_v or -rf),
  hp+(transferred and p.hp_aux_transfer_relative_v or p.hp_aux_capture_relative_v),
  lp+p.lp_outer_relative_v,lp+p.lp_inner_relative_v,p.entrance_lens_v,
  lp+p.end_lens_relative_v,lp,hp}
end
return M
