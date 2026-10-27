# RF多极杆离子光学项目状态

本文件是本项目当前事实、结构变体资格、有效结论和开放任务的唯一正文。运行方法见
[实现说明](IMPLEMENTATION.md)，理论与物理约定见[理论索引](theory/index.md)，
跨器件结果由[集成状态](../../../integrations/docs/INTEGRATION.md)维护。
本文汇合原四、六、八极杆项目仍有效的结论；身份迁移和代码合并本身不产生新的物理资格。

## 当前结论

| 结构变体 | 已有功能证据 | 保持的限制 |
|---|---|---|
| [四极杆](#quad) | 三种typed电气模式COMSOL/SIMION N=100功能传输；质量过滤理论与有限几何响应 | 连续数值等价未闭合；历史严格接口相空间比较FAIL；质量分辨能力未资格 |
| [六极杆](#hex) | 三种typed电气模式COMSOL/SIMION N=100功能传输 | 连续数值资格延期且未豁免；RF微小排序不稳定，保留原P0基线 |
| [八极杆](#oct) | 三模式N=100功能传输；单端贯通模型100 Da和524 Da的SIMION真实机械出口功能 | 出口贯通不授予边缘场、数值或下游捕获资格；双端贯通仍须按独立证据范围判断 |

## 资格边界

共同三模式baseline只闭合功能分类。四极与八极原N=100运行两求解器均100/100且handoff身份一致；
六极原记录也已闭合功能传输。连续相空间的空间／时间敏感性与跨求解器比较保持
`INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`；工程六指标PASS只允许声明范围内的下游推进。
四极与八极两种加速模式的SIMION相邻空间档已执行，COMSOL空间档触发原预登记资源帽，保持
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不事后抬帽或改写历史终态。

- 正式统计binding须在运行前冻结bootstrap、接受尺度、effect resolution与预算；缺失这些设置的旧run
  保持`POSTHOC_DESCRIPTIVE`，不能通过补写配置升级资格。
- 项目descriptor的`candidate`生命周期及execution profile中的可申请证据级别，不等于某变体或功能已验收。
  机械、GUI/CAD与本项目Formal尚未闭合；质量过滤、接口、三模式和组装结果不能互相代替。
- 当前传输base未启用碰撞、空间电荷或磁场，也未建立制造支撑、公差与机械装配资格。
  碰撞理论已收录，但不代表碰撞运行能力已建立。
- 配置编译和纯回归只证明输入、投影及机制行为；没有真实求解、数值矩阵或GUI/CAD证据时不得宣称对应层级通过。

## 当前机械与模式

四、六、八极杆分别为径向阶数`n=2/3/4`的结构变体。精确机械、RF/DC、源和数值只认下表机器合同。
当前圆柱base的共同三种typed电气模式是`no_acceleration_full_length`、
`segmented_rod_axial_acceleration`和`exit_aperture_plate_acceleration`；同一base内模式只改变杆段与
出口孔板电位，不隐式改变几何、源或数值。电气模式名不含结构变体前缀；具名设计、runtime、数值和变体专属源profile使用
`quadrupole_`、`hexapole_`或`octupole_`前缀避免歧义。完全相同的家族与论文母群源由三变体共用，
保留不带变体前缀的源ID，具体绑定以粒子源注册表为准。

`structural_variant_id`表达极数结构，装配的`variant_id`保留外壳/API选择语义。封闭外端盖、带孔
接口板、释放面、handoff和机械出口不是同一对象；术语只在[实现说明](IMPLEMENTATION.md#统一术语)
定义。当前内部handoff传输不能证明穿过整个器件外端盖。

## 机器权威

| 职责 | 入口 |
|---|---|
| 身份、结构变体与发现能力 | [project.json](../config/project.json) |
| 变体极数、电极数与物理设计校验 | [家族合同](../config/contracts/family_contract.json)、[项目设计Schema](../config/contracts/design_profiles.schema.json)、[设计解析器](../runtime/design_profile.py) |
| 具名设计与typed电气模式 | [design_profiles.json](../config/design_profiles.json)、[operating_modes.json](../config/operating_modes.json) |
| 完整runtime与粒子源绑定 | [runtime_profiles.json](../config/runtime_profiles.json)、[particle_source_profiles.json](../config/particle_source_profiles.json) |
| 三变体传输数值注册表 | [COMSOL](../config/comsol_solver_numerics.json)、[SIMION](../config/simion_solver_numerics.json) |
| 四极机械、变量、源及专用workflow合同 | [quadrupole/config](../variants/quadrupole/config/) |
| 六极机械、变量及工程合同 | [hexapole/config](../variants/hexapole/config/) |
| 八极机械、贯通请求、来源模型及工程合同 | [octupole/config](../variants/octupole/config/) |
| 可执行入口与绑定要求 | [execution_profiles.json](../config/execution_profiles.json) |
| 旧资格、原身份与冻结记录 | [历史索引](history/README.md) |

活动runtime编译完整输入后执行；不能用命令行自由覆盖几何、RF/DC、源或已绑定数值语义。
专用workflow的允许输入与探索数值范围见软件说明及其机器合同。模型参数、阈值和正式证据都不从本文推导。
旧资格JSON保留原owner、profile名、SHA和run；它们不是可复制改名后执行的新资格合同。
新的运行合同若引用旧源数据，必须显式验证该来源身份，不能给历史数据补一个新owner。
家族合同两处`consumers`中的旧ID用于匹配历史owner；[家族门禁](../analysis/verify_family_foundation.py)
保留`recorded_project_id`核查原身份，同时以当前项目和结构变体验证活动设计。这些旧ID不参与公共能力发现，
也不允许新run回写到旧owner。

<a id="quad"></a>

## 四极杆

四极杆保留无碰撞传输、接口就绪、质量过滤和同求解器数值研究等科学workflow。
`quadrupole_official_transport`矩形参考服务旧接口／质量过滤的相应作用域，不是圆柱三模式实验端口；
`Mode`或粒子数不能切换科学声明。接口历史严格相空间比较FAIL，当前机械base仍待新资格。
RF+DC已有理论和有限几何功能响应，网格、跨求解器一致性及质量分辨能力未闭合。

旧非typed设计`exit_aperture_plate_acceleration_reference`在迁移前基线`3647bcae`即因
`axial-drive potential profile does not accelerate selected charge sign`被编译器拒绝；新具名对应项
`quadrupole_exit_aperture_plate_acceleration_reference`保留此拒绝，不改物理符号来制造迁移PASS。
它与已完成N=100功能的typed `quadrupole_exit_aperture_plate_acceleration`不同。

质量过滤L0参考实现仍在[专属workflow](../workflows/mass_filter_reference/theory.py)，其源由
[official_particle_source.json](../variants/quadrupole/config/official_particle_source.json)声明，确定性采样由
[公共ion_release](../../../common/ion_release/README.md)提供。旧150 mm碰撞脚本不是活动合同。
旧矩形PA导出／比较三脚本已退役，不恢复硬编码0.2 mm基线的GEM文本替换链。

N=1000 COMSOL bridge曾在release构造阶段资源中断，向量化release候选未证明等价；两者都不是生产路径。
相关数值、释放诊断及旧接口证据见
[四极历史](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md)。
当前适用操作保留在[COMSOL](COMSOL.md)与[SIMION](SIMION.md)说明中。
既有四极→oaTOF功能链不授予连续相空间、分辨率、机械或整机Formal资格。

<a id="hex"></a>

## 六极杆

六极杆保留理想场、圆杆场筛选与有限三维传输的模型层级。三模式功能证据不改变
`DEFERRED_NOT_WAIVED`／`INCONCLUSIVE`的连续量资格。相位匹配的RF幅值—频率筛选及N=1000复核
显示微小排序不稳定，继续保留P0 RF基线，不据此优选参数或扩展扫描；证据见
[RF复核](history/retired_projects/rf_hexapole_ion_optics/docs/history/20260803__hex-rf-drive-phase-matched-h15-n1000.md)。
源能量与加速方式的比较保持描述性，数值只见
[源能量记录](history/retired_projects/rf_hexapole_ion_optics/docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md)。

oaTOF的零长度直连、接地圆套筒与带孔法兰由集成合同显式选择；屏蔽电位不作为隐式变量开放。
旧逐臂profile、预登记和专用诊断测试的结论从
[退役campaign](history/retired_projects/rf_hexapole_ion_optics/docs/history/20260802__retired-comsol-qualification-campaigns.md)
追溯，新的研究只使用当前注册的runtime与窄变量campaign，不恢复一次性诊断树。

<a id="oct"></a>

## 八极杆

### 真实机械出口

旧闭壳模型的内部handoff在`z=80.6 mm`，近端数值标记在`81.1 mm`，外端盖`81.6..82.1 mm`实心。
旧100/100只证明内部传输；不将它重述为穿过最外端盖。
[through_exit.json](../variants/octupole/config/requests/through_exit.json)显式选择单端贯通外壳；
`octupole_through_exit_no_acceleration`设计保持真实物理外端面`82.1 mm`，数值域延至`82.7 mm`。
延长数值域不是延长金属，也不建立第二份孔径。

旧owner下的SIMION运行`20261022_210633__sim__simion__octupole-through-exit-n100`已完成新求场与N=100飞行，
100个原始ID真实穿过外端面，64项manifest输出校验通过。出口由步长前后真实状态包围并插值，完整母群、
位置／速度／绝对时间与canonical clock均校验。首次尝试的旧电极11绑定错误已在该重跑前修复；
不补假几何，也不把出口后的停止回退状态误记为出口前损失。
这些状态可用于显式state handoff功能验证，不授予边缘场截断、数值收敛、COMSOL、GUI/CAD或Formal资格。

### 双端贯通与源身份

`octupole_through_entrance_exit_no_acceleration`复用同一贯通request和变量包络，通过显式
`enclosure_model`选择双端贯通外壳。原单端设计不变；两端孔径、法向、壁厚与RF/DC仍从同一request编译。
原项目证据覆盖profile→resolved→真实双端口与GEM的纯回归及非法选择拒绝；这项提供者证据本身未包含
新的原生求场、飞行或多实例验收。正在集成的装配工作以集成状态为准，不提前继承其结论。

[family_complete_mother_n100.json](../variants/octupole/config/sources/family_complete_mother_n100.json)
声明N=100即完整实验母群；新源profile为`octupole_family_complete_mother_n100`。它经公共release物化，
已与上述旧100 Da运行的原CSV逐字节重建一致，相关纯装配准备的局部及投影源也保持字节一致。
此重建不是一次新的native求解。旧嵌套家族源profile继续表达其原有前缀关系，不能与完整N=100母群混用。

### 524 Da工况与来源模型比较

`octupole_through_exit_no_acceleration_524da_n100`绑定独立
[524 Da源](../variants/octupole/config/sources/planar_524da_2ev_n100.json)和具名数值profile，复用单端贯通设计。
旧100 Da源保留；相同位置、方向、ID和出生抽样下，质量改为524 Da、仍为+1及2 eV，速度按`sqrt(100/524)`
缩放。RF与机械不随质量调优；观察窗按相同轴向速度尺度扩展，不保证传输或收敛。
理想八极伪势深度在固定RF与几何下按`1/m`变化，因此同一明确物种不等于下游捕获保证。

旧owner的运行`20261023_084802__sim__simion__rf-octupole-ion-optics-through-exit-no-acceleration__resolved-l3`
完成新求场与N=100飞行，100个原始ID全部真实越过`82.1 mm`外端面、非出口数0，52项manifest输出校验通过。
该结果只关闭上游真实出口功能。旧100 Da→IP的74入HP／0捕获负结果保留；524 Da注入和MR交接由
[集成状态](../../../integrations/docs/INTEGRATION.md)维护，不以新上游配置关闭旧负结果。

平面冻结源与轴向体积快照的N=1000 SIMION两臂均全传输，出口位置与角分布不同；这是描述性来源模型比较，
详见[源模型记录](history/retired_projects/rf_octupole_ion_optics/docs/history/20260911__source-model-comparison.md)。
后续更改该比较仍须固定设计、下游端口、数值及完整粒子母队列，仅改变receipt绑定的source model。

## 部件与组装边界

本项目发布原生机械、端口、驱动及canonical handoff；连接器、位姿、公共电位、时钟和下游场域由
[组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)与集成配方表达，不反写提供者base。
IP自身提供的裸八杆导引与本项目八极杆保持不同来源，不能只因杆数相同而互换模型、驱动或粒子母群。

提供者迁移的关闭条件是冻结输入下几何、驱动、端口、完整源／handoff与绝对时钟对照成立，
原消费者结论保持，新增接收端口和真实物理链另行验收。组装纯回归与重启恢复不授予器件数值或Formal资格。
跨器件执行与当前任务进度只查[集成状态](../../../integrations/docs/INTEGRATION.md)。

## 开放任务

1. 新出口相空间研究按[通用方法](theory/exit_phase_space_control.md)先固定真实下游接受尺度、唯一变量、
   损失约束、共同幸存者与相邻数值档，再选择具名campaign；本页不预选加速模式或最优参数。
2. 连续量、逐粒子等价与统计资格须先冻结误差预算和bootstrap设置；资源受限模式使用有依据的新预算
   或替代离散策略，不改旧run的预算或资格。
3. RF-only、RF+DC、轴向加速与各结构变体分别建立相称Candidate证据；机械、GUI/CAD与装配闭环后才讨论Formal。
4. 碰撞冷却须由当前机械base建立独立物理合同与workflow；气压、分子流等新增物理按需求增加，本文不预建能力。
5. 下游或整机性能研究由集成任务明确目标、指标和授权，功能贯通不自动扩展为优化或N=1000统计工作。

## 产物与历史

新运行的owner是`rf_multipole_ion_optics`，只写`artifacts/projects/rf_multipole_ion_optics/`。
旧三个项目的run、manifest和冻结资格继续使用原身份与原artifact解析位置，不提供猜测旧路径的fallback。
[历史索引](history/README.md)登记原owner、原路径、固定Git版本及迁移映射；冻结内容不改字节。
普通README／PROJECT编辑由Git保留版本，不因本次合并再复制一套全文快照或逐会话状态历史。
