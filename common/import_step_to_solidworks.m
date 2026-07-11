function result = import_step_to_solidworks(stepPaths, sldprtPaths, visible, assemblyPath)
%IMPORT_STEP_TO_SOLIDWORKS Save STEP solids as SLDPRT files and an assembly.
%
% Uses a Python/pywin32 COM bridge (not UI automation).  PowerShell's
% late-bound COM dispatch is not reliable with the co-installed 2013 and
% 2022 SolidWorks type libraries, while pywin32 connects cleanly to the
% version-specific SolidWorks 2022 automation server.

    arguments
        stepPaths (1,:) string
        sldprtPaths (1,:) string
        visible (1,1) logical = false
        assemblyPath (1,1) string = ""
    end

    assert(numel(stepPaths) == numel(sldprtPaths), ...
        'oatofCadExport:PartCountMismatch', ...
        'The STEP and SLDPRT path counts must match.');
    assert(all(isfile(stepPaths)), 'oatofCadExport:MissingStep', ...
        'One or more STEP files are missing.');
    for k = 1:numel(sldprtPaths)
        outputFolder = fileparts(sldprtPaths(k));
        if ~isfolder(outputFolder)
            mkdir(outputFolder);
        end
    end
    if strlength(assemblyPath) > 0
        assemblyFolder = fileparts(assemblyPath);
        if ~isfolder(assemblyFolder)
            mkdir(assemblyFolder);
        end
    end

    scriptPath = fullfile(fileparts(mfilename('fullpath')), 'import_step_to_solidworks.py');
    visibleArg = "";
    if visible
        visibleArg = " --visible";
    end
    command = sprintf('python "%s"', scriptPath);
    for k = 1:numel(stepPaths)
        command = sprintf('%s --step "%s" --sldprt "%s"', ...
            command, stepPaths(k), sldprtPaths(k));
    end
    if strlength(assemblyPath) > 0
        command = sprintf('%s --assembly "%s"', command, assemblyPath);
    end
    command = sprintf('%s%s', command, visibleArg);
    [status, output] = system(command);
    if status ~= 0
        error('oatofCadExport:SolidWorksImportFailed', '%s', output);
    end
    result = jsondecode(output);
end
