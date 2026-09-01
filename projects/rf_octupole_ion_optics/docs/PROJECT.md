# RF八极杆离子光学项目状态

本文件只维护八极杆项目当前设计、资格、有效结论和开放任务。公共编译与术语见
[`common/multipole/README.md`](../../../common/multipole/README.md)；跨器件结果由
[RF多极杆→oaTOF integration](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)
拥有。

## 当前结论

- 三个规范模式由同一机械base和typed operating-mode registry编译，只改变电气模式；当前N=100
  baseline均已完成COMSOL与SIMION真实运行，100/100且交接粒子身份一致。
- 无加速空间/时间敏感性已执行，但连续量仍为
  `INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`。
- 两个加速模式的SIMION空间档已执行；COMSOL空间档均触发预登记资源帽，保持
  `INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不事后抬帽。
- 家族工程六指标可用于下游推进，不授予数值收敛、求解器等价、Candidate或Formal。
- N=1000 平面冻结源与独立轴向体积快照的 SIMION 成对传输已完成，并由 recovery analysis run
  `20260830_212610__analysis__python__oct-source-model-comparison-recovery__n1000` 发布；恢复只重做 Python
  分析与绘图，未重跑求解器。两臂均为 1000/1000 传输。体积快照在源端为同刻释放、z RMS 0.6251 mm、
  vz RMS 49.2820 m/s、动能 RMS 0.1005 eV，且 z--vz Pearson r=-0.01154；平面源的 z 宽度为零、连续
  birth-time 跨度非零。体积源出口空间 RMS 为 0.4169 mm（平面 0.5381 mm）、角 RMS 为 1.3490°
  （平面 3.2660°），实际墙钟 120.9 s（平面 128.8 s）。这是 source-model 的描述性对比，不构成
  数值收敛、探测器、Candidate 或 Formal 结论。
- 当前oaTOF连续SIMION单流程选择了八极杆末端加速方案，并确认高传输与10 eV目标注入；角度和z方向
  空间展宽仍未闭合。具体census、能量、2.2 mm源宽候选和PA重构结果只查integration。

## 资格边界

| 对象 | 当前状态 |
|---|---|
| 三模式N=100功能 | PASS |
| 连续数值收敛/跨求解器等价 | INCONCLUSIVE |
| N=1000多极杆统计资格 | 未完成 |
| oaTOF单流程 | `INCONCLUSIVE_DIAGNOSTIC_ONLY` |
| 机械、CAD、Candidate、Formal | BLOCKED |

已完成run缺少运行前冻结的bootstrap seed和resample数，不能事后发布为正式three-mode dispersion
binding；现有点估计只能保持`POSTHOC_DESCRIPTIVE`。

## 机械与电气合同

识别性摘要如下；求解器重建只认机器合同。

| 项目 | 当前值 |
|---|---|
| 电极 | 八极、8根圆杆，径向阶数`n=4` |
| 场半径/杆半径比 | `r0=4 mm` / `0.5` |
| 杆区 | `z=0..79.6 mm`，4段×19.6 mm，3个0.4 mm间隙 |
| 轴向面 | release −1.5 mm；handoff 80.6 mm；near census 81.1 mm |
| RF | 1.1 MHz，零到峰值139.81792 V |
| 家族源 | 100 amu、+1、2 eV；N=100为N=1000精确前缀 |
| 无加速 | 四段与出口板均0 V |
| 分段加速 | 四段`0/−1/−2/−3 V`，出口板−3 V |
| 出口孔板加速 | 四段0 V，出口板−3 V |

碰撞、空间电荷、磁场、支撑、公差和真实下游器件不属于本机械base。oaTOF连接器、入口参考套筒、
入口板和脉冲加速器由integration组合，不得反向写入本项目base。

## 数值合同

| 层级 | COMSOL局部最大单元 / 步每RF周期 | SIMION cell / 步每RF周期 |
|---|---|---|
| baseline | 0.5 mm / 80 | 0.4 mm / 40 |
| spatial refined | 0.35 mm / 80 | 0.3 mm / 40 |
| temporal refined | 0.35 mm / 160 | 0.3 mm / 80 |

空间比较只改变空间离散；时间比较固定已选细网格。缺少接受尺度时不能发明百分比PASS。资源预算见
项目资格合同，耗尽即停止且零自动重试。

## 机器权威

| 职责 | 入口 |
|---|---|
| 机械request | [`mechanical_base.json`](../config/requests/mechanical_base.json) |
| 变量与包络 | [`design_variables.json`](../config/design_variables.json)、[`optimization_envelope.json`](../config/optimization_envelope.json) |
| typed模式 | [`operating_modes.json`](../config/operating_modes.json) |
| 设计profile | [`design_profiles.json`](../config/design_profiles.json) |
| runtime与源 | [`runtime_profiles.json`](../config/runtime_profiles.json)、[`particle_source_profiles.json`](../config/particle_source_profiles.json) |
| 求解器数值 | [`comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)、[`simion_solver_numerics.json`](../config/simion_solver_numerics.json) |
| 资格 | [`qualification/`](../config/qualification/) |
| 工程推进 | [`engineering_progression_acceptance.json`](../../../common/multipole/engineering_progression_acceptance.json) |

活动L1/L2/L3只消费具名profile。旧设计/runtime alias和旧resolved快照不是活动输入；无加速具名发布
`resolved_design_no_acceleration_full_length.json`只是当前profile的发布视图。

## oaTOF资格影响

integration中的1.5 mm入口参考套筒和10 eV连续单流程使用真实八极杆输出，证明当前末端方案可提供
高传输且在加速器内达到目标能量；它也证明角度和脉冲前z展宽仍超过理想源尺度。后续2.2 mm理论源宽
候选没有改变八极杆源、handoff或脉冲前相空间，因此不改变本项目资格。详情见
[integration当前状态](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)。

## 开放任务

1. 依据[通用出口相空间方法](../../../docs/multipoles/exit_phase_space_control.md)建立新的具名筛选campaign；
   本PROJECT不预选分段或端板模式。关闭条件是冻结真实下游接受尺度、唯一变量、损失约束、共同
   幸存者分析和相邻数值档。
2. 若推进连续量资格，为资源受限的加速模式建立有依据的新预算或替代离散策略，不得事后抬帽。
3. 新统计实验必须先冻结bootstrap设置，再运行N=1000；不能回填到既有证据。
4. 若修改该来源模型比较，须保持八极杆、下游端口、数值合同和完整粒子 ID 母队列固定，仅改变 receipt-bound
   source model；新运行仍须从 canonical 输出报告全源传输、损失分类和实际 wall-clock，且不得解释为数值收敛或
   Candidate 证据。
5. Candidate/Formal前建立制造基线、GUI/CAD同步、机械装配和完整统计证据。
6. 碰撞冷却保持独立workflow，不由无碰撞或oaTOF结果代替。

## 历史

完整三模式、网格、接口孔、10 eV及单流程时间线保存在项目
[`history/`](history/)和根[`docs/history/`](../../../docs/history/)；本文件不复制run清单或被取代
数值。活动产物只写`artifacts/projects/rf_octupole_ion_optics/`。
