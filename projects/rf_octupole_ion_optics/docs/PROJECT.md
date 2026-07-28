# RF八极杆离子光学项目状态

## 当前结论

2026-07-28起，八极杆三种传输/轴向加速工况已改为一个机械base、一个变量目录、一个优化包络和一个
typed operating mode registry。三个规范profile由公共编译器在内存中只施加电气模式，机械实体、
接口、RF和粒子源保持严格相同。该转型已具备静态合同和纯Python回归；本轮没有运行COMSOL、SIMION、
GUI或CAD，因此不恢复旧run的功能、收敛、跨求解器、Candidate或Formal资格。

旧的`baseline_finite_3d`和`exit_aperture_plate_acceleration_reference`保留为兼容alias，分别映射
`segmented_rod_axial_acceleration`和`exit_aperture_plate_acceleration`。alias不保存机械副本，
不构成额外实验arm；新文档和新run应使用规范mode名称。

## 机械与电气合同

- 八极杆：`radial_order_n=4`，8根圆柱杆，`r0=4 mm`，杆半径比`0.5`。
- 杆轴向范围：`0..79.6 mm`。
- 四个导体段：`[0,19.6]`、`[20.0,39.6]`、`[40.0,59.6]`、
  `[60.0,79.6] mm`；三个间隙均为`0.4 mm`。
- 释放面：`z=-1.5 mm`。
- 入口带孔接口板：`z=-1.0..-0.5 mm`。
- 出口带孔接口板：`z=80.1..80.6 mm`。
- 规范交接面：`z=80.6 mm`；近接口统计面：`z=81.1 mm`。
- `no_acceleration_full_length`：四段`0/0/0/0 V`，出口板`0 V`。
- `segmented_rod_axial_acceleration`：四段`0/-1/-2/-3 V`，出口板`-3 V`。
- `exit_aperture_plate_acceleration`：四段`0/0/0/0 V`，出口板`-3 V`。

RF为1.1 MHz余弦、每组零到峰值139.81792 V；源为100 amu、+1、2 eV。碰撞、空间电荷、磁场、
支撑、公差和真实下游器件仍未进入本机械base。

## 数值预登记

每个规范mode使用相同N=100源和三个runtime层级：

|层级|COMSOL局部最大单元|COMSOL步/周期|SIMION cell|SIMION步/周期|
|---|---:|---:|---:|---:|
|baseline|0.5 mm|80|0.4 mm|40|
|spatial refined|0.25 mm|80|0.2 mm|40|
|temporal refined|0.25 mm|160|0.2 mm|80|

空间比较只改变空间离散；时间比较在已选细网格上保持空间离散不变，只改变每RF周期步数，符合根
`docs/VALIDATION_METHODS.md`的顺序门禁。没有物理、下游或误差预算支持
时不得发明百分比作为PASS阈值，结果固定为`INCONCLUSIVE`。当前只授权无加速N=100 baseline
双求解器pilot：COMSOL/SIMION分别受1200/300 s、2 GiB瞬态目录、16 GiB进程树内存、8 GiB最低
可用内存、25 MiB compact保留和零自动重试约束；其他runtime由
[`../config/qualification/engineering_budget.json`](../config/qualification/engineering_budget.json)
失败关闭。

N=100 baseline runtime key直接使用三种完整mode ID；加密key分别追加`_n100_spatial_refined`和
`_n100_temporal_refined`。三个N=1000统计runtime追加`_n1000`并绑定同一母样本的N1000档。
solver numerics ID与四/六极杆统一为`baseline_finite_3d`、`n100_spatial_refined`和
`n100_temporal_refined`。

三模式发散实验的方法来自`common/multipole/three_mode_dispersion_contract.json`。本项目已登记
acceptance、effect-resolution、engineering-budget和三份电压合同，但前两者尚无可辩护尺度；它们
只防止事后挑阈值，不授予资格。项目preregistration不是公共正式binding：只有真实solver run已发布
三份canonical handoff-state并冻结对应numerics SHA后，才生成一个solver专属正式binding；缺少真实
状态固定`FAIL_CLOSED_NO_FORMAL_BINDING`。

## 权威入口

- [`../config/requests/mechanical_base.json`](../config/requests/mechanical_base.json)
- [`../config/design_variables.json`](../config/design_variables.json)
- [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- [`../config/operating_modes.json`](../config/operating_modes.json)
- [`../config/design_profiles.json`](../config/design_profiles.json)
- [`../config/runtime_profiles.json`](../config/runtime_profiles.json)
- [`../config/particle_source_profiles.json`](../config/particle_source_profiles.json)
- [`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)
- [`../config/simion_solver_numerics.json`](../config/simion_solver_numerics.json)
- [`../config/qualification/n100_convergence_preregistration.json`](../config/qualification/n100_convergence_preregistration.json)
- [`../config/qualification/three_mode_dispersion_preregistration.json`](../config/qualification/three_mode_dispersion_preregistration.json)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

`config/requests/baseline.json`、`config/requests/no_acceleration_full_length.json`、
`config/requests/exit_aperture_plate.json`、各自旧catalog/envelope以及`config/finite_3d_transport.json`
都是兼容或历史快照，不得成为新run输入。`config/resolved_design.json`是无加速规范profile的静态发布
视图；其他模式在runtime解析时由同一base和typed registry生成。

## 未决

1. 为接受尺度绑定真实下游器件的孔径/相空间预算，或建立可审查的项目误差预算；此前只能报告
   `INCONCLUSIVE`。
2. 完成已登记wall clock与峰值内存预算的无加速N=100 baseline pilot，再按实测值决定相邻加密档。
3. 三种模式各自完成独立COMSOL/SIMION运行、共同幸存粒子配对和跨求解器闭合。
4. 若推进Candidate/Formal，再建立机械制造基线、GUI/CAD同步和N=1000统计证据。
5. 碰撞冷却和真实下游连接保持独立workflow，不由无碰撞三模式结果代替。
