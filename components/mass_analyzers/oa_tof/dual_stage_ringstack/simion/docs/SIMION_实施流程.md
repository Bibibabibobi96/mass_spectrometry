# oa-TOF 在 SIMION 8.2 中的实施流程

## 阶段 A：确认安装与可写工作区

程序：`C:\Program Files\SIMION-2020\simion.exe`。

工作文件必须保存在本目录，不能保存在Program Files。先在SIMION中打开
`examples_reference/simion_fast_adjust_demo.gem`，另存为
`01_accelerator/smoke_fast_adjust.pa#`，并完成：GEM处理、Refine、Fast Adjust和保存PA0。
这一步通过的标准是：生成`smoke_fast_adjust.pa0/.pa1/.pa2/.pa3`，且可改变某个电极电压而不重新Refine。

随后只读打开`examples_reference/simion_nonideal_grid_demo.gem`，观察真实细丝grid的网格尺度；不要把该示例直接放大到oa-TOF全孔径。

## 阶段 B：理想栅网反射镜 PA#

已建立`02_reflectron/oatof_reflectron_ideal_10_5.pa#`，使用2D cylindrical PA，标尺`1 mm/gu`。这是与COMSOL轴对称理想栅网反射镜场比较的正式第一基线；在它通过轴线场和转向深度比较前，不扩展成全尺寸3D阵列。

几何包含：接地圆柱屏蔽壳、入口栅网、10个一级环、级间栅网、5个二级环、背板。每个环单独为一个Fast Adjust电极；准确位置/电压见：

- `00_reference/oatof_final_10_5_baseline.json`
- `00_reference/reflectron_ring_table_10_5.csv`

栅网规则：`entgrid`和`midgrid`是与有效截面等大的、一网格点厚的电极面。它们是理想透明等势面，**不是**带大孔的实体板。这样才与COMSOL内部边界基线一致。

建议编号：

| electrode | SIMION fast-adjust号 |
|---|---:|
| entgrid | 1 |
| stage1 ring 1..10 | 2..11 |
| midgrid | 12 |
| stage2 ring 1..5 | 13..17 |
| backplate | 18 |

地屏蔽罩保持普通0 V电极，不需要单独Fast Adjust。

## 阶段 C：加速器 PA#

正式加速器使用3D Cartesian、各轴`0.25 mm/gu`、`361×361×141`的PA。GEM的物理几何
只有一份；`mmgu_xy`、`mmgu_z`和`xy_span`仅控制数值网格与接地屏蔽外部真空包围范围，
不得借诊断变体修改电极尺寸、电极间隙或电极—屏蔽间隙。

包含repeller、grid1、grid2、5个加速器环和接地屏蔽罩。grid1/grid2同样是一网格点厚的透明等势面。

基准电压：repeller=2240 V，grid1=1760 V，grid2=0 V；加速器环电压依据当前COMSOL脚本的线性规则。

当前电极编号与 fast-adjust：1=repeller，2=grid1，3..7=五个加速器环，8=grid2，9=grounded shield；对应电位为2240、1760、1466.666667、1173.333333、880、586.666667、293.333333、0、0 V。`build_accelerator_3d.cmd`可无GUI重建全部PA并应用这些电位。

网格闭合使用`build_accelerator_variant.lua`。构建器必须先打印尺寸和10阵列容量估算，并
设置可接受的GiB硬上限。已验证的受控方案为：xy仍0.25 mm、只把z降至0.125 mm，并把
xy包围范围从90 mm裁至接地屏蔽外宽78 mm；所得`313×313×281`数组保留全部物理几何。
完整基阵存于artifacts用于复现，飞行时只用已fast-adjust的PA0，通过
`OATOF_ACCELERATOR_PA_OVERRIDE`、`pa:load()`和`_debug_update_size()`替换正式IOB中的
加速器实例，同时设`accelerator_fast_adjust_enable=0`。禁止为大PA反复保存变体IOB或
每次启动重新组合9个基阵。

## 阶段 D：Workbench 与初始验证

将加速器PA放在`x=-48.8 mm`，反射镜轴放在`x=0`；探测面位于`x=+48.8 mm, z=L_accel`。

第一轮只飞固定单粒子，记录：

1. 到达entgrid时刻；
2. 最大反射深度；
3. 返回探测面时刻；
4. 横向位置和速度。

然后比较COMSOL基准：到达时间约31.44793 us、二级最大穿透约51.07 mm。只有这些量对齐后，才进行N=100和N=1000统计。

## 阶段 E：真实丝网局部单元

仅在理想栅网版本通过后，建立`03_grid_cell/`中的高分辨率3D网孔单元。输入真实丝径、节距、材料和两侧电压；输出透过率、撞丝概率、横向kick查表。

主Workbench不显式铺满细丝。用Lua在粒子通过栅网平面时按局部表施加损失/偏转，或采用SIMION的非理想grid单元重复/跳转技术。

优先顺序：先`entgrid`、再`midgrid`、最后才评估grid1/grid2。

## 结果纪律

- 每次曲线含多条线必须有legend。
- 图标题写明PA标尺、栅网模式、粒子数和Fast Adjust电压集。
- 理想栅网与真实丝网结果不得混在同一基线表。
- 首次比较必须保留COMSOL与SIMION的轴线`V(z)`、`Ez(z)`和单粒子轨迹PNG。
- 加密测试必须先做同网格裁边控制，再做单离子、N=100、N=1000；否则不能把裁边效应、
  统计波动和网格收敛混为同一结论。
