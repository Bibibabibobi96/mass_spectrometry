# 质谱仿真仓库

本仓库用于质谱仪器及离子/电子光学部件的参数化多物理场建模与验证。项目通过统一机器契约联动
COMSOL、SIMION、MATLAB、Python和SolidWorks，目标是形成跨求解器独立闭合、GUI可检查、CAD同步
且能够可靠重建的正式模型。

仓库同时面向人类研究人员和编码Agent，当前包含oa-TOF、RF四极杆碰撞冷却与传输、电子轰击离子源
和Wehnelt电子枪等项目。各项目以物理问题为中心组织，COMSOL、SIMION、MATLAB、Python和SolidWorks
是平等的实现工具，不以任何软件作为目录主轴。

长期使命和能力边界以[`docs/VISION.md`](docs/VISION.md)为准，跨项目实施阶段以
[`docs/ROADMAP.md`](docs/ROADMAP.md)为准；两者不覆盖项目当前状态或机器参数合同。

## 如何使用仓库

本README是仓库的操作入口、知识路由器和所有维护者共用规则。每次开始任务先读本文件，再进入目标项目；
不要从软件目录或历史日志猜测当前状态。

## 固定阅读顺序

1. 先读本文件，判断任务属于哪个项目、哪类知识和哪种生命周期。
2. 读目标项目的 `projects/<project>/README.md`，确认该项目的入口与知识写入规则。
3. 读该项目的 `docs/PROJECT.md`，确认当前参数、正式/候选边界、已闭合结论和开放任务。
4. 只按实际操作再读 `docs/COMSOL.md`、`docs/SIMION.md` 或 `docs/CAD.md` 中的一份。
5. 只有追溯旧结论时才读 `docs/history/`；历史记录不能覆盖 `PROJECT.md`。
6. 只有项目文档无法回答跨项目问题时，才读仓库根 `docs/` 中对应的通用文档。

日常项目任务不要求重复阅读Vision或Roadmap；只有判断长期范围、建立新项目、调整跨项目优先级或
评估平台能力时才读取它们。

四个项目现均已建立`README.md → docs/PROJECT.md`的统一入口；软件实施文档仍按实际规模建立，
不为追求形式一次性拆出空文档。

## 知识权威与写入路由

### 文档权威和冲突优先级

本仓库采用单一权威来源（Single Source of Truth, SSOT）。规范只在最高权威文档定义一次；下游
文档只链接该定义，并记录本项目的应用、例外或验证结果，不复制整段通用规则。

仓库使用者同时包括人类与AI。两者共享相同的项目入口、术语、机器契约和验收证据；不会为AI
另建一套内容不同的“简化真值”。`AGENTS.md`只额外规定Agent的执行行为，不取代面向所有使用者
的项目知识文档。

|文档|性质|唯一职责|
|---|---|---|
|仓库[`AGENTS.md`](AGENTS.md)|规范性|Agent执行、权限、删除授权、测试报告与自主Git行为；发生执行冲突时优先级最高|
|本README|规范性|仓库架构、阅读顺序、知识路由、参数与产物生命周期、通用Git及跨项目标准|
|项目`README.md`|规范性入口|项目导航、权威入口、项目特有硬规则；不重述根规则|
|项目`docs/PROJECT.md`|项目权威状态|当前参数、正式/候选边界、跨软件结论、开放任务|
|项目软件文档|实施说明|单一软件的节点、接口、运行与独立验证；不定义跨软件结论|
|[`docs/VISION.md`](docs/VISION.md)|长期愿景|平台使命、目标闭环、能力边界和正式交付目标；不记录阶段顺序或当前状态|
|[`docs/ROADMAP.md`](docs/ROADMAP.md)|跨项目规划|设计族、能力阶段、依赖顺序和阶段完成条件；不保存项目短期任务|
|根`docs/`|通用参考|至少两个项目验证过的跨项目技术知识|
|项目`docs/history/`|只读证据|失效结论和演进过程；任何“当前”“正式”“下一步”均按归档时点解释|

冲突处理顺序是：执行行为看`AGENTS.md`，仓库结构和知识归属看本README，项目当前事实看
`docs/PROJECT.md`，实现细节看对应软件文档。历史记录和README中的状态速览都不能覆盖
`PROJECT.md`。项目确有例外时，只记录“例外内容、原因、适用范围和失效条件”，不得复制后修改
通用规则形成第二版本。

### 新知识写入表

|新信息|权威写入位置|不得写入|
|---|---|---|
|项目统一几何、粒子源、指标定义、正式状态、跨软件结论、下一步|`projects/<project>/docs/PROJECT.md`|单个软件文档或历史日志|
|某项目的 COMSOL 节点、网格、求解、GUI 操作和独立错误|项目 `docs/COMSOL.md`|根通用文档，除非已跨项目验证|
|某项目的 SIMION PA/GEM、Program、Fly2、网格、GUI 和独立错误|项目 `docs/SIMION.md`|COMSOL/CAD 文档|
|某项目的 STEP、SolidWorks 零件/装配、坐标和保存验证|项目 `docs/CAD.md`|SIMION/COMSOL 文档|
|已关闭、被取代或达到明确里程碑且仍需追溯的长过程|项目 `docs/history/`|当前状态入口或活跃运行日志|
|机器必须共同读取的项目参数|项目 `config/`，优先 JSON|散落在文档中的多份数值|
|项目身份、设计族、机器能力和成熟度|项目 `config/project.json`；根注册表自动生成|Roadmap或人工维护的第二份项目表|
|工程需求字段、选择与规划规则|`common/contracts/`中的Schema和校验器；获批实例归目标项目`config/requests/`|自然语言对话、Roadmap或求解器脚本|
|项目设计变量、优化包络和候选参数派生|项目`config/design_variables.json`、`config/optimization_envelope.json`及邻近编译器|正式baseline、对话或优化器内部隐藏状态|
|跨项目稳定的 COMSOL API|`docs/COMSOL_API.md`|单一项目参数|
|跨项目稳定的 COMSOL 排错策略|`docs/COMSOL_DEBUGGING.md`|只验证过一次的项目个例|
|跨求解器通用的网格、统计、FWHM 与几何闭合方法|`docs/VALIDATION_METHODS.md`|某次运行的具体结果|
|多极杆通用解析理论、符号、电压约定和模型适用域|[`docs/multipoles/index.md`](docs/multipoles/index.md)|具体项目参数、状态或运行结果|
|跨项目稳定的 SIMION GUI/PA/GEM/Program 经验|`docs/SIMION_REFERENCE.md`|oa-TOF 专属尺寸|
|仓库长期使命、能力边界和目标交付形态|`docs/VISION.md`|项目PROJECT、Roadmap或history|
|跨项目设计族、未来项目和能力阶段|`docs/ROADMAP.md`|项目短期下一步或机器参数合同|
|COMSOL可复用测试与其已验证范围|`common/comsol/README.md`及测试源码|根API或项目正式结论|
|其他可复用代码事实|源码和最邻近的短 README/注释|长项目历史|

### 跨项目知识提升条件

判断规则只有两步：先问“换一个项目是否仍成立”，再问“这是已发表解析理论、调用事实、排错方法，
还是当前项目结论”。没有通过第二个不同项目验证的工程经验先留在项目文档，不能提前提升为通用规则。
有固定权威来源、明确符号和适用域的解析理论可以先作为根 `docs/` 下的 `provisional` 参考；建立
求解器无关实现和自动理论测试后才可提升为 `reference`。这项例外不适用于单项目数值经验或排错结论。

项目内采用星形引用：项目 README 是入口，指向 PROJECT/COMSOL/SIMION/CAD；三份软件文档
只返回 PROJECT，不互相横向引用。跨软件结论必须先统一输入并验证，再提升到 PROJECT。这样
人和 AI 都只需要记住一个入口，不维护文档网状图。

## 总体目录与项目边界

```text
simulation_repo/
├─ README.md                 # 本文件：仓库操作规则与知识路由
├─ config/
│  └─ project_registry.json # 由项目描述符生成的发现索引，禁止手改
├─ docs/                     # 跨项目知识，直接放置，不设 software/ 重复层
│  ├─ VISION.md
│  ├─ ROADMAP.md
│  ├─ COMSOL_API.md
│  ├─ COMSOL_DEBUGGING.md
│  ├─ VALIDATION_METHODS.md
│  ├─ SIMION_REFERENCE.md
│  └─ multipoles/              # 多极杆设计族通用理论与可复现图示
├─ projects/                 # 平级项目；不再按软件或器件类别嵌套
│  ├─ oa_tof/
│  ├─ electron_impact_ion_source/
│  ├─ rf_quadrupole_collision_cooling/
│  └─ wehnelt_electron_gun/
├─ common/
│  ├─ comsol/                # LiveLink启动器、可复用COMSOL测试及就近README
│  ├─ paths/                 # 工作区与 artifacts 路径解析
│  └─ solidworks/            # STEP→SolidWorks 可复用桥接
├─ official_docs/            # 官方离线原始资料及索引
```

项目测试留在各项目内；只有出现真正跨项目的仓库级门禁时才创建根 `tests/`，不预建空目录。

源码目标目录深度不超过 5 级（文件可处于第 6 段）。新目录只有在承载明确职责时才创建；不建立
`components/`、`project/components/`、`docs/software/` 或只有一个子目录的重复分类层。

### 项目与软件平权

每个 `projects/<project>/` 是一个可独立理解、验证和交付的研究项目。项目可以同时包含
`comsol/`、`simion/`、`cad/`、`analysis/`、`config/` 和 `tests/`，但不要求空目录占位。
目录按知识对象和生命周期划分，不按“主软件/辅助软件”划分。选择结果以物理问题和统一契约
为准，不以某个求解器先完成为准。

项目ID对应一条可以独立维护baseline、验收状态和正式资产的具体硬件设计线，不对应宽泛设计族。
设计族通过机器元数据和Roadmap关联，不在`projects/`或artifacts中增加包住多个formal的深层容器。
同一硬件只改变电压、频率、气体、粒子源或运行目的时使用mode；参数扫描和优化候选使用run。
电极拓扑、主要功能、正式资产或验收合同需要独立长期维护时，建立新的平级项目。共享代码只有在
第二个项目实际复用并验证后才提升到`common/`。

当前项目：

- `projects/oa_tof`：正交加速双级反射 oa-TOF。
- `projects/electron_impact_ion_source`：电子轰击离子源。
- `projects/rf_quadrupole_collision_cooling`：RF四极杆碰撞冷却与传输。
- `projects/wehnelt_electron_gun`：螺旋灯丝 Wehnelt 电子枪。

每个项目用`config/project.json`声明稳定项目身份、设计族、可选择能力及其真实成熟度；
`common/contracts/build_project_registry.py`据此生成根`config/project_registry.json`。根注册表只用于
项目发现和自动选择，不取代项目`PROJECT.md`、baseline/resolved参数合同或Roadmap，也不得手改。

## 参数权威与单向派生

所有项目必须遵循同一条不可逆的数据流：

`物理输入参数 + 公式 + 明确精度规则 → 项目config中的baseline工程参数 → COMSOL / SIMION / CAD`

- `baseline`不是任一软件当前文件的抄录，而是物理输入经公式计算后的唯一工程参数契约。
- 公式、输入量、单位和工程舍入位数必须机器可读并接受门禁；不得只把最终尺寸散写在代码或文档中。
- COMSOL、SIMION、CAD及SolidWorks只能读取、生成或验证baseline，不得因网格、格式化、GUI显示、
  旧模型或某个求解器的现有数值而反向改写baseline。
- 扫描参数也必须先形成候选契约，再联动生成各实现；禁止分别手改多个软件后凭肉眼判断一致。
- 序列化精度不得低于baseline精度。`%g`、Excel显示位数或GUI四舍五入不能充当工程参数定义。
- 若实现与baseline冲突，实现一律判为失效候选；在重新生成、跨软件门禁和正式CAD同步全部通过前，
  不得转正。AI和人均无权为了迁就某一现有文件而擅自改变派生结果。

### 跨项目几何参数化标准

- 人工只维护`baseline`物理设计；项目解析器单向生成`resolved`，各软件不得重复推导或反写。
- 数值模式与物理设计分层；候选运行参数不得反写物理baseline。
- 开发入口读取统一契约；SIMION等正式交付包可由该契约生成自包含文件，并接受过期门禁。
- 正式入口不得以缺失配置时回退到旧物理硬数字；候选覆盖不得反写baseline。
- 每项目提供`Static/Candidate/Formal`三级总门禁；正式几何仍须完成COMSOL GUI与SolidWorks同步。

## 语言职责

- MATLAB R2025b只负责COMSOL模型树、求解、GUI结果节点、MPH和正式STEP导出。
- GEM/Lua/Fly2只负责SIMION几何、PA/IOB、粒子和运行时行为。
- Python 3.11负责求解器无关的数据规范、峰形/FWHM/统计、跨软件比较和正式分析图。
- PowerShell只负责Windows环境检查、进程调用和PASS/FAIL门禁，不实现物理公式。
- JSON/CSV是跨语言机器契约；Excel只允许人工导入和检查，不能作为唯一真值。

分析算法不得在MATLAB、Python、Lua和Excel中平行发展多份。某项目建立Python参考实现后，
软件内MATLAB图表只作为GUI展示和对等检查；正式跨软件指标以项目`config/`中的版本化分析契约
和Python参考实现为准。公共Python代码仍须经过第二个项目实际复用后才能上移`common/`。

## 产物与运行生命周期

### Git / artifacts 边界

Git 只管理可复现、可审阅的轻量源码与文档。MPH、PA/PA#、IOB、SolidWorks 文件、运行日志、
粒子表和图像放在仓库同级 `artifacts/projects/<project>/`，不进入 Git。仓库根目录和源码树不得
充当scratch；`common/verify_repository_hygiene.ps1`负责检查根目录工具残留和误入Git的产物。

### artifacts 目录职责

唯一结构：

```text
artifacts/projects/<project>/
├─ 00_README.txt
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
的错觉。运行的模型、结果和日志统一放在同一个`runs/<run_id>/`中，不再建立顶层`models/`、`cad/`、
`results/`或`logs/`，也不按软件再拆第二棵运行树。`00_README.txt`只提供面向资源管理器的导航，
不得成为项目状态或规则权威。各目录的状态、保留与清理条件由本节末尾统一定义。脚本必须通过项目
路径解析器定位这里，禁止硬编码用户名或重建旧 `artifacts/components/`。
SIMION IOB 可能嵌入 PA 的绝对路径，移动工作区后必须重新打开/保存或重建 IOB，并验证四个 PA
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
  `formal/comsol/oa_tof__model.mph`和`formal/cad/oa_tof__assembly.SLDASM`。这样文件脱离父目录后仍可
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

知识的权威位置只由“新知识写入表”决定；本节只规定调查状态如何迁移。归档不按操作者、软件或
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
原始文件若无法唯一归属，先移入项目`scratch/<software>/`并在
当前任务结束前完成归属或报告，不得长期悬置。

### history 冻结条件

`history`不是实时工作日志。活跃调查的逐次原始事实以artifacts中的结构化运行记录为准；只有达到
可命名里程碑、结论关闭或旧方案被取代时才生成只读叙事快照。归档后若有新阶段，创建新的日期化
快照，不回写旧档案中的“当前”。项目README必须列出全部history入口。

`docs/history/`采用扁平Markdown入口：所有归档清单或叙事快照直接放在该目录；没有附加载荷时只保留
Markdown。需要冻结原始文本、源码或二进制时，使用与Markdown完全同名（去掉`.md`）的可选载荷
子目录，清单逐项链接其中每个文件并记录SHA-256或链接已验证的`SHA256SUMS.txt`。载荷目录不得再
嵌套子目录，不得包含Markdown入口、`__pycache__`、`.pyc`或其他运行缓存；项目README只索引扁平
Markdown入口。这里的“载荷”表示只读原始证据，不限于二进制，也不因保存源码而恢复其活跃资格。

### 保留与清理策略

保留策略面向可复现性：`formal`只保留当前门禁通过资产，候选及其结果留在来源`run_id`中，
`archive`保留被正式引用的旧资产和冻结快照，`runs`保留被文档引用或用于失败根因的运行，`scratch`
不作为引用来源。删除仍遵守`AGENTS.md`的用户确认规则；
“已进入history”“已被superseded”或“manifest已生成”本身均不授权删除原始证据。

模型生成代码不能自动替代正式二进制：代码描述构建过程，`.mph`、SolidWorks装配体和SIMION交付包
还承载已验收的节点、选择、网格、解或外部引用状态。每个项目只保留一套通过门禁的当前正式二进制；
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
原因和适用范围应写入正确文档。具体删除权限与确认要求只由`AGENTS.md`定义，本README不维护
第二套清理授权。

## GUI 与 CAD 门禁

- COMSOL：影响物理或数值结果的几何、选择、材料、物理场、粒子释放、网格、Study、Solver、
  数据集和派生值必须持久化为 Model Builder 中可见、可编辑、可保存的节点。必须重新打开 MPH，
  验证 GUI Compute 使用预期设置；只验证脚本 `runAll` 不足。
- SIMION：正式 IOB 的 PA 实例、坐标、电压、粒子定义和 Program 必须能在 GUI 中检查。关键
  物理不能只藏在命令行参数或外部后处理里；数值检测面也必须有 GUI 可见实体。
- 几何联动：迁移器件、间隙、电极厚度、孔径、屏蔽件和检测面尽量由统一参数派生。跨求解器
  测试必须证明坐标、有效面、粒子表和统计定义一致。
- SolidWorks：正式机械几何一旦确认，必须在同一任务更新正式 COMSOL MPH 和 SolidWorks
  零件/装配体，并验证数量、版本、变换、保存错误/警告和参数一致性；未同步不得称为正式完成。

## 通用验证口径

质量分辨率统一为 `R=m/FWHM_m`；窄峰时间域等价式是 `R=T/(2*FWHM_t)`。`2.3548×sigma`
只有在峰形近似高斯时才可作为 FWHM 代理。比较 COMSOL 与 SIMION 时至少统一几何、粒子表、
有效检测面、命中定义、FWHM 算法和样本量，并分别检查网格收敛与统计不确定度。详细方法写入
`docs/VALIDATION_METHODS.md`，项目数值写入项目 PROJECT。

## 工具链与执行入口

### 轻量门禁

不依赖商业软件和外部artifacts的统一入口为`common/verify_lightweight.ps1`。它使用Python 3.11运行
文档/仓库卫生门禁、机器合同测试、项目注册表新鲜度、oa-TOF Static门禁和RF Static门禁；本机默认
使用`.venv`，GitHub Workflow注入干净运行器的Python路径。门禁逻辑只在该脚本及其调用的项目门禁中维护；
项目发现、设计请求校验和求解器中立规划入口见[`common/contracts/README.md`](common/contracts/README.md)。
`.github/workflows/lightweight-gate.yml`只负责编排，在push、pull request和人工触发时调用同一入口，
不复制检查规则，也不执行求解器、CAD或正式资产门禁。

### artifact结构门禁

本机存在artifacts时运行：

```powershell
python common/contracts/verify_artifact_layout.py ..\artifacts\projects
```

它只检查目录合同、`run_id/archive_id`、三件套和manifest身份，不读取大二进制内容；因此适合每次
产物整理后运行，但不放进不具备本机artifacts的GitHub Workflow。命名合同单元测试仍属于轻量门禁。

### COMSOL R2025b 执行入口

本机 MATLAB R2025b 与 COMSOL 6.4 的长期入口是：

```powershell
.\common\comsol\run_comsol_r2025b.ps1 -TaskScript <任务脚本.m> -ReportPath <报告.txt>
```

入口通过 `common/comsol/livelink_r2025b/comsolstartup.m` 连接官方 LiveLink/Java API。首次使用
新的直连脚本先做最小测试。临时连接工具不能替代正式项目脚本和项目专属后处理判据。
连接生命周期只由该入口管理：任务脚本不得再次调用`mphstart`。一次相关任务在同一连接内完成
加载、Compute、保存和轻量节点检查；容易触发大内存传输的粒子结果读取可放入第二个干净任务。
入口对未创建任务报告的启动失败做有限干净重试；若报告已创建，只对白名单中的首次模型打开
`mphload/mphopen + Not connected to a server`连接瞬态重试，并先归档失败报告。进入配置、Study
Compute或求解器后的错误不自动重算。

### 正式工具链基线

自2026-07-15起，所有项目的新建、修改、验证和交付均只使用**MATLAB R2025b**与
**SolidWorks 2022**。MATLAB/COMSOL任务必须通过上述R2025b入口运行；凡涉及STEP导入、
零件、装配或CAD保存的任务必须使用`common/solidworks/`中的SolidWorks 2022桥接。不得启动、
调用或为兼容而降级到MATLAB R2022或SolidWorks 2013。历史文档中出现的旧版本仅用于解释当时
结果，不构成可用入口或复现环境。

每次涉及MATLAB或SolidWorks的正式变更前，运行：

```powershell
.\common\verify_toolchain.ps1
```

该门禁验证R2025b可执行文件和SolidWorks 2022 PIA/COM revision；项目默认继承本节，不在每个
README重复声明。它不重写或重存已有的MPH、SLDPRT或SLDASM。若Live COM探测失败，门禁可用
`FILE_VERSION_FALLBACK`确认安装版本与PIA基线，但这不证明CAD可编辑或可保存；任何实际CAD
变更仍必须通过项目SolidWorks导出与装配门禁。

自2026-07-16起，求解器无关分析固定使用**64位Python 3.11**。MATLAB R2025b官方支持
Python 3.9至3.12；本机默认Python 3.14和旧Python 3.8均不得作为本仓库正式运行时。依赖由根目录
`pyproject.toml`声明、`requirements-lock.txt`冻结，并安装在不入Git的`.venv/`。oa-TOF入口见
`projects/oa_tof/analysis/README.md`。

## Git 规则

仓库根是 `simulation_repo/`，远程私有仓库为
`https://github.com/Bibibabibobi96/mass_spectrometry.git`。提交只包含一个可审阅主题；使用明确
路径或 `git add -p`，不习惯性执行 `git add .`。提交前运行：

```powershell
git status --short --branch
git diff --check
git diff --stat
.\common\verify_lightweight.ps1
```

确认没有 MPH、PA/IOB、结果、日志或一次性脚本进入暂存区。不得强制推送、改写远程历史或
覆盖/夹带任务开始前的无关改动；Agent何时自主提交和推送只由[`AGENTS.md`](AGENTS.md)定义。

提交信息使用简洁、可检索的标题。除纯机械性或单点且意图显而易见的修改外，还必须有与改动复杂度
和风险相称的正文，说明修改动机、关键行为变化、验证结果，以及必要的限制或未完成事项；正文应让
未来维护者无需查阅聊天记录即可理解提交，但不逐文件复述diff，也不设固定字数。

## 任务完成定义

一次变更只有在源码、机器契约、最近的权威文档、路径引用和相称测试一致后才算完成。验证证据必须
足以还原目标、输入、唯一变量、结果、判据和产物，但不保存无关常规日志；正式几何还必须满足
COMSOL GUI和SolidWorks同步门禁。Agent面向用户的报告顺序与篇幅只由[`AGENTS.md`](AGENTS.md)定义。

文档变更还应运行`common/verify_documentation.ps1`，检查唯一H1、标题层级、相对链接、历史归档
标记和项目入口完整性。自动门禁只验证可机器判断的结构；技术结论是否放在正确权威层仍需审阅。
