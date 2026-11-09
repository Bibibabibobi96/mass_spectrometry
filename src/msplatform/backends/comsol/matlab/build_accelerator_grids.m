function gridTags = build_accelerator_grids(geom1, sheets)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
%BUILD_ACCELERATOR_GRIDS Embed explicit ideal zero-thickness sheets in 3D.
% COMSOL 6.4 WorkPlane quickplane/quickz and Rectangle are used directly;
% the instrument owns vacuum Union and the electrical boundary selections.
arguments
    geom1
    sheets (1,:) struct
end
gridTags = cell(1,numel(sheets));
for k=1:numel(sheets)
    sheet=sheets(k);
    assert(all(isfield(sheet,{'tag','z','width','x','y'})), ...
        'accelerator:GridContract','Every ideal sheet requires tag, plane, width and center.');
    width=char(sheet.width);
    wp=geom1.feature.create(char(sheet.tag),'WorkPlane');
    wp.set('quickplane','xy');
    wp.set('quickz',char(sheet.z));
    wp.geom.feature.create('r1','Rectangle');
    wp.geom.feature('r1').set('size',{width,width});
    wp.geom.feature('r1').set('pos',{[char(sheet.x) '-(' width ')/2'],[char(sheet.y) '-(' width ')/2']});
    gridTags{k}=char(sheet.tag);
end
end
