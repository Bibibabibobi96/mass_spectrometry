# 质谱仿真仓库

本仓库用于质谱仪器及离子/电子光学部件的参数化多物理场建模与验证。项目通过统一机器契约联动
COMSOL、SIMION、MATLAB、Python和SolidWorks，目标是形成跨求解器独立闭合、GUI可检查、CAD同步
且能够可靠重建的正式模型。

仓库同时面向人类研究人员和编码Agent，当前包含单次反射正交加速飞行时间质量分析器、RF多极杆
离子光学、开孔长管电子轰击离子源和横置螺旋灯丝Wehnelt电子枪等项目。各项目以物理问题为中心组织，
COMSOL、SIMION、MATLAB、Python和SolidWorks
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
4. 修改或审查代码时完整阅读[`docs/DEVELOPMENT_STANDARDS.md`](docs/DEVELOPMENT_STANDARDS.md)；纯状态
   查询、结果解释或不涉及代码的文档任务不必读取。
5. 创建或实质修改运行诊断图、证据图、报告图或发表图时，完整阅读
   [`docs/PLOTTING_STANDARDS.md`](docs/PLOTTING_STANDARDS.md)。
6. 只按实际操作再读 `docs/COMSOL.md`、`docs/SIMION.md` 或 `docs/CAD.md` 中的一份。
7. 只有追溯旧结论时才读 `docs/history/`；历史记录不能覆盖 `PROJECT.md`。
8. 只有项目文档无法回答跨项目问题时，才读仓库根 `docs/` 中对应的通用文档。

日常项目任务不要求重复阅读Vision或Roadmap；只有判断长期范围、建立新项目、调整跨项目优先级或
评估平台能力时才读取它们。

现有项目均以`README.md → docs/PROJECT.md`作为统一入口；软件实施文档仍按实际规模建立，
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
|[`docs/DEVELOPMENT_STANDARDS.md`](docs/DEVELOPMENT_STANDARDS.md)|规范性|人类与Agent共同遵守的跨语言编码、合同实现、[术语作用域](docs/DEVELOPMENT_STANDARDS.md#术语权威与作用域)、外部进程、性能、缓存和测试标准；不定义仓库架构或项目状态|
|[`docs/PLOTTING_STANDARDS.md`](docs/PLOTTING_STANDARDS.md)|规范性|跨项目科学绘图、图形证据、可访问性、追溯、导出与图审标准；不定义指标或项目状态|
|项目`README.md`|规范性入口|项目导航、权威入口、项目特有硬规则；不重述根规则|
|项目`docs/PROJECT.md`|项目权威状态|当前参数、正式/候选边界、跨软件结论、开放任务|
|项目软件文档|实施说明|单一软件的节点、接口、运行与独立验证；不定义跨软件结论|
|[`docs/VISION.md`](docs/VISION.md)|长期愿景|平台使命、目标闭环、能力边界和正式交付目标；不记录阶段顺序或当前状态|
|[`docs/ROADMAP.md`](docs/ROADMAP.md)|跨项目规划|设计族、能力阶段、依赖顺序和阶段完成条件；不保存项目短期任务|
|获批跨项目架构决策|迁移目标|带明确状态、适用边界和替换门禁的跨项目目标架构；不是当前已实现能力或已验证通用参考|
|根`docs/`其他稳定文档|通用参考|至少两个项目验证过的跨项目技术知识|
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
|全仓日期化审计、处置清单和一次性盘点|根`docs/history/`；稳定索引为[`docs/AUDITS.md`](docs/AUDITS.md)|根`docs/`稳定参考层或项目PROJECT|
|机器必须共同读取的项目参数|项目 `config/`，优先 JSON|散落在文档中的多份数值|
|项目身份、设计族、机器能力和成熟度|项目 `config/project.json`；根注册表自动生成|Roadmap或人工维护的第二份项目表|
|工程需求字段、选择与规划规则|`common/contracts/`中的Schema和校验器；获批实例归目标项目`config/requests/`|自然语言对话、Roadmap或求解器脚本|
|项目设计变量、优化包络和候选参数派生|项目`config/design_variables.json`、`config/optimization_envelope.json`及邻近编译器|正式baseline、对话或优化器内部隐藏状态|
|跨项目稳定的 COMSOL API|`docs/COMSOL_API.md`|单一项目参数|
|跨项目稳定的 COMSOL 排错策略|`docs/COMSOL_DEBUGGING.md`|只验证过一次的项目个例|
|跨求解器通用的网格、统计、FWHM 与几何闭合方法|`docs/VALIDATION_METHODS.md`|某次运行的具体结果|
|跨项目编码、命名、复杂度、合同实现、进程、缓存、性能和测试规范|`docs/DEVELOPMENT_STANDARDS.md`|项目状态、物理参数或Agent权限|
|跨项目科学绘图、图形证据、色图、坐标轴、导出、caption和图审规范|`docs/PLOTTING_STANDARDS.md`|单次运行结果或项目状态|
|多极杆通用解析理论、符号、电压约定和模型适用域|[`docs/multipoles/index.md`](docs/multipoles/index.md)|具体项目参数、状态或运行结果|
|跨项目稳定的 SIMION GUI/PA/GEM/Program 经验|`docs/SIMION_REFERENCE.md`|oa-TOF 专属尺寸|
|仓库长期使命、能力边界和目标交付形态|`docs/VISION.md`|项目PROJECT、Roadmap或history|
|跨项目设计族、未来项目和能力阶段|`docs/ROADMAP.md`|项目短期下一步或机器参数合同|
|获批但尚未实施的跨项目架构决策|根`docs/`中的具名决策文档，并在Roadmap和所有参与项目PROJECT登记迁移任务|把目标架构写成当前能力、只登记单侧项目或预建空实现目录|
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
│  ├─ DEVELOPMENT_STANDARDS.md
│  ├─ PLOTTING_STANDARDS.md
│  ├─ VALIDATION_METHODS.md
│  ├─ SIMION_REFERENCE.md
│  ├─ AUDITS.md                # 已完成全仓日期化审计的稳定索引
│  ├─ history/                 # 全仓一次性审计与处置快照
│  └─ multipoles/              # 多极杆设计族通用理论与可复现图示
├─ projects/                 # 平级项目；不再按软件或器件类别嵌套
│  ├─ single_reflection_oa_tof_mass_analyzer/
│  ├─ parallel_mirror_dual_stripe_mr_tof/
│  ├─ apertured_tube_electron_impact_ion_source/
│  ├─ rf_quadrupole_ion_optics/
│  ├─ rf_hexapole_ion_optics/
│  ├─ rf_octupole_ion_optics/
│  └─ transverse_helical_filament_wehnelt_electron_gun/
├─ common/
│  ├─ comsol/                # LiveLink启动器、可复用COMSOL测试及就近README
│  ├─ multipole/             # 四/六/八极杆共享合同、圆杆几何、COMSOL/SIMION传输与分析
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

当前项目ID与显示名：

| `project_id` / 目录 | `display_name` |
|---|---|
| `single_reflection_oa_tof_mass_analyzer` | 单次反射正交加速飞行时间质量分析器 |
| `parallel_mirror_dual_stripe_mr_tof` | 开放路径平行镜双条带多次反射飞行时间质量分析器 |
| `apertured_tube_electron_impact_ion_source` | 开孔长管电子轰击离子源 |
| `rf_quadrupole_ion_optics` | RF四极杆离子光学 |
| `rf_hexapole_ion_optics` | RF六极杆离子光学 |
| `rf_octupole_ion_optics` | RF八极杆离子光学 |
| `transverse_helical_filament_wehnelt_electron_gun` | 横置螺旋灯丝Wehnelt电子枪 |

每个项目用`config/project.json`声明稳定项目身份、设计族、可选择能力及其真实成熟度；
`common/contracts/build_project_registry.py`据此生成根`config/project_registry.json`。根注册表只用于
项目发现和自动选择，不取代项目`PROJECT.md`、baseline/resolved参数合同或Roadmap，也不得手改。
发生行政改名时，活动源码、新run和新artifact只使用当前`project_id`。描述符`legacy_identities`保留
旧项目身份及唯一artifact位置合同：未迁移时`source_pending_relocation`只读旧根，完成逐文件身份复核
后原子切为`archived_verified`且只指向当前项目的具名`archive/`载荷；不得长期回退或搜索旧顶层路径。
旧manifest不改写、不追加新run，并始终按其recorded project identity验证；行政改名和路径迁移均不得
改变原资格、状态或声明边界。

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

### 工作区顶层卫生

仓库的管理边界包含其父工作区`mass_spectrometry/`，不只包含Git源码树。工作区顶层只允许：
发现入口`AGENTS.md`、`README.md`、`CLAUDE.md`，源码根`simulation_repo/`，产物根`artifacts/`，以及
固定工具缓存`.tools/`和明确列入`common/verify_repository_hygiene.ps1`的本机Agent、IDE、COMSOL和
MATLAB状态。`.tools/`当前只允许`cloc/2.10/cloc.exe`；缓存、安装器、
一次性审计、会话交接、探针输出和任意临时目录不得直接留在工作区顶层。`artifacts/`顶层只允许
`projects/`；项目run、scratch、cache、archive和formal仍按下节的唯一结构管理。新增顶层职责必须先
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
| `cache/simion_pa_basis/<SHA-256>/` | `multipole_simion_pa_basis_cache` |
| `cache/simion_single_flight_frontend/<SHA-256>/` | `simion_single_flight_frontend_pa_cache` |
| `cache/simion_accelerator_overlay/<SHA-256>/` | `simion_accelerator_overlay_pa_cache` |
| `cache/simion_oatof_downstream_pa/<SHA-256>/` | `simion_oatof_flight_tube_pa_cache`或`simion_oatof_reflectron_pa_cache`，由entry manifest唯一消歧 |

不得在`cache/`保存唯一输入、canonical结果、正式资产或未登记的任意文件。所有`formal/` PA无条件按
正式资产合同保留，禁止作为cache清理；当前实验仍引用的cache PA和无法由冻结输入重建的唯一来源同样
保留。2026-08-14引用审计后，当前实验仍需的10个legacy PA entry（33,919,321,596 bytes）物理保留；
它们只能由artifact布局门禁识别，运行器必须fail-closed视为MISS，首次需要时按schema-v2精确重建。
其余不被当前实验使用、非formal且可由冻结配置/代码/求解器身份重建的legacy cache属于可清理性能层；
清理只影响后续重算，不得改写既有run、manifest或结论。
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
[`common/contracts/artifact_retention.json`](common/contracts/artifact_retention.json)和run manifest
schema v2冻结保留类别；默认类别是`compact`。保留类别在`run_config.json`运行前确定，manifest逐项记录
输出的`retention_role`，不得在看见结果或磁盘占用后改类。现有schema v1历史run保持可读、可复核，
但不得作为新入口绕过保留合同的模板。

| 保留类别 | 适用范围 | 终态必须/允许保留 |
|---|---|---|
|`compact`|功能回归、常规参数运行、失败关闭的默认类别|三件套、冻结输入、代码身份、summary/metrics、canonical粒子终态/事件、必要日志和轻量图；禁止MPH、SIMION PA解阵列和完整轨迹|
|`qualification`|预注册的最终收敛参考点、跨求解器资格参考资产或正式证据源run|允许完整轨迹及求解器原生重型文件；必须在运行前写明保留理由|
|`solver_review`|需要GUI重开、节点/网格审查或供应商缺陷复现的专项诊断|允许完整轨迹及求解器原生重型文件；必须在运行前写明保留理由，不自动获得资格|

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
快照，不回写旧档案中的“当前”。项目README以紧凑`History索引`列出全部扁平Markdown入口，供人和
门禁发现；索引只列链接，不复制每份历史的结论、运行数字或时间线。

新建history中的配置注册表、结果矩阵和正文简称必须应用开发标准的
[科学配置规范名称与结果身份](docs/DEVELOPMENT_STANDARDS.md#科学配置规范名称与结果身份)；既有只读
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

### 新代码分类与一次性实现清理

所有新增代码、配置和辅助脚本在创建前必须归入以下一种生命周期；“先写进去以后再整理”不属于合法
分类：

|类别|允许位置与命名|完成要求|
|---|---|---|
|正式功能|最邻近的`projects/`、`integrations/`或已满足复用条件的`common/`职责目录；名称表达稳定能力，不使用`tmp/new/final/v2/retry`表示状态|接入唯一正式入口或机器注册能力，具备配置/Schema、失败关闭、相称测试、最近文档和artifact合同；默认路径保持向后兼容|
|长期验证|项目`tests/`、公共实现的邻近测试边界或具名验证入口；使用`test_*`或`verify_*`语义|保留可重复输入和明确PASS/FAIL判据；不得被生产入口反向依赖，也不得把一次性打印探针伪装成回归测试|
|一次性实现|默认位于`artifacts/projects/<project>/scratch/<task_id>/`或操作系统临时目录；文件名显式含`tmp_`、`diagnostic_`或`migration_`，不得进入正式源码目录|创建前向用户说明准确路径、名称、用途和删除时点；不得被正式入口、活动配置、文档结论或长期测试引用；使用完、方案放弃、任务中断后恢复或任务结束前必须删除|

一次性实现若显现稳定复用价值，必须先停止沿用，按正式功能或长期验证重新设计、迁入规范位置并补齐
合同、测试和文档；不能仅改名后保留。一次性输出若成为故障根因、科学结论或审计所需证据，须先按
run/artifact合同发布并进入manifest，此后它属于受管理证据而非临时产物；临时代码仍应删除。任务交接
必须分别报告新增的长期代码、创建并清理的一次性实现、保留的证据及未完成清理的明确阻塞。

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

独立粒子轨迹项目统一使用两档粒子数：N=100是功能检查、日常回归和Candidate功能证据的最低标准档；
N=1000是峰形、尾部、束斑/发散分布、损失分布、分辨率及Formal统计的标准档。机器权威为
[`common/contracts/particle_count_policy.json`](common/contracts/particle_count_policy.json)，实现必须在昂贵
求解前调用其校验器。N=100必须是同一种子N=1000母样本的前100行，不能分别抽样。低于100的粒子数
不得成为新项目或新模式的功能、Candidate或Formal基线；专项收敛或集体效应研究可以通过版本化项目合同
增加具名粒子数，但不能改写这两档含义。历史小N运行只保留为历史证据，不构成当前入口。

质量分辨率统一为 `R=m/FWHM_m`；窄峰时间域等价式是 `R=T/(2*FWHM_t)`。`2.3548×sigma`
只有在峰形近似高斯时才可作为 FWHM 代理。比较 COMSOL 与 SIMION 时至少统一几何、粒子表、
有效检测面、命中定义、FWHM 算法和样本量，并分别检查网格收敛与统计不确定度。详细方法写入
`docs/VALIDATION_METHODS.md`，项目数值写入项目 PROJECT。

## 工具链与执行入口

PowerShell Core 7（`pwsh`）是仓库唯一受支持的PowerShell运行时。公开根入口必须通过公共preflight
失败关闭地验证当前宿主为Core 7，禁止回退到Windows PowerShell 5.1。Python等非PowerShell边界启动
PowerShell时必须使用`pwsh`；PowerShell脚本内部继承当前宿主，不得另行选择或启动第二套PowerShell。

### 分层门禁

所有门禁使用Python 3.11；本机默认使用`.venv`，GitHub Workflow注入干净运行器的Python路径。门禁不执行
商业求解器、CAD或正式资产门禁。项目发现、设计请求校验和求解器中立规划入口见
[`common/contracts/README.md`](common/contracts/README.md)。

|层级|入口|何时运行|范围|
|---|---|---|---|
|L1 changed-scope|`common/verify_changed.ps1`|每次提交、push和日常参数探索|始终先运行仓库卫生与受管文本字节门禁；全部改动均为Markdown时再运行文档门禁并结束。其他改动只运行活动项目、其直接公共依赖及必要静态合同。RF四极杆或其直接公共依赖变化时，先运行生成物`Freshness`快速失败，随后以已验证前置条件运行无求解器的`Core`合同；输出`RUN/SKIP`原因或显式`DOCUMENTATION_ONLY`快速路径|
|L2 repository integration|`common/verify_repository_integration.ps1`|修改门禁实现、项目注册表、机器合同语义、共享运行机制或跨项目接口时；GitHub手动触发|在长测试前检查RF四极杆生成物`Freshness`，随后从统一门禁目录发现并运行全部活动项目、integration和公共静态回归；四极杆`Static`复用已通过的Freshness，不重复生成物检查。纯文档和规则文字调整不触发|
|L3 project evidence|各项目`verify_project.ps1`的Candidate/Formal级别|Candidate、Formal、promotion或真实物理资产变化时|商业求解、GUI/CAD复验、冻结输入、manifest和物理证据链|

`common/gate_catalog.json`是L1路径路由、依赖等级、阶段前置关系和L2成员身份的唯一机器目录；项目或
integration新增公开门禁时必须注册，目录与文件系统不一致即失败。仓库只保留
`common/verify_changed.ps1`这一个L1入口，不提供旧名称兼容脚本。`.github/workflows/lightweight-gate.yml`
在push只运行L1；L2仅可由`workflow_dispatch`人工启动，不对pull request自动运行全仓回归。

L1的`-PlanOnly`使用同一目录先给出`stdlib`或`locked`依赖等级；GitHub对只需标准库的文档和门禁
合同范围跳过完整科学Python环境安装，任何未明确分类、项目注册表、Python lint、项目/集成、依赖声明或
FullScope均失败关闭为`locked`。本地并发默认为`min(8, logical_processors)`，可用
`-MaxConcurrency 1..32`显式覆盖；GitHub托管runner固定为2。并行阶段即时报告进程启动与完成，随后按
稳定顺序回放完整日志。2026-08-02审计基线为本机L2四路209.5秒、八路183.1秒；远端一次标准库范围
push的73秒中45秒用于完整依赖安装。该次push包含项目注册表变化，按新规则仍属于`locked`；45秒节省
适用于纯文档或其他完整`stdlib`范围。L2仍是显式全仓审计，不得成为纯文档提交的默认门禁。

数值探索参数可在活动项目的声明范围内自由修改：L1只校验该项目的参数schema、单位/范围、resolved合同和
必要输入生成，不自动启动商业求解器，也不检查无关项目。若改变几何、电压、粒子源、网格、RF相位或跨项目
接口，旧Candidate/Formal证据不再适用；只有在要声明新结果时才运行该项目相应的L3物理链。

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
`pyproject.toml`声明、`requirements-lock.txt`冻结，并安装在不入Git的`.venv/`。跨目录Python入口从
仓库根使用`python -m <module>`运行，禁止由各脚本重复修改`sys.path`。单次反射oa-TOF入口见
`projects/single_reflection_oa_tof_mass_analyzer/analysis/README.md`。

## Git 规则

仓库根是 `simulation_repo/`，远程公开仓库为
`https://github.com/Bibibabibobi96/mass_spectrometry.git`。提交只包含一个可审阅主题；使用明确
路径或 `git add -p`，不习惯性执行 `git add .`。提交前运行：

```powershell
git status --short --branch
git diff --check
git diff --stat
.\common\verify_changed.ps1
```

确认没有 MPH、PA/IOB、结果、日志或一次性脚本进入暂存区。不得强制推送、改写远程历史或
覆盖/夹带任务开始前的无关改动；Agent何时自主提交和推送只由[`AGENTS.md`](AGENTS.md)定义。

每个提交都使用简洁、可检索的标题，并提供与改动复杂度和风险相称的正文；不再允许只有标题的提交。
正文至少说明修改目的、关键结果或行为变化、实际验证，以及必要的限制或未完成事项，使未来维护者
无需查阅聊天记录即可理解提交。正文不逐文件复述diff，也不以无信息量模板凑长度；不设机械字数下限。

## 任务完成定义

一次变更只有在源码、机器契约、最近的权威文档、路径引用和相称测试一致后才算完成。验证证据必须
足以还原目标、输入、唯一变量、结果、判据和产物，但不保存无关常规日志；正式几何还必须满足
COMSOL GUI和SolidWorks同步门禁。Agent面向用户的报告顺序与篇幅只由[`AGENTS.md`](AGENTS.md)定义。

文档变更还应运行`common/verify_documentation.ps1`，检查唯一H1、标题层级、相对链接、历史归档
标记和项目入口完整性。自动门禁只验证可机器判断的结构；技术结论是否放在正确权威层仍需审阅。
