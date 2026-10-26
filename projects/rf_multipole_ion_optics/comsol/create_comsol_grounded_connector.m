function created = create_comsol_grounded_connector(geom,tag,shape,outerSizeMm,apertureRadiusMm,lengthMm,zMinMm)
%CREATE_COMSOL_GROUNDED_CONNECTOR Build a shared straight grounded connector.
% outerSizeMm is the half-width for rectangular_bore and outer radius for
% cylindrical_bore.  A zero length intentionally creates no COMSOL feature.

assert(isfinite(lengthMm) && lengthMm>=0, 'Connector length must be finite and nonnegative.');
assert(isfinite(apertureRadiusMm) && isfinite(outerSizeMm) && ...
    apertureRadiusMm>0 && outerSizeMm>apertureRadiusMm, ...
    'Connector outer size must exceed its positive aperture radius.');
assert(any(strcmp(shape,{'rectangular_bore','cylindrical_bore'})), ...
    'Unsupported grounded connector shape: %s',shape);
if lengthMm==0
    created=false;
    return
end

outerTag=[tag '_outer']; holeTag=[tag '_hole'];
if strcmp(shape,'rectangular_bore')
    geom.feature.create(outerTag,'Block');
    geom.feature(outerTag).set('size',{sprintf('%.17g[mm]',2*outerSizeMm), ...
        sprintf('%.17g[mm]',2*outerSizeMm),sprintf('%.17g[mm]',lengthMm)});
    geom.feature(outerTag).set('pos',{sprintf('%.17g[mm]',-outerSizeMm), ...
        sprintf('%.17g[mm]',-outerSizeMm),sprintf('%.17g[mm]',zMinMm)});
else
    geom.feature.create(outerTag,'Cylinder');
    geom.feature(outerTag).set('r',sprintf('%.17g[mm]',outerSizeMm));
    geom.feature(outerTag).set('h',sprintf('%.17g[mm]',lengthMm));
    geom.feature(outerTag).set('pos',{'0','0',sprintf('%.17g[mm]',zMinMm)});
end
geom.feature.create(holeTag,'Cylinder');
geom.feature(holeTag).set('r',sprintf('%.17g[mm]',apertureRadiusMm));
geom.feature(holeTag).set('h',sprintf('%.17g[mm]',lengthMm));
geom.feature(holeTag).set('pos',{'0','0',sprintf('%.17g[mm]',zMinMm)});
geom.feature.create(tag,'Difference');
geom.feature(tag).selection('input').set({outerTag});
geom.feature(tag).selection('input2').set({holeTag});
geom.feature(tag).set('selresult','on');
created=true;
end
