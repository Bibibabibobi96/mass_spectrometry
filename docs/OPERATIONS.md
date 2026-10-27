# 工具链与仓库操作

返回[仓库入口](../README.md)。从仓库根`simulation_repo/`执行本页命令；项目输入和资格见项目README与PROJECT。命令中的尖括号是必须替换的占位符。

## 按任务选择

| 当前任务或症状 | 入口与下一步 |
|---|---|
| 确认宿主、解释器与商业工具版本 | [工具链与执行入口](#工具链与执行入口)、[正式工具链基线](#正式工具链基线) |
| 查看要跑的检查或执行L1/L2 | [分层门禁](#分层门禁)，先用`-PlanOnly`检查路由 |
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

### 分层门禁

所有门禁使用Python 3.11；本机默认使用`.venv`，GitHub Workflow注入干净运行器的Python路径。门禁不执行
商业求解器、CAD或正式资产门禁。项目发现、设计请求校验和求解器中立规划入口见
[`common/contracts/README.md`](../common/contracts/README.md)。

| 层级 | 入口 | 使用条件 |
|---|---|---|
| L1 改动范围 | `common/verify_changed.ps1` | 每次提交、push及日常参数探索 |
| L2 仓库集成 | `common/verify_repository_integration.ps1` | 门禁、注册表、机器语义、共享运行或跨项目接口改变 |
| L3 项目证据 | 项目 `verify_project.ps1` 的 Candidate/Formal 级别 | 资格、promotion或真实物理资产变化 |

L1 始终先查仓库卫生与受管文本字节。纯 Markdown 及根、项目或integration的
`docs/history/<同名载荷目录>/*.txt`单层只读快照改动，运行文档检查后走`DOCUMENTATION_ONLY`快速路径；
快照清单、字节和SHA检查仍执行。活动配置、源码及其他文本不获该豁免；其余只运行活动项目、直接公共依赖和必要静态合同，报告 RUN/SKIP 原因。
触发多极杆发布或变体门禁时，先由统一项目入口执行`Freshness -StructuralVariant All`，检查三种结构的
设计发布及四极专属派生物。L1按改动范围选择四极`Core`、六极／八极`Static`，三者均复用该发布前置结果。
统一`verify_project.ps1`的`Core`停在所选结构的无求解器设计合同；`Static`再运行所选变体的Python回归并
解析全项目PowerShell。共享领域测试由目录中的独立阶段执行，不由变体`Core`或`Static`替代。

L2在长测试前完成全多极杆`Freshness`，之后覆盖全部活动项目、integration和公共静态回归；四／六／八极
均执行`Static`并复用该前置结果。纯文档和规则文字调整不触发L2，GitHub仅手动触发。
L3才核验商业求解、GUI/CAD、冻结输入、manifest和物理证据链。

历史迁位清单会核对固定源提交中的Git blob，因此克隆必须能读取这些源提交；L1/L2的CI checkout均保留完整
历史。浅克隆缺少源对象时须先补取历史，再进行身份校验，不能跳过原始字节验证。


阶段目录、路径路由与前置关系统一由[`common/gate_catalog.json`](../common/gate_catalog.json)定义。
先查看本次计划，再按需执行：

```powershell
.\common\verify_changed.ps1 -PlanOnly
.\common\verify_changed.ps1
# 共享机制、注册表或跨项目合同变化完成后：
.\common\verify_repository_integration.ps1
```

计划报告`stdlib`或`locked`依赖等级；未知或涉及项目实现的范围使用完整锁定环境。门禁输出逐阶段
RUN／SKIP原因、启动与完成状态；`LOG_PATH`定位执行中的完整日志，结束时按稳定顺序回放输出。
本地并发默认保守自动选择，可用`-MaxConcurrency`显式降低；资源调度器仍决定实际准入。
GitHub的push执行L1，L2通过`workflow_dispatch`显式启动。只有所有适用阶段成功才表示该层门禁通过；
超时、环境失败与科学求解失败分别处理。

结束后检查`GATE_DIAGNOSTICS`：`CLEANED`表示临时日志已清理，`RETAINED`表示日志目录仍在。
失败时先读取原`LOG_PATH`和`group_failure.log`，原请求JSON保留用于核对阶段参数。
复核完成后dot-source `. .\common\parallel_gate_support.ps1`，执行该次输出的
`GATE_DIAGNOSTICS_CLEANUP`命令；它包含精确目录和期望前缀，不能换成广泛删除TEMP。
失败证据不按年龄自动清理；成功组若清理不全，也会报告`RETAINED`。

新增阶段、修改路由或排查调用器时，再读[门禁编排维护说明](../common/README.md#门禁编排)；
日常执行无需通读其进程、编码和CI内部实现。

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

仅审查文档结构时运行 `common/verify_documentation.ps1 -StructureOnly`：检查活动本地链接、中文与页内锚点、格式和历史归档完整性，不取得主机执行租约、不运行外部工作区卫生。默认模式与 L1 仍执行完整卫生检查并遵守租约。

`.\.venv\Scripts\python.exe -m common.documentation_links --inventory-json`输出逐文件行数、字符数与诊断。
字符数基于UTF-8解码、换行规范化后的文本，不是token数。既有只读历史的失效链接只诊断，新历史断链仍阻断。
长文、重复段落、无入链、表格列数不齐和空单元格是人工审查提示；合法空值不能仅凭检查器判断为遗漏。
相对artifact路径允许外部载荷不在当前机器上，远程文献和科学结论需另行核验。
结构PASS不证明新旧指令一致或阅读范围完整；文档升级还按[任务检索验收](REPOSITORY_ARCHITECTURE.md#按任务读取与局部检索)
核对当前答案、必需约束和失效路径。

### artifact结构门禁

清理时先运行卫生门禁检查源码与工作区顶层，再按[生命周期](LIFECYCLE.md#保留与清理策略)盘点产物、
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

它检查目录合同、`run_id/archive_id`、三件套和manifest身份；项目 artifact 默认不读取大二进制，
但已注册的公共 SIMION PA-family cache 会对其当前 generation 的完整 payload 做字节级验证。因此它适合
每次产物整理后运行，但不放进不具备本机artifacts的GitHub Workflow。命名合同单元测试仍属于轻量门禁。

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
.\common\verify_changed.ps1
```

独立工作树复用其他checkout的Python 3.11时，提交前将该解释器目录置于当前进程PATH首位；
提交钩子依次选择本checkout的`.venv`和PATH中的`python`并验证版本。

确认没有 MPH、PA/IOB、结果、日志或一次性脚本进入暂存区。不得强制推送、改写远程历史或
覆盖/夹带任务开始前的无关改动；Agent何时自主提交和推送只由[`AGENTS.md`](../AGENTS.md)定义。

每个提交都使用简洁、可检索的标题，并提供与改动复杂度和风险相称的正文；不再允许只有标题的提交。
正文至少说明修改目的、关键结果或行为变化、实际验证，以及必要的限制或未完成事项，使未来维护者
无需查阅聊天记录即可理解提交。正文不逐文件复述diff，也不以无信息量模板凑长度；不设机械字数下限。

## 任务完成定义

一次变更只有在源码、机器契约、最近的权威文档、路径引用和相称测试一致后才算完成。验证证据必须
足以还原目标、输入、唯一变量、结果、判据和产物，但不保存无关常规日志；正式几何还必须满足
COMSOL [GUI和SolidWorks同步门禁](REPOSITORY_ARCHITECTURE.md#gui-与-cad-门禁)。Agent面向用户的报告顺序与篇幅只由[`AGENTS.md`](../AGENTS.md)定义。

文档变更还应运行`common/verify_documentation.ps1`，检查唯一H1、标题层级、相对链接、历史归档
标记和项目入口完整性。自动门禁只验证可机器判断的结构；技术结论是否放在正确权威层仍需审阅。
