function selection = oatof_parse_field_idealization(fieldMode)
%OATOF_PARSE_FIELD_IDEALIZATION Parse composable region/component masks.
% New syntax: ideal:<region>.<component>[+<region>.<component>...]
% Regions: accel, drift, stage1, stage2, reflectron, all.
% Components: ex, ey, ez, all. Legacy ideal_* names remain supported.

mode = lower(strtrim(string(fieldMode)));
regions = ["accel", "drift", "stage1", "stage2"];
components = ["ex", "ey", "ez"];
mask = false(numel(regions), numel(components));

legacy = struct( ...
    real=[], ...
    ideal=[1 2 3 4], ...
    ideal_accel=1, ...
    ideal_drift=2, ...
    ideal_stage1=3, ...
    ideal_stage2=4, ...
    ideal_reflectron=[3 4]);
legacyName = matlab.lang.makeValidName(char(mode));
if isfield(legacy, legacyName) && any(mode == ["real", "ideal", "ideal_accel", ...
        "ideal_drift", "ideal_stage1", "ideal_stage2", "ideal_reflectron"])
    selectedRegions = legacy.(legacyName);
    mask(selectedRegions, :) = true;
elseif startsWith(mode, "ideal:")
    specification = extractAfter(mode, "ideal:");
    assert(strlength(specification) > 0, ...
        'oaTOF:InvalidFieldIdealization', ...
        'FieldMode idealization selector cannot be empty.');
    atoms = split(specification, "+");
    for atomIndex = 1:numel(atoms)
        parts = split(strtrim(atoms(atomIndex)), ".");
        assert(numel(parts) == 2 && all(strlength(parts) > 0), ...
            'oaTOF:InvalidFieldIdealization', ...
            'Invalid field idealization atom "%s"; expected region.component.', atoms(atomIndex));
        selectedRegions = resolve_regions(parts(1));
        selectedComponents = resolve_components(parts(2));
        mask(selectedRegions, selectedComponents) = true;
    end
else
    error('oaTOF:InvalidFieldIdealization', ...
        ['Unsupported FieldMode "%s". Use real, a legacy ideal_* mode, or ' ...
         'ideal:<region>.<component>[+...].'], fieldMode);
end

canonicalAtoms = strings(0, 1);
for regionIndex = 1:numel(regions)
    selected = components(mask(regionIndex, :));
    if numel(selected) == numel(components)
        canonicalAtoms(end+1) = regions(regionIndex) + ".all"; %#ok<AGROW>
    else
        for componentIndex = 1:numel(selected)
            canonicalAtoms(end+1) = regions(regionIndex) + "." + selected(componentIndex); %#ok<AGROW>
        end
    end
end
if isempty(canonicalAtoms)
    canonical = "real";
else
    canonical = "ideal:" + join(canonicalAtoms, "+");
end

selection = struct('regions', regions, 'components', components, ...
    'mask', mask, 'canonical', canonical, 'requested', mode);
end

function indices = resolve_regions(name)
switch char(name)
    case {'accel', 'accelerator'}
        indices = 1;
    case 'drift'
        indices = 2;
    case 'stage1'
        indices = 3;
    case 'stage2'
        indices = 4;
    case 'reflectron'
        indices = [3 4];
    case 'all'
        indices = 1:4;
    otherwise
        error('oaTOF:InvalidFieldIdealization', 'Unknown idealization region "%s".', name);
end
end

function indices = resolve_components(name)
switch char(name)
    case 'ex'
        indices = 1;
    case 'ey'
        indices = 2;
    case 'ez'
        indices = 3;
    case 'all'
        indices = 1:3;
    otherwise
        error('oaTOF:InvalidFieldIdealization', 'Unknown idealization component "%s".', name);
end
end
