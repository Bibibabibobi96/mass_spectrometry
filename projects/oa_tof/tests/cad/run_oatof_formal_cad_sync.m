reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
addpath(paths.cadDir, paths.commonSolidWorksDir);
mphstart(2036);
import com.comsol.model.util.*

modelPath = fullfile(paths.comsolFormalDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');
outputDir = paths.cadFormalDir;
assert(isfile(modelPath), 'Formal COMSOL model is missing: %s', modelPath);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\n', modelPath);
fprintf(fid, 'OUTPUT_DIR=%s\n', outputDir);

try
    result = ms_export_oatof_to_solidworks(modelPath, outputDir, false);
    exportResult = result.export;
    sw = result.solidWorks;
    assembly = sw.assembly;

    assert(isfile(exportResult.stepPath), 'Combined STEP was not written.');
    assert(isfile(exportResult.manifestPath), 'CAD manifest was not written.');
    assert(all(isfile(string(exportResult.partStepPaths))), ...
        'One or more individual STEP files are missing.');
    assert(sw.partCount == exportResult.exportedObjectCount, ...
        'SolidWorks part count does not match exported COMSOL object count.');
    assert(assembly.componentCount == sw.partCount, ...
        'SolidWorks assembly component count does not match part count.');
    assert(isfile(assembly.sldasmPath), 'SolidWorks assembly was not written.');
    assert(all([sw.parts.loadErrors] == 0), ...
        'At least one STEP import reported a load error.');
    assert(all([sw.parts.loadWarnings] == 0), ...
        'At least one STEP import reported a load warning.');
    assert(all([sw.parts.saveErrors] == 0), ...
        'At least one SLDPRT save reported an error.');
    assert(all([sw.parts.saveWarnings] == 0), ...
        'At least one SLDPRT save reported a warning.');
    assert(assembly.saveErrors == 0 && assembly.saveWarnings == 0, ...
        'SLDASM save reported an error or warning.');
    assert(startsWith(string(sw.solidWorksRevision), '30.'), ...
        'Formal CAD sync did not use SolidWorks 2022: revision %s', ...
        string(sw.solidWorksRevision));

    expectedCentersMm = exportResult.partTranslationsMm;
    actualCentersMm = assembly.componentWorldCentersM * 1000;
    centerErrorMm = max(abs(actualCentersMm-expectedCentersMm), [], 'all');
    assert(centerErrorMm <= 1e-6, ...
        'Assembly world-center error %.12g mm exceeds tolerance.', centerErrorMm);

    fprintf(fid, 'COMBINED_STEP=%s\n', exportResult.stepPath);
    fprintf(fid, 'MANIFEST=%s\n', exportResult.manifestPath);
    fprintf(fid, 'BODY_FEATURE_COUNT=%d\n', exportResult.bodyFeatureCount);
    fprintf(fid, 'EXPORTED_OBJECT_COUNT=%d\n', exportResult.exportedObjectCount);
    fprintf(fid, 'SOLIDWORKS_REVISION=%s\n', string(sw.solidWorksRevision));
    fprintf(fid, 'PART_COUNT=%d\n', sw.partCount);
    fprintf(fid, 'ASSEMBLY=%s\n', assembly.sldasmPath);
    fprintf(fid, 'ASSEMBLY_COMPONENT_COUNT=%d\n', assembly.componentCount);
    fprintf(fid, 'MAX_WORLD_CENTER_ERROR_MM=%.12g\n', centerErrorMm);
    fprintf(fid, 'ASSEMBLY_SAVE_ERRORS=%d\n', assembly.saveErrors);
    fprintf(fid, 'ASSEMBLY_SAVE_WARNINGS=%d\n', assembly.saveWarnings);
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
