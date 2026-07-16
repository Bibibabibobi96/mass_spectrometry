function result = ms_rf_quadrupole_no_collision()
%MS_RF_QUADRUPOLE_NO_COLLISION Build the SIMION-reference RF-only candidate.

projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(projectRoot);
paths = rf_quadrupole_paths();
baseline = jsondecode(fileread(fullfile(projectRoot,'config','baseline.json')));
source = jsondecode(fileread(fullfile(projectRoot,'config','official_particle_source.json')));
mode = jsondecode(fileread(fullfile(projectRoot,'config','modes','transport_no_collision.json')));
runLabel = getenv('RFQUAD_COMSOL_RUN_LABEL');
if isempty(runLabel), runLabel = 'baseline'; end
stepsOverride = str2double(getenv('RFQUAD_COMSOL_RF_STEPS'));
if isfinite(stepsOverride) && stepsOverride > 0
    mode.numerics.comsol_rf_steps_per_period = stepsOverride;
end
meshAuto = str2double(getenv('RFQUAD_COMSOL_MESH_AUTO'));
if ~isfinite(meshAuto) || meshAuto <= 0, meshAuto = mode.numerics.comsol_mesh_auto_level; end
ionPath = fullfile(projectRoot,'config','particles','official_fixed_25.ion');
ions = readmatrix(ionPath,'FileType','text','Delimiter',',');
assert(size(ions,1)==source.particles && size(ions,2)==11, 'Fixed ION table shape mismatch.');

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
try
    mphstart(2036);
catch ME
    if ~contains(ME.message,'Already connected'), rethrow(ME); end
end
import com.comsol.model.*
import com.comsol.model.util.*

tag = 'RFQuadTransport';
if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
model = ModelUtil.create(tag);
model.label('SIMION reference quadrupole - RF-only transport');
comp = model.component.create('comp1',true);
geom = comp.geom.create('geom1',3);
geom.lengthUnit('mm');
geom.label('SIMION built-in quad monolithic geometry');

g = baseline.geometry_mm; rf = mode.rf;
p = model.param;
p.set('r0',sprintf('%.12g[mm]',g.field_radius_r0),'Inter-rod field radius');
p.set('r_rod',sprintf('%.12g[mm]',g.rod_radius),'Circular rod radius');
p.set('R_center',sprintf('%.12g[mm]',g.rod_center_radius),'Rod center radius');
p.set('z_rod_min',sprintf('%.12g[mm]',g.rod_z_min));
p.set('L_rod',sprintf('%.12g[mm]',g.rod_length));
p.set('V_rf',sprintf('%.12g[V]',rf.amplitude_V_peak));
p.set('f_rf',sprintf('%.12g[Hz]',rf.frequency_Hz));
p.set('m_ion',sprintf('%.15g[kg]',source.mass_amu*1.66053906660e-27));
p.set('q_mathieu','4*e_const*V_rf/(m_ion*(2*pi*f_rf)^2*r0^2)');

rodTags = cell(1,4);
for k=1:4
    rodTags{k}=sprintf('rod%d',k);
    geom.feature.create(rodTags{k},'Cylinder');
    geom.feature(rodTags{k}).label(sprintf('Reference circular rod %d',k));
    geom.feature(rodTags{k}).set('r','r_rod');
    geom.feature(rodTags{k}).set('h','L_rod');
    geom.feature(rodTags{k}).set('pos',{sprintf('R_center*cos(%d[deg])',(k-1)*90),sprintf('R_center*sin(%d[deg])',(k-1)*90),'z_rod_min'});
    geom.feature(rodTags{k}).set('selresult','on');
end

geom.feature.create('vacuum','Block');
geom.feature('vacuum').label('Reference PA vacuum envelope');
geom.feature('vacuum').set('size',{sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',g.model_z_span)});
geom.feature('vacuum').set('pos',{sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),'0'});

geom.feature.create('ent_outer','Block');
geom.feature('ent_outer').set('size',{sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',g.entrance_plate_z_max-g.entrance_plate_z_min)});
geom.feature('ent_outer').set('pos',{sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',g.entrance_plate_z_min)});
geom.feature.create('ent_hole','Cylinder');
geom.feature('ent_hole').set('r',sprintf('%.12g[mm]',g.entrance_aperture_radius));
geom.feature('ent_hole').set('h',sprintf('%.12g[mm]',g.entrance_plate_z_max-g.entrance_plate_z_min));
geom.feature('ent_hole').set('pos',{'0','0',sprintf('%.12g[mm]',g.entrance_plate_z_min)});
geom.feature.create('entrance','Difference');
geom.feature('entrance').label('Reference entrance plate with aperture');
geom.feature('entrance').selection('input').set({'ent_outer'});
geom.feature('entrance').selection('input2').set({'ent_hole'});
geom.feature('entrance').set('selresult','on');

geom.feature.create('exit_outer','Block');
geom.feature('exit_outer').set('size',{sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',g.exit_enclosure_z_max-g.exit_enclosure_z_min)});
geom.feature('exit_outer').set('pos',{sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',g.exit_enclosure_z_min)});
geom.feature.create('exit_inner','Block');
geom.feature('exit_inner').set('size',{sprintf('%.12g[mm]',2*g.exit_enclosure_inner_half_width),sprintf('%.12g[mm]',2*g.exit_enclosure_inner_half_width),sprintf('%.12g[mm]',g.exit_enclosure_z_max-g.exit_enclosure_front_wall_end_z)});
geom.feature('exit_inner').set('pos',{sprintf('%.12g[mm]',-g.exit_enclosure_inner_half_width),sprintf('%.12g[mm]',-g.exit_enclosure_inner_half_width),sprintf('%.12g[mm]',g.exit_enclosure_front_wall_end_z)});
geom.feature.create('exit_hole','Cylinder');
geom.feature('exit_hole').set('r',sprintf('%.12g[mm]',g.exit_aperture_radius));
geom.feature('exit_hole').set('h',sprintf('%.12g[mm]',g.exit_enclosure_z_max-g.exit_enclosure_z_min));
geom.feature('exit_hole').set('pos',{'0','0',sprintf('%.12g[mm]',g.exit_enclosure_z_min)});
geom.feature.create('exit_enclosure','Difference');
geom.feature('exit_enclosure').label('Reference exit enclosure');
geom.feature('exit_enclosure').selection('input').set({'exit_outer'});
geom.feature('exit_enclosure').selection('input2').set({'exit_inner','exit_hole'});
geom.feature('exit_enclosure').set('selresult','on');

geom.feature.create('detector','Cylinder');
geom.feature('detector').label('Reference detector plate');
geom.feature('detector').set('r',sprintf('%.12g[mm]',g.detector_radius));
geom.feature('detector').set('h','0.4[mm]');
detectorZ=baseline.coordinate_convention.detector_plane_z_mm;
geom.feature('detector').set('pos',{'0','0',sprintf('%.12g[mm]',detectorZ)});
geom.feature('detector').set('selresult','on');
geom.run;

electrodeDomains=[cellfun(@(t)['geom1_' t '_dom'],rodTags,'UniformOutput',false),{'geom1_entrance_dom','geom1_exit_enclosure_dom','geom1_detector_dom'}];
comp.selection.create('sel_vac','Complement');
comp.selection('sel_vac').label('Vacuum excluding every electrode');
comp.selection('sel_vac').set('input',electrodeDomains);
vacDomains=comp.selection('sel_vac').entities();
assert(~isempty(vacDomains),'Vacuum selection is empty.');

mat=model.material.create('mat_vac','Common'); mat.label('Vacuum'); mat.selection.named('sel_vac'); mat.propertyGroup('def').set('relpermittivity',{'1'});
es=comp.physics.create('es','Electrostatics','geom1'); es.label('RF unit field and grounded static electrodes'); es.selection.named('sel_vac');
for k=1:4
    s=sprintf('selb_rod%d',k); comp.selection.create(s,'Adjacent'); comp.selection(s).set('input',{sprintf('geom1_rod%d_dom',k)});
    pot=es.create(sprintf('pot_rod%d',k),'ElectricPotential',2); pot.selection.named(s); pot.set('V0',sprintf('%d[V]',100*(-1)^(k+1)));
end
for item={{'entrance','entrance'},{'exit','exit_enclosure'},{'detector','detector'}}
    entry=item{1}; s=['selb_' entry{1}]; comp.selection.create(s,'Adjacent'); comp.selection(s).set('input',{['geom1_' entry{2} '_dom']});
    pot=es.create(['pot_' entry{1}],'ElectricPotential',2); pot.selection.named(s); pot.set('V0','0[V]');
end

mesh=comp.mesh.create('mesh1'); mesh.label('Candidate tetrahedral mesh'); mesh.feature('size').set('hauto',meshAuto); mesh.feature.create('ftet1','FreeTet'); mesh.run;
mi=mphmeshstats(model,'mesh1'); assert(~mi.isempty && mi.iscomplete && ~mi.hasproblems,'Mesh gate failed.');
std1=model.study.create('std1'); std1.label('Stationary RF unit field'); std1.create('stat1','Stationary');
sol1=model.sol.create('sol1'); sol1.study('std1'); sol1.createAutoSequence('std1'); sol1.attach('std1'); sol1.runAll;

cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1'); cpt.label('RF-only transport - no collisions'); cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp','m_ion'); cpt.feature('pp1').set('Z',sprintf('%d',source.charge_state));
scratch=fullfile(paths.scratchDir,'comsol','fixed_particles'); if ~exist(scratch,'dir'),mkdir(scratch);end
for i=1:size(ions,1)
    speed=sqrt(2*ions(i,9)*1.602176634e-19/(source.mass_amu*1.66053906660e-27));
    az=deg2rad(ions(i,7)); el=deg2rad(ions(i,8));
    vSim=[speed*cos(el)*cos(az),speed*cos(el)*sin(az),speed*sin(el)];
    % The copied built-in IOB persists this basis mapping:
    % PA x -> workbench z, PA y -> -workbench y, PA z -> workbench x.
    % COMSOL x/y/z reproduce PA x/y/z, so apply the exact inverse mapping
    % to both position and velocity rather than only aligning the axis.
    releaseData=[ions(i,6),-ions(i,5),ions(i,4),vSim(3),-vSim(2),vSim(1)];
    releasePath=fullfile(scratch,sprintf('particle_%03d.txt',i)); writematrix(releaseData,releasePath,'Delimiter','tab');
    rel=cpt.create(sprintf('rel%03d',i),'ReleaseFromDataFile',-1); rel.label(sprintf('Official fixed particle %03d, birth %.9g us',i,ions(i,1)));
    rel.set('Filename',releasePath); rel.set('icolp','0'); rel.set('VelocitySpecification','SpecifyVelocity'); rel.set('InitialVelocity','FromFile'); rel.set('icolv','3'); rel.set('rt',sprintf('%.12g[us]',ions(i,1))); rel.importData();
end
ef=cpt.create('ef1','ElectricForce',3); ef.label('RF-only electric force'); ef.selection.named('sel_vac'); ef.set('E_src','userdef');
ef.set('E',{'(V_rf/100[V])*es.Ex*sin(2*pi*f_rf*t)','(V_rf/100[V])*es.Ey*sin(2*pi*f_rf*t)','(V_rf/100[V])*es.Ez*sin(2*pi*f_rf*t)'});

std2=model.study.create('std2'); std2.label('Transient RF-only transport'); time=std2.create('time1','Transient');
dt=1/rf.frequency_Hz/mode.numerics.comsol_rf_steps_per_period; tmax=(max(ions(:,1))+mode.numerics.maximum_time_us)*1e-6;
time.set('tlist',sprintf('range(0,%.15g,%.15g)',dt,tmax)); time.setEntry('activate','es',false); time.setEntry('activate','cpt',true);
for i=1:size(ions,1), cpt.feature(sprintf('rel%03d',i)).set('StudyStep','std2/time1'); end
cpt.feature('pp1').set('StudyStep','std2/time1');
sol2=model.sol.create('sol2'); sol2.study('std2'); sol2.createAutoSequence('std2'); sol2.feature('v1').set('notsolmethod','sol'); sol2.feature('v1').set('notsol','sol1'); sol2.attach('std2'); sol2.runAll;

pdset=model.result.dataset.create('pdset1','Particle'); pdset.label('Official fixed 25 particle trajectories'); pdset.set('solution','sol2');
pg=model.result.create('pg_traj','PlotGroup3D'); pg.label('RF-only transport trajectories'); pg.set('data','pdset1'); pg.set('titletype','manual'); pg.set('title','SIMION reference quadrupole: RF-only transport (N=25)'); pg.create('traj1','ParticleTrajectories');
pd=mphparticle(model,'dataset','pdset1'); x=squeeze(pd.p(:,:,1)); y=squeeze(pd.p(:,:,2)); z=squeeze(pd.p(:,:,3)); radial=sqrt(x.^2+y.^2);
nP=size(z,2); assert(nP==size(ions,1),'Solved particle count mismatch.');
arrival=nan(1,nP); arrivalRadius=nan(1,nP); crossedDetectorPlane=false(1,nP); hit=false(1,nP); maxRadius=max(radial,[],1,'omitnan'); threshold=detectorZ-1e-6;
rodRadial=radial; rodRadial(z<g.rod_z_min | z>g.rod_z_max)=NaN;
maxRodRadius=max(rodRadial,[],1,'omitnan');
terminalX=nan(1,nP); terminalY=nan(1,nP); terminalZ=nan(1,nP);
for i=1:nP
    finalSample=find(isfinite(x(:,i)) & isfinite(y(:,i)) & isfinite(z(:,i)),1,'last');
    assert(~isempty(finalSample),'Particle %d has no finite terminal coordinate.',i);
    terminalX(i)=x(finalSample,i); terminalY(i)=y(finalSample,i); terminalZ(i)=z(finalSample,i);
    k=find(z(:,i)>=threshold,1,'first');
    if ~isempty(k)
        crossedDetectorPlane(i)=true;
        arrivalRadius(i)=radial(k,i);
        if arrivalRadius(i)<=g.detector_radius
            hit(i)=true;
            arrival(i)=pd.t(k)*1e6;
        end
    end
end
hitRodRadius=maxRodRadius(hit); if isempty(hitRodRadius), maxHitRodRadius=NaN; else, maxHitRodRadius=max(hitRodRadius); end
featureTags=cell(cpt.feature.tags()); collisionPresent=any(contains(lower(string(featureTags)),'coll'));
result=struct('solver','COMSOL','mode','transport_no_collision','collision_feature_present',collisionPresent,'q_mathieu',mphglobal(model,'q_mathieu','dataset','dset1'), ...
    'particles',nP,'hits',sum(hit),'transmission',mean(hit),'max_radius_mm',max(maxRadius),'max_hit_rod_radius_mm',maxHitRodRadius, ...
    'detector_plane_crossings',sum(crossedDetectorPlane),'max_detector_hit_radius_mm',max(arrivalRadius(hit),[],'omitnan'), ...
    'mean_detector_time_us',mean(arrival,'omitnan'),'rf_steps_per_period',mode.numerics.comsol_rf_steps_per_period,'mesh_auto_level',meshAuto,'run_label',runLabel);
if collisionPresent || result.transmission<mode.numerics.minimum_expected_transmission || result.max_hit_rod_radius_mm>=mode.numerics.maximum_allowed_radius_fraction_r0*g.field_radius_r0
    error('COMSOL transport/confinement gate failed: transmission=%.6g maxHitRodRadius=%.6g',result.transmission,result.max_hit_rod_radius_mm);
end

if ~exist(paths.comsolCandidateDir,'dir'),mkdir(paths.comsolCandidateDir);end
if ~exist(paths.comsolResultsDir,'dir'),mkdir(paths.comsolResultsDir);end
if strcmp(runLabel,'baseline')
    suffix=''; modelName='rf_quadrupole_transport_no_collision_simion_reference.mph';
else
    suffix=['_' runLabel]; modelName=['rf_quadrupole_transport_no_collision_simion_reference_' runLabel '.mph'];
end
modelPath=fullfile(paths.comsolCandidateDir,modelName); model.save(modelPath);
summaryPath=fullfile(paths.comsolResultsDir,['transport_no_collision_summary' suffix '.json']); fid=fopen(summaryPath,'w'); fprintf(fid,'%s',jsonencode(result,'PrettyPrint',true)); fclose(fid);
particleTable=table((1:nP)',crossedDetectorPlane',hit',arrival',arrivalRadius',maxRodRadius',maxRadius',terminalX',terminalY',terminalZ','VariableNames', ...
    {'particle_id','crossed_detector_plane','hit','arrival_time_us','detector_plane_radius_mm','max_rod_radius_mm','max_radius_mm', ...
    'terminal_x_mm','terminal_y_mm','terminal_z_mm'}); writetable(particleTable,fullfile(paths.comsolResultsDir,['transport_no_collision_particles' suffix '.csv']));
fprintf('STATUS=PASS\n');
end
