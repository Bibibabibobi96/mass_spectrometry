-- Three-instance oa-TOF workbench: accelerator, reflectron, grounded tube.
-- The bender filenames are private PA copies in template_bender/.
simion.command('"template_bender\\bend.iob"')
local wb = simion.wb
assert(#wb.instances == 3, 'three-instance template did not load')

-- Template order is bend_y (reflectron), bend_x (accelerator), bend_xy (tube).
local r = wb.instances[1]
r.x, r.y, r.z = 0, 0, 619.83
-- Provisional rotation: to be finalized by the axial field orientation test.
r.az, r.el, r.rt, r.scale = -90, 0, 0, 1

local a = wb.instances[2]
a.x, a.y, a.z = -39, -39, -10
a.az, a.el, a.rt, a.scale = 0, 0, 0, 1

local t = wb.instances[3]
t.x, t.y, t.z = 0, 0, 19.83
t.az, t.el, t.rt, t.scale = -90, 0, 0, 1

wb:save([[oatof_grounded_tube.iob]])
