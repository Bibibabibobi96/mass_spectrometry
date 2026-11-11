function readbacks = configure_comsol_mesh(mesh, geometryTag, globalAutoLevel, regionSelection, regionHmaxMm, minimumElementSizeMm)
%CONFIGURE_COMSOL_MESH Apply global and optional region sizes; optional hmin is explicit.
readbacks = struct();
if nargin < 6, minimumElementSizeMm = []; end
if ~isempty(minimumElementSizeMm)
    assert(isnumeric(minimumElementSizeMm) && isreal(minimumElementSizeMm) && ...
        isscalar(minimumElementSizeMm) && isfinite(minimumElementSizeMm) && ...
        minimumElementSizeMm > 0, 'common:comsol:MeshMinimum', ...
        'Explicit mesh hmin must be a positive finite numeric scalar.');
    assert(nargin < 5 || ~isfinite(regionHmaxMm) || minimumElementSizeMm <= regionHmaxMm, ...
        'common:comsol:MeshMinimum', 'Explicit mesh hmin must not exceed hmax.');
end
assert(globalAutoLevel>=1 && globalAutoLevel<=9 && globalAutoLevel==round(globalAutoLevel), ...
    'common:comsol:MeshAutoLevel','Automatic mesh level must be an integer from 1 through 9.');
mesh.feature('size').set('hauto',globalAutoLevel);
if ~isempty(minimumElementSizeMm)
    before = read_comsol_mesh_size_controls(mesh.feature('size'));
    mesh.feature('size').set('custom','on');
    mesh.feature('size').set('hmin',sprintf('%.17g[mm]',minimumElementSizeMm));
    after = read_comsol_mesh_size_controls(mesh.feature('size'));
    readbacks.global = struct('before',before,'after',after);
    assert(isequal(rmfield(before,{'custom','hmin'}),rmfield(after,{'custom','hmin'})), ...
        'common:comsol:MeshSizeDrift', ...
        'Setting explicit hmin changed other global Size controls: before=%s after=%s', ...
        jsonencode(before),jsonencode(after));
end
if nargin>=4 && ~isempty(regionSelection)
    assert(nargin>=5 && isfinite(regionHmaxMm) && regionHmaxMm>0, ...
        'common:comsol:MeshRegion','A selected mesh region requires a positive finite hmax.');
    [~, localReadbacks] = add_comsol_size_feature(mesh,'szCommonWork','Common selected-region refinement', ...
        geometryTag,3,regionSelection,regionHmaxMm,minimumElementSizeMm);
    if ~isempty(minimumElementSizeMm), readbacks.local=localReadbacks; end
elseif nargin>=5 && isfinite(regionHmaxMm) && regionHmaxMm>0
    mesh.feature('size').set('custom','on');
    mesh.feature('size').set('hmax',sprintf('%.17g[mm]',regionHmaxMm));
end
mesh.feature.create('ftet1','FreeTet');
end
