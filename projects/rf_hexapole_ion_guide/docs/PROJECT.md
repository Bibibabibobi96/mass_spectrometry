# RF六极杆离子导引项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。分段杆轴向加速和出口带孔接口板加速（历史简称“端面加速”）曾分别
通过COMSOL与SIMION N=100功能复验；这些run早于request/resolved schema v2，现只作为
[`family_contract.json`](../../../common/multipole/family_contract.json)中的`superseded_evidence`
保留，不构成当前功能PASS。v2须重新完成双求解器运行后才能恢复功能资格，更不授予网格收敛、
跨求解器数值等价、机械或Formal资格。

Phase 4已用[`../config/design_profiles.json`](../config/design_profiles.json)冻结
`baseline_finite_3d`的request、变量目录、包络SHA-256及`full_length_grounded_shield + uniform`
拓扑。项目L3薄wrapper只接受`RuntimeProfileId`，由版本化profile绑定design profile、canonical粒子
CSV的SHA和各求解器数值profile；任意粒子路径和自由数值不再属于生产入口。公共runner保留为低层
投影机制。无evidence contract的运行固定为`UNQUALIFIED`。

2026-07-28新增`no_acceleration_full_length`具名design/runtime profile：它保持当前79.6 mm全长杆、
圆柱外壳和紧邻接口几何，把分段关闭并把入口、杆共同偏置、出口带孔接口板全部冻结为0 V；同时预先冻结
`rf_vs_zero_rf`证据合同。当前只通过合同编译和静态门禁，尚未运行COMSOL/SIMION，因此不构成
N=100功能PASS、网格收敛或Candidate资格。

Phase 2设计配置把当前`n=3`、6根电极身份、`r0=4 mm`、圆杆比0.5、有限杆范围、圆柱接地屏蔽及
真空域、圆孔接口、canonical驱动和uniform四段参考冻结为单一求解器无关请求。33个数值变量均以
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
- 固定N=100、100 amu、+1、2 eV功能源；最大源半径0.5 mm，最大入射发散5°。
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
- L2从`baseline_finite_3d` governed profile即时编译resolved，再使用二维COMSOL场的谐波展开；
  只发布逐候选metrics，不选择或回写L3几何。未做网格收敛，不允许机械设计、Candidate或Formal声明。
- L3使用20 mm内半径连续接地圆柱外壳、独立外壳封闭端盖、完整有限圆杆、两块带孔接地接口板和
  两段有限外部区，COMSOL
  和SIMION均有功能入口；尚未完成网格收敛、跨求解器数值等价或Candidate资格门禁。

## 权威入口

- [`../config/requests/baseline.json`](../config/requests/baseline.json)
- [`../config/design_variables.json`](../config/design_variables.json)
- [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- [`../config/execution_profiles.json`](../config/execution_profiles.json)
- [`../config/design_profiles.json`](../config/design_profiles.json)
- [`../config/requests/no_acceleration_full_length.json`](../config/requests/no_acceleration_full_length.json)
- [`../config/design_variables_no_acceleration.json`](../config/design_variables_no_acceleration.json)
- [`../config/optimization_envelope_no_acceleration.json`](../config/optimization_envelope_no_acceleration.json)
- [`../config/evidence/no_acceleration_full_length.json`](../config/evidence/no_acceleration_full_length.json)
- [`../config/resolved_design.json`](../config/resolved_design.json)
- [`../config/runtime_profiles.json`](../config/runtime_profiles.json)
- [`../config/particle_source_profiles.json`](../config/particle_source_profiles.json)
- [`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)
- [`../config/simion_solver_numerics.json`](../config/simion_solver_numerics.json)
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
六/八极杆共同使用的固定N=100 CSV只有一份，位于
`common/multipole/sources/hex_oct_baseline_fixed_100.csv`；两个项目分别以profile和SHA绑定它。

## 下一步

多极杆公共机制已冻结，后续不再为本项目复制公共杆阵列、运行时或接口实现。v1离子导引和接口功能链
曾由COMSOL与SIMION独立贯通，但不能继承为v2当前资格。下一阶段不再增加模型层级；在需要把本设计
推进为Candidate时，先对无加速profile完成N=100双求解器功能运行，再进行各求解器独立网格/时间步
收敛、冻结同输入数值等价和机械baseline；没有N=1000、GUI/CAD同步与formal asset promotion时不得
声明Formal。碰撞冷却与CAD仍为独立后续阶段。轴向加速若
继续推进，须先建立项目具名design request与runtime profile，再研究分段数量、各段长度/间隙/电势、
馈电和机械实现；当前默认uniform四段参数仅保留v1历史功能依据，待v2双求解器N=100重验，且不是
正式硬件选择。

共享SIMION模板、GUI复核、`.wgem`绕过和跨机可移植性状态只由
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)维护；公共机制证据不授予
本项目Candidate或Formal资格。本项目还保留两项项目专属退出任务：

1. `project.json.contracts.baseline`暂因根registry builder的旧`multipole`身份检查保留只读
   `config/baseline.json`。根schema/builder改由design profile/request或独立identity contract校验，
   且三RF项目registry门禁通过后，解除该兼容绑定并按删除授权处理旧文件。
2. `config/finite_3d_transport.json`仍供旧family/L1测试读取。测试改为消费design request、resolved和
   solver-numerics profile且活动引用归零后，按删除授权退出该快照。
