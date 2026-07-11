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

    [~, modelBase, ~] = fileparts(modelPath);
    stepPath = fullfile(outputDir, modelBase + "_physical_components.step");
    csvPath = fullfile(outputDir, modelBase + "_physical_components_manifest.csv");

    exportFeature = geom.export();
    exportFeature.selection().init();
    exportFeature.selection().set(cellstr(objectNames));
    exportFeature.setType('step');
    exportFeature.setLengthUnitSTEP('mm');
    geom.export(char(stepPath));

    exportedObjects = table(objectFeatureTags, objectNames, ...
        'VariableNames', {'FeatureTag', 'ObjectName'});
    writetable(exportedObjects, csvPath);

    result = struct( ...
        'modelPath', char(modelPath), ...
        'stepPath', char(stepPath), ...
        'manifestPath', char(csvPath), ...
        'format', 'STEP AP203', ...
        'unit', 'mm', ...
        'bodyFeatureCount', height(manifest), ...
        'exportedObjectCount', height(exportedObjects), ...
        'excluded', {{'vacuum domains', 'grid1/grid2/entgrid/midgrid ideal internal boundaries', 'physics, mesh, studies, and results'}});
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
