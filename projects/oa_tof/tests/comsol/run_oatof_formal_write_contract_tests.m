reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
addpath(fullfile(projectRoot, 'cad'));
paths = oatof_paths();
formalModel = fullfile(paths.comsolFormalDir, 'oa_tof__model.mph');
formalCad = paths.cadFormalDir;
assert(isfile(formalModel), 'Formal COMSOL model is missing: %s', formalModel);

previousTransaction = getenv('OATOF_PROMOTION_TRANSACTION');
cleanupEnvironment = onCleanup(@() setenv( ...
    'OATOF_PROMOTION_TRANSACTION', previousTransaction));
setenv('OATOF_PROMOTION_TRANSACTION', '');

comsolRejected = catches_error( ...
    @() run_oatof_model(OutputModelPath=string(formalModel)), ...
    'Normal COMSOL runs may write only under runs or scratch');
cadRejected = catches_error( ...
    @() export_oatof_cad_step( ...
        string(formalModel), string(formalCad), "export"), ...
    'Formal writes require OATOF_PROMOTION_TRANSACTION');
assert(comsolRejected, 'Normal COMSOL entry accepted a Formal destination.');
assert(cadRejected, 'Normal CAD entry accepted a Formal destination.');

transactionPath = string(tempname) + ".json";
cleanupTransaction = onCleanup(@() delete_if_present(transactionPath));
transaction = struct( ...
    'schema_version', 1, ...
    'role', 'oa_tof_formal_promotion_transaction', ...
    'project', 'oa_tof', ...
    'status', 'authorized', ...
    'authorization_id', 'matlab_contract_test', ...
    'destinations', struct( ...
        'comsol_model', formalModel, ...
        'cad_root', formalCad));
fid = fopen(transactionPath, 'w');
assert(fid >= 0, 'Could not create promotion transaction fixture.');
fwrite(fid, jsonencode(transaction), 'char');
fclose(fid);
setenv('OATOF_PROMOTION_TRANSACTION', transactionPath);

authorizedComsol = oatof_assert_formal_write_authorized( ...
    formalModel, 'comsol_model');
authorizedCad = oatof_assert_formal_write_authorized(formalCad, 'cad_root');
assert(strcmp(authorizedComsol.authorization_id, 'matlab_contract_test'));
assert(strcmp(authorizedCad.authorization_id, 'matlab_contract_test'));
destinationMismatchRejected = catches_error( ...
    @() oatof_assert_formal_write_authorized( ...
        fullfile(paths.comsolFormalDir, 'other.mph'), 'comsol_model'), ...
    'Promotion destination differs from the authorized exact path');
assert(destinationMismatchRejected, ...
    'Promotion transaction authorized a non-exact destination.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanupReport = onCleanup(@() fclose(fid));
fprintf(fid, 'NORMAL_COMSOL_FORMAL_WRITE_REJECTED=1\n');
fprintf(fid, 'NORMAL_CAD_FORMAL_WRITE_REJECTED=1\n');
fprintf(fid, 'PROMOTION_COMSOL_EXACT_DESTINATION_AUTHORIZED=1\n');
fprintf(fid, 'PROMOTION_CAD_EXACT_DESTINATION_AUTHORIZED=1\n');
fprintf(fid, 'PROMOTION_DESTINATION_MISMATCH_REJECTED=1\n');
fprintf(fid, 'STATUS=PASS\n');
clear cleanupReport cleanupTransaction cleanupEnvironment

function matched = catches_error(operation, messageFragment)
matched = false;
try
    operation();
catch exception
    matched = contains(exception.message, messageFragment);
end
end

function delete_if_present(path)
if isfile(path), delete(path); end
end
