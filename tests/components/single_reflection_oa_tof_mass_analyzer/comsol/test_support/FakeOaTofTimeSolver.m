classdef FakeOaTofTimeSolver < handle
    % In-memory COMSOL Time feature double; no commercial runtime required.
    properties
        values
        writes = strings(0,1)
        ignoreWrites = false
    end
    methods
        function obj = FakeOaTofTimeSolver(odeType,method)
            obj.values = struct('odesolvertype',odeType,'timemethod',method, ...
                'timemethodexp','rk','rkmethod','dopri5', ...
                'tstepsgenalpha','strict','tstepsbdf','intermediate', ...
                'tstepsdopri5','strict','tout','tsteps');
        end
        function value = getString(obj,key)
            value = obj.values.(key);
        end
        function set(obj,key,value)
            obj.writes(end+1,1) = string(key);
            if ~obj.ignoreWrites
                obj.values.(key) = value;
            end
        end
    end
end
