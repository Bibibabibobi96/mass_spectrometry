function oatof_build_detector_geometry(geom1,geometryMm)
% Detector: a REAL solid object (must actually stop/detect the ion, not
% be transparent like the grids). Placed far out of the beam path for
% now -- repositioned once trajectories with the new grid design are
% measured (same "perfect condition" approach used throughout: verify
% the core physics is clean before introducing anything that could
% perturb it).
geom1.feature.create('detector', 'Cylinder');
geom1.feature('detector').label('Detector (grounded, solid, real physical stop)');
% !!! Widened from 10mm to 25mm: the first large-N resolution test
% (N=3000) showed R=22.5, MUCH worse than the earlier short-flight-tube
% result -- root cause was NOT the longer flight path itself, but an
% unintended coupling: ions have a real vx spread (from the 5+-1eV
% Gaussian energy), so at the extended flight length their x-spread at
% the detector's z-level grew large (172.9-188.6mm) relative to the old
% 10mm-radius window. Since the detector is a REAL SOLID object, an ion
% only gets absorbed once it geometrically enters this window -- ions
% with off-nominal vx need extra/less lateral drift TIME to reach a
% narrow window, contaminating the measured arrival time with an
% x-drift effect that has nothing to do with the mass-dependent
% z-direction TOF. Widening the window so ALL ions enter it at
% essentially the same z-crossing (regardless of their individual vx)
% decouples this.
% !!! Widened from 25mm to 40mm (doc §7.49): the detector now physically
% intercepts the ion (Wall/Freeze condition), and the upcoming d2 scan
% will shift the arrival time (and hence the ion's x-drift at impact)
% somewhat from point to point -- a larger radius gives comfortable
% tolerance across the scan range without needing to recompute the
% detector's exact x-position for every d2 value.
geom1.feature('detector').set('r', 'detector_radius');
geom1.feature('detector').set('h', sprintf('%.12g[mm]', geometryMm.detector_thickness));
% !!! Repositioned to the measured landing spot (x=27.45-28.05mm at
% z~22mm, measured directly after the accelflightbox/reflvac gap fix --
% the ion now genuinely completes a clean round trip). r=10mm centered
% at x=28 spans x=[18,38], comfortably covering the tight measured
% footprint while excluding x=0 (the outbound pass's position at this
% z, avoiding the earlier "blocks the outbound pass" bug).
% !!! TEMPORARILY moved far away for re-measurement diagnostic (per the
% "perfect condition" methodology): the 10x longer L_flight means total
% round-trip x-drift will be roughly 10x larger too, so the old x=28mm
% position is almost certainly wrong now -- measure the real landing
% spot first, unobstructed, before repositioning the detector.
% !!! Repositioned to the re-measured landing spot for the extended
% L_flight=3000mm (x=173.5-190.2mm, mean 183.2mm -- ~6.5x farther out
% than the old 300mm-flight-tube landing spot, since total round-trip
% x-drift scales with the ~10x longer total TOF).
% !!! TEMPORARILY moved far away for re-measurement diagnostic (per the
% "perfect condition" methodology): L_flight dropped drastically
% (3000->320mm), so the old x=183mm calibration is almost certainly
% wrong now -- measure the real landing spot first, unobstructed.
% !!! Repositioned to the re-measured landing spot for the compact
% redesign (L_flight=320mm): return xEnd measured at x=26.6-28.7mm.
% !!! Repositioned to the re-measured landing spot: return xEnd measured
% at x=172-175mm (mean 173mm) for the 200/500/500mm design.
% !!! CORRECTED: the earlier x=173mm estimate came from a stale/wrong
% measurement. Direct unrestricted-crossing check at z=25 (just past the
% detector plane) measured x tightly clustered at 79.4-80.6mm -- using
% that value instead recovered 100% detection (was 25/50) and R=396.7
% (was 91.5, itself an artifact of the miscalibrated narrow window).
% !!! TEMPORARILY moved far away for re-measurement diagnostic (within
% the 800x800mm domain's x range of [-400,400]).
% !!! Moved closer to the field-free boundary (grid2, z=L_accel): the
% Mamyrin dual-stage theory's L2 (reflectron-to-detector drift) is
% measured from z=L_accel, not from wherever the detector happened to
% sit.
% !!! Per explicit request, z moved to EXACTLY L_accel (was L_accel+
% 0.3mm) so L2=L_flight-L_accel=500.00mm holds EXACTLY, matching L1
% exactly too (both now precisely 500mm, L_total=1000mm exactly, no
% 0.3mm residual). This reintroduces the geometric conflict the old
% +0.3mm offset was created to avoid (detector's flat face exactly
% !!! MOVED (doc §7.48, per explicit request) from x=420mm (parked off
% to the side, avoiding any overlap with grid2's disk) to x=94.93mm --
% the ion's ACTUAL x-position at detection time, so the detector sits
% exactly where the returning ion hits, "parallel to the accelerator
% exit" (same z as grid2/L_accel, matching L2=500mm exactly). Derived
% from x=v_x*t: v_x=3106.2 m/s (the 5eV transverse entrance speed,
% constant throughout the whole flight since there's no x-direction
% force) times the measured mean detection time (~30.56-30.57us) =~
% 94.93mm. This value is mass-independent: v_x scales as 1/sqrt(m) for
% fixed 5eV transverse KE, while total flight time scales as sqrt(m) for
% fixed accelerating voltage -- the two dependencies cancel, so the same
% x-position is correct regardless of which ion mass is simulated.
% Detector (solid, 0V) now spatially overlaps grid2's disk (also 0V,
% zero-thickness) at their shared z -- same-voltage overlap, matching
% the established benign pattern used throughout this design (verify
% empirically after this change, same as always).
% !!! FIXED (per explicit request): the ion returns traveling in the -z
% direction (coming back from the reflectron at large z, heading toward
% the source at small z), so it strikes the detector's TOP face (the
% +z-facing surface) FIRST, not the bottom face. Cylinder's 'pos' is the
% BASE (bottom, smaller-z) center -- with pos.z=detector_z directly, the
% detector spanned z=[detector_z, detector_z+h], meaning its ion-facing
% TOP surface sat at detector_z+h (1mm PAST the intended L2=500mm
% position), not AT detector_z where L2 is actually measured from. Moved
% back by h so the TOP (ion-striking) face lands exactly at detector_z.
% !!! x updated to +48.80mm (doc §7.50, per explicit request): the
% accelerator (and hence the ion's release point) is now shifted to
% x_accel_center=-48.80mm, and the detector sits at the MIRROR position
% +48.80mm=-x_accel_center, so the ion's release point and detection
% point are symmetric about the flight tube's true cylindrical axis
% (x=0) -- rather than the ion starting exactly on-axis and drifting
% one-sided to an off-axis detector as before. Detector radius kept at
% 40mm for tolerance margin.
geom1.feature('detector').set('pos', {'detector_x' '0' sprintf('detector_z-%.12g[mm]', geometryMm.detector_thickness)});

end
