function result = export_oatof_cad_step(modelPath, outputDir)
%EXPORT_OATOF_CAD_STEP Export oa-TOF physical solids from an MPH to STEP.
%
% The source MPH is opened read-only in COMSOL server memory and is never
% saved.  STEP AP203 is used because COMSOL 6.4 emits Parasolid v37, which
% is not a dependable interchange target for the installed SolidWorks 2013.

    arguments
        modelPath (1,1) string {mustBeFile}
        outputDir (1,1) string
    end

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    ensure_comsol_livelink();
    modelTag = 'oatof_cad_export';
    remove_model_if_present(modelTag);
    cleanupModel = onCleanup(@() remove_model_if_present(modelTag));

    model = mphload(char(modelPath), modelTag);
    geom = model.component('comp1').geom('geom1');
    manifest = oatof_cad_export_manifest();

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

function ensure_comsol_livelink()
    mliPath = 'D:\COMSOL 6.4\COMSOL64\Multiphysics\mli';
    if exist('mphload', 'file') == 0
        addpath(mliPath);
    end
    if exist('mphload', 'file') == 0
        error('oatofCadExport:LiveLinkUnavailable', ...
            'COMSOL LiveLink for MATLAB was not found at "%s".', mliPath);
    end

    try
        mphstart(2036);
    catch exception
        if contains(exception.message, 'Already connected')
            return;
        end
        error('oatofCadExport:ComsolServerUnavailable', ...
            'Cannot connect to comsolmphserver on port 2036: %s', exception.message);
    end
end
