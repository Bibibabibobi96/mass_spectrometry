# RF八极杆离子光学项目状态

本文件只维护八极杆项目当前设计、资格、有效结论和开放任务。公共编译与术语见
[`common/multipole/README.md`](../../../common/multipole/README.md)；跨器件结果由
[统一装配与物理工作流](../../../integrations/README.md)
拥有。

## 统一组装迁移任务

按[统一组装计划](../../../docs/ROADMAP.md#统一组装迁移计划)实施提供方接口，独立运行入口保持。
待将本项目机械base、端口、RF及源合同映射到统一配方；本项目八极杆与IP提供的裸导引须保留不同来源
身份，不能因同为八根杆而互换几何、驱动或粒子母群。关闭条件是原oaTOF消费者在冻结输入下完成投影、
handoff及绝对时钟对照；真实IP上游接入另补物理验证。既有封存输入与资格边界保持。
接口语义只按[组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)。

### 真实外出口的独立模型

历史SIMION模型的内部handoff位于z=80.6 mm，数值终止标记在81.1 mm；其81.6～82.1 mm外端盖为
实心。因此原100/100结果只证明内部handoff传输，不证明离子已穿过整个器件的最外端盖，不回写历史证据。

新增作者请求[through_exit.json](../config/requests/through_exit.json)显式选择
`cylindrical_grounded_shield_through_exit_v1`：外端盖沿作者出口孔径同轴贯通，不再另设第二份孔径。
具名design profile为`through_exit_no_acceleration`，N=100 runtime profile为
`through_exit_no_acceleration_n100`，使用原家族母样本及0.3 mm网格；物理外端面仍为82.1 mm，
数值域显式延至82.7 mm，给真实出口后的观察和终止留出网格余量，不能把数值域延伸解释成金属加长。

当前静态配置门禁按旧followup实际选中的arm核对runtime的源／设计／预算／数值profile绑定，
并核对完整已选数值语义；追加无关profile不会改变这些arm。旧预登记中的整registry SHA保持原字节，
只记录当时整表的来源身份；未保存该整表冻结副本，因此不能把今天活动整表的SHA当作历史副本验证。
resolution及各arm独立预算仍验证实际文件SHA，已选源绑定或步数变化仍由反例回归拒绝。
这项门禁修正不改变旧运行、参数、预登记或资格。

新请求已通过内存编译／GEM投影与[独立功能预算](../config/qualification/through_exit_functional_budget.json)
校验。实际运行`20261022_210633__sim__simion__octupole-through-exit-n100`已完成新求场与N=100飞行，
完整manifest的64项输出校验通过；100个原始ID全部真实穿过82.1 mm外端面，穿面绝对时间为
42.4896679278～43.6467650702 µs。真实步长前后状态包围出口，位置／速度／时间插值及完整母群校验通过。
canonical clock保留原出生与零instrument epoch；这些机械出口状态可用于显式state handoff的后续功能验证，
不授予接口边缘场截断、数值收敛、COMSOL、GUI/CAD或Formal资格。

第一次运行`20261022_210052…`在Fly启动时报不存在的电极11；原因是新GEM已删除旧吸收电极，
运行配置仍为其赋压。修复只从新模型的电压绑定及PA basis清单删除该电极，不补假几何；43项公共runner回归通过。
成功重跑保持相同resolved设计与母样本。机械出口后的终态记录保留SIMION实际停止回退状态及`unknown`原因，
不能将其当作100个机械出口前损失，也不能伪造数值guard上的物理撞击状态。

### 双端贯通提供者设计

具名 design profile `through_entrance_exit_no_acceleration`复用
[through_exit.json](../config/requests/through_exit.json)、原变量包络及`no_acceleration_full_length`电气模式，
仅通过显式`enclosure_model`选择已实现的双端贯通机械变体。两端真实孔径、端面和所有RF/DC数值仍由
同一请求编译，不另存完整机械请求或复制工作点。选择进入resolved的governance并由原编译器重放验证；
原`through_exit_no_acceleration`的机械、电气与输出身份不变。

当前纯回归已覆盖profile→resolved→真实双端口与GEM消费、原请求不变及非法选择拒绝。
2026-10-25项目静态门禁修正了仅列单端贯通variant的旧预期；三类typed电气模式保持，双端profile
额外核对共用请求／包络、仅enclosure模型改变，以及两端真实端面、法向、壁厚和来源孔径。
完整项目35项纯回归通过（18.438 s）；未修改生产实现或机器配置。
该设计尚未执行新的原生求场、飞行或多实例验收，不代表三重四极杆性能、数值收敛或Formal资格。

### 100Da 完整母群源

完整链路的当前 100 Da N=100 母群源权威是
[family_complete_mother_n100.json](../config/sources/family_complete_mother_n100.json)。它声明 N=100 即本实验的完整母群，
由具名 `family_complete_mother_n100` profile 以公共 release materializer 在 run 内物化一次；不在仓库保存同义 CSV。
该源已与 20261022_210633 的原 CSV 逐字节重建一致；其在 125626 的纯 preparation 装配投影也与 094111 的
local source 和 `projected_source.csv` 分别逐字节一致。该验证未执行 native 求场或 Fly。历史
`family_mother_sample_v1_n100` profile 保持不变，供其既有运行继续引用。

### 524Da 多极杆→IP共同工况

为重新生成与IP明确524Da/+1工况一致的真实上游源，登记独立runtime
`through_exit_no_acceleration_524da_n100`。它复用上述贯通机械design，源权威是
[planar_524da_2ev_n100.json](../config/sources/planar_524da_2ev_n100.json)，由现有具名source registry引用。
runner冻结该spec后仅物化一次run-local canonical CSV／receipt；不把CSV加入仓库，不改100Da历史源，
也不借用独立IP出口代替真实上游传输。

唯一物种变化为100→524Da，电荷仍+1。RF仍为139.81792 V零到峰值／组、1.1 MHz，所有几何、DC、
2 eV、seed 2026072801、半径0.5 mm的z=−1.5 mm释放盘、5°filled-cone及均匀RF出生相位抽样保持。
同一采样序列的ID、位置、方向与出生时刻保持，速度乘`sqrt(100/524)=0.436852028330519`。
数值profile `n100_spatial_refined_524da_observation_window`仅把原80 µs观察窗改为
`80*sqrt(524/100)=183.12837027615356 µs`，保留相同轴向速度尺度下的相对观察裕量；
0.3 mm网格、TQual=10、每RF周期40步保持。这不是根据实飞结果调窗，也不能保证到达或数值收敛。

[独立功能预算](../config/qualification/through_exit_524da_functional_budget.json)的contract ID为
`octupole_through_exit_524da_n100_functional`，绑定新runtime/source/numerics，仅授权SIMION N100功能。
限额与原贯通N100一致：720 s、运行目录2 GiB、进程树工作集16 GiB、系统可用内存8 GiB、compact
最终25 MiB、零自动重试。没有因质量提高资源额度；实际不足须保留原结果并另行决定，不事后抬帽。

在仓库根使用现有公共项目facade启动单主臂：

```powershell
. ./common/multipole/project_transport_launcher_support.ps1
Invoke-MultipoleProjectFinite3dTransport -Solver simion -ProjectId rf_octupole_ion_optics `
  -RepoRoot (Get-Location).Path -RuntimeProfileId through_exit_no_acceleration_524da_n100 `
  -CaseSet primary_only
```

该路径生成新的run身份，机械出口仍须由原生轨迹真实包围82.1 mm端面，发布
`results/mechanical_exit_states__rf_on.csv`、完整母群census与canonical clock；随后由显式装配消费一次
局部→装配投影，保留原ID、质量／电荷、出生与到达绝对时刻。纯runtime／预算预审不采样；项目配置
回归在系统临时目录仅生成一次N100源，与原100Da源逐ID核对位置／方向／出生及速度尺度，结束即清理。

固定RF和几何时，理想八极伪势深度按`1/m`降为原来的`100/524`，见
[高阶多极杆理论](../../../docs/multipoles/higher_multipoles.md#1-一般-2n-极模型)。因此“同一明确物种”
不等于上游传输或IP捕获保证。真实运行
`20261023_084802__sim__simion__rf-octupole-ion-optics-through-exit-no-acceleration__resolved-l3`
已完成求场及10批N=100飞行，批次全部自然exit 0、总飞行调度94.255 s；100个原始ID全部实际穿过
82.1 mm机械外端面，非出口数0，完整manifest的52项输出核验通过。源SHA为
`513114052574AEFCBB0C4B81FB358C52E373978CFE97A16A8FEA732AA908A429`，resolved父身份保持。
该上游证据本身只关闭真实外出口功能；后续IP注入及MR交接结果由
[集成状态](../../../integrations/docs/INTEGRATION.md#真实多极杆ip状态交接)维护。
旧100Da→IP的74入HP／0捕获负结果保持有效，不能用新配置关闭，也不授予优化、数值或Formal资格。

## 当前结论

- 三个规范模式由同一机械base和typed operating-mode registry编译，只改变电气模式；当前N=100
  baseline均已完成COMSOL与SIMION真实运行，100/100且交接粒子身份一致。
- 无加速空间/时间敏感性已执行，但连续量仍为
  `INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`。
- 两个加速模式的SIMION空间档已执行；COMSOL空间档均触发预登记资源帽，保持
  `INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不事后抬帽。
- 家族工程六指标可用于下游推进，不授予数值收敛、求解器等价、Candidate或Formal。
- 平面冻结源与轴向体积快照的 N=1000 SIMION 比较已完成；Python 恢复分析没有重跑求解器。
  两臂均全传输，源模型改变出口空间与角分布；这是描述性对比，详见
  [源模型记录](history/20260911__source-model-comparison.md)，不构成统计或数值资格。
## 资格边界

| 对象 | 当前状态 |
|---|---|
| 三模式N=100功能 | PASS |
| 连续数值收敛/跨求解器等价 | INCONCLUSIVE |
| N=1000多极杆统计资格 | 未完成 |
| oaTOF连接 | 状态归 integration；不赋予本项目新资格 |
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

## oaTOF连接

本项目发布 canonical handoff，连接器、套筒、目标注入能量和脉冲前接受度由
[integration 当前状态](../../../integrations/docs/INTEGRATION.md)
维护。下游源宽或装配候选不自动改变本项目的机械 base、源模型和资格。

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
