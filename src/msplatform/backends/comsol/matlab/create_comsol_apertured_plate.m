function create_comsol_apertured_plate(geom, tag, outerRadiusMm, apertureRadiusMm, thicknessMm, zMinMm)
%CREATE_COMSOL_APERTURED_PLATE Create a circular plate with an axial aperture.
assert(outerRadiusMm>apertureRadiusMm && apertureRadiusMm>0, ...
    'common:comsol:PlateDimensions','Plate outer radius must exceed its positive aperture radius.');
blank=[tag 'Blank'];hole=[tag 'Hole'];
create_comsol_cylinder(geom,blank,outerRadiusMm,thicknessMm,zMinMm,false);
create_comsol_cylinder(geom,hole,apertureRadiusMm,thicknessMm,zMinMm,false);
geom.feature.create(tag,'Difference');
geom.feature(tag).selection('input').set({blank});
geom.feature(tag).selection('input2').set({hole});
geom.feature(tag).set('selresult','on');
end
