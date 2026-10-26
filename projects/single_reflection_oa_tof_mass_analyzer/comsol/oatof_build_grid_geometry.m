function oatof_build_grid_geometry(geom1,z_mid_expr,geometry)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
% Embed the provider's zero-thickness accelerator sheets and the two
% reflectron sheets in the same vacuum Union, retaining interior boundaries.
projectsRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
previousPath = path;
restorePath = onCleanup(@() path(previousPath)); %#ok<NASGU>
addpath(fullfile(projectsRoot,'orthogonal_accelerator','comsol'));
if nargin < 3, geometry=struct(); end
sheets=struct('tag',{'wp_grid1','wp_grid2'},'z',{'z_accel_grid1','z_accel_grid2'}, ...
    'width',{'2*(accel_shield_half-accel_ring_gap)','2*accel_shield_half'}, ...
    'x',{'x_accel_center','x_accel_center'},'y',{'0','0'});
if ~isempty(fieldnames(geometry))
    assert(strcmp(geometry.cross_section,'square'),'oatof:AcceleratorCrossSection', ...
        'COMSOL accelerator sheets require the explicit square section.');
    roles={'grid1','grid2'};
    if isfield(geometry,'intermediate2_z_mm'), roles={'grid1','intermediate2','grid2'}; end
    sheets=repmat(sheets(1),1,numel(roles));
    for k=1:numel(roles)
        role=roles{k}; width=geometry.electrode_width_mm;
        if strcmp(role,'grid2'), width=geometry.shield_inner_width_mm; end
        sheets(k)=struct('tag',['wp_' role],'z',sprintf('%.17g[mm]',geometry.([role '_z_mm'])), ...
            'width',sprintf('%.17g[mm]',width),'x',sprintf('%.17g[mm]',geometry.axis_x_mm), ...
            'y',sprintf('%.17g[mm]',geometry.axis_y_mm));
    end
end
acceleratorGridTags=build_accelerator_grids(geom1,sheets);

gridspecs = {
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
geom1.feature('uni_grids').label('Embed the declared accelerator and reflectron ideal sheets in vacuum');
geom1.feature('uni_grids').selection('input').set({'accelflightbox', ...
    acceleratorGridTags{:},'wp_entgrid','wp_midgrid'});
geom1.feature('uni_grids').set('intbnd', true);

end
