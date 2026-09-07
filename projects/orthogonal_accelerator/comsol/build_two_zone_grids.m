function gridTags = build_two_zone_grids(geom1, layout)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
%BUILD_TWO_ZONE_GRIDS Create two ideal zero-thickness accelerator sheet objects.
% All coordinates and widths are explicit model length expressions. The caller
% owns the vacuum domain, Boolean embedding, electrical boundary selections,
% and the distinction between an ideal sheet and a manufactured wire mesh.
arguments
    geom1
    layout (1,1) struct
end
required = {'grid1_z','grid2_z','grid1_width','grid2_width','x_center','y_center'};
for k = 1:numel(required)
    key = required{k};
    if ~isfield(layout,key) || ~(ischar(layout.(key)) || isstring(layout.(key))) || ...
            ~isscalar(string(layout.(key))) || strlength(string(layout.(key))) == 0
        error('accelerator:GridContract','layout.%s must be a nonempty expression.',key);
    end
end
gridTags = {'wp_grid1','wp_grid2'};
zExpressions = {layout.grid1_z,layout.grid2_z};
widthExpressions = {layout.grid1_width,layout.grid2_width};
for k = 1:numel(gridTags)
    width = char(widthExpressions{k});
    wp = geom1.feature.create(gridTags{k},'WorkPlane');
    wp.set('quickplane','xy');
    wp.set('quickz',char(zExpressions{k}));
    wp.geom.feature.create('r1','Rectangle');
    wp.geom.feature('r1').set('size',{width,width});
    wp.geom.feature('r1').set('pos',{ ...
        [char(layout.x_center) '-(' width ')/2'], ...
        [char(layout.y_center) '-(' width ')/2']});
end
end
