function samples = export_comsol_stationary_field_samples(model, pointsCsv, outputCsv, caseSpecs)
%EXPORT_COMSOL_STATIONARY_FIELD_SAMPLES Export governed stationary-field samples.
%   SAMPLES = EXPORT_COMSOL_STATIONARY_FIELD_SAMPLES(MODEL, POINTSCSV,
%   OUTPUTCSV, CASESPECS) reads a CSV with the exact columns sample_id,
%   region, x_mm, y_mm and z_mm. CASESPECS is a nonempty struct array with
%   the exact fields case_id, solution_tag, potential_expression,
%   Ex_expression, Ey_expression and Ez_expression.
%
%   Each case is evaluated at the same model-geometry coordinates through
%   a unique temporary Solution dataset bound to the declared solution.
%   Temporary datasets are removed on success and failure. The returned
%   table is also written to OUTPUTCSV.

pointsPath = require_path(pointsCsv, "points CSV");
outputPath = require_path(outputCsv, "output CSV");
if ~isfile(pointsPath)
    error("multipole:stationaryFieldSamples:MissingPointsCsv", ...
        "The points CSV does not exist: %s", pointsPath);
end

requiredPointColumns = {'sample_id', 'region', 'x_mm', 'y_mm', 'z_mm'};
options = detectImportOptions(pointsPath, VariableNamingRule="preserve");
if ~isequal(options.VariableNames, requiredPointColumns)
    error("multipole:stationaryFieldSamples:InvalidPointsColumns", ...
        "The points CSV columns must be exactly: %s.", ...
        strjoin(requiredPointColumns, ", "));
end
options = setvartype(options, {'sample_id', 'region'}, 'string');
options = setvartype(options, {'x_mm', 'y_mm', 'z_mm'}, 'double');
points = readtable(pointsPath, options);
if height(points) == 0
    error("multipole:stationaryFieldSamples:EmptyPoints", ...
        "The points CSV must contain at least one sample.");
end

sampleIds = normalize_identifier_column(points.sample_id, "sample_id");
if numel(unique(sampleIds)) ~= numel(sampleIds)
    error("multipole:stationaryFieldSamples:DuplicateSampleId", ...
        "The points CSV sample_id values must be unique.");
end
regions = normalize_text_column(points.region, "region");
coordinates = validate_coordinates(points);
cases = validate_case_specs(model, caseSpecs);
geometryLengthUnit = string(model.component('comp1').geom('geom1').lengthUnit());
if geometryLengthUnit ~= "mm"
    error("multipole:stationaryFieldSamples:GeometryUnit", ...
        "The governed comp1/geom1 geometry length unit must be mm.");
end

pointCount = height(points);
caseCount = numel(cases);
rowCount = pointCount*caseCount;
outputSampleIds = repmat(sampleIds, caseCount, 1);
outputRegions = repmat(regions, caseCount, 1);
fieldCases = strings(rowCount, 1);
potentialV = nan(rowCount, 1);
exVPerM = nan(rowCount, 1);
eyVPerM = nan(rowCount, 1);
ezVPerM = nan(rowCount, 1);

for caseIndex = 1:caseCount
    firstRow = (caseIndex - 1)*pointCount + 1;
    lastRow = caseIndex*pointCount;
    fieldCases(firstRow:lastRow) = cases(caseIndex).case_id;
    datasetTag = next_temporary_dataset_tag(model, caseIndex);
    expressions = {
        char(cases(caseIndex).potential_expression)
        char(cases(caseIndex).Ex_expression)
        char(cases(caseIndex).Ey_expression)
        char(cases(caseIndex).Ez_expression)
    };
    interpolated = cell(1, numel(expressions));

    try
        dataset = model.result.dataset.create(datasetTag, 'Solution');
        dataset.set('solution', char(cases(caseIndex).solution_tag));
        [interpolated{:}, returnedUnits] = mphinterp(model, expressions, ...
            'coord', coordinates, 'dataset', datasetTag, 'matherr', 'on', ...
            'unit', {'V', 'V/m', 'V/m', 'V/m'});
    catch exception
        remove_temporary_dataset(model, datasetTag);
        rethrow(exception)
    end
    remove_temporary_dataset(model, datasetTag);

    validate_returned_units(returnedUnits, cases(caseIndex).case_id);
    values = validate_interpolated_values(interpolated, pointCount, ...
        cases(caseIndex).case_id);
    potentialV(firstRow:lastRow) = values(:, 1);
    exVPerM(firstRow:lastRow) = values(:, 2);
    eyVPerM(firstRow:lastRow) = values(:, 3);
    ezVPerM(firstRow:lastRow) = values(:, 4);
end

samples = table(outputSampleIds, outputRegions, fieldCases, ...
    repmat(coordinates(1, :).', caseCount, 1), ...
    repmat(coordinates(2, :).', caseCount, 1), ...
    repmat(coordinates(3, :).', caseCount, 1), ...
    potentialV, exVPerM, eyVPerM, ezVPerM, ...
    'VariableNames', {'sample_id', 'region', 'field_case', ...
    'x_mm', 'y_mm', 'z_mm', 'potential_V', ...
    'Ex_V_per_m', 'Ey_V_per_m', 'Ez_V_per_m'});

outputDirectory = fileparts(outputPath);
if strlength(outputDirectory) > 0 && ~isfolder(outputDirectory)
    [created, message] = mkdir(outputDirectory);
    if ~created
        error("multipole:stationaryFieldSamples:OutputDirectory", ...
            "Could not create the output directory: %s", message);
    end
end
writetable(samples, outputPath);
end

function path = require_path(value, label)
if ~(ischar(value) && isrow(value)) && ~(isstring(value) && isscalar(value))
    error("multipole:stationaryFieldSamples:InvalidPath", ...
        "The %s path must be a text scalar.", label);
end
path = string(value);
if ismissing(path) || strlength(strtrim(path)) == 0
    error("multipole:stationaryFieldSamples:InvalidPath", ...
        "The %s path must be nonempty.", label);
end
path = char(path);
end

function values = normalize_identifier_column(column, label)
if ~(isstring(column) || iscellstr(column) || isnumeric(column))
    error("multipole:stationaryFieldSamples:InvalidIdentifier", ...
        "The %s column must contain text or numeric identifiers.", label);
end
values = string(column);
if any(ismissing(values)) || any(strlength(strtrim(values)) == 0)
    error("multipole:stationaryFieldSamples:InvalidIdentifier", ...
        "The %s column must contain nonempty identifiers.", label);
end
if any(values ~= strtrim(values))
    error("multipole:stationaryFieldSamples:InvalidIdentifier", ...
        "The %s column values must be trimmed.", label);
end
values = values(:);
end

function values = normalize_text_column(column, label)
if ~(isstring(column) || iscellstr(column))
    error("multipole:stationaryFieldSamples:InvalidTextColumn", ...
        "The %s column must contain text.", label);
end
values = string(column);
if any(ismissing(values)) || any(strlength(strtrim(values)) == 0)
    error("multipole:stationaryFieldSamples:InvalidTextColumn", ...
        "The %s column must contain nonempty text.", label);
end
if any(values ~= strtrim(values))
    error("multipole:stationaryFieldSamples:InvalidTextColumn", ...
        "The %s column values must be trimmed.", label);
end
values = values(:);
end

function coordinates = validate_coordinates(points)
coordinateNames = {'x_mm', 'y_mm', 'z_mm'};
coordinates = zeros(3, height(points));
for coordinateIndex = 1:numel(coordinateNames)
    name = coordinateNames{coordinateIndex};
    values = points.(name);
    if ~isnumeric(values) || ~isreal(values) || ...
            numel(values) ~= height(points) || any(~isfinite(values))
        error("multipole:stationaryFieldSamples:InvalidCoordinates", ...
            "The %s column must contain one finite real numeric value per sample.", ...
            name);
    end
    coordinates(coordinateIndex, :) = double(values(:)).';
end
end

function cases = validate_case_specs(model, caseSpecs)
requiredFields = {
    'case_id'
    'solution_tag'
    'potential_expression'
    'Ex_expression'
    'Ey_expression'
    'Ez_expression'
};
if ~isstruct(caseSpecs) || isempty(caseSpecs) || ...
        ~isequal(sort(fieldnames(caseSpecs)), sort(requiredFields))
    error("multipole:stationaryFieldSamples:InvalidCaseSpecs", ...
        "Case specs must be a nonempty struct array with exactly the governed fields.");
end

cases = caseSpecs;
textFields = string(requiredFields);
for caseIndex = 1:numel(cases)
    for fieldIndex = 1:numel(textFields)
        fieldName = textFields(fieldIndex);
        cases(caseIndex).(fieldName) = require_text_scalar( ...
            cases(caseIndex).(fieldName), fieldName);
    end
end

caseIds = string({cases.case_id}).';
solutionTags = string({cases.solution_tag}).';
if numel(caseIds) ~= 2 || ~isequal(sort(caseIds), ...
        sort(["differential"; "static"]))
    error("multipole:stationaryFieldSamples:FieldCaseSet", ...
        "Case case_id values must be exactly differential and static.");
end

availableSolutionTags = string(cell(model.sol.tags()));
unknownTags = setdiff(solutionTags, availableSolutionTags);
if ~isempty(unknownTags)
    error("multipole:stationaryFieldSamples:UnknownSolutionTag", ...
        "The declared solution tag does not exist in the model: %s", ...
        strjoin(unknownTags, ", "));
end
end

function validate_returned_units(returnedUnits, caseId)
expectedUnits = ["V", "V/m", "V/m", "V/m"];
actualUnits = string(returnedUnits);
if numel(actualUnits) ~= numel(expectedUnits) || ...
        ~isequal(actualUnits(:), expectedUnits(:))
    error("multipole:stationaryFieldSamples:ReturnedUnits", ...
        "Case %s returned units that differ from V and V/m.", caseId);
end
end

function value = require_text_scalar(value, label)
if ~(ischar(value) && isrow(value)) && ~(isstring(value) && isscalar(value))
    error("multipole:stationaryFieldSamples:InvalidCaseSpecs", ...
        "Case field %s must be a text scalar.", label);
end
value = string(value);
if ismissing(value) || strlength(strtrim(value)) == 0
    error("multipole:stationaryFieldSamples:InvalidCaseSpecs", ...
        "Case field %s must be nonempty.", label);
end
end

function datasetTag = next_temporary_dataset_tag(model, caseIndex)
existingTags = string(cell(model.result.dataset.tags()));
suffix = 0;
while true
    datasetTag = sprintf('tmp_stat_field_%d_%d', caseIndex, suffix);
    if ~any(existingTags == string(datasetTag))
        return
    end
    suffix = suffix + 1;
end
end

function remove_temporary_dataset(model, datasetTag)
existingTags = string(cell(model.result.dataset.tags()));
if any(existingTags == string(datasetTag))
    model.result.dataset.remove(datasetTag);
end
remainingTags = string(cell(model.result.dataset.tags()));
if any(remainingTags == string(datasetTag))
    error("multipole:stationaryFieldSamples:DatasetCleanup", ...
        "The temporary Solution dataset could not be removed: %s", datasetTag);
end
end

function values = validate_interpolated_values(interpolated, pointCount, caseId)
values = zeros(pointCount, numel(interpolated));
for expressionIndex = 1:numel(interpolated)
    column = interpolated{expressionIndex};
    if ~isnumeric(column) || ~isreal(column) || ...
            numel(column) ~= pointCount || any(~isfinite(column))
        error("multipole:stationaryFieldSamples:InvalidInterpolatedValues", ...
            "Case %s returned nonfinite, nonreal or incorrectly sized field samples.", ...
            caseId);
    end
    values(:, expressionIndex) = double(column(:));
end
end
