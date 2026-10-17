function [value, physical_id, namespace] = classify_corridor_conductor_voltage( ...
    points_mm, geometry, analyzer_voltages_v, assembly, component_voltages_v)
% CLASSIFY_CORRIDOR_CONDUCTOR_VOLTAGE Prescribed V at known conductor points.
% N-by-3 project coordinates are in mm; voltages are V. Call only after the
% native vacuum FEM query is nonfinite. This is not a collision classifier.
% Reuses the frozen analyzer strict CSG and later-ID ordering. OA/detector use
% the same resolved projection as build_corridor_reference_geometry, without
% rederiving dimensions. Cross-component identity conflicts, exposed surfaces
% and unknowns return NaN, ID zero and empty namespace. Ideal transparent
% sheets have exactly zero thickness; only their open aperture interior is V.
validateattributes(points_mm, {'numeric'}, {'real','finite','2d','ncols',3});
validateattributes(analyzer_voltages_v, {'numeric'}, {'real','finite','vector'});
points = double(points_mm);
points(:,1) = abs(points(:,1));
[value, physical_id, analyzer_boundary] = analyzer_voltage(points, geometry, analyzer_voltages_v);
namespace = strings(size(physical_id));
namespace(physical_id > 0) = "analyzer";
conflict = false(size(physical_id));
uncertain = false(size(physical_id));
oa = assembly.accelerator_resolved_electrodes;
assert(oa.schema_version == 1 && ...
    strcmp(oa.coordinate_frame, 'accelerator_centered_transverse_local_z_mm') && ...
    strcmp(oa.acceleration_direction, '-z'), 'MRTOF:InvalidAssembly', ...
    'Unsupported resolved OA coordinate contract');
offset = reshape(oa.local_to_pa_translation_mm,1,3) + ...
    reshape(assembly.accelerator_iob_origin_mm,1,3);
assert(all(isfinite(offset)) && offset(1) == 0, 'MRTOF:InvalidAssembly', ...
    'OA assembly must retain the x=0 symmetry plane');
body = oa.grounded_enclosure;
[s,c] = boxMasks(points, project_box(body.outer_box_mm,offset));
[hs,hc] = boxMasks(points, project_box(body.cavity_box_mm,offset));
[es,ec] = boxMasks(points, project_box(body.exit_opening_box_mm,offset));
accept(s & ~(hc|ec), (c & ~s & ~(hs|es)) | (c & ((hc & ~hs)|(ec & ~es))), ...
    body.component_electrode_id, 'accelerator');
body = oa.repeller;
[s,c] = boxMasks(points, project_box(body.solid_box_mm,offset));
accept(s,c & ~s,body.component_electrode_id,'accelerator');
for k=1:numel(oa.grid_supports)
    body = itemAt(oa.grid_supports,k);
    [s,c] = boxMasks(points,project_box(body.frame_outer_box_mm,offset));
    [hs,hc] = boxMasks(points,project_box(body.aperture_box_mm,offset));
    accept(s & ~hc,(c & ~s & ~hs)|(c & hc & ~hs), ...
        body.component_electrode_id,'accelerator');
    assert(strcmp(body.transmission,'ideal_transparent'), ...
        'MRTOF:InvalidAssembly','Only the resolved ideal transparent sheet is supported');
    sheet = body.ideal_sheet_mm;
    low = [sheet.x_min_mm,sheet.y_min_mm] + offset(1:2);
    high = [sheet.x_max_mm,sheet.y_max_mm] + offset(1:2);
    % Equality restricts V to the original plane, never a PA-thick slab.
    on_plane = points(:,3) == sheet.z_mm + offset(3);
    interior = on_plane & points(:,1) >= 0 & points(:,1) < high(1) & ...
        points(:,1) > low(1) & points(:,2) > low(2) & points(:,2) < high(2);
    edge = on_plane & all(points(:,1:2) >= low & points(:,1:2) <= high,2) & ~interior;
    accept(interior,edge,body.component_electrode_id,'accelerator');
end
for k=1:numel(oa.rings)
    body = itemAt(oa.rings,k);
    [s,c] = boxMasks(points,project_box(body.outer_box_mm,offset));
    [hs,hc] = boxMasks(points,project_box(body.aperture_box_mm,offset));
    accept(s & ~hc,(c & ~s & ~hs)|(c & hc & ~hs), ...
        body.component_electrode_id,'accelerator');
end
body = assembly.detector;
assert(body.separate_pa == true,'MRTOF:InvalidAssembly','Detector component identity required');
[s,c] = boxMasks(points,body.box);
accept(s,c & ~s,body.id,'detector');
invalid = conflict | uncertain | analyzer_boundary;
value(invalid) = NaN;
physical_id(invalid) = 0;
namespace(invalid) = "";

    function accept(strict, boundary, id, space)
        entries = false(1,numel(component_voltages_v));
        for j=1:numel(component_voltages_v)
            entry = itemAt(component_voltages_v,j);
            entries(j) = strcmp(entry.component_namespace,space) && entry.component_electrode_id == id;
        end
        assert(nnz(entries)==1,'MRTOF:ComponentVoltage', ...
            'Exactly one namespaced prescribed voltage is required');
        entry = itemAt(component_voltages_v,find(entries,1));
        validateattributes(entry.voltage_v,{'numeric'},{'scalar','real','finite'});
        same = physical_id == id & namespace == string(space);
        conflict = conflict | (strict & physical_id > 0 & ~same);
        chosen = strict & ~conflict;
        value(chosen) = entry.voltage_v;
        physical_id(chosen) = id;
        namespace(chosen) = string(space);
        uncertain(chosen) = false; % Same-ID union absorbs internal primitive faces.
        uncertain = uncertain | (boundary & ~same);
    end
end

function box = project_box(record, offset)
% Exact projection used by the COMSOL assembly geometry consumer.
box = [record.x_min_mm,record.y_min_mm,record.z_min_mm, ...
       record.x_max_mm,record.y_max_mm,record.z_max_mm] + [offset,offset];
end
function [value, physicalId, uncertain] = analyzer_voltage(points, geometry, voltages)
% CLASSIFYCONDUCTORVOLTAGE Return prescribed V only for strict effective solids.
% points: N-by-3 mm coordinates, called only for nonfinite vacuum FEM queries.
% The primitive and later-ID order mirrors build_corridor_reference_geometry.m.
% Boundaries, holes and points without one effective conductor retain ID zero.
points = double(points);
points(:, 1) = abs(points(:, 1)); % The saved model mirrors its positive half.
physicalId = zeros(size(points, 1), 1);
uncertain = false(size(physicalId));

for k = 1:numel(geometry.mirror_electrodes)
    body = itemAt(geometry.mirror_electrodes, k);
    if isfield(geometry, 'mirror_convergence_transform')
        [strict, closed, holeStrict, holeClosed] = mirrorMasks(points, body);
    else
        [strict, closed] = boxMasks(points, body.box);
        [holeStrict, holeClosed] = boxMasks(points, body.beam_slot);
    end
    [physicalId, uncertain] = consume(physicalId, uncertain, strict, closed, ...
        holeStrict, holeClosed, body.id);
end
for k = 1:numel(geometry.mirror_ground_shields)
    body = itemAt(geometry.mirror_ground_shields, k);
    if isfield(geometry, 'mirror_convergence_transform')
        [strict, closed, holeStrict, holeClosed] = mirrorMasks(points, body);
    else
        [strict, closed] = boxMasks(points, body.box);
        holeStrict = false(size(physicalId));
        holeClosed = holeStrict;
        if strcmp(body.role, 'inner_stripe_facing_4mm_slot')
            [holeStrict, holeClosed] = boxMasks(points, geometry.mirror_inner_shield_slot);
        end
    end
    [physicalId, uncertain] = consume(physicalId, uncertain, strict, closed, ...
        holeStrict, holeClosed, 15);
end
for k = 1:numel(geometry.mirror_e_closures)
    body = itemAt(geometry.mirror_e_closures, k);
    if isfield(geometry, 'mirror_convergence_transform')
        [strict, closed, holeStrict, holeClosed] = mirrorMasks(points, body);
    else
        [strict, closed] = boxMasks(points, body.box);
        holeStrict = false(size(physicalId));
        holeClosed = holeStrict;
    end
    [physicalId, uncertain] = consume(physicalId, uncertain, strict, closed, ...
        holeStrict, holeClosed, body.id);
end
for k = 1:numel(geometry.stripe_electrodes)
    body = itemAt(geometry.stripe_electrodes, k);
    [mainStrict, mainClosed] = polygonMasks(points, body.x, body.polygon_yz_mm);
    [terminalStrict, terminalClosed] = polygonMasks(points, body.x, body.terminal_polygon_yz_mm);
    [holeStrict, holeClosed] = boxMasks(points, geometry.stripe_slot);
    [physicalId, uncertain] = consume(physicalId, uncertain, ...
        mainStrict | terminalStrict, mainClosed | terminalClosed, ...
        holeStrict, holeClosed, body.id);
end
for k = 1:numel(geometry.central_ground_electrodes)
    body = itemAt(geometry.central_ground_electrodes, k);
    [strict, closed] = polygonMasks(points, body.x, body.polygon_yz_mm);
    holeStrict = false(size(physicalId));
    holeClosed = holeStrict;
    for j = 1:size(geometry.central_ground_slots, 1)
        [thisStrict, thisClosed] = boxMasks(points, geometry.central_ground_slots(j, :));
        holeStrict = holeStrict | thisStrict;
        holeClosed = holeClosed | thisClosed;
    end
    [physicalId, uncertain] = consume(physicalId, uncertain, strict, closed, ...
        holeStrict, holeClosed, 15);
end
for k = 1:numel(geometry.prism_electrodes)
    body = itemAt(geometry.prism_electrodes, k);
    for j = 1:numel(body.parts)
        part = itemAt(body.parts, j);
        [strict, closed] = polygonMasks(points, part.x, part.polygon_yz_mm);
        [physicalId, uncertain] = consume(physicalId, uncertain, strict, closed, ...
            false(size(physicalId)), false(size(physicalId)), body.id);
    end
end
for k = 1:numel(geometry.prism_ground_shields)
    body = itemAt(geometry.prism_ground_shields, k);
    [holeStrict, holeClosed] = polygonMasks(points, body.x, body.prism_clearance_polygon_yz_mm);
    for j = 1:size(body.rectangular_slots_mm, 1)
        [thisStrict, thisClosed] = boxMasks(points, body.rectangular_slots_mm(j, :));
        holeStrict = holeStrict | thisStrict;
        holeClosed = holeClosed | thisClosed;
    end
    for j = 1:numel(body.body_sections)
        section = itemAt(body.body_sections, j);
        [strict, closed] = polygonMasks(points, section.x, section.polygon_yz_mm);
        [physicalId, uncertain] = consume(physicalId, uncertain, strict, closed, ...
            holeStrict, holeClosed, body.id);
    end
end
physicalId(uncertain) = 0;
assert(numel(voltages) >= max(physicalId), 'Frozen voltage vector omits a physical conductor');
value = nan(size(physicalId));
chosen = physicalId > 0;
value(chosen) = voltages(physicalId(chosen));
end

function [strict, closed, holeStrict, holeClosed] = mirrorMasks(points, body)
% Match the builder's transformed extrusion and all resolved hole extrusions.
assert(isfield(body, 'x') && isfield(body, 'polygon_yz_mm') && ...
    isfield(body, 'holes'), 'MRTOF:MissingMirrorPolygon', ...
    'Transformed mirror solids require resolved x, polygon and holes.');
[strict, closed] = polygonMasks(points, body.x, body.polygon_yz_mm);
holeStrict = false(size(strict));
holeClosed = holeStrict;
for k = 1:numel(body.holes)
    hole = itemAt(body.holes, k);
    assert(isfield(hole, 'x') && isfield(hole, 'polygon_yz_mm'), ...
        'MRTOF:MissingMirrorPolygon', 'Transformed mirror hole requires its resolved polygon.');
    [hs, hc] = polygonMasks(points, hole.x, hole.polygon_yz_mm);
    holeStrict = holeStrict | hs;
    holeClosed = holeClosed | hc;
end
end

function [id, uncertain] = consume(id, uncertain, strict, closed, holeStrict, holeClosed, physicalId)
% The last physical electrode wins where distinct solids overlap.
effectiveStrict = strict & ~holeClosed;
effectiveBoundary = (closed & ~strict & ~holeStrict) | ...
    (closed & holeClosed & ~holeStrict);
% Strict later material overrides a prior primitive boundary. Same-ID
% unions also absorb internal primitive faces, while exposed faces remain
% invalid rather than fabricating a vacuum or conductor potential.
uncertain(effectiveStrict) = false;
id(effectiveStrict) = physicalId;
uncertain = uncertain | (effectiveBoundary & id ~= physicalId);
end

function [strict, closed] = boxMasks(points, box)
% x=0 is interior after mirroring if the positive primitive reaches that plane.
box = double(box(:).');
low = [max(0, box(1)), box(2:3)];
high = box(4:6);
strict = false(size(points, 1), 1);
closed = strict;
if high(1) <= low(1)
    return
end
tolerance = 1e-9; % Conservative geometry-boundary exclusion, not a mesh halo.
closed = all(points >= low - tolerance & points <= high + tolerance, 2);
strict = all(points(:, 2:3) > low(2:3) + tolerance & ...
    points(:, 2:3) < high(2:3) - tolerance, 2);
if low(1) == 0
    strict = strict & points(:, 1) < high(1) - tolerance;
else
    strict = strict & points(:, 1) > low(1) + tolerance & ...
        points(:, 1) < high(1) - tolerance;
end
end

function [strict, closed] = polygonMasks(points, xRange, polygon)
% Use MATLAB's inpolygon on the same y-z vertices consumed by the COMSOL builder.
xRange = double(xRange(:).');
polygon = double(polygon);
lowX = max(0, xRange(1));
strict = false(size(points, 1), 1);
closed = strict;
if xRange(2) <= lowX
    return
end
tolerance = 1e-9;
candidate = points(:, 1) >= lowX - tolerance & ...
    points(:, 1) <= xRange(2) + tolerance & ...
    points(:, 2) >= min(polygon(:, 1)) - tolerance & ...
    points(:, 2) <= max(polygon(:, 1)) + tolerance & ...
    points(:, 3) >= min(polygon(:, 2)) - tolerance & ...
    points(:, 3) <= max(polygon(:, 2)) + tolerance;
if ~any(candidate)
    return
end
[inside, on] = inpolygon(points(candidate, 2), points(candidate, 3), ...
    polygon(:, 1), polygon(:, 2));
closed(candidate) = inside | on;
if lowX == 0
    xInside = points(candidate, 1) < xRange(2) - tolerance;
else
    xInside = points(candidate, 1) > lowX + tolerance & ...
        points(candidate, 1) < xRange(2) - tolerance;
end
strict(candidate) = inside & ~on & xInside;
end

function item = itemAt(items, index)
% JSON records with unequal fields may decode as a cell array.
if iscell(items)
    item = items{index};
else
    item = items(index);
end
end
