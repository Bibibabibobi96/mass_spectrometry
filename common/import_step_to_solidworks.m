function result = import_step_to_solidworks(stepPath, sldprtPath, visible)
%IMPORT_STEP_TO_SOLIDWORKS Import a STEP file and save a native SLDPRT.
%
% Uses a Python/pywin32 COM bridge (not UI automation).  PowerShell's
% late-bound COM dispatch is not reliable with the co-installed 2013 and
% 2022 SolidWorks type libraries, while pywin32 connects cleanly to the
% version-specific SolidWorks 2022 automation server.

    arguments
        stepPath (1,1) string {mustBeFile}
        sldprtPath (1,1) string
        visible (1,1) logical = false
    end

    outputFolder = fileparts(sldprtPath);
    if ~isfolder(outputFolder)
        mkdir(outputFolder);
    end

    scriptPath = fullfile(fileparts(mfilename('fullpath')), 'import_step_to_solidworks.py');
    visibleArg = "";
    if visible
        visibleArg = " --visible";
    end
    command = sprintf('python "%s" --step "%s" --sldprt "%s"%s', ...
        scriptPath, stepPath, sldprtPath, visibleArg);
    [status, output] = system(command);
    if status ~= 0
        error('oatofCadExport:SolidWorksImportFailed', '%s', output);
    end
    result = jsondecode(output);
end
