function selections = configure_comsol_segment_hybrid_mesh(comp, mesh, geometryTag, numerics, ...
    sweepGeometryTags, rodBoundarySelectionTags, sweepRodBoundarySelectionTags)
%CONFIGURE_COMSOL_SEGMENT_HYBRID_MESH Mesh invariant rod interiors with prisms.
%
% Geometry partitions must already exist and the geometry must have been
% built.  Each sweep partition lies strictly inside one physical rod
% segment, leaving rod ends, intersegment gaps, aperture plates and
% external regions to the tetrahedral transition mesh.

strategy = numerics.mesh.hybrid;
assert(~isempty(sweepGeometryTags), ...
    'common:multipole:HybridMeshPartitions', ...
    'Segment-hybrid meshing requires at least one swept partition.');
assert(~isempty(rodBoundarySelectionTags), ...
    'common:multipole:HybridMeshRodBoundaries', ...
    'Segment-hybrid meshing requires explicit rod-boundary selections.');
assert(numel(sweepRodBoundarySelectionTags) == numel(sweepGeometryTags), ...
    'common:multipole:HybridMeshSweepRodBoundaries', ...
    'Each swept partition requires its own rod-boundary selection.');
positive = [strategy.core_radius_mm, strategy.radial_core_and_rod_hmax_mm, ...
    strategy.outer_vacuum_hmax_mm, strategy.transition_and_end_tetra_hmax_mm, ...
    strategy.minimum_element_size_mm];
assert(all(isfinite(positive) & positive > 0), ...
    'common:multipole:HybridMeshSize', ...
    'Segment-hybrid mesh dimensions must be positive and finite.');
assert(strategy.axial_layers_per_swept_segment >= 1 && ...
    strategy.axial_layers_per_swept_segment == round(strategy.axial_layers_per_swept_segment), ...
    'common:multipole:HybridMeshLayers', ...
    'Segment-hybrid axial layers must be a positive integer.');

coreGeometrySelection = [geometryTag '_meshCore_dom'];
sweepSelections = cell(1, numel(sweepGeometryTags));
sweepCoreSelections = cell(1, numel(sweepGeometryTags));
for index = 1:numel(sweepGeometryTags)
    sweepSelections{index} = sprintf('sel_mesh_sweep_%d_vac', index);
    create_intersection(comp, sweepSelections{index}, ...
        {'sel_vac', [geometryTag '_' sweepGeometryTags{index} '_dom']});
    sweepCoreSelections{index} = sprintf('sel_mesh_sweep_%d_core_vac', index);
    create_intersection(comp, sweepCoreSelections{index}, ...
        {sweepSelections{index}, coreGeometrySelection});
end

comp.selection.create('sel_mesh_swept_vac', 'Union');
comp.selection('sel_mesh_swept_vac').set('entitydim', 3);
comp.selection('sel_mesh_swept_vac').set('input', sweepSelections);
comp.selection.create('sel_mesh_tet_vac', 'Difference');
comp.selection('sel_mesh_tet_vac').set('entitydim', 3);
comp.selection('sel_mesh_tet_vac').set('add', {'sel_vac'});
comp.selection('sel_mesh_tet_vac').set('subtract', {'sel_mesh_swept_vac'});
create_intersection(comp, 'sel_mesh_tet_core_vac', ...
    {'sel_mesh_tet_vac', coreGeometrySelection});
comp.selection.create('sel_mesh_rod_bnd', 'Union');
comp.selection('sel_mesh_rod_bnd').set('entitydim', 2);
comp.selection('sel_mesh_rod_bnd').set('input', rodBoundarySelectionTags);

mesh.feature('size').set('hauto', numerics.mesh.global_auto_level);
for index = 1:numel(sweepSelections)
    sweep = mesh.feature.create(sprintf('swe%d', index), 'Sweep');
    sweep.selection.geom(geometryTag, 3);
    sweep.selection.named(sweepSelections{index});
    sweep.set('facemethod', 'tri');
    add_size(sweep, sprintf('szOut%d', index), geometryTag, ...
        sweepSelections{index}, strategy.outer_vacuum_hmax_mm, ...
        strategy.minimum_element_size_mm);
    add_size(sweep, sprintf('szCore%d', index), geometryTag, ...
        sweepCoreSelections{index}, strategy.radial_core_and_rod_hmax_mm, ...
        strategy.minimum_element_size_mm);
    add_size(sweep, sprintf('szRod%d', index), geometryTag, ...
        sweepRodBoundarySelectionTags{index}, strategy.radial_core_and_rod_hmax_mm, ...
        strategy.minimum_element_size_mm, 2);
    distribution = sweep.feature.create(sprintf('dist%d', index), 'Distribution');
    distribution.selection.geom(geometryTag, 3);
    distribution.selection.named(sweepSelections{index});
    distribution.set('type', 'number');
    distribution.set('numelem', round(strategy.axial_layers_per_swept_segment));
    distribution.set('equidistant', 'on');
end

tetrahedra = mesh.feature.create('ftet1', 'FreeTet');
tetrahedra.selection.geom(geometryTag, 3);
tetrahedra.selection.named('sel_mesh_tet_vac');
add_size(tetrahedra, 'szTetOut', geometryTag, 'sel_mesh_tet_vac', ...
    strategy.outer_vacuum_hmax_mm, strategy.minimum_element_size_mm);
add_size(tetrahedra, 'szTetCore', geometryTag, 'sel_mesh_tet_core_vac', ...
    strategy.transition_and_end_tetra_hmax_mm, strategy.minimum_element_size_mm);
add_size(tetrahedra, 'szTetRod', geometryTag, 'sel_mesh_rod_bnd', ...
    strategy.radial_core_and_rod_hmax_mm, strategy.minimum_element_size_mm, 2);

selections = struct( ...
    'sweep', {sweepSelections}, ...
    'sweep_core', {sweepCoreSelections}, ...
    'tetrahedral', 'sel_mesh_tet_vac', ...
    'tetrahedral_core', 'sel_mesh_tet_core_vac', ...
    'rod_boundary', 'sel_mesh_rod_bnd', ...
    'sweep_rod_boundary', {sweepRodBoundarySelectionTags});
end

function create_intersection(comp, tag, inputs)
comp.selection.create(tag, 'Intersection');
comp.selection(tag).set('entitydim', 3);
comp.selection(tag).set('input', inputs);
end

function add_size(parent, tag, geometryTag, selectionTag, hmax, hmin, entityDimension)
if nargin < 7
    entityDimension = 3;
end
feature = parent.feature.create(tag, 'Size');
feature.selection.geom(geometryTag, entityDimension);
feature.selection.named(selectionTag);
feature.set('custom', 'on');
feature.set('hmaxactive', true);
feature.set('hmax', sprintf('%.17g[mm]', hmax));
feature.set('hminactive', true);
feature.set('hmin', sprintf('%.17g[mm]', hmin));
end
