function test_simion_unit_field_interpolation()
%TEST_SIMION_UNIT_FIELD_INTERPOLATION Verify a GUI-persistent PA field import.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
try
projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
paths = rf_quadrupole_paths();
fieldPath = fullfile(paths.simionResultsDir, 'unit_rf_field_ex.csv');
assert(isfile(fieldPath), 'SIMION PA unit-field CSV is missing: %s', fieldPath);

import com.comsol.model.*
import com.comsol.model.util.*
tag = 'RFQuadPaFieldImportTest';
if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
model = ModelUtil.create(tag);
field = model.func.create('simion_ex_unit', 'Interpolation');
field.label('SIMION PA unit RF Ex field');
field.set('source', 'file');
field.set('filename', fieldPath);
field.set('nargs', '3');
field.set('struct', 'spreadsheet');
field.set('argunit', {'mm','mm','mm'});
field.set('fununit', 'V/m');
field.importData();
assert(~isempty(char(field.getString('importedname'))), 'PA field import did not retain an imported file name.');
importedStruct = char(field.getString('importedstruct'));
ModelUtil.remove(tag);
fprintf('STATUS=PASS FUNCTION=simion_ex_unit ARGS=3 IMPORTED_STRUCT=%s\n', importedStruct);
fid = fopen(reportPath, 'w'); fprintf(fid, 'STATUS=PASS\n'); fclose(fid);
catch ME
    if ~isempty(reportPath)
        fid = fopen(reportPath, 'w'); fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ME.message); fclose(fid);
    end
    rethrow(ME)
end
end
