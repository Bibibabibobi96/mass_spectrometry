function create_comsol_cylinder(geom, tag, radiusMm, heightMm, zMinMm, selectionEnabled)
%CREATE_COMSOL_CYLINDER Create one axial cylindrical geometry primitive.
if nargin < 6, selectionEnabled = true; end
assert(radiusMm>0 && heightMm>0,'common:comsol:CylinderDimensions', ...
    'Cylinder dimensions must be positive.');
geom.feature.create(tag,'Cylinder');
geom.feature(tag).set('r',sprintf('%.17g[mm]',radiusMm));
geom.feature(tag).set('h',sprintf('%.17g[mm]',heightMm));
geom.feature(tag).set('pos',{'0','0',sprintf('%.17g[mm]',zMinMm)});
if selectionEnabled, geom.feature(tag).set('selresult','on'); end
end
