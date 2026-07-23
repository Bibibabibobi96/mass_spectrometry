function result = ms_export_oatof_to_solidworks(modelPath, outputDir, visibleSolidWorks)
%MS_EXPORT_OATOF_TO_SOLIDWORKS Export physical oa-TOF solids to an assembly.
%
% No solve is run and the source MPH is never overwritten.  The output is a
% Each physical COMSOL solid becomes one imported-body SLDPRT.  Those parts
% are inserted at their preserved global origin into one SLDASM; the imported
% geometry is directly editable but cannot recreate COMSOL feature history.

    arguments
        modelPath (1,1) string = ""
        outputDir (1,1) string = ""
        visibleSolidWorks (1,1) logical = false
    end

    thisDir = fileparts(mfilename('fullpath'));
    componentRoot = fileparts(thisDir);
    addpath(componentRoot);
    paths = oatof_paths();
    addpath(thisDir, paths.commonDir);
    if strlength(modelPath) == 0
        modelPath = fullfile(paths.comsolFormalDir, ...
            "oa_tof__model.mph");
    end
    assert(strlength(outputDir)>0, ...
        ['outputDir is required; ordinary CAD export cannot default to ' ...
         'Formal. Use an explicit promotion transaction for Formal CAD.']);
    formalCad = string(java.io.File(paths.cadFormalDir).getCanonicalPath());
    resolvedOutput = string(java.io.File(char(outputDir)).getCanonicalPath());
    if startsWith(lower(resolvedOutput),lower(formalCad+filesep)) || ...
            strcmpi(resolvedOutput,formalCad)
        oatof_assert_formal_write_authorized(resolvedOutput,'cad_root');
    end

    exportResult = export_oatof_cad_step(modelPath, outputDir);
    partStepPaths = string(exportResult.partStepPaths);
    [~, partBases, ~] = fileparts(partStepPaths);
    [~, modelBase, ~] = fileparts(modelPath);
    partsDir = fullfile(outputDir, string(modelBase) + "_parts");
    partPaths = fullfile(partsDir, partBases + ".sldprt");
    assemblyPath = fullfile(outputDir, string(modelBase) + "_physical_components.sldasm");
    solidWorksResult = import_step_to_solidworks( ...
        partStepPaths, partPaths, visibleSolidWorks, assemblyPath, ...
        exportResult.partTranslationsMm);

    result = struct('export', exportResult, 'solidWorks', solidWorksResult);
    reportPath = fullfile(outputDir, "oaTOF_solidworks_export_report.json");
    fid = fopen(reportPath, 'w');
    assert(fid ~= -1, 'oatofCadExport:ReportWriteFailed', 'Cannot write "%s".', reportPath);
    cleanupFile = onCleanup(@() fclose(fid));
    fwrite(fid, jsonencode(result), 'char');
    result.reportPath = char(reportPath);
end
