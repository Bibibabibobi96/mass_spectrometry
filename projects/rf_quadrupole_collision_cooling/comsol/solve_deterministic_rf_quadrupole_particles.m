function result = solve_deterministic_rf_quadrupole_particles(runConfig, executionControl)
%SOLVE_DETERMINISTIC_RF_QUADRUPOLE_PARTICLES Solve one compiled no-collision case.
% This project-local mechanism does not select a scientific workflow. Dedicated
% entries must validate and compile their claim before calling this function.

projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(projectRoot);
repoRoot=fileparts(fileparts(projectRoot));
addpath(fullfile(repoRoot,'common','comsol'));
addpath(fullfile(repoRoot,'common','multipole'));
assert(nargin>=1 && nargin<=2 && isstruct(runConfig), ...
    'A fully compiled run-config struct is required.');
releaseGateEnabled=nargin==2;
if releaseGateEnabled
    executionControl=validateReleaseGateControl(executionControl);
end
assert(strcmp(requireText(runConfig,'project'),'rf_quadrupole_collision_cooling'), ...
    'RF quadrupole run-config project mismatch.');
inputs=requireStruct(runConfig,'inputs');
resolvedPath=requireExistingFile(inputs,'resolved_design');
resolved = load_rf_quadrupole_contract(resolvedPath);
baseline = resolved; source = resolved.particle_source;
interfacePath=requireExistingFile(inputs,'interface_contract');
interface=jsondecode(fileread(interfacePath));
ionPath=requireExistingFile(inputs,'particle_table');
numerics=requireStruct(runConfig,'compiled_solver_numerics');
assert(requireFiniteScalar(numerics,'schema_version')==1, ...
    'Compiled solver-numerics schema_version must equal 1.');
assert(strcmp(requireText(numerics,'role'), ...
    'rf_quadrupole_compiled_comsol_solver_numerics'), ...
    'Compiled solver-numerics envelope role mismatch.');
authority=requireStruct(numerics,'authority');
contractId=requireText(authority,'contract_id');
logicalSha256=requireText(authority,'logical_sha256');
assert(~isempty(regexp(logicalSha256,'^[0-9A-F]{64}$','once')), ...
    'Compiled solver-numerics logical_sha256 is invalid.');
selection=requireStruct(numerics,'selection');
profileId=requireText(selection,'profile_id');
requireText(selection,'usage');
experimentId=requirePresentText(selection,'numerical_experiment_id');
assert(strcmp(requireText(runConfig,'solver_numerics_contract_id'),contractId) && ...
    strcmp(requireText(runConfig,'solver_numerics_contract_logical_sha256'), ...
    logicalSha256) && ...
    strcmp(requireText(runConfig,'solver_numerics_profile_id'),profileId) && ...
    strcmp(requirePresentText(runConfig,'numerical_experiment_id'),experimentId), ...
    'Compiled solver-numerics identity differs from frozen run-config mirrors.');
mesh=requireStruct(numerics,'mesh');
meshAuto=requirePositiveInteger(mesh,'global_auto_level');
assert(meshAuto<=9,'COMSOL mesh global_auto_level must be in [1, 9].');
hmaxEnabled=requireLogicalScalar(mesh,'working_region_hmax_override_enabled');
if hmaxEnabled
    meshHmaxMm=requireFiniteScalar(mesh,'working_region_hmax_mm');
    assert(meshHmaxMm>0,'COMSOL mesh working_region_hmax_mm must be positive.');
else
    assert(~isfield(mesh,'working_region_hmax_mm'), ...
        'working_region_hmax_mm must be absent when its override is disabled.');
    meshHmaxMm=NaN;
end
trajectory=requireStruct(numerics,'trajectory');
rfStepsPerPeriod=requirePositiveInteger(trajectory,'rf_steps_per_period');
assert(rfStepsPerPeriod>=4 && rfStepsPerPeriod<=10000, ...
    'COMSOL trajectory rf_steps_per_period must be in [4, 10000].');
maximumTimeUs=requireFiniteScalar(trajectory,'maximum_time_us');
assert(maximumTimeUs>0,'COMSOL trajectory maximum_time_us must be positive.');
assert(requireFiniteScalar(runConfig,'comsol_mesh_auto_level')==meshAuto && ...
    requireFiniteScalar(runConfig,'comsol_rf_steps_per_period')==rfStepsPerPeriod && ...
    requireFiniteScalar(runConfig,'maximum_time_us')==maximumTimeUs, ...
    'Compiled solver-numerics values differ from frozen run-config mirrors.');
scientificSpec=requireStruct(runConfig,'compiled_scientific_spec');
sourceAxialOffsetMm=requireFiniteScalar(scientificSpec,'source_axial_offset_mm');
outputPolicy=requireStruct(runConfig,'output_policy');
saveModel=requireLogicalScalar(outputPolicy,'save_model');
writeDetailedOutputs=requireLogicalScalar(outputPolicy,'write_detailed_outputs');
runLabel=requireText(runConfig,'run_id');
operatingPoint=requireText(runConfig,'operating_point');
workflowId=requireText(runConfig,'workflow_id');
comsolOutputDir=requireText(runConfig,'comsol_dir');
resultsOutputDir=requireText(runConfig,'results_dir');
drive=resolved.drive;
assert(strcmp(drive.waveform,'sine'),'Quadrupole COMSOL modes require the shared sine-wave contract.');
rfPeakV=drive.rf_amplitude_V_zero_to_peak_per_group;
rfPhaseRad=drive.phase_rad;
dcV=drive.dc_amplitude_V_per_group;
axisV=drive.common_mode_offset_V;
rfFrequencyHz=drive.frequency_Hz;
staticElectrodes=resolved.static_electrodes_V;
assert(strcmp(staticElectrodes.role,'rectangular_reference_static_electrodes'), ...
    'Unsupported static-electrode role.');
staticEntranceV=staticElectrodes.entrance_plate_and_connector;
staticExitV=staticElectrodes.exit_enclosure_and_connector;
staticDetectorV=staticElectrodes.detector;
ions = readmatrix(ionPath,'FileType','text','Delimiter',',');
assert(size(ions,1)>0 && size(ions,2)==11, 'Fixed ION table shape mismatch.');
assert(all(abs(ions(:,2)-ions(1,2))<1e-12) && all(abs(ions(:,3)-ions(1,3))<1e-12), ...
    'One run requires a single particle mass and charge state.');
if releaseGateEnabled
    assert(requireFiniteScalar(runConfig,'particles')==100, ...
        'Release-construction gate requires runConfig.particles=100.');
    assert(isequal(size(ions),[100 11]) && all(isfinite(ions),'all'), ...
        'Release-construction gate requires one finite 100-by-11 ION11 table.');
    assert(numel(unique(ions(:,1)))==100, ...
        'Release-construction gate requires 100 unique finite birth times.');
    releaseTimeExpressions=arrayfun(@(birthTime) ...
        sprintf('%.12g[us]',birthTime),ions(:,1),'UniformOutput',false);
    assert(numel(unique(releaseTimeExpressions))==100, ...
        'Release-construction gate requires 100 unique formatted release times.');
end
source.particles=size(ions,1); source.mass_amu=ions(1,2); source.charge_state=ions(1,3);

import com.comsol.model.*
import com.comsol.model.util.*

tag = 'RFQuadTransport';
if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
model = ModelUtil.create(tag);
model.label('Reference quadrupole - compiled no-collision transport');
comp = model.component.create('comp1',true);
geom = comp.geom.create('geom1',3);
geom.lengthUnit('mm');
geom.label('SIMION built-in quad monolithic geometry');

g = baseline.geometry_mm; enclosure = g.enclosure;
rodArray = g.rod_array; rods = rodArray.rods;
interfaces = baseline.interfaces_mm;
p = model.param;
p.set('r0',sprintf('%.12g[mm]',g.inscribed_radius_r0),'Inter-rod field radius');
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
geom.feature('vacuum').set('size',{sprintf('%.12g[mm]',2*enclosure.outer_half_width_mm),sprintf('%.12g[mm]',2*enclosure.outer_half_width_mm),sprintf('%.12g[mm]',enclosure.vacuum_z_max_mm-enclosure.vacuum_z_min_mm)});
geom.feature('vacuum').set('pos',{sprintf('%.12g[mm]',-enclosure.outer_half_width_mm),sprintf('%.12g[mm]',-enclosure.outer_half_width_mm),sprintf('%.12g[mm]',enclosure.vacuum_z_min_mm)});

geom.feature.create('ent_outer','Block');
geom.feature('ent_outer').set('size',{sprintf('%.12g[mm]',2*enclosure.outer_half_width_mm),sprintf('%.12g[mm]',2*enclosure.outer_half_width_mm),sprintf('%.12g[mm]',interfaces.entrance.plate_z_max_mm-interfaces.entrance.plate_z_min_mm)});
geom.feature('ent_outer').set('pos',{sprintf('%.12g[mm]',-enclosure.outer_half_width_mm),sprintf('%.12g[mm]',-enclosure.outer_half_width_mm),sprintf('%.12g[mm]',interfaces.entrance.plate_z_min_mm)});
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
geom.feature('exit_outer').set('size',{sprintf('%.12g[mm]',2*enclosure.outer_half_width_mm),sprintf('%.12g[mm]',2*enclosure.outer_half_width_mm),sprintf('%.12g[mm]',enclosure.exit_enclosure_z_max_mm-enclosure.exit_enclosure_z_min_mm)});
geom.feature('exit_outer').set('pos',{sprintf('%.12g[mm]',-enclosure.outer_half_width_mm),sprintf('%.12g[mm]',-enclosure.outer_half_width_mm),sprintf('%.12g[mm]',enclosure.exit_enclosure_z_min_mm)});
geom.feature.create('exit_inner','Block');
geom.feature('exit_inner').set('size',{sprintf('%.12g[mm]',2*enclosure.inner_half_width_mm),sprintf('%.12g[mm]',2*enclosure.inner_half_width_mm),sprintf('%.12g[mm]',enclosure.exit_enclosure_z_max_mm-enclosure.exit_front_wall_end_z_mm)});
geom.feature('exit_inner').set('pos',{sprintf('%.12g[mm]',-enclosure.inner_half_width_mm),sprintf('%.12g[mm]',-enclosure.inner_half_width_mm),sprintf('%.12g[mm]',enclosure.exit_front_wall_end_z_mm)});
geom.feature.create('exit_hole','Cylinder');
geom.feature('exit_hole').set('r',sprintf('%.12g[mm]',interfaces.exit.aperture_radius_mm));
geom.feature('exit_hole').set('h',sprintf('%.12g[mm]',enclosure.exit_enclosure_z_max_mm-enclosure.exit_enclosure_z_min_mm));
geom.feature('exit_hole').set('pos',{'0','0',sprintf('%.12g[mm]',enclosure.exit_enclosure_z_min_mm)});
geom.feature.create('exit_enclosure','Difference');
geom.feature('exit_enclosure').label('Reference exit enclosure');
geom.feature('exit_enclosure').selection('input').set({'exit_outer'});
geom.feature('exit_enclosure').selection('input2').set({'exit_inner','exit_hole'});
geom.feature('exit_enclosure').set('selresult','on');

geom.feature.create('detector','Cylinder');
geom.feature('detector').label('Reference detector plate');
geom.feature('detector').set('r',sprintf('%.12g[mm]',enclosure.detector_radius_mm));
geom.feature('detector').set('h',sprintf('%.12g[mm]',enclosure.detector_thickness_mm));
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
std1.label('Stationary differential and static fields');
std1.create('stat1','Stationary');
sol1=model.sol.create('sol1'); sol1.study('std1'); sol1.createAutoSequence('std1');
sol1.attach('std1'); sol1.runAll;

cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1');
cpt.label('Compiled no-collision particle transport');
cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp','m_ion'); cpt.feature('pp1').set('Z',sprintf('%d',source.charge_state));
scratch=runConfig.runtime_dir; if ~exist(scratch,'dir'),mkdir(scratch);end
initialPositionMm=zeros(size(ions,1),3); initialVelocityMS=zeros(size(ions,1),3);
if releaseGateEnabled
    assert(~isfile(executionControl.breadcrumbs_path), ...
        'Release-construction breadcrumbs already exist: %s', ...
        executionControl.breadcrumbs_path);
    breadcrumbSequence=0;
end
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
    releasePath=fullfile(scratch,sprintf('particle_%03d.txt',i));
    releaseText=sprintf([ ...
        '%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\n'],releaseData);
    writeTextFileChecked(releasePath,'w',releaseText,'release data');
    releaseTag=sprintf('rel%03d',i);
    if releaseGateEnabled
        releaseTimeExpression=releaseTimeExpressions{i};
        releaseFile=readmatrix(releasePath,'FileType','text', ...
            'Delimiter',char(9));
        releaseFileShape=size(releaseFile);
        assert(isequal(releaseFileShape,[1 6]), ...
            'Release file %d shape is %s; expected [1 6].', ...
            i,mat2str(releaseFileShape));
        nonFiniteReleaseIndices=find(~isfinite(releaseFile));
        assert(isempty(nonFiniteReleaseIndices), ...
            'Release file %d has non-finite linear indices %s.', ...
            i,mat2str(nonFiniteReleaseIndices(:).'));
        releaseMaxAbsError=max(abs(releaseFile-releaseData),[],'all');
        assert(releaseMaxAbsError<1e-12, ...
            'Release file %d max abs error %.17g exceeds 1e-12.', ...
            i,releaseMaxAbsError);
        breadcrumb=releaseBreadcrumbBase(runConfig,releasePath,releaseData, ...
            i,releaseTag,ions(i,1),releaseTimeExpression);
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'before_create',cpt,'','');
    else
        releaseTimeExpression=sprintf('%.12g[us]',ions(i,1));
    end
    rel=cpt.create(releaseTag,'ReleaseFromDataFile',-1);
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_create',cpt,'','');
    end
    rel.label(sprintf('Official fixed particle %03d, birth %.9g us',i,ions(i,1)));
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_label',cpt,'','');
    end
    rel.set('Filename',releasePath);
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_set_filename',cpt,char(rel.getString('Filename')),'');
    end
    rel.set('icolp','0');
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_set_icolp',cpt,char(rel.getString('Filename')),'');
    end
    rel.set('VelocitySpecification','SpecifyVelocity');
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_set_velocity_specification',cpt, ...
            char(rel.getString('Filename')),'');
    end
    rel.set('InitialVelocity','FromFile');
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_set_initial_velocity',cpt,char(rel.getString('Filename')),'');
    end
    rel.set('icolv','3');
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_set_icolv',cpt,char(rel.getString('Filename')),'');
    end
    rel.set('rt',releaseTimeExpression);
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_set_rt',cpt,char(rel.getString('Filename')), ...
            char(rel.getString('rt')));
    end
    rel.importData();
    if releaseGateEnabled
        breadcrumbSequence=writeReleaseBreadcrumb( ...
            executionControl.breadcrumbs_path,breadcrumbSequence,breadcrumb, ...
            'after_import',cpt,char(rel.getString('Filename')), ...
            char(rel.getString('rt')));
    end
end
if releaseGateEnabled
    result=completeReleaseConstructionGate(model,cpt,ions, ...
        initialPositionMm,initialVelocityMS,releaseTimeExpressions,runConfig, ...
        executionControl,breadcrumbSequence);
    return
end
ef=cpt.create('ef1','ElectricForce',3);
ef.label('Differential RF/DC and static electric force');
ef.selection.named('sel_vac'); ef.set('E_src','userdef');
fieldScale='((V_dc+V_rf*sin(2*pi*f_rf*t+phi_rf))/100[V])';
ef.set('E',{[fieldScale '*(-d(Vdiff,x))-axial_scale*d(Vstatic,x)'],[fieldScale '*(-d(Vdiff,y))-axial_scale*d(Vstatic,y)'],[fieldScale '*(-d(Vdiff,z))-axial_scale*d(Vstatic,z)']});

std2=model.study.create('std2');
std2.label('Transient compiled no-collision transport');
time=std2.create('time1','Transient');
dt=1/rfFrequencyHz/rfStepsPerPeriod; tmax=(max(ions(:,1))+maximumTimeUs)*1e-6;
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
pg.label('Compiled no-collision trajectories');
pg.set('title',sprintf('Reference quadrupole: no-collision transport at %.12g Th (N=%d)',source.mass_amu,source.particles));
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
        if arrivalRadius(i)<=enclosure.detector_radius_mm
            hit(i)=true;
            arrival(i)=pd.t(k)*1e6;
        end
    end
end
hitRodRadius=maxRodRadius(hit); if isempty(hitRodRadius), maxHitRodRadius=NaN; else, maxHitRodRadius=max(hitRodRadius); end
featureTags=cell(cpt.feature.tags()); collisionPresent=any(contains(lower(string(featureTags)),'coll'));
result=struct('solver','COMSOL','mode',workflowId,'workflow_id',workflowId,'operating_point',operatingPoint,'collision_feature_present',collisionPresent,'q_mathieu',mphglobal(model,'q_mathieu','dataset','dset1'),'a_mathieu',mphglobal(model,'a_mathieu','dataset','dset1'), ...
    'particles',nP,'hits',sum(hit),'transmission',mean(hit),'max_radius_mm',max(maxRadius),'max_hit_rod_radius_mm',maxHitRodRadius, ...
    'detector_plane_crossings',sum(crossedDetectorPlane),'max_detector_hit_radius_mm',max(arrivalRadius(hit),[],'omitnan'), ...
    'mean_detector_time_us',mean(arrival,'omitnan'),'rf_steps_per_period',rfStepsPerPeriod,'mesh_auto_level',meshAuto,'mesh_hmax_mm',meshHmaxMm,'mesh_elements_total',sum(mi.numelem), ...
    'source_axial_offset_mm',sourceAxialOffsetMm,'mass_Th',source.mass_amu,'rf_peak_V',rfPeakV,'dc_per_group_V',dcV, ...
    'axis_common_mode_V',axisV,'static_entrance_V',staticEntranceV,'static_exit_V',staticExitV,'static_detector_V',staticDetectorV, ...
    'run_label',runLabel);
primaryMetrics=summarizeDetectorEnergy(pd,detectorZ,enclosure.detector_radius_mm,source.mass_amu);
result.mean_output_energy_eV=primaryMetrics.mean_output_energy_eV;
if collisionPresent
    error('COMSOL no-collision case contains a collision feature.');
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
    elseif terminalState.t_s-ions(i,1)*1e-6 >= maximumTimeUs*1e-6-1e-12
        terminalStatus='timeout'; terminalReason='timeout';
    elseif terminalZ(i)<0, terminalReason='backward_escape';
    elseif terminalRadius>enclosure.outer_half_width_mm, terminalReason='radial_escape';
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

function value=requireStruct(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName) && isstruct(parent.(fieldName)) && ...
    isscalar(parent.(fieldName)), '%s must be a scalar struct.',fieldName);
value=parent.(fieldName);
end

function value=requireText(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
raw=parent.(fieldName);
assert((ischar(raw) || (isstring(raw) && isscalar(raw))) && ...
    ~isempty(strtrim(char(raw))), '%s must be non-empty text.',fieldName);
value=char(raw);
end

function value=requirePresentText(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
raw=parent.(fieldName);
assert(ischar(raw) || (isstring(raw) && isscalar(raw)), ...
    '%s must be scalar text.',fieldName);
value=char(raw);
end

function path=requireExistingFile(parent,fieldName)
path=requireText(parent,fieldName);
assert(isfile(path), '%s does not identify a frozen file: %s',fieldName,path);
end

function value=requireFiniteScalar(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
value=parent.(fieldName);
assert(isnumeric(value) && isscalar(value) && isfinite(value), ...
    '%s must be one finite numeric scalar.',fieldName);
value=double(value);
end

function value=requirePositiveInteger(parent,fieldName)
value=requireFiniteScalar(parent,fieldName);
assert(value>0 && value==fix(value), '%s must be a positive integer.',fieldName);
end

function value=requireLogicalScalar(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
value=parent.(fieldName);
assert(islogical(value) && isscalar(value), '%s must be one logical scalar.',fieldName);
end

function control=validateReleaseGateControl(control)
assert(isstruct(control) && isscalar(control), ...
    'Release-construction execution control must be one scalar struct.');
assert(strcmp(requireText(control,'role'),'rf_release_construction_gate_control'), ...
    'Release-construction execution-control role mismatch.');
assert(requireLogicalScalar(control,'stop_after_release_construction'), ...
    'Release-construction execution control must stop after release construction.');
control.breadcrumbs_path=requireText(control,'breadcrumbs_path');
control.model_path=requireText(control,'model_path');
control.result_path=requireText(control,'result_path');
end

function breadcrumb=releaseBreadcrumbBase(runConfig,releasePath,releaseData, ...
        particleIndex,releaseTag,releaseTimeUs,releaseTimeExpression)
runDir=requireText(runConfig,'run_dir');
prefix=[runDir filesep];
assert(startsWith(releasePath,prefix), ...
    'Release file is outside the current run directory: %s',releasePath);
breadcrumb=struct( ...
    'schema_version',1, ...
    'role','rf_release_construction_breadcrumb', ...
    'run_id',requireText(runConfig,'run_id'), ...
    'particle_index',particleIndex, ...
    'release_tag',releaseTag, ...
    'release_time_us',releaseTimeUs, ...
    'release_time_expression',releaseTimeExpression, ...
    'file_relative_path',strrep(releasePath(numel(prefix)+1:end),'\','/'), ...
    'file_sha256',sha256File(releasePath), ...
    'row_count',1, ...
    'column_count',numel(releaseData));
end

function sequence=writeReleaseBreadcrumb(path,sequence,base,phase,cpt, ...
        actualFilename,actualReleaseTime)
entry=base;
sequence=sequence+1;
entry.sequence=sequence;
entry.timestamp_utc=char(datetime('now','TimeZone','UTC', ...
    'Format',"yyyy-MM-dd'T'HH:mm:ss.SSSXXX"));
entry.phase=phase;
featureTags=cell(cpt.feature.tags());
entry.release_tag_count=sum(startsWith(featureTags,'rel'));
entry.actual_filename=actualFilename;
entry.actual_release_time_expression=actualReleaseTime;
directory=fileparts(path);
if ~isfolder(directory),mkdir(directory);end
writeTextFileChecked(path,'a',[jsonencode(entry) newline], ...
    'release-construction breadcrumb');
end

function result=completeReleaseConstructionGate(model,cpt,ions, ...
        initialPositionMm,initialVelocityMS,releaseTimeExpressions,runConfig, ...
        control,breadcrumbSequence)
expectedParticles=100;
expectedTags=arrayfun(@(index)sprintf('rel%03d',index), ...
    1:expectedParticles,'UniformOutput',false);
featureTags=cell(cpt.feature.tags());
releaseTags=featureTags(startsWith(featureTags,'rel'));
assert(isequal(releaseTags(:),expectedTags(:)), ...
    'Release-construction gate did not create the exact ordered release-tag set.');
runtimeDir=requireText(runConfig,'runtime_dir');
expectedFileNames=arrayfun(@(index)sprintf('particle_%03d.txt',index), ...
    1:expectedParticles,'UniformOutput',false);
fileListing=dir(fullfile(runtimeDir,'particle_*.txt'));
[~,order]=sort({fileListing.name});
fileListing=fileListing(order);
assert(isequal({fileListing.name},expectedFileNames), ...
    'Release-construction gate did not preserve particle_001..particle_100.');
releaseFiles=repmat(struct('particle_index',0,'relative_path','', ...
    'sha256','','row_count',0,'column_count',0),1,expectedParticles);
for index=1:expectedParticles
    feature=cpt.feature(expectedTags{index});
    expectedPath=fullfile(runtimeDir,expectedFileNames{index});
    expectedTime=releaseTimeExpressions{index};
    assert(strcmp(char(feature.getString('Filename')),expectedPath), ...
        'Release feature %s filename differs from its particle file.', ...
        expectedTags{index});
    assert(strcmp(char(feature.getString('rt')),expectedTime), ...
        'Release feature %s birth time differs from its frozen source row.', ...
        expectedTags{index});
    assert(strcmp(char(feature.getString('icolp')),'0') && ...
        strcmp(char(feature.getString('VelocitySpecification')), ...
        'SpecifyVelocity') && ...
        strcmp(char(feature.getString('InitialVelocity')),'FromFile') && ...
        strcmp(char(feature.getString('icolv')),'3'), ...
        'Release feature %s attributes differ from the fixed import contract.', ...
        expectedTags{index});
    actualReleaseData=readmatrix(expectedPath,'FileType','text', ...
        'Delimiter',char(9));
    expectedReleaseData=[initialPositionMm(index,:) initialVelocityMS(index,:)];
    actualReleaseShape=size(actualReleaseData);
    assert(isequal(actualReleaseShape,[1 6]), ...
        'Release file %03d shape is %s; expected [1 6].', ...
        index,mat2str(actualReleaseShape));
    actualNonFiniteIndices=find(~isfinite(actualReleaseData));
    assert(isempty(actualNonFiniteIndices), ...
        'Release file %03d has non-finite linear indices %s.', ...
        index,mat2str(actualNonFiniteIndices(:).'));
    actualReleaseMaxAbsError=max( ...
        abs(actualReleaseData-expectedReleaseData),[],'all');
    assert(actualReleaseMaxAbsError<1e-12, ...
        'Release file %03d max abs error %.17g exceeds 1e-12.', ...
        index,actualReleaseMaxAbsError);
    releaseFiles(index)=struct( ...
        'particle_index',index, ...
        'relative_path',strrep(fullfile('runtime',expectedFileNames{index}), ...
            '\','/'), ...
        'sha256',sha256File(expectedPath), ...
        'row_count',1, ...
        'column_count',6);
end
studyTags=cell(model.study.tags());
solutionTags=cell(model.sol.tags());
assert(~any(strcmp(featureTags,'ef1')), ...
    'Release-construction gate crossed into Electric Force construction.');
assert(~any(strcmp(studyTags,'std2')), ...
    'Release-construction gate crossed into the particle Study.');
assert(~any(strcmp(solutionTags,'sol2')), ...
    'Release-construction gate crossed into the particle Solver.');
assert(any(strcmp(studyTags,'std1')) && any(strcmp(solutionTags,'sol1')), ...
    'Release-construction gate did not preserve the stationary-field precondition.');

modelDirectory=fileparts(control.model_path);
if ~isfolder(modelDirectory),mkdir(modelDirectory);end
model.save(control.model_path);
result=struct( ...
    'schema_version',1, ...
    'role','rf_release_construction_gate_result', ...
    'status','success', ...
    'run_id',requireText(runConfig,'run_id'), ...
    'particle_table_sha256',sha256File(requireExistingFile( ...
        requireStruct(runConfig,'inputs'),'particle_table')), ...
    'particles',expectedParticles, ...
    'release_tag_count',numel(releaseTags), ...
    'release_file_count',numel(releaseFiles), ...
    'release_files',releaseFiles, ...
    'birth_time_count',numel(ions(:,1)), ...
    'unique_birth_time_count',numel(unique(ions(:,1))), ...
    'unique_release_time_expression_count', ...
        numel(unique(releaseTimeExpressions)), ...
    'first_release_tag',releaseTags{1}, ...
    'last_release_tag',releaseTags{end}, ...
    'breadcrumb_count',breadcrumbSequence, ...
    'stationary_study_present',any(strcmp(studyTags,'std1')), ...
    'stationary_solver_present',any(strcmp(solutionTags,'sol1')), ...
    'electric_force_present',any(strcmp(featureTags,'ef1')), ...
    'particle_study_present',any(strcmp(studyTags,'std2')), ...
    'particle_solver_present',any(strcmp(solutionTags,'sol2')), ...
    'model_path',control.model_path);
resultDirectory=fileparts(control.result_path);
if ~isfolder(resultDirectory),mkdir(resultDirectory);end
writeTextFileChecked(control.result_path,'w', ...
    jsonencode(result,'PrettyPrint',true), ...
    'release-construction result');
end

function digest=sha256File(path)
calculator=java.security.MessageDigest.getInstance('SHA-256');
fileObject=java.io.File(path);
bytes=java.nio.file.Files.readAllBytes(fileObject.toPath());
calculator.update(bytes);
raw=typecast(calculator.digest(),'uint8');
digest=lower(reshape(dec2hex(raw,2).',1,[]));
end

function writeTextFileChecked(path,mode,text,role)
fid=fopen(path,mode);
assert(fid>=0,'Could not open %s for checked write: %s',role,path);
try
    written=fprintf(fid,'%s',text);
catch ME
    fclose(fid);
    rethrow(ME)
end
closeStatus=fclose(fid);
assert(written==numel(text), ...
    'Checked %s write was incomplete: %s',role,path);
assert(closeStatus==0, ...
    'Checked %s close/flush failed: %s',role,path);
end
