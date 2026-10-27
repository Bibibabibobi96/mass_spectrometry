function report = test_comsol_enclosure_geometry(casePath, runDir)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
% Validate frozen enclosure bodies through the production builder, without solving.
% Input: JSON {cases:[{case_id,bodies,expected_body_count,expected_ground_present}]}.
% Bodies use the provider enclosure_layout annuli in mm. Empty bodies mean bare.
% Complete-device cases instead supply resolved_design, expected_rod_count and
% export_step. Their enclosure bodies and RF rods come only from that resolved design.
% COMSOL 6.4 API sources, checked 2026-10-27:
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.015.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.008.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.070.html
% Intersection, measurement and STEP round-trip usage also has native evidence in
% instrument_assembly/20261027_093507__test__cad__component-geometry-acceptance.
import com.comsol.model.util.*
reportPath = fullfile(runDir, 'results', 'comsol_enclosure_geometry.json');
cadDir = fullfile(runDir, 'cad');
if ~isfolder(fileparts(reportPath)), mkdir(fileparts(reportPath)); end
if ~isfolder(cadDir), mkdir(cadDir); end
report = struct('schema_version', 1, 'role', 'multipole_enclosure_geometry_acceptance', ...
    'status', 'running', 'input_path', char(casePath), 'cases', {{}}, ...
    'builder', 'projects/rf_multipole_ion_optics/comsol/build_multipole_enclosure.m', ...
    'domain_count_scope', 'grounded_enclosure_only', ...
    'scope', 'Geometry only; no field, trajectory, manufacturing or Formal qualification.', ...
    'formal_gate_passed', false);
report.api_sources = { ...
    'https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.015.html', ...
    'https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.008.html', ...
    'https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.070.html'};
caseIndex = 0;
item = struct();
write_report(reportPath, report);
try
    request = jsondecode(fileread(casePath));
    cases = request.cases;
    assert(~isempty(cases), 'Enclosure geometry acceptance requires explicit cases.');
    ids = {cases.case_id};
    assert(numel(unique(ids)) == numel(ids), 'Geometry case IDs must be unique.');
    for caseIndex = 1:numel(cases)
        spec = cases(caseIndex);
        item = struct('case_id', spec.case_id, 'status', 'validating');
        assert(~isempty(regexp(spec.case_id, '^[a-z][a-z0-9_]*$', 'once')), ...
            'Geometry case ID must be a safe lowercase identifier.');
        completeDevice = isfield(spec, 'resolved_design');
        if completeDevice
            assert(~isfield(spec, 'bodies'), 'Complete-device cases must have one resolved geometry authority.');
            resolved = spec.resolved_design;
            bodies = resolved.geometry_mm.enclosure_layout.bodies;
            assert(islogical(spec.export_step) && isscalar(spec.export_step), ...
                'Complete-device export_step must be one JSON boolean.');
        else
            bodies = spec.bodies;
        end
        assert(numel(bodies) == spec.expected_body_count, 'Frozen body count differs.');
        assert(islogical(spec.expected_ground_present) && isscalar(spec.expected_ground_present), ...
            'expected_ground_present must be one JSON boolean.');
        item = struct('case_id', spec.case_id, 'status', 'building', ...
            'expected_body_count', spec.expected_body_count, ...
            'expected_ground_present', spec.expected_ground_present, ...
            'raw_bodies', bodies, 'body_measurements', {{}}, 'pair_probes', {{}});
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        modelTag = sprintf('EnclosureAcceptance%03d', caseIndex);
        assert(~any(strcmp(cell(ModelUtil.tags()), modelTag)), 'Acceptance model tag is already in use.');
        model = ModelUtil.create(modelTag);
        modelCleanup = onCleanup(@() ModelUtil.remove(modelTag)); %#ok<NASGU>
        model.component.create('c', true);
        geom = model.component('c').geom.create('g', 3);
        geom.lengthUnit('mm');
        tags = build_multipole_enclosure(geom, bodies, 'housing');
        assert(numel(tags) == spec.expected_body_count, 'Production builder body count differs.');
        item.ground_body_present = ~isempty(tags);
        assert(item.ground_body_present == spec.expected_ground_present, 'Enclosure presence differs.');
        if isempty(tags)
            assert(isempty(cell(geom.objectNames())), 'Bare provider fabricated enclosure geometry.');
            if completeDevice
                check_component_rods(geom, resolved, {}, {}, spec.expected_rod_count);
            end
            item.status = 'pass';
            item.domain_count = 0;
            item.step_roundtrip = struct('status', 'not_applicable', ...
                'reason', 'Bare rods contain no enclosure solid to export.');
            report.cases{caseIndex} = item;
            write_report(reportPath, report);
            clear modelCleanup;
            continue;
        end
        geom.run(tags{end});
        objects = cell(size(tags));
        rawVolume = 0;
        analyticVolume = 0;
        for bodyIndex = 1:numel(tags)
            names = reshape(cell(geom.feature(tags{bodyIndex}).objectNames()), 1, []);
            assert(numel(names) == 1, 'One enclosure annulus must produce one solid object.');
            objects{bodyIndex} = names{1};
            measurement = measure_objects(geom, names);
            assert(measurement.domain_count == 1 && measurement.volume_mm3 > 0, ...
                'An authored enclosure annulus did not materialize as a solid domain.');
            body = bodies(bodyIndex);
            analytic = pi * (body.outer_radius_mm^2 - body.inner_radius_mm^2) * ...
                (body.z_max_mm - body.z_min_mm);
            measurement.role = body.role;
            measurement.analytic_volume_mm3 = analytic;
            measurement.volume_minus_analytic_mm3 = measurement.volume_mm3 - analytic;
            item.body_measurements{bodyIndex} = measurement;
            rawVolume = rawVolume + measurement.volume_mm3;
            analyticVolume = analyticVolume + analytic;
        end
        for left = 1:numel(objects)
            for right = left+1:numel(objects)
                probe = intersection_probe(geom, {objects{left}, objects{right}}, ...
                    sprintf('pair_%03d_%03d', left, right));
                probe.left_role = bodies(left).role;
                probe.right_role = bodies(right).role;
                item.pair_probes{end+1} = probe;
                report.cases{caseIndex} = item;
                write_report(reportPath, report);
                assert(probe.volume_mm3 == 0, 'Enclosure bodies have a positive-volume overlap.');
            end
        end
        if completeDevice
            check_component_rods(geom, resolved, objects, item.body_measurements, spec.expected_rod_count);
        end
        feature = geom.create('housing_union', 'Union');
        feature.selection('input').set(objects);
        feature.set('intbnd', 'off');
        geom.run('housing_union');
        united = reshape(cell(feature.objectNames()), 1, []);
        unionMeasure = measure_objects(geom, united);
        item.domain_count = unionMeasure.domain_count;
        item.union = unionMeasure;
        item.raw_volume_sum_mm3 = rawVolume;
        item.analytic_volume_sum_mm3 = analyticVolume;
        item.union_volume_minus_raw_sum_mm3 = unionMeasure.volume_mm3 - rawVolume;
        item.union_volume_minus_analytic_mm3 = unionMeasure.volume_mm3 - analyticVolume;
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        assert(unionMeasure.domain_count == 1, 'Housing is not one continuous conductor domain.');
        lower = min([bodies.z_min_mm]);
        upper = max([bodies.z_max_mm]);
        radius = min([bodies.inner_radius_mm]);
        create_comsol_cylinder(geom, 'axial_clearance', radius, upper-lower, lower, false);
        geom.run('axial_clearance');
        hole = reshape(cell(geom.feature('axial_clearance').objectNames()), 1, []);
        item.axial_hole_probe = intersection_probe(geom, [united, hole], 'axial_hole_probe');
        item.axial_hole_probe.radius_mm = radius;
        item.axial_hole_probe.z_min_mm = lower;
        item.axial_hole_probe.z_max_mm = upper;
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        assert(item.axial_hole_probe.volume_mm3 == 0, 'Housing blocks its declared central through-hole.');
        geom.feature.remove('axial_clearance');
        if ~completeDevice || spec.export_step
            stepPath = fullfile(cadDir, [spec.case_id '.step']);
            item.step_roundtrip = step_roundtrip(geom, united, stepPath, unionMeasure, caseIndex);
        else
            item.step_roundtrip = struct('status', 'not_requested', ...
                'reason', 'STEP export explicitly disabled for this clearance case.');
        end
        item.status = 'pass';
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        clear modelCleanup;
    end
    report.status = 'success';
    report.case_count = numel(cases);
    write_report(reportPath, report);
    fprintf('COMSOL_ENCLOSURE_GEOMETRY=PASS CASES=%d GEOMETRY_ONLY=1\n', numel(cases));
catch failure
    report.status = 'failed';
    report.error = struct('identifier', failure.identifier, 'message', failure.message, ...
        'stack', failure.stack);
    if caseIndex > 0
        item.status = 'failed';
        report.cases{caseIndex} = item;
    end
    write_report(reportPath, report);
    rethrow(failure);
end

    function check_component_rods(geometry, design, groundObjects, groundMeasurements, expectedCount)
        % Use the same rod constructors and resolved arrays as the native transport builder.
        facts = struct('status', 'building_rods', 'expected_rod_count', expectedCount, ...
            'resolved_design_sha256', design.resolved_sha256, 'components', {{}}, ...
            'pairs', {{}}, 'checked_pair_count', 0, 'bbox_separated_pair_count', 0, ...
            'boolean_pair_count', 0, 'positive_overlap_count', 0);
        item.component_geometry = facts;
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        rodArray = design.geometry_mm.rod_array;
        segmented = isfield(design.segmentation, 'segmented_rod_array') && ...
            ~isempty(design.segmentation.segmented_rod_array);
        if segmented
            facts.rod_builder = 'common/comsol/create_multipole_segmented_round_rods.m';
            [rodTags, metadata] = create_multipole_segmented_round_rods( ...
                geometry, rodArray, design.segmentation.axial_acceleration, 'rfrod');
        else
            facts.rod_builder = 'common/comsol/create_multipole_round_rods.m';
            rodTags = create_multipole_round_rods(geometry, rodArray, 'rfrod', 'z', [0 0 0]);
        end
        facts.rod_count = numel(rodTags);
        facts.ground_body_count = numel(groundObjects);
        item.component_geometry = facts;
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        assert(facts.rod_count == expectedCount && expectedCount > 0, 'Actual RF rod count differs.');
        geometry.run(rodTags{end});
        rodObjects = cell(size(rodTags));
        for rodIndex = 1:numel(rodTags)
            names = reshape(cell(geometry.feature(rodTags{rodIndex}).objectNames()), 1, []);
            assert(numel(names) == 1, 'One RF rod segment must produce one solid object.');
            rodObjects{rodIndex} = names{1};
            measured = measure_objects(geometry, names);
            assert(measured.domain_count == 1 && measured.volume_mm3 > 0, ...
                'An RF rod did not materialize as a solid domain.');
            if segmented
                rodId = metadata(rodIndex).rod_id;
                segmentId = metadata(rodIndex).segment_id;
                group = metadata(rodIndex).electrode_group;
            else
                rodId = rodArray.rods(rodIndex).rod_id;
                segmentId = [];
                group = rodArray.rods(rodIndex).electrode_group;
            end
            facts.components{end+1} = struct('kind', 'rf_rod', 'native_tag', rodTags{rodIndex}, ...
                'native_object', names{1}, 'rod_id', rodId, 'segment_id', segmentId, ...
                'electrode_group', group, 'geometry', measured);
        end
        for groundIndex = 1:numel(groundObjects)
            facts.components{end+1} = struct('kind', 'ground', ...
                'role', groundMeasurements{groundIndex}.role, ...
                'native_object', groundObjects{groundIndex}, 'geometry', groundMeasurements{groundIndex});
        end
        componentObjects = [rodObjects, groundObjects];
        facts.expected_pair_count = numel(rodObjects)*(numel(rodObjects)-1)/2 + ...
            numel(rodObjects)*numel(groundObjects);
        facts.status = 'checking_clearances';
        for leftIndex = 1:numel(rodObjects)
            for rightIndex = leftIndex+1:numel(componentObjects)
                leftBox = facts.components{leftIndex}.geometry.bbox_mm;
                rightBox = facts.components{rightIndex}.geometry.bbox_mm;
                gap = max(leftBox(1:3), rightBox(1:3)) - min(leftBox(4:6), rightBox(4:6));
                pair = struct('left_component', leftIndex, 'right_component', rightIndex, ...
                    'native_bbox_gap_mm', gap, 'measured_volume_mm3', [], 'volume_upper_bound_mm3', []);
                if any(gap >= 0)
                    pair.method = 'disjoint_native_bounding_boxes';
                    pair.volume_upper_bound_mm3 = 0;
                    facts.bbox_separated_pair_count = facts.bbox_separated_pair_count + 1;
                else
                    facts.active_pair = [leftIndex, rightIndex];
                    item.component_geometry = facts;
                    report.cases{caseIndex} = item;
                    write_report(reportPath, report);
                    probe = intersection_probe(geometry, componentObjects([leftIndex, rightIndex]), ...
                        sprintf('rod_probe_%03d_%03d', leftIndex, rightIndex));
                    pair.method = 'native_intersection';
                    pair.measured_volume_mm3 = probe.volume_mm3;
                    facts.boolean_pair_count = facts.boolean_pair_count + 1;
                    facts.positive_overlap_count = facts.positive_overlap_count + (probe.volume_mm3 > 0);
                end
                facts.pairs{end+1} = pair;
                facts.checked_pair_count = facts.checked_pair_count + 1;
            end
        end
        facts.active_pair = [];
        facts.status = 'completed';
        item.component_geometry = facts;
        report.cases{caseIndex} = item;
        write_report(reportPath, report);
        assert(facts.checked_pair_count == facts.expected_pair_count, 'RF clearance pair coverage is incomplete.');
        assert(facts.positive_overlap_count == 0, 'RF rods overlap another rod or grounded enclosure body.');
    end
end

function result = intersection_probe(geom, objects, tag)
feature = geom.create(tag, 'Intersection');
feature.selection('input').set(objects);
feature.set('keep', 'on');
feature.set('keeplowerdim', 'off');
geom.run(tag);
result = measure_objects(geom, reshape(cell(feature.objectNames()), 1, []));
geom.feature.remove(tag);
end

function result = measure_objects(geom, objects)
result = struct('object_count', numel(objects), 'domain_count', 0, 'volume_mm3', 0, 'bbox_mm', []);
if isempty(objects), return; end
for index = 1:numel(objects)
    object = geom.obj(objects{index});
    object.check();
    result.domain_count = result.domain_count + double(object.getNDomains());
end
geom.measure().selection().init(3);
for index = 1:numel(objects), geom.measure().selection().all(objects{index}); end
result.volume_mm3 = double(geom.measure().getVolume());
coordinates = double(geom.measure().getBoundingBox());
result.bbox_mm = reshape(coordinates([1 3 5 2 4 6]), 1, 6);
assert(isfinite(result.volume_mm3) && result.volume_mm3 >= 0, 'Invalid geometric volume.');
end

function result = step_roundtrip(geom, objects, stepPath, source, index)
import com.comsol.model.util.*
exporter = geom.export();
exporter.selection().init();
exporter.selection().set(objects);
exporter.setType('step');
exporter.setLengthUnitSTEP('mm');
geom.export(stepPath);
tag = sprintf('EnclosureCold%03d', index);
assert(~any(strcmp(cell(ModelUtil.tags()), tag)), 'Cold-import model tag is already in use.');
cold = ModelUtil.create(tag);
cleanup = onCleanup(@() ModelUtil.remove(tag)); %#ok<NASGU>
cold.component.create('c', true);
coldGeom = cold.component('c').geom.create('g', 3);
coldGeom.lengthUnit('mm');
feature = coldGeom.create('imp', 'Import');
feature.set('filename', stepPath);
coldGeom.run('imp');
objects = reshape(cell(feature.objectNames()), 1, []);
result = measure_objects(coldGeom, objects);
result.path = stepPath;
result.volume_minus_source_mm3 = result.volume_mm3 - source.volume_mm3;
result.bbox_minus_source_mm = result.bbox_mm - source.bbox_mm;
result.measurement_boundary = 'Approximate kernel residuals; no manufacturing tolerance qualification.';
assert(result.domain_count == 1, 'STEP cold import lost the continuous housing domain.');
end

function write_report(reportPath, report)
temporary = [reportPath '.tmp'];
file = fopen(temporary, 'w');
assert(file >= 0, 'Cannot write enclosure geometry facts.');
cleanup = onCleanup(@() fclose(file));
fprintf(file, '%s\n', jsonencode(report, PrettyPrint=true));
clear cleanup;
[moved, message] = movefile(temporary, reportPath, 'f');
assert(moved, 'Cannot publish enclosure geometry facts: %s', message);
end
