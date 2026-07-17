function export_fem_unit_rf_field()
%EXPORT_FEM_UNIT_RF_FIELD Sample COMSOL's own FEM unit field on the PA grid.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
try
    testDir = fileparts(mfilename('fullpath'));
    projectRoot = fileparts(fileparts(testDir));
    addpath(projectRoot);
    paths = rf_quadrupole_paths();
    modelPath = fullfile(paths.comsolCandidateDir, 'rf_quadrupole_transport_no_collision_simion_reference.mph');
    inputPath = fullfile(paths.simionResultsDir, 'unit_rf_field_pa_grid.csv');
    outputPath = fullfile(paths.comsolResultsDir, 'unit_rf_field_fem_grid.csv');
    assert(isfile(modelPath) && isfile(inputPath), 'FEM model or SIMION coordinate grid is missing.');

    import com.comsol.model.util.*
    tag = 'RFQuadFemFieldExport';
    if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
    model = mphload(modelPath, tag);
    points = readmatrix(inputPath, 'NumHeaderLines', 1);
    coordinates = points(:,1:3).';
    ex = mphinterp(model, 'es.Ex', 'coord', coordinates, 'dataset', 'dset1').';
    ey = mphinterp(model, 'es.Ey', 'coord', coordinates, 'dataset', 'dset1').';
    ez = mphinterp(model, 'es.Ez', 'coord', coordinates, 'dataset', 'dset1').';
    valid = isfinite(ex) & isfinite(ey) & isfinite(ez);
    assert(nnz(valid) > 1000, 'Too few vacuum points remain in FEM field export.');
    tableOut = array2table([points(valid,1:3),ex(valid),ey(valid),ez(valid)], 'VariableNames', ...
        {'x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m'});
    writetable(tableOut, outputPath);
    ModelUtil.remove(tag);
    fid = fopen(reportPath, 'w'); fprintf(fid, 'STATUS=PASS\nPOINTS=%d\n', nnz(valid)); fclose(fid);
catch ME
    if ~isempty(reportPath), fid=fopen(reportPath,'w'); fprintf(fid,'STATUS=FAIL\nERROR=%s\n',ME.message); fclose(fid); end
    rethrow(ME)
end
end
