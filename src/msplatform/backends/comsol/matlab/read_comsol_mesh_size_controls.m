function controls = read_comsol_mesh_size_controls(feature)
%READ_COMSOL_MESH_SIZE_CONTROLS Read official typed Size properties without unit conversion.
names = {'hauto','custom','hmin','hmax','hcurve','hgrad','hnarrow'};
controls = struct();
for index = 1:numel(names)
    name = names{index};
    kind = char(feature.getValueType(name));
    switch kind
        case 'String'
            value = char(feature.getString(name));
        case 'Double'
            value = double(feature.getDouble(name));
        case 'Int'
            value = double(feature.getInt(name));
        otherwise
            error('common:comsol:MeshSizeReadback', ...
                'Unsupported Size property type %s for %s.', kind, name);
    end
    controls.(name) = struct('type',kind,'value',value);
end
end
