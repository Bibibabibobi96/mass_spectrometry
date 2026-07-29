function tests = test_export_comsol_stationary_field_samples
%TEST_EXPORT_COMSOL_STATIONARY_FIELD_SAMPLES Future LiveLink smoke entry.
tests = functiontests(localfunctions);
end

function setupOnce(testCase)
import com.comsol.model.util.*

modelTag = 'StationaryFieldSampleFixture';
existingModelTags = cell(ModelUtil.tags());
if any(strcmp(existingModelTags, modelTag))
    ModelUtil.remove(modelTag);
end
model = ModelUtil.create(modelTag);
component = model.component.create('comp1', true);
geometry = component.geom.create('geom1', 3);
geometry.lengthUnit('mm');
block = geometry.feature.create('blk1', 'Block');
block.set('size', {'1', '1', '1'});
block.set('pos', {'-0.5', '-0.5', '-0.5'});
geometry.run();

leftBoundary = mphselectbox(model, 'geom1', ...
    [-0.501, -0.499; -0.501, 0.501; -0.501, 0.501], 'boundary');
rightBoundary = mphselectbox(model, 'geom1', ...
    [0.499, 0.501; -0.501, 0.501; -0.501, 0.501], 'boundary');
assert(~isempty(leftBoundary) && ~isempty(rightBoundary), ...
    'The fixture could not identify its driven boundaries.');

model.param.set('fixture_drive', '1[V]');
electrostatics = component.physics.create('es', 'Electrostatics', 'geom1');
ground = electrostatics.feature.create('gnd1', 'Ground', 2);
ground.selection.set(leftBoundary);
potential = electrostatics.feature.create('pot1', 'ElectricPotential', 2);
potential.selection.set(rightBoundary);
potential.set('V0', 'fixture_drive');

mesh = component.mesh.create('mesh1');
mesh.feature('size').set('hauto', 3);
tetrahedra = mesh.feature.create('ftet1', 'FreeTet');
tetrahedra.selection.geom('geom1', 3);
tetrahedra.selection.all();
mesh.run();

solve_fixture_case(model, 'one', '1[V]');
solve_fixture_case(model, 'two', '2[V]');
testCase.TestData.Model = model;
testCase.TestData.ModelTag = modelTag;
end

function teardownOnce(testCase)
import com.comsol.model.util.*
ModelUtil.remove(testCase.TestData.ModelTag);
end

function test_two_stationary_solutions_are_sampled_and_datasets_are_removed(testCase)
model = testCase.TestData.Model;
temporaryDirectory = tempname();
mkdir(temporaryDirectory);
cleanup = onCleanup(@() rmdir(temporaryDirectory, 's'));
pointsPath = fullfile(temporaryDirectory, 'points.csv');
outputPath = fullfile(temporaryDirectory, 'samples.csv');

points = table(["p_left"; "p_center"; "p_right"], ...
    ["vacuum"; "vacuum"; "vacuum"], [-0.25; 0; 0.25], ...
    zeros(3, 1), zeros(3, 1), ...
    'VariableNames', {'sample_id', 'region', 'x_mm', 'y_mm', 'z_mm'});
writetable(points, pointsPath);
caseSpecs = fixture_case_specs();
datasetTagsBefore = string(cell(model.result.dataset.tags()));

samples = export_comsol_stationary_field_samples( ...
    model, pointsPath, outputPath, caseSpecs);

testCase.verifyEqual(samples.Properties.VariableNames, ...
    {'sample_id', 'region', 'field_case', 'x_mm', 'y_mm', 'z_mm', ...
    'potential_V', 'Ex_V_per_m', 'Ey_V_per_m', 'Ez_V_per_m'});
testCase.verifyEqual(height(samples), 6);
testCase.verifyEqual(samples.field_case, ...
    ["differential"; "differential"; "differential"; ...
    "static"; "static"; "static"]);
testCase.verifyEqual(samples.potential_V, ...
    [0.25; 0.5; 0.75; 0.5; 1.0; 1.5], AbsTol=1e-8);
testCase.verifyEqual(samples.Ex_V_per_m, ...
    [-1000; -1000; -1000; -2000; -2000; -2000], AbsTol=1e-5);
testCase.verifyEqual(samples.Ey_V_per_m, zeros(6, 1), AbsTol=1e-8);
testCase.verifyEqual(samples.Ez_V_per_m, zeros(6, 1), AbsTol=1e-8);
testCase.verifyTrue(isfile(outputPath));
testCase.verifyEqual(readtable(outputPath, TextType="string"), samples);
testCase.verifyEqual(string(cell(model.result.dataset.tags())), datasetTagsBefore);
clear cleanup
end

function test_invalid_contracts_fail_before_sampling(testCase)
model = testCase.TestData.Model;
temporaryDirectory = tempname();
mkdir(temporaryDirectory);
cleanup = onCleanup(@() rmdir(temporaryDirectory, 's'));
pointsPath = fullfile(temporaryDirectory, 'points.csv');
outputPath = fullfile(temporaryDirectory, 'samples.csv');

missingRegion = table(["p1"; "p2"], [0; 0.1], [0; 0], [0; 0], ...
    'VariableNames', {'sample_id', 'x_mm', 'y_mm', 'z_mm'});
writetable(missingRegion, pointsPath);
testCase.verifyError(@() export_comsol_stationary_field_samples( ...
    model, pointsPath, outputPath, fixture_case_specs()), ...
    "multipole:stationaryFieldSamples:InvalidPointsColumns");

duplicateIds = table(["p1"; "p1"], ["vacuum"; "vacuum"], ...
    [0; 0.1], [0; 0], [0; 0], ...
    'VariableNames', {'sample_id', 'region', 'x_mm', 'y_mm', 'z_mm'});
writetable(duplicateIds, pointsPath);
testCase.verifyError(@() export_comsol_stationary_field_samples( ...
    model, pointsPath, outputPath, fixture_case_specs()), ...
    "multipole:stationaryFieldSamples:DuplicateSampleId");

validPoints = duplicateIds;
validPoints.sample_id = ["p1"; "p2"];
writetable(validPoints, pointsPath);
duplicateCases = fixture_case_specs();
duplicateCases(2).case_id = duplicateCases(1).case_id;
testCase.verifyError(@() export_comsol_stationary_field_samples( ...
    model, pointsPath, outputPath, duplicateCases), ...
    "multipole:stationaryFieldSamples:FieldCaseSet");

sharedSolutionCases = fixture_case_specs();
sharedSolutionCases(2).solution_tag = sharedSolutionCases(1).solution_tag;
sharedSolutionSamples = export_comsol_stationary_field_samples( ...
    model, pointsPath, outputPath, sharedSolutionCases);
testCase.verifyEqual(height(sharedSolutionSamples), 4);
clear cleanup
end

function solve_fixture_case(model, label, voltage)
model.param.set('fixture_drive', voltage);
studyTag = ['std_fixture_' label];
solutionTag = ['sol_fixture_' label];
study = model.study.create(studyTag);
stationary = study.create('stat', 'Stationary');
stationary.setEntry('activate', 'es', true);
solution = model.sol.create(solutionTag);
solution.study(studyTag);
solution.createAutoSequence(studyTag);
solution.attach(studyTag);
solution.runAll();
end

function caseSpecs = fixture_case_specs()
caseSpecs = struct( ...
    'case_id', {'differential', 'static'}, ...
    'solution_tag', {'sol_fixture_one', 'sol_fixture_two'}, ...
    'potential_expression', {'V', 'V'}, ...
    'Ex_expression', {'es.Ex', 'es.Ex'}, ...
    'Ey_expression', {'es.Ey', 'es.Ey'}, ...
    'Ez_expression', {'es.Ez', 'es.Ez'});
end
