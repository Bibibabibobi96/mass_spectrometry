# RF八极杆离子光学项目状态

## 当前结论

2026-07-28起，八极杆三种传输/轴向加速工况已改为一个机械base、一个变量目录、一个优化包络和一个
typed operating mode registry。三个规范profile由公共编译器在内存中只施加电气模式，机械实体、
接口、RF和粒子源保持严格相同。当前三个N=100 baseline均已完成COMSOL与SIMION真实运行并以
100/100及相同交接粒子身份闭合功能分类；连续数值、Candidate和Formal资格仍未闭合。

四、六、八极杆共同的临时下游工程方向由
[`engineering_progression_acceptance.json`](../../../common/multipole/engineering_progression_acceptance.json)
统一记录；本项目只声明适用性，不复制阈值、状态或判定。后续先复用现有SIMION状态并只补最小相邻
加密臂；任何工程PASS都不得改称数值收敛或求解器等价。

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
|spatial refined|0.35 mm|80|0.3 mm|40|
|temporal refined|0.35 mm|160|0.3 mm|80|

空间比较只改变空间离散；时间比较在已选细网格上保持空间离散不变，只改变每RF周期步数，符合根
`docs/VALIDATION_METHODS.md`的顺序门禁。没有物理、下游或误差预算支持
时不得发明百分比作为PASS阈值，结果固定为`INCONCLUSIVE`。无加速N=100 baseline双求解器pilot
和空间敏感性pair已经完成，各档两边均为RF 100/100、zero-RF 21/100且粒子身份一致；当前只授权
固定0.35/0.3 mm的时间敏感性pair也已完成；SIMION时间RMS半径变化约`0.0033%`，COMSOL约
`2.19%`，最终跨求解器RMS半径/发散角差约`3.85%/4.62%`。功能传输闭合，连续结果仍为
`INCONCLUSIVE`，不得增加第四档。最大实测为572.776 s、1.047 GB瞬态目录和8.673 GB进程树内存；
2026-07-31无加速定向跟进完成SIMION A/R/Z/I/T五臂和COMSOL局部0.20 mm的160→320步时间pair。
SIMION径向/轴向RMS半径变化为`3.066%/0.309%`，I→T为`0.000133%`且只在固定分箱下稳定；
COMSOL时间变化为`3.980%`且仍跨固定分箱。功能保持100/100，连续结论为
`INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`；机器身份见
[`followup_result.json`](../config/qualification/no_acceleration_followup/followup_result.json)。
分段杆轴向加速N=100 baseline已在两求解器保持100/100传输和精确粒子身份；SIMION空间档也
保持100/100，RMS半径、发散角和平均能量相对baseline分别变化约`2.39%`、`7.98%`和`0.196%`。
COMSOL空间档在`MESH_COMPLETE`后以19.180 GB超过17.180 GB进程树帽，记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不重跑、不抬帽。
出口孔板加速N=100 baseline已在两求解器保持100/100传输和精确粒子身份；SIMION空间档也
保持100/100，RMS半径、发散角和平均能量相对baseline分别变化约`0.67%`、`6.72%`和`0.80%`。
COMSOL空间档在`MESH_COMPLETE`后以17.181 GB超过17.180 GB进程树帽，记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不重跑、不抬帽。当前没有授权任何商业求解器运行；
时间档、N=1000和完整矩阵仍未授权。出口孔板功能能量增益使用下游terminal/census状态；跨求解器
连续诊断使用规范handoff状态，两者不得混作同一观察面。出口孔板身份和资源结论登记在
`../config/qualification/n100_exit_aperture_plate_acceleration_qualification.json`。
完整身份登记在
`../config/qualification/n100_no_acceleration_qualification.json`。
分段杆轴向加速身份和资源结论登记在
`../config/qualification/n100_segmented_rod_axial_acceleration_qualification.json`。
2026-07-31声明式SIMION H15 N=100三模式对照中，出口孔板加速相对无加速把中心化空间/角RMS降低
`0.0995 mm/0.6912°`；相对分段加速，空间RMS低`0.1563 mm`，但角RMS高`0.6438°`。它避免了同一
H15条件下分段加速空间RMS略增的信号；统一九臂证据见
[`../../../docs/history/20260731__multipole-three-mode-h15-n100.md`](../../../docs/history/20260731__multipole-three-mode-h15-n100.md)。
该结果只用于工程取舍，不改变数值资格。统一图组和机器摘要已发布为成功analysis run
`20260731_223000__analysis__python__multipole-three-mode-h15-n100`，不再依赖scratch。
同日另以当前ACTIVE六指标工程合同正式评价无加速T→H15相邻横向加密：质心位置、中心化空间展宽、
平均方向、中心化角展宽、平均能量和中心化能量展宽差依次为`0.003254 mm`、`0.017724 mm`、
`0.161877°`、`0.017208°`、`0.001544 eV`和`0.009394 eV`，机器结论为`PASS`；analysis run为
`20260731_223300__analysis__python__oct-simion-t-to-h15`。它只允许工程推进，数值收敛仍为
`DEFERRED_NOT_WAIVED`。包含本项目在内的家族18项既有比较也已按ACTIVE合同重分析为18/18 PASS，
统一记录见
[`../../../docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md`](../../../docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md)。
随后统一oaTOF屏蔽罩终端H15 campaign完成9/9；八极杆无加速/分段/终端阶跃的handoff分别为
`59/41/70`，穿过4 mm厚矩形孔后的terminal分别为`43/34/62`。终端阶跃同时给出本项目最高terminal
透射`62/100`、最高terminal/handoff`88.6%`和最小handoff中心化空间RMS`0.3215 mm`；分段模式的
中心化角RMS更小，为`2.1969°`。完整对照见
[`../../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md`](../../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md)。
这是新矩形厚孔拓扑下的N=100事后工程结果，不可与旧独立末端板H15表作仅模式变化的配对比较，也不
改变数值资格。
COMSOL/SIMION分别受1200/720 s、2 GiB瞬态目录、16 GiB进程树内存、8 GiB最低
可用内存、25 MiB compact保留和零自动重试约束；其他runtime由
[`../config/qualification/engineering_budget.json`](../config/qualification/engineering_budget.json)
失败关闭。

N=100 baseline runtime key直接使用三种完整mode ID；加密key分别追加`_n100_spatial_refined`和
`_n100_temporal_refined`。三个N=1000统计runtime追加`_n1000`并绑定同一母样本的N1000档。
solver numerics ID与四/六极杆统一为`baseline_finite_3d`、`n100_spatial_refined`和
`n100_temporal_refined`。

另有独立的无加速混合网格粒子收敛预登记：
`../config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json`。
它登记`0.25 mm/160`参考、`0.20 mm/160`空间加密和`0.25 mm/80`时间粗档，使用独立工程预算。
六极杆混合源下游A/B在2026-07-30满足预注册扩展规则后，只授权首个参考arm用于生成八极杆
oaTOF source revision。参考run
`20260730_231701__sim__comsol__oct-noacc-hybrid-exit025-t160__r01`为100/100传输；接入固定oaTOF链后
得到`100→46→34→34→10→10`，相对旧COMSOL源为`0,-12,-2,-2,-6,-6`。15个共同局部出口粒子的
位置、速度、时间、能量RMS差分别为1.1674 mm、2357.1 m/s、0.07206 µs和107.56 eV。空间和时间arm仍
未授权，且不继承六极杆结果或收敛结论；当前差异只支持source revision敏感性诊断。

三模式发散实验的方法来自`common/multipole/three_mode_dispersion_contract.json`。本项目已登记
acceptance、effect-resolution、engineering-budget和三份电压合同，但前两者尚无可辩护尺度；它们
只防止事后挑阈值，不授予资格。项目preregistration不是公共正式binding：只有真实solver run已发布
三份canonical handoff-state并冻结对应numerics SHA后，才生成一个solver专属正式binding；缺少真实
状态固定`FAIL_CLOSED_NO_FORMAL_BINDING`。
现有preregistration没有在这些run之前冻结bootstrap seed与resample数，因而不得把运行后选择的
bootstrap设置伪称为预注册。公共正式发布入口对此固定失败关闭。2026-07-29已另行发布COMSOL和
SIMION两份`POSTHOC_DESCRIPTIVE` binding和报告：只含点估计，不计算bootstrap、不评价资格。若未来
需要统计分散证据，必须先完成包含bootstrap设置的新预注册，再执行对应的新run。

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
- [`../config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json`](../config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json)
- [`../config/qualification/three_mode_dispersion_preregistration.json`](../config/qualification/three_mode_dispersion_preregistration.json)
- [`../../../common/multipole/engineering_progression_acceptance.json`](../../../common/multipole/engineering_progression_acceptance.json)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

旧的baseline/no-acceleration/exit-aperture-plate request及其专属catalog/envelope已在活动消费者
归零后退出；当前三模式只使用单一`config/requests/mechanical_base.json`与typed operating-mode
registry。旧finite-3D快照及resolver已在消费者迁移到current合同后退出。
`config/resolved_design.json`是无加速规范profile的静态发布视图；其他模式在runtime解析时由同一base
和typed registry生成。`config/project.json`的注册身份由全部design profile的一致identity给出，
不绑定历史`config/baseline.json`；尚未迁移的兼容路径只能只读访问该旧文件。

## 未决

1. 为接受尺度绑定真实下游器件的孔径/相空间预算，或建立可审查的项目误差预算；此前只能报告
   `INCONCLUSIVE`。
2. 若批准混合网格粒子收敛活动，严格按预登记的参考、空间、时间顺序执行；任一资源或结构门禁失败即停止。
3. 若推进连续量数值资格，为资源受限的加速模式建立有依据的新预算或替代离散策略；不得事后抬帽。
4. 若推进Candidate/Formal，再建立机械制造基线、GUI/CAD同步和N=1000统计证据。
5. 碰撞冷却和真实下游连接保持独立workflow，不由无碰撞三模式结果代替。
