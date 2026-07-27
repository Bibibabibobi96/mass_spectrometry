function gpu_solver_comparison()
% Compares solve time for the Phase-2 electrostatics study using:
%   (a) the default/regular solver configuration (CPU iterative, i1)
%   (b) the direct solver switched to NVIDIA cuDSS (GPU)
% No plotting/rendering is done - numeric solve + timing only.

scriptDir = fileparts(mfilename('fullpath'));
componentRoot = fileparts(fileparts(scriptDir));
addpath(componentRoot);
paths = egun_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = fullfile(paths.modelWorkspaceDir, 'ElectronGun_ES.mph');

%% (a) Regular / default solver (CPU, iterative i1)
if any(strcmp(cell(ModelUtil.tags()), 'ModelRegular'))
    ModelUtil.remove('ModelRegular');
end
mA = ModelUtil.load('ModelRegular', modelPath);
sol1a = mA.sol('sol1');
fprintf('Regular solver (fc1.linsolver=%s)\n', char(sol1a.feature('s1').feature('fc1').getString('linsolver')));
tic;
sol1a.runAll;
t_regular = toc;
fprintf('Regular solve time: %.3f s\n\n', t_regular);
ModelUtil.remove('ModelRegular');

%% (b) GPU solver: Direct solver (dDef) with cuDSS
if any(strcmp(cell(ModelUtil.tags()), 'ModelGPU'))
    ModelUtil.remove('ModelGPU');
end
mB = ModelUtil.load('ModelGPU', modelPath);
sol1b = mB.sol('sol1');
s1b = sol1b.feature('s1');
dDefb = s1b.feature('dDef');

dDefb.set('linsolver', 'cudss');
s1b.feature('fc1').set('linsolver', 'dDef');

fprintf('GPU solver (fc1.linsolver=%s, dDef.linsolver=%s)\n', ...
    char(s1b.feature('fc1').getString('linsolver')), char(dDefb.getString('linsolver')));
tic;
sol1b.runAll;
t_gpu = toc;
fprintf('GPU (cuDSS) solve time: %.3f s\n\n', t_gpu);

fprintf('=== Comparison ===\n');
fprintf('Regular (CPU iterative): %.3f s\n', t_regular);
fprintf('GPU (cuDSS direct):      %.3f s\n', t_gpu);
fprintf('Speedup factor: %.2fx\n', t_regular / t_gpu);

ModelUtil.remove('ModelGPU');
exit;
end
