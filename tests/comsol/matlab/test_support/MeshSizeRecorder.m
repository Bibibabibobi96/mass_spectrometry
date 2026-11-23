classdef MeshSizeRecorder < handle
    % Test-only recording of the narrow public mesh feature API.
    properties
        Data
        Nodes
        Writes
        ResetOnCustom = false
    end
    methods
        function self = MeshSizeRecorder(addDefault)
            if nargin == 0, addDefault = true; end
            self.Data = containers.Map('KeyType','char','ValueType','any');
            self.Nodes = containers.Map('KeyType','char','ValueType','any');
            self.Writes = containers.Map('KeyType','char','ValueType','any');
            self.Data('hauto')=5; self.Data('custom')='off';
            self.Data('hmin')=0.5; self.Data('hmax')=10;
            self.Data('hcurve')=0.6; self.Data('hgrad')=1.5; self.Data('hnarrow')=0.5;
            if addDefault, self.create('size', 'Size'); end
        end
        function node = feature(self, tag)
            node = self;
            if nargin > 1, node = self.Nodes(tag); end
        end
        function node = create(self, tag, kind)
            node = MeshSizeRecorder(false);
            node.Data('type') = kind;
            self.Nodes(tag) = node;
        end
        function set(self, key, value)
            self.Data(key) = value;
            self.Writes(key) = value;
            if self.ResetOnCustom && strcmp(key,'custom')
                self.Data('hgrad')=99;
            end
        end
        function kind = getValueType(self,key)
            kind = 'Double';
            if ischar(self.Data(key)), kind='String'; end
        end
        function value = getString(self,key)
            value = self.Data(key);
        end
        function value = getDouble(self,key)
            value = self.Data(key);
        end
        function label(self, value)
            self.Data('label') = value;
        end
        function node = selection(self)
            node = self;
        end
        function geom(self, tag, dimension)
            self.Data('geometry') = tag;
            self.Data('dimension') = dimension;
        end
        function named(self, value)
            self.Data('selection') = value;
        end
    end
end
