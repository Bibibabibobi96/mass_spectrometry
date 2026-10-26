function facts = run_paired_accelerator_pulse(planPath,outputDir,SavedParticleModelPath)
%RUN_PAIRED_ACCELERATOR_PULSE Trace frozen OA states in an existing static field.
% The managed owner verifies input records/asset protection before this call.
% No geometry, mesh, ES solve, input-model write or additional OFF field.
% COMSOL 6.4 references (checked 2026-10-26):
% particle_ug_math.06.27/06.17 (file release/absolute release times),
% particle_ug_math.06.04 (interior Pass through/exterior Freeze),
% comsol_api_solver.51.51 (GA strict/tlist/maxstep),
% llmatlab_ug_ref.9.51 (mphparticle expressions/units/returned times).
% The first native run must establish actual release-property/array layouts;
% static tests do not qualify that API, field accuracy or particle physics.
arguments
    planPath (1,:) char
    outputDir (1,:) char
    SavedParticleModelPath (1,:) char = ''
end
plan=jsondecode(fileread(planPath));
[static,release,releaseData]=validate_inputs(plan);
if ~isfolder(outputDir), mkdir(outputDir); end
import com.comsol.model.util.*
tag='PairedAcceleratorPulse';
modelPath=SavedParticleModelPath;
if isempty(modelPath), modelPath=plan.model.path; end
model=mphload(modelPath,tag);
cleanup=onCleanup(@() ModelUtil.remove(tag)); %#ok<NASGU>
assert(~model.sol('sol1').isEmpty(),'oatof:PairedPulseField','Stored ES solution is empty.');
if isempty(SavedParticleModelPath)
    configure_particle_study(model,plan,static,releaseData,outputDir);
    verify_particle_study(model,plan);
    model.study('std_pulse').run;
    assert(~model.sol('sol_pulse').isEmpty(),'oatof:PairedPulseSolution','Particle solution is empty.');
    modelPath=fullfile(outputDir,'paired_accelerator_pulse.mph');
    % Successful native data must survive any subsequent particle export error.
    mphsave(model,modelPath);
    write_json(fullfile(outputDir,'paired_pulse_solution.json'),struct( ...
        'schema_version',1,'role','paired_accelerator_pulse_solution', ...
        'status','solved_saved','plan_path',planPath,'model_path',modelPath, ...
        'solution_tag','sol_pulse','saved_in_this_run',true));
    solverFacts=verify_particle_study(model,plan);
else
    % This branch consumes an owner-bound solved model; never Compute or copy it.
    solverFacts=verify_particle_study(model,plan);
    assert(~model.sol('sol_pulse').isEmpty(),'oatof:PairedPulseSolution','Saved particle solution is empty.');
end
facts=export_particles(model,plan,release,releaseData,outputDir,modelPath);
facts.reused_particle_solution=~isempty(SavedParticleModelPath);
facts.solver=solverFacts;
facts.plan_path=planPath;
write_json(fullfile(outputDir,'paired_pulse_native_facts.json'),facts);
end

function [static,release,data]=validate_inputs(plan)
assert(plan.schema_version==1 && strcmp(plan.role,'paired_accelerator_pulse_plan'), ...
    'oatof:PairedPulsePlan','Current paired pulse plan required.');
assert(finite_scalar(plan.particle_count) && plan.particle_count>0 && ...
    plan.particle_count==fix(plan.particle_count) && finite_scalar(plan.mass_amu) && ...
    plan.mass_amu>0 && finite_scalar(plan.mass_kg) && plan.mass_kg>0 && ...
    finite_scalar(plan.charge_state) && plan.charge_state==1, ...
    'oatof:PairedPulseSpecies','Positive particle count/mass and the supported +1 species required.');
times=plan.observation_times_us; n=plan.numerics;
assert(finite_scalar(plan.source_time_us) && finite_scalar(plan.pulse.on_us) && finite_scalar(plan.pulse.off_us) && ...
    plan.source_time_us<=plan.pulse.on_us && plan.pulse.on_us<plan.pulse.off_us && ...
    isnumeric(times) && isvector(times) && numel(times)>=3 && all(isfinite(times)) && all(diff(times)>0) && ...
    times(1)==plan.source_time_us && any(times==plan.pulse.on_us) && ...
    any(times==plan.pulse.off_us) && times(end)>plan.pulse.off_us, ...
    'oatof:PairedPulseTimes','Explicit absolute source/ON/OFF and increasing observation times required.');
assert(finite_scalar(n.maximum_step_us) && n.maximum_step_us>0 && ...
    finite_scalar(n.relative_tolerance) && n.relative_tolerance>0 && ...
    finite_scalar(n.absolute_tolerance) && n.absolute_tolerance>0, ...
    'oatof:PairedPulseNumerics','Positive finite step and solver tolerances required.');
static=jsondecode(fileread(plan.static_plan.path));
assert(static.schema_version==2 && strcmp(static.role,'oatof_paired_accelerator_static_field_plan') && ...
    strcmp(static.accelerator_variant,'three_zone_square') && ...
    numel(static.composition_plan.scope.instance_ids)==1 && ...
    strcmp(static.numerical_domain.boundary_policy,'native_zero_neumann') && ...
    strcmp(static.numerical_domain.comsol_outer_boundary,'zero_charge'), ...
    'oatof:PairedPulseScope','Frozen isolated three-zone OA static BVP required.');
binding=static.native_geometry_compilation.electrode_bindings.(static.oatof_instance_id);
ids=[binding.accelerator_repeller_id,binding.grounded_shield_id,binding.accelerator_grid1_id, ...
    binding.accelerator_intermediate2_id,binding.accelerator_grid2_id,binding.accelerator_ring_ids(:).'];
keys=arrayfun(@(id) matlab.lang.makeValidName(sprintf('%.0f',id)),ids,'UniformOutput',false);
assert(numel(unique(ids))==numel(ids) && ...
    isequal(sort(fieldnames(static.static_on_electrode_voltages_v)),sort(keys(:))) && ...
    isequal(sort(fieldnames(plan.off_electrode_voltages_v)),sort(keys(:))) && ...
    all(structfun(@(v) isnumeric(v) && isscalar(v) && isfinite(v) && v==0,plan.off_electrode_voltages_v)), ...
    'oatof:PairedPulseOff','Actual OA electrode coverage and all-zero frozen OFF voltages required.');
% The existing Cartesian reader owns column, ID, species and finite-6D checks.
[release,data]=oatof_read_cartesian_release(plan.source_csv.path,plan.mass_amu,plan.particle_count);
end

function valid=finite_scalar(value)
valid=isnumeric(value) && isscalar(value) && isfinite(value);
end

function configure_particle_study(model,plan,static,data,outputDir)
comp=model.component('comp1');
assert(isequal(string(cell(comp.physics.tags())),"es"), ...
    'oatof:PairedPulseScope','Source model must contain only the isolated electrostatic interface.');
vac=comp.selection('sel_vac').entities();
% Native finite interpolation in the exact tracked domains: no field-probe
% clearance, coordinate shift, projection or extrapolation of release points.
values=mphinterp(model,'V','coord',data(:,1:3).','selection',vac, ...
    'edim','domain','ext',0,'matherr','on');
assert(numel(values)==plan.particle_count && all(isfinite(values)), ...
    'oatof:PairedPulseVacuum','Every original release must be in the actual vacuum mesh.');
model.param.set('paired_source_time',sprintf('%.17g[us]',plan.source_time_us));
model.param.set('paired_pulse_on',sprintf('%.17g[us]',plan.pulse.on_us));
model.param.set('paired_pulse_off',sprintf('%.17g[us]',plan.pulse.off_us));
cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1'); cpt.selection.named('sel_vac');
% The owner derives kg from the one repository mass constant. COMSOL's u
% unit is not assumed to use that same frozen constant.
cpt.feature('pp1').set('mp',sprintf('%.17g[kg]',plan.mass_kg));
cpt.feature('pp1').set('Z',sprintf('%.0f',plan.charge_state));
cpt.prop('StoreParticleStatusData').set('StoreParticleStatusData',true);
% Default Wall is Freeze on exterior boundaries. Name the two disjoint
% exterior classes explicitly; transparent interior sheets stay separate.
roles=[{'repeller','accelshield'},arrayfun(@(k) sprintf('accelring_%d',k), ...
    1:static.accelerator_geometry.ring_count,'UniformOutput',false)];
metal=[];
for k=1:numel(roles), metal=union(metal,comp.selection(['selb_' roles{k}]).entities()); end
outer=comp.selection('sel_outer').entities(); sheets=[];
for role={'grid1','intermediate2','grid2'}
    sheets=union(sheets,comp.selection(['selb_' role{1}]).entities());
end
assert(isempty(intersect(metal,outer)) && isempty(intersect(sheets,union(metal,outer))) && ...
    isequal(sort(union(union(metal,outer),sheets)),sort(comp.selection('vac_boundaries').entities())), ...
    'oatof:PairedPulseBoundaries','Actual metal/outer/ideal-sheet boundary partition differs.');
% UI "Pass through" uses native 6.4 WallCondition token "Pass". Only the
% interior sheets use it: at an exterior boundary it means disappearance.
for row={{'wall_metal',metal,'Freeze'},{'wall_outer',outer,'Freeze'},{'wall_grids',sheets,'Pass'}}
    item=row{1}; wall=cpt.create(item{1},'Wall',2);
    wall.selection.set(item{2}); wall.set('WallCondition',item{3});
end
releasePath=fullfile(outputDir,'paired_pulse_release.txt');
fid=fopen(releasePath,'w'); assert(fid>=0,'oatof:PairedPulseOutput','Cannot write native release.');
closeFile=onCleanup(@() fclose(fid));
fprintf(fid,'%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\n',data.');
clear closeFile
rel=cpt.create('rel1','ReleaseFromDataFile',-1);
rel.set('Filename',releasePath); rel.set('icolp','0');
rel.set('VelocitySpecification','SpecifyVelocity'); rel.set('InitialVelocity','FromFile'); rel.set('icolv','3');
% The target-version release-time property is read back before Compute.
rel.set('rt','paired_source_time'); rel.importData;
force=cpt.create('ef_pulse','ElectricForce',3); force.selection.named('sel_vac');
force.set('E_src','userdef'); force.set('E',pulse_expressions());
study=model.study.create('std_pulse'); transient=study.create('time','Transient');
transient.set('tlist',strtrim(sprintf('%.17g ',plan.observation_times_us(:)*1e-6)));
transient.setEntry('activate','es',false); transient.setEntry('activate','cpt',true);
model.study('std1').feature('stat').setEntry('activate','cpt',false);
cpt.feature('pp1').set('StudyStep','std_pulse/time'); rel.set('StudyStep','std_pulse/time');
sol=model.sol.create('sol_pulse'); sol.study('std_pulse'); sol.createAutoSequence('std_pulse'); sol.attach('std_pulse');
sol.feature('v1').set('notsolmethod','sol'); sol.feature('v1').set('notsol','sol1');
time=sol.feature('t1'); time.set('odesolvertype','implicit'); time.set('timemethod','genalpha');
oatof_cpt_solver_policy(time,struct('solver_steps','strict','times_to_store','tlist'),'apply');
time.set('maxstepconstraintgenalpha','const'); time.set('maxstepgenalpha',sprintf('%.17g',plan.numerics.maximum_step_us*1e-6));
time.set('rtol',sprintf('%.17g',plan.numerics.relative_tolerance));
time.set('atolglobalvaluemethod','manual'); time.set('atolglobalmethod','scaled');
time.set('atolglobal',sprintf('%.17g',plan.numerics.absolute_tolerance));
dataset=model.result.dataset.create('paired_pulse_particles','Particle'); dataset.set('solution','sol_pulse');
end

function facts=verify_particle_study(model,plan)
comp=model.component('comp1'); cpt=comp.physics('cpt'); time=model.sol('sol_pulse').feature('t1');
facts=oatof_cpt_solver_policy(time,struct('solver_steps','strict','times_to_store','tlist'),'verify');
assert(strcmp(time.getString('odesolvertype'),'implicit') && strcmp(time.getString('timemethod'),'genalpha') && ...
    strcmp(time.getString('maxstepconstraintgenalpha'),'const') && ...
    strcmp(time.getString('atolglobalvaluemethod'),'manual') && strcmp(time.getString('atolglobalmethod'),'scaled') && ...
    strcmp(cpt.feature('rel1').getString('rt'),'paired_source_time') && ...
    isequal(string(cpt.feature('ef_pulse').getStringArray('E')),string(pulse_expressions()).'), ...
    'oatof:PairedPulseReadback','Saved pulse, release or active solver configuration differs.');
actual=[time.getDouble('maxstepgenalpha')*1e6,time.getDouble('rtol'),time.getDouble('atolglobal'), ...
    model.param.evaluate('paired_source_time','us'),model.param.evaluate('paired_pulse_on','us'), ...
    model.param.evaluate('paired_pulse_off','us'), ...
    model.param.evaluate(char(cpt.feature('pp1').getString('mp')),'kg'), ...
    model.param.evaluate(char(cpt.feature('pp1').getString('Z')))];
expected=[plan.numerics.maximum_step_us,plan.numerics.relative_tolerance,plan.numerics.absolute_tolerance, ...
    plan.source_time_us,plan.pulse.on_us,plan.pulse.off_us,plan.mass_kg,plan.charge_state];
assert(all(abs(actual-expected)<=8*eps(abs(expected))), ...
    'oatof:PairedPulseReadback','Saved numerical values or absolute times differ.');
assert(model.sol('sol_pulse').isAttached() && ...
    strcmp(model.result.dataset('paired_pulse_particles').getString('solution'),'sol_pulse'), ...
    'oatof:PairedPulseReadback','Saved particle study/solver/dataset is not attached.');
facts.maximum_step_us=actual(1); facts.relative_tolerance=actual(2);
facts.scaled_global_absolute_tolerance=actual(3); facts.source_time_us=actual(4);
facts.pulse_on_us=actual(5); facts.pulse_off_us=actual(6);
facts.mass_kg=actual(7); facts.charge_state=actual(8);
end

function expressions=pulse_expressions()
gate='if(t>=paired_pulse_on&&t<paired_pulse_off,1,0)';
expressions=arrayfun(@(axis) sprintf('(%s)*withsol(''sol1'',es.E%c)',gate,axis), ...
    'xyz','UniformOutput',false);
end

function facts=export_particles(model,plan,release,expected,outputDir,modelPath)
% Explicit dimensionless expressions encode the output units without assuming
% the units of mphparticle.p/v or silently transposing a squeezed array.
expressions={'cpt.pidx','qx/1[mm]','qy/1[mm]','qz/1[mm]', ...
    'cpt.vx/1[m/s]','cpt.vy/1[m/s]','cpt.vz/1[m/s]','cpt.fs','cpt.st/1[us]'};
solutionInfo=mphsolinfo(model,'soltag','sol_pulse');
storedTimes=solutionInfo.solvals(:)*1e6; requested=plan.observation_times_us(:);
assert(isequal(size(storedTimes),size(requested)) && all(abs(storedTimes-requested)<=8*eps(abs(requested))), ...
    'oatof:PairedPulseStoredTimes','Saved particle solution does not contain the declared strict output times.');
data=mphparticle(model,'dataset','paired_pulse_particles','t',plan.observation_times_us(:)*1e-6, ...
    'expr',expressions,'dataonly','on');
times=data.t(:)*1e6; count=plan.particle_count;
assert(isequal(size(times),size(requested)) && all(abs(times-requested)<=8*eps(abs(requested))), ...
    'oatof:PairedPulseTimes','Actual particle evaluation times differ.');
raw=double(data.d1); nt=numel(times);
transpose=false;
if isequal(size(raw),[nt,count]) && numel(unique(raw(1,:)))==count
    indices=raw;
elseif isequal(size(raw),[count,nt]) && numel(unique(raw(:,1)))==count
    indices=raw.'; transpose=true;
else
    error('oatof:PairedPulseShape','Native pidx layout does not identify every initial particle.');
end
[nativeIds,order]=sort(indices(1,:));
assert(all(isfinite(nativeIds)) && all(nativeIds==fix(nativeIds)) && numel(unique(nativeIds))==count, ...
    'oatof:PairedPulseIdentity','Native particle indices are missing or duplicated.');
values=nan(nt,count,numel(expressions));
for k=1:numel(expressions)
    component=double(data.(sprintf('d%d',k)));
    assert(isequal(size(component),size(raw)),'oatof:PairedPulseShape','Native expression shapes differ.');
    if transpose, component=component.'; end
    values(:,:,k)=component(:,order);
end
initial=reshape(values(1,:,2:7),count,6);
assert(all(isfinite(initial),'all') && ...
    all(abs(initial-expected)<=32*eps(max(ones(size(expected)),max(abs(initial),abs(expected)))),'all'), ...
    'oatof:PairedPulseInitial','Actual initial6D differs from the complete original source.');
indexValues=values(:,:,1);
assert(all(~isfinite(indexValues) | indexValues==nativeIds,'all'), ...
    'oatof:PairedPulseIdentity','Native trajectory columns changed particle identity.');
columns={'particle_id','native_particle_index','instrument_time_us','x_mm','y_mm','z_mm', ...
    'vx_m_per_s','vy_m_per_s','vz_m_per_s','state_present','solver_raw_status','solver_stop_time_us'};
rows=zeros(nt*count,numel(columns));
for k=1:count
    state=reshape(values(:,k,2:7),nt,6);
    rows((k-1)*nt+(1:nt),:)=[repmat(release.particle_id(k),nt,1), ...
        values(:,k,1),times,state,all(isfinite(state),2),values(:,k,8),values(:,k,9)];
end
write_samples(fullfile(outputDir,'paired_pulse_particles.csv'),columns,rows);
write_samples(fullfile(outputDir,'paired_pulse_initial.csv'),columns,rows(1:nt:end,:));
facts=struct('schema_version',1,'role','paired_accelerator_pulse_native_facts', ...
    'model_path',modelPath,'particle_count',count,'observation_count',nt, ...
    'actual_observation_times_us',times.','native_particle_indices',nativeIds, ...
    'stored_solution_times_us',storedTimes.', ...
    'native_expression_shape',size(raw),'native_expressions',{expressions}, ...
    'native_expression_units',{data.unit},'array_transposed',transpose, ...
    'native_elementary_charge_C',model.param.evaluate('e_const','C'), ...
    'initial_complete',true,'rows_with_missing_state',sum(rows(:,10)==0), ...
    'stop_reason','unknown; raw status/stop time are not collision-entity identities', ...
    'qualification','finite_pulse_wiring_only_no_numerical_equivalence_or_formal_qualification');
end

function write_samples(path,columns,rows)
fid=fopen(path,'w'); assert(fid>=0,'oatof:PairedPulseOutput','Cannot write particle output.');
cleanup=onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid,'%s\n',strjoin(columns,','));
fprintf(fid,[repmat('%.17g,',1,size(rows,2)-1),'%.17g\n'],rows.');
end

function write_json(path,value)
fid=fopen(path,'w'); assert(fid>=0,'oatof:PairedPulseOutput','Cannot write native facts.');
cleanup=onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid,'%s\n',jsonencode(value));
end
