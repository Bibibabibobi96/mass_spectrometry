% Solve one 2D rod-midpoint unit-field case inside a grounded cylindrical shield.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('RF_SHIELD_2D_FIELD_CSV');
contractPath = getenv('RF_SHIELD_CONTRACT');
resolvedPath = getenv('RF_SHIELD_RF_RESOLVED');
shieldRadius = str2double(getenv('RF_SHIELD_INNER_RADIUS_MM'));
meshHmax = str2double(getenv('RF_SHIELD_MESH_HMAX_MM'));
assert(~isempty(reportPath) && ~isempty(outputCsv) && ~isempty(contractPath) && ~isempty(resolvedPath), ...
    'RF shield 2D environment is incomplete.');
assert(isfinite(shieldRadius) && shieldRadius > 0, 'RF shield radius must be positive.');
assert(isfinite(meshHmax) && meshHmax > 0, 'RF shield mesh hmax must be positive.');
fid = fopen(reportPath,'w'); assert(fid>=0,'Could not create task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid,'TASK=RF_CONTINUOUS_SHIELD_2D\nSHIELD_INNER_RADIUS_MM=%.17g\nMESH_HMAX_MM=%.17g\n',shieldRadius,meshHmax);

try
    contract = jsondecode(fileread(contractPath));
    resolved = jsondecode(fileread(resolvedPath));
    allowedRadii = contract.candidate_geometry_mm.inner_radius_mm_sweep(:);
    allowedHmax = contract.two_dimensional_field_screen.local_maximum_element_size_mm(:);
    assert(any(abs(allowedRadii-shieldRadius)<1e-12),'Shield radius is outside the frozen sweep.');
    assert(any(abs(allowedHmax-meshHmax)<1e-12),'Mesh hmax is outside the frozen sweep.');
    g = resolved.geometry_mm;
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = 'RF_SHIELD_2D';
    if any(strcmp(cell(ModelUtil.tags()),tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    model.label(sprintf('RF continuous grounded shield 2D R=%.6g mm',shieldRadius));
    comp = model.component.create('comp1',true);
    geom = comp.geom.create('geom1',2); geom.lengthUnit('mm');

    geom.feature.create('vac','Circle'); geom.feature('vac').set('r',sprintf('%.17g[mm]',shieldRadius)); geom.feature('vac').set('selresult','on');
    rodTags = cell(1,4);
    for k=1:4
        rodTags{k}=sprintf('rod%d',k); angle=(k-1)*90;
        geom.feature.create(rodTags{k},'Circle');
        geom.feature(rodTags{k}).set('r',sprintf('%.17g[mm]',g.rod_radius));
        geom.feature(rodTags{k}).set('pos',{sprintf('%.17g[mm]',g.rod_center_radius*cosd(angle)),sprintf('%.17g[mm]',g.rod_center_radius*sind(angle))});
        geom.feature(rodTags{k}).set('selresult','on');
    end
    numericalWall = max(meshHmax,0.1);
    geom.feature.create('shieldO','Circle'); geom.feature('shieldO').set('r',sprintf('%.17g[mm]',shieldRadius+numericalWall));
    geom.feature.create('shieldH','Circle'); geom.feature('shieldH').set('r',sprintf('%.17g[mm]',shieldRadius));
    geom.feature.create('shield','Difference'); geom.feature('shield').selection('input').set({'shieldO'}); geom.feature('shield').selection('input2').set({'shieldH'}); geom.feature('shield').set('selresult','on');
    geom.run;

    electrodeTags=[rodTags,{'shield'}];
    electrodeDomains=cellfun(@(name)['geom1_' name '_dom'],electrodeTags,'UniformOutput',false);
    comp.selection.create('sel_vac','Complement'); comp.selection('sel_vac').set('input',electrodeDomains);
    material=model.material.create('mat_vac','Common'); material.selection.named('sel_vac'); material.propertyGroup('def').set('relpermittivity',{'1'});
    es=comp.physics.create('es','Electrostatics','geom1'); es.selection.named('sel_vac');
    for k=1:4
        selection=sprintf('selb_rod%d',k); comp.selection.create(selection,'Adjacent'); comp.selection(selection).set('input',{sprintf('geom1_rod%d_dom',k)});
        potential=es.create(sprintf('pot_rod%d',k),'ElectricPotential',1); potential.selection.named(selection); potential.set('V0',sprintf('%d[V]',100*(-1)^(k+1)));
    end
    comp.selection.create('selb_shield','Adjacent'); comp.selection('selb_shield').set('input',{'geom1_shield_dom'});
    potential=es.create('pot_shield','ElectricPotential',1); potential.selection.named('selb_shield'); potential.set('V0','0[V]');

    mesh=comp.mesh.create('mesh1'); mesh.feature('size').set('hauto',contract.two_dimensional_field_screen.global_mesh_auto_level);
    mesh.feature.create('szvac','Size'); mesh.feature('szvac').selection.geom('geom1',2); mesh.feature('szvac').selection.named('sel_vac');
    mesh.feature('szvac').set('custom','on'); mesh.feature('szvac').set('hmaxactive',true); mesh.feature('szvac').set('hmax',sprintf('%.17g[mm]',meshHmax));
    mesh.feature.create('ftri1','FreeTri'); mesh.run;
    study=model.study.create('std1'); study.create('stat','Stationary'); solution=model.sol.create('sol1'); solution.study('std1'); solution.createAutoSequence('std1'); solution.attach('std1'); solution.runAll;

    fractions=contract.two_dimensional_field_screen.sample_radius_fraction_of_r0(:);
    nTheta=contract.two_dimensional_field_screen.azimuth_samples_per_radius;
    theta=(0:nTheta-1)'*(2*pi/nTheta);
    radius=[]; thetaAll=[];
    for index=1:numel(fractions)
        radius=[radius;repmat(fractions(index)*g.inscribed_radius_r0,nTheta,1)]; %#ok<AGROW>
        thetaAll=[thetaAll;theta]; %#ok<AGROW>
    end
    x=radius.*cos(thetaAll); y=radius.*sin(thetaAll);
    [V,Ex,Ey]=mphinterp(model,{'V','-d(V,x)','-d(V,y)'},'coord',[x.';y.'],'dataset','dset1','matherr','on');
    samples=table(repmat(shieldRadius,numel(x),1),repmat(meshHmax,numel(x),1),radius,thetaAll,x,y,V(:),Ex(:),Ey(:), ...
        'VariableNames',{'shield_inner_radius_mm','mesh_hmax_mm','sample_radius_mm','theta_rad','x_mm','y_mm','potential_V','Ex_V_per_m','Ey_V_per_m'});
    outputDir=fileparts(outputCsv); if ~isfolder(outputDir),mkdir(outputDir);end; writetable(samples,outputCsv);
    fprintf(fid,'SAMPLE_ROWS=%d\nMODEL_SAVED=false\nSTATUS=PASS\n',height(samples));
catch exception
    fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off')); rethrow(exception)
end
clear cleanup
