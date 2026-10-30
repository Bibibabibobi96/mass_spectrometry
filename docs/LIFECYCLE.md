# 源码、运行与文档生命周期

返回[仓库入口](../README.md)。本页定义产物、脚本、保留和历史归档。删除授权只由[AGENTS](../AGENTS.md)规定；知识归属见[仓库架构](REPOSITORY_ARCHITECTURE.md)。

## 产物与运行生命周期

### 工作区顶层卫生

源码默认位于`simulation_repo/`，生成产物按所属owner放入相邻`artifacts/projects/`或`artifacts/common/`。
工具缓存与本机软件、Agent或IDE状态可留在工作区；兄弟目录、根目录和`.tools`的名称不作固定白名单。
额外本地目录和根日志本身不阻断研发，也不因此自动成为可消费、可删除或可信资产。整理重复副本时仍须
确认归属与实际引用，遵循既有删除授权与生命周期；运行与产物入口继续执行其实际路径、容量和输入保护。

### Git / artifacts 边界

Git 只管理可复现、可审阅的轻量源码与文档。MPH、PA/PA#、IOB、SolidWorks 文件、运行日志、
粒子表和运行结果图放在仓库同级 `artifacts/projects/<project>/`，不进入 Git。用于解释正文的示意图与
轻量再生成脚本可放在所属文档的`figures/`并进入Git，标明假设、来源和复现方法；不能把运行结果
改名为示意图以绕过产物合同。正式运行使用所属owner的scratch；`common/verify_repository_hygiene.ps1`只负责生成大资产误入Git的边界，
不检查未消费的本地目录与日志。

### 外部参考资料

外部资料统一从[`docs/references/README.md`](references/README.md)发现。学术书籍与论文的本地原始PDF
放在`docs/references/literature/`，供应商离线手册放在`docs/references/software/`；两类均只将书目、
来源、版次、定位和必要的文件身份记录纳入Git，PDF由`.gitignore`排除。
这是外部知识来源，不是run输出，不放入某个项目的运行证据或Formal资产。干净checkout没有这些PDF，
阅读入口必须说明缺失时的合法获取方式，不能假定每台机器都有原用户路径。

从外部引入资料时保留用户原件，核验副本字节与SHA-256；仓库内迁移核对原路径、新路径、字节数、
SHA-256与索引引用后，按已确认保留范围处置重复副本。不以文件名推断内容，不覆盖不同版本，也不将全文或
大段摘录复制进当前说明。大型资料先读元数据、目录或书签，再按问题抽取相关页；页码明确区分PDF页与
书内页。引用只支持原文实际覆盖的结论，不自动成为仓库能力、参数或验收合同。

### artifacts 目录职责

唯一结构：

```text
artifacts/projects/<project>/
├─ 00_README.txt
├─ cache/                       # 可删除的、内容寻址且经机器校验的性能缓存
├─ formal/
│  ├─ comsol/
│  ├─ simion/
│  ├─ cad/
│  ├─ results/
│  └─ asset_manifest.json
├─ runs/<run_id>/
│  ├─ comsol/
│  ├─ simion/
│  ├─ results/
│  ├─ logs/
│  ├─ run_config.json
│  ├─ summary.json
│  └─ run_manifest.json
├─ archive/<archive_id>/
│  └─ archive_manifest.json
└─ scratch/<task_id>/
```

`formal`只在项目存在通过当前门禁的正式资产时创建；不得用空目录或未验收模型制造“已有正式模型”
的错觉。运行的模型、结果和日志统一放在同一个`runs/<run_id>/`中；求解器无关分析、收敛比较和跨run
比较同样属于run，不得另建顶层`analysis/`或`comparisons/`。项目根也不再建立`models/`、`cad/`、
`results/`或`logs/`，不按软件或工作类型拆第二棵运行树。`00_README.txt`只提供面向资源管理器的导航，
不得成为项目状态或规则权威。各目录的状态、保留与清理条件由本节末尾统一定义。脚本必须通过项目
路径解析器定位这里，禁止硬编码用户名或重建旧 `artifacts/components/`。
`cache/`不是运行证据或第二份项目状态，只允许机器校验器显式注册的内容寻址性能缓存；缓存命中必须
复核配置、代码、几何/网格、求解器版本与关键选项身份，以及manifest中的完整文件字节数和SHA-256。
损坏、不完整或旧schema条目只能视为MISS并重建，不能作为run输入。当前注册角色为：

| cache根 | 注册角色 |
|---|---|
| `artifacts/common/simion/pa_family_cache/<cache-key>/generations/<generation-sha256>/` | `simion_pa_family_cache`；公共可重建PA性能缓存，键与当前代均由 manifest 和完整 payload 校验 |
| `artifacts/common/capacity_protection_leases/<lease-id>.json` | 公共容量TTL保护租约；只临时钉住精确cache key或artifact-root相对路径，过期自动失效，损坏则门禁失败关闭 |
| `artifacts/common/capacity_disposal_receipts/*.json` | 容量或卫生处置收据；保存精确路径、身份、原因和结果，仅允许直接JSON记录，不存放求解器载荷；保留在被清理树之外 |
| `cache/simion_pa_basis/<cache-key>/generations/<generation-sha256>/` | `simion_pa_family_cache`（multipole PA-basis 适配器） |
| `cache/<registered-role>/<SHA-256>/` | 集成PA及已验证脉冲收据；目录名与允许角色的唯一对应表为[`verify_artifact_layout.py`](../common/contracts/verify_artifact_layout.py)的`INTEGRATION_CACHE_ROLES`，新增角色同步机器校验及测试，不在文档抄写第二份名单 |

不得在`cache/`保存唯一输入、canonical结果、正式资产或未登记的任意文件。所有`formal/` PA无条件按
正式资产合同保留，禁止作为cache清理；当前实验仍引用的cache PA和无法由冻结输入重建的唯一来源同样
保留。旧schema缓存只能用于只读追溯，不能被运行器直接接受为新输入；需要时按当前schema重建。
历史保留盘点见[审计索引](AUDITS.md)，具体保留对象以运行与处置记录为准，不在规范里复制数量。
SIMION IOB 可能嵌入 PA 的绝对路径，移动工作区后必须重新打开/保存或重建 IOB，并验证该合同声明的全部 PA
实例；文件存在不等于迁移成功。SolidWorks 装配移动后必须检查外部引用。

来源run三件套只回答“输入是什么、运行结论是什么、证据是否完整”；它们不代表已经转正。
`formal/results/`保存从成功run选出的当前正式结果，Git内项目验证合同说明这些结果证明了什么，
`formal/asset_manifest.json`则统一冻结来源run、验证合同以及模型、SIMION、CAD和结果清单的身份。
三者必须分开并用相对路径和SHA-256关联，不复制大结果制造第二份权威数据。

### 统一组装产物归属

本节对应[统一组装目标](COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)，定义统一入口的产物归属。
已切换的工作流按下表发布新run；具体实施和验证范围见[集成状态](../integrations/docs/INTEGRATION.md)。
尚未切换的路径仍须完成运行器、身份、路径解析、容量／保留门禁和测试后再切换，
不能仅凭文档改变既有或在途运行的路径与身份。

| 对象 | 归属与发布边界 |
|---|---|
| 配方、实验作者输入、实现和规范 | Git内固定组装目录及既有公共／项目权威；不保存生成模型或结果 |
| 组件独立构建与验证 | 原`artifacts/projects/<provider_project_id>/runs/<run_id>/`，由提供者负责发布 |
| 目标跨项目组装、联合飞行与联合分析 | `artifacts/projects/instrument_assembly/runs/<run_id>/`，以`integration_id=instrument_assembly`归属；不为每份配方新增artifact根 |
| 冻结装配、来源与执行计划 | 该组装run的`inputs/`及三件套；绑定recipe、workflow、实验行、组件实例、接口与实际依赖身份 |
| PA、MPH、STEP、IOB、粒子表、图与日志 | 同一owner的run内部既有角色目录；保留类别仍由本页run合同决定，不能因组装用途扩大保留 |
| 共享PA与其他已登记缓存 | 既有公共owner及内容身份，不因源码迁移复制、重命名或接管缓存 |
| 既有run、Formal、GUI交付与历史证据 | 保持原owner、路径、manifest和资格，新的组装run通过已核验引用消费 |

路径沿用`artifacts/projects/`并不把integration变成硬件project。机器身份须区分集成owner、组件
project和组件instance；配方ID用于选择，冻结内容身份用于判定实际装配，不能仅凭配方名复用结果。
父组装run引用组件子run的manifest，不把子run复制成另一份发布权威；重型资产仍只有一个生命周期owner。

多配方正式发布须先实现能区分配方、workflow和实际装配身份的asset manifest及路径校验，按下文多变体
Formal规则验收；不得用固定同名模型覆盖另一配方，或把统一目录本身当成Formal发布。组件与仪器原有
Formal继续归原项目，联合发布不自动授予或替换它们的资格。当前未实现该发布合同，不创建空formal。

迁移仅对完成切换后的新run生效。旧运行不改写`integration_id`、`project_id`、run ID或冻结SHA；
来源路径映射用于追溯，不作为运行器搜索旧根的fallback。停止、恢复、保留和删除继续使用本页既有机制，
不得因目标目录确定而清理在途输入、消费者需要的PA或GUI资产。

### artifact标识与文件命名

目录标识采用“时间优先、受控词汇、人工可读”的统一合同：

|对象|格式|用途|
|---|---|---|
|`run_id`|`YYYYMMDD_HHMMSS__activity__scope__subject[__detail][__rNN]`|可引用的模拟、测试、分析、构建、基准或门禁运行|
|`archive_id`|`YYYYMMDD_HHMMSS__reason__scope__subject[__detail]`|冻结、取代、失败证据、旧资产或迁移快照|
|`task_id`|`YYYYMMDD_HHMMSS__scope__subject`|scratch中的短期任务；不得被正式文档引用|
|history快照|`YYYYMMDD__milestone-topic.md`|可命名里程碑；同日多份时才增加`HHMMSS`|

目录时间使用上海本地时间以便资源管理器排序，manifest同时保存带时区时间和UTC时间。`activity`
限定为`sim/test/analysis/build/benchmark/gate/migration`；`scope`限定为
`comsol/simion/cross/cad/python/repo`；`reason`限定为
`superseded/legacy/milestone/failed-evidence/migration-snapshot`。其余词段使用小写ASCII kebab-case，
完整标识不超过96字符，重试只在末尾增加`__r02`等序号。实现和自动检查的唯一来源为
`common/contracts/artifact_naming.py`。

清晰命名主要由容器承担，容器内部采用固定角色名，避免路径过长和脚本漂移：

- 项目ID使用稳定snake_case，正式主二进制采用`<project_id>__<role>.<ext>`，例如
  `formal/comsol/<project_id>__model.mph`和`formal/cad/<project_id>__assembly.SLDASM`。这样文件脱离父目录后仍可
  识别，但不把日期或`v2/final/new`写入文件名；版本、来源run和哈希写入`asset_manifest.json`。
  SIMION多文件包继续使用`accelerator.pa#`、`reflectron.pa#`等物理部件名，不机械添加项目名前缀。
- `run_config.json`、`summary.json`、`run_manifest.json`、`stdout.log`、`particle_state.csv`等角色文件
  保持短而固定；图表使用`subject__view.png`等语义名，例如`mass-spectrum__peak-overlay.png`。
- 候选资产不另造candidate ID，直接归属于生成它的`run_id`；晋升时复制或构建到稳定formal路径并
  记录来源。源码函数使用既有语言规范的`verb_object`，禁止用`final/new/v2/retry`表达生命周期。
- archive容器必须可读，但其中受哈希、嵌入引用或第三方软件约束的原始文件通常保留原名；其原始
  路径、冻结原因、来源run和替代关系写入`archive_manifest.json`。

### run_config / summary / manifest

每次可被引用的运行必须形成三类机器记录：

|记录|创建时机|唯一职责|
|---|---|---|
|`run_config.json`|运行前|冻结项目、模式、输入路径、唯一变量、种子、软件环境和是否具备正式门禁资格|
|`summary.json`或具名`*_summary.json`|运行结束或中断时|记录样本数、关键指标、终止阶段、判据结果和简短错误分类，不复制原始长日志|
|`run_manifest.json`|所有输出落盘后|冻结run config、输入和输出的存在性、字节数、SHA-256、运行状态及正式资格|

原始报告、CSV、模型、图像和崩溃日志是manifest列出的输出，不替代summary。运行器用
`common/contracts/write_run_manifest.py`在producer停写后计算全部输入/输出身份、拒绝缺失文件并检查保留合同，
原子写入后读回小型manifest并与计算结果完整比对；公共发布器随后发布候选，不在同一闭合边界再次全文读取载荷。
后续独立消费通过`verify_run_manifest.py`按实际字节重新验证；未完成适用发布/消费核验的目录不能被正式文档引用。
这里的“全部记录”是run发布门禁，不能用消费投影代替。下游只读取历史run的严格子集时，可按
[公共合同](../common/contracts/README.md#运行身份与生命周期)使用具名、路径绑定的消费投影；该投影只证明
被读取记录及上游身份，不恢复或宣称未消费记录有效，并须由下游run config冻结其范围。

### run产物保留合同

新建或实质修改的run入口必须使用
[`common/contracts/artifact_retention.json`](../common/contracts/artifact_retention.json)和run manifest
schema v2冻结保留类别；默认类别是`compact`。保留类别在`run_config.json`运行前确定，manifest逐项记录
输出的`retention_role`，不得在看见结果或磁盘占用后改类。现有schema v1历史run保持可读、可复核，
但不得作为新入口绕过保留合同的模板。

| 保留类别 | 适用范围 | 终态必须/允许保留 |
|---|---|---|
|`compact`|功能回归、常规参数运行、失败关闭的默认类别|三件套、冻结输入、代码身份、summary/metrics、canonical粒子终态/事件、必要日志和轻量图；禁止MPH、SIMION PA解阵列和完整轨迹|
|`qualification`|预注册的最终收敛参考点、跨求解器资格参考资产或正式证据源run|允许完整轨迹及求解器原生重型文件；必须在运行前写明保留理由|
|`solver_review`|需要GUI重开、节点/网格审查或供应商缺陷复现的专项诊断|允许完整轨迹及求解器原生重型文件；必须在运行前写明保留理由，不自动获得资格|

`compact`的终态只保留为该次结论、复核或下游受管 handoff 所必需的文件；可由冻结输入重算的筛选中间量、
缓存工作副本、临时曲线和调试输出必须在写终态manifest前清理，不能因文件较小、运行中断或已经写入
初始manifest而留下。非`compact`类别才可额外保留重型或可重建输出，并须在运行合同中事先说明理由。

canonical粒子状态、事件、metrics和summary属于必需证据，不因超过大文件阈值改变保留角色。
已登记的IOB结构模板在执行快照中属于必需运行资源，不是本次求解产生的PA；compact保留冻结输入，
实际求解场仍按其原生载荷角色处置，不能凭位于inputs目录扩大保留范围。
`finite_3d_transport.mph`、`.pa#/.paN/.pa_/.pa-surf`、完整`trajectory_samples*`（含压缩文件）以及达到策略阈值的其他可选大文件
属于可选重型或可重建临时输出，不是每个成功run的必需证据。`compact`运行可在求解期间生成它们，但须在
终态manifest前由公共retention执行器移除，并用`retention_actions.json`记录精确相对路径、类型角色、字节数
和处置原因；删除时复核路径范围、常规文件类型和大小，不为待丢弃的未封存临时载荷新增全文哈希。
既有封存输入／结果的内容身份仍由来源manifest保留。执行器只接受无manifest或checkpoint的本次`runs/<run_id>`，先写pending收据再删除，完成后标记complete；
既有收据不得覆盖，部分失败不能当成完成。最终interrupted须走专用reconcile，只处理未被manifest记录的可弃载荷并复核容量保护。
writer和verifier会扫描未列出的
重型文件并失败关闭，因此不能靠遗漏`--output`绕过。资格或GUI复核若确实需要重型文件，必须显式选择
非compact类别；从compact run晋升时应重跑冻结输入，不得事后补造缺失资产。
普通及中间网格/时间步收敛点仍使用`compact`：先从完整轨迹生成冻结metrics，再保留canonical states、
metrics、numerics、summary和manifest用于成对比较；只有少数最终参考点或确需GUI/网格复核的点升级保留类。

### success / failed / interrupted / superseded

|状态|判定条件|允许的结论|
|---|---|---|
|`success`|运行完成预定流程并通过该入口声明的运行判据|可引用本次结果；只有额外正式门禁通过时才可转正|
|`failed`|运行正常返回失败判据、任务报错、启动失败或原生崩溃|可引用为负结果；summary必须写失败阶段及是否有资格进入物理/数值矩阵|
|`interrupted`|被用户、Agent、掉电、超时外部终止或编排中断，未得到预定终态|只证明运行未完成，不得写成求解器或物理FAIL|
|`superseded`|记录曾完整有效，但已被明确的新运行或新契约取代|保留追溯关系，不再作为当前结论来源|

状态描述运行记录是否完整，不等于候选是否应转正。失败启动和Study Compute失败都可使用`failed`，
但必须由summary中的`failure_stage`、`threshold_result_eligible`等项目字段区分适用范围。

### 故障调查状态转换

知识的权威位置只由[新知识写入表](REPOSITORY_ARCHITECTURE.md#新知识写入表)决定；本节只规定调查状态如何迁移。归档不按操作者、软件或
文件出现顺序决定。

故障调查采用固定状态转换：

```text
发现问题
→ PROJECT登记影响、优先级和当前绕行
→ 软件文档登记最小复现、受控矩阵、当前边界和证据路径
→ 每次尝试写独立run_config、结构化摘要和success/failed/interrupted manifest
→ 原始日志与崩溃转储立即移入该次artifacts运行目录
→ 达到里程碑或关闭时，把完整时间线冻结为history只读快照
→ 正式文档收缩为最终根因/绕行、验证范围和history索引
```

明确的负结果与失败运行也是证据，不得被后续成功覆盖；失败manifest与成功manifest使用相同输入/
输出哈希规则，只是状态不同。运行器必须在启动前确定运行目录，并捕获运行期间落到仓库根目录的
`hs_err_pid*.log`、MATLAB crash dump等工具日志，移动到该次运行目录后再写manifest。意外产生的
原始文件若无法唯一归属，先移入项目`scratch/<task_id>/`并在
当前任务结束前完成归属或报告，不得长期悬置。

### history 冻结条件

先按记录用途选择保留方式，不把每次对话、重试或文档编辑都转成新的历史文件。

| 内容 | 保留方式 |
|---|---|
| 当前能力、资格、限制与开放动作 | 所属PROJECT／INTEGRATION；更新当前答案 |
| 普通文字修订、排版、链接修复或重复段落收缩 | Git固定提交与原路径；无需额外复制全本TXT或源码 |
| 可命名科学里程碑、关键负结果、旧方案或必要迁移审计 | 所属`docs/history/`的冻结记录，说明输入身份、结论边界和原证据 |
| 每次运行的逐次事实、模型、结果图和日志 | artifacts的run config、summary和manifest，不复制成活动文档 |
| 未由Git或受管run保留的外部原始输入、唯一数据与必要复现载荷 | 具名冻结包及身份清单；不能用引用替代实际缺失的必要证据 |

`history`不是实时工作日志。达到科学里程碑、结论关闭或方案被取代时，优先引用已有完整记录；
只有新证据无法由已有记录清楚表达时才新增冻结正文。正文绑定当时的输入、运行与资格，不回写旧档案
中的“当前”“正式”或“下一步”。后续勘误或新证据在新记录说明替代关系，不改旧字节制造一致。

以下情况需要收缩当前视图，但不一律要求新增history：章节按日期堆积已完成尝试、三个以上仅供追溯的
run ID、不同入口重复同一状态正文，或日期化审计只剩追溯价值。普通编辑由Git保存；具有独立科学或迁移
意义的材料按上表归档。PROJECT保留有效结论、资格、限制和开放动作，软件说明保留可执行操作及独立验证，
完整时间线和旧数值矩阵只引用其原记录。不得为降低行数删除必要假设、负结果或尚未关闭的问题。

每个所有者维护一个可编辑历史索引。根索引为[`docs/AUDITS.md`](AUDITS.md)；项目与集成优先使用
`docs/history/README.md`，所属README只链接该索引。索引可按主题更新导航、来源提交、原owner与替代关系，
但不复制冻结正文或重新解释其资格。小型既有README内索引可在同一职责迁移时收敛，不能长期维护两份名单。
索引与冻结科学记录的生命周期不同；`history/README.md`不是冻结证据。

新冻结记录默认使用`YYYYMMDD__milestone-topic.md`。没有附加载荷时只保留Markdown；需要保存
非Git原始输入或不可替代数据时，可使用与Markdown同名的载荷目录，清单逐项记录原路径、用途、字节数和
SHA-256。可由Git固定提交完整恢复的普通文本不再额外复制全本。冻结包不包含`__pycache__`、`.pyc`或运行缓存；
科学输出按既有artifact保留合同管理，不能用文档包扩大重型载荷保留范围。

Git内冻结历史不在普通软件提交或完整软件回归中逐文件重查属性、载荷哈希和迁移来源。初次迁移、实际
历史修改按受影响记录或证据包核对；全档案认证通过显式`verify_documentation.ps1 -AuditHistory`请求。
`-ChangedPath`只核本次相关历史，活动导航、链接和锚点继续日常检查。工作区兄弟、根与`.tools`中的
未消费目录和本地日志不是生命周期拒绝条件；生成大资产误入Git、消费或删除范围、容量、writer与输入保护保持。

### 退役所有者与历史迁移

活动项目整合后，原项目身份仍是原run和科学记录的身份，不能回写成新项目或新变体。
新owner的历史索引必须给出旧owner、固定来源提交／原路径及新入口；旧活动项目目录不作为永久兼容实现。

- Git已经完整保留的旧Markdown或源码，可在索引中固定来源提交与原路径后移出活动工作树；
  先验证提交可解析、相关正文和必要依赖可恢复，并记录原始链接的解释基址。
- 仍需本地直接查阅的冻结科学记录可以移动，但须验证原字节、来源身份、相对引用与manifest消费者；
  保留必要原相对结构或在包外提供明确来源映射，不通过修改冻结正文让新路径看似兼容。
- 需要自包含复现的具名包可保留原相对层次，清单说明原owner、来源提交和每项载荷身份；
  这是有明确消费者的证据保留，不是复制整棵活动项目或重建第二份源码树。

迁移前后核对记录数量、内容哈希及全部活动入链；缺失的外部run载荷、软件环境或原始输入应明确列为复现限制，
不能因Markdown可读取而声称实验可复现。旧路径解析只用于追溯，不作为新运行器搜索历史根的fallback。
对在途运行、正式资产、GUI包、缓存或机器manifest的迁移仍须遵循对应artifact合同，不能仅凭文档整理授权移动。

新建历史中的配置与结果名称仍遵守[科学配置规范名称与结果身份](DEVELOPMENT_STANDARDS.md#科学配置规范名称与结果身份)。
旧记录的规范化映射写在可维护索引或新说明中，不回写原始证据。

### 保留与清理策略

保留策略面向可复现性：`formal`只保留当前门禁通过资产，候选及其结果留在来源`run_id`中，
`archive`保留被正式引用的旧资产和冻结快照，`runs`保留被文档引用或用于失败根因的运行，`scratch`
不作为引用来源。删除仍遵守`AGENTS.md`的删除授权规则；
“已进入history”“已被superseded”或“manifest已生成”本身均不授权删除原始证据。
run生成阶段的自动保留行为只按上文预注册的run产物保留合同执行；它不授权事后清理既有run。

`failed/interrupted/cancelled/aborted`只说明运行终态，不能单独成为整目录删除条件。容量规划必须先保护
失败根因、冻结输入和引用链，只按下节裁剪符合合同的可重建载荷；清理工具不得以状态过滤替代证据判断。

### 仓库外临时文件与清理闭环

清理范围包括已确认由本仓库生成的系统Temp、求解器临时工作目录和本机工具日志；不扩展到用户其他
项目、应用安装、许可证或配置。目录名前缀、文件年龄、Git忽略状态和低CPU占用都只能用于发现候选。
执行前核对内容与创建用途、活动进程及run引用；无法确认归属或含唯一输入的对象保留并报告原因。
不跟随目录链接递归清理，不因父目录可清理而删除其中新出现的文件。

任务结束时清理可弃工作副本、空壳目录和一次性实现，把需要保留的收据放入上述公共收据目录，避免
清理任务本身留下新的顶层杂物。清理报告分别列出文件逻辑大小、磁盘可用空间变化及未处置对象；
硬链接、稀疏文件和并行写入会使两种容量数字不同。受管容量水位线只针对artifacts树，另须检查所在卷
余量和已知外部临时副本；低于水位线不表示临时文件可无限积累，也不要求为了达到某个容量而删除证据。

### 工作区容量水位线

工作区`artifacts/`的受管目标上限和所在卷预计峰值后的最小空闲，其唯一配置来源是
[`artifact_capacity_policy.json`](../common/contracts/artifact_capacity_policy.json)。台账记录逻辑字节，
磁盘检查读取真实空闲量；二者含义不同。

容量台账只区分：必要轻量证据`light_evidence`、公共可复用重型资产`published_cache`、可重建载荷
`rebuildable_payload`。Formal、唯一来源和其他必须保留的对象以具名pin表达；正在使用或已经安排消费者的对象
以公共TTL租约保护。run状态、科学资格和容量类别分别记录，不用保留类别与软件验证范围的组合标签决定删除。

删除资格必须同时满足：对象明确可重建、写入已结束、无活动或待交接消费者、未pin、身份和处置范围明确。
维护直接处理使用结束的`rebuildable_payload`；对`published_cache`只能向台账登记的固定owner manager请求退休，
由manager在容量决策锁内先提交owner终态，再把sealed disposition登记为可重建载荷。删除器仅执行这份批准清单，
中断后按固定receipt续作，不重新扫描或重复哈希整个对象；`light_evidence`不自动删除。
历史文字引用不自动保护重型载荷，结构化消费者引用和租约才形成使用保护。仅过期、无进程或summary终态均不单独授权删除。

所有`writing`对象必须有负责人、恢复原因和复核日期。到期不会自动删除；影响当前输入或使剩余容量不可判定时
阻止新任务，无关逾期对象只警告并报告精确路径。
因此未知或未完成占用不能无限期留存。历史未知只通过一次性迁移入口分类，日常启动不得扫描全仓补救漏登记。
所有生产run和公共缓存发布入口必须在创建时登记，终态按实际保留结果更新台账。

工作流租约分别记录输入保护和“从当前时刻起仍可能新增”的峰值字节。父工作流登记一次，子任务继承，
共享输入只计一次；阶段完成后递减剩余承诺。启动只读取磁盘、可信台账和租约，目标5秒内完成；超过5/60秒
只报警，不能跳过安全判定。维护删除与消费登记共用短决策锁：锁内复查并标记退休，锁外执行大文件删除，
最后再锁内登记实际结果；锁不覆盖hash、复制、求解或飞行。

模型生成代码不能自动替代正式二进制：代码描述构建过程，`.mph`、SolidWorks装配体和SIMION交付包
还承载已验收的节点、选择、网格、解或外部引用状态。每个项目只保留一套通过门禁的当前正式发布；
若该发布包含多个结构变体，asset manifest必须分别绑定各变体的输入、资产、来源和资格，不得覆盖同名
二进制或共享未经验证的资格。尚未具备变体级发布合同的项目不得发布多变体Formal。
运行中的模型副本仅在它是该次实验的必要输入、结果或根因证据时保留。已被正式资产取代且可由代码
重建的重复二进制可从迁移快照清理，但必须保留数值结果、报告和清理manifest。

## 脚本生命周期

|命名|生命周期|规则|
|---|---|---|
|`scan_*` / `tmp_*`|一次性探索|结论归档后删除源码；未引用的临时产物可清理，失败/根因证据必须迁入artifacts并写manifest|
|`test_*`|长期验证|保留可重复判据；项目测试放项目 `tests/`，通用测试放 `common/`|
|`ms_*` / `phase*`|正式生产|长期维护；被新正式入口取代后才能删除|
|`verify_*`|门禁|必须给出明确 PASS/FAIL，不能只输出人工猜测所需数据|

新脚本创建前先确定生命周期。一次性脚本不能因“以后也许有用”进入长期目录；探索结论、失败
原因和适用范围应写入正确文档。具体删除权限与确认要求只由`AGENTS.md`定义，本页不维护
第二套清理授权。

### 新代码分类与一次性实现清理

所有新增代码、配置和辅助脚本在创建前必须归入以下一种生命周期；“先写进去以后再整理”不属于合法
分类：

|类别|允许位置与命名|完成要求|
|---|---|---|
|正式功能|最邻近的`projects/`、`integrations/`或已满足复用条件的`common/`职责目录；名称表达稳定能力，不使用`tmp/new/final/v2/retry`表示状态|接入唯一正式入口或机器注册能力，具备配置/Schema、失败关闭、相称测试、最近文档和artifact合同；活动入口采用当前标准，历史证据只读|
|长期验证|项目`tests/`、公共实现的邻近测试边界或具名验证入口；使用`test_*`或`verify_*`语义|保留可重复输入和明确PASS/FAIL判据；不得被生产入口反向依赖，也不得把一次性打印探针伪装成回归测试|
|一次性实现|默认位于`artifacts/projects/<project>/scratch/<task_id>/`或操作系统临时目录；文件名显式含`tmp_`、`diagnostic_`或`migration_`，不得进入正式源码目录|创建前向用户说明准确路径、名称、用途和删除时点；不得被正式入口、活动配置、文档结论或长期测试引用；使用完、方案放弃、任务中断后恢复或任务结束前必须删除|

一次性实现若显现稳定复用价值，必须先停止沿用，按正式功能或长期验证重新设计、迁入规范位置并补齐
合同、测试和文档；不能仅改名后保留。一次性输出若成为故障根因、科学结论或审计所需证据，须先按
run/artifact合同发布并进入manifest，此后它属于受管理证据而非临时产物；临时代码仍应删除。任务交接
必须分别报告新增的长期代码、创建并清理的一次性实现、保留的证据及未完成清理的明确阻塞。

## 冻结历史的既有载荷例外

已有`retired_campaigns`、文档收口原文和迁移载荷由其既有身份或manifest管理；其中的嵌套目录、
原始文件名和`INDEX.md`可能是证据结构。既有字节继续受校验，不因新目录规则、排版或旧术语批量重写。
移动或整合按上文[退役所有者与历史迁移](#退役所有者与历史迁移)单独核对，不能仅因它位于history就删除。

既有全本快照不构成今后每次编辑都复制全文的要求。后续普通修订由Git保存，科学记录保留其不可替代的
解释和证据；索引维护导航，当前文档维护当前答案。
