function result = export_oatof_cad_step(modelPath, outputDir, executionMode)
%EXPORT_OATOF_CAD_STEP Export oa-TOF physical solids from an MPH to STEP.
%
% The source MPH is opened read-only in COMSOL server memory and is never
% saved.  STEP AP203 is used because COMSOL 6.4 emits Parasolid v37, which
% is not a dependable interchange target for the formal SolidWorks 2022 workflow.
% executionMode='load_only' stops after loading the MPH and discovering all
% exportable geometry objects; it creates no output directory or CAD file.

    arguments
        modelPath (1,1) string {mustBeFile}
        outputDir (1,1) string
        executionMode (1,1) string {mustBeMember(executionMode, ["export", "load_only"])} = "export"
    end

    if executionMode == "export" && ~isfolder(outputDir)
        mkdir(outputDir);
    end

    require_comsol_livelink();
    modelTag = 'oatof_cad_export';
    remove_model_if_present(modelTag);
    cleanupModel = onCleanup(@() remove_model_if_present(modelTag));

    model = mphload(char(modelPath), modelTag);
    geom = model.component('comp1').geom('geom1');
    manifest = oatof_cad_export_manifest();
    manifest = expand_reflectron_ring_manifest(manifest, geom);

    [~, modelBase, ~] = fileparts(modelPath);
    objectNames = strings(0,1);
    objectFeatureTags = strings(0,1);
    for k = 1:height(manifest)
        featureTag = char(manifest.FeatureTag(k));
        featureObjects = string(cell(geom.feature(featureTag).objectNames()));
        if isempty(featureObjects)
            error('oatofCadExport:MissingGeometryObject', ...
                'Feature "%s" has no exportable geometry object.', featureTag);
        end
        objectNames = [objectNames; featureObjects(:)]; %#ok<AGROW>
        objectFeatureTags = [objectFeatureTags; repmat(manifest.FeatureTag(k), numel(featureObjects), 1)]; %#ok<AGROW>
    end

    if executionMode == "load_only"
        result = struct( ...
            'modelPath', char(modelPath), ...
            'executionMode', char(executionMode), ...
            'modelLoaded', true, ...
            'geometryResolved', true, ...
            'bodyFeatureCount', height(manifest), ...
            'exportableObjectCount', numel(objectNames), ...
            'stepExported', false, ...
            'formalAssetModified', false);
        return;
    end

    stepPath = fullfile(outputDir, modelBase + "_physical_components.step");
    csvPath = fullfile(outputDir, modelBase + "_physical_components_manifest.csv");
    partStepDir = fullfile(outputDir, modelBase + "_individual_steps");
    if ~isfolder(partStepDir)
        mkdir(partStepDir);
    end

    exportFeature = geom.export();
    exportFeature.selection().init();
    exportFeature.selection().set(cellstr(objectNames));
    exportFeature.setType('step');
    exportFeature.setLengthUnitSTEP('mm');
    geom.export(char(stepPath));

    partStepPaths = strings(numel(objectNames), 1);
    partTranslationsMm = zeros(numel(objectNames), 3);
    for k = 1:numel(objectNames)
        partStepPaths(k) = fullfile(partStepDir, ...
            sprintf('%02d_%s.step', k, objectFeatureTags(k)));
        exportFeature.selection().set({char(objectNames(k))});
        geom.export(char(partStepPaths(k)));
        partTranslationsMm(k, :) = export_feature_center_mm( ...
            model, geom, char(objectFeatureTags(k)));
    end

    exportedObjects = table(objectFeatureTags, objectNames, partStepPaths, ...
        partTranslationsMm(:, 1), partTranslationsMm(:, 2), partTranslationsMm(:, 3), ...
        'VariableNames', {'FeatureTag', 'ObjectName', 'PartStepPath', 'CenterX_mm', 'CenterY_mm', 'CenterZ_mm'});
    writetable(exportedObjects, csvPath);

    result = struct( ...
        'modelPath', char(modelPath), ...
        'executionMode', char(executionMode), ...
        'stepPath', char(stepPath), ...
        'manifestPath', char(csvPath), ...
        'format', 'STEP AP203', ...
        'unit', 'mm', ...
        'bodyFeatureCount', height(manifest), ...
        'exportedObjectCount', height(exportedObjects), ...
        'partStepPaths', {cellstr(partStepPaths)}, ...
        'partTranslationsMm', partTranslationsMm, ...
        'excluded', {{'vacuum domains', 'grid1/grid2/entgrid/midgrid ideal internal boundaries', 'physics, mesh, studies, and results'}});
end

function manifest = expand_reflectron_ring_manifest(manifest, geom)
    % Ring counts are parameterized in the production model. The original
    % static manifest only represented the then-default 5/5 stack and
    % silently omitted additional rings from CAD export. Discover exactly
    % the completed Difference features ring1_<integer>/ring2_<integer>,
    % natural-sort them, and place them between the flight tube and the
    % backplate just as the fixed manifest does.
    allTags = string(cell(geom.feature.tags()));
    ring1Tags = natural_ring_tags(allTags, 'ring1_');
    ring2Tags = natural_ring_tags(allTags, 'ring2_');
    if isempty(ring1Tags) || isempty(ring2Tags)
        error('oatofCadExport:MissingReflectronRings', ...
            'No completed ring1/ring2 Difference features found for CAD export.');
    end

    isStageRing = startsWith(manifest.FeatureTag, 'ring1_') | startsWith(manifest.FeatureTag, 'ring2_');
    fixedManifest = manifest(~isStageRing, :);
    insertAt = find(fixedManifest.FeatureTag == "backplate", 1, 'first');
    prefix = fixedManifest(1:insertAt-1, :);
    suffix = fixedManifest(insertAt:end, :);
    stage1 = table(ring1Tags(:), repmat("reflectron_stage1_ring", numel(ring1Tags), 1), ...
        'VariableNames', fixedManifest.Properties.VariableNames);
    stage2 = table(ring2Tags(:), repmat("reflectron_stage2_ring", numel(ring2Tags), 1), ...
        'VariableNames', fixedManifest.Properties.VariableNames);
    manifest = [prefix; stage1; stage2; suffix];
end

function tags = natural_ring_tags(allTags, prefix)
    matches = allTags(startsWith(allTags, prefix));
    numbers = NaN(size(matches));
    for k = 1:numel(matches)
        token = regexp(char(matches(k)), ['^' regexptranslate('escape', prefix) '(\d+)$'], 'tokens', 'once');
        if ~isempty(token)
            numbers(k) = str2double(token{1});
        end
    end
    valid = ~isnan(numbers);
    matches = matches(valid);
    numbers = numbers(valid);
    [~, order] = sort(numbers);
    tags = matches(order);
end

function centerMm = export_feature_center_mm(model, geom, featureTag)
    anchorTag = featureTag;
    if strcmp(featureTag, 'accelshield')
        anchorTag = 'accelshieldO';
    elseif strcmp(featureTag, 'flighttubewall')
        anchorTag = 'flighttubewallO';
    elseif startsWith(featureTag, 'accelring_') || ...
            startsWith(featureTag, 'ring1_') || startsWith(featureTag, 'ring2_')
        anchorTag = [featureTag 'O'];
    end

    feature = geom.feature(anchorTag);
    posExpr = feature.getStringArray('pos');
    posMm = zeros(1, 3);
    for d = 1:3
        posMm(d) = evaluate_geometry_length_mm(model, posExpr(d));
    end

    featureType = char(feature.getType());
    switch featureType
        case 'Block'
            sizeExpr = feature.getStringArray('size');
            sizeMm = zeros(1, 3);
            for d = 1:3
                sizeMm(d) = evaluate_geometry_length_mm(model, sizeExpr(d));
            end
            centerMm = posMm + sizeMm/2;
        case 'Cylinder'
            heightMm = evaluate_geometry_length_mm(model, feature.getString('h'));
            centerMm = posMm + [0, 0, heightMm/2];
        otherwise
            error('oatofCadExport:UnsupportedPlacementFeature', ...
                'Feature "%s" has unsupported placement type "%s".', anchorTag, featureType);
    end
end

function valueMm = evaluate_geometry_length_mm(model, expression)
    expression = char(expression);
    literalValue = str2double(expression);
    if ~isnan(literalValue)
        % Geometry features interpret unitless literal coordinates and sizes
        % in the geometry length unit (mm for this model).
        valueMm = literalValue;
    else
        valueMm = model.param.evaluate(expression, 'mm');
    end
end

function remove_model_if_present(modelTag)
    try
        com.comsol.model.util.ModelUtil.remove(modelTag);
    catch
        % The tag is absent, or the server has already released it.
    end
end

function require_comsol_livelink()
    if exist('mphload', 'file') == 0
        error('oatofCadExport:LiveLinkUnavailable', ...
            ['COMSOL LiveLink is unavailable. Run this task through ', ...
             'common/comsol/run_comsol_r2025b.ps1.']);
    end
end
