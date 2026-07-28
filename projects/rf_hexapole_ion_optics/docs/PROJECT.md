# RF六极杆离子光学项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。分段杆轴向加速和出口带孔接口板加速（历史简称“端面加速”）曾分别
通过COMSOL与SIMION N=100功能复验；这些run早于request/resolved schema v2，现只作为
[`family_contract.json`](../../../common/multipole/family_contract.json)中的`superseded_evidence`
保留，不构成当前功能PASS。v2须重新完成双求解器运行后才能恢复功能资格，更不授予网格收敛、
跨求解器数值等价、机械或Formal资格。

当前家族实验已用[`../config/design_profiles.json`](../config/design_profiles.json)冻结
`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`三个canonical profile。三者共享唯一
`mechanical_base.json + design_variables.json + optimization_envelope.json`，只由
`operating_modes.json`映射三项电气量；`baseline_finite_3d`和
`exit_aperture_plate_acceleration_reference`仅为兼容alias，不是第二机械权威。项目L3薄wrapper只接受
`RuntimeProfileId`，由版本化profile绑定design profile、canonical粒子
CSV的SHA和各求解器数值profile；任意粒子路径和自由数值不再属于生产入口。公共runner保留为低层
投影机制。无evidence contract的运行固定为`UNQUALIFIED`。

当前`no_acceleration_full_length`保持79.6 mm杆、圆柱外壳、紧邻接口几何及四段物理导体，把四段和
出口带孔接口板电位全部冻结为0 V。2026-07-28完成的同名双求解器功能复验和随后数值矩阵属于改名前
`rf_hexapole_ion_guide`、旧固定N=100源（SHA-256
`494CB26FA128C475CB2DC1DB1A3437342DFBB5D1C1900E811E4BEBF47D7A6385`）及旧resolved几何；其run只在
`project.json`登记的legacy artifact根中只读保留。当前家族实验改为始终存在的四物理段和公共母样本
前缀后，这些结果不得继承为功能、收敛、跨求解器数值等价或Candidate资格。

Phase 2设计配置把当前`n=3`、6根电极身份、`r0=4 mm`、圆杆比0.5、有限杆范围、圆柱接地屏蔽及
真空域、圆孔接口、canonical驱动和uniform四段参考冻结为单一求解器无关请求。34个数值变量均以
请求JSON pointer、单位和双向边界声明；pole count保持项目身份，外壳model与连接器shape保持受支持
的锁定拓扑。注册execution profile仍是compile-only；薄wrapper运行公共runner时，无evidence合同只能
生成`UNQUALIFIED`结果。

项目已建立独立身份和理想有限长度L1传输合同。模型使用六根交替极性电极对应的理想六极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。L1/L2/L3迁移前小样本及2 mm连接器数值只保留在
[`history/20260723__pre-n100-multipole-functional-evidence.md`](history/20260723__pre-n100-multipole-functional-evidence.md)，
不构成当前Candidate证据。

## 当前参数与边界

- 阶数`n=3`，电极数6，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 坐标、`r0`和双极性组电压语义由`common/multipole/family_contract.json`统一；具体物理量只由项目
  design request编译，数值设置只由solver-numerics profile发布，并在每个run冻结。
- 新家族实验的N=100和N=1000源由同一版本化算法/seed生成，前者是后者精确前缀；100 amu、+1、
  2 eV，最大源半径0.5 mm，最大入射发散5°。旧六/八N=100只供legacy功能兼容。
- baseline pilot后、refined运行前登记的N=100数值三档为：COMSOL基线
  `0.5 mm/80 steps per RF period`、空间敏感性`0.35 mm/80`、在同一`0.35 mm`网格上的时间
  敏感性`160`；SIMION对应为`0.4 mm/40`、`0.3 mm/40`和在同一`0.3 mm`网格上的`80`。
  时间比较必须使用空间敏感性档作为对照，
  不得回到粗网格，也不增加第四档。
- 入口和出口孔半径均为3.6 mm；入口、出口连接器长度当前均为0 mm（直连合同）。入口带孔接口板
  上/下游面为`z=-1.0/-0.5 mm`，源释放面为`z=-1.5 mm`；出口带孔接口板上/下游面为
  `z=80.1/80.6 mm`，出口孔穿越面与零长度连接器的规范交接面在`z=80.6 mm`，近接口统计面为
  `z=81.1 mm`。外壳封闭端盖是屏蔽外壳的独立实体面，不是上述带孔接口板。绝对位置只由request
  编译后的接口合同派生；即使穿越面与交接面坐标重合，事件职责仍不同。
- Gate 0把源释放面和近接口统计面限定为紧邻接口发散：两者分别距杆入口/出口1.5 mm，统计面仅在
  出口带孔接口板下游面后0.5 mm。Pittman与O'Connor的真实FT-ICR六极杆接口设计报告9.53 mm内径导引器之间
  5.21 mm总间距和2.67 mm剩余边缘场区
  （[JASMS 16 (2005) 441–445](https://doi.org/10.1016/j.jasms.2004.12.010)）；据此当前毫米级间距
  不属于失去物理意义的远距离，但这是尺度相容的设计判断，不是本机械实现的直接复现。当前近接口
  统计面不得解释为数厘米下游远场；真实下游匹配须另建带独立漂移距离/观察面的workflow。
- 碰撞、空间电荷、磁场、支撑和机械公差均未启用。
- L2从兼容alias `baseline_finite_3d`即时编译resolved，再使用二维COMSOL场的谐波展开；
  只发布逐候选metrics，不选择或回写L3几何。未做网格收敛，不允许机械设计、Candidate或Formal声明。
- L3使用20 mm内半径连续接地圆柱外壳、独立外壳封闭端盖、四段有限圆杆、两块带孔接地接口板和
  两段有限外部区；当前三模式均尚未用公共N=100前缀完成COMSOL/SIMION功能、空间/时间收敛和连续
  相空间数值等价，也未完成Candidate资格门禁。

## 权威入口

- [`../config/requests/mechanical_base.json`](../config/requests/mechanical_base.json)
- [`../config/operating_modes.json`](../config/operating_modes.json)
- [`../config/design_variables.json`](../config/design_variables.json)
- [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- [`../config/execution_profiles.json`](../config/execution_profiles.json)
- [`../config/design_profiles.json`](../config/design_profiles.json)
- [`../config/resolved_design.json`](../config/resolved_design.json)
- [`../config/interfaces/provided/rf_multipole_exit.json`](../config/interfaces/provided/rf_multipole_exit.json)
- [`../config/runtime_profiles.json`](../config/runtime_profiles.json)
- [`../config/particle_source_profiles.json`](../config/particle_source_profiles.json)
- [`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)
- [`../config/simion_solver_numerics.json`](../config/simion_solver_numerics.json)
- [`../config/qualification/n100_convergence_preregistration.json`](../config/qualification/n100_convergence_preregistration.json)
- [`../config/qualification/dispersion_acceptance.json`](../config/qualification/dispersion_acceptance.json)
- [`../config/qualification/dispersion_effect_resolution.json`](../config/qualification/dispersion_effect_resolution.json)
- [`../config/qualification/engineering_budget.json`](../config/qualification/engineering_budget.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../config/round_rod_field_screen.json`](../config/round_rod_field_screen.json)
- [`../analysis/run_round_rod_field_screen.ps1`](../analysis/run_round_rod_field_screen.ps1)
- [`../analysis/run_round_rod_transport.ps1`](../analysis/run_round_rod_transport.ps1)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

`config/baseline.json`和`config/finite_3d_transport.json`仅为历史L1/L3兼容快照，不得接收新参数或
供活动L3 solver直接消费。前者只因当前registry schema保留为旧格式项目身份检查，不构成solver权威。
`config/requests/baseline.json`、`requests/no_acceleration_full_length.json`、
`requests/exit_aperture_plate.json`及其专属catalog/envelope只保留历史/兼容读取；当前家族实验不得引用。
`config/evidence/no_acceleration_full_length.json`和
`config/evidence/exit_aperture_plate_acceleration_reference.json`中的固定功能阈值同样只保留给旧profile复现，
不得绑定当前公共母样本三模式，也不得替代`config/qualification/`中显式保持`INCONCLUSIVE`的资格判据。
`rf_multipole_exit`只发布`resolved_design.json`的出口交接视图；其来源SHA和逐值binding防止陈旧，
frame、轴向法向、中心向量、RF相位零点clock及场是否到达交接面的派生前提由项目直接测试冻结。
四/六/八极杆当前家族实验共同使用
`common/multipole/sources/rf_multipole_family_mother_sample_v1_1000.csv`及其精确
`..._100.csv`前缀；metadata冻结单一生成算法、seed、分布和SHA。旧
`hex_oct_baseline_fixed_100.csv`不属于新实验。

## 下一步

多极杆公共机制已冻结，后续不再为本项目复制公共杆阵列、运行时或接口实现。v1离子导引和接口功能链
曾由COMSOL与SIMION独立贯通，但不能继承为当前三模式资格。新的三模式机械base、typed电气合同、
N=100/N=1000源和N=100三档数值矩阵已经预登记，但没有有依据的连续量阈值。当前只授权无加速
N=100 baseline双求解器pilot已经完成：两边均为RF 100/100、zero-RF 21/100且传输粒子身份一致；
当前只授权相邻空间敏感性pair，COMSOL/SIMION分别受1200/720 s、2 GiB瞬态目录、16 GiB进程树内存、
8 GiB最低可用内存、25 MiB compact保留和零自动重试约束。时间档和完整商业矩阵尚未授权，
连续结果只能`INCONCLUSIVE`。正式
`three_mode_dispersion_binding`还需要真实solver handoff state路径/SHA，只能在真实run后生成；静态阶段
不得伪造。没有N=1000真实运行、GUI/CAD同步与formal asset promotion时不得
声明Formal。碰撞冷却与CAD仍为独立后续阶段。轴向加速若
继续推进，应使用当前typed runtime profile研究各段电势，同时另行研究分段数量、长度/间隙、
馈电和机械实现；当前uniform四段参数是家族实验机械baseline，不是
正式硬件选择。

共享SIMION模板、GUI复核、`.wgem`绕过和跨机可移植性状态只由
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)维护；公共机制证据不授予
本项目Candidate或Formal资格。

项目L3薄wrapper默认使用根README定义的`compact`产物保留类；数值资格或GUI复核需要MPH、PA解阵列或
完整轨迹时，必须在运行前显式选择非compact类并写明理由。该设置只管理产物，不是数值或资格参数。

活动产物位于`artifacts/projects/rf_hexapole_ion_optics/`；改名前证据继续只读保存在
`config/project.json`登记的legacy artifact根，不搬移、不改写旧manifest、不追加新run，也不改变其
原身份、状态和声明边界。

本项目还保留两项项目专属退出任务：

1. `project.json.contracts.baseline`暂因根registry builder的旧`multipole`身份检查保留只读
   `config/baseline.json`。根schema/builder改由design profile/request或独立identity contract校验，
   且三RF项目registry门禁通过后，解除该兼容绑定并按删除授权处理旧文件。
2. `config/finite_3d_transport.json`仍供旧family/L1测试读取。测试改为消费design request、resolved和
   solver-numerics profile且活动引用归零后，按删除授权退出该快照。
