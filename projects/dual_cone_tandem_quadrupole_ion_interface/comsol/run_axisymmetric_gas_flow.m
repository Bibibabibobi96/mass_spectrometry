% RUN_AXISYMMETRIC_GAS_FLOW Fail-closed batch entry point for COMSOL with MATLAB.
scriptPath = string(mfilename("fullpath"));
projectRoot = fileparts(fileparts(scriptPath));
outputDir = string(getenv("DUAL_CONE_GAS_FLOW_OUTPUT_DIR"));
if strlength(outputDir) == 0
    error("GasFlow:MissingOutput", ...
        "DUAL_CONE_GAS_FLOW_OUTPUT_DIR must name an explicit output directory.");
end
if ~isfolder(outputDir)
    mkdir(outputDir);
end
reportPath = fullfile(outputDir, "comsol_run_report.txt");
try
    result = build_and_solve_axisymmetric_gas_flow(projectRoot, outputDir);
    report = compose("STATUS=PASS\nMODEL=%s\nFIELD=%s\nMETADATA=%s\n", ...
        result.model_path, result.field_csv_path, result.field_metadata_path);
    writeReport(reportPath, report);
catch exception
    report = compose("STATUS=FAIL\nIDENTIFIER=%s\nMESSAGE=%s\n", ...
        exception.identifier, exception.message);
    writeReport(reportPath, report);
    rethrow(exception);
end

function writeReport(path, content)
handle = fopen(path, "w", "n", "UTF-8");
if handle < 0
    error("GasFlow:ReportWrite", "Cannot create run report: %s", path);
end
cleanup = onCleanup(@() fclose(handle)); %#ok<NASGU>
fwrite(handle, content, "char");
end
