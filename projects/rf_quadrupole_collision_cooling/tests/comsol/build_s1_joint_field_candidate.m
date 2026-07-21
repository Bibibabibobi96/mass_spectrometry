% Build and solve the local RF-to-oaTOF S1 joint field; no particle tracing.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('RF_OATOF_S1_FIELD_CSV');
jointPath = getenv('RF_OATOF_S1_CONTRACT');
interfacePath = getenv('RF_OATOF_INTERFACE_CONTRACT');
rfResolvedPath = getenv('RF_OATOF_RF_RESOLVED');
oaBaselinePath = getenv('RF_OATOF_OA_BASELINE');
oaComsolDir = getenv('RF_OATOF_OA_COMSOL_DIR');
portWidth = str2double(getenv('RF_OATOF_PORT_WIDTH_MM'));
meshAutoLevel = str2double(getenv('RF_OATOF_MESH_AUTO_LEVEL'));
acceleratorHmax = str2double(getenv('RF_OATOF_ACCELERATOR_HMAX_MM'));
jointScope = getenv('RF_OATOF_JOINT_SCOPE');
includeRfHardware = strcmp(jointScope,'rf-oa');
downstreamBuffer = str2double(getenv('RF_OATOF_DOWNSTREAM_BUFFER_MM'));
outerVacuumMargin = str2double(getenv('RF_OATOF_OUTER_VACUUM_MARGIN_MM'));
assert(~isempty(outputCsv) && ~isempty(jointPath) && ~isempty(interfacePath), 'S1 environment is incomplete.');
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
assert(isfinite(outerVacuumMargin) && outerVacuumMargin > 0, ...
    'RF_OATOF_OUTER_VACUUM_MARGIN_MM must be positive.');
fid = fopen(reportPath, 'w'); assert(fid >= 0, 'Could not create task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=S1_LOCAL_JOINT_FIELD\nJOINT_SCOPE=%s\nPORT_WIDTH_MM=%.17g\nDOWNSTREAM_BUFFER_MM=%.17g\nOUTER_VACUUM_MARGIN_MM=%.17g\nMESH_AUTO_LEVEL=%d\nACCELERATOR_HMAX_MM=%.17g\n', jointScope, portWidth, downstreamBuffer, outerVacuumMargin, meshAutoLevel, acceleratorHmax);

try
    joint = jsondecode(fileread(jointPath));
    interface = jsondecode(fileread(interfacePath));
    rf = jsondecode(fileread(rfResolvedPath));
    oa = jsondecode(fileread(oaBaselinePath));
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

    sourcePose = joint.nominal_registration.source_component_pose;
    tx = sourcePose.translation_mm(1); tz = sourcePose.translation_mm(3);
    rg = rf.geometry_mm;
    xMin = tx - 1.0; xMax = oa.coordinate_convention.accelerator_axis_x + ...
        g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap+g.accelerator_shield_wall+outerVacuumMargin;
    yHalf = g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap+g.accelerator_shield_wall+outerVacuumMargin;
    zMin = g.accelerator_repeller_z-g.accelerator_repeller_thickness-g.accelerator_rear_clearance-g.accelerator_shield_wall-outerVacuumMargin;
    zMax = g.accelerator_grid2_z+downstreamBuffer;
    geom.feature.create('jointvac', 'Block'); geom.feature('jointvac').set('selresult', 'on');
    geom.feature('jointvac').set('size', {sprintf('%.17g[mm]',xMax-xMin),sprintf('%.17g[mm]',2*yHalf),sprintf('%.17g[mm]',zMax-zMin)});
    geom.feature('jointvac').set('pos', {sprintf('%.17g[mm]',xMin),sprintf('%.17g[mm]',-yHalf),sprintf('%.17g[mm]',zMin)});
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
    geom.feature.create('univacgrid','Union'); geom.feature('univacgrid').selection('input').set({'jointvac','wp_grid1','wp_grid2','relvol'}); geom.feature('univacgrid').set('intbnd',true);

    assert(~isempty(oaComsolDir) && isfolder(oaComsolDir), 'Frozen oa COMSOL source directory is missing.');
    addpath(oaComsolDir);
    interfacePort = struct('enabled',portWidth>0,'full_width_y_mm',portWidth,'full_height_z_mm',portHeight,'center_z_mm',joint.port_sweep.center_z_mm);
    accelrings = oatof_build_accelerator_geometry(geom, interfacePort);
    geom.feature('repeller').set('selresult','on');
    geom.feature('accelshield').set('selresult','on');
    for k=1:numel(accelrings), geom.feature(accelrings{k}).set('selresult','on'); end

    rodTags = {};
    if includeRfHardware
        rodTags = cell(1,4);
        for k=1:4
            rodTags{k}=sprintf('rfrod%d',k); angle=(k-1)*90;
            geom.feature.create(rodTags{k},'Cylinder'); geom.feature(rodTags{k}).set('axis',{'1','0','0'});
            geom.feature(rodTags{k}).set('r',sprintf('%.17g[mm]',rg.rod_radius)); geom.feature(rodTags{k}).set('h',sprintf('%.17g[mm]',rg.rod_length));
            geom.feature(rodTags{k}).set('pos',{sprintf('%.17g[mm]',tx+rg.rod_z_min),sprintf('%.17g[mm]',rg.rod_center_radius*cosd(angle)),sprintf('%.17g[mm]',tz+rg.rod_center_radius*sind(angle))});
            geom.feature(rodTags{k}).set('selresult','on');
        end
        add_plate(geom,'rfentrance',tx+rg.entrance_plate_z_min,rg.entrance_plate_z_max-rg.entrance_plate_z_min,rg.exit_enclosure_outer_half_width,rg.entrance_aperture_radius,tz);
        add_plate(geom,'rfexit',tx+rg.exit_enclosure_z_min,rg.exit_enclosure_front_wall_end_z-rg.exit_enclosure_z_min,rg.exit_enclosure_outer_half_width,rg.exit_aperture_radius,tz);
    end
    geom.run;

    rfSolidTags = {}; if includeRfHardware, rfSolidTags = {'rfentrance','rfexit'}; end
    solidTags = [{'repeller','accelshield'}, rfSolidTags, accelrings, rodTags];
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
    if includeRfHardware, set_potential(esStatic,'rfentrance','selb_rfentrance',0); set_potential(esStatic,'rfexit','selb_rfexit',0); end
    set_potential(esStatic,'grid1','selb_grid1',oa.electrodes_V.grid1); set_potential(esStatic,'grid2','selb_grid2',0);
    for k=1:5, set_potential(esStatic,sprintf('ring%d',k),sprintf('selb_accelring_%d',k),oa.electrodes_V.grid1*(1-k/6)); end
    if includeRfHardware
        for k=1:4
            set_potential(esStatic,sprintf('rfrod%d',k),sprintf('selb_rfrod%d',k),0);
        end
    end
    groundedRfTags = [{'repeller','accelshield'}, rfSolidTags, accelrings];
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
    fprintf(fid,'PROFILE_ROWS=%d\nINJECTION_ROWS=%d\nMODEL_SAVED=false\nSTATUS=PASS\n',height(profile),height(injection));
catch exception
    fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off')); rethrow(exception)
end
clear cleanup

function add_plate(geom,tag,xStart,thickness,halfWidth,holeRadius,zCenter)
geom.feature.create([tag 'O'],'Block'); geom.feature([tag 'O']).set('size',{sprintf('%.17g[mm]',thickness),sprintf('%.17g[mm]',2*halfWidth),sprintf('%.17g[mm]',2*halfWidth)}); geom.feature([tag 'O']).set('pos',{sprintf('%.17g[mm]',xStart),sprintf('%.17g[mm]',-halfWidth),sprintf('%.17g[mm]',zCenter-halfWidth)});
geom.feature.create([tag 'H'],'Cylinder'); geom.feature([tag 'H']).set('axis',{'1','0','0'}); geom.feature([tag 'H']).set('r',sprintf('%.17g[mm]',holeRadius)); geom.feature([tag 'H']).set('h',sprintf('%.17g[mm]',thickness)); geom.feature([tag 'H']).set('pos',{sprintf('%.17g[mm]',xStart),'0',sprintf('%.17g[mm]',zCenter)});
geom.feature.create(tag,'Difference'); geom.feature(tag).selection('input').set({[tag 'O']}); geom.feature(tag).selection('input2').set({[tag 'H']}); geom.feature(tag).set('selresult','on');
end

function create_grid_selection(comp,tag,zValue,xCenter,halfWidth,zHalf)
comp.selection.create(tag,'Box'); comp.selection(tag).geom('geom1',2); comp.selection(tag).set('xmin',xCenter-halfWidth); comp.selection(tag).set('xmax',xCenter+halfWidth); comp.selection(tag).set('ymin',-halfWidth); comp.selection(tag).set('ymax',halfWidth); comp.selection(tag).set('zmin',zValue-zHalf); comp.selection(tag).set('zmax',zValue+zHalf); comp.selection(tag).set('condition','allvertices');
end

function set_potential(physics,tag,selection,value)
feature=physics.create(['pot_' tag],'ElectricPotential',2); feature.selection.named(selection); feature.set('V0',sprintf('%.17g[V]',value));
end
