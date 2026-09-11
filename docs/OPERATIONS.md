# 工具链与仓库操作

返回[仓库入口](../README.md)。从仓库根`simulation_repo/`执行本页命令；项目输入和资格见项目README与PROJECT。命令中的尖括号是必须替换的占位符。

## 通用验证口径

独立粒子轨迹项目的正式证据统一使用三档粒子数：N=100是功能检查、日常回归和Candidate功能证据的最低标准档；
N=1000是峰形、尾部、束斑/发散分布、损失分布与标准分辨率统计档；N=5000是高统计档。机器权威为
[`common/contracts/particle_count_policy.json`](../common/contracts/particle_count_policy.json)，实现必须在昂贵
求解前调用其校验器。探索运行可使用任意正整数粒子数，并必须在输入与结果中记录实际数目；较小标准样本必须是同一种子较大母样本的前缀，不能分别抽样。低于100的粒子数不得成为新项目或新模式的功能、Candidate或Formal基线；专项收敛或集体效应研究可以通过版本化项目合同
增加具名粒子数，但不能改写这些档位的含义。历史小N运行只保留为历史证据，不构成当前入口。

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
[`common/contracts/README.md`](../common/contracts/README.md)。

| 层级 | 入口 | 使用条件 |
|---|---|---|
| L1 改动范围 | `common/verify_changed.ps1` | 每次提交、push及日常参数探索 |
| L2 仓库集成 | `common/verify_repository_integration.ps1` | 门禁、注册表、机器语义、共享运行或跨项目接口改变 |
| L3 项目证据 | 项目 `verify_project.ps1` 的 Candidate/Formal 级别 | 资格、promotion或真实物理资产变化 |

L1 始终先查仓库卫生与受管文本字节。纯 Markdown 改动运行文档检查后走
`DOCUMENTATION_ONLY` 快速路径；其余只运行活动项目、直接公共依赖和必要静态合同，报告 RUN/SKIP 原因。
四极杆或其直接公共依赖变化时先查生成物 Freshness，再复用前置结果执行无求解器 Core 合同。

L2 在长测试前检查四极杆 Freshness，然后覆盖全部活动项目、integration 和公共静态回归；四极杆
Static 复用该前置检查。纯文档和规则文字调整不触发 L2，GitHub 仅手动触发。
L3 才核验商业求解、GUI/CAD、冻结输入、manifest 和物理证据链。


`common/gate_catalog.json`是L1路径路由、依赖等级、阶段前置关系和L2成员身份的唯一机器目录；项目或
integration新增公开门禁时必须注册，目录与文件系统不一致即失败。仓库只保留
`common/verify_changed.ps1`这一个L1入口，不提供旧名称兼容脚本。`.github/workflows/lightweight-gate.yml`
在push只运行L1；L2仅可由`workflow_dispatch`人工启动，不对pull request自动运行全仓回归。

L1的`-PlanOnly`使用同一目录先给出`stdlib`或`locked`依赖等级；GitHub对只需标准库的文档和门禁
合同范围跳过完整科学Python环境安装，任何未明确分类、项目注册表、Python lint、项目/集成、依赖声明或
FullScope均失败关闭为`locked`。本地并发默认为`min(8, logical_processors)`，可用
`-MaxConcurrency 1..32`显式覆盖；GitHub托管runner固定为2。并行阶段即时报告进程启动与完成，随后按
稳定顺序回放完整日志。历史耗时测量见[门禁审计](history/20260802__gate-system-audit.md)；
L2用于显式全仓审计，纯文档提交不默认运行L2。

除下述只读文档结构模式外，本机公开门禁与真实SIMION/COMSOL运行共享一个Windows命名主机执行租约。外层入口先获得租约，子门禁
继承该租约；另一类工作等待并报告持有PID与等待时间。租约只协调两类顶层负载，不改变门禁自身的并行
度或SIMION内部的资源调度；正常结束显式释放，宿主崩溃时由Windows自动释放。

真实求解器入口在发布终态 manifest 后，向共享租约报告 `success`、`failed` 或 `interrupted`；仅持有
`SIMION`或`COMSOL`租约的顶层运行因此播放一次本机系统提示音（成功为三音上行完成提示，其余为 Hand）。提示不属于科学
输入、run identity 或证据，声卡不可用不能改变终态；设置进程环境变量 `SIMULATION_COMPLETION_SOUND=off`
可静默。批次、45 秒资源观测、重试、门禁和继承租约不得单独提示。

数值探索参数可在活动项目的声明范围内自由修改：L1只校验该项目的参数schema、单位/范围、resolved合同和
必要输入生成，不自动启动商业求解器，也不检查无关项目。若改变几何、电压、粒子源、网格、RF相位或跨项目
接口，旧Candidate/Formal证据不再适用；只有在要声明新结果时才运行该项目相应的L3物理链。

### 文档结构检查

仅审查文档结构时运行 `common/verify_documentation.ps1 -StructureOnly`：检查活动本地链接、中文与页内锚点、格式和历史归档完整性，不取得主机执行租约、不运行外部工作区卫生。默认模式与 L1 仍执行完整卫生检查并遵守租约。

`.\.venv\Scripts\python.exe -m common.documentation_links --inventory-json`输出逐文件清单。既有只读历史的失效链接只诊断，新历史断链仍阻断；长文、重复段落和无入链只是人工审查提示。相对 artifact 路径允许外部载荷不在当前机器上，远程文献和科学结论需另行核验。

### artifact结构门禁

本机存在artifacts时运行：

```powershell
.\.venv\Scripts\python.exe -m common.contracts.verify_artifact_layout ..\artifacts\projects
```

它检查目录合同、`run_id/archive_id`、三件套和manifest身份；项目 artifact 默认不读取大二进制，
但已注册的公共 SIMION PA-family cache 会对其当前 generation 的完整 payload 做字节级验证。因此它适合
每次产物整理后运行，但不放进不具备本机artifacts的GitHub Workflow。命名合同单元测试仍属于轻量门禁。

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
