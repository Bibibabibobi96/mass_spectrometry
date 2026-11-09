classdef eiSourceContractTest < matlab.unittest.TestCase
    % Pure contract/path checks; no LiveLink connection or model construction.
    properties
        Contract
        TemporaryDirectory
    end

    methods (TestClassSetup)
        function addCanonicalHelpers(testCase)
            projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            repoRoot = fileparts(fileparts(projectRoot));
            helperDirectory = fullfile(repoRoot, 'src', 'msplatform', 'backends', 'comsol', 'matlab');
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(helperDirectory));
            testCase.Contract = jsondecode(fileread(fullfile(projectRoot, 'config', 'resolved_model.json')));
        end
    end

    methods (TestMethodSetup)
        function createTemporaryDirectory(testCase)
            fixture = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.TemporaryDirectory = fixture.Folder;
        end
    end

    methods (Test)
        function validResolvedFixtureKeepsBuildOnlyIdentity(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            actual = load_ei_source_contract(contractPath);
            testCase.verifyEqual(actual.project_id, 'apertured_tube_electron_impact_ion_source');
            testCase.verifyEqual(actual.selected_mode_id, 'build_only_smoke');
            testCase.verifyEqual(actual.numerical.execution_mode, 'build_only');
            testCase.verifyFalse(actual.evidence.candidate_evidence_allowed);
        end

        function missingContractStopsBeforeComsol(testCase)
            testCase.verifyError(@() ms_stage1_ei_source(), 'EISource:MissingContract');
        end

        function missingRunDirectoryStopsBeforeComsol(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            testCase.verifyError(@() ms_stage1_ei_source(contractPath), 'EISource:MissingRunDirectory');
        end

        function emptyRunDirectoryStopsBeforeComsol(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            testCase.verifyError(@() ms_stage1_ei_source(contractPath, ''), 'EISource:MissingRunDirectory');
        end

        function nonexistentRunDirectoryStopsBeforeComsol(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            missingDirectory = fullfile(testCase.TemporaryDirectory, 'not-created-by-owner');
            testCase.verifyError(@() ms_stage1_ei_source(contractPath, missingDirectory), 'EISource:RunDirectoryMissing');
        end

        function unitTextPreservesOriginalPrecision(testCase)
            testCase.verifyEqual(ei_source_unit_text(1/3, 's'), '0.33333333333333331[s]');
            testCase.verifyEqual(ei_source_unit_text(-.125, 'mm'), '-0.125[mm]');
        end

        function parameterBindingsAcceptActualContractExpressions(testCase)
            model = testCase.boundParameterModel();
            testCase.verifyTrue(verify_ei_source_parameter_bindings(model, testCase.Contract));
        end

        function parameterBindingsRejectChangedModelExpression(testCase)
            model = testCase.boundParameterModel();
            original = model.param.get;
            model.param.get = @(key) replace(original(key), '[mm]', '[s]');
            exception = testCase.captureException(@() verify_ei_source_parameter_bindings(model, testCase.Contract));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'COMSOL parameter R_tube is not bound to the resolved contract.');
        end

        function coldVerifierRequiresActualModelFileBeforeComsol(testCase)
            contractPath = testCase.writeContract(testCase.Contract);
            missingModel = fullfile(testCase.TemporaryDirectory, 'missing.mph');
            testCase.verifyError(@() verify_ei_source_model(missingModel, contractPath), 'EISource:MissingModel');
        end

        function coldVerifierRejectsSolvedModeBeforeComsol(testCase)
            fullContract = testCase.Contract;
            fullContract.selected_mode_id = 'functional_reference';
            fullContract.numerical.execution_mode = 'full';
            fullContract.numerical.candidate_evidence_allowed = true;
            fullContract.evidence.candidate_evidence_allowed = true;
            fullContract.evidence.requested_particle_count = 100;
            fullContract.evidence.minimum_particle_count = 100;
            contractPath = testCase.writeContract(fullContract);
            modelPath = fullfile(testCase.TemporaryDirectory, 'inert-not-a-comsol-model.mph');
            fid = fopen(modelPath, 'w');
            fclose(fid);
            testCase.verifyError(@() verify_ei_source_model(modelPath, contractPath), 'EISource:NotBuildOnly');
        end

        function wrongProjectIdentityIsRejected(testCase)
            invalid = testCase.Contract;
            invalid.project_id = 'different_project';
            contractPath = testCase.writeContract(invalid);
            exception = testCase.captureException(@() load_ei_source_contract(contractPath));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'Resolved EI-source project identity mismatch.');
        end

        function heavyIonClaimIsRejected(testCase)
            invalid = testCase.Contract;
            invalid.physical.capability.heavy_ion_source_claim_allowed = true;
            contractPath = testCase.writeContract(invalid);
            exception = testCase.captureException(@() load_ei_source_contract(contractPath));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'This prototype contract cannot claim a heavy-ion source.');
        end

        function belowMinimumFunctionalEvidenceIsRejected(testCase)
            invalid = testCase.Contract;
            invalid.numerical.candidate_evidence_allowed = true;
            invalid.evidence.requested_particle_count = 1;
            invalid.evidence.minimum_particle_count = 100;
            contractPath = testCase.writeContract(invalid);
            exception = testCase.captureException(@() load_ei_source_contract(contractPath));
            testCase.verifyEqual(exception.identifier, '');
            testCase.verifyEqual(exception.message, 'Functional evidence particle count is below the contract minimum.');
        end
    end

    methods (Access = private)
        function model = boundParameterModel(testCase)
            contract = testCase.Contract;
            geometry = contract.physical.geometry_mm;
            expressions = struct( ...
                'R_tube', ei_source_unit_text(geometry.tube_bore_radius, 'mm'), ...
                'L_cell', ei_source_unit_text(geometry.cathode_anode_path_length, 'mm'), ...
                'r_hole', ei_source_unit_text(geometry.electrode_aperture_radius, 'mm'), ...
                'Nd', ei_source_unit_text(contract.physical.gas.neutral_number_density_per_m3, '1/m^3'), ...
                'sigma_ion', ei_source_unit_text(contract.physical.ionization.cross_section_m2, 'm^2'), ...
                'dE_ion', ei_source_unit_text(contract.physical.ionization.primary_energy_loss_eV, 'eV'));
            model = struct('param', struct('get', @(key) expressions.(key)));
        end

        function exception = captureException(testCase, action)
            exception = [];
            try
                action();
            catch actualException
                exception = actualException;
            end
            testCase.assertClass(exception, 'MException', ...
                'The malformed contract must throw its semantic validation error.');
        end

        function contractPath = writeContract(testCase, contract)
            contractPath = fullfile(testCase.TemporaryDirectory, 'resolved.json');
            fid = fopen(contractPath, 'w', 'n', 'UTF-8');
            assert(fid >= 0, 'Cannot create pure contract fixture.');
            cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
            fprintf(fid, '%s', jsonencode(contract));
        end
    end
end
