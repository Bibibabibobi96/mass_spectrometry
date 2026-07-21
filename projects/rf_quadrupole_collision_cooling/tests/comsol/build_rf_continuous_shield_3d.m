% Solve one 3D unit-RF field case inside a continuous grounded cylindrical shield.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('RF_SHIELD_3D_FIELD_CSV');
contractPath = getenv('RF_SHIELD_CONTRACT');
resolvedPath = getenv('RF_SHIELD_RF_RESOLVED');
shieldRadius = str2double(getenv('RF_SHIELD_INNER_RADIUS_MM'));
meshHmax = str2double(getenv('RF_SHIELD_MESH_HMAX_MM'));
globalMeshAutoLevel = str2double(getenv('RF_SHIELD_GLOBAL_MESH_AUTO_LEVEL'));
particleTablePath = getenv('RF_SHIELD_PARTICLE_TABLE');
particleEventsCsv = getenv('RF_SHIELD_PARTICLE_EVENTS_CSV');
particleSummaryJson = getenv('RF_SHIELD_PARTICLE_SUMMARY_JSON');
particleRuntimeDir = getenv('RF_SHIELD_PARTICLE_RUNTIME_DIR');
particleEnabled = ~isempty(particleTablePath);
assert(~isempty(reportPath) && ~isempty(outputCsv) && ~isempty(contractPath) && ~isempty(resolvedPath), ...
    'RF shield 3D environment is incomplete.');
assert(isfinite(shieldRadius) && shieldRadius > 0, 'RF shield radius must be positive.');
assert(isfinite(meshHmax) && meshHmax > 0, 'RF shield mesh hmax must be positive.');
fid = fopen(reportPath,'w'); assert(fid>=0,'Could not create task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid,'TASK=RF_CONTINUOUS_SHIELD_3D\nSHIELD_INNER_RADIUS_MM=%.17g\nMESH_HMAX_MM=%.17g\n',shieldRadius,meshHmax);

try
    contract = jsondecode(fileread(contractPath));
    resolved = jsondecode(fileread(resolvedPath));
    screen = contract.three_dimensional_fringe_field_screen;
    if ~isfinite(globalMeshAutoLevel), globalMeshAutoLevel=screen.global_mesh_auto_level; end
    assert(any(screen.global_mesh_auto_level_particle_stability_sequence(:)==globalMeshAutoLevel),'Global mesh auto level is outside the frozen sequence.');
    assert(any(abs(screen.inner_radius_mm(:)-shieldRadius)<1e-12),'Shield radius is outside the retained 3D candidates.');
    assert(any(abs(screen.local_maximum_element_size_mm(:)-meshHmax)<1e-12),'Mesh hmax is outside the frozen 3D sequence.');
    g = resolved.geometry_mm;
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = 'RF_SHIELD_3D';
    if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    model.label(sprintf('RF continuous grounded shield 3D R=%.6g mm',shieldRadius));
    comp = model.component.create('comp1',true);
    geom = comp.geom.create('geom1',3); geom.lengthUnit('mm');

    modelZMin = 0.0;
    modelZMax = g.exit_enclosure_front_wall_end_z;
    numericalWall = 1.0;
    geom.feature.create('vac','Cylinder'); geom.feature('vac').set('r',sprintf('%.17g[mm]',shieldRadius));
    geom.feature('vac').set('h',sprintf('%.17g[mm]',modelZMax-modelZMin)); geom.feature('vac').set('pos',{'0','0',sprintf('%.17g[mm]',modelZMin)}); geom.feature('vac').set('selresult','on');
    geom.feature.create('work','Cylinder'); geom.feature('work').set('r',sprintf('%.17g[mm]',screen.local_mesh_partition_radius_mm));
    geom.feature('work').set('h',sprintf('%.17g[mm]',screen.local_mesh_partition_z_max_mm-screen.local_mesh_partition_z_min_mm)); geom.feature('work').set('pos',{'0','0',sprintf('%.17g[mm]',screen.local_mesh_partition_z_min_mm)}); geom.feature('work').set('selresult','on');
    geom.feature.create('univac','Union'); geom.feature('univac').selection('input').set({'vac','work'}); geom.feature('univac').set('intbnd',true); geom.feature('univac').set('selresult','on');

    rodTags = cell(1,4);
    for k=1:4
        rodTags{k}=sprintf('rod%d',k); angle=(k-1)*90;
        geom.feature.create(rodTags{k},'Cylinder'); geom.feature(rodTags{k}).set('r',sprintf('%.17g[mm]',g.rod_radius));
        geom.feature(rodTags{k}).set('h',sprintf('%.17g[mm]',g.rod_length));
        geom.feature(rodTags{k}).set('pos',{sprintf('%.17g[mm]',g.rod_center_radius*cosd(angle)),sprintf('%.17g[mm]',g.rod_center_radius*sind(angle)),sprintf('%.17g[mm]',g.rod_z_min)});
        geom.feature(rodTags{k}).set('selresult','on');
    end
    geom.feature.create('shieldO','Cylinder'); geom.feature('shieldO').set('r',sprintf('%.17g[mm]',shieldRadius+numericalWall));
    geom.feature('shieldO').set('h',sprintf('%.17g[mm]',g.exit_enclosure_z_min-g.entrance_plate_z_max)); geom.feature('shieldO').set('pos',{'0','0',sprintf('%.17g[mm]',g.entrance_plate_z_max)});
    geom.feature.create('shieldH','Cylinder'); geom.feature('shieldH').set('r',sprintf('%.17g[mm]',shieldRadius));
    geom.feature('shieldH').set('h',sprintf('%.17g[mm]',g.exit_enclosure_z_min-g.entrance_plate_z_max)); geom.feature('shieldH').set('pos',{'0','0',sprintf('%.17g[mm]',g.entrance_plate_z_max)});
    geom.feature.create('shield','Difference'); geom.feature('shield').selection('input').set({'shieldO'}); geom.feature('shield').selection('input2').set({'shieldH'}); geom.feature('shield').set('selresult','on');
    add_annular_plate(geom,'entrance',shieldRadius+numericalWall,g.entrance_aperture_radius,g.entrance_plate_z_min,g.entrance_plate_z_max-g.entrance_plate_z_min);
    add_annular_plate(geom,'exit',shieldRadius+numericalWall,g.exit_aperture_radius,g.exit_enclosure_z_min,g.exit_enclosure_front_wall_end_z-g.exit_enclosure_z_min);
    geom.run;

    solidTags=[rodTags,{'shield','entrance','exit'}];
    solidDomains=cellfun(@(name)['geom1_' name '_dom'],solidTags,'UniformOutput',false);
    comp.selection.create('sel_vac','Complement'); comp.selection('sel_vac').set('input',solidDomains);
    material=model.material.create('mat_vac','Common'); material.selection.named('sel_vac'); material.propertyGroup('def').set('relpermittivity',{'1'});
    for index=1:numel(solidTags)
        name=solidTags{index}; comp.selection.create(['selb_' name],'Adjacent'); comp.selection(['selb_' name]).set('input',{['geom1_' name '_dom']});
    end
    es=comp.physics.create('es','Electrostatics','geom1'); es.selection.named('sel_vac');
    for k=1:4
        potential=es.create(sprintf('pot_rod%d',k),'ElectricPotential',2); potential.selection.named(sprintf('selb_rod%d',k)); potential.set('V0',sprintf('%d[V]',100*(-1)^(k+1)));
    end
    for name={'shield','entrance','exit'}
        potential=es.create(['pot_' name{1}],'ElectricPotential',2); potential.selection.named(['selb_' name{1}]); potential.set('V0','0[V]');
    end

    mesh=comp.mesh.create('mesh1'); mesh.feature('size').set('hauto',globalMeshAutoLevel);
    mesh.feature.create('szwork','Size'); mesh.feature('szwork').selection.geom('geom1',3); mesh.feature('szwork').selection.named('geom1_work_dom');
    mesh.feature('szwork').set('custom','on'); mesh.feature('szwork').set('hmaxactive',true); mesh.feature('szwork').set('hmax',sprintf('%.17g[mm]',meshHmax));
    mesh.feature.create('ftet1','FreeTet'); mesh.run;
    meshInfo=mphmeshstats(model,'mesh1');
    fprintf(fid,'GLOBAL_MESH_AUTO_LEVEL=%d\nMESH_ISEMPTY=%d\nMESH_ISCOMPLETE=%d\nMESH_HASPROBLEMS=%d\nMESH_TETRAHEDRA=%d\n',globalMeshAutoLevel,meshInfo.isempty,meshInfo.iscomplete,meshInfo.hasproblems,meshInfo.numelem(2));
    assert(~meshInfo.isempty && meshInfo.iscomplete && ~meshInfo.hasproblems,'3D RF shield mesh gate failed.');
    study=model.study.create('std1'); study.create('stat','Stationary'); solution=model.sol.create('sol1'); solution.study('std1'); solution.createAutoSequence('std1'); solution.attach('std1'); solution.runAll;

    fractions=screen.sample_radius_fraction_of_r0(:); zValues=screen.sample_z_mm(:); nTheta=screen.azimuth_samples_per_radius;
    inset=screen.boundary_evaluation_inset_mm; theta=(0:nTheta-1)'*(2*pi/nTheta); nominalRadius=[]; evaluationRadius=[]; thetaAll=[]; nominalZ=[]; evaluationZ=[];
    for zIndex=1:numel(zValues)
        for radiusIndex=1:numel(fractions)
            requestedRadius=fractions(radiusIndex)*g.field_radius_r0;
            evaluatedRadius=requestedRadius; if abs(requestedRadius-g.exit_aperture_radius)<1e-12, evaluatedRadius=requestedRadius-inset; end
            requestedZ=zValues(zIndex); evaluatedZ=requestedZ;
            if abs(requestedZ-g.exit_enclosure_z_min)<1e-12 || abs(requestedZ-g.exit_enclosure_front_wall_end_z)<1e-12, evaluatedZ=requestedZ-inset; end
            nominalRadius=[nominalRadius;repmat(requestedRadius,nTheta,1)]; %#ok<AGROW>
            evaluationRadius=[evaluationRadius;repmat(evaluatedRadius,nTheta,1)]; %#ok<AGROW>
            thetaAll=[thetaAll;theta]; %#ok<AGROW>
            nominalZ=[nominalZ;repmat(requestedZ,nTheta,1)]; %#ok<AGROW>
            evaluationZ=[evaluationZ;repmat(evaluatedZ,nTheta,1)]; %#ok<AGROW>
        end
    end
    x=evaluationRadius.*cos(thetaAll); y=evaluationRadius.*sin(thetaAll);
    [V,Ex,Ey,Ez]=mphinterp(model,{'V','-d(V,x)','-d(V,y)','-d(V,z)'},'coord',[x.';y.';evaluationZ.'],'dataset','dset1','matherr','on');
    samples=table(repmat(shieldRadius,numel(x),1),repmat(meshHmax,numel(x),1),nominalZ,evaluationZ,nominalRadius,evaluationRadius,thetaAll,x,y,V(:),Ex(:),Ey(:),Ez(:), ...
        'VariableNames',{'shield_inner_radius_mm','mesh_hmax_mm','sample_z_mm','evaluation_z_mm','sample_radius_mm','evaluation_radius_mm','theta_rad','x_mm','y_mm','potential_V','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m'});
    outputDir=fileparts(outputCsv); if ~isfolder(outputDir),mkdir(outputDir);end; writetable(samples,outputCsv);
    if particleEnabled
        assert(~isempty(particleEventsCsv) && ~isempty(particleSummaryJson) && ~isempty(particleRuntimeDir),'RF shield particle outputs are incomplete.');
        [events,particleSummary]=run_particle_diagnostic(model,comp,screen,contract.n100_transport_screen,g,particleTablePath,particleRuntimeDir);
        eventDir=fileparts(particleEventsCsv); if ~isfolder(eventDir),mkdir(eventDir);end; writetable(events,particleEventsCsv);
        summaryFile=fopen(particleSummaryJson,'w'); assert(summaryFile>=0,'Could not create particle summary.'); fprintf(summaryFile,'%s',jsonencode(particleSummary,'PrettyPrint',true)); fclose(summaryFile);
        fprintf(fid,'PARTICLE_ROWS=%d\nPARTICLE_TRANSMITTED=%d\n',height(events),particleSummary.transmitted);
    end
    fprintf(fid,'SAMPLE_ROWS=%d\nPARTICLE_TRACKING=%d\nMODEL_SAVED=false\nSTATUS=PASS\n',height(samples),particleEnabled);
catch exception
    fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off')); rethrow(exception)
end
clear cleanup

function add_annular_plate(geom,tag,outerRadius,holeRadius,zStart,thickness)
geom.feature.create([tag 'O'],'Cylinder'); geom.feature([tag 'O']).set('r',sprintf('%.17g[mm]',outerRadius)); geom.feature([tag 'O']).set('h',sprintf('%.17g[mm]',thickness)); geom.feature([tag 'O']).set('pos',{'0','0',sprintf('%.17g[mm]',zStart)});
geom.feature.create([tag 'H'],'Cylinder'); geom.feature([tag 'H']).set('r',sprintf('%.17g[mm]',holeRadius)); geom.feature([tag 'H']).set('h',sprintf('%.17g[mm]',thickness)); geom.feature([tag 'H']).set('pos',{'0','0',sprintf('%.17g[mm]',zStart)});
geom.feature.create(tag,'Difference'); geom.feature(tag).selection('input').set({[tag 'O']}); geom.feature(tag).selection('input2').set({[tag 'H']}); geom.feature(tag).set('selresult','on');
end

function [events,summary]=run_particle_diagnostic(model,comp,screen,transport,g,particleTablePath,runtimeDir)
ions=readmatrix(particleTablePath,'FileType','text','Delimiter',',');
assert(size(ions,1)==transport.particle_count && size(ions,2)==11,'Frozen N=100 ION table shape mismatch.');
assert(all(abs(ions(:,2)-ions(1,2))<1e-12) && all(abs(ions(:,3)-ions(1,3))<1e-12),'One particle run requires one mass and charge state.');
if ~isfolder(runtimeDir),mkdir(runtimeDir);end
cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1'); cpt.label('Continuous-shield paired N=100 diagnostic'); cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp',sprintf('%.17g[kg]',ions(1,2)*1.66053906660e-27)); cpt.feature('pp1').set('Z',sprintf('%d',round(ions(1,3))));
initialPosition=zeros(size(ions,1),3); initialVelocity=zeros(size(ions,1),3);
for index=1:size(ions,1)
    speed=sqrt(2*ions(index,9)*1.602176634e-19/(ions(index,2)*1.66053906660e-27));
    az=deg2rad(ions(index,7)); el=deg2rad(ions(index,8)); vSim=[speed*cos(el)*cos(az),speed*cos(el)*sin(az),speed*sin(el)];
    releaseData=[ions(index,6),-ions(index,5),ions(index,4),-vSim(2),-vSim(3),vSim(1)];
    initialPosition(index,:)=releaseData(1:3); initialVelocity(index,:)=releaseData(4:6);
    releasePath=fullfile(runtimeDir,sprintf('particle_%03d.txt',index)); writematrix(releaseData,releasePath,'Delimiter','tab');
    rel=cpt.create(sprintf('rel%03d',index),'ReleaseFromDataFile',-1); rel.set('Filename',releasePath); rel.set('icolp','0'); rel.set('VelocitySpecification','SpecifyVelocity'); rel.set('InitialVelocity','FromFile'); rel.set('icolv','3'); rel.set('rt',sprintf('%.17g[us]',ions(index,1))); rel.importData();
end
scale=transport.rf_peak_V/100.0; frequency=transport.rf_frequency_Hz; phase=transport.rf_phase_rad;
ef=cpt.create('ef1','ElectricForce',3); ef.selection.named('sel_vac'); ef.set('E_src','userdef');
ef.set('E',{sprintf('%.17g*es.Ex*sin(2*pi*%.17g[Hz]*t+%.17g)',scale,frequency,phase),sprintf('%.17g*es.Ey*sin(2*pi*%.17g[Hz]*t+%.17g)',scale,frequency,phase),sprintf('%.17g*es.Ez*sin(2*pi*%.17g[Hz]*t+%.17g)',scale,frequency,phase)});
std2=model.study.create('std2'); time=std2.create('time1','Transient'); dt=1/frequency/transport.rf_steps_per_period; tmax=(max(ions(:,1))+transport.maximum_particle_age_us)*1e-6;
time.set('tlist',sprintf('range(0,%.17g,%.17g)',dt,tmax)); time.setEntry('activate','es',false); time.setEntry('activate','cpt',true);
for index=1:size(ions,1), cpt.feature(sprintf('rel%03d',index)).set('StudyStep','std2/time1'); end; cpt.feature('pp1').set('StudyStep','std2/time1');
sol2=model.sol.create('sol2'); sol2.study('std2'); sol2.createAutoSequence('std2'); sol2.feature('v1').set('notsolmethod','sol'); sol2.feature('v1').set('notsol','sol1'); sol2.attach('std2'); sol2.runAll;
pdset=model.result.dataset.create('pdset1','Particle'); pdset.set('solution','sol2'); pd=mphparticle(model,'dataset','pdset1');
x=squeeze(pd.p(:,:,1)); y=squeeze(pd.p(:,:,2)); z=squeeze(pd.p(:,:,3)); vx=squeeze(pd.v(:,:,1)); vy=squeeze(pd.v(:,:,2)); vz=squeeze(pd.v(:,:,3));
assert(size(z,2)==size(ions,1),'Solved particle count mismatch.'); radial=sqrt(x.^2+y.^2); handoffPlane=transport.nominal_handoff_z_mm-transport.handoff_evaluation_inset_mm;
rows=cell(size(ions,1),19); transmitted=false(size(ions,1),1);
for index=1:size(ions,1)
    valid=find(isfinite(x(:,index)) & isfinite(y(:,index)) & isfinite(z(:,index)) & isfinite(vx(:,index)) & isfinite(vy(:,index)) & isfinite(vz(:,index)));
    assert(~isempty(valid),'Particle %d has no finite state.',index);
    [state,found]=interpolate_plane(pd.t,x(:,index),y(:,index),z(:,index),vx(:,index),vy(:,index),vz(:,index),handoffPlane);
    event='terminal'; status='lost'; reason='electrode_or_boundary';
    if found
        event='handoff'; status='transmitted'; reason='none'; transmitted(index)=true; state.z_mm=transport.nominal_handoff_z_mm;
    else
        last=valid(end); state=struct('t_s',pd.t(last),'x_mm',x(last,index),'y_mm',y(last,index),'z_mm',z(last,index),'vx_m_s',vx(last,index),'vy_m_s',vy(last,index),'vz_m_s',vz(last,index));
        if state.t_s-ions(index,1)*1e-6 >= transport.maximum_particle_age_us*1e-6-dt, status='timeout'; reason='timeout'; elseif state.z_mm<0, reason='backward_escape'; end
    end
    speed2=state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2; energy=0.5*ions(index,2)*1.66053906660e-27*speed2/1.602176634e-19;
    rodRadius=radial(:,index); rodRadius(z(:,index)<g.rod_z_min | z(:,index)>g.rod_z_max)=NaN; maxRod=max(rodRadius,[],'omitnan'); maxAll=max(radial(:,index),[],'omitnan');
    rows(index,:)={index,event,status,reason,ions(index,1),state.t_s*1e6,(state.t_s-ions(index,1)*1e-6)*1e6,mod(2*pi*frequency*state.t_s+phase,2*pi),state.x_mm,state.y_mm,state.z_mm,state.vx_m_s,state.vy_m_s,state.vz_m_s,energy,hypot(state.x_mm,state.y_mm),atan2d(hypot(state.vx_m_s,state.vy_m_s),state.vz_m_s),maxRod,maxAll};
end
names={'particle_id','event','status','terminal_reason','birth_time_us','global_time_us','particle_age_us','rf_phase_rad','x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s','kinetic_energy_eV','radial_position_mm','divergence_angle_deg','max_rod_radius_mm','max_radius_mm'};
events=cell2table(rows,'VariableNames',names); accepted=events(transmitted,:);
summary=struct('schema_version',1,'role','rf_continuous_shield_n100_mesh_sensitivity_diagnostic','status','CHARACTERIZED','particles',height(events),'transmitted',sum(transmitted),'transmission',mean(transmitted),'mesh_hmax_mm',str2double(getenv('RF_SHIELD_MESH_HMAX_MM')),'shield_inner_radius_mm',str2double(getenv('RF_SHIELD_INNER_RADIUS_MM')),'rf_peak_V',transport.rf_peak_V,'rf_frequency_Hz',frequency,'rf_steps_per_period',transport.rf_steps_per_period,'handoff_evaluation_z_mm',handoffPlane,'selection_allowed',false);
if ~isempty(accepted)
    summary.mean_global_time_us=mean(accepted.global_time_us); summary.rms_radial_position_mm=sqrt(mean(accepted.radial_position_mm.^2)); summary.rms_divergence_angle_deg=sqrt(mean(accepted.divergence_angle_deg.^2)); summary.mean_kinetic_energy_eV=mean(accepted.kinetic_energy_eV);
end
end

function [state,found]=interpolate_plane(time_s,x,y,z,vx,vy,vz,planeMm)
state=struct(); found=false; valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
for index=2:numel(valid)
    a=valid(index-1); b=valid(index);
    if z(a)<planeMm && z(b)>=planeMm && z(b)>z(a)
        fraction=(planeMm-z(a))/(z(b)-z(a)); lerp=@(left,right) left+fraction*(right-left);
        state=struct('t_s',lerp(time_s(a),time_s(b)),'x_mm',lerp(x(a),x(b)),'y_mm',lerp(y(a),y(b)),'z_mm',planeMm,'vx_m_s',lerp(vx(a),vx(b)),'vy_m_s',lerp(vy(a),vy(b)),'vz_m_s',lerp(vz(a),vz(b))); found=true; return
    end
end
end
