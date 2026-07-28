function oatof_build_drift_geometry(geom1,sourceDesign,ringtags,accelringtags)
%% Vacuum envelope: ONE continuous cylinder spanning accel+drift, plus
% the ring-stack's own envelope (auto Form Union merges everything, same
% technique used throughout this project for the quadrupole rods).
% !!! CHANGED from a square Block to a circular Cylinder ("flight tube"
% is a hollow cylinder, per explicit request) -- radius=flight_tube_r,
% comfortably larger than both the electrodes inside it (ion's real
% drift path reaches ~80mm off-axis) and ring_outer_r (so the tube's own
% grounded wall has real clearance from anything at a different
% potential, e.g. the reflectron rings/backplate it borders). The
% accelerator's own SQUARE shield (accelshield, small radius
% accel_shield_half) sits NESTED inside this larger cylinder for the
% z<L_accel portion -- two different cross-section shapes sharing the
% same vacuum, connected via the shared grid2 boundary at z=L_accel.
% !!! Bore z-range (doc §7.46): the flight tube's own vacuum interior,
% shared exactly by accelflightbox (the vacuum) and flighttubewallH (the
% "hole" subtracted from the shield's outer solid, below). Defining both
% ends here ONCE avoids the two features drifting out of sync.
% z0_bore: endcap_gap(3mm) past the (extended) accelerator shield's own
% back edge (z=-1-accel_shield_back_extra). z1_bore: shield_axial_gap
% (50mm) past backplate's own far face.
% !!! Extended by accel_shield_wall (doc §7.47): the accelerator shield
% now has an INTEGRATED back cap (built into the same accelshieldO/H
% Difference, see above) whose own back face is at -1-
% accel_shield_back_extra-accel_shield_wall -- z0_bore (where the flight
% tube's own vacuum bore begins) must stay behind THAT, or flighttubewallO
% (a full disk before flighttubewallH's hole starts) would overlap the
% accelerator shield's new back cap at the same z.
z0_bore = 'z_accel_origin-accel_repeller_thickness-accel_shield_back_extra-accel_shield_wall-endcap_gap';
% !!! backplate is a real solid disk again (front face at L_flight+
% L_refl, extending ring_thickness further out in +z, see the backplate
% feature below) -- z1_bore must stay shield_axial_gap clear of its own
% FAR face, i.e. past L_flight+L_refl+ring_thickness, not just
% L_flight+L_refl itself.
z1_bore = 'L_flight+L_refl+ring_thickness+shield_axial_gap';
geom1.feature.create('accelflightbox', 'Cylinder');
geom1.feature('accelflightbox').label('Flight tube (accelerator drift-out + field-free flight tube + reflectron, hollow cylinder)');
geom1.feature('accelflightbox').set('r', 'flight_tube_r');
geom1.feature('accelflightbox').set('h', [z1_bore '-(' z0_bore ')']);
geom1.feature('accelflightbox').set('pos', {'0', '0', z0_bore});

% !!! Flight-tube shield (doc §7.46, simplified per explicit request):
% ONE Difference -- a single outer Cylinder (radius flight_tube_r+
% flight_tube_wall, spanning the bore's z-range EXTENDED by
% flight_tube_wall at EACH end) minus a single inner Cylinder (radius
% flight_tube_r, EXACTLY matching the bore z-range z0_bore..z1_bore,
% same as accelflightbox above) -- this gives walls AND both end caps
% in one Boolean operation, with wall/cap thickness uniformly
% flight_tube_wall everywhere and NO possibility of internal overlap
% (previously a separate endcap+flighttubewall+endcap2 three-feature
% design had a real overlap: endcap's z-range fell inside
% flighttubewall's own z-range at the same radius band). The inner
% Cylinder's z-range matches accelflightbox's bore EXACTLY, so the
% vacuum and the shield's own hole share one common boundary with no gap
% and no overlap.
geom1.feature.create('flighttubewallO', 'Cylinder');
geom1.feature('flighttubewallO').label('Flight tube shield outer solid (spans bore + both end-cap thicknesses)');
geom1.feature('flighttubewallO').set('r', 'flight_tube_r+flight_tube_wall');
geom1.feature('flighttubewallO').set('h', [z1_bore '-(' z0_bore ')+2*flight_tube_wall']);
geom1.feature('flighttubewallO').set('pos', {'0', '0', [z0_bore '-flight_tube_wall']});
geom1.feature.create('flighttubewallH', 'Cylinder');
geom1.feature('flighttubewallH').label('Flight tube shield bore (matches accelflightbox exactly)');
geom1.feature('flighttubewallH').set('r', 'flight_tube_r');
geom1.feature('flighttubewallH').set('h', [z1_bore '-(' z0_bore ')']);
geom1.feature('flighttubewallH').set('pos', {'0', '0', z0_bore});
geom1.feature.create('flighttubewall', 'Difference');
geom1.feature('flighttubewall').label('Flight tube shield (grounded, one-piece shell with both ends closed -- encloses field-free tube + reflectron)');
geom1.feature('flighttubewall').selection('input').set({'flighttubewallO'});
geom1.feature('flighttubewall').selection('input2').set({'flighttubewallH'});

% !!! REMOVED 'reflvac' (doc §7.47, per explicit request to check for
% redundant entities): it spanned z=[L_flight+1, L_flight+L_refl-1] at
% radius=ring_outer_r(350mm) -- entirely a SUBSET of accelflightbox's
% own region, which (since §7.44/§7.46) already spans z0_bore..z1_bore
% (comfortably containing reflvac's whole z-range with margin on both
% sides) at a LARGER radius (flight_tube_r=350mm by default). Both features
% supplied the exact same material (vacuum) over the exact same 3D
% region -- reflvac was pure redundancy left over from when the
% reflectron had its own separate, smaller vacuum envelope (before
% accelflightbox was extended to cover it too).

geom1.feature.create('relvol', 'Block');
geom1.feature('relvol').label('Release volume (ion entering pusher at 5eV, 1mm cube)');
geom1.feature('relvol').set('size', {sprintf('%.12g', sourceDesign.size_x_mm), ...
    sprintf('%.12g', sourceDesign.size_y_mm), sprintf('%.12g', sourceDesign.size_z_mm)});
geom1.feature('relvol').set('pos', { ...
    sprintf('%.17g[mm]-%.17g[mm]', sourceDesign.center_x_mm, sourceDesign.size_x_mm/2), ...
    sprintf('%.17g[mm]-%.17g[mm]', sourceDesign.center_y_mm, sourceDesign.size_y_mm/2), ...
    sprintf('%.17g[mm]-%.17g[mm]', sourceDesign.center_z_mm, sourceDesign.size_z_mm/2)});
geom1.feature('relvol').set('selresult', 'on');

for t = [{'repeller','detector','accelshield','flighttubewall','backplate'}, ringtags, accelringtags]
    geom1.feature(t{1}).set('selresult','on');
end

end
