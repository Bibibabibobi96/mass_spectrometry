classdef ComsolMeshSizeTest < matlab.unittest.TestCase
    properties (TestParameter)
        invalidMinimum = struct('zero',0,'negative',-0.2,'nan',NaN,'inf',Inf, ...
            'vector',[0.1 0.2],'logical',true,'text','0.2','complex',1i);
    end
    methods (TestClassSetup)
        function configurePath(testCase)
            folder = fileparts(mfilename('fullpath'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fileparts(folder)));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(folder,'test_support')));
        end
    end
    methods (Test)
        function absentMinimumPreservesDefaults(testCase)
            mesh = MeshSizeRecorder;
            configure_comsol_mesh(mesh,'geom1',9,'work',2);
            testCase.verifyFalse(isKey(mesh.Nodes('size').Writes,'hmin'));
            testCase.verifyFalse(isKey(mesh.Nodes('size').Writes,'custom'));
            testCase.verifyFalse(isKey(mesh.Nodes('szCommonWork').Writes,'hmin'));
            testCase.verifyEqual(mesh.Nodes('size').Data('hauto'),9);
        end
        function explicitMinimumReachesGlobalAndLocal(testCase)
            mesh = MeshSizeRecorder;
            configure_comsol_mesh(mesh,'geom1',9,'work',2,0.2);
            testCase.verifyEqual(mesh.Nodes('size').Data('hmin'),'0.20000000000000001[mm]');
            testCase.verifyEqual(mesh.Nodes('size').Data('custom'),'on');
            testCase.verifyFalse(isKey(mesh.Nodes('size').Data,'hminactive'));
            testCase.verifyEqual(mesh.Nodes('szCommonWork').Data('hmin'),'0.20000000000000001[mm]');
            testCase.verifyTrue(mesh.Nodes('szCommonWork').Data('hminactive'));
            testCase.verifyEqual(mesh.Nodes('szCommonWork').Data('hmax'),'2[mm]');
        end
        function noRegionUsesExplicitGlobalMinimum(testCase)
            mesh = MeshSizeRecorder;
            configure_comsol_mesh(mesh,'geom1',9,'',2,0.2);
            testCase.verifyEqual(mesh.Nodes('size').Data('hmin'),'0.20000000000000001[mm]');
            testCase.verifyEqual(mesh.Nodes('size').Data('hmax'),'2[mm]');
            testCase.verifyFalse(isKey(mesh.Nodes,'szCommonWork'));
        end
        function oldOaExpressionCallPreservesDefaultMinimum(testCase)
            mesh = MeshSizeRecorder;
            feature = add_comsol_size_feature(mesh,'oa','OA boundary','geom1',2,'boundary','h_work');
            testCase.verifyEqual(feature.Data('hmax'),'h_work');
            testCase.verifyEqual(feature.Data('dimension'),2);
            testCase.verifyEqual(feature.Data('selection'),'boundary');
            testCase.verifyFalse(isKey(feature.Writes,'hmin'));
        end
        function invalidMinimumFailsBeforeMutation(testCase,invalidMinimum)
            mesh = MeshSizeRecorder;
            testCase.verifyError(@() configure_comsol_mesh(mesh,'geom1',9,'work',2,invalidMinimum), ...
                'common:comsol:MeshMinimum');
            testCase.verifyFalse(isKey(mesh.Nodes('size').Writes,'hauto'));
        end
        function minimumAboveMaximumRejected(testCase)
            mesh = MeshSizeRecorder;
            testCase.verifyError(@() configure_comsol_mesh(mesh,'geom1',9,'work',0.1,0.2), ...
                'common:comsol:MeshMinimum');
        end
        function typedReadbackDoesNotEvaluateOrConvertUnits(testCase)
            mesh = MeshSizeRecorder;
            feature = mesh.Nodes('size');
            feature.set('hmax','2[mm]');
            controls = read_comsol_mesh_size_controls(feature);
            testCase.verifyEqual(controls.hmax,struct('type','String','value','2[mm]'));
            testCase.verifyEqual(controls.hmin,struct('type','Double','value',0.5));
        end
        function implicitCustomResetFailsClosed(testCase)
            mesh = MeshSizeRecorder;
            feature = mesh.Nodes('size');
            feature.ResetOnCustom=true;
            testCase.verifyError(@() configure_comsol_mesh(mesh,'geom1',9,'work',2,0.2), ...
                'common:comsol:MeshSizeDrift');
        end
        function directLocalMinimumAboveMaximumRejected(testCase)
            mesh = MeshSizeRecorder;
            testCase.verifyError(@() add_comsol_size_feature(mesh,'bad','','geom1',3,'work',0.1,0.2), ...
                'common:comsol:MeshMinimum');
        end
    end
end
