function create_comsol_cylindrical_shell(geom, tag, innerRadiusMm, outerRadiusMm, heightMm, zMinMm)
%CREATE_COMSOL_CYLINDRICAL_SHELL Create a coaxial cylindrical shell.
assert(outerRadiusMm>innerRadiusMm && innerRadiusMm>0, ...
    'common:comsol:ShellDimensions','Shell outer radius must exceed its positive inner radius.');
outer=[tag 'Outer'];hole=[tag 'Hole'];
create_comsol_cylinder(geom,outer,outerRadiusMm,heightMm,zMinMm,false);
create_comsol_cylinder(geom,hole,innerRadiusMm,heightMm,zMinMm,false);
geom.feature.create(tag,'Difference');
geom.feature(tag).selection('input').set({outer});
geom.feature(tag).selection('input2').set({hole});
geom.feature(tag).set('selresult','on');
end
