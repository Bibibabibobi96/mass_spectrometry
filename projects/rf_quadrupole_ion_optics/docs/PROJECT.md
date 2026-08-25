# RF四极杆离子光学项目状态

本文件是本项目当前事实、资格边界和开放任务的唯一权威。共享编译、粒子源、术语和分析方法见
[`common/multipole/README.md`](../../../common/multipole/README.md)；完整旧运行表和故障链只查
[`history/`](history/)。

## 当前结论

- 当前圆柱家族机械base上的三个规范模式均完成COMSOL与SIMION N=100 baseline，两个求解器均
  100/100且交接粒子身份一致；只闭合功能分类。
- 无加速空间/时间敏感性矩阵已执行，但连续相空间没有可辩护接受尺度；结论保持
  `INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`。
- 分段杆和出口带孔接口板加速的SIMION相邻空间档已执行；两项COMSOL空间档受预登记资源帽限制，
  均为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不再事后抬帽。
- RF+DC质量过滤已有理论与有限几何功能响应；网格、跨求解器一致性和分辨能力未闭合。
- 当前RF多极杆→oaTOF integration已贯通四极杆功能链，但不授予连续相空间、分辨率、机械或整机
  Formal资格。
- 碰撞冷却物理尚未建立；旧150 mm碰撞脚本不是活动合同。

## 资格边界

| 对象 | 当前状态 |
|---|---|
| 三模式N=100功能 | PASS |
| 连续数值收敛/跨求解器等价 | INCONCLUSIVE |
| 接口就绪输运 | 历史严格相空间比较FAIL；当前机械base待新资格 |
| RF+DC质量过滤 | 功能证据；分辨能力未资格 |
| RF多极杆→oaTOF | integration功能贯通；整机Formal BLOCKED |
| 机械、CAD与本项目Formal | BLOCKED |

`Static`门禁可用；物理运行按workflow profile授权；机械与CAD闭环前`Formal`必须失败关闭。公共
工程推进合同的PASS只允许进入下一阶段，不回写上述`INCONCLUSIVE`。

## 当前机械与模式

识别性摘要如下；精确值只认机器合同。

| 项目 | 当前值 |
|---|---|
| 电极 | 四极、4根圆杆 |
| 场半径/杆半径比 | `r0=4 mm` / `0.5` |
| 杆区 | `z=0..79.6 mm`，4段×19.6 mm，3个0.4 mm间隙 |
| 规范轴向面 | release −1.5 mm；handoff 80.6 mm；near census 81.1 mm |
| RF | 1.1 MHz；幅值与DC由resolved发布 |
| 家族源 | 2 eV；N=100是N=1000母样本的精确前缀 |
| 三模式 | 全0 V；分段`0/−1/−2/−3 V`；杆全0且出口板−3 V |

四极杆`official_transport`矩形参考外壳只服务旧接口/质量过滤作用域，不是圆柱家族实验端口。不同
workflow可复用机制，但不得互相消费run或用`Mode`切换科学声明。

## 机器权威

| 职责 | 入口 |
|---|---|
| 身份与能力 | [`project.json`](../config/project.json) |
| 圆柱机械base与typed模式 | [`requests/baseline.json`](../config/requests/baseline.json)、[`operating_modes.json`](../config/operating_modes.json) |
| 变量与包络 | [`design_variables.json`](../config/design_variables.json)、[`optimization_envelope.json`](../config/optimization_envelope.json) |
| 具名设计 | [`design_profiles.json`](../config/design_profiles.json) |
| runtime与粒子源 | [`runtime_profiles.json`](../config/runtime_profiles.json)、[`particle_source_profiles.json`](../config/particle_source_profiles.json) |
| 三模式COMSOL/SIMION数值 | [`multipole_transport_comsol_solver_numerics.json`](../config/multipole_transport_comsol_solver_numerics.json)、[`simion_solver_numerics.json`](../config/simion_solver_numerics.json) |
| 三模式资格 | [`family_experiment/`](../config/family_experiment/) |
| 接口、质量过滤专用数值 | [`comsol_solver_numerics.json`](../config/comsol_solver_numerics.json) |
| 接口事件 | [`interface_contract.json`](../config/interface_contract.json) |
| 执行profile | [`execution_profiles.json`](../config/execution_profiles.json) |

活动runner只消费具名profile编译的完整request/resolved。CLI不得覆盖几何、RF/DC、静态电极或轴向
加速；SIMION入口可选择任意正数的RF步数/周期与trajectory quality，实际值会冻结到运行产物，偏离
数值基线的运行仅为未资格探索。缺失绑定必须在商业软件启动前失败关闭。

## 当前能力

- 无碰撞部件回归、接口就绪输运、RF+DC质量过滤和三模式轴向实验是四个独立workflow。
- 三模式正式统计binding必须在运行前冻结bootstrap、接受尺度、effect resolution和预算；既有缺少
  统计预登记的run只能发布`POSTHOC_DESCRIPTIVE`。
- N=1000 COMSOL bridge曾在粒子释放构造阶段资源中断；向量化释放候选也未通过等价门禁。这两条路线
  不属于当前生产入口，详见项目history和资格JSON。
- 工程比较与运行身份由机器资格记录和根
  [多极杆history](../../../docs/history/)保存，本PROJECT不维护第二份数值表。

## oaTOF连接

当前连接由
[integration入口](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)
拥有。项目只发布provided port和canonical handoff；connection profile负责连接器、位姿、公共电位、
时钟和下游场域。单流程或分阶段策略、当前census与oaTOF性能不得复制回本PROJECT。

## 开放任务

1. 依据[通用出口相空间方法](../../../docs/multipoles/exit_phase_space_control.md)建立新的具名筛选campaign；
   当前PROJECT不预选分段或端板模式，也不复制通用步骤。关闭条件是冻结下游接受尺度、唯一变量、
   共同幸存者分析和相邻数值档。
2. 若声明束斑、发散、能量或逐粒子等价，先预登记目标效应误差预算，再运行相称资格矩阵。
3. 为RF-only、RF+DC和轴向加速分别建立Candidate证据，不能以功能run互相替代。
4. 建立端部、屏蔽、馈通、装配与GUI/CAD机械闭环后，才开放Formal。
5. 若恢复oaTOF资格工作，在integration单独批准目标和指标，并完成N=1000、脉冲/时间步、分辨率、
   容差及机械装配；当前功能链不自动进入该阶段。
6. 碰撞冷却必须从当前机械base建立新物理合同和独立workflow。

## 产物与历史

活动产物位于`artifacts/projects/rf_quadrupole_ion_optics/`。改名前证据只按`project.json`的
`archived_verified`位置读取；旧顶层路径不回退。运行保留、迁移与裁剪只认manifest，不在current
文档复制字节数和完整run ID。
