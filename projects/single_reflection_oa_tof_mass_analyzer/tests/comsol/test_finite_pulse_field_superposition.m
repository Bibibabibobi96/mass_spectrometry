% Native COMSOL 6.4 regression: two stationary fields and a finite CPT pulse.
% This declared micro-case is not an oaTOF physical qualification. Run only
% through the repository COMSOL bootstrap; no production model is loaded.
% Official APIs: comsol_api_solver.51.75 (Parametric),
% comsol_api_solver.51.51 (Time), llmatlab_ug_ref.9.67 (mphsolutioninfo),
% llmatlab_ug_ref.9.51 (mphparticle), comsol_ref_definitions.21.039 (withsol).
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath) && isfolder(fileparts(reportPath)), ...
    'A run-private COMSOL_BOOTSTRAP_REPORT directory is required.');
runDir = fileparts(reportPath);
testDir = fileparts(mfilename('fullpath'));
addpath(fullfile(fileparts(fileparts(testDir)), 'comsol'));
detailPath = fullfile(runDir,'finite_pulse_field_superposition.log');
fid = fopen(detailPath, 'w');
assert(fid >= 0, 'Cannot open probe detail report.');
reportCleanup = onCleanup(@() fclose(fid));
import com.comsol.model.util.*
tag = 'FinitePulseSuperpositionProbe';
model = ModelUtil.create(tag);
modelCleanup = onCleanup(@() ModelUtil.remove(tag));
modelPath = fullfile(runDir, 'finite_pulse_field_superposition.mph');
try
    % SI case, not a projection or replacement of the real instrument pulse.
    % The 10 mm cube contains a 100 u, +1 ion initially at rest at its centre.
    % Constant Ex=17 V/m; switched Ez=43 V/m from 0.371 to 1.613 us.
    % The affine boundary voltage has an exactly affine FE solution.
    mass = 100*1.66053906660e-27;
    charge = 1.602176634e-19;
    edgeOn = 0.371e-6; edgeOff = 1.613e-6; endTime = 3e-6;
    staticField = 17; pulseField = 43;
    times = unique([0:0.2e-6:endTime, edgeOn, edgeOff, endTime]);
    % Predeclared accuracy target: 1 nm and 1 mm/s; coarse pass permits
    % 10x that budget. Fine uses 100x smaller rtol/atol. Convergence must
    % improve any error still above 10% of the fine accuracy budget.
    positionBudget = 1e-9; velocityBudget = 1e-3;
    tolerances = [1e-6, 1e-8];
    % `strict` makes the solver land on each declared output time, including
    % the discontinuous pulse edges.  It does not bound integration steps
    % within those intervals.  Keep every native step below 1 ns so the
    % finite gate is integrated independently of the 200 ns output cadence.
    maxInternalStep = 1e-9;
    fprintf(fid, ['CASE=cube_10mm_100u_rest\nSTATIC_EX_V_M=%.17g\n' ...
        'PULSE_EZ_V_M=%.17g\nON_S=%.17g\nOFF_S=%.17g\n' ...
        'POSITION_BUDGET_M=%.17g\nVELOCITY_BUDGET_M_S=%.17g\n'], ...
        staticField,pulseField,edgeOn,edgeOff,positionBudget,velocityBudget);
    model.param.set('oa_state','0');
    model.param.set('Es','17[V/m]'); model.param.set('Ep','43[V/m]');
    model.param.set('pulse_on',sprintf('%.17g[s]',edgeOn));
    model.param.set('pulse_off',sprintf('%.17g[s]',edgeOff));
    model.component.create('comp1',true);
    comp = model.component('comp1');
    geom = comp.geom.create('geom1',3); geom.lengthUnit('m');
    block = geom.create('blk1','Block');
    block.set('size',{'0.01','0.01','0.01'});
    block.set('pos',{'-0.005','-0.005','-0.005'}); geom.run;
    mat = comp.material.create('mat1','Common');
    mat.propertyGroup('def').set('relpermittivity','1');
    es = comp.physics.create('es','Electrostatics','geom1');
    voltage = es.create('pot1','ElectricPotential',2);
    voltage.selection.all; voltage.set('V0','-Es*x-oa_state*Ep*z');
    % An affine Dirichlet potential is represented exactly by quadratic
    % potential elements; leave the field tolerance to expose solver error.
    es.prop('ShapeProperty').set('order_electricpotential','2');
    mesh = comp.mesh.create('mesh1'); mesh.autoMeshSize(9); mesh.run;
    std = model.study.create('std_field');
    sweep = std.create('param','Parametric');
    sweep.setIndex('pname','oa_state',0);
    sweep.setIndex('plistarr','0 1',0);
    sweep.set('keepsol','all'); sweep.set('pdistrib',false);
    std.create('stat','Stationary');
    fieldSolver = model.sol.create('sol_field');
    fieldSolver.study('std_field');
    fieldSolver.createAutoSequence('std_field');
    fieldSolver.attach('std_field');
    stationary = fieldSolver.feature('s1');
    stationary.set('control','user');
    stationary.set('stol','1e-12');
    stationary.feature('dDef').set('linsolver','pardiso');
    fprintf(fid,['FIELD_SOLVER=%s\nFIELD_STATIONARY_STOL=%s\n' ...
        'FIELD_LINEAR_SOLVER=%s\nFIELD_POTENTIAL_ORDER=%s\n'], ...
        'sol_field','1e-12','pardiso','2');
    fieldSolver.runAll;
    [fieldTag, fieldInfo] = field_solution(model);
    fprintf(fid,'FIELD_SOLUTION=%s\nFIELD_INFORMATION=%s\n', ...
        fieldTag,jsonencode(fieldInfo));
    fieldExpressions = cell(2,3);
    for stateIndex = 1:2
        for componentIndex = 1:3
            axis = 'xyz';
            fieldExpressions{stateIndex,componentIndex} = sprintf( ...
                'withsol(''%s'',es.E%c,setval(oa_state,%d))', ...
                fieldTag,axis(componentIndex),stateIndex-1);
        end
    end
    % Evaluate the actual two-state reference at the cube centre, not a
    % presumed sol1 or parameter order. Both states retain the static field.
    expectedFields = [staticField,0,0;staticField,0,pulseField];
    sampledFields = zeros(2,3);
    for stateIndex = 1:2
        for componentIndex = 1:3
            % withsol/setval selects the physical oa_state; solnum selects one
            % evaluation row of that parametric solution rather than asking
            % mphinterp to return the whole two-row sweep.
            sampled = mphinterp(model,fieldExpressions{stateIndex,componentIndex}, ...
                'coord',[0;0;0],'solnum',1);
            assert(isscalar(sampled), ...
                'Each explicitly selected parametric field evaluation must be scalar.');
            sampledFields(stateIndex,componentIndex) = sampled;
        end
    end
    fprintf(fid,'SAMPLED_FIELDS_V_M=%s\n',jsonencode(sampledFields));
    fieldRelativeError = max(abs(sampledFields-expectedFields),[],'all')/pulseField;
    assert(fieldRelativeError <= tolerances(2), ...
        'Affine two-state field exceeds the fine numerical budget.');
    cpt = comp.physics.create('cpt','ChargedParticleTracing','geom1');
    cpt.selection.all;
    std.feature('stat').setEntry('activate','es',true);
    std.feature('stat').setEntry('activate','cpt',false);
    cpt.feature('pp1').set('mp',sprintf('%.17g[kg]',mass));
    cpt.feature('pp1').set('Z','1');
    releasePath = fullfile(runDir,'finite_pulse_particle.txt');
    writematrix([0,0,0,0,0,0],releasePath,'Delimiter','tab');
    release = cpt.create('rel1','ReleaseFromDataFile',-1);
    release.set('Filename',releasePath); release.set('icolp','0');
    release.set('VelocitySpecification','SpecifyVelocity');
    release.set('InitialVelocity','FromFile'); release.set('icolv','3');
    release.importData;
    force = cpt.create('ef1','ElectricForce',3); force.selection.all;
    force.set('E_src','userdef');
    gate = 'if(t>=pulse_on&&t<pulse_off,1,0)';
    fields = cell(1,3);
    for componentIndex = 1:3
        fields{componentIndex} = sprintf('%s+(%s)*(%s-%s)', ...
            fieldExpressions{1,componentIndex},gate, ...
            fieldExpressions{2,componentIndex},fieldExpressions{1,componentIndex});
    end
    force.set('E',fields);
    particleStudy = model.study.create('std_particle');
    transient = particleStudy.create('time','Transient');
    transient.set('tlist',strtrim(sprintf('%.17g ',times)));
    transient.setEntry('activate','es',false);
    transient.setEntry('activate','cpt',true);
    cpt.feature('pp1').set('StudyStep','std_particle/time');
    release.set('StudyStep','std_particle/time');
    sol = model.sol.create('sol_particle'); sol.study('std_particle');
    sol.createAutoSequence('std_particle'); sol.attach('std_particle');
    sol.feature('v1').set('notsolmethod','sol');
    sol.feature('v1').set('notsol',fieldTag);
    timeSolver = sol.feature('t1');
    runtime = struct('solver_steps','strict','times_to_store','tlist');
    policy = oatof_cpt_solver_policy(timeSolver,runtime,'apply');
    timeSolver.set('maxstepconstraintgenalpha','const');
    timeSolver.set('maxstepgenalpha',num2str(maxInternalStep,17));
    assert(strcmp(timeSolver.getString('maxstepconstraintgenalpha'),'const') && ...
        abs(str2double(timeSolver.getString('maxstepgenalpha'))-maxInternalStep) <= eps(maxInternalStep), ...
        'Finite-pulse maximum internal time-step setting did not persist.');
    fprintf(fid,'ACTUAL_ALGORITHM=%s\n',jsonencode(policy));
    fprintf(fid,'MAX_INTERNAL_STEP_S=%.17g\n',maxInternalStep);
    dataset = model.result.dataset.create('pulse_particles','Particle');
    dataset.set('solution','sol_particle');
    ax = charge*staticField/mass; az = charge*pulseField/mass;
    elapsedOn = max(times(:)-edgeOn,0); elapsedOff = max(times(:)-edgeOff,0);
    expectedPosition = [ax*times(:).^2/2,zeros(numel(times),1), ...
        az*(elapsedOn.^2-elapsedOff.^2)/2];
    expectedVelocity = [ax*times(:),zeros(numel(times),1), ...
        az*(elapsedOn-elapsedOff)];
    errors = zeros(2,2); traces = cell(1,2);
    for level = 1:2
        timeSolver.set('rtol',num2str(tolerances(level),17));
        timeSolver.set('atolglobalvaluemethod','manual');
        timeSolver.set('atolglobal',num2str(tolerances(level),17));
        particleStudy.run;
        rawCheckpointPath = fullfile(runDir, ...
            sprintf('finite_pulse_level_%d_raw.mph',level));
        mphsave(model,rawCheckpointPath);
        fprintf(fid,'RAW_PARTICLE_CHECKPOINT_LEVEL_%d=%s\n',level,rawCheckpointPath);
        oatof_cpt_solver_policy(timeSolver,runtime,'verify');
        traces{level} = sample_trace(model,times,fid);
        errors(level,:) = trace_errors(traces{level},expectedPosition,expectedVelocity);
        writematrix([times(:),traces{level}.position,traces{level}.velocity, ...
            expectedPosition,expectedVelocity],fullfile(runDir, ...
            sprintf('finite_pulse_level_%d.csv',level)));
        fprintf(fid,'LEVEL_%d_RTOL=%.17g ERR_POSITION_M=%.17g ERR_VELOCITY_M_S=%.17g\n', ...
            level,tolerances(level),errors(level,1),errors(level,2));
    end
    mphsave(model,modelPath);
    budgets = [positionBudget,velocityBudget];
    assert(all(errors(1,:)<=10*budgets) && all(errors(2,:)<=budgets), ...
        'Strict finite-pulse integration exceeds predeclared analytic budgets.');
    assert(all(errors(2,:)<=max(errors(1,:)/2,0.1*budgets)), ...
        'Tightened tolerances do not demonstrate convergence above the budget floor.');
    post = find(times>edgeOff);
    observedAcceleration = diff(traces{2}.velocity(post,:),1,1)./diff(times(post)).';
    % Velocity-error budget propagated through the smallest post-OFF interval.
    accelerationBudget = 2*velocityBudget/min(diff(times(post)));
    assert(max(abs(observedAcceleration-[ax,0,0]),[],'all')<=accelerationBudget, ...
        'Post-OFF motion does not retain only the static acceleration.');
    fprintf(fid,'POST_OFF_ACCELERATION_BUDGET_M_S2=%.17g\n',accelerationBudget);
    % Reopen and use Study Compute: no rebuilding, solver repair, or explicit
    % runAll is allowed to conceal a broken persisted Study/solution link.
    clear modelCleanup
    model = mphload(modelPath,tag);
    modelCleanup = onCleanup(@() ModelUtil.remove(tag));
    model.study('std_field').run;
    reopenedTag = field_solution(model);
    assert(strcmp(reopenedTag,fieldTag),'Reopened default Compute changed the field solution binding.');
    model.study('std_particle').run;
    oatof_cpt_solver_policy(model.sol('sol_particle').feature('t1'),runtime,'verify');
    reopened = sample_trace(model,times,fid);
    reopenedErrors = trace_errors(reopened,expectedPosition,expectedVelocity);
    repeatErrors = trace_errors(reopened,traces{2}.position,traces{2}.velocity);
    fprintf(fid,'REOPEN_ANALYTIC_ERRORS=%s\nREOPEN_REPEAT_ERRORS=%s\n', ...
        jsonencode(reopenedErrors),jsonencode(repeatErrors));
    assert(all(reopenedErrors<=budgets) && all(repeatErrors<=budgets), ...
        'Reopened default Compute exceeds the same predeclared budgets.');
    mphsave(model,modelPath);
    fprintf(fid,'MODEL=%s\nSTATUS=PASS\n',modelPath);
catch exception
    fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off'));
    rethrow(exception)
end
clear modelCleanup reportCleanup

function [tag,info] = field_solution(model)
off = mphsolutioninfo(model,'parameters',{'oa_state',0,0});
on = mphsolutioninfo(model,'parameters',{'oa_state',1,0});
common = intersect(string(off.solutions),string(on.solutions));
candidates = strings(0);
for candidate = reshape(common,1,[])
    entry = off.(char(candidate));
    if strcmp(entry.study,'std_field'), candidates(end+1)=candidate; end %#ok<SAGROW>
end
assert(numel(candidates)==1, ...
    'Expected one actual ES solution containing both oa_state=0 and 1.');
tag = char(candidates(1));
info = struct('off',off.(tag),'on',on.(tag));
end

function trace = sample_trace(model,times,fid)
data = mphparticle(model,'dataset','pulse_particles','t',times);
positionSize = size(data.p); velocitySize = size(data.v);
fprintf(fid,'PARTICLE_POSITION_SIZE=%s\nPARTICLE_VELOCITY_SIZE=%s\n', ...
    mat2str(positionSize),mat2str(velocitySize));
if isequal(positionSize,[numel(times),3]) && isequal(velocitySize,[numel(times),3])
    % LiveLink collapses the singleton particle dimension for this explicit
    % one-particle time query. The remaining columns are exactly x/y/z.
    position = data.p; velocity = data.v;
else
    assert(size(data.p,1)==numel(times) && size(data.p,2)==1 && size(data.p,3)==3 && ...
        size(data.v,1)==numel(times) && size(data.v,2)==1 && size(data.v,3)==3, ...
        'Probe requires one complete three-dimensional native particle trajectory.');
    position = reshape(data.p,[],3); velocity = reshape(data.v,[],3);
end
assert(max(abs(data.t(:)-times(:)))<=8*eps(max(times)), ...
    'Particle readout times differ from the explicit strict time list.');
trace = struct('position',position,'velocity',velocity);
assert(all(isfinite(trace.position),'all') && all(isfinite(trace.velocity),'all'), ...
    'Native particle trajectory is incomplete or nonfinite.');
end

function errors = trace_errors(trace,position,velocity)
errors = [max(abs(trace.position-position),[],'all'), ...
    max(abs(trace.velocity-velocity),[],'all')];
end
