function [feature, readbacks] = add_comsol_size_feature(mesh, tag, label, geometryTag, entityDimension, selectionName, hmax, hmin)
%ADD_COMSOL_SIZE_FEATURE Add ordered local Size; absent optional hmin preserves defaults.
readbacks = struct();
if nargin < 8, hmin = []; end
if ~isempty(hmin)
    assert(isnumeric(hmin) && isreal(hmin) && isscalar(hmin) && ...
        isfinite(hmin) && hmin > 0, 'common:comsol:MeshMinimum', ...
        'Explicit mesh hmin must be a positive finite numeric scalar.');
    assert(~isnumeric(hmax) || (isscalar(hmax) && hmin <= hmax), ...
        'common:comsol:MeshMinimum', 'Explicit mesh hmin must not exceed hmax.');
end
assert(~isempty(tag) && ~isempty(selectionName),'common:comsol:MeshSelection', ...
    'Mesh Size tag and named selection are required.');
feature=mesh.feature.create(tag,'Size');
if ~isempty(label), feature.label(label); end
feature.selection.geom(geometryTag,entityDimension);
feature.selection.named(selectionName);
feature.set('custom','on');feature.set('hmaxactive',true);
if isnumeric(hmax), hmax=sprintf('%.17g[mm]',hmax); end
feature.set('hmax',hmax);
if ~isempty(hmin)
    before = read_comsol_mesh_size_controls(feature);
    feature.set('hminactive',true);
    feature.set('hmin',sprintf('%.17g[mm]',hmin));
    after = read_comsol_mesh_size_controls(feature);
    readbacks = struct('before',before,'after',after);
    assert(isequal(rmfield(before,'hmin'),rmfield(after,'hmin')), ...
        'common:comsol:MeshSizeDrift', ...
        'Setting explicit hmin changed other local Size controls: before=%s after=%s', ...
        jsonencode(before),jsonencode(after));
end
end
