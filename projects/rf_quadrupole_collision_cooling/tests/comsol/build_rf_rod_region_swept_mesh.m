% Validate a triangular-source, prism-swept mesh in the uniform RF rod region.

reportPath=getenv('COMSOL_BOOTSTRAP_REPORT'); outputCsv=getenv('RF_SWEPT_FIELD_CSV'); contractPath=getenv('RF_SWEPT_CONTRACT'); resolvedPath=getenv('RF_SWEPT_RESOLVED');
transverseHmax=str2double(getenv('RF_SWEPT_TRANSVERSE_HMAX_MM')); axialLayers=str2double(getenv('RF_SWEPT_AXIAL_LAYERS'));meshProfile=getenv('RF_SWEPT_MESH_PROFILE');outerHmax=str2double(getenv('RF_SWEPT_OUTER_HMAX_MM'));coreRadius=str2double(getenv('RF_SWEPT_CORE_RADIUS_MM'));
assert(~isempty(reportPath)&&~isempty(outputCsv)&&~isempty(contractPath)&&~isempty(resolvedPath),'RF swept mesh environment is incomplete.');
fid=fopen(reportPath,'w');assert(fid>=0,'Could not create task report.');cleanup=onCleanup(@()fclose(fid));
fprintf(fid,'TASK=RF_ROD_REGION_SWEPT_MESH\nTRANSVERSE_HMAX_MM=%.17g\nAXIAL_LAYERS=%d\n',transverseHmax,axialLayers);
try
    contract=jsondecode(fileread(contractPath));resolved=jsondecode(fileread(resolvedPath));g=resolved.geometry_mm;geometry=contract.geometry_mm;
    assert(any(strcmp(meshProfile,{'full','localized'})),'Unknown RF swept mesh profile.');
    assert(any(abs(contract.transverse_mesh.maximum_element_size_mm(:)-transverseHmax)<1e-12),'Transverse hmax is outside the frozen sequence.');
    assert(any(contract.axial_mesh.layer_count(:)==axialLayers),'Axial layer count is outside the frozen sequence.');
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag='RF_ROD_SWEPT';if any(strcmp(cell(ModelUtil.tags()),tag)),ModelUtil.remove(tag);end
    model=ModelUtil.create(tag);model.label(sprintf('RF uniform rod swept mesh hxy=%.3g mm Nz=%d',transverseHmax,axialLayers));
    comp=model.component.create('comp1',true);geom=comp.geom.create('geom1',3);geom.lengthUnit('mm');
    zMin=geometry.z_min;lengthZ=geometry.length;shieldRadius=geometry.shield_inner_radius;numericalWall=1.0;
    geom.feature.create('vac','Cylinder');geom.feature('vac').set('r',sprintf('%.17g[mm]',shieldRadius));geom.feature('vac').set('h',sprintf('%.17g[mm]',lengthZ));geom.feature('vac').set('pos',{'0','0',sprintf('%.17g[mm]',zMin)});geom.feature('vac').set('selresult','on');
    rodTags=cell(1,4);
    for index=1:4
        rodTags{index}=sprintf('rod%d',index);angle=(index-1)*90;geom.feature.create(rodTags{index},'Cylinder');geom.feature(rodTags{index}).set('r',sprintf('%.17g[mm]',g.rod_radius));geom.feature(rodTags{index}).set('h',sprintf('%.17g[mm]',lengthZ));geom.feature(rodTags{index}).set('pos',{sprintf('%.17g[mm]',g.rod_center_radius*cosd(angle)),sprintf('%.17g[mm]',g.rod_center_radius*sind(angle)),sprintf('%.17g[mm]',zMin)});geom.feature(rodTags{index}).set('selresult','on');
    end
    geom.feature.create('shieldO','Cylinder');geom.feature('shieldO').set('r',sprintf('%.17g[mm]',shieldRadius+numericalWall));geom.feature('shieldO').set('h',sprintf('%.17g[mm]',lengthZ));geom.feature('shieldO').set('pos',{'0','0',sprintf('%.17g[mm]',zMin)});
    geom.feature.create('shieldH','Cylinder');geom.feature('shieldH').set('r',sprintf('%.17g[mm]',shieldRadius));geom.feature('shieldH').set('h',sprintf('%.17g[mm]',lengthZ));geom.feature('shieldH').set('pos',{'0','0',sprintf('%.17g[mm]',zMin)});
    geom.feature.create('shield','Difference');geom.feature('shield').selection('input').set({'shieldO'});geom.feature('shield').selection('input2').set({'shieldH'});geom.feature('shield').set('selresult','on');geom.run;
    if strcmp(meshProfile,'localized')
        local=contract.localized_transverse_mesh;assert(any(abs(local.outer_vacuum_hmax_mm(:)-outerHmax)<1e-12),'Outer hmax is outside the frozen sequence.');assert(any(abs(local.work_core_radius_mm_candidates(:)-coreRadius)<1e-12),'Core radius is outside the frozen sequence.');
        geom.feature.create('workCore','Cylinder');geom.feature('workCore').set('r',sprintf('%.17g[mm]',coreRadius));geom.feature('workCore').set('h',sprintf('%.17g[mm]',lengthZ));geom.feature('workCore').set('pos',{'0','0',sprintf('%.17g[mm]',zMin)});geom.feature('workCore').set('selresult','on');geom.run;
    else
        outerHmax=transverseHmax;
    end
    solidTags=[rodTags,{'shield'}];solidDomains=cellfun(@(name)['geom1_' name '_dom'],solidTags,'UniformOutput',false);comp.selection.create('sel_vac','Complement');comp.selection('sel_vac').set('input',solidDomains);
    material=model.material.create('mat_vac','Common');material.selection.named('sel_vac');material.propertyGroup('def').set('relpermittivity',{'1'});
    for index=1:numel(solidTags),name=solidTags{index};comp.selection.create(['selb_' name],'Adjacent');comp.selection(['selb_' name]).set('input',{['geom1_' name '_dom']});end
    es=comp.physics.create('es','Electrostatics','geom1');es.selection.named('sel_vac');
    for index=1:4,potential=es.create(sprintf('pot_rod%d',index),'ElectricPotential',2);potential.selection.named(sprintf('selb_rod%d',index));potential.set('V0',sprintf('%d[V]',100*(-1)^(index+1)));end
    potential=es.create('pot_shield','ElectricPotential',2);potential.selection.named('selb_shield');potential.set('V0','0[V]');
    mesh=comp.mesh.create('mesh1');mesh.feature('size').set('hauto',6);
    sweep=mesh.feature.create('swe1','Sweep');sweep.selection.geom('geom1',3);sweep.selection.named('sel_vac');sweep.set('facemethod','tri');
    sizeFeature=sweep.feature.create('size1','Size');sizeFeature.selection.geom('geom1',3);sizeFeature.selection.named('sel_vac');sizeFeature.set('custom','on');sizeFeature.set('hmaxactive',true);sizeFeature.set('hmax',sprintf('%.17g[mm]',outerHmax));
    if strcmp(meshProfile,'localized')
        sizeFeature.set('hminactive',true);sizeFeature.set('hmin',sprintf('%.17g[mm]',local.transition_minimum_element_size_mm));
        coreSize=sweep.feature.create('sizeCore','Size');coreSize.selection.geom('geom1',3);coreSize.selection.named('geom1_workCore_dom');coreSize.set('custom','on');coreSize.set('hmaxactive',true);coreSize.set('hmax',sprintf('%.17g[mm]',transverseHmax));
        for index=1:4
            rodSize=sweep.feature.create(sprintf('sizeRod%d',index),'Size');rodSize.selection.geom('geom1',2);rodSize.selection.named(sprintf('selb_rod%d',index));rodSize.set('custom','on');rodSize.set('hmaxactive',true);rodSize.set('hmax',sprintf('%.17g[mm]',transverseHmax));
        end
    end
    distribution=sweep.feature.create('dist1','Distribution');distribution.selection.geom('geom1',3);distribution.selection.named('sel_vac');distribution.set('type','number');distribution.set('numelem',round(axialLayers));distribution.set('equidistant','on');
    mesh.run;meshInfo=mphmeshstats(model,'mesh1');vacuumMeshInfo=mphmeshstats(model,'mesh1','selection','sel_vac');vacuumDomains=comp.selection('sel_vac').entities(3);
    fprintf(fid,'MESH_PROFILE=%s\nCORE_RADIUS_MM=%.17g\nOUTER_HMAX_MM=%.17g\nGLOBAL_MESH_ISEMPTY=%d\nGLOBAL_MESH_ISCOMPLETE=%d\nGLOBAL_MESH_HASPROBLEMS=%d\nVACUUM_MESH_ISEMPTY=%d\nVACUUM_MESH_ISCOMPLETE_DIAGNOSTIC=%d\nVACUUM_MESH_HASPROBLEMS=%d\nVACUUM_DOMAIN_COUNT=%d\nVACUUM_DOMAIN_IDS=%s\nMESH_TOTAL_ELEMENTS=%d\n',meshProfile,coreRadius,outerHmax,meshInfo.isempty,meshInfo.iscomplete,meshInfo.hasproblems,vacuumMeshInfo.isempty,vacuumMeshInfo.iscomplete,vacuumMeshInfo.hasproblems,numel(vacuumDomains),strjoin(string(vacuumDomains),','),sum(vacuumMeshInfo.numelem));
    if meshInfo.hasproblems
        problemTags=cell(mesh.problems());fprintf(fid,'MESH_PROBLEM_FEATURE_COUNT=%d\n',numel(problemTags));
        for problemIndex=1:numel(problemTags)
            problemFeature=mesh.feature(problemTags{problemIndex});fprintf(fid,'MESH_PROBLEM_FEATURE_%d=%s\nMESH_PROBLEM_STATUS_%d=%s\nMESH_PROBLEM_MESSAGE_%d=%s\n',problemIndex,problemTags{problemIndex},problemIndex,char(problemFeature.status()),problemIndex,char(problemFeature.message()));
        end
    end
    assert(~meshInfo.hasproblems&&~vacuumMeshInfo.isempty&&~vacuumMeshInfo.hasproblems&&numel(vacuumDomains)>=1&&sum(vacuumMeshInfo.numelem)>0,'RF swept vacuum-domain mesh coverage gate failed.');
    study=model.study.create('std1');study.create('stat','Stationary');solution=model.sol.create('sol1');solution.study('std1');solution.createAutoSequence('std1');solution.attach('std1');solution.runAll;
    field=contract.field_contract;fractions=field.sample_radius_fraction_of_r0(:);zValues=field.sample_z_mm(:);nTheta=field.azimuth_samples_per_radius;theta=(0:nTheta-1)'*(2*pi/nTheta);radius=[];thetaAll=[];zAll=[];
    for zIndex=1:numel(zValues),for radiusIndex=1:numel(fractions),radius=[radius;repmat(fractions(radiusIndex)*g.field_radius_r0,nTheta,1)];thetaAll=[thetaAll;theta];zAll=[zAll;repmat(zValues(zIndex),nTheta,1)];end,end %#ok<AGROW>
    x=radius.*cos(thetaAll);y=radius.*sin(thetaAll);[V,Ex,Ey,Ez]=mphinterp(model,{'V','-d(V,x)','-d(V,y)','-d(V,z)'},'coord',[x.';y.';zAll.'],'dataset','dset1','matherr','on');
    assert(all(isfinite(V))&&all(isfinite(Ex))&&all(isfinite(Ey))&&all(isfinite(Ez)),'RF swept field sampling did not cover every frozen point.');
    samples=table(repmat(shieldRadius,numel(x),1),repmat(transverseHmax,numel(x),1),repmat(transverseHmax,numel(x),1),repmat(axialLayers,numel(x),1),zAll,radius,thetaAll,x,y,V(:),Ex(:),Ey(:),Ez(:),'VariableNames',{'shield_inner_radius_mm','mesh_hmax_mm','transverse_hmax_mm','axial_layers','sample_z_mm','sample_radius_mm','theta_rad','x_mm','y_mm','potential_V','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m'});
    outputDir=fileparts(outputCsv);if~isfolder(outputDir),mkdir(outputDir);end;writetable(samples,outputCsv);fprintf(fid,'SAMPLE_ROWS=%d\nMODEL_SAVED=false\nSTATUS=PASS\n',height(samples));
catch exception
    fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off'));rethrow(exception)
end
clear cleanup
