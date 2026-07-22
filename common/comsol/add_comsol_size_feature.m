function feature = add_comsol_size_feature(mesh, tag, label, geometryTag, entityDimension, selectionName, hmax)
%ADD_COMSOL_SIZE_FEATURE Add one ordered, GUI-visible local Size feature.
assert(~isempty(tag) && ~isempty(selectionName),'common:comsol:MeshSelection', ...
    'Mesh Size tag and named selection are required.');
feature=mesh.feature.create(tag,'Size');
if ~isempty(label), feature.label(label); end
feature.selection.geom(geometryTag,entityDimension);
feature.selection.named(selectionName);
feature.set('custom','on');feature.set('hmaxactive',true);
if isnumeric(hmax), hmax=sprintf('%.17g[mm]',hmax); end
feature.set('hmax',hmax);
end
