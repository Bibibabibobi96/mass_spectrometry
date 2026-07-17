function accelringtags = oatof_build_accelerator_geometry(geom1)
%% Solid electrodes (repeller, rings, backplate) -- unchanged technique
% (Difference: outer solid minus bore, auto Form Union with a vacuum
% envelope). These are real solid objects the ion never passes through
% (repeller: ion starts near it and moves away; rings: ion flies through
% the empty bore, never touching the annulus material; backplate: a
% plain full disk, no bore at all -- see its own feature below for why).
% !!! Changed from a circular Cylinder (r=100mm) to a rectangular Block:
% per explicit request, since the ion's initial distribution is only a
% 1mm cube and it barely drifts in x/y during the (very brief, ~14ns)
% acceleration crossing (~0.04mm of x-drift at vx=3106m/s), the repeller
% doesn't need to be anywhere near as large as the old "radius >> gap"
% sizing -- a few tens of mm is plenty. 40x40mm chosen (2x the 20mm
% accel gap, comfortably still in the "large plate" regime for a beam
% that stays this close to the axis).
% !!! RESIZED (doc §7.47, per explicit request) from a fixed 40mm to
% match the accelerator ring electrodes' own OUTER profile exactly:
% 2*(accel_shield_half-accel_ring_gap) = 66mm. This gives repeller the
% SAME accel_ring_gap(2mm) clearance from the shield's inner bore that
% the ring electrodes already have -- consistent sizing across all the
% accelerator's charged solid electrodes.
geom1.feature.create('repeller', 'Block');
geom1.feature('repeller').label('Repeller (pulses 0->V_repeller, solid, rectangular, ion never passes through it)');
geom1.feature('repeller').set('size', {'2*(accel_shield_half-accel_ring_gap)', '2*(accel_shield_half-accel_ring_gap)', 'accel_repeller_thickness'});
geom1.feature('repeller').set('pos', {'x_accel_center-(accel_shield_half-accel_ring_gap)', '-(accel_shield_half-accel_ring_gap)', 'z_accel_origin-accel_repeller_thickness'});

% !!! Square shield tube around the accelerator (repeller to grid2): a
% thin grounded square-annular wall (Block-minus-Block, same technique
% as the reflectron rings but square instead of cylindrical), validated
% in isolation via test_square_shield_accel.m (see notes above). Spans
% the accelerator z-range (bracket + second stage) so grid1/grid2 can
% both sit flush against its bore.
% !!! Doc §7.47 (per explicit request): merged the separate 'repback'
% plate INTO this same single Difference, exactly the same "one big
% block minus one smaller block" technique used for the flight-tube
% shield (§7.46) -- accelshieldO now extends accel_shield_wall FURTHER
% back than accelshieldH's own back face, so the "extra" solid material
% left behind automatically forms an integrated back cap, with no
% separate feature needed. (An earlier attempt removed the back-sealing
% plate entirely, assuming repeller's new, smaller ring-sized gap
% wouldn't need it -- wrong: repeller sits at the very FRONT of the
% shield tube with open buffer vacuum directly behind it, unlike the
% rings which are fully surrounded by vacuum on both sides within the
% sealed bore. Even a small 2mm gap around repeller's edge reconnects to
% that buffer vacuum and leaks field forward -- confirmed: field-free
% residual rose to 0.16V/m without any back seal, vs 0.0016V/m with the
% old separate repback. This integrated-cap version achieves the same
% seal without a second Difference feature.) The shield's FORWARD end
% still ends exactly at z=L_accel (grid2's position), unaffected.
geom1.feature.create('accelshieldO', 'Block');
geom1.feature('accelshieldO').label('Accelerator shield outer solid (includes integrated back cap)');
geom1.feature('accelshieldO').set('size', {'2*(accel_shield_half+accel_shield_wall)', '2*(accel_shield_half+accel_shield_wall)', 'L_accel+accel_repeller_thickness+accel_shield_back_extra+accel_shield_wall'});
geom1.feature('accelshieldO').set('pos', {'x_accel_center-(accel_shield_half+accel_shield_wall)', '-(accel_shield_half+accel_shield_wall)', 'z_accel_origin-accel_repeller_thickness-accel_shield_back_extra-accel_shield_wall'});
geom1.feature.create('accelshieldH', 'Block');
geom1.feature('accelshieldH').label('Accelerator shield bore (stops accel_shield_wall short of the outer solid''s back face, leaving the integrated back cap)');
geom1.feature('accelshieldH').set('size', {'2*accel_shield_half', '2*accel_shield_half', 'L_accel+accel_repeller_thickness+accel_shield_back_extra'});
geom1.feature('accelshieldH').set('pos', {'x_accel_center-accel_shield_half', '-accel_shield_half', 'z_accel_origin-accel_repeller_thickness-accel_shield_back_extra'});
geom1.feature.create('accelshield', 'Difference');
geom1.feature('accelshield').label('Accelerator shield (grounded, one-piece: side walls + integrated back cap)');
geom1.feature('accelshield').selection('input').set({'accelshieldO'});
geom1.feature('accelshield').selection('input2').set({'accelshieldH'});

% !!! Flight-tube shield (doc §7.46, simplified per explicit request):
% REMOVED the separate 'endcap'/'endcap2'/'flighttubewall' three-feature
% design (which had a real geometric OVERLAP between endcap and
% flighttubewall's own end -- both occupied the same z-range at radius
% [flight_tube_r, flight_tube_r+flight_tube_wall]). Replaced with a
% SINGLE Difference (one big outer Cylinder minus one smaller inner
% Cylinder, both ends automatically closed by construction, no overlap
% possible) -- see 'flighttubewallO/H/flighttubewall' below, built right
% after accelflightbox so the bore dimensions are defined in one place.

% !!! 5 intermediate graded square ring electrodes between grid1 (z=3mm)
% and grid2 (z=L_accel): maintains field linearity across the 16.83mm
% gap (comparable to the 35mm shield half-width, so 2 endpoints alone
% would fringe -- same reasoning as the reflectron's own ring-stack).
% Each ring needs a REQUIRED vacuum gap from the shield wall (different-
% voltage conductors cannot touch -- see doc §7.32 for the hard-won
% lesson from the cylindrical attempt).
accelringtags = {};
for k = 1:5
    tagk = sprintf('accelring_%d', k);
    zk_expr = sprintf('z_accel_origin+3[mm]+%d*(L_accel-3[mm])/6', k);
    Vk_expr = sprintf('V_grid1*(1-%d/6)', k);
    outer_half = 'accel_shield_half-accel_ring_gap';
    geom1.feature.create([tagk 'O'], 'Block');
    geom1.feature([tagk 'O']).label(sprintf('Accelerator ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('size', {['2*(' outer_half ')'], ['2*(' outer_half ')'], 'accel_ring_thickness'});
    geom1.feature([tagk 'O']).set('pos', {['x_accel_center-(' outer_half ')'], ['-(' outer_half ')'], [zk_expr '-accel_ring_thickness/2']});
    geom1.feature.create([tagk 'H'], 'Block');
    geom1.feature([tagk 'H']).label(sprintf('Accelerator ring %d bore', k));
    geom1.feature([tagk 'H']).set('size', {'2*accel_ring_bore_half', '2*accel_ring_bore_half', 'accel_ring_thickness'});
    geom1.feature([tagk 'H']).set('pos', {'x_accel_center-accel_ring_bore_half', '-accel_ring_bore_half', [zk_expr '-accel_ring_thickness/2']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Accelerator ring %d (V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    accelringtags{end+1} = tagk; %#ok<AGROW>
end
end
