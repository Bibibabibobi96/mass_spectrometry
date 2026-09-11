# 源码、运行与文档生命周期

返回[仓库入口](../README.md)。本页定义产物、脚本、保留和历史归档。删除授权只由[AGENTS](../AGENTS.md)规定；知识归属见[仓库架构](REPOSITORY_ARCHITECTURE.md)。

## 产物与运行生命周期

### 工作区顶层卫生

仓库的管理边界包含其父工作区`mass_spectrometry/`，不只包含Git源码树。工作区顶层只允许：
发现入口`AGENTS.md`、`README.md`、`CLAUDE.md`，源码根`simulation_repo/`，产物根`artifacts/`，以及
固定工具缓存`.tools/`和明确列入`common/verify_repository_hygiene.ps1`的本机Agent、IDE、COMSOL和
MATLAB状态。`.tools/`当前只允许`cloc/2.10/cloc.exe`及其官方回退脚本`cloc/2.10/cloc-2.10.pl`；缓存、安装器、
一次性审计、会话交接、探针输出和任意临时目录不得直接留在工作区顶层。`artifacts/`顶层允许
`projects/`及下表明确注册的`common/`职责；项目run、scratch、cache、archive和formal仍按下节的唯一结构管理。新增顶层职责必须先
修改本节和现有卫生门禁，不能通过临时命名或扩大通配符绕过。

### Git / artifacts 边界

Git 只管理可复现、可审阅的轻量源码与文档。MPH、PA/PA#、IOB、SolidWorks 文件、运行日志、
粒子表和图像放在仓库同级 `artifacts/projects/<project>/`，不进入 Git。仓库根目录和源码树不得
充当scratch；`common/verify_repository_hygiene.ps1`负责检查根目录工具残留和误入Git的产物。

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
| `cache/simion_pa_basis/<cache-key>/generations/<generation-sha256>/` | `simion_pa_family_cache`（multipole PA-basis 适配器） |
| `cache/simion_single_flight_frontend/<SHA-256>/` | `simion_single_flight_frontend_pa_cache` |
| `cache/simion_single_flight_upstream_bridge/<SHA-256>/` | `simion_single_flight_upstream_bridge_pa_cache` |
| `cache/simion_single_flight_accelerator_main/<SHA-256>/` | `simion_single_flight_accelerator_main_pa_cache` |
| `cache/simion_accelerator_overlay/<SHA-256>/` | `simion_accelerator_overlay_pa_cache` |
| `cache/simion_oatof_downstream_pa/<SHA-256>/` | `simion_oatof_flight_tube_pa_cache`或`simion_oatof_reflectron_pa_cache`，由entry manifest唯一消歧 |
| `cache/verified_pulse/<SHA-256>/` | `rf_oatof_verified_pulse_timing_receipt`；仅保存相同内容身份下已通过完整pulse-on飞行确认的可删除时刻收据 |

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
`common/contracts/write_run_manifest.py`写manifest，再用`verify_run_manifest.py`重新计算全部记录；
没有通过manifest复核的目录只能留在scratch，不能被正式文档引用。

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

`finite_3d_transport.mph`、`.pa#/.paN/.pa-surf`、完整`trajectory_samples*`以及达到策略阈值的其他大文件
属于可选重型或可重建临时输出，不是每个成功run的必需证据。`compact`运行可在求解期间生成它们，但须在
终态manifest前由公共retention执行器移除，并用`retention_actions.json`记录相对路径、字节数、原SHA-256
和处置原因；执行器只能作用于尚无最终manifest的本次`runs/<run_id>`。writer和verifier会扫描未列出的
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

`history`不是实时工作日志。活跃调查的逐次原始事实以artifacts中的结构化运行记录为准；只有达到
可命名里程碑、结论关闭或旧方案被取代时才生成只读叙事快照。归档后若有新阶段，创建新的日期化
快照，不回写旧档案中的“当前”。项目README以紧凑`History索引`列出全部扁平Markdown入口，供人和
门禁发现；索引只列链接，不复制每份历史的结论、运行数字或时间线。

新建history中的配置注册表、结果矩阵和正文简称必须应用开发标准的
[科学配置规范名称与结果身份](DEVELOPMENT_STANDARDS.md#科学配置规范名称与结果身份)；既有只读
history仍按该标准记录映射，不回写原始证据。

current文档必须保持可执行的当前视图。满足以下任一条件时，在同一主题提交中冻结日期化history并
收缩current：

1. 调查、迁移或候选已经关闭、被取代或达到明确里程碑，后续不再执行原步骤；
2. 一个current章节开始按日期叙述两个以上已完成尝试，或列出三个以上仅用于追溯的历史run ID；
3. README、PROJECT和软件文档中出现同一状态、数值表或开放任务正文；
4. 日期化审计、保留盘点或处置清单已完成执行，只剩追溯价值。

迁移后，项目README只保留导航，PROJECT只保留当前参数摘要、资格、有效证据结论与未完成动作，软件
文档只保留活动入口、实现边界和独立验收。完整时间线、旧数值表、失败链、run清单和被取代文本进入
history。current可链接一个代表性机器合同或history入口，但不得复制manifest的完整清单。每个开放
任务只写未完成动作、进入条件和关闭条件；“已完成事实 + 若获批再做”必须拆开，完成事实归当前结论
或history。

项目`docs/history/`和根`docs/history/`采用扁平Markdown入口：所有归档清单或叙事快照直接放在该目录；没有附加载荷时只保留
Markdown。需要冻结原始文本、源码或二进制时，使用与Markdown完全同名（去掉`.md`）的可选载荷
子目录，清单逐项链接其中每个文件并记录SHA-256或链接已验证的`SHA256SUMS.txt`。载荷目录不得再
嵌套子目录，不得包含Markdown入口、`__pycache__`、`.pyc`或其他运行缓存；项目README只索引扁平
Markdown入口。这里的“载荷”表示只读原始证据，不限于二进制，也不因保存源码而恢复其活跃资格。

### 保留与清理策略

保留策略面向可复现性：`formal`只保留当前门禁通过资产，候选及其结果留在来源`run_id`中，
`archive`保留被正式引用的旧资产和冻结快照，`runs`保留被文档引用或用于失败根因的运行，`scratch`
不作为引用来源。删除仍遵守`AGENTS.md`的用户确认规则；
“已进入history”“已被superseded”或“manifest已生成”本身均不授权删除原始证据。
run生成阶段的自动保留行为只按上文预注册的run产物保留合同执行；它不授权事后清理既有run。

### 工作区容量水位线

工作区`artifacts/`的目标上限为 **500 GiB**。当该树的实占用即将达到或超过此水位线时，运行器不得继续
发布会使其越线的重型载荷；必须先按本节的必要性顺序执行可审计处置。**同一必要性等级内严格按时间从旧到新**：
可重建 cache 优先采用其在成功/完成 run manifest 中记录的最后一次实际消费时刻，缺失该可信记录才回退到
cache generation 发布时刻；run 采用终态记录时刻，scratch 采用创建时刻。不得用易受索引或备份影响的文件访问时间，
也不得因文件更大而跳过较旧对象：

1. 无 manifest 的 scratch、临时 staging 与损坏/不完整 cache generation；
2. 未被活动实验引用、可由冻结输入重建的非 Formal cache；
3. `compact` 类中断 run 的可重建重型 payload（仅 PA、轨迹和其他 retention 合同允许移除的文件），保留冻结输入、日志、summary、manifest 与处置 receipt；
4. 仅在用户针对精确对象明确授权后，处置不再被文档/manifest引用且已有替代证据的非 Formal run 重型副本。

`formal/`、`archive/`、活动 cache generation、当前实验引用的 cache、唯一来源输入及任何被当前文档引用的科学结果
始终禁止由容量治理删除。历史 run 内已冻结的 cache manifest 是重建 provenance，不把相应非活动、可重建 cache
提升为不可删除证据。每次处置必须先验证对象身份、活动引用、终态、可重建性和精确路径，随后
写入日期化审计与处置 receipt（路径、字节数、SHA-256、理由、删除后可用空间）；水位线不是放宽证据保护
或删除权限的例外。

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

新归档采用上文的扁平入口和同名载荷。已有`retired_campaigns`由不可变机器manifest管理，
部分旧载荷含嵌套目录和`INDEX.md`迁移映射；这些是证据元数据，不是活动文档入口。
文档门禁保留其现有身份与哈希校验，不因排版、旧术语或旧链接改写冻结字节。
例外不允许新任务复制该历史布局；新结论引用旧证据时在当前正文说明范围与替代关系。

归档按科学问题或里程碑合并，不按每次小修复建立文件。优先引用已有完整历史；只有它不能承载本次
独立证据时才新建快照。Git保留普通编辑历史，history保留需要解释科学结论或受管迁移的材料。
