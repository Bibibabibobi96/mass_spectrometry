function [mesh1,mi,t_mesh] = oatof_build_mesh(model,comp1,p,mesh_hmax_refl_mm,mesh_hmax_accel_mm,runtime)
t_mesh_start = tic;
mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=6, refined at release, accelerator + ring stack)');
mesh1.feature('size').set('hauto', 6);
add_comsol_size_feature(mesh1,'sz1','Fine mesh on release volume', ...
    'geom1',3,'geom1_relvol_dom','0.1[mm]');
% GUI-visible whole-accelerator selection for diagnostics and migration
% regression checks.  All bounds are expressions tied to the accelerator
% parameters: the old hardcoded x=[-50,50] box stopped following the
% assembly when x_accel_center moved to -48.8mm and silently selected only
% the release-volume domain.  The ordered 2026-07-16 convergence test
% showed that the earlier apparent 1mm no-op was caused by appending Size
% after ftet1.  A GUI-visible 1mm Size before ftet1 removes the transverse
% field/landing artifact at much lower cost than the 0.5mm reference.
comp1.selection.create('selbracket', 'Box');
comp1.selection('selbracket').label('Whole accelerator region (parameter-linked, diagnostics)');
comp1.selection('selbracket').set('xmin', 'x_accel_center-accel_shield_half');
comp1.selection('selbracket').set('xmax', 'x_accel_center+accel_shield_half');
comp1.selection('selbracket').set('ymin', '-accel_shield_half');
comp1.selection('selbracket').set('ymax', 'accel_shield_half');
comp1.selection('selbracket').set('zmin', 'z_accel_origin');
comp1.selection('selbracket').set('zmax', 'z_accel_grid2');
comp1.selection('selbracket').set('condition', 'inside');
bracketDomainIds = comp1.selection('selbracket').entities(3);
assert(numel(bracketDomainIds) >= 6, ...
    'Parameter-linked accelerator selection resolved to only %d domains.', ...
    numel(bracketDomainIds));
fprintf('Parameter-linked accelerator selection: %d domains.\n', ...
    numel(bracketDomainIds));
comp1.selection.create('selreflregion', 'Cylinder');
comp1.selection('selreflregion').label('Ring-stack region (geometric, for mesh refinement)');
% !!! Changed from a hardcoded 210 (already smaller than ring_outer_r=
% 350mm) to a parameter EXPRESSION tied to ring_outer_r, so the fine-
% mesh region always tracks the ring stack's actual size instead of
% needing manual re-tuning. A fixed attempt at 700 (to safely cover a
% 650mm ring_outer_r test) blew the mesh up to 3.66M elements (was
% ~170-260K) and timed out -- applying fine mesh over a fixed 700mm
% radius wastes enormous effort when ring_outer_r is much smaller.
comp1.selection('selreflregion').set('r', 'ring_outer_r+10[mm]');
comp1.selection('selreflregion').set('rin', 0);
% !!! Was hardcoded [41.2 0 500] (matching the OLD, now-removed
% x_refl_center=41.2mm reflectron-axis offset). Recomputed from the
% CURRENT parameter values (x_refl_center is now 0, unified axis, see
% doc §7.38) rather than left stale -- this selection type takes a
% plain numeric array, not string expressions, so the values are
% evaluated here in MATLAB instead of passed as parameter names.
comp1.selection('selreflregion').set('pos', [p.evaluate('x_refl_center','mm') 0 p.evaluate('L_flight','mm')]);
comp1.selection('selreflregion').set('axis', [0 0 1]);
% !!! FIXED: 'top' for a Cylinder selection is the ABSOLUTE z-coordinate
% of the far end (not a height delta) -- was hardcoded to 502, which
% with pos.z=500 only covered a 2mm sliver right at the reflectron
% entrance, leaving the remaining ~498mm of the ring stack on the
% coarser default mesh (hauto=6). This was found via a fine-resolution
% field-precision scan: on-axis Ez deviation from theory was NOT the
% ring-discretization ripple expected, but a smooth ~0.06%->0.58%
% monotonic trend across each stage, worst right at each stage's
% "settling" boundary (entgrid/backplate) and best near the shared,
% flat midgrid -- a pattern consistent with under-refined mesh over
% most of the ring stack, not an inherent field/geometry limitation.
% Fixed to properly span the whole reflectron (z=500 to z=1000+2mm
% margin) via a parameter expression, so it stays correct if L_flight/
% L_refl change later instead of needing manual re-tuning again.
% !!! Extended by +ring_thickness (per the backplate solid-disk revert
% above): backplate's own solid domain now extends ring_thickness past
% L_flight+L_refl, so the fine-mesh region must reach that far too, or
% part of backplate's volume would silently fall back on the coarser
% default mesh.
comp1.selection('selreflregion').set('top', 'L_flight+L_refl+ring_thickness+2');
comp1.selection('selreflregion').set('condition', 'inside');
add_comsol_size_feature(mesh1,'szrefl', ...
    'Finer mesh on ring-stack region (resolve the graded field)', ...
    'geom1',3,'selreflregion',sprintf('%g[mm]',mesh_hmax_refl_mm));
% Layered local refinement for field diagnostics: uniformly setting the
% full r=ring_outer_r cylinder to 5mm creates millions of elements and
% makes every particle scan prohibitively expensive. The useful field
% curves are controlled by the ring inner edge. A connected vacuum volume
% cannot be partially selected as a domain. Do NOT select the whole bore
% boundary either: it touches large connected vacuum faces and becomes as
% expensive as global refinement. Select only the narrow physical inner
% cylindrical walls of the annular rings; FreeTet then grades their
% adjacent vacuum cells locally.
local_rim_hmax_mm = max(runtime.local_reflectron_edge_hmax_floor_mm, ...
    mesh_hmax_refl_mm/runtime.local_reflectron_edge_hmax_divisor);
% The narrow-boundary experiment is an explicit resolved-runtime choice.
% Candidate and Formal models therefore record the same mesh behavior.
use_local_edge_refinement = logical( ...
    runtime.local_reflectron_edge_refinement_enabled);
if use_local_edge_refinement
    comp1.selection.create('selreflrimmesh', 'Cylinder');
    comp1.selection('selreflrimmesh').label('Reflectron ring-inner-edge boundaries (local mesh)');
    comp1.selection('selreflrimmesh').set('entitydim', '2');
    comp1.selection('selreflrimmesh').set('r', 'bore_r+1.5[mm]');
    comp1.selection('selreflrimmesh').set('rin', 'bore_r-1.5[mm]');
    comp1.selection('selreflrimmesh').set('pos', [p.evaluate('x_refl_center','mm') 0 p.evaluate('L_flight','mm')]);
    comp1.selection('selreflrimmesh').set('axis', [0 0 1]);
    comp1.selection('selreflrimmesh').set('top', 'L_flight+L_refl+ring_thickness+2');
    comp1.selection('selreflrimmesh').set('condition', 'intersects');
    add_comsol_size_feature(mesh1,'szreflrim', ...
        sprintf('Fine mesh at reflectron ring inner edge (%.3gmm)',local_rim_hmax_mm), ...
        'geom1',2,'selreflrimmesh',sprintf('%g[mm]',local_rim_hmax_mm));
end
% COMSOL resolves overlapping Size features in feature-tree order.  The
% accelerator selection overlaps the broad ring-stack/drift sizing region,
% so szaccel must be the last Size before FreeTet.  Creating it earlier made
% the GUI show 1 mm while the built mesh silently remained the old coarse
% 274576-element mesh.  Keep this order as a numerical-geometry gate.
add_comsol_size_feature(mesh1,'szaccel', ...
    sprintf('Accelerator convergence mesh (hmax %.3g mm)',mesh_hmax_accel_mm), ...
    'geom1',3,'selbracket','mesh_hmax_accel');
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
meshFeatureTags = string(cell(mesh1.feature.tags()));
assert(find(meshFeatureTags == "szaccel", 1) < ...
    find(meshFeatureTags == "ftet1", 1), ...
    'Accelerator Size must precede FreeTet in the persisted GUI tree.');
if abs(mesh_hmax_accel_mm-1) < 1e-12
    assert(mi.numelem(2) > 300000, ...
        ['Accelerator hmax=1 mm did not materially refine the built mesh ' ...
         '(only %d tetrahedra); check overlapping Size-feature order.'], ...
        mi.numelem(2));
end
fprintf('mesh: isempty=%d iscomplete=%d, Nelem=%d\n', mi.isempty, mi.iscomplete, mi.numelem(2));
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end
t_mesh = toc(t_mesh_start);
fprintf('[TIMING] mesh (mesh1.run + mphmeshstats): %.2fs\n', t_mesh);
end
