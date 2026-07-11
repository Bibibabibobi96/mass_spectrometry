function result = ms_export_oatof_to_solidworks(modelPath, outputDir, visibleSolidWorks)
%MS_EXPORT_OATOF_TO_SOLIDWORKS Export the official oa-TOF model to SLDPRT.
%
% No solve is run and the source MPH is never overwritten.  The output is a
% SolidWorks imported-body part: editable with direct-edit features, but it
% cannot recreate the original COMSOL feature or physics history.

    arguments
        modelPath (1,1) string = "C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\project_oaTOF\MS_oaTOF_TwoStageRingStackReflectron_Final.mph"
        outputDir (1,1) string = "C:\Users\Liao\PycharmProjects\PythonProject\cad_exports\project_oaTOF"
        visibleSolidWorks (1,1) logical = false
    end

    thisDir = fileparts(mfilename('fullpath'));
    addpath(fullfile(fileparts(thisDir), 'common'));

    exportResult = export_oatof_cad_step(modelPath, outputDir);
    [~, stepBase, ~] = fileparts(exportResult.stepPath);
    sldprtPath = fullfile(outputDir, string(stepBase) + ".sldprt");
    solidWorksResult = import_step_to_solidworks(exportResult.stepPath, sldprtPath, visibleSolidWorks);

    result = struct('export', exportResult, 'solidWorks', solidWorksResult);
    reportPath = fullfile(outputDir, "oaTOF_solidworks_export_report.json");
    fid = fopen(reportPath, 'w');
    assert(fid ~= -1, 'oatofCadExport:ReportWriteFailed', 'Cannot write "%s".', reportPath);
    cleanupFile = onCleanup(@() fclose(fid));
    fwrite(fid, jsonencode(result), 'char');
    result.reportPath = char(reportPath);
end
