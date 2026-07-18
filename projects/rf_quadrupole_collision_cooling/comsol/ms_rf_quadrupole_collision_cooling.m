function result = ms_rf_quadrupole_collision_cooling(varargin)
%MS_RF_QUADRUPOLE_COLLISION_COOLING Unsupported legacy entry guard.
%
% The former implementation used a different 150 mm geometry, hard-coded
% RF and particle parameters, direct mphstart connection management, and an
% unvalidated generic collision model.  It is intentionally unavailable:
% those assumptions do not belong to the current 95.2 mm shared hardware
% contract and must not be mistaken for a cooling baseline.
%
% A future collision mode must be rebuilt from baseline/resolved geometry,
% an explicit gas/cross-section contract, GUI-visible COMSOL nodes, and a
% dedicated statistical validation gate.  Git history retains the previous
% experiment if its implementation history must be inspected.

result = struct(); %#ok<NASGU>
error('RFQUAD:UnsupportedLegacyCollisionEntry', [ ...
    'Legacy collision-cooling entry is disabled. Use ', ...
    'ms_rf_quadrupole_no_collision for the current transport mode.']);
end
