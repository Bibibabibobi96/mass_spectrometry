% Solve frozen 2D circular-rod multipole candidates and export potential samples.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
baselinePath = getenv('MULTIPOLE_BASELINE');
familyOperatingPath = getenv('MULTIPOLE_FAMILY_OPERATING');
contractPath = getenv('MULTIPOLE_ROUND_ROD_SCREEN');
outputCsv = getenv('MULTIPOLE_ROUND_ROD_SAMPLES');
assert(~isempty(reportPath) && ~isempty(baselinePath) && ~isempty(familyOperatingPath) && ...
    ~isempty(contractPath) && ~isempty(outputCsv), ...
    'Multipole round-rod screen environment is incomplete.');
assert(isfile(baselinePath) && isfile(familyOperatingPath) && isfile(contractPath), ...
    'Multipole round-rod screen inputs are missing.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the round-rod field-screen report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=MULTIPOLE_ROUND_ROD_FIELD_SCREEN\n');

try
    baseline = jsondecode(fileread(baselinePath));
    familyOperating = jsondecode(fileread(familyOperatingPath));
    contract = jsondecode(fileread(contractPath));
    n = familyOperating.identity.radial_order_n;
    electrodeCount = familyOperating.identity.electrode_count;
    assert(electrodeCount == 2*n && n >= 3, ...
        'The L2 screen requires a high-order 2n-pole contract.');
    assert(electrodeCount == baseline.multipole.electrode_count, ...
        'Baseline and L2 electrode counts differ.');
    r0 = contract.geometry_mm.inscribed_radius_r0;
    assert(abs(r0-familyOperating.geometry_mm.r0) < 1e-12, ...
        'L2 field radius differs from the shared family operating contract.');
    ratios = contract.geometry_mm.rod_radius_ratio_sweep(:);
    radii = contract.sampling.radius_fraction_of_r0(:) * r0;
    thetaCount = contract.sampling.azimuth_samples_per_radius;
    theta = (0:thetaCount-1)' * (2*pi/thetaCount);
    shieldRadius = contract.geometry_mm.grounded_shield_inner_radius;
    driveVoltage = contract.field_solve.rod_voltage_zero_to_peak_V;
    meshHmax = contract.mesh.vacuum_maximum_element_size_mm;
    rows = table();
    import com.comsol.model.*
    import com.comsol.model.util.*

    for ratioIndex = 1:numel(ratios)
        ratio = ratios(ratioIndex);
        rodRadius = ratio * r0;
        centerRadius = r0 + rodRadius;
        adjacentGap = 2*centerRadius*sin(pi/electrodeCount) - 2*rodRadius;
        assert(adjacentGap >= contract.selection.minimum_adjacent_surface_gap_mm, ...
            'A frozen rod candidate violates the minimum adjacent gap.');
        tag = sprintf('MULTIPOLE_ROUND_ROD_%d', electrodeCount);
        if any(strcmp(cell(ModelUtil.tags()), tag)), ModelUtil.remove(tag); end
        model = ModelUtil.create(tag);
        model.label(sprintf('%d-pole circular-rod L2 screen ratio %.8g', electrodeCount, ratio));
        comp = model.component.create('comp1', true);
        geom = comp.geom.create('geom1', 2);
        geom.lengthUnit('mm');
        geom.feature.create('vac', 'Circle');
        geom.feature('vac').set('r', sprintf('%.17g[mm]', shieldRadius));
        geom.feature('vac').set('selresult', 'on');
        rodTags = cell(1, electrodeCount);
        for k = 1:electrodeCount
            rodTags{k} = sprintf('rod%d', k);
            angle = (k-1) * 360/electrodeCount;
            geom.feature.create(rodTags{k}, 'Circle');
            geom.feature(rodTags{k}).set('r', sprintf('%.17g[mm]', rodRadius));
            geom.feature(rodTags{k}).set('pos', { ...
                sprintf('%.17g[mm]', centerRadius*cosd(angle)), ...
                sprintf('%.17g[mm]', centerRadius*sind(angle))});
            geom.feature(rodTags{k}).set('selresult', 'on');
        end
        wallThickness = max(0.5, meshHmax);
        geom.feature.create('shieldO', 'Circle');
        geom.feature('shieldO').set('r', sprintf('%.17g[mm]', shieldRadius+wallThickness));
        geom.feature.create('shieldH', 'Circle');
        geom.feature('shieldH').set('r', sprintf('%.17g[mm]', shieldRadius));
        geom.feature.create('shield', 'Difference');
        geom.feature('shield').selection('input').set({'shieldO'});
        geom.feature('shield').selection('input2').set({'shieldH'});
        geom.feature('shield').set('selresult', 'on');
        geom.run;

        electrodeTags = [rodTags, {'shield'}];
        electrodeDomains = cellfun(@(name) ['geom1_' name '_dom'], ...
            electrodeTags, 'UniformOutput', false);
        comp.selection.create('sel_vac', 'Complement');
        comp.selection('sel_vac').set('input', electrodeDomains);
        material = model.material.create('mat_vac', 'Common');
        material.selection.named('sel_vac');
        material.propertyGroup('def').set('relpermittivity', {'1'});
        es = comp.physics.create('es', 'Electrostatics', 'geom1');
        es.selection.named('sel_vac');
        for k = 1:electrodeCount
            boundarySelection = sprintf('selb_rod%d', k);
            comp.selection.create(boundarySelection, 'Adjacent');
            comp.selection(boundarySelection).set('input', {sprintf('geom1_rod%d_dom', k)});
            potential = es.create(sprintf('pot_rod%d', k), 'ElectricPotential', 1);
            potential.selection.named(boundarySelection);
            potential.set('V0', sprintf('%.17g[V]', driveVoltage*(-1)^(k+1)));
        end
        comp.selection.create('selb_shield', 'Adjacent');
        comp.selection('selb_shield').set('input', {'geom1_shield_dom'});
        shieldPotential = es.create('pot_shield', 'ElectricPotential', 1);
        shieldPotential.selection.named('selb_shield');
        shieldPotential.set('V0', '0[V]');

        mesh = comp.mesh.create('mesh1');
        mesh.feature('size').set('hauto', contract.mesh.global_auto_level);
        mesh.feature.create('szvac', 'Size');
        mesh.feature('szvac').selection.geom('geom1', 2);
        mesh.feature('szvac').selection.named('sel_vac');
        mesh.feature('szvac').set('custom', 'on');
        mesh.feature('szvac').set('hmaxactive', true);
        mesh.feature('szvac').set('hmax', sprintf('%.17g[mm]', meshHmax));
        mesh.feature.create('ftri1', 'FreeTri');
        mesh.run;
        study = model.study.create('std1');
        study.create('stat', 'Stationary');
        solution = model.sol.create('sol1');
        solution.study('std1');
        solution.createAutoSequence('std1');
        solution.attach('std1');
        solution.runAll;

        for radiusIndex = 1:numel(radii)
            radius = radii(radiusIndex);
            x = radius*cos(theta);
            y = radius*sin(theta);
            potentialValues = mphinterp(model, 'V', 'coord', [x.'; y.'], ...
                'dataset', 'dset1', 'matherr', 'on');
            block = table(repmat(ratio, thetaCount, 1), ...
                repmat(rodRadius, thetaCount, 1), repmat(centerRadius, thetaCount, 1), ...
                repmat(adjacentGap, thetaCount, 1), repmat(radius, thetaCount, 1), ...
                theta, x, y, potentialValues(:), ...
                'VariableNames', {'rod_radius_ratio','rod_radius_mm', ...
                'rod_center_radius_mm','adjacent_surface_gap_mm', ...
                'sample_radius_mm','theta_rad','x_mm','y_mm','potential_V'});
            rows = [rows; block]; %#ok<AGROW>
        end
        ModelUtil.remove(tag);
    end
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(rows, outputCsv);
    fprintf(fid, 'ELECTRODE_COUNT=%d\nCANDIDATES=%d\nSAMPLE_ROWS=%d\nSTATUS=PASS\n', ...
        electrodeCount, numel(ratios), height(rows));
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
