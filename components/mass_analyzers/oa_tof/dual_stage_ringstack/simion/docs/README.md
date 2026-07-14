# oa-TOF SIMION 工作区

SIMION程序位置：`C:\Program Files\SIMION-2020\simion.exe`（SIMION 8.2.0.11）。

本目录是唯一可写的SIMION项目目录；不要在`Program Files`中的示例或安装目录内Refine、保存PA或写结果。

## 目录

- `00_reference/`：当前COMSOL正式10/5环模型的参数、验证指标和待导出参考曲线。
- `01_accelerator/`：三栅加速器的3D PA#、GEM和Lua。
- `02_reflectron/`：10/5双级环栈反射镜的轴对称理想栅网 PA#、GEM和Lua。
- `03_grid_cell/`：真实丝网局部单元；只在理想栅网版本验证后启用。
- `04_workbench/`：PA实例、ION/FLY2、Lua记录程序和测试平面。
- `05_results/`：CSV、PNG和SIMION-对-COMSOL比较表。
- `examples_reference/`：从安装目录复制的Fast Adjust与非理想grid示例，仅作参考。
- `workbench/run_ideal_field_diagnostic.ps1`：先执行跨求解器几何门禁，再运行实际场/分区
  理想场矩阵；`-AnalyzeOnly`可按当前探测器口径重算已有完整过面日志。
- `tests/cross_solver/verify_geometry_contract.ps1`：联动测试硬门禁，任一共享尺寸、正式
  Lua、IOB实例或PA尺寸/网格不一致即失败。
- `accelerator/build_accelerator_variant.lua`：从同一正式GEM生成各向异性诊断PA；构建前
  估算10个电位数组连同PA#/表面元数据的实际总容量并按调用参数设置硬上限。
- `accelerator/verify_accelerator_variant.lua`与`verify_accelerator_override_field.lua`：
  分别核对PA头和运行时替换后的实例原点/场点，不保存或改写正式IOB。

## 分阶段目标

1. `ideal_grid`：所有栅网以一网格点厚的透明等势面建模，复现COMSOL正式模型。
2. `field_validation`：比较轴线电势、电场、转向深度及单粒子到达时间。
3. `statistics`：N=100、N=1000到达时间统计与COMSOL对照。
4. `nonideal_grid`：仅用高分辨率局部网格单元研究丝网透过、撞丝和横向kick；不把真实细丝铺满主PA。

## 首次操作

1. 打开`examples_reference/simion_fast_adjust_demo.gem`，另存为项目内PA#，完成一次Refine和Fast Adjust。
2. 打开`examples_reference/simion_nonideal_grid_demo.gem`，只观察网格尺度和边界构造，不修改主oa-TOF模型。
3. 依据`00_reference/oatof_final_10_5_baseline.json`建立两个独立3D PA：加速器和反射镜。
4. 栅网基线使用一网格点厚的全截面电极面；禁止使用“大板挖孔”替代细网。

## 当前正式COMSOL对照目标

- 配置：100 amu、真实场、`N1/N2=10/5`、`d1=120 mm`、`d2=86.8328 mm`、`bore_r=250 mm`。
- N=1000：1000/1000到达，平均到达时间`31.4478763926 us`，σ=`0.897802250264 ns`，
  `R=t/(2σ)=17513.8102`。
- 最大二级穿透约`51.07 mm`；真实丝网敏感性分析不得使用二级75%深度作为离子采样截面。

## 已完成的 SIMION 基线与网格闭合（更新至2026-07-14）

- `02_reflectron/oatof_reflectron_ideal_10_5.pa0`：2D cylindrical、1 mm/gu、19个电极，已按COMSOL正式电位 fast-adjust。
- 正式加速器GUI基线为3D Cartesian、`361×361×141`、0.25 mm/gu、9个电极；与COMSOL
  几何门禁、IOB持久化原点和7个场点保持联动。
- 数值闭合诊断使用同一GEM，裁掉78 mm接地屏蔽外部真空且只把z加密至0.125 mm，得到
  `313×313×281`、`dx/dy/dz=0.25/0.25/0.125 mm`的PA。N=1000为1000/1000命中，
  `sigma=0.834246 ns`、`R=t/(2sigma)=18849.4`，与COMSOL的0.897802 ns、17513.8分别
  相差-7.08%和+7.63%。同源N=100裁边控制证明xy裁剪只改变sigma约0.1%—0.2%，收敛
  来自z网格而非几何缩小。完整数据见`VALIDATION_LOG.md`。
