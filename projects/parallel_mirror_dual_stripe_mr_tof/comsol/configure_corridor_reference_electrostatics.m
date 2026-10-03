function out = configure_corridor_reference_electrostatics(model, comp, geom, geometryOut, analyzerElectrodeVoltagesV, boundaryGridDir)
% Fixed-workpoint reference: vacuum ES and original PA boundary data.
% Two-sided x domains use even extension of the positive-half five faces.
% Consumes finalized geometry and physical-ID-indexed voltages; no mesh,
% study, solver or save. This adapter does not confer numerical qualification.
% COMSOL 6.4 API checked 2026-10-04; native Interpolation grid + Box selections:
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.34.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.56.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_fileformats.53.05.html
validateattributes(analyzerElectrodeVoltagesV, {'numeric'}, {'real','finite','vector'});
electrodes = geometryOut.electrodes;
assert(numel(analyzerElectrodeVoltagesV) >= max([electrodes.id]), ...
    'MRTOF:MissingElectrodeVoltage', 'Voltage vector must use physical electrode IDs.');
box = geometryOut.corridor_box_mm;
halfDomain = box(1) == 0;
assert(halfDomain || box(1) == -box(4), ...
    'MRTOF:SymmetryPlane', 'Reference requires half or symmetric full x domain.');
geomTag = char(geom.tag());
% Domain-union exterior excludes internal vacuum partitions but retains
% electrode cavity contacts. COMSOL 6.4 llmatlab_ug_model.6.37.html.
external = comp.selection.create('mrc_vacuum_exterior', 'Adjacent');
external.set('entitydim', 3);
external.set('outputdim', 2);
external.set('input', {geometryOut.vacuum_domain_selection});
external.set('exterior', 'on');
external.set('interior', 'off');
vacuum = mphgetselection(external);
vacuumIds = reshape(vacuum.entities, 1, []);
material = comp.material.create('mrc_vacuum', 'Common');
material.selection.named(geometryOut.vacuum_domain_selection);
material.propertyGroup('def').set('relpermittivity', {'1'});
es = comp.physics.create('es', 'Electrostatics', geomTag);
es.selection.named(geometryOut.vacuum_domain_selection);
electrodeBoundaries = [];
electrodeInfo = struct('id', {}, 'selection_tag', {}, 'boundary_ids', {}, 'voltage_v', {});
for k = 1:numel(electrodes)
    entry = electrodes(k);
    source = mphgetselection(comp.selection(entry.boundary_selection));
    ids = intersect(vacuumIds, reshape(source.entities, 1, []));
    assert(~isempty(ids), 'MRTOF:EmptyElectrodeContact', ...
        'Electrode %d has no vacuum-contact boundary.', entry.id);
    selectionTag = sprintf('mrc_e%d_contact', entry.id);
    make_explicit(selectionTag, ids);
    potential = es.create(sprintf('mrc_e%d_potential', entry.id), 'ElectricPotential', 2);
    potential.selection.named(selectionTag);
    voltage = analyzerElectrodeVoltagesV(entry.id);
    potential.set('V0', sprintf('%.17g[V]', voltage));
    electrodeBoundaries = union(electrodeBoundaries, ids);
    electrodeInfo(k) = struct('id', entry.id, 'selection_tag', selectionTag, ...
        'boundary_ids', ids, 'voltage_v', voltage);
end
exteriorIds = setdiff(vacuumIds, electrodeBoundaries);
% Plane identification only: 64 machine spacings at the coordinate scale.
% This tolerance does not move geometry or change physical aperture sizes.
planeToleranceMm = 64 * eps(max(1, max(abs(box))));
names = {'xmax','ymin','ymax','zmin','zmax','xmin'};
axes = [1,2,2,3,3,1];
boxIndices = [4,2,5,3,6,1];
faceArguments = {'y,z','x,z','x,z','x,y','x,y',''};
if ~halfDomain
    faceArguments = {'y,z','abs(x),z','abs(x),z','abs(x),y','abs(x),y','y,z'};
end
argumentAxes = [2,3;1,3;1,3;1,2;1,2;2,3];
% Grid files retain positive-half x coordinates even for the full domain.
gridLow = [0, box(2:3)];
gridHigh = box(4:6);
faces = struct('name', {}, 'selection_tag', {}, 'boundary_ids', {}, ...
    'function_tag', {}, 'function_name', {}, 'file', {});
covered = [];
for k = 1:numel(names)
    name = names{k};
    selectionTag = ['mrc_outer_', name];
    plane = box(boxIndices(k));
    low = box(1:3) - planeToleranceMm;
    high = box(4:6) + planeToleranceMm;
    low(axes(k)) = plane - planeToleranceMm;
    high(axes(k)) = plane + planeToleranceMm;
    selected = comp.selection.create(['mrc_plane_', name], 'Box');
    selected.geom(geomTag, 2);
    selected.set('condition', 'allvertices');
    coordinates = {'x','y','z'};
    for axis = 1:3
        selected.set([coordinates{axis}, 'min'], low(axis));
        selected.set([coordinates{axis}, 'max'], high(axis));
    end
    ids = intersect(exteriorIds, reshape(selected.entities(), 1, []));
    assert(~isempty(ids), 'MRTOF:EmptyOuterFace', 'No vacuum boundary on %s.', name);
    assert(isempty(intersect(covered, ids)), 'MRTOF:OuterFaceOverlap', ...
        'An entire boundary was selected on more than one outer face.');
    covered = union(covered, ids);
    make_explicit(selectionTag, ids);
    functionTag = '';
    functionName = '';
    file = '';
    if k <= 5
        functionTag = ['mrc_boundary_', name];
        functionName = ['V_mrc_', name];
        file = fullfile(boundaryGridDir, [name, '.txt']);
        f = model.func.create(functionTag, 'Interpolation');
        f.set('source', 'file');
        f.set('struct', 'grid');
        f.set('filename', file);
        f.setIndex('funcs', functionName, 0, 0);
        f.set('interp', 'linear');
        f.set('extrap', 'none');
        f.importData();
        % Axis numbers denote mm. Normalize once at the boundary expression;
        % dimensional argument conversion after snapping can cross an endpoint.
        f.set('argunit', {'1','1'});
        f.set('fununit', {'V'});
    elseif ~halfDomain
        % The negative x endpoint consumes the same original xmax function.
        functionTag = faces(1).function_tag;
        functionName = faces(1).function_name;
        file = faces(1).file;
    end
    if k <= 5 || ~halfDomain
        potential = es.create(['mrc_outer_potential_', name], 'ElectricPotential', 2);
        potential.selection.named(selectionTag);
        coordinateArguments = strsplit(faceArguments{k}, ',');
        snapped = cell(1, 2);
        for argumentIndex = 1:2
            axisIndex = argumentAxes(k, argumentIndex);
            numericMm = sprintf('(%s)/(1[mm])', coordinateArguments{argumentIndex});
            snapped{argumentIndex} = snap_endpoint_expression(numericMm, ...
                gridLow(axisIndex), gridHigh(axisIndex));
        end
        potential.set('V0', sprintf('%s(%s,%s)', functionName, snapped{1}, snapped{2}));
    end
    faces(k) = struct('name', name, 'selection_tag', selectionTag, ...
        'boundary_ids', ids, 'function_tag', functionTag, ...
        'function_name', functionName, 'file', file);
end

assert(isempty(setdiff(exteriorIds, covered)), 'MRTOF:UnassignedVacuumExterior', ...
    'Non-electrode vacuum boundaries remain outside the six corridor faces.');
% Only the half-domain xmin remains a natural Zero Charge boundary.
symmetry = faces([]);
if halfDomain
    symmetry = faces(6);
    faces = faces(1:5);
end
out = struct('physics_tag', 'es', 'material_tag', 'mrc_vacuum', ...
    'electrodes', electrodeInfo, 'faces', faces, ...
    'symmetry', symmetry, 'plane_tolerance_mm', planeToleranceMm);

    function make_explicit(tag, ids)
        selection = comp.selection.create(tag, 'Explicit');
        selection.geom(geomTag, 2);
        selection.set(ids);
    end
end

function expression = snap_endpoint_expression(value, low, high)
% Representation-only budget, not a physical tolerance: 16 machine spacings
% cover observed mesh-plane roundoff. Interior and farther-outside values stay
% unchanged; extrap=none still rejects missing coverage beyond this budget.
tolerance = 16 * eps(max([1, abs(low), abs(high)]));
expression = sprintf(['if((%s)<%.17g&&(%s)>=%.17g,%.17g,', ...
    'if((%s)>%.17g&&(%s)<=%.17g,%.17g,(%s)))'], ...
    value, low, value, low-tolerance, low, ...
    value, high, value, high+tolerance, high, value);
end
