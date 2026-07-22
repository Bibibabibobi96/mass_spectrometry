function configure_comsol_mesh(mesh, geometryTag, globalAutoLevel, regionSelection, regionHmaxMm)
%CONFIGURE_COMSOL_MESH Apply a global mesh plus optional selected-region refinement.
assert(globalAutoLevel>=1 && globalAutoLevel<=9 && globalAutoLevel==round(globalAutoLevel), ...
    'common:comsol:MeshAutoLevel','Automatic mesh level must be an integer from 1 through 9.');
mesh.feature('size').set('hauto',globalAutoLevel);
if nargin>=4 && ~isempty(regionSelection)
    assert(nargin>=5 && isfinite(regionHmaxMm) && regionHmaxMm>0, ...
        'common:comsol:MeshRegion','A selected mesh region requires a positive finite hmax.');
    add_comsol_size_feature(mesh,'szCommonWork','Common selected-region refinement', ...
        geometryTag,3,regionSelection,regionHmaxMm);
elseif nargin>=5 && isfinite(regionHmaxMm) && regionHmaxMm>0
    mesh.feature('size').set('custom','on');
    mesh.feature('size').set('hmax',sprintf('%.17g[mm]',regionHmaxMm));
end
mesh.feature.create('ftet1','FreeTet');
end
