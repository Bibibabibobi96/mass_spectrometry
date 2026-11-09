% Same stored mesh/solver candidate field. No geometry or mesh rebuilding.
import com.comsol.model.util.*
task = fileparts(mfilename('fullpath'));
addpath(task);
p = jsondecode(fileread(fullfile(task,'plan.json')));
resourceDirectory = getenv('MRTOF_COMSOL_RESOURCE_DIRECTORY');
assert(~isempty(resourceDirectory),'MRTOF:ResourcePath','Project runner must supply installed MATLAB resources');
addpath(resourceDirectory);
ModelUtil.showProgress(fullfile(task,'native.log'));
model = mphload(p.source_mph,'MRTOFCandidateField');
cleanup = onCleanup(@() ModelUtil.remove('MRTOFCandidateField'));
source = jsondecode(fileread(fullfile(task,'source_authority.json')));
target = jsondecode(fileread(fullfile(task,'frozen_input.json')));
geometry = jsondecode(fileread(fullfile(task,'resolved_geometry.json')));
before = solverReadback(model);
saveJson(fullfile(task,'solver_before.json'),before);
assert(before.fc_active && before.iterative_active && before.fc_solver=="i1" && ...
    before.multigrid_active, ...
    'MRTOF:SolverPath','Saved reviewed iterative path is not active');
assert(before.active_mesh_tag==string(p.active_mesh_tag), ...
    'MRTOF:ActiveMesh','Saved Study mesh differs from the sealed source');
vacuum = mphgetselection(model.component('comp1').physics('es').selection);
mesh = model.component('comp1').mesh(char(before.active_mesh_tag));
stats = mesh.stat();
stats.selection().geom('geom1',3).set(int32(vacuum.entities));
assert(mesh.isLocked() && stats.isComplete() && double(stats.getNumElem('tet'))==p.expected_tetrahedra && ...
    numel(vacuum.entities)==p.expected_vacuum_domain_count, ...
    'MRTOF:SelectedMesh','Saved electrostatic vacuum mesh differs from source');
voltageReadback = update_corridor_workpoint_voltages(model,source,target);
saveJson(fullfile(task,'voltage_readback.json'),voltageReadback);
model.sol(char(p.export_grid.solution_tag)).clearSolutionData;
timer = tic;
model.sol(char(p.export_grid.solution_tag)).runAll;
solveSeconds = toc(timer);
after = solverReadback(model);
saveJson(fullfile(task,'solver_after.json'),after);
assert(isequaln(before,after),'MRTOF:SolverChanged','Candidate solve changed reviewed solver controls');
result = export_corridor_scalar_field(model,geometry,target,p.export_grid,string(task));
result.solve_seconds = solveSeconds;
result.active_mesh_tag = char(after.active_mesh_tag);
result.mesh_locked = logical(mesh.isLocked());
result.selected_tetrahedra = double(stats.getNumElem('tet'));
result.selected_vacuum_domains = reshape(double(vacuum.entities),1,[]);
saveJson(fullfile(task,'result.json'),result);
for k = 1:numel(p.refinement_windows)
    window = p.refinement_windows(k);
    localResult = export_corridor_scalar_field(model,geometry,target, ...
        window.export_grid,string(window.output_directory));
    localResult.active_mesh_tag = char(after.active_mesh_tag);
    saveJson(fullfile(window.output_directory,'result.json'),localResult);
end
fprintf('MRTOF_CANDIDATE_FIELD_COMPLETE_NO_FLIGHT_QUALIFICATION\n');
function out = solverReadback(model)
s = model.sol('sol1').feature('s1');
i = s.feature('i1');
v = model.sol('sol1').feature('v1');
step = model.study('std1').feature('stat');
method = string(i.getString('linsolver'));
if method=="cg"
    mg = i.feature('mg1');
elseif method=="fgmres"
    mg = i.feature('gmg1');
else
    error('MRTOF:SolverPath','Saved iterative solver is not a reviewed CG or manual FGMRES path');
end
out = struct('fc_solver',string(s.feature('fc1').getString('linsolver')), ...
    'active_mesh_tag',string(step.mesh('geom1')), ...
    'fc_active',logical(s.feature('fc1').isActive()), ...
    'iterative_active',logical(i.isActive()),'iterative_solver',string(i.getString('linsolver')), ...
    'multigrid_active',logical(mg.isActive()), ...
    'mg_prefun',string(mg.getString('prefun')),'mg_cycle',string(mg.getString('mgcycle')), ...
    'mg_prefermatfree',logical(mg.getBoolean('prefermatfree')), ...
    'stationary_control',string(s.getString('control')),'stationary_stol',double(s.getDouble('stol')), ...
    'study_usestol',logical(step.getBoolean('usestol')),'study_stol',double(step.getDouble('stol')), ...
    'scale_method',string(v.getString('scalemethod')),'scale_v',double(v.getDouble('scaleval')), ...
    'field_scale_method',string(v.feature('comp1_V').getString('scalemethod')), ...
    'rhob',double(i.getDouble('rhob')),'errorchk',string(i.getString('errorchk')), ...
    'prefuntype',string(i.getString('prefuntype')),'nlinnormuse',string(i.getString('nlinnormuse')));
if method=="cg"
    out.solver_profile = "cg_mg1";
    out.mg_amgauto = double(mg.getInt('amgauto'));
    out.mg_loweramg = string(mg.getString('loweramg'));
    assert(out.mg_prefun=="amg",'MRTOF:SolverPath','Saved CG/mg1 preconditioner is not reviewed AMG');
else
    es = model.component('comp1').physics('es');
    level = step.mglevel('mgl1');
    out.solver_profile = "fgmres_manual_gmg1";
    out.fine_order = string(es.prop('ShapeProperty').getString('order_electricpotential'));
    out.fine_discretization = string(step.discretization('es'));
    out.manual_levels = cell(step.mglevel().tags());
    out.coarse_mesh = string(level.mesh('geom1'));
    out.coarse_discretization = string(level.discretization('es'));
    out.coarse_order = string(es.feature('disc1').getString('order_electricpotential'));
    out.mg_casegen = string(mg.getString('mcasegen'));
    out.mg_caseuse = cell(mg.getStringArray('mcaseuse'));
    out.mg_caseassem = cell(mg.getStringArray('mcaseassem'));
    out.mg_levels = double(mg.getInt('gmglevels'));
    out.mg_assemble = string(mg.getString('massem'));
    out.mg_keep = string(mg.getString('mkeep'));
    out.matrix_format = string(s.feature('aDef').getString('matrixformat'));
    out.iterative_active_children = activeChildren(i);
    for tag = {'pr','po'}
        parent = mg.feature(tag{1});
        smoother = parent.feature('kr1');
        record = struct('active_children',{activeChildren(parent)}, ...
            'solver',string(smoother.getString('prefun')), ...
            'termination',string(smoother.getString('iterm')), ...
            'iterations',double(smoother.getInt('iter')), ...
            'preconditioners',{activeChildren(smoother)});
        assert(isequal(record.active_children,{'kr1'}) && record.solver=="gmres" && ...
            record.termination=="iter" && record.iterations==2 && isempty(record.preconditioners), ...
            'MRTOF:SolverPath','Manual GMG smoother differs from reviewed no-PC GMRES path');
        out.(tag{1}) = record;
    end
    coarse = mg.feature('cs');
    out.coarse_active_children = activeChildren(coarse);
    out.coarse_solver = string(coarse.feature('amg1').getString('prefun'));
    assert(out.fine_order=="2" && out.fine_discretization=="physics" && ...
        isequal(out.manual_levels,{'mgl1'}) && out.coarse_mesh=="mesh1" && ...
        out.coarse_discretization=="disc1" && out.coarse_order=="1" && ...
        out.mg_prefun=="gmg" && out.mg_casegen=="manual" && ...
        isequal(out.mg_caseuse,{'mgl1'}) && isequal(out.mg_caseassem,{'mgl1'}) && ...
        out.mg_levels==1 && out.mg_prefermatfree && out.mg_assemble=="on" && ...
        out.mg_keep=="on" && out.matrix_format=="matrixfree" && ...
        isequal(out.iterative_active_children,{'gmg1'}) && ...
        isequal(out.coarse_active_children,{'amg1'}) && out.coarse_solver=="amg", ...
        'MRTOF:SolverPath','Saved manual GMG hierarchy differs from reviewed fine-Q2/coarse-Q1 path');
end
end
function tags = activeChildren(feature)
tags = {};
children = cell(feature.feature().tags());
for k = 1:numel(children)
    if feature.feature(children{k}).isActive()
        tags{end+1} = children{k};
    end
end
end
function saveJson(filename,value)
fid = fopen(filename,'w');
assert(fid>=0,'MRTOF:EvidenceWrite','Cannot write stage evidence');
closer = onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(value,PrettyPrint=true));
end
