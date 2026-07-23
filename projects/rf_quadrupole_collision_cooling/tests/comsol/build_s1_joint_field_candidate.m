% Build and solve the local RF-to-oaTOF S1 joint field, with optional sparse particle events.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('RF_OATOF_S1_FIELD_CSV');
jointPath = getenv('RF_OATOF_S1_CONTRACT');
interfacePath = getenv('RF_OATOF_INTERFACE_CONTRACT');
spatialRegistrationPath = getenv('RF_OATOF_SPATIAL_REGISTRATION');
rfResolvedPath = getenv('RF_OATOF_RF_RESOLVED');
oaBaselinePath = getenv('RF_OATOF_OA_BASELINE');
oaComsolDir = getenv('RF_OATOF_OA_COMSOL_DIR');
portWidth = str2double(getenv('RF_OATOF_PORT_WIDTH_MM'));
meshAutoLevel = str2double(getenv('RF_OATOF_MESH_AUTO_LEVEL'));
acceleratorHmax = str2double(getenv('RF_OATOF_ACCELERATOR_HMAX_MM'));
jointScope = getenv('RF_OATOF_JOINT_SCOPE');
includeRfHardware = strcmp(jointScope,'rf-oa');
downstreamBuffer = str2double(getenv('RF_OATOF_DOWNSTREAM_BUFFER_MM'));
assert(~isempty(outputCsv) && ~isempty(jointPath) && ~isempty(interfacePath) && ...
    isfile(spatialRegistrationPath), 'S1 environment is incomplete.');
assert(isfinite(portWidth) && portWidth >= 0, 'RF_OATOF_PORT_WIDTH_MM must be non-negative.');
assert(isfinite(meshAutoLevel) && meshAutoLevel == round(meshAutoLevel) && meshAutoLevel >= 1 && meshAutoLevel <= 9, ...
    'RF_OATOF_MESH_AUTO_LEVEL must be an integer from 1 through 9.');
assert(isfinite(acceleratorHmax) && acceleratorHmax > 0, ...
    'RF_OATOF_ACCELERATOR_HMAX_MM must be positive.');
assert(includeRfHardware || strcmp(jointScope,'oa-only-control'), ...
    'RF_OATOF_JOINT_SCOPE must be rf-oa or oa-only-control.');
assert(includeRfHardware || portWidth == 0, ...
    'The oa-only diagnostic is allowed only for the closed control.');
assert(isfinite(downstreamBuffer) && downstreamBuffer > 0, ...
    'RF_OATOF_DOWNSTREAM_BUFFER_MM must be positive.');
fid = fopen(reportPath, 'w'); assert(fid >= 0, 'Could not create task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=S1_LOCAL_JOINT_FIELD\nJOINT_SCOPE=%s\nPORT_WIDTH_MM=%.17g\nDOWNSTREAM_BUFFER_MM=%.17g\nEXTERNAL_VACUUM_INCLUDED=false\nMESH_AUTO_LEVEL=%d\nACCELERATOR_HMAX_MM=%.17g\n', jointScope, portWidth, downstreamBuffer, meshAutoLevel, acceleratorHmax);

try
    joint = jsondecode(fileread(jointPath));
    interface = jsondecode(fileread(interfacePath));
    spatial = jsondecode(fileread(spatialRegistrationPath));
    rf = jsondecode(fileread(rfResolvedPath));
    oa = jsondecode(fileread(oaBaselinePath));
    assert_supported_registration(joint.nominal_registration, spatial, 'S1');
    sweep = joint.port_sweep.full_width_y_mm(:);
    closedControl = joint.port_sweep.closed_control_full_width_y_mm;
    assert(any(abs(sweep-portWidth) < 1e-12) || abs(closedControl-portWidth) < 1e-12, ...
        'Requested width is outside the frozen S1 sweep and closed control.');
    portHeight = joint.port_sweep.full_height_z_mm;
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = 'RFOATOF_S1_JOINT';
    if any(strcmp(cell(ModelUtil.tags()), tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    model.label(sprintf('RF to oaTOF S1 local joint field %.3g x %.3g mm', portWidth, portHeight));
    comp = model.component.create('comp1', true);
    geom = comp.geom.create('geom1', 3); geom.lengthUnit('mm');
    p = model.param;
    g = oa.geometry_mm;
    p.set('x_accel_center', sprintf('%.17g[mm]', oa.coordinate_convention.accelerator_axis_x));
    p.set('z_accel_origin', sprintf('%.17g[mm]', g.accelerator_repeller_z));
    p.set('L_accel', sprintf('%.17g[mm]', g.L_accel));
    p.set('z_accel_grid1', sprintf('%.17g[mm]', g.accelerator_grid1_z));
    p.set('z_accel_grid2', sprintf('%.17g[mm]', g.accelerator_grid2_z));
    p.set('accel_ring_bore_half', sprintf('%.17g[mm]', g.accelerator_bore_half));
    p.set('accel_shield_half', sprintf('%.17g[mm]', g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap));
    p.set('accel_ring_gap', sprintf('%.17g[mm]', g.accelerator_insulation_gap));
    p.set('accel_shield_wall', sprintf('%.17g[mm]', g.accelerator_shield_wall));
    p.set('accel_repeller_thickness', sprintf('%.17g[mm]', g.accelerator_repeller_thickness));
    p.set('accel_ring_thickness', sprintf('%.17g[mm]', g.accelerator_ring_thickness));
    p.set('accel_shield_back_extra', sprintf('%.17g[mm]', g.accelerator_rear_clearance));
    p.set('V_grid1', sprintf('%.17g[V]', oa.electrodes_V.grid1));

    sourcePose = spatial.component_poses.rf_quadrupole_component;
    tx = sourcePose.translation_mm(1); tz = sourcePose.translation_mm(3);
    rg = rf.geometry_mm;
    rfInterfaces = rf.interfaces_mm;
    rfShieldInnerRadius = joint.local_domain.rf_shield_inner_radius_mm;
    rfShieldWall = joint.local_domain.rf_shield_numerical_wall_thickness_mm;
    fprintf(fid,'RF_SHIELD_INNER_RADIUS_MM=%.17g\nRF_SHIELD_NUMERICAL_WALL_MM=%.17g\n',rfShieldInnerRadius,rfShieldWall);
    vacuumInputs = {};
    if includeRfHardware
        geom.feature.create('rfvac', 'Cylinder'); geom.feature('rfvac').set('axis',{'1','0','0'});
        geom.feature('rfvac').set('r',sprintf('%.17g[mm]',rfShieldInnerRadius));
        geom.feature('rfvac').set('h',sprintf('%.17g[mm]',joint.local_domain.rf_local_z_max_mm-joint.local_domain.rf_local_z_min_mm));
        geom.feature('rfvac').set('pos',{sprintf('%.17g[mm]',tx+joint.local_domain.rf_local_z_min_mm),'0',sprintf('%.17g[mm]',tz)});
        geom.feature('rfvac').set('selresult','on'); vacuumInputs{end+1}='rfvac';
    end
    oaVacHalf = g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap;
    oaVacZMin = g.accelerator_repeller_z-g.accelerator_repeller_thickness-g.accelerator_rear_clearance;
    oaVacZMax = g.accelerator_grid2_z+downstreamBuffer;
    geom.feature.create('oavac', 'Block'); geom.feature('oavac').set('selresult', 'on');
    geom.feature('oavac').set('size', {sprintf('%.17g[mm]',2*oaVacHalf),sprintf('%.17g[mm]',2*oaVacHalf),sprintf('%.17g[mm]',oaVacZMax-oaVacZMin)});
    geom.feature('oavac').set('pos', {sprintf('%.17g[mm]',oa.coordinate_convention.accelerator_axis_x-oaVacHalf),sprintf('%.17g[mm]',-oaVacHalf),sprintf('%.17g[mm]',oaVacZMin)});
    vacuumInputs{end+1}='oavac';
    if includeRfHardware && portWidth>0
        oaShieldOuterX = oa.coordinate_convention.accelerator_axis_x-(oaVacHalf+g.accelerator_shield_wall);
        oaShieldInnerX = oa.coordinate_convention.accelerator_axis_x-oaVacHalf;
        geom.feature.create('portvac','Block'); geom.feature('portvac').set('selresult','on');
        geom.feature('portvac').set('size',{sprintf('%.17g[mm]',oaShieldInnerX-oaShieldOuterX),sprintf('%.17g[mm]',portWidth),sprintf('%.17g[mm]',portHeight)});
        geom.feature('portvac').set('pos',{sprintf('%.17g[mm]',oaShieldOuterX),sprintf('%.17g[mm]',-portWidth/2),sprintf('%.17g[mm]',joint.port_sweep.center_z_mm-portHeight/2)});
        vacuumInputs{end+1}='portvac';
    end
    source = oa.particle_source;
    geom.feature.create('relvol','Block'); geom.feature('relvol').set('selresult','on');
    geom.feature('relvol').set('size',{sprintf('%.17g[mm]',source.size_x_mm),sprintf('%.17g[mm]',source.size_y_mm),sprintf('%.17g[mm]',source.size_z_mm)});
    geom.feature('relvol').set('pos',{sprintf('%.17g[mm]',source.center_x_mm-source.size_x_mm/2),sprintf('%.17g[mm]',source.center_y_mm-source.size_y_mm/2),sprintf('%.17g[mm]',source.center_z_mm-source.size_z_mm/2)});

    for gridSpec = {{'wp_grid1',g.accelerator_grid1_z,2*(g.accelerator_bore_half+g.accelerator_ring_width)}, ...
                    {'wp_grid2',g.accelerator_grid2_z,2*(g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap)}}
        item = gridSpec{1}; wp = geom.feature.create(item{1}, 'WorkPlane'); wp.set('quickplane','xy'); wp.set('quickz',sprintf('%.17g[mm]',item{2}));
        wp.geom.feature.create('r1','Rectangle'); wp.geom.feature('r1').set('size',{sprintf('%.17g[mm]',item{3}),sprintf('%.17g[mm]',item{3})});
        wp.geom.feature('r1').set('pos',{sprintf('%.17g[mm]',oa.coordinate_convention.accelerator_axis_x-item{3}/2),sprintf('%.17g[mm]',-item{3}/2)});
    end
    geom.feature.create('univacgrid','Union'); geom.feature('univacgrid').selection('input').set([vacuumInputs,{'wp_grid1','wp_grid2','relvol'}]); geom.feature('univacgrid').set('intbnd',true);

    assert(~isempty(oaComsolDir) && isfolder(oaComsolDir), 'Frozen oa COMSOL source directory is missing.');
    addpath(oaComsolDir);
    interfacePort = struct('enabled',portWidth>0,'full_width_y_mm',portWidth,'full_height_z_mm',portHeight,'center_z_mm',joint.port_sweep.center_z_mm);
    accelrings = oatof_build_accelerator_geometry( ...
        geom, oa.rings.accelerator_count, interfacePort);
    geom.feature('repeller').set('selresult','on');
    geom.feature('accelshield').set('selresult','on');
    for k=1:numel(accelrings), geom.feature(accelrings{k}).set('selresult','on'); end

    rodTags = {};
    rfGroundTags = {};
    if includeRfHardware
        rodTags = cell(1,4);
        for k=1:4
            rodTags{k}=sprintf('rfrod%d',k); angle=(k-1)*90;
            geom.feature.create(rodTags{k},'Cylinder'); geom.feature(rodTags{k}).set('axis',{'1','0','0'});
            geom.feature(rodTags{k}).set('r',sprintf('%.17g[mm]',rg.rod_radius)); geom.feature(rodTags{k}).set('h',sprintf('%.17g[mm]',rg.rod_length));
            geom.feature(rodTags{k}).set('pos',{sprintf('%.17g[mm]',tx+rg.rod_z_min),sprintf('%.17g[mm]',rg.rod_center_radius*cosd(angle)),sprintf('%.17g[mm]',tz+rg.rod_center_radius*sind(angle))});
            geom.feature(rodTags{k}).set('selresult','on');
        end
        geom.feature.create('rfshieldO','Cylinder'); geom.feature('rfshieldO').set('axis',{'1','0','0'}); geom.feature('rfshieldO').set('r',sprintf('%.17g[mm]',rfShieldInnerRadius+rfShieldWall)); geom.feature('rfshieldO').set('h',sprintf('%.17g[mm]',rfInterfaces.exit.plate_z_min_mm-rfInterfaces.entrance.plate_z_max_mm)); geom.feature('rfshieldO').set('pos',{sprintf('%.17g[mm]',tx+rfInterfaces.entrance.plate_z_max_mm),'0',sprintf('%.17g[mm]',tz)});
        geom.feature.create('rfshieldH','Cylinder'); geom.feature('rfshieldH').set('axis',{'1','0','0'}); geom.feature('rfshieldH').set('r',sprintf('%.17g[mm]',rfShieldInnerRadius)); geom.feature('rfshieldH').set('h',sprintf('%.17g[mm]',rfInterfaces.exit.plate_z_min_mm-rfInterfaces.entrance.plate_z_max_mm)); geom.feature('rfshieldH').set('pos',{sprintf('%.17g[mm]',tx+rfInterfaces.entrance.plate_z_max_mm),'0',sprintf('%.17g[mm]',tz)});
        geom.feature.create('rfshield','Difference'); geom.feature('rfshield').selection('input').set({'rfshieldO'}); geom.feature('rfshield').selection('input2').set({'rfshieldH'}); geom.feature('rfshield').set('selresult','on');
        add_circular_plate(geom,'rfentrance',tx+rfInterfaces.entrance.plate_z_min_mm,rfInterfaces.entrance.plate_z_max_mm-rfInterfaces.entrance.plate_z_min_mm,rfShieldInnerRadius+rfShieldWall,rfInterfaces.entrance.aperture_radius_mm,tz);
        add_circular_plate(geom,'rfexit',tx+rfInterfaces.exit.plate_z_min_mm,rfInterfaces.exit.plate_z_max_mm-rfInterfaces.exit.plate_z_min_mm,rfShieldInnerRadius+rfShieldWall,rfInterfaces.exit.aperture_radius_mm,tz);
        rfGroundTags={'rfshield','rfentrance','rfexit'};
    end
    geom.run;

    solidTags = [{'repeller','accelshield'}, rfGroundTags, accelrings, rodTags];
    solidSelections = cellfun(@(name) ['geom1_' name '_dom'],solidTags,'UniformOutput',false);
    comp.selection.create('sel_vac','Complement'); comp.selection('sel_vac').set('input',solidSelections);
    mat=model.material.create('mat_vac','Common'); mat.selection.named('sel_vac'); mat.propertyGroup('def').set('relpermittivity',{'1'});
    for index=1:numel(solidTags)
        name=solidTags{index}; comp.selection.create(['selb_' name],'Adjacent'); comp.selection(['selb_' name]).set('input',{['geom1_' name '_dom']});
    end
    create_grid_selection(comp,'selb_grid1',g.accelerator_grid1_z,oa.coordinate_convention.accelerator_axis_x,g.accelerator_bore_half+g.accelerator_ring_width,0.2);
    create_grid_selection(comp,'selb_grid2',g.accelerator_grid2_z,oa.coordinate_convention.accelerator_axis_x,g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap,0.05);
    comp.selection.create('sel_accel_mesh','Box'); comp.selection('sel_accel_mesh').geom('geom1',3);
    comp.selection('sel_accel_mesh').set('xmin',oa.coordinate_convention.accelerator_axis_x-(g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap));
    comp.selection('sel_accel_mesh').set('xmax',oa.coordinate_convention.accelerator_axis_x+(g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap));
    comp.selection('sel_accel_mesh').set('ymin',-(g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap));
    comp.selection('sel_accel_mesh').set('ymax',g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap);
    comp.selection('sel_accel_mesh').set('zmin',g.accelerator_repeller_z); comp.selection('sel_accel_mesh').set('zmax',g.accelerator_grid2_z);
    comp.selection('sel_accel_mesh').set('condition','inside');

    esStatic=comp.physics.create('es_static','Electrostatics','geom1'); esStatic.selection.named('sel_vac');
    esStatic.field('electricpotential').field('V'); esStatic.field('electricpotential').component({'V'});
    esRf=comp.physics.create('es_rf','Electrostatics','geom1'); esRf.selection.named('sel_vac');
    esRf.field('electricpotential').field('Vrf'); esRf.field('electricpotential').component({'Vrf'});
    set_potential(esStatic,'repeller','selb_repeller',oa.electrodes_V.repeller);
    set_potential(esStatic,'accelshield','selb_accelshield',0);
    if includeRfHardware
        for k=1:numel(rfGroundTags)
            set_potential(esStatic,rfGroundTags{k},['selb_' rfGroundTags{k}],0);
        end
    end
    set_potential(esStatic,'grid1','selb_grid1',oa.electrodes_V.grid1); set_potential(esStatic,'grid2','selb_grid2',0);
    for k=1:5, set_potential(esStatic,sprintf('ring%d',k),sprintf('selb_accelring_%d',k),oa.electrodes_V.grid1*(1-k/6)); end
    if includeRfHardware
        for k=1:4
            set_potential(esStatic,sprintf('rfrod%d',k),sprintf('selb_rfrod%d',k),0);
        end
    end
    groundedRfTags = [{'repeller','accelshield'}, rfGroundTags, accelrings];
    for name=groundedRfTags, set_potential(esRf,['g_' name{1}],['selb_' name{1}],0); end
    set_potential(esRf,'g_grid1','selb_grid1',0); set_potential(esRf,'g_grid2','selb_grid2',0);
    if includeRfHardware
        for k=1:4
            set_potential(esRf,sprintf('u_rfrod%d',k),sprintf('selb_rfrod%d',k),100*(-1)^(k+1));
        end
    end

    mesh=comp.mesh.create('mesh1'); mesh.feature('size').set('hauto',meshAutoLevel);
    mesh.feature.create('szrelease','Size'); mesh.feature('szrelease').selection.geom('geom1',3); mesh.feature('szrelease').selection.named('geom1_relvol_dom'); mesh.feature('szrelease').set('custom','on'); mesh.feature('szrelease').set('hmaxactive',true); mesh.feature('szrelease').set('hmax','0.1[mm]');
    mesh.feature.create('szaccel','Size'); mesh.feature('szaccel').selection.geom('geom1',3); mesh.feature('szaccel').selection.named('sel_accel_mesh'); mesh.feature('szaccel').set('custom','on'); mesh.feature('szaccel').set('hmaxactive',true); mesh.feature('szaccel').set('hmax',sprintf('%.17g[mm]',acceleratorHmax));
    if includeRfHardware && portWidth>0
        mesh.feature.create('szconnector','Size'); mesh.feature('szconnector').selection.geom('geom1',3); mesh.feature('szconnector').selection.named('geom1_portvac_dom'); mesh.feature('szconnector').set('custom','on'); mesh.feature('szconnector').set('hmaxactive',true); mesh.feature('szconnector').set('hmax',sprintf('%.17g[mm]',joint.numerical_qualification.connector_diagnostic_hmax_mm));
    end
    mesh.feature.create('ftet1','FreeTet'); mesh.run;
    study=model.study.create('std1'); study.create('stat','Stationary'); solution=model.sol.create('sol1'); solution.study('std1'); solution.createAutoSequence('std1'); solution.attach('std1'); solution.runAll;

    positiveY=unique([0:0.25:3.5,3.6,portWidth/2]); yOffsets=[-fliplr(positiveY(2:end)),positiveY];
    z1=linspace(g.accelerator_repeller_z+0.1,g.accelerator_grid1_z-0.1,29); z2=linspace(g.accelerator_grid1_z+0.1,g.accelerator_grid2_z-0.1,69); zSamples=[z1,z2];
    nY=numel(yOffsets); nZ=numel(zSamples); x=repmat(oa.coordinate_convention.accelerator_axis_x,nY*nZ,1); y=repelem(yOffsets(:),nZ); z=repmat(zSamples(:),nY,1);
    fieldExpressions={'-d(V,x)','-d(V,y)','-d(V,z)','V','-d(Vrf,x)','-d(Vrf,y)','-d(Vrf,z)','Vrf'};
    [sEx,sEy,sEz,sV,rEx,rEy,rEz,rV]=mphinterp(model,fieldExpressions,'coord',[x.';y.';z.'],'dataset','dset1','matherr','on');
    profile=table(repmat("accelerator_profile",numel(x),1),x,y,z,sEx(:),sEy(:),sEz(:),sV(:),rEx(:),rEy(:),rEz(:),rV(:),repmat(portWidth,numel(x),1),repmat(portHeight,numel(x),1), ...
        'VariableNames',{'sample_type','x_mm','y_mm','z_mm','static_Ex_V_per_m','static_Ey_V_per_m','static_Ez_V_per_m','static_potential_V','rf_Ex_V_per_m','rf_Ey_V_per_m','rf_Ez_V_per_m','rf_potential_V','port_full_width_y_mm','port_full_height_z_mm'});
    if portWidth>0
        xAxis=linspace(tx+rg.rod_z_max,oa.coordinate_convention.accelerator_axis_x,121).'; yAxis=zeros(size(xAxis)); zAxis=repmat(joint.port_sweep.center_z_mm,size(xAxis));
        [sEx,sEy,sEz,sV,rEx,rEy,rEz,rV]=mphinterp(model,fieldExpressions,'coord',[xAxis.';yAxis.';zAxis.'],'dataset','dset1','matherr','on');
        injection=table(repmat("injection_axis",numel(xAxis),1),xAxis,yAxis,zAxis,sEx(:),sEy(:),sEz(:),sV(:),rEx(:),rEy(:),rEz(:),rV(:),repmat(portWidth,numel(xAxis),1),repmat(portHeight,numel(xAxis),1),'VariableNames',profile.Properties.VariableNames);
    else
        injection=profile([],:);
    end
    outputDir=fileparts(outputCsv); if ~isfolder(outputDir),mkdir(outputDir);end; writetable([profile;injection],outputCsv);
    particleInput=getenv('RF_OATOF_S1_PARTICLE_INPUT');
    particleRows=0; captureRows=0;
    if ~isempty(particleInput)
        particleOutput=getenv('RF_OATOF_S1_PARTICLE_OUTPUT');
        captureOutput=getenv('RF_OATOF_S1_CAPTURE_OUTPUT');
        pulseTimeUs=str2double(getenv('RF_OATOF_PULSE_TIME_US'));
        pulseWidthUs=str2double(getenv('RF_OATOF_PULSE_WIDTH_US'));
        assert(portWidth>0 && includeRfHardware,'S1 particles require the opened joint RF-oa geometry.');
        assert(~isempty(particleOutput) && ~isempty(captureOutput) && isfinite(pulseTimeUs) && isfinite(pulseWidthUs) && pulseWidthUs>0,'S1 particle environment is incomplete.');
        [particleEvents,captureEvents]=run_s1_particles(model,comp,particleInput,fileparts(particleOutput),joint,spatial,rf,oa,portWidth,portHeight,downstreamBuffer,pulseTimeUs,pulseWidthUs);
        writetable(particleEvents,particleOutput); particleRows=height(particleEvents);
        writetable(captureEvents,captureOutput); captureRows=height(captureEvents);
    end
    fprintf(fid,'PROFILE_ROWS=%d\nINJECTION_ROWS=%d\nPARTICLE_ROWS=%d\nCAPTURE_ROWS=%d\nMODEL_SAVED=false\nSTATUS=PASS\n',height(profile),height(injection),particleRows,captureRows);
catch exception
    fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off')); rethrow(exception)
end
clear cleanup

function assert_supported_registration(registration, spatial, expectedStage)
assert(strcmp(spatial.role,'resolved_spatial_registration_do_not_edit') && ...
    strcmp(spatial.project_semantics.stage,expectedStage), ...
    'S1 requires the authoritative resolved spatial registration.');
sourcePose = spatial.component_poses.rf_quadrupole_component;
targetPose = spatial.component_poses.oatof_global;
assert(isequal(registration.source_component_pose.rotation_component_to_instrument,sourcePose.rotation) && ...
    isequal(registration.source_component_pose.translation_mm,sourcePose.translation_mm) && ...
    isequal(registration.target_component_pose.rotation_component_to_instrument,targetPose.rotation) && ...
    isequal(registration.target_component_pose.translation_mm,targetPose.translation_mm), ...
    'S1 project inputs are stale relative to resolved spatial registration.');
sourceCenter = spatial.resolved_surfaces.source_exit.in_instrument_frame.center_mm;
targetCenter = spatial.resolved_surfaces.target_entry.in_instrument_frame.center_mm;
assert(all(abs(sourceCenter-registration.source_exit_center_instrument_mm) <= 1e-12) && ...
    all(abs(targetCenter-registration.target_entry_center_instrument_mm) <= 1e-12) && ...
    abs(targetCenter(1)-sourceCenter(1)) <= 1e-12, ...
    'S1 resolved direct-mating centers are inconsistent.');
end

function add_circular_plate(geom,tag,xStart,thickness,outerRadius,holeRadius,zCenter)
geom.feature.create([tag 'O'],'Cylinder'); geom.feature([tag 'O']).set('axis',{'1','0','0'}); geom.feature([tag 'O']).set('r',sprintf('%.17g[mm]',outerRadius)); geom.feature([tag 'O']).set('h',sprintf('%.17g[mm]',thickness)); geom.feature([tag 'O']).set('pos',{sprintf('%.17g[mm]',xStart),'0',sprintf('%.17g[mm]',zCenter)});
geom.feature.create([tag 'H'],'Cylinder'); geom.feature([tag 'H']).set('axis',{'1','0','0'}); geom.feature([tag 'H']).set('r',sprintf('%.17g[mm]',holeRadius)); geom.feature([tag 'H']).set('h',sprintf('%.17g[mm]',thickness)); geom.feature([tag 'H']).set('pos',{sprintf('%.17g[mm]',xStart),'0',sprintf('%.17g[mm]',zCenter)});
geom.feature.create(tag,'Difference'); geom.feature(tag).selection('input').set({[tag 'O']}); geom.feature(tag).selection('input2').set({[tag 'H']}); geom.feature(tag).set('selresult','on');
end

function create_grid_selection(comp,tag,zValue,xCenter,halfWidth,zHalf)
comp.selection.create(tag,'Box'); comp.selection(tag).geom('geom1',2); comp.selection(tag).set('xmin',xCenter-halfWidth); comp.selection(tag).set('xmax',xCenter+halfWidth); comp.selection(tag).set('ymin',-halfWidth); comp.selection(tag).set('ymax',halfWidth); comp.selection(tag).set('zmin',zValue-zHalf); comp.selection(tag).set('zmax',zValue+zHalf); comp.selection(tag).set('condition','allvertices');
end

function set_potential(physics,tag,selection,value)
feature=physics.create(['pot_' tag],'ElectricPotential',2); feature.selection.named(selection); feature.set('V0',sprintf('%.17g[V]',value));
end

function [events,capture]=run_s1_particles(model,comp,inputPath,runtimeDir,joint,spatial,rf,oa,portWidth,portHeight,downstreamBuffer,pulseTimeUs,pulseWidthUs)
ions=readtable(inputPath,'VariableNamingRule','preserve');
assert(height(ions)==100,'S1 physical-port runtime requires the frozen N=100 input.');
required={'particle_id','instrument_time_us','mass_amu','charge_state','frame_id','clock_epoch_id','position_x_mm','position_y_mm','position_z_mm','velocity_x_m_s','velocity_y_m_s','velocity_z_m_s'};
assert(all(ismember(required,ions.Properties.VariableNames)),'S1 canonical particle columns are incomplete.');
center=spatial.resolved_surfaces.target_entry.in_instrument_frame.center_mm;
assert(all(string(ions.frame_id)==string(joint.nominal_registration.instrument_frame)), ...
    'S1 canonical frame_id must match the joint-contract instrument frame.');
clockEpochs=unique(string(ions.clock_epoch_id));
assert(isscalar(clockEpochs) && strlength(clockEpochs(1))>0, ...
    'S1 canonical particles must use one nonempty clock epoch.');
assert(all(abs(ions.position_x_mm-center(1))<=1e-12), ...
    'S1 canonical position_x_mm must equal the physical oa-TOF entry surface; silent coordinate replacement is forbidden.');
inside=abs(ions.position_y_mm)<=portWidth/2+1e-12 & abs(ions.position_z_mm-center(3))<=portHeight/2+1e-12;
accepted=find(inside); assert(~isempty(accepted),'S1 port rejects every input particle geometrically.');
if ~isfolder(runtimeDir),mkdir(runtimeDir);end
cpt=comp.physics.create('cpt','ChargedParticleTracing','geom1'); cpt.label('S1 physical-port shared-clock pulse N=100'); cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp',sprintf('%.17g[kg]',ions.mass_amu(1)*1.66053906660e-27)); cpt.feature('pp1').set('Z',sprintf('%d',round(ions.charge_state(1))));
for solverIndex=1:numel(accepted)
    row=accepted(solverIndex); releaseData=[ions.position_x_mm(row)+joint.port_sweep.particle_release_offset_inside_outer_face_mm,ions.position_y_mm(row),ions.position_z_mm(row),ions.velocity_x_m_s(row),ions.velocity_y_m_s(row),ions.velocity_z_m_s(row)];
    releasePath=fullfile(runtimeDir,sprintf('physical_port_particle_%03d.txt',ions.particle_id(row))); writematrix(releaseData,releasePath,'Delimiter','tab');
    rel=cpt.create(sprintf('rel%03d',solverIndex),'ReleaseFromDataFile',-1); rel.set('Filename',releasePath); rel.set('icolp','0'); rel.set('VelocitySpecification','SpecifyVelocity'); rel.set('InitialVelocity','FromFile'); rel.set('icolv','3'); rel.set('rt',sprintf('%.17g[us]',ions.instrument_time_us(row))); rel.importData();
end
rfScale=rf.drive.rf_amplitude_V_zero_to_peak_per_group/100.0; frequency=rf.drive.frequency_Hz; phase=rf.drive.phase_rad;
gate=sprintf('if(t>=%.17g[us]&&t<%.17g[us],1,0)',pulseTimeUs,pulseTimeUs+pulseWidthUs);
ef=cpt.create('ef1','ElectricForce',3); ef.selection.named('sel_vac'); ef.set('E_src','userdef');
ef.set('E',{sprintf('%.17g*(-d(Vrf,x))*sin(2*pi*%.17g[Hz]*t+%.17g)+(%s)*(-d(V,x))',rfScale,frequency,phase,gate),sprintf('%.17g*(-d(Vrf,y))*sin(2*pi*%.17g[Hz]*t+%.17g)+(%s)*(-d(V,y))',rfScale,frequency,phase,gate),sprintf('%.17g*(-d(Vrf,z))*sin(2*pi*%.17g[Hz]*t+%.17g)+(%s)*(-d(V,z))',rfScale,frequency,phase,gate)});
std2=model.study.create('std2'); time=std2.create('time1','Transient'); dt=1/frequency/80; tmax=(pulseTimeUs+pulseWidthUs+8.0)*1e-6;
time.set('tlist',sprintf('range(0,%.17g,%.17g)',dt,tmax)); time.setEntry('activate','es_static',false); time.setEntry('activate','es_rf',false); time.setEntry('activate','cpt',true);
for solverIndex=1:numel(accepted),cpt.feature(sprintf('rel%03d',solverIndex)).set('StudyStep','std2/time1');end; cpt.feature('pp1').set('StudyStep','std2/time1');
sol2=model.sol.create('sol2'); sol2.study('std2'); sol2.createAutoSequence('std2'); sol2.feature('v1').set('notsolmethod','sol'); sol2.feature('v1').set('notsol','sol1'); sol2.attach('std2'); sol2.runAll;
pdset=model.result.dataset.create('pdset1','Particle'); pdset.set('solution','sol2'); pd=mphparticle(model,'dataset','pdset1');
x=squeeze(pd.p(:,:,1));y=squeeze(pd.p(:,:,2));z=squeeze(pd.p(:,:,3));vx=squeeze(pd.v(:,:,1));vy=squeeze(pd.v(:,:,2));vz=squeeze(pd.v(:,:,3));
if isvector(x),x=x(:);y=y(:);z=z(:);vx=vx(:);vy=vy(:);vz=vz(:);end
assert(size(z,2)==numel(accepted),'S1 solved particle count differs from geometric acceptance.');
plane=oa.geometry_mm.accelerator_grid2_z+downstreamBuffer-0.001; rows=cell(height(ions),17); captureRows=cell(numel(accepted),11); captureCount=0; solverIndex=0;
for row=1:height(ions)
    if ~inside(row)
        state=struct('t_s',ions.instrument_time_us(row)*1e-6,'x_mm',center(1),'y_mm',ions.position_y_mm(row),'z_mm',ions.position_z_mm(row),'vx_m_s',ions.velocity_x_m_s(row),'vy_m_s',ions.velocity_y_m_s(row),'vz_m_s',ions.velocity_z_m_s(row)); event='geometric_reject';status='lost';reason='outside_1p0_by_0p9_mm_port';
    else
        solverIndex=solverIndex+1; valid=find(isfinite(x(:,solverIndex))&isfinite(y(:,solverIndex))&isfinite(z(:,solverIndex))&isfinite(vx(:,solverIndex))&isfinite(vy(:,solverIndex))&isfinite(vz(:,solverIndex))); assert(~isempty(valid),'S1 particle has no finite state.');
        [captureState,captureFound]=interpolate_time(pd.t,x(:,solverIndex),y(:,solverIndex),z(:,solverIndex),vx(:,solverIndex),vy(:,solverIndex),vz(:,solverIndex),pulseTimeUs*1e-6);
        if captureFound
            source=oa.particle_source;
            insideReference=abs(captureState.x_mm-source.center_x_mm)<=source.size_x_mm/2+1e-12 && abs(captureState.y_mm-source.center_y_mm)<=source.size_y_mm/2+1e-12 && abs(captureState.z_mm-source.center_z_mm)<=source.size_z_mm/2+1e-12;
            captureCount=captureCount+1;
            captureRows(captureCount,:)={ions.particle_id(row),string(ions.frame_id(row)), ...
                string(ions.clock_epoch_id(row)),captureState.t_s*1e6,captureState.x_mm, ...
                captureState.y_mm,captureState.z_mm,captureState.vx_m_s, ...
                captureState.vy_m_s,captureState.vz_m_s,insideReference};
        end
        [state,found]=interpolate_z_plane(pd.t,x(:,solverIndex),y(:,solverIndex),z(:,solverIndex),vx(:,solverIndex),vy(:,solverIndex),vz(:,solverIndex),plane);
        if found,event='local_joint_exit';status='transmitted';reason='none';else,last=valid(end);state=struct('t_s',pd.t(last),'x_mm',x(last,solverIndex),'y_mm',y(last,solverIndex),'z_mm',z(last,solverIndex),'vx_m_s',vx(last,solverIndex),'vy_m_s',vy(last,solverIndex),'vz_m_s',vz(last,solverIndex));event='terminal';status='lost';reason='electrode_or_boundary';end
    end
    speed2=state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2; energy=0.5*ions.mass_amu(row)*1.66053906660e-27*speed2/1.602176634e-19;
    rows(row,:)={ions.particle_id(row),event,status,reason,string(ions.frame_id(row)), ...
        string(ions.clock_epoch_id(row)),ions.instrument_time_us(row),state.t_s*1e6, ...
        (state.t_s*1e6>=pulseTimeUs),state.x_mm,state.y_mm,state.z_mm,state.vx_m_s, ...
        state.vy_m_s,state.vz_m_s,energy,mod(2*pi*frequency*state.t_s+phase,2*pi)};
end
events=cell2table(rows,'VariableNames',{'particle_id','event','status','terminal_reason', ...
    'frame_id','clock_epoch_id','entry_instrument_time_us','instrument_time_us', ...
    'pulse_time_reached','x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s', ...
    'kinetic_energy_eV','rf_phase_rad'});
capture=cell2table(captureRows(1:captureCount,:),'VariableNames',{'particle_id', ...
    'frame_id','clock_epoch_id','instrument_time_us','x_mm','y_mm','z_mm', ...
    'vx_m_s','vy_m_s','vz_m_s','inside_oatof_ideal_reference_volume'});
end

function [state,found]=interpolate_time(time_s,x,y,z,vx,vy,vz,targetTimeS)
state=struct();found=false;valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
if isempty(valid) || targetTimeS<time_s(valid(1)) || targetTimeS>time_s(valid(end)),return,end
right=valid(find(time_s(valid)>=targetTimeS,1,'first')); left=valid(find(time_s(valid)<=targetTimeS,1,'last'));
if isempty(left)||isempty(right),return,end
if left==right,fraction=0;else,fraction=(targetTimeS-time_s(left))/(time_s(right)-time_s(left));end
lerp=@(a,b)a+fraction*(b-a); state=struct('t_s',targetTimeS,'x_mm',lerp(x(left),x(right)),'y_mm',lerp(y(left),y(right)),'z_mm',lerp(z(left),z(right)),'vx_m_s',lerp(vx(left),vx(right)),'vy_m_s',lerp(vy(left),vy(right)),'vz_m_s',lerp(vz(left),vz(right)));found=true;
end

function [state,found]=interpolate_z_plane(time_s,x,y,z,vx,vy,vz,planeMm)
state=struct();found=false;valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
for index=2:numel(valid),a=valid(index-1);b=valid(index);if z(a)<planeMm&&z(b)>=planeMm&&z(b)>z(a),fraction=(planeMm-z(a))/(z(b)-z(a));lerp=@(left,right)left+fraction*(right-left);state=struct('t_s',lerp(time_s(a),time_s(b)),'x_mm',lerp(x(a),x(b)),'y_mm',lerp(y(a),y(b)),'z_mm',planeMm,'vx_m_s',lerp(vx(a),vx(b)),'vy_m_s',lerp(vy(a),vy(b)),'vz_m_s',lerp(vz(a),vz(b)));found=true;return,end,end
end
