function oatof_build_grid_geometry(geom1,z_mid_expr)
%% Idealized mesh grids: FULL 800x800mm interior boundaries (no aperture
% needed at all -- the ion passes through anywhere), embedded via
% Union+intbnd into the vacuum. Four grids now: grid1 (accelerator,
% forms a weak bracket field with repeller for low KE spread), grid2
% (accelerator exit, always grounded, marks the field-free interface),
% entgrid (reflectron entrance, always grounded), midgrid (reflectron
% stage1/stage2 boundary, V_mid).
% !!! SIMPLIFIED per explicit request: removed gridA/gridB/accelmid
% entirely. New accelerator: repeller(z=0)->grid1(z=3mm)->grid2(z=6mm=
% L_accel). Ion releases between repeller and grid1 (z0 in [1,2]mm,
% unchanged) -- repeller+grid1 form the SAME "weak bracket field" role
% that gridA/gridB used to serve, just using the accelerator's own two
% real electrodes instead of a separate dedicated pair. grid1's voltage
% (V_grid1, set above) is derived from the desired initial KE and KE
% spread, NOT chosen arbitrarily. grid1 and grid2 have no direct
% relationship (per explicit statement) -- just spatially separated by
% another 3mm.
% !!! grid1/grid2 sized to match the square shield's bore EXACTLY
% (2*accel_shield_half=70mm) -- flat idealized interior boundaries can
% safely sit FLUSH against the shield's bore (validated in
% test_square_shield_accel.m: selb_g1/selb_g2 boundary count=1, no
% overlap issue) since they're not separate solid conductors, unlike the
% ring electrodes which need an actual gap.
% !!! entgrid/midgrid UNIFIED with accelflightbox's own (now
% ring_outer_r-derived) sizing: changed from a fixed, unrelated 800mm to
% 2*(ring_outer_r+20mm), EXACTLY matching accelflightbox above. This is
% a hard TOPOLOGY requirement, not just a style preference: a WorkPlane
% cutting through a vacuum block to form an interior boundary must span
% the block's FULL cross-section at that z, or a "frame" of vacuum
% around its edges is left uncovered, breaking the interior-boundary
% topology. First attempt sized entgrid/midgrid to ring_outer_r+10mm
% while accelflightbox was still the OLD fixed 800mm -- smaller than the
% box, leaving exactly this kind of uncovered frame, and corrupting the
% field-free drift region (previously exact -0.0000 V/m everywhere,
% became -0.17 to +0.45 V/m) even though selection-count diagnostics
% alone might have looked passable. Fixed by narrowing accelflightbox to
% match instead of just shrinking entgrid/midgrid independently -- both
% now derive from the SAME ring_outer_r+20mm expression.
% !!! Shapes per explicit request: grid1 (inside the accelerator's own
% SQUARE shield) stays a square Rectangle. grid2 (shared accelerator-
% exit/flight-tube-entrance grid) and entgrid (flight-tube-exit/
% reflectron-entrance grid) are now CIRCLES matching the (now
% cylindrical) flight tube -- sized to flight_tube_r exactly, since
% both are at 0V, the SAME potential as the flight tube's own grounded
% wall (no short-circuit concern, and exact match is REQUIRED for
% topology: a WorkPlane cutting through a vacuum domain must span that
% domain's full cross-section, see the accelflightbox-narrowing lesson
% above). midgrid (entirely inside the reflectron, bordered by reflvac
% on both sides) is also a circle, matching ring_outer_r exactly --
% same reasoning as the rings/backplate already touching reflvac's own
% edge safely (reflvac isn't a charged conductor).
% !!! Explicit x-center column added (5th column): grid2/entgrid (flight
% tube boundary grids) are centered on the ACCELERATOR's own axis (x=0),
% matching accelflightbox. midgrid sits BETWEEN the stage1/stage2 rings,
% which are centered on x_refl_center -- it must match THEM, not
% default to the workplane's own origin (0,0). Previously midgrid's
% Circle was created with no explicit 'pos', silently defaulting to
% (0,0) instead of x_refl_center -- a real axis-misalignment bug (only
% harmless by coincidence if x_refl_center happened to be 0). Now that
% x_refl_center is ALSO reset to 0 (see below, unifying the whole
% system on one axis), this is currently a no-op numerically, but is
% fixed explicitly so a future non-zero x_refl_center won't silently
% reintroduce the same misalignment.
% !!! grid2 REVERTED from the large shared circle (flight_tube_r) back
% to a small square, per the end-cap redesign (doc §7.42): the end cap
% is now at z=0 (the flight tube's OTHER end, opposite the reflectron),
% NOT at z=L_accel -- so grid2, at z=L_accel, has nothing to do with the
% end cap's hole sizing at all. It goes back to sealing ONLY the
% accelerator's own aperture, no longer coupled to flight_tube_r or the
% end cap in any way.
% !!! TRIED (first attempt) shrinking grid1/grid2/entgrid ALL by a gap
% from their shield's own bore -- broke the field-free region badly
% (residual jumped to -8.07V/m at z=25mm). REFINED understanding (doc
% §7.48, per explicit request): the BOUNDARY grids that mark the
% transition between "inside a sealed grounded enclosure" and "the
% exterior field-free region" (grid2 at the accelerator's exit, entgrid
% at the flight-tube/reflectron transition) MUST fully seal (touch their
% shield exactly) -- shrinking THESE is what caused the leak, since it
% opened a path to the exterior. But grid1 and midgrid sit ENTIRELY
% INSIDE an already-sealed enclosure (grid1: inside accelshield's tube,
% with grid2 sealing the only exit; midgrid: inside the flight-tube
% shield, which is now one continuous grounded shell with both ends
% closed per §7.46) -- any small gap they leave stays CONTAINED within
% that sealed box and cannot leak to the exterior. So: grid1 shrunk to
% match repeller/ring size (2*(accel_shield_half-accel_ring_gap)=66mm,
% same accel_ring_gap discipline as every other charged accelerator
% electrode); grid2/entgrid kept at full size (still the sealing
% boundaries); midgrid (charged, V_mid) shrunk to a real gap from the
% flight-tube shield instead of touching flight_tube_r directly.
% !!! midgrid radius CHANGED from flight_tube_r-10mm (10mm gap) to
% ring_outer_r (per explicit request, to match the SAME 50mm gap to
% flight_tube_r that the ring stack/backplate already use) -- midgrid
% sits entirely inside the already-sealed flight-tube shield (same as
% before), so this is purely a "make the gap consistent across all of
% the reflectron's charged internal components" change, not a topology
% fix; §4.5's "sealed enclosure contains internal leakage" reasoning
% still applies unchanged.
% !!! grid1/grid2 (accelerator-internal grids) now centered at
% x_accel_center too, matching repeller/accelring_k/accelshield's own
% shift (doc §7.50) -- entgrid/midgrid stay on the true flight-tube axis
% (x=0/x_refl_center=0), unchanged: by the time the ion reaches entgrid
% (roughly the flight's halfway point), its x-drift from x_accel_center
% has carried it back to ~0, matching the reflectron's own true-axis
% centering -- the symmetric design is self-consistent at this crossing
% point.
gridspecs = {
    'wp_grid1',     'z_accel_grid1' 'square'  '2*(accel_shield_half-accel_ring_gap)'  'x_accel_center'
    'wp_grid2',     'z_accel_grid2' 'square'  '2*accel_shield_half'  'x_accel_center'
    'wp_entgrid',   'L_flight'      'circle'  'flight_tube_r'         '0'
    'wp_midgrid',   z_mid_expr      'circle'  'ring_outer_r'          'x_refl_center'
};
for gi_ = 1:size(gridspecs,1)
    wptag = gridspecs{gi_,1};
    zexpr = gridspecs{gi_,2};
    wshape = gridspecs{gi_,3};
    wsize = gridspecs{gi_,4};
    wxc = gridspecs{gi_,5};
    wp = geom1.feature.create(wptag, 'WorkPlane');
    wp.set('quickplane', 'xy');
    wp.set('quickz', zexpr);
    if strcmp(wshape, 'square')
        wp.geom.feature.create('r1', 'Rectangle');
        wp.geom.feature('r1').set('size', {wsize, wsize});
        wp.geom.feature('r1').set('pos', {[wxc '-(' wsize ')/2'], ['-(' wsize ')/2']});
    else
        wp.geom.feature.create('c1', 'Circle');
        wp.geom.feature('c1').set('r', wsize);
        wp.geom.feature('c1').set('pos', {wxc, '0'});
    end
end
geom1.feature.create('uni_grids', 'Union');
geom1.feature('uni_grids').label('Embed all 4 idealized grids as interior boundaries (backplate is a real solid again, handled via soliddoms)');
geom1.feature('uni_grids').selection('input').set({'accelflightbox', ...
    'wp_grid1','wp_grid2','wp_entgrid','wp_midgrid'});
geom1.feature('uni_grids').set('intbnd', true);

end
