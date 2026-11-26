function trace_assembly_particles(planPath, modelPath, releasePath, outputDir)
%TRACE_ASSEMBLY_PARTICLES COMSOL 6.4/R2025b co-resident field CPT.
% Official APIs checked 2026-11-27: Electric Force particle_ug_acdc.07.22,
% withsol comsol_ref_definitions.21.039, mphparticle llmatlab_ug_ref.9.51.
% Caller must validate/protect the frozen plan, model, original release and
% writer lifecycle. Native execution and the exact model tree remain unverified.
plan=jsondecode(fileread(planPath));
assert(plan.schema_version==1 && strcmp(plan.role,'comsol_assembly_pulse_plan'));
assert(exist(outputDir,'dir')==7 && isfile(modelPath) && isfile(releasePath));
assert(isfield(plan,'native') && isfield(plan.native,'background_solution_tag') && ...
    isfield(plan.native,'on_solution_tag') && isfield(plan.native,'vacuum_selection'));
assert(~strcmp(plan.native.background_solution_tag,plan.native.on_solution_tag));
assert(plan.source.mass_kg>0 && plan.source.charge_state~=0 && ...
    plan.source.charge_state==fix(plan.source.charge_state));
times=plan.observation_times_us(:);
assert(numel(times)>=2 && all(isfinite(times)) && all(diff(times)>0));
assert(times(1)==plan.source.source_time_us && plan.drive.on_us<plan.drive.off_us);
assert(plan.numerics.maximum_step_us>0 && plan.numerics.relative_tolerance>0 && ...
    plan.numerics.absolute_tolerance>0);
data=readmatrix(releasePath,'FileType','text','Delimiter',',');
assert(size(data,1)==numel(plan.source.particle_ids) && size(data,2)==6 && all(isfinite(data),'all'));
import com.comsol.model.util.*
model=mphload(modelPath,'AssemblyParticleTracing');
cleanupModel=onCleanup(@() ModelUtil.remove('AssemblyParticleTracing')); %#ok<NASGU>
soltags=string(cell(model.sol.tags));
assert(any(soltags==string(plan.native.background_solution_tag)) && any(soltags==string(plan.native.on_solution_tag)));
comp=model.component('comp1');
assert(any(string(cell(comp.selection.tags))==string(plan.native.vacuum_selection)));
assert(~any(string(cell(comp.physics.tags))=="cpt"));
vac=comp.selection(plan.native.vacuum_selection).entities();
assert(~isempty(vac));
values=mphinterp(model,'V','coord',data(:,1:3).','selection',vac, ...
    'edim','domain','ext',0,'matherr','on');
assert(numel(values)==size(data,1) && all(isfinite(values)), ...
    'assembly:BirthVacuum','Every original birth must lie in the actual field domain.');
model.param.set('assembly_source_time',sprintf('%.17g[us]',plan.source.source_time_us));
model.param.set('assembly_pulse_on',sprintf('%.17g[us]',plan.drive.on_us));
model.param.set('assembly_pulse_off',sprintf('%.17g[us]',plan.drive.off_us));
cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1');
cpt.selection.named(plan.native.vacuum_selection);
% Reuse the geometry producer's propagated per-member selections. Interior
% ideal sheets are transparent; actual metal and exterior boundaries freeze.
% All three classes must be non-overlapping and exhaust the vacuum boundary.
members=plan.native.members;if isstruct(members),members=num2cell(members);end
vacuumFaces=double(comp.selection('assembly_reference_vacuum_faces').entities());
vacuumFaces=vacuumFaces(:)';metal=[];sheets=[];
for k=1:numel(members)
    member=members{k};
    if strcmp(member.representation_role,'ideal_surface')
        selected=double(comp.selection(['geom1_' char(member.feature_tag) '_bnd']).entities());
        sheets=union(sheets,intersect(selected(:)',vacuumFaces));
    else
        selected=double(comp.selection(sprintf('assembly_member_adj_%04d',k)).entities());
        metal=union(metal,intersect(selected(:)',vacuumFaces));
    end
    assert(~isempty(intersect(selected(:)',vacuumFaces)), ...
        'assembly:BoundaryMember','A declared member has no selected vacuum faces.');
end
outer=double(comp.selection('assembly_outer_boundary').entities());outer=outer(:)';
assignedFaces=union(union(metal,sheets),outer);
assert(isempty(intersect(metal,sheets)) && isempty(intersect(metal,outer)) && ...
    isempty(intersect(sheets,outer)) && ...
    isequal(sort(assignedFaces(:)),sort(vacuumFaces(:))), ...
    'assembly:BoundaryPartition','Metal, ideal sheets and outer faces must be disjoint and exhaustive.');
for row={{'wall_assembly_metal',metal,'Freeze'},{'wall_assembly_outer',outer,'Freeze'}, ...
         {'wall_assembly_ideal',sheets,'Pass'}}
    item=row{1};
    if ~isempty(item{2})
        wall=cpt.create(item{1},'Wall',2);wall.selection.set(item{2});wall.set('WallCondition',item{3});
        readFaces=double(wall.selection.entities());
        assert(strcmp(char(wall.getString('WallCondition')),item{3}) && ...
            isequal(sort(readFaces(:)),sort(double(item{2}(:)))), ...
            'assembly:WallReadback','CPT wall selection or condition differs.');
    end
end
cpt.feature('pp1').set('mp',sprintf('%.17g[kg]',plan.source.mass_kg));
cpt.feature('pp1').set('Z',sprintf('%.0f',plan.source.charge_state));
cpt.prop('StoreParticleStatusData').set('StoreParticleStatusData',true);
rel=cpt.create('rel1','ReleaseFromDataFile',-1);
nativeReleasePath=fullfile(outputDir,'assembly_release.txt');
writematrix(data,nativeReleasePath,'Delimiter','tab');
rel.set('Filename',nativeReleasePath); rel.set('icolp','0');
rel.set('VelocitySpecification','SpecifyVelocity'); rel.set('InitialVelocity','FromFile'); rel.set('icolv','3');
rel.set('rt','assembly_source_time'); rel.importData;
force=cpt.create('ef_pulse','ElectricForce',3); force.selection.named(plan.native.vacuum_selection);
force.set('E_src','userdef');
gate='if(t>=assembly_pulse_on&&t<assembly_pulse_off,1,0)';
axes='xyz'; expressions=cell(1,3);
for k=1:3
    off=sprintf('withsol(''%s'',es.E%c)',plan.native.background_solution_tag,axes(k));
    on=sprintf('withsol(''%s'',es.E%c)',plan.native.on_solution_tag,axes(k));
    expressions{k}=sprintf('(%s)+(%s)*((%s)-(%s))',off,gate,on,off);
end
force.set('E',expressions);
study=model.study.create('std_assembly_particle'); transient=study.create('time','Transient');
transient.set('tlist',strtrim(sprintf('%.17g ',times*1e-6)));
transient.setEntry('activate','es',false); transient.setEntry('activate','cpt',true);
cpt.feature('pp1').set('StudyStep','std_assembly_particle/time'); rel.set('StudyStep','std_assembly_particle/time');
sol=model.sol.create('sol_assembly_particle'); sol.study('std_assembly_particle');
sol.createAutoSequence('std_assembly_particle'); sol.attach('std_assembly_particle');
sol.feature('v1').set('notsolmethod','sol');
sol.feature('v1').set('notsol',plan.native.background_solution_tag);
time=sol.feature('t1'); time.set('odesolvertype','implicit'); time.set('timemethod','genalpha');
oatof_cpt_solver_policy(time,struct('solver_steps','strict','times_to_store','tlist'),'apply');
time.set('maxstepconstraintgenalpha','const'); time.set('maxstepgenalpha',sprintf('%.17g',plan.numerics.maximum_step_us*1e-6));
time.set('rtol',sprintf('%.17g',plan.numerics.relative_tolerance));
time.set('atolglobalvaluemethod','manual'); time.set('atolglobalmethod','scaled');
time.set('atolglobal',sprintf('%.17g',plan.numerics.absolute_tolerance));
dataset=model.result.dataset.create('assembly_particles','Particle'); dataset.set('solution','sol_assembly_particle');
model.study('std_assembly_particle').run;
expr={'cpt.pidx','qx/1[mm]','qy/1[mm]','qz/1[mm]', ...
    'cpt.vx/1[m/s]','cpt.vy/1[m/s]','cpt.vz/1[m/s]','cpt.fs','cpt.st/1[us]'};
p=mphparticle(model,'dataset','assembly_particles','t',times*1e-6,'expr',expr,'dataonly','on');
assert(numel(p.t)==numel(times) && all(abs(p.t(:)*1e6-times)<=8*eps(max(1,abs(times)))));
count=size(data,1); nt=numel(times); raw=double(p.d1);
if isequal(size(raw),[nt,count]), trans=false;
elseif isequal(size(raw),[count,nt]), trans=true;
else, error('assembly:ParticleShape','Unexpected native particle layout'); end
values=nan(nt,count,numel(expr));
for k=1:numel(expr)
    v=double(p.(sprintf('d%d',k))); if trans, v=v.'; end
    assert(isequal(size(v),[nt,count])); values(:,:,k)=v;
end
ids=reshape(values(1,:,1),1,[]);
assert(isequal(sort(ids),1:count),'assembly:ParticleIDs','Native index mapping differs');
[~,order]=sort(ids); values=values(:,order,:);
indexValues=values(:,:,1);expectedIndices=repmat(1:count,nt,1);
assert(all(~isfinite(indexValues) | indexValues==expectedIndices,'all'), ...
    'assembly:ParticleIDs','Native trajectory index changed between samples.');
initial=reshape(values(1,:,2:7),count,6);
assert(all(abs(initial-data)<=32*eps(max(ones(size(data)),max(abs(initial),abs(data)))),'all'));
out=fullfile(outputDir,'assembly_particles.csv'); fid=fopen(out,'w'); assert(fid>=0);
closer=onCleanup(@() fclose(fid));
fprintf(fid,'particle_id,native_particle_index,instrument_time_us,x_mm,y_mm,z_mm,vx_m_per_s,vy_m_per_s,vz_m_per_s,state_present,solver_raw_status,solver_stop_time_us\n');
for j=1:count
    for i=1:nt
        v=reshape(values(i,j,2:7),1,6); present=all(isfinite(v));
        fprintf(fid,'%.0f,%.0f,%.17g,',plan.source.particle_ids(j),j,times(i));
        fprintf(fid,'%.17g,',v); fprintf(fid,'%d,%.0f,%.17g\n',present,values(i,j,8),values(i,j,9));
    end
end
clear closer
facts=struct('comsol_version',char(ModelUtil.getComsolVersion()), ...
    'particle_count',count,'stored_times_us',times,'study_completed',true, ...
    'boundary_policy','metal_and_outer_freeze_ideal_pass', ...
    'metal_faces',metal,'outer_faces',outer,'ideal_sheet_faces',sheets);
fid=fopen(fullfile(outputDir,'assembly_particle_facts.json'),'w');assert(fid>=0);
closer=onCleanup(@() fclose(fid));fprintf(fid,'%s',jsonencode(facts));clear closer
end
