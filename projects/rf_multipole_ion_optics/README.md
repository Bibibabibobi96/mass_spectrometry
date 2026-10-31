# RF多极杆离子光学

本项目统一维护多极杆设计模型、理论和运行机制，并保留[四极杆](variants/quadrupole/README.md)、
[六极杆](variants/hexapole/README.md)、[八极杆](variants/octupole/README.md)三个显式结构变体。
当前研究包括无碰撞RF传输、轴向加速和四极RF+DC质量过滤。碰撞、空间电荷等扩展物理尚无当前资格。
变体共享机制，分别声明科学输入与证据；项目合并不提升已有结果的资格。
项目门禁的unittest执行通过公共计时runner记录逐测试耗时并即时输出失败详情；测试范围仍由门禁目录选择。
SIMION 正常入口以 `-NativeFieldRunPath` 显式复用原 producer 的 fractional 场，
场、Fly 与分析依赖分别判断；公共检查点 API 及保留条件见[项目状态](docs/PROJECT.md#当前结论)。
finite、interface_readiness 与 mass_filter_reference 的三条 SIMION CLI，request／completion 和收尾恢复默认接入公共 PowerShell owner API，
项目只提供真实退出和 host release 事实；这三条 SIMION CLI 均可用 `-ResumeFinalization -RunId` 恢复收尾。
COMSOL 正常无碰撞入口支持 `-AnalyzeOnly -ParentManifestPath <原封存manifest> -EngineeringBudgetPath <分析自有预算>` 创建仅分析新run，
复用充分封存CSV且不启动COMSOL；显式增加`-ReextractFromModel`才只读冷重开已解MPH并提取，所需原映射及边界见[项目状态](docs/PROJECT.md#当前结论)。
两个 COMSOL solver 通过项目共用分窗 API 提取原解；保存、实际原生读取证据和范围见[项目状态](docs/PROJECT.md#当前结论)。

有限三维 COMSOL 的显式网格最小尺寸、完整源的精确出生分组及未知末态语义见[项目状态](docs/PROJECT.md#当前结论)。两正式原生消费者共享同一项目分组器，不做相位近似。

四极接口 COMSOL 可用 `-AnalyzeOnly -ParentManifestPath <原manifest> -LimitsPath <本次分析预算>` 创建后继分析run，复用已完成native阶段且不启动COMSOL；checkpoint父另须实际 `-StoppedReceiptPath`，科学与恢复范围见[项目状态](docs/PROJECT.md#接口原cli的后继分析)。

## 固定阅读顺序

1. 仓库根[README](../../README.md)与[执行规则](../../AGENTS.md)。
2. [项目状态](docs/PROJECT.md)：当前事实、各变体资格、限制和开放任务的唯一正文。
3. 选择下表中的变体入口；涉及物理解释时读[理论索引](docs/theory/index.md)。
4. 实现与运行查[多极杆实现说明](docs/IMPLEMENTATION.md)；按所用求解器查
   [COMSOL说明](docs/COMSOL.md)或[SIMION说明](docs/SIMION.md)，各workflow分别声明变体范围。
5. 仅在追溯旧结论、run或资格身份时读[历史索引](docs/history/README.md)。

## 设计变体

| 结构变体 | 主要研究范围 | 专属输入 | 当前资格 |
|---|---|---|---|
| [四极杆](variants/quadrupole/README.md) | RF传输、RF+DC质量过滤、接口就绪 | [配置](variants/quadrupole/config/) | [四极状态](docs/PROJECT.md#quad) |
| [六极杆](variants/hexapole/README.md) | 理想场、圆杆场筛选、有限三维传输 | [配置](variants/hexapole/config/) | [六极状态](docs/PROJECT.md#hex) |
| [八极杆](variants/octupole/README.md) | 有限三维传输、真实机械出口及来源模型比较 | [配置](variants/octupole/config/) | [八极状态](docs/PROJECT.md#oct) |

`structural_variant_id`选择四／六／八极结构；typed电气mode选择同一机械base上的电位方式。
装配提供者已有的`variant_id`表达外壳/API变体，不能与极数混用。可装配提供者默认裸杆；接地圆柱壳须显式声明，壳体与可选带孔端盖连续相接、共用0 V。
壳体只输入内半径、壁厚和两个轴向端面，每个端盖只输入孔径半径与厚度；端盖不开放独立电压。
独立孔板、透镜等光学部件由外部提供者拥有，装配间隙由配方显式声明，没有1 mm默认值。多实例由
[组装配方](../../integrations/README.md)表达，不复制项目或源码。

## 机器权威

[project.json](config/project.json)声明项目身份与结构变体；[设计注册表](config/design_profiles.json)、
[runtime注册表](config/runtime_profiles.json)、[粒子源注册表](config/particle_source_profiles.json)
分别绑定设计、完整运行与源。极数与物理结构映射归[家族合同](config/contracts/family_contract.json)，
由项目设计解析器校验；公共发现合同只登记变体身份与能力。精确参数和路径只由机器合同维护，完整路由见
[PROJECT的机器权威表](docs/PROJECT.md#机器权威)。

选择具名设计或runtime profile时必须显式带结构变体前缀，例如`octupole_no_acceleration_full_length`；不存在默认极数。
普通传输的runtime同时冻结设计、源、数值与预算；campaign只允许已登记的实验选择，不能成为自由覆盖参数的入口。
专用接口与质量过滤workflow按各自合同绑定输入，不与普通传输互相消费结果。

变量定义与编译机制共用，范围和值由具体设计绑定；长度统一含义而不强制同值，见[变量共享边界](docs/IMPLEMENTATION.md#变量与长度的共享边界)。

## 工作流入口

| 科学问题 | 入口 |
|---|---|
| 预登记campaign与输入解释 | [运行与输入合同](docs/IMPLEMENTATION.md#粒子源与runtime-profile) |
| 六／八极杆无加速设计的理想场、圆杆场筛选与传输 | [L1传输](analysis/run_transport.ps1)、[L2场筛选](analysis/run_round_rod_field_screen.ps1)、[L2传输](analysis/run_round_rod_transport.ps1)；显式选择对应无加速DesignProfileId，其他设计拒绝 |
| 三变体有限三维无碰撞传输 | [COMSOL](workflows/no_collision_transport/run_comsol.ps1)、[SIMION](workflows/no_collision_transport/run_simion.ps1) |
| 四极接口就绪 | [COMSOL](workflows/interface_readiness/run_comsol.ps1)、[SIMION](workflows/interface_readiness/run_simion.ps1) |
| 四极RF+DC质量过滤 | [COMSOL](workflows/mass_filter_reference/run_comsol.ps1)、[SIMION](workflows/mass_filter_reference/run_simion.ps1)、[响应比较](workflows/mass_filter_reference/compare_responses.ps1) |
| 同求解器数值研究 | [比较入口](workflows/same_solver_convergence/run_comparison.ps1) |
| 已记录四极轨迹的RF相位与横向差异 | [轨迹诊断](analysis/plot_transport_phase_diagnostics.py)；从仓库根用下方唯一模块入口，证据边界见[项目状态](docs/PROJECT.md#已记录轨迹相位诊断) |
| 跨组件装配、外部光学与整机状态 | [统一集成入口](../../integrations/README.md) |
| 项目软件验证 | [公共Owner范围](../../common/verify.ps1)，`-Scope Owner -Owner rf_multipole_ion_optics` |

上述三个 SIMION CLI 均可通过 `-ContinuationPredecessorManifestPath` 显式指定同 workflow 终态前驱，
以新的 `-RunId` 复用完整批次；科学输入和原分区必须匹配，旧 run 缺少所需证据时不会被当作完整批次。
恢复、分析资源及保留边界见[SIMION活动入口](docs/SIMION.md#活动入口)。

```powershell
python -m projects.rf_multipole_ion_optics.analysis.plot_transport_phase_diagnostics --run-dir <run> --comsol-trajectory <comsol.csv> --simion-trajectory <simion.csv> --output-label <label>
```

内部物理handoff不自动等于机械外出口；冻结旧几何运行不能继承为当前裸杆或新壳体的验证。
配置编译、纯回归、真实求解、GUI/CAD和Formal资格分别判断，边界见PROJECT。
L1按[统一测试目录](../../common/README.md#门禁编排)给项目门禁传入`ChangedTestModules`，
使四极`Core`同时运行本次改动的测试；`Static`运行所选变体的完整回归，Freshness前置保持。
L1的fixture／未知目录回退和`-FullScope`由统一目录发现并补充模块；独立`Static`不自动推断新目录归属。

## 目录与产物

根`config/`维护注册表，`config/modes/`集中保存带变体前缀的科学运行模式，变体目录不保存模式副本；
`variants/<id>/config/`保存专属机械与其他科学输入；
`workflows/`按科学问题组织；`core/`拥有物理模型，`runtime/`编排运行，`analysis/`分析结果，
`comsol/`与`simion/`投影求解器，`tests/`按领域与变体保留回归边界。
理论、软件说明和当前状态放在`docs/`，不为每个变体复制一套PROJECT或通用理论。

新运行的owner为`rf_multipole_ion_optics`，产物进入工作区
`artifacts/projects/rf_multipole_ion_optics/`。旧run、manifest、源和资格保留原owner与字节身份，
由[历史索引](docs/history/README.md)定位；旧结果不会因目录合并变成新项目已通过的证据。
