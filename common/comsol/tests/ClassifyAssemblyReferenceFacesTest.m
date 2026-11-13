classdef ClassifyAssemblyReferenceFacesTest < matlab.unittest.TestCase
    % Tests native entity orientation and fail-closed classification.
    methods (TestClassSetup)
        function addBackendToPath(testCase)
            root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
            backend = fullfile(root, 'src', 'msplatform', 'backends', 'comsol', 'matlab');
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(backend));
        end
    end
    methods (Test)
        function unevenMixedOrientations(testCase)
            keys={'rf/a','rf/a','oa/b'};
            faces={int32([1;2;3]),int32([4 5]),int32([6;7])};
            [groupKeys,groupFaces]=classify_assembly_reference_faces( ...
                keys,faces,int32((1:10)'),int32([8 9 10]));
            testCase.verifyEqual(groupKeys,{'rf/a','oa/b'});
            testCase.verifyEqual(groupFaces,{[1 2 3 4 5],[6 7]});
            testCase.verifyClass(groupFaces{1},'double');
        end
        function emptyMember(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[],[3 4]},[1;2;3;4;5],5),'assembly:MemberFaces');
        end
        function memberOutsideVacuum(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[1 8],[3 4]},[1;2;3;4;5],5),'assembly:MemberFaces');
        end
        function overlappingGroups(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[1 2],[2 3 4]},[1;2;3;4;5],5),'assembly:GroupOverlap');
        end
        function emptyOuter(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[1;2],[3 4]},[1;2;3;4;5],[]),'assembly:OuterFaces');
        end
        function outerContact(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[1;2],[3 4]},[1;2;3;4;5],[4 5]),'assembly:OuterContact');
        end
        function unclassifiedVacuumFace(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[1;2],[3 4]},[1 2 3 4 5 6],5),'assembly:UnclassifiedFaces');
        end
        function emptyVacuum(testCase)
            testCase.verifyError(@() classify_assembly_reference_faces( ...
                {'a','b'},{[1;2],[3 4]},[],5),'assembly:VacuumFaces');
        end
    end
end
