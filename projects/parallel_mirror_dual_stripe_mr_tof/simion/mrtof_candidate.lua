-- Full MR-TOF Candidate workbench program.  Candidate/prototype only.
simion.workbench_program()

adjustable V_m1 = 0
adjustable V_m2 = -600
adjustable V_m3 = 1200
adjustable V_m4 = 3000
adjustable V_m5 = 5200
adjustable V_stripe_1 = -40
adjustable V_stripe_2 = 60
adjustable V_repeller = 4480
adjustable V_grid1 = 3520
adjustable V_grid2 = 0
adjustable V_nonaccelerator_scale = 1
adjustable trajectory_quality = 8
adjustable maximum_step_us = 0.002

local previous, turns, crossings = {}, {}, {}

function segment.initialize_run()
  sim_trajectory_quality = trajectory_quality
  previous, turns, crossings = {}, {}, {}
  print('MRTOF_CANDIDATE: status=prototype geometry=full_monolithic_3d')
end

function segment.fast_adjust()
  adj_elect01, adj_elect02, adj_elect03, adj_elect04, adj_elect05 = V_nonaccelerator_scale*V_m1,V_nonaccelerator_scale*V_m2,V_nonaccelerator_scale*V_m3,V_nonaccelerator_scale*V_m4,V_nonaccelerator_scale*V_m5
  adj_elect06, adj_elect07, adj_elect08, adj_elect09, adj_elect10 = V_nonaccelerator_scale*V_m1,V_nonaccelerator_scale*V_m2,V_nonaccelerator_scale*V_m3,V_nonaccelerator_scale*V_m4,V_nonaccelerator_scale*V_m5
  adj_elect11, adj_elect12 = V_nonaccelerator_scale*V_stripe_1,V_nonaccelerator_scale*V_stripe_1
  adj_elect13, adj_elect14 = V_nonaccelerator_scale*V_stripe_2,V_nonaccelerator_scale*V_stripe_2
  adj_elect15, adj_elect18, adj_elect19, adj_elect20, adj_elect21 = 0,0,0,0,0
  adj_elect16, adj_elect17 = 0,0
  adj_elect22, adj_elect23, adj_elect24, adj_elect25 = V_repeller,V_grid1,V_grid2,0
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.other_actions()
  local p = previous[ion_number]
  if p then
    if p.vz * ion_vz_mm < 0 then
      turns[ion_number] = (turns[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT turn ion=%d n=%d t_us=%.12g z_mm=%.12g', ion_number, turns[ion_number], ion_time_of_flight, ion_pz_mm))
    end
    if p.z * ion_pz_mm <= 0 then
      crossings[ion_number] = (crossings[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT central_plane ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g', ion_number, crossings[ion_number], ion_time_of_flight, ion_px_mm, ion_py_mm))
    end
  end
  previous[ion_number] = {z=ion_pz_mm, vz=ion_vz_mm}
end

function segment.terminate()
  print(string.format('MRTOF_EVENT terminal ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g turns=%d central_crossings=%d',
    ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm,
    turns[ion_number] or 0, crossings[ion_number] or 0))
end
