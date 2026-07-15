function result = import_step_to_solidworks(stepPaths, sldprtPaths, visible, assemblyPath, translationsMm)
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
        translationsMm double = zeros(0, 3)
    end

    assert(numel(stepPaths) == numel(sldprtPaths), ...
        'oatofCadExport:PartCountMismatch', ...
        'The STEP and SLDPRT path counts must match.');
    assert(all(isfile(stepPaths)), 'oatofCadExport:MissingStep', ...
        'One or more STEP files are missing.');
    if isempty(translationsMm)
        translationsMm = zeros(numel(stepPaths), 3);
    end
    assert(isequal(size(translationsMm), [numel(stepPaths), 3]), ...
        'oatofCadExport:TranslationCountMismatch', ...
        'One XYZ translation in mm is required for every STEP file.');
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
    % A five-ring model fit on one command line, but parameterized ring
    % counts can exceed Windows' command-length limit. Pass the complete
    % import manifest through a temporary JSON file instead of repeating
    % every STEP/SLDPRT path as a command-line option.
    payload = struct();
    payload.stepPaths = cellstr(stepPaths);
    payload.sldprtPaths = cellstr(sldprtPaths);
    payload.translationsMm = translationsMm;
    payload.assemblyPath = char(assemblyPath);
    manifestPath = string([tempname '.json']);
    fid = fopen(manifestPath, 'w');
    assert(fid ~= -1, 'oatofCadExport:ManifestWriteFailed', ...
        'Cannot write temporary SolidWorks import manifest "%s".', manifestPath);
    cleanupManifest = onCleanup(@() delete_if_present(manifestPath));
    fwrite(fid, jsonencode(payload), 'char');
    fclose(fid);
    command = sprintf('python "%s" --manifest "%s"%s', ...
        scriptPath, manifestPath, visibleArg);
    [status, output] = system(command);
    if status ~= 0
        error('oatofCadExport:SolidWorksImportFailed', '%s', output);
    end
    result = jsondecode(output);
end

function delete_if_present(pathValue)
    if isfile(pathValue)
        delete(pathValue);
    end
end
