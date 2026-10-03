function out = build_corridor_reference_geometry(geom, resolved, corridorBoxMm)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
% Maintained project geometry adapter; not yet model/geometry qualified.
% Input: resolve_geometry output and [xmin ymin zmin xmax ymax zmax], mm.
% A symmetric two-sided box mirrors the positive-half definition, matching
% native SIMION x symmetry even if resolved negative-side polygons differ.
% Caller owns geom creation/finalization and all non-geometric setup.
% Preserve original polygons. Closed CAD boundaries do not reproduce
% SIMION's inside/on voxel collision classifications.
% Official COMSOL 6.4 API checked 2026-10-02:
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.143.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.125.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.088.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.070.html
validateattributes(corridorBoxMm, {'numeric'}, {'real','finite','numel',6});
corridorBoxMm = reshape(corridorBoxMm, 1, 6);
assert(all(corridorBoxMm(4:6) > corridorBoxMm(1:3)), ...
    'MRTOF:InvalidCorridor', 'Corridor must have positive axis extents.');
if corridorBoxMm(1) < 0
    assert(corridorBoxMm(1) == -corridorBoxMm(4), ...
        'MRTOF:InvalidCorridor', 'Two-sided reference requires symmetric x extents.');
    halfBox = corridorBoxMm;
    halfBox(1) = 0;
    out = build_corridor_reference_geometry(geom, resolved, halfBox);
    % COMSOL 6.4 Mirror, comsol_api_geom.48.113.html; tested with actual solids.
    for k = 1:numel(out.electrodes)+1
        if k <= numel(out.electrodes)
            original = out.electrodes(k).object_tag;
        else
            original = out.vacuum_tag;
        end
        mirrorTag = sprintf('mrcMirror%d', k);
        mirror = geom.create(mirrorTag, 'Mirror');
        mirror.selection('input').set({original});
        mirror.set('axis', [1,0,0]);
        mirror.set('pos', [0,0,0]);
        mirror.set('keep', 'on');
        unionTag = sprintf('mrcFull%d', k);
        united = geom.create(unionTag, 'Union');
        united.selection('input').set({original, mirrorTag});
        united.set('intbnd', 'off');
        united.set('selresult', 'on');
        united.set('selresultshow', 'all');
        if k <= numel(out.electrodes)
            out.electrodes(k).object_tag = unionTag;
            out.electrodes(k).domain_selection = selection_name(unionTag, 'dom');
            out.electrodes(k).boundary_selection = selection_name(unionTag, 'bnd');
        else
            % Retain the vacuum midplane for native CopyDomain meshing.
            % This is an internal interface, not a physical electrode/wall.
            united.set('intbnd', 'on');
            out.vacuum_tag = unionTag;
            out.vacuum_domain_selection = selection_name(unionTag, 'dom');
            out.vacuum_boundary_selection = selection_name(unionTag, 'bnd');
        end
    end
    out.corridor_box_mm = corridorBoxMm;
    return
end
geom.lengthUnit('mm');
serial = 0;
bodies = struct('id', {}, 'tag', {}, 'box_mm', {});
% Match native_system_geometry._analyzer_geometry_lines emission order.
for k = 1:numel(resolved.mirror_electrodes)
    item = at(resolved.mirror_electrodes, k);
    tag = subtract(block(item.box), {block(item.beam_slot)}, false);
    append(item.id, tag, item.box);
end
for k = 1:numel(resolved.mirror_ground_shields)
    item = at(resolved.mirror_ground_shields, k);
    tag = block(item.box);
    if strcmp(item.role, 'inner_stripe_facing_4mm_slot')
        tag = subtract(tag, {block(resolved.mirror_inner_shield_slot)}, false);
    end
    append(15, tag, item.box);
end
for k = 1:numel(resolved.mirror_e_closures)
    item = at(resolved.mirror_e_closures, k);
    append(item.id, block(item.box), item.box);
end
for k = 1:numel(resolved.stripe_electrodes)
    item = at(resolved.stripe_electrodes, k);
    extent = union_box(polygon_box(item.x, item.polygon_yz_mm), ...
        polygon_box(item.x, item.terminal_polygon_yz_mm));
    tag = unite({extrude(item.x, item.polygon_yz_mm), ...
        extrude(item.x, item.terminal_polygon_yz_mm)});
    append(item.id, subtract(tag, {block(resolved.stripe_slot)}, false), extent);
end
[tag, extent] = extrude_parts(resolved.central_ground_electrodes);
holes = cell(1, size(resolved.central_ground_slots, 1));
for k = 1:numel(holes)
    holes{k} = block(resolved.central_ground_slots(k, :));
end
append(15, subtract(tag, holes, false), extent);
for k = 1:numel(resolved.prism_electrodes)
    item = at(resolved.prism_electrodes, k);
    [tag, extent] = extrude_parts(item.parts);
    append(item.id, tag, extent);
end
for k = 1:numel(resolved.prism_ground_shields)
    item = at(resolved.prism_ground_shields, k);
    [tag, extent] = extrude_parts(item.body_sections);
    holes = {extrude(item.x, item.prism_clearance_polygon_yz_mm)};
    if isfield(item, 'rectangular_slots_mm')
        for j = 1:size(item.rectangular_slots_mm, 1)
            holes{end+1} = block(item.rectangular_slots_mm(j, :)); %#ok<AGROW>
        end
    end
    append(item.id, subtract(tag, holes, false), extent);
end
% Later GEM electrodes overwrite earlier ones. Only unlike-ID bounding-box
% overlaps need Boolean subtraction; retain later physical solids.
for k = numel(bodies):-1:1
    later = {};
    for j = k+1:numel(bodies)
        if bodies(k).id ~= bodies(j).id && overlaps(bodies(k).box_mm, bodies(j).box_mm)
            later{end+1} = bodies(j).tag; %#ok<AGROW>
        end
    end
    bodies(k).tag = subtract(bodies(k).tag, later, true);
end
ids = unique([bodies.id], 'stable');
electrodes = struct('id', {}, 'object_tag', {}, 'domain_selection', {}, 'boundary_selection', {});
tags = cell(1, numel(ids));
for k = 1:numel(ids)
    tags{k} = unite({bodies([bodies.id] == ids(k)).tag});
    mark_selection(tags{k});
    electrodes(k) = struct('id', ids(k), 'object_tag', tags{k}, ...
        'domain_selection', selection_name(tags{k}, 'dom'), ...
        'boundary_selection', selection_name(tags{k}, 'bnd'));
end
vacuum = subtract(block(corridorBoxMm), tags, true);
mark_selection(vacuum);
out = struct('electrodes', electrodes, 'vacuum_tag', vacuum, ...
    'vacuum_domain_selection', selection_name(vacuum, 'dom'), ...
    'vacuum_boundary_selection', selection_name(vacuum, 'bnd'), ...
    'corridor_box_mm', corridorBoxMm);

    function tag = next_tag()
        serial = serial + 1;
        tag = sprintf('mrc%d', serial);
    end
    function tag = block(box)
        box = clip_box(reshape(box, 1, 6));
        if any(box(4:6) <= box(1:3))
            tag = '';
            return
        end
        tag = next_tag();
        feature = geom.create(tag, 'Block');
        feature.set('base', 'corner');
        feature.set('pos', box(1:3));
        feature.set('size', box(4:6) - box(1:3));
    end
    function tag = extrude(x, polygon)
        box = clip_box(polygon_box(x, polygon));
        if any(box(4:6) <= box(1:3))
            tag = '';
            return
        end
        wpTag = next_tag();
        wp = geom.create(wpTag, 'WorkPlane');
        wp.set('planetype', 'quick');
        wp.set('quickplane', 'yz');
        wp.set('quickx', box(1));
        poly = wp.geom.create('outline', 'Polygon');
        poly.set('source', 'table');
        poly.set('table', polygon);
        poly.set('type', 'solid');
        extTag = next_tag();
        ext = geom.create(extTag, 'Extrude');
        ext.set('workplane', wpTag);
        ext.selection('input').set({wpTag});
        ext.set('distance', box(4) - box(1));
        clipTag = block(corridorBoxMm);
        tag = next_tag();
        clip = geom.create(tag, 'Intersection');
        clip.selection('input').set({extTag, clipTag});
        clip.set('intbnd', 'off');
    end
    function [tag, box] = extrude_parts(items)
        inputs = cell(1, numel(items));
        box = [];
        for n = 1:numel(items)
            part = at(items, n);
            inputs{n} = extrude(part.x, part.polygon_yz_mm);
            box = union_box(box, polygon_box(part.x, part.polygon_yz_mm));
        end
        tag = unite(inputs);
    end
    function tag = unite(inputs)
        inputs = inputs(~cellfun(@isempty, inputs));
        if isempty(inputs)
            tag = '';
        elseif numel(inputs) == 1
            tag = inputs{1};
        else
            tag = next_tag();
            feature = geom.create(tag, 'Union');
            feature.selection('input').set(inputs);
            feature.set('intbnd', 'off');
        end
    end
    function tag = subtract(tag, holes, retain)
        holes = holes(~cellfun(@isempty, holes));
        if isempty(tag) || isempty(holes)
            return
        end
        input = tag;
        tag = next_tag();
        feature = geom.create(tag, 'Difference');
        feature.selection('input').set({input});
        feature.selection('input2').set(holes);
        if retain
            feature.set('keepsubtract', 'on');
        end
        feature.set('intbnd', 'off');
    end
    function append(id, tag, box)
        if ~isempty(tag)
            bodies(end+1) = struct('id', id, 'tag', tag, 'box_mm', clip_box(box));
        end
    end
    function box = clip_box(box)
        box = [max(box(1:3), corridorBoxMm(1:3)), min(box(4:6), corridorBoxMm(4:6))];
    end
    function mark_selection(tag)
        geom.feature(tag).set('selresult', 'on');
        geom.feature(tag).set('selresultshow', 'all');
    end
    function name = selection_name(tag, entity)
        name = [char(geom.tag()), '_', tag, '_', entity];
    end
end
function item = at(items, index)
% jsondecode uses cells for records with unequal field sets.
if iscell(items)
    item = items{index};
else
    item = items(index);
end
end
function box = polygon_box(x, polygon)
box = [x(1), min(polygon, [], 1), x(2), max(polygon, [], 1)];
end
function box = union_box(a, b)
if isempty(a)
    box = b;
else
    box = [min(a(1:3), b(1:3)), max(a(4:6), b(4:6))];
end
end
function yes = overlaps(a, b)
yes = all(min(a(4:6), b(4:6)) > max(a(1:3), b(1:3)));
end
