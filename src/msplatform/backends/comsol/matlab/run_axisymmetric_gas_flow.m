function result = run_axisymmetric_gas_flow(sciencePath, numericsPath, geometryPath, outputDir, resumeModelPath)
%RUN_AXISYMMETRIC_GAS_FLOW Fail-closed explicit COMSOL gas-flow operation.
arguments
    sciencePath (1, 1) string
    numericsPath (1, 1) string
    geometryPath (1, 1) string
    outputDir (1, 1) string
    resumeModelPath (1, 1) string = ""
end
if ~isfolder(outputDir)
    mkdir(outputDir);
end
reportPath = fullfile(outputDir, "comsol_run_report.txt");
writeReport(reportPath, compose("STATUS=RUNNING\nTASK=axisymmetric_gas_flow\n"));
try
    result = build_and_solve_axisymmetric_gas_flow( ...
        sciencePath, numericsPath, geometryPath, outputDir, resumeModelPath);
    report = compose("STATUS=PASS\nMODEL=%s\nFIELD=%s\nMETADATA=%s\n", ...
        result.model_path, result.field_csv_path, result.field_metadata_path);
    writeReport(reportPath, report);
catch exception
    report = compose("STATUS=FAIL\nIDENTIFIER=%s\nMESSAGE=%s\n", ...
        exception.identifier, exception.message);
    writeReport(reportPath, report);
    rethrow(exception);
end

end

function writeReport(path, content)
handle = fopen(path, "w", "n", "UTF-8");
if handle < 0
    error("GasFlow:ReportWrite", "Cannot create run report: %s", path);
end
cleanup = onCleanup(@() fclose(handle)); %#ok<NASGU>
fwrite(handle, content, "char");
end
