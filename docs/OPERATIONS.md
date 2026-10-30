# 工具链与仓库操作

返回[仓库入口](../README.md)。从仓库根`simulation_repo/`执行本页命令；项目输入和资格见项目README与PROJECT。命令中的尖括号是必须替换的占位符。

## 按任务选择

| 当前任务或症状 | 入口与下一步 |
|---|---|
| 确认宿主、解释器与商业工具版本 | [工具链与执行入口](#工具链与执行入口)、[正式工具链基线](#正式工具链基线) |
| 软件验证范围和科学证据 | [职责与入口](#软件验证与科学证据)，PlanOnly可选 |
| 门禁或求解器等待资源 | [主机资源调度](#主机资源调度)，核对owner、阶段与日志 |
| 文档链接、锚点、索引或历史检查失败 | [文档结构检查](#文档结构检查) |
| 容量、产物目录或保留合同失败 | [artifact结构门禁](#artifact结构门禁)，按报告中的准确对象排查 |
| COMSOL无法连接或启动 | [统一COMSOL入口](#comsol-r2025b-执行入口)，按报告区分环境、连接和模型错误 |
| 求解已完成但分析或发布失败 | [已有阶段恢复](DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)，先确认已有原始结果及身份 |
| 提交、推送与交接 | [Git规则](#git-规则)、[任务完成定义](#任务完成定义) |

## 通用验证口径

独立粒子轨迹项目的正式证据统一使用三档粒子数：N=100是功能检查、日常回归和Candidate功能证据的最低标准档；
N=1000是峰形、尾部、束斑/发散分布、损失分布与标准分辨率统计档；N=5000是高统计档。机器权威为
[`common/contracts/particle_count_policy.json`](../common/contracts/particle_count_policy.json)，实现必须在昂贵
求解前调用其校验器。探索运行可使用任意正整数粒子数，并必须在输入与结果中记录实际数目；较小标准样本必须是同一种子较大母样本的前缀，不能分别抽样。低于100的粒子数不得成为新项目或新模式的功能、Candidate或Formal基线；专项收敛或集体效应研究可以通过版本化项目合同
增加具名粒子数，但不能改写这些档位的含义。历史小N运行只保留为历史证据，不构成当前入口。

质量分辨率统一为 `R=m/FWHM_m`；窄峰时间域等价式是 `R=T/(2*FWHM_t)`。`2.3548×sigma`
只有在峰形近似高斯时才可作为 FWHM 代理。比较 COMSOL 与 SIMION 时至少统一几何、粒子表、
有效检测面、命中定义、FWHM 算法和样本量，并分别检查网格收敛与统计不确定度。详细方法写入
`docs/science/VALIDATION_METHODS.md`，项目数值写入项目 PROJECT。

## 工具链与执行入口

门禁的实际宿主、验证范围与失败记录按固定源码归档，见[审计索引](AUDITS.md)。

PowerShell Core 7（`pwsh`）是仓库唯一受支持的PowerShell运行时。公开根入口必须通过公共preflight
失败关闭地验证当前宿主为Core 7，禁止回退到Windows PowerShell 5.1。Python等非PowerShell边界启动
PowerShell时必须使用`pwsh`；PowerShell脚本内部继承当前宿主，不得另行选择或启动第二套PowerShell。

### 软件验证与科学证据

软件验证统一使用`common/verify.ps1`、Python 3.11、现有catalog和公共资源调度。
一次命令自动选择、执行并汇总；`-PlanOnly`是可选预览，不是正常运行的手工前置。

| 范围或任务 | 正常入口 | 实际含义 |
|---|---|---|
| 改动软件 | `common/verify.ps1 -Scope Changed` | 从Git差异或显式ChangedPath选择真实owner及消费者 |
| 指定软件owner | `common/verify.ps1 -Scope Owner -Owner <owner>` | 该owner的完整适用软件职责 |
| 完整软件 | `common/verify.ps1 -Scope Repository` | 全部适用软件职责和项目回归 |
| 科学运行 | 项目或integration公开workflow | 本次输入、工具、资源和资产准入，执行声明动作 |
| 科学验证或发布 | 模型、问题和资产的具名入口 | 相应原生、数值、GUI/CAD及资格证据 |

范围、测试性质、模型、工具成本和科学资格分别记录。内部Core／Static保留其实际集合，
不表示物理精度；Candidate／Formal只保留项目内真实的资格或发布用途。
Changed的FullScope保留原Core／Static选择，不等于Repository。不支持的owner或能力在选择阶段明确拒绝。

普通参数探索不自动执行软件回归或整套跨求解器资格。源码、合同及公共默认行为改变才选择相称软件范围，
相关物理输入和结论变化才触发科学验收。

父进程规划一次，子任务直接消费同轮解析请求。公共合同按实际owner选择，短分析模块分stdlib／locked合批。
中央Ruff、注册表及RF公共PS解析各承担唯一职责；MR保留必要PS／Lua前置，纯Ruff集成前置已撤销。
独立项目入口默认完成必要检查。Changed／Owner首错停新派发，Repository继续独立诊断；
真实前置失败仍阻断消费者，健康任务自然收尾。
CI 同分支运行沿现有 concurrency group 串行，新推送不取消已启动的验证；尚未启动的待运行请求仍可由更新请求替代。
该行为采用 [GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)；
取消或未完成的旧轮不计为通过，最终源码仍须取得相应范围的完整结果。

参考环境预算：owner/窄范围1–3分钟，较复杂≤5分钟，宽改动≤10分钟，完整软件范围争取15分钟。
超预算须定位主要重复与必要成本，不靠漏测、改名或隐藏开销达标；它不是原生求解的强杀超时。

```powershell
.\common\verify.ps1
.\common\verify.ps1 -Scope Owner -Owner orthogonal_accelerator
.\common\verify.ps1 -Scope Repository
# 可选预览
.\common\verify.ps1 -ChangedPath projects/orthogonal_accelerator/analysis/component_focus_analysis.py -PlanOnly
```

职责与依赖只在[`common/gate_catalog.json`](../common/gate_catalog.json)维护。普通验证不认证全部Git历史，
实际历史改动定向检查，整档核验仅显式AuditHistory；只获取实际base/head或档案审计需要的源提交。

SummaryPath保存范围、命令、环境、状态、原因、日志和慢测试计时。完整公开命令墙钟由外层单调时钟
在启动前到实际退出测量，另列summary／stage区间。软件通过不代表科学PASS，未执行和阻断分别报告。
失败诊断保留请求及group_failure.log；复核后使用该次输出的精确GATE_DIAGNOSTICS_CLEANUP，
不广泛删除TEMP、不按年龄删失败证据。编排细节按需查[公共实现](../common/README.md#门禁编排)。

### 主机资源调度

门禁和商业运行通过同一公共入口申请资源；重、轻阶段及额度只由
[`host_resource_policy.json`](../common/host_resource_policy.json)管理。资源等待时先查询状态：

```powershell
. .\common\host_execution_lease.ps1
Get-HostResourceStatus
```

结合owner、PID与创建身份、阶段日志和实际进展定位等待原因。低CPU、无新日志或预算告警本身不是
终止条件；不得删除账本、另设账本或绕过准入。停止和恢复遵循
[进程与失败规则](DEVELOPMENT_STANDARDS.md#6-外部进程失败与日志)。

默认账本为同级`artifacts/common/host_resources.sqlite3`。不同父目录的工作树必须显式共用同一绝对
账本；部署、阶段切换、子进程登记与释放的完整合同见[主机资源实现](../common/README.md#主机资源实现)。
本机资源许可与artifact容量保护分别生效；资源可用不代表输出容量已获准。

新运行通过项目公开入口执行，不手动管理求解器连接或私建并发器。独立粒子与耦合求解的区别见
[调度规则](DEVELOPMENT_STANDARDS.md#独立粒子与耦合求解的调度)，已完成阶段的复用见
[恢复规则](DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)。变更几何、源或数值设置后，旧资格不能自动沿用。
真实求解器顶层终态会播放一次本机提示音；设置进程环境变量`SIMULATION_COMPLETION_SOUND=off`可静默，
提示是否成功不改变科学终态。

### 文档结构检查

仅检查活动入口、本地链接和页内锚点时运行`common/verify_documentation.ps1 -StructureOnly`。
文案、标题语言、排版、篇幅和本地额外目录不作为提交硬门；文档检查不重复调用工作区卫生。
普通软件验证不重新认证全部Git历史；实际历史改动用`-ChangedPath`定向核验，明确档案审计用`-AuditHistory`。

`.\.venv\Scripts\python.exe -m common.documentation_links --inventory-json`输出逐文件行数、字符数与诊断。
字符数基于UTF-8解码、换行规范化后的文本，不是token数。既有只读历史的失效链接只诊断，新历史断链仍阻断。
长文、重复段落、无入链及排版审查仅在显式维护任务中输出，不阻断普通提交。
相对artifact路径允许外部载荷不在当前机器上，远程文献和科学结论需另行核验。
结构PASS不证明新旧指令一致或阅读范围完整；文档升级还按[任务检索验收](REPOSITORY_ARCHITECTURE.md#按任务读取与局部检索)
核对当前答案、必需约束和失效路径。

### artifact结构门禁

清理时核对生成资产未误入Git，再按[生命周期](LIFECYCLE.md#保留与清理策略)盘点产物、
活动引用和相关系统临时目录。`reconcile_artifact_capacity.py --artifact-root ..\artifacts`只执行
ledger-only日常startup/maintenance。首次校准或台账失准时，必须显式调用
`legacy_capacity_calibration.py --workspace-root <simulation_repo>`；它一次性统计artifact根、
仓库`scratch/`和`generated/`，而日常启动绝不遍历这些目录。`legacy_capacity_backfill.py`
只保留历史发现／恢复，不能作为日常准入或覆盖容量水位。
未核对候选不得追加`--apply`。清理收据统一放在
`artifacts/common/capacity_disposal_receipts/`，不留在工作区顶层。主机资源许可不替代容量保护租约，
调用与保护参数见[公共容量合同](../common/contracts/README.md#运行身份与生命周期)。

本机存在artifacts时运行：

```powershell
.\.venv\Scripts\python.exe -m common.contracts.verify_artifact_layout ..\artifacts\projects
```

它默认检查目录合同、`run_id/archive_id`、三件套、manifest身份和文件类型/大小；公共SIMION缓存也不默认
读取完整PA。需核对载荷内容时显式增加`--verify-hashes`，该标志同时覆盖公共缓存；metadata通过不代表
载荷内容已验证。显式`--cache-entry`是冻结输入的消费边界，始终完整核对哈希，不受该默认范围影响。
因此结构检查适合每次产物整理后运行，但不放进不具备本机artifacts的GitHub Workflow；命名合同单元测试仍属于轻量门禁。

公共根识别既有`execution_aliases`与具名当前`host_resources.sqlite3`：alias沿原owner校验junction目标，
不递归遍历目标；数据库只检查具名普通文件，不把动态大小当内容身份。历史备份和一次性任务目录
仍须按其owner受管归档或处置，不能为使结构门禁通过而一并放行。

公共 PA-family generation 是不可变发布介质，不是求解器可写工作目录。原生 family 成员及其物化副本
不能交给供应商进程；已发布 ordinary standalone PA 的受护直接只读消费与必要独立副本，统一遵循
[长PA输入路径](tools/SIMION_REFERENCE.md#长pa输入路径)。不得用Junction或硬链接替代该隔离边界。
公共 `New-ShortPaCopy` 对父目录含 `cache_manifest.json` 的来源强制要求manifest `bytes + SHA-256`，
缺少任一项即失败。Windows 大 PA 若普通缓冲读取与 `/J` 持久读取分叉，不得对发布源 ReadWrite/Flush；
应先用 manifest-bound `/J` 快照验证，并把旧文件对象隔离后以同字节的新对象原子替换，禁止原位修补。

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
.\common\verify.ps1
```

独立工作树复用其他checkout的Python 3.11时，提交前将该解释器目录置于当前进程PATH首位；
提交钩子依次选择本checkout的`.venv`和PATH中的`python`并验证版本。

确认没有 MPH、PA/IOB、结果、日志或一次性脚本进入暂存区。不得强制推送、改写远程历史或
覆盖/夹带任务开始前的无关改动；Agent何时自主提交和推送只由[`AGENTS.md`](../AGENTS.md)定义。
提交钩子对Git索引中的检查器与受管源码执行开发标准硬检查；未暂存的修复不能证明待提交版本正确。
消费者可达性审计由`common/verify_development_standards.py --audit-consumers`显式请求，默认不执行。

每个提交都使用简洁、可检索的标题，并提供与改动复杂度和风险相称的正文；不再允许只有标题的提交。
正文至少说明修改目的、关键结果或行为变化、实际验证，以及必要的限制或未完成事项，使未来维护者
无需查阅聊天记录即可理解提交。正文不逐文件复述diff，也不以无信息量模板凑长度；不设机械字数下限。

## 任务完成定义

一次变更只有在源码、机器契约、最近的权威文档、路径引用和相称测试一致后才算完成。验证证据必须
足以还原目标、输入、唯一变量、结果、判据和产物，但不保存无关常规日志；正式几何还必须满足
COMSOL [GUI和SolidWorks同步门禁](REPOSITORY_ARCHITECTURE.md#gui-与-cad-门禁)。Agent面向用户的报告顺序与篇幅只由[`AGENTS.md`](../AGENTS.md)定义。

文档变更按实际范围检查活动入口、本地链接和锚点；历史来源仅在实际改动或显式档案审计时核验。自动门禁只验证可机器判断的结构；技术结论是否放在正确权威层仍需审阅。
