function [ringtags,z_mid_expr] = oatof_build_reflectron_geometry(geom1,n_rings1,n_rings2)
z_mid_expr = 'L_flight+L_stage1';
ringtags = {};
for k = 1:n_rings1
    tagk = sprintf('ring1_%d', k);
    % Equal center pitch from entgrid to midgrid.  With equal thickness,
    % this also makes all axial solid-to-solid gaps equal.
    zk_expr = sprintf('L_flight+%d*L_stage1/(N_rings1+1)', k);
    Vk_expr = sprintf('%d*V_mid/(N_rings1+1)', k);
    % !!! FIXED center-alignment bug: COMSOL's Cylinder 'pos' is the
    % BASE (bottom face) center, not the ring's own center -- with
    % pos.z=zk_expr and h=1mm, the ring actually spanned [zk,zk+1mm],
    % true center at zk+0.5mm, while Vk_expr's theoretical linear
    % voltage was computed AT zk. This systematic offset (half the ring
    % thickness -- was 0.5mm out of a ~33-50mm ring pitch, ~1-1.5%, now
    % 2.5mm since ring_thickness=5mm) matters given the Mamyrin theory's
    % second-order sensitivity to field precision. Shifted pos.z by
    % -ring_thickness/2 so the ring's true center lands exactly at zk
    % (matching the accelerator's own rings, which already did this
    % correctly via Block's pos being a corner, not base-center).
    geom1.feature.create([tagk 'O'], 'Cylinder');
    geom1.feature([tagk 'O']).label(sprintf('Stage1 ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('r', 'ring_outer_r');
    geom1.feature([tagk 'O']).set('h', 'ring_thickness');
    geom1.feature([tagk 'O']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create([tagk 'H'], 'Cylinder');
    geom1.feature([tagk 'H']).label(sprintf('Stage1 ring %d bore', k));
    geom1.feature([tagk 'H']).set('r', 'bore_r');
    geom1.feature([tagk 'H']).set('h', 'ring_thickness');
    geom1.feature([tagk 'H']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Stage1 ring %d (annulus electrode, V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    ringtags{end+1} = tagk; %#ok<AGROW>
end
for k = 1:n_rings2 % N_rings2
    tagk = sprintf('ring2_%d', k);
    % Equal center pitch from midgrid to the solid backplate.  In
    % particular, the last-ring/backplate gap equals the ring-to-ring gap;
    % d2 and the backplate-to-shield clearance remain unchanged.
    zk_expr = sprintf('L_flight+L_stage1+%d*(L_refl-L_stage1)/(N_rings2+1)', k);
    Vk_expr = sprintf('V_mid+%d*(V_mirror-V_mid)/(N_rings2+1)', k);
    % !!! Same center-alignment fix as stage1 rings above.
    geom1.feature.create([tagk 'O'], 'Cylinder');
    geom1.feature([tagk 'O']).label(sprintf('Stage2 ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('r', 'ring_outer_r');
    geom1.feature([tagk 'O']).set('h', 'ring_thickness');
    geom1.feature([tagk 'O']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create([tagk 'H'], 'Cylinder');
    geom1.feature([tagk 'H']).label(sprintf('Stage2 ring %d bore', k));
    geom1.feature([tagk 'H']).set('r', 'bore_r');
    geom1.feature([tagk 'H']).set('h', 'ring_thickness');
    geom1.feature([tagk 'H']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Stage2 ring %d (annulus electrode, V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    ringtags{end+1} = tagk; %#ok<AGROW>
end

% !!! backplate REVERTED back to a real solid disk (per explicit
% request): the idealized-zero-thickness-boundary version (doc §6.11)
% fixed the ideal_stage2 gap, but that fix was solving a real-field-
% accuracy problem, not a particle-transparency one -- the "must be an
% idealized boundary" rationale used for entgrid/grid2/midgrid/grid1
% applies ONLY because ions actually pass THROUGH those grids' full
% cross-section. No ion ever physically reaches backplate (it turns
% around ~35-50mm short of it, well inside d2's margin), so it never
% needed particle transparency in the first place -- a real solid full
% disk (same technique as detector/repeller: implicit CPT stop via
% exclusion from sel_vac, no dedicated Wall/Freeze feature) is simpler
% and behaves like every other solid electrode in this design.
% !!! Sized/gapped per explicit request to match the OTHER electrodes it
% sits behind, not re-derive a new gap: radius=ring_outer_r, giving it
% the SAME 50mm gap to flight_tube_r that every ring in stage1/stage2
% already uses (no special-cased smaller gap the way the idealized
% version needed). Positioned so its ion-facing front face (smaller z,
% Cylinder's 'pos' is the base/bottom-face anchor) sits exactly at the
% theoretical z=L_flight+L_refl -- the same location the zero-thickness
% plane used to occupy, i.e. where the field theoretically reaches
% V_mirror -- and extends ring_thickness further out in +z, away from
% the ion path (harmless: nothing back there but the shield's own end
% cap, which z1_bore above keeps shield_axial_gap clear of backplate's
% new, thicker far face).
geom1.feature.create('backplate', 'Cylinder');
geom1.feature('backplate').label('Reflectron backplate (V_mirror, solid disk, ion never reaches it)');
geom1.feature('backplate').set('r', 'ring_outer_r');
geom1.feature('backplate').set('h', 'ring_thickness');
geom1.feature('backplate').set('pos', {'x_refl_center', '0', 'L_flight+L_refl'});

end
