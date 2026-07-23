function result = ms_rf_quadrupole_no_collision()
%MS_RF_QUADRUPOLE_NO_COLLISION Build a traceable RF transport or RF+DC mass-filter case.

projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(projectRoot);
repoRoot=fileparts(fileparts(projectRoot));
addpath(fullfile(repoRoot,'common','comsol'));
addpath(fullfile(repoRoot,'common','multipole'));
interface = jsondecode(fileread(fullfile(projectRoot,'config','interface_contract.json')));
runLabel = 'baseline';
operatingPoint = 'official_100amu_2eV';
meshAuto = 1;
meshHmaxMm = NaN;
sourceAxialOffsetMm = 0;
saveModel = true;
writeDetailedOutputs = true;
ionPath = fullfile(projectRoot,'config','particles','official_fixed_100.ion');
runConfigPath = getenv('RFQUAD_RUN_CONFIG');
assert(~isempty(runConfigPath), 'RFQUAD_RUN_CONFIG is required for a traceable run.');
runConfig = jsondecode(fileread(runConfigPath));
assert(strcmp(runConfig.project, 'rf_quadrupole_collision_cooling') && ...
    any(strcmp(runConfig.mode, {'transport_no_collision','transport_interface_readiness','mass_filter_reference'})), ...
    'RF quadrupole run-config project or mode mismatch.');
runMode = runConfig.mode;
resolvedPath=fullfile(projectRoot,'config','resolved_geometry.json');
if isfield(runConfig,'inputs') && isfield(runConfig.inputs,'resolved_contract')
    resolvedPath=runConfig.inputs.resolved_contract;
    if ~isfile(resolvedPath), resolvedPath=fullfile(projectRoot,resolvedPath); end
end
resolved = load_rf_quadrupole_contract(resolvedPath);
baseline = resolved; source = resolved.particle_source; mode = resolved.mode;
assert(isfield(runConfig.inputs,'family_operating_contract'), ...
    'Run config must freeze the shared multipole operating contract.');
operating = jsondecode(fileread(runConfig.inputs.family_operating_contract));
assert(operating.schema_version==1 && strcmp(operating.role,'rf_multipole_normalized_operating_contract') && ...
    strcmp(operating.identity.project_id,'rf_quadrupole_collision_cooling') && ...
    operating.identity.radial_order_n==2 && operating.identity.electrode_count==4, ...
    'Shared multipole operating contract identity mismatch.');
assert(abs(operating.geometry_mm.r0-baseline.geometry_mm.field_radius_r0)<1e-12 && ...
    abs(operating.geometry_mm.effective_length-baseline.geometry_mm.rod_length)<1e-12, ...
    'Shared multipole operating geometry differs from the resolved quadrupole.');
if isfield(runConfig, 'run_id'), runLabel = runConfig.run_id; end
if isfield(runConfig, 'operating_point'), operatingPoint = runConfig.operating_point; end
if isfield(runConfig, 'particle_table_path'), ionPath = runConfig.particle_table_path; end
if isfield(runConfig, 'comsol_rf_steps_per_period'), mode.numerics.comsol_rf_steps_per_period = runConfig.comsol_rf_steps_per_period; end
if isfield(runConfig, 'comsol_mesh_auto_level'), meshAuto = runConfig.comsol_mesh_auto_level; end
if isfield(runConfig, 'comsol_hmax_mm'), meshHmaxMm = runConfig.comsol_hmax_mm; end
if isfield(runConfig, 'source_axial_offset_mm'), sourceAxialOffsetMm = runConfig.source_axial_offset_mm; end
if isfield(runConfig, 'save_model'), saveModel = logical(runConfig.save_model); end
if isfield(runConfig, 'write_detailed_outputs'), writeDetailedOutputs = logical(runConfig.write_detailed_outputs); end
comsolOutputDir = runConfig.comsol_dir; resultsOutputDir = runConfig.results_dir;
isMassFilter=strcmp(runMode,'mass_filter_reference');
drive=operating.voltage;
assert(strcmp(drive.waveform,'sine'),'Quadrupole COMSOL modes require the shared sine-wave contract.');
rfPeakV=drive.rf_amplitude_V_zero_to_peak_per_group;
rfPhaseRad=drive.phase_rad;
dcV=drive.dc_amplitude_V_per_group;
axisV=drive.common_mode_offset_V;
rfFrequencyHz=drive.frequency_Hz;
staticEntranceV=0; staticExitV=0; staticDetectorV=0;
if isMassFilter
    staticEntranceV=mode.static_electrodes_V.entrance_plate;
    staticExitV=mode.static_electrodes_V.exit_enclosure;
    staticDetectorV=mode.static_electrodes_V.detector;
end
assert(meshAuto > 0 && isfinite(meshAuto), 'COMSOL mesh-auto level must be positive.');
if isempty(meshHmaxMm) || ~isscalar(meshHmaxMm) || ~(meshHmaxMm > 0 && isfinite(meshHmaxMm))
    meshHmaxMm = NaN;
end
ions = readmatrix(ionPath,'FileType','text','Delimiter',',');
assert(size(ions,1)>0 && size(ions,2)==11, 'Fixed ION table shape mismatch.');
assert(all(abs(ions(:,2)-ions(1,2))<1e-12) && all(abs(ions(:,3)-ions(1,3))<1e-12), ...
    'One run requires a single particle mass and charge state.');
source.particles=size(ions,1); source.mass_amu=ions(1,2); source.charge_state=ions(1,3);

import com.comsol.model.*
import com.comsol.model.util.*

tag = 'RFQuadTransport';
if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
model = ModelUtil.create(tag);
if isMassFilter, model.label('Reference quadrupole - RF+DC mass filter'); else, model.label('SIMION reference quadrupole - RF-only transport'); end
comp = model.component.create('comp1',true);
geom = comp.geom.create('geom1',3);
geom.lengthUnit('mm');
geom.label('SIMION built-in quad monolithic geometry');

g = baseline.geometry_mm; rodArray = baseline.rod_array_mm; rods = rodArray.rods;
interfaces = baseline.interface_layout_mm;
p = model.param;
p.set('r0',sprintf('%.12g[mm]',g.field_radius_r0),'Inter-rod field radius');
p.set('r_rod',sprintf('%.12g[mm]',g.rod_radius),'Circular rod radius');
p.set('R_center',sprintf('%.12g[mm]',g.rod_center_radius),'Rod center radius');
p.set('z_rod_min',sprintf('%.12g[mm]',g.rod_z_min));
p.set('L_rod',sprintf('%.12g[mm]',g.rod_length));
p.set('V_rf',sprintf('%.12g[V]',rfPeakV));
p.set('V_dc',sprintf('%.12g[V]',dcV));
p.set('V_axis',sprintf('%.12g[V]',axisV));
p.set('phi_rf',sprintf('%.12g[rad]',rfPhaseRad));
p.set('f_rf',sprintf('%.12g[Hz]',rfFrequencyHz));
p.set('axial_scale','1');
p.set('z_rod_exit',sprintf('%.12g[mm]',interface.planes.rod_exit.z_mm),'Rod-exit diagnostic plane');
p.set('z_handoff',sprintf('%.12g[mm]',interface.planes.handoff.z_mm),'Downstream component handoff plane');
p.set('z_acceptance',sprintf('%.12g[mm]',interface.planes.acceptance_detector.z_mm),'Standalone acceptance detector plane');
p.set('m_ion',sprintf('%.15g[kg]',source.mass_amu*1.66053906660e-27));
p.set('q_mathieu','4*e_const*V_rf/(m_ion*(2*pi*f_rf)^2*r0^2)');
p.set('a_mathieu','8*e_const*V_dc/(m_ion*(2*pi*f_rf)^2*r0^2)');

rodTags=create_multipole_round_rods(geom,rodArray,'rod','z',[0 0 0]);
rodMetadata=repmat(struct('tag','','rod_id',0,'electrode_group',0, ...
    'segment_id',1,'common_mode_V',axisV),1,numel(rods));
for k=1:numel(rods)
    rodMetadata(k).tag=rodTags{k}; rodMetadata(k).rod_id=rods(k).rod_id;
    rodMetadata(k).electrode_group=rods(k).electrode_group;
end
for k=1:numel(rodTags)
    geom.feature(rodTags{k}).label(sprintf('Reference circular rod %d',k));
end

geom.feature.create('vacuum','Block');
geom.feature('vacuum').label('Reference PA vacuum envelope');
geom.feature('vacuum').set('size',{sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',g.model_z_span)});
geom.feature('vacuum').set('pos',{sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),'0'});

geom.feature.create('ent_outer','Block');
geom.feature('ent_outer').set('size',{sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',2*g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',interfaces.entrance.plate_z_max_mm-interfaces.entrance.plate_z_min_mm)});
geom.feature('ent_outer').set('pos',{sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',-g.exit_enclosure_outer_half_width),sprintf('%.12g[mm]',interfaces.entrance.plate_z_min_mm)});
geom.feature.create('ent_hole','Cylinder');
geom.feature('ent_hole').set('r',sprintf('%.12g[mm]',interfaces.entrance.aperture_radius_mm));
geom.feature('ent_hole').set('h',sprintf('%.12g[mm]',interfaces.entrance.plate_z_max_mm-interfaces.entrance.plate_z_min_mm));
geom.feature('ent_hole').set('pos',{'0','0',sprintf('%.12g[mm]',interfaces.entrance.plate_z_min_mm)});
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
geom.feature('detector').set('h',sprintf('%.12g[mm]',g.detector_thickness));
detectorZ=interfaces.exit.particle_plane_z_mm;
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
es=comp.physics.create('es','Electrostatics','geom1'); es.label('Differential RF/DC unit field'); es.selection.named('sel_vac');
es.field('electricpotential').field('Vdiff'); es.field('electricpotential').component({'Vdiff'});
for k=1:numel(rodTags)
    s=['selb_' rodTags{k}]; comp.selection.create(s,'Adjacent'); comp.selection(s).set('input',{['geom1_' rodTags{k} '_dom']});
    pot=es.create(sprintf('pot_rod%d',k),'ElectricPotential',2); pot.selection.named(s); pot.set('V0',sprintf('%d[V]',100*(3-2*rodMetadata(k).electrode_group)));
end
for item={{'entrance','entrance'},{'exit','exit_enclosure'},{'detector','detector'}}
    entry=item{1}; s=['selb_' entry{1}]; comp.selection.create(s,'Adjacent'); comp.selection(s).set('input',{['geom1_' entry{2} '_dom']});
    pot=es.create(['pot_' entry{1}],'ElectricPotential',2); pot.selection.named(s); pot.set('V0','0[V]');
end

ess=comp.physics.create('ess','Electrostatics','geom1'); ess.label('Axis common mode and static end fields'); ess.selection.named('sel_vac');
ess.field('electricpotential').field('Vstatic'); ess.field('electricpotential').component({'Vstatic'});
for k=1:numel(rodTags)
    pot=ess.create(sprintf('pot_rod%d',k),'ElectricPotential',2); pot.selection.named(['selb_' rodTags{k}]);
    pot.set('V0',sprintf('%.12g[V]',rodMetadata(k).common_mode_V));
end
staticItems={{'entrance',staticEntranceV},{'exit',staticExitV},{'detector',staticDetectorV}};
for item=staticItems
    entry=item{1}; pot=ess.create(['pot_' entry{1}],'ElectricPotential',2); pot.selection.named(['selb_' entry{1}]);
    pot.set('V0',sprintf('%.12g[V]',entry{2}));
end

mesh=comp.mesh.create('mesh1'); mesh.label('Candidate tetrahedral mesh');
if isfinite(meshHmaxMm)
    mesh.label(sprintf('Candidate tetrahedral mesh (hmax %.12g mm)',meshHmaxMm));
end
configure_comsol_mesh(mesh,'geom1',meshAuto,'',meshHmaxMm);mesh.run;
mi=mphmeshstats(model,'mesh1'); assert(~mi.isempty && mi.iscomplete && ~mi.hasproblems,'Mesh gate failed.');
std1=model.study.create('std1');
if isMassFilter, std1.label('Stationary differential and static fields'); else, std1.label('Stationary RF unit field'); end
std1.create('stat1','Stationary');
sol1=model.sol.create('sol1'); sol1.study('std1'); sol1.createAutoSequence('std1');
sol1.attach('std1'); sol1.runAll;

cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1');
if isMassFilter, cpt.label('RF+DC mass-filter transport - no collisions'); else, cpt.label('RF-only transport - no collisions'); end
cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp','m_ion'); cpt.feature('pp1').set('Z',sprintf('%d',source.charge_state));
scratch=runConfig.runtime_dir; if ~exist(scratch,'dir'),mkdir(scratch);end
initialPositionMm=zeros(size(ions,1),3); initialVelocityMS=zeros(size(ions,1),3);
for i=1:size(ions,1)
    speed=sqrt(2*ions(i,9)*1.602176634e-19/(source.mass_amu*1.66053906660e-27));
    az=deg2rad(ions(i,7)); el=deg2rad(ions(i,8));
    vSim=[speed*cos(el)*cos(az),speed*cos(el)*sin(az),speed*sin(el)];
    % Positions follow the copied IOB basis: PA x -> wb z, PA y -> -wb y,
    % PA z -> wb x.  SIMION applies FLY2 standard_beam az/el in its local
    % beam basis before the IOB placement, so a direct trajectory-slope
    % audit gives physical PA velocity [-vSim(2),-vSim(3),vSim(1)] rather
    % than the position-basis inverse.  Preserve this empirically verified
    % distinction; it aligns the fixed source's x(z), y(z) with SIMION.
    releaseData=[ions(i,6),-ions(i,5),ions(i,4)+sourceAxialOffsetMm,-vSim(2),-vSim(3),vSim(1)];
    initialPositionMm(i,:)=releaseData(1:3); initialVelocityMS(i,:)=releaseData(4:6);
    releasePath=fullfile(scratch,sprintf('particle_%03d.txt',i)); writematrix(releaseData,releasePath,'Delimiter','tab');
    rel=cpt.create(sprintf('rel%03d',i),'ReleaseFromDataFile',-1); rel.label(sprintf('Official fixed particle %03d, birth %.9g us',i,ions(i,1)));
    rel.set('Filename',releasePath); rel.set('icolp','0'); rel.set('VelocitySpecification','SpecifyVelocity'); rel.set('InitialVelocity','FromFile'); rel.set('icolv','3'); rel.set('rt',sprintf('%.12g[us]',ions(i,1))); rel.importData();
end
ef=cpt.create('ef1','ElectricForce',3);
if isMassFilter, ef.label('RF+DC and static electric force'); else, ef.label('RF-only electric force'); end
ef.selection.named('sel_vac'); ef.set('E_src','userdef');
fieldScale='((V_dc+V_rf*sin(2*pi*f_rf*t+phi_rf))/100[V])';
ef.set('E',{[fieldScale '*(-d(Vdiff,x))-axial_scale*d(Vstatic,x)'],[fieldScale '*(-d(Vdiff,y))-axial_scale*d(Vstatic,y)'],[fieldScale '*(-d(Vdiff,z))-axial_scale*d(Vstatic,z)']});

std2=model.study.create('std2');
if isMassFilter, std2.label('Transient RF+DC mass filtering'); else, std2.label('Transient RF-only transport'); end
time=std2.create('time1','Transient');
dt=1/rfFrequencyHz/mode.numerics.comsol_rf_steps_per_period; tmax=(max(ions(:,1))+mode.numerics.maximum_time_us)*1e-6;
time.set('tlist',sprintf('range(0,%.15g,%.15g)',dt,tmax)); time.setEntry('activate','es',false);
time.setEntry('activate','ess',false);
time.setEntry('activate','cpt',true);
for i=1:size(ions,1), cpt.feature(sprintf('rel%03d',i)).set('StudyStep','std2/time1'); end
cpt.feature('pp1').set('StudyStep','std2/time1');
sol2=model.sol.create('sol2'); sol2.study('std2'); sol2.createAutoSequence('std2');
sol2.feature('v1').set('notsolmethod','sol'); sol2.feature('v1').set('notsol','sol1');
sol2.attach('std2'); sol2.runAll;

pdset=model.result.dataset.create('pdset1','Particle'); pdset.label(sprintf('Fixed paired particle trajectories (N=%d)',source.particles)); pdset.set('solution','sol2');
pg=model.result.create('pg_traj','PlotGroup3D'); pg.set('data','pdset1'); pg.set('titletype','manual');
if isMassFilter
    pg.label('RF+DC mass-filter trajectories'); pg.set('title',sprintf('Reference quadrupole: RF+DC mass filtering at %.12g Th (N=%d)',source.mass_amu,source.particles));
else
    pg.label('RF-only transport trajectories'); pg.set('title',sprintf('SIMION reference quadrupole: RF-only transport (N=%d)',source.particles));
end
pg.create('traj1','ParticleTrajectories');
pd=mphparticle(model,'dataset','pdset1'); x=squeeze(pd.p(:,:,1)); y=squeeze(pd.p(:,:,2)); z=squeeze(pd.p(:,:,3));
vx=squeeze(pd.v(:,:,1)); vy=squeeze(pd.v(:,:,2)); vz=squeeze(pd.v(:,:,3)); radial=sqrt(x.^2+y.^2);
nP=size(z,2); assert(nP==size(ions,1),'Solved particle count mismatch.');
arrival=nan(1,nP); arrivalRadius=nan(1,nP); crossedDetectorPlane=false(1,nP); hit=false(1,nP); maxRadius=max(radial,[],1,'omitnan'); threshold=detectorZ-1e-6;
rodRadial=radial; rodRadial(z<g.rod_z_min | z>g.rod_z_max)=NaN;
maxRodRadius=max(rodRadial,[],1,'omitnan');
terminalX=nan(1,nP); terminalY=nan(1,nP); terminalZ=nan(1,nP);
terminalIndex=nan(1,nP);
for i=1:nP
    finalSample=find(isfinite(x(:,i)) & isfinite(y(:,i)) & isfinite(z(:,i)),1,'last');
    assert(~isempty(finalSample),'Particle %d has no finite terminal coordinate.',i);
    terminalX(i)=x(finalSample,i); terminalY(i)=y(finalSample,i); terminalZ(i)=z(finalSample,i);
    terminalIndex(i)=finalSample;
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
result=struct('solver','COMSOL','mode',runMode,'operating_point',operatingPoint,'collision_feature_present',collisionPresent,'q_mathieu',mphglobal(model,'q_mathieu','dataset','dset1'),'a_mathieu',mphglobal(model,'a_mathieu','dataset','dset1'), ...
    'particles',nP,'hits',sum(hit),'transmission',mean(hit),'max_radius_mm',max(maxRadius),'max_hit_rod_radius_mm',maxHitRodRadius, ...
    'detector_plane_crossings',sum(crossedDetectorPlane),'max_detector_hit_radius_mm',max(arrivalRadius(hit),[],'omitnan'), ...
    'mean_detector_time_us',mean(arrival,'omitnan'),'rf_steps_per_period',mode.numerics.comsol_rf_steps_per_period,'mesh_auto_level',meshAuto,'mesh_hmax_mm',meshHmaxMm, ...
    'source_axial_offset_mm',sourceAxialOffsetMm,'mass_Th',source.mass_amu,'rf_peak_V',rfPeakV,'dc_per_group_V',dcV, ...
    'axis_common_mode_V',axisV,'static_entrance_V',staticEntranceV,'static_exit_V',staticExitV,'static_detector_V',staticDetectorV, ...
    'run_label',runLabel);
primaryMetrics=summarizeDetectorEnergy(pd,detectorZ,g.detector_radius,source.mass_amu);
result.mean_output_energy_eV=primaryMetrics.mean_output_energy_eV;
transportGateFailed=~isMassFilter && (result.transmission<mode.numerics.minimum_expected_transmission || result.max_hit_rod_radius_mm>=mode.numerics.maximum_allowed_radius_fraction_r0*g.field_radius_r0);
if collisionPresent || transportGateFailed
    error('COMSOL transport/confinement gate failed: transmission=%.6g maxHitRodRadius=%.6g',result.transmission,result.max_hit_rod_radius_mm);
end

if ~exist(comsolOutputDir,'dir'),mkdir(comsolOutputDir);end
if ~exist(resultsOutputDir,'dir'),mkdir(resultsOutputDir);end
modelName='rf_quadrupole_collision_cooling__model.mph';
particleStatePath=fullfile(resultsOutputDir,'particle_state.csv');
rawPhaseSpacePath=fullfile(resultsOutputDir,'particle_raw.csv');

% Persist a GUI-visible raw export node.  The standardized crossing table
% below is derived from this solved particle dataset by solver-independent
% linear crossing interpolation; no field or force logic is hidden here.
if writeDetailedOutputs
    rawExport=model.result.export.create('exp_phase_raw','Data');
    rawExport.label('Raw particle phase space for interface reconstruction');
    rawExport.set('data','pdset1');
    rawExport.set('expr',{'x','y','z','cpt.vx','cpt.vy','cpt.vz'});
    rawExport.set('filename',rawPhaseSpacePath);
    rawExport.run;
end

stateRows=cell(0,17);
for i=1:nP
    sourceState=struct('t_s',ions(i,1)*1e-6,'x_mm',initialPositionMm(i,1),'y_mm',initialPositionMm(i,2), ...
        'z_mm',initialPositionMm(i,3),'vx_m_s',initialVelocityMS(i,1),'vy_m_s',initialVelocityMS(i,2),'vz_m_s',initialVelocityMS(i,3));
    stateRows(end+1,:)=particleStateRow(i,'source','alive','none',sourceState,ions(i,1)*1e-6,rfFrequencyHz,rfPhaseRad, ...
        source.mass_amu,hypot(sourceState.x_mm,sourceState.y_mm),hypot(sourceState.x_mm,sourceState.y_mm)); %#ok<AGROW>

    [rodState,rodFound]=interpolateParticlePlane(pd.t,x(:,i),y(:,i),z(:,i),vx(:,i),vy(:,i),vz(:,i),interface.planes.rod_exit.z_mm);
    if rodFound
        stateRows(end+1,:)=particleStateRow(i,'rod_exit','alive','none',rodState,ions(i,1)*1e-6,rfFrequencyHz,rfPhaseRad, ...
            source.mass_amu,hypot(rodState.x_mm,rodState.y_mm),maxRodRadius(i)); %#ok<AGROW>
    end
    [handoffState,handoffFound]=interpolateParticlePlane(pd.t,x(:,i),y(:,i),z(:,i),vx(:,i),vy(:,i),vz(:,i),interface.planes.handoff.z_mm);
    if handoffFound
        stateRows(end+1,:)=particleStateRow(i,'handoff','transmitted','none',handoffState,ions(i,1)*1e-6,rfFrequencyHz,rfPhaseRad, ...
            source.mass_amu,hypot(handoffState.x_mm,handoffState.y_mm),maxRodRadius(i)); %#ok<AGROW>
    end

    finalSample=terminalIndex(i); terminalState=struct('t_s',pd.t(finalSample),'x_mm',terminalX(i),'y_mm',terminalY(i), ...
        'z_mm',terminalZ(i),'vx_m_s',vx(finalSample,i),'vy_m_s',vy(finalSample,i),'vz_m_s',vz(finalSample,i));
    terminalRadius=hypot(terminalX(i),terminalY(i)); terminalStatus='lost'; terminalReason='electrode';
    if hit(i), terminalStatus='transmitted'; terminalReason='acceptance_detector';
    elseif terminalState.t_s-ions(i,1)*1e-6 >= mode.numerics.maximum_time_us*1e-6-1e-12
        terminalStatus='timeout'; terminalReason='timeout';
    elseif terminalZ(i)<0, terminalReason='backward_escape';
    elseif terminalRadius>g.exit_enclosure_outer_half_width, terminalReason='radial_escape';
    end
    stateRows(end+1,:)=particleStateRow(i,'terminal',terminalStatus,terminalReason,terminalState,ions(i,1)*1e-6,rfFrequencyHz,rfPhaseRad, ...
        source.mass_amu,terminalRadius,maxRodRadius(i)); %#ok<AGROW>
end
stateNames={'particle_id','event','status','terminal_reason','time_us','elapsed_time_us','rf_phase_rad','axial_z_mm', ...
    'transverse_x_mm','transverse_y_mm','velocity_axial_m_s','velocity_x_m_s','velocity_y_m_s','kinetic_energy_eV', ...
    'radial_position_mm','divergence_angle_deg','max_rod_radius_mm'};
assert(isequal(stateNames(:),cellstr(string(interface.particle_state_columns(:)))),'Interface column contract mismatch.');
writetable(cell2table(stateRows,'VariableNames',stateNames),particleStatePath);

modelPath=fullfile(comsolOutputDir,modelName); if saveModel, model.save(modelPath); end
summaryPath=fullfile(resultsOutputDir,'solver_summary.json'); fid=fopen(summaryPath,'w'); fprintf(fid,'%s',jsonencode(result,'PrettyPrint',true)); fclose(fid);
if writeDetailedOutputs
    trajectoryPath=fullfile(resultsOutputDir,'trajectory_samples.csv');
    trajectoryFile=fopen(trajectoryPath,'w'); assert(trajectoryFile>=0,'Could not open trajectory CSV.');
    fprintf(trajectoryFile,'particle_id,time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm\n');
    for i=1:nP
        valid=find(isfinite(x(:,i)) & isfinite(y(:,i)) & isfinite(z(:,i)));
        sampled=unique([valid(1:5:end); valid(end)]);
        for sample=sampled'
            fprintf(trajectoryFile,'%d,%.12g,%.12g,%.12g,%.12g,%.12g\n',i,pd.t(sample)*1e6,z(sample,i),x(sample,i),y(sample,i),radial(sample,i));
        end
    end
    fclose(trajectoryFile);
end
fprintf('STATUS=PASS\n');
end

function [state,found]=interpolateParticlePlane(time_s,x,y,z,vx,vy,vz,planeMm)
state=struct(); found=false;
valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
if numel(valid)<2, return; end
for j=2:numel(valid)
    a=valid(j-1); b=valid(j);
    if z(a)<planeMm && z(b)>=planeMm && z(b)>z(a)
        fraction=(planeMm-z(a))/(z(b)-z(a));
        lerp=@(left,right) left+fraction*(right-left);
        state=struct('t_s',lerp(time_s(a),time_s(b)),'x_mm',lerp(x(a),x(b)),'y_mm',lerp(y(a),y(b)), ...
            'z_mm',planeMm,'vx_m_s',lerp(vx(a),vx(b)),'vy_m_s',lerp(vy(a),vy(b)),'vz_m_s',lerp(vz(a),vz(b)));
        found=true; return
    end
end
end

function row=particleStateRow(particleId,event,status,reason,state,birthTimeS,frequencyHz,phaseRad,massAmu,radiusMm,maxRodRadiusMm)
speed2=state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2;
energyEv=0.5*massAmu*1.66053906660e-27*speed2/1.602176634e-19;
divergenceDeg=atan2d(hypot(state.vx_m_s,state.vy_m_s),state.vz_m_s);
row={particleId,event,status,reason,state.t_s*1e6,(state.t_s-birthTimeS)*1e6, ...
    mod(2*pi*frequencyHz*state.t_s+phaseRad,2*pi),state.z_mm,state.x_mm,state.y_mm, ...
    state.vz_m_s,state.vx_m_s,state.vy_m_s,energyEv,radiusMm,divergenceDeg,maxRodRadiusMm};
end

function metrics=summarizeDetectorEnergy(pd,detectorZ,detectorRadius,massAmu)
x=squeeze(pd.p(:,:,1)); y=squeeze(pd.p(:,:,2)); z=squeeze(pd.p(:,:,3));
vx=squeeze(pd.v(:,:,1)); vy=squeeze(pd.v(:,:,2)); vz=squeeze(pd.v(:,:,3));
if isvector(z), x=x(:); y=y(:); z=z(:); vx=vx(:); vy=vy(:); vz=vz(:); end
energy=nan(1,size(z,2)); hit=false(1,size(z,2));
for particle=1:size(z,2)
    sample=find(z(:,particle)>=detectorZ-1e-6,1,'first');
    if ~isempty(sample) && hypot(x(sample,particle),y(sample,particle))<=detectorRadius
        hit(particle)=true;
        speed2=vx(sample,particle)^2+vy(sample,particle)^2+vz(sample,particle)^2;
        energy(particle)=0.5*massAmu*1.66053906660e-27*speed2/1.602176634e-19;
    end
end
metrics=struct('transmission',mean(hit),'mean_output_energy_eV',mean(energy,'omitnan'), ...
    'output_energy_standard_deviation_eV',std(energy,'omitnan'));
end
