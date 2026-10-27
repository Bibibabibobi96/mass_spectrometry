function tags = build_multipole_enclosure(geom, bodies, prefix)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
% Project frozen same-ground enclosure annuli; bare rods supply no bodies.
% Dimensions and cap placement belong to the provider's enclosure_layout.
tags = cell(1, numel(bodies));
for index = 1:numel(bodies)
    body = bodies(index);
    tag = [prefix '_' char(body.role)];
    create_comsol_cylindrical_shell(geom, tag, body.inner_radius_mm, ...
        body.outer_radius_mm, body.z_max_mm-body.z_min_mm, body.z_min_mm);
    tags{index} = tag;
end
end
