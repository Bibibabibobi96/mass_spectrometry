reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
modelPath = getenv('OATOF_COMSOL_MODEL_PATH');
assert(~isempty(modelPath) && isfile(modelPath), ...
    'OATOF_COMSOL_MODEL_PATH must name the modular candidate MPH.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
import com.comsol.model.util.*
model = mphload(modelPath, 'OaTofModularGuiCompute');

initialSolutions = joinJavaStrings(model.sol.tags);
assert(model.sol('sol1').isAttached() && model.sol('sol2').isAttached(), ...
    'Persisted solver sequences are not attached to both studies.');
skipCompute = strcmp(getenv('OATOF_SKIP_GUI_COMPUTE'), '1');
if ~skipCompute
    model.study('std1').run;
    afterStatic = joinJavaStrings(model.sol.tags);
    assert(strcmp(afterStatic, initialSolutions), ...
        'GUI std1 Compute generated an unexpected solver sequence.');
    model.study('std2').run;
    afterParticle = joinJavaStrings(model.sol.tags);
    assert(strcmp(afterParticle, initialSolutions), ...
        'GUI std2 Compute generated an unexpected solver sequence.');
    model.save(modelPath);
else
    afterStatic = initialSolutions;
    afterParticle = initialSolutions;
end

assert(strcmp(char(model.result.dataset('dset1').getString('solution')), 'sol1'), ...
    'Electrostatic dataset is not linked to sol1.');
assert(strcmp(char(model.result.dataset('pdset1').getString('solution')), 'sol2'), ...
    'Particle dataset is not linked to sol2.');

fprintf(fid, 'MODEL=%s\n', modelPath);
fprintf(fid, 'SOLUTION_TAGS=%s\n', afterParticle);
fprintf(fid, 'COMPUTE_EXECUTED=%d\n', ~skipCompute);
fprintf(fid, 'DATASET_LINKS=dset1:sol1,pdset1:sol2\n');
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('OaTofModularGuiCompute');

function text = joinJavaStrings(values)
items = cell(1,length(values));
for index = 1:length(values), items{index} = char(values(index)); end
text = strjoin(items,',');
end
