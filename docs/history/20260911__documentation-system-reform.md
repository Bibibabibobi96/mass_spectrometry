# 2026-09-11 文档体系整治与交付审计

DOC_STATUS: ARCHIVED_READ_ONLY

本记录描述本次文档整治，不承担持续规则或项目当前状态。入口见[仓库 README](../../README.md)，
维护规则见[架构](../REPOSITORY_ARCHITECTURE.md)、[生命周期](../LIFECYCLE.md)与[操作指南](../OPERATIONS.md)。

## 范围与证据口径

任务起点为 `45a6741550aae5cbb009615896d16ef6d20618a2` 上的共享工作树。起点清单包含 229 份 Markdown：
102 份非 history 文档、127 份 history 文档。全量覆盖入口、规范、公共实现、九项目、集成、理论、发表材料、
日期审计与机器发现入口。另核对工作区发现入口和五份官方 PDF 的索引；没有改写官方手册或重新认证外部论文。

工作树在任务开始前已含 MRTOF、SIMION 缓存、容量治理、集成与加速器代码及文档改动。
文档修订保留这些事实和负结果，不能把共享工作树总差异或仿真进展归功于本任务。

Agent 0 负责架构、规范、集成文档和裁决；Agent 1 负责 oaTOF 与发表材料；Agent 2 负责其他七项目和
公共 SIMION 整理；Agent 3 负责通用参考、理论及协调获准的 MRTOF 文档；Agent 4 负责文档检查、测试迁移与独立复核。
外部 MRTOF agent 仍拥有科学代码、配置和实验，并在终态边界逐次移交文档写权及门禁窗口。

## 主要问题与处置

| 问题 | 已实施的处置 |
|---|---|
| 根 README 同时承担导航、规范和状态 | 缩成任务入口；完整规则分别迁入架构、生命周期、操作指南 |
| README、PROJECT、软件说明重复维护结果 | 入口只导航；当前状态留 PROJECT／INTEGRATION；操作与历史各自归位 |
| 规则散落、互相指回失效位置 | 明确规范、机器合同、证据的不同职责，补 integration 写入路由并更新引用 |
| 过期完成事项仍留开放任务 | 核对实现与阶段合同，将“未实现”收窄为真正未完成的证据验收 |
| 历史失效结果被写成当前成功 | 保留失败链，撤下已被合同或缺陷记录否定的当前声明 |
| 论文证据矩阵漂移 | C1 历史仅 DEVELOPMENT_ONLY；C3 区分 N=100 平台与未完成独立参考 |
| 操作模板无法直接使用 | 修正公共 COMSOL 启动器、仓库工作目录、Python 环境、新输出身份和 producer 映射键 |
| 软件能力、物理资格混淆 | 区分配置校验、实现完成、真实执行、数值／统计证据及 Candidate／Formal |
| 长表、长路径和过深标题 | 缩窄比较表，长解释移正文；长推导加导航，实验治理提升标题层级 |
| 日期流水账占用当前入口 | 按已闭合主题归档，历史索引折叠；保留旧路径路由和真实消费者 |
| 门禁只能检查简单链接且锁死排版 | 增加中文／页内／图片／reference 链接与锚点检查，结构模式不抢求解租约 |
| 只做格式检查不能解释余项 | 长文、重复段落、孤立入口作为审查提示逐项裁决，不机械拒绝合理文档 |

整治没有修改科学输入、放宽物理阈值、重算历史结果或提升项目资格。MRTOF 机器成熟度的陈旧描述、
全仓测试中暴露的在途科学代码问题均交原工作流处理，不用文档重写掩盖。

## 保留与减量决策

不以文件总数单独判断维护成本。独立推导、预注册合同、交付包内检查单和不可变历史仍需保留；
普通编辑历史交给 Git，只有需要解释结果或迁移的材料建立具名归档。

- `SIMION_REPRODUCTION_PARAMETERS.md` 被正式交付脚本复制且被源码冻结合同消费，保留独立检查单。
- oaTOF 旧加速器理论入口被机器候选合同及历史消费，保留短路由。
- 两稿旧 scope、旧 Fly 审计、MRTOF 旧 CAD 审计保留短迁移入口，原正文不再承担当前权威。
- 日期化 prior-art 与硬限制审计就地明确冻结范围，避免仅为目录形式额外复制一组文档。
- 长理论保留连贯符号、假设与推导；本次没有逐公式重新证明全部理论或重新检索全部外部文献。
- Skill 由机器发现机制消费，CLAUDE 使用专用导入语法；无 Markdown 入链不等于废弃。
- 六／八极杆重复段落为短导航，不包含重复规范或状态；生命周期 scratch 提示为合法路径示例。

## 验证边界

结构检查覆盖活动文件、中文及页内锚点、代码围栏、唯一 H1、历史索引与载荷完整性。
既有历史旧链接只诊断；新增历史断链阻断。外部 artifact 可以不在当前机器上，因此链接通过不等于
外部载荷哈希已复核。远程链接与科学真实性不是此检查器的能力。

本次抽查根入口、操作指南、集成参数表与独立加速器理论的本地 HTML 渲染；发现并将集成五列表
和门禁长表改为三列加正文。该预览使用 PowerShell Markdown 转换与浏览器，确认的是表格、正文和导航布局，
不等同于 GitHub 数学渲染或全部公式复证。四份临时 HTML、临时服务与浏览器页均已清理。


## 验收结果与提交边界

本主题 L1 通过：文档、工作区卫生、受管文本字节、开发标准、Ruff，以及文档 10 例、门禁合同 42 例、公共合同 269 例（1 skip）。
独立 focused 37 例通过；文档／粒子数迁移 9 例、理论模块 7 例通过。部分用例重复覆盖，不把这些数相加冒充独立总数。
最终工作树结构检查：243 份 Markdown、0 个本地链接／锚点错误、16 项人工审查提示，均已有保留判断。

首轮 L2 未通过，六个失败阶段共执行 2156 个 unittest，12 failures、1 error、5 skips；此数只统计失败阶段，不是全仓总测试数。
其中三项文档迁移断言已在本主题修复。公共合同随后在 L1 全组通过；其余阶段未以该轮结果声称全仓通过。

| L2 首轮失败阶段 | 原因及本次处置 |
|---|---|
| 公共合同，269例 | 标题层级及旧 README 粒子口径由本主题修复；MR入口retention注册、Lua refine策略交科学任务；随后 L1 269例通过 |
| 公共多极杆，393例 | case set、终端圆／矩形截面预期与当前合同不同；保留失败并交原任务 |
| RF→oaTOF集成，855例 | 发布绑定新鲜度、run_artifacts源码SHA及恢复路径形状断言；交原工作流，不替换冻结身份 |
| oaTOF，366例 | 公式块数量断言改为完整公式语义，7例通过；另一 stderr／编码错误交原任务 |
| 四极杆，225例 | 非标准粒子数旧拒绝预期与参数自由变化不一致；交原任务 |
| 电子枪，48例 | 冻结测试副本缺新增主机租约依赖；交公共运行支持改动者 |

实现提交为 `aadfc3289a8ebd815d55e15e27ad77e80517b279`，包含 97 个文件、8 个代码／机器配置文件。
它只提交独立文档主题。以下整理已在共享工作树完成，继续随所属科学实现提交：公共 SIMION 与 contracts README、
SIMION_REFERENCE、MRTOF PROJECT／SIMION README及状态历史、integration整组文档。LIFECYCLE 的在途 TTL 行和
MR README 的状态历史入口也保留为未暂存差异。原科学代码、配置、产物和未提交差异没有夹带进此提交。

一次相邻 integration JSON 的 CRLF 导致受管字节门禁失败，本任务仅将其行尾还原为规定 LF，内容不变、未纳入文档提交。
没有删除任务开始前的文件；临时预览已清理。后续科学结果仍由各工作流更新，不回写本日期审计。

## 篇幅与覆盖快照

| 指标 | 任务开始 | 整治快照 | 变化 |
|---|---:|---:|---:|
| Markdown 总数 | 229 | 243 | +14 |
| 非history文档 | 102 | 106 | +4（三个规则职责页及集成RUNNING） |
| history文档（含旧载荷INDEX） | 127 | 137 | +10（其中一份本报告） |
| 非history正文行数 | 21179 | 18190 | −2989，约−14.1% |
| 原有文档改变／保留 | — | 89／140 | 127份旧history全数原字节保留 |
| 根README行数 | 665 | 64 | −601 |
| MRTOF PROJECT行数 | 1385 | 190 | −1195 |
| MRTOF SIMION README行数 | 623 | 288 | −335 |
| integration INTEGRATION行数 | 746 | 70 | −676；运行说明另有185行 |

统计按起点工作树 SHA-256 清单与整治快照比较，不把源码 CLOC 当文档篇幅。总文件数确有增加：
职责拆分增加4个活动页，保留证据增加10个历史页；本次压缩的是重复权威与当前阅读负担，没有声称物理文件总量下降。
后续应优先替换唯一正文、复用现有归档，继续控制新增文件，而不是持续追加当前日志。

## 代码变化（CLOC 2.10）

下列计数只比较 `45a6741550aae5cbb009615896d16ef6d20618a2 → aadfc3289a8ebd815d55e15e27ad77e80517b279`，
排除其他 agent 的工作树科学改动。后续本审计提交只改 Markdown，不改变代码计数。每格为“基线 → 结果（delta）”。

<details>
<summary>total：按语言 files、blank、comment、code</summary>

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 480 → 480 (0) | 0 → 0 (0) | 0 → 0 (0) | 47652 → 47666 (+14) |
| Lua | 88 → 88 (0) | 407 → 407 (0) | 561 → 561 (0) | 8016 → 8016 (0) |
| MATLAB | 110 → 110 (0) | 964 → 964 (0) | 2179 → 2179 (0) | 12888 → 12888 (0) |
| PowerShell | 133 → 133 (0) | 963 → 962 (-1) | 908 → 908 (0) | 33802 → 33756 (-46) |
| Python | 670 → 672 (+2) | 15802 → 15839 (+37) | 6480 → 6494 (+14) | 182190 → 182454 (+264) |
| SIMION | 11 → 11 (0) | 35 → 35 (0) | 83 → 83 (0) | 256 → 256 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 114 → 114 (0) |
| SUM | 1495 → 1497 (+2) | 18179 → 18215 (+36) | 10212 → 10226 (+14) | 284942 → 285174 (+232) |

</details>

<details>
<summary>production：按语言 files、blank、comment、code</summary>

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 476 → 476 (0) | 0 → 0 (0) | 0 → 0 (0) | 47542 → 47556 (+14) |
| Lua | 75 → 75 (0) | 311 → 311 (0) | 499 → 499 (0) | 6554 → 6554 (0) |
| MATLAB | 72 → 72 (0) | 526 → 526 (0) | 1661 → 1661 (0) | 9390 → 9390 (0) |
| PowerShell | 125 → 125 (0) | 912 → 911 (-1) | 902 → 902 (0) | 32862 → 32816 (-46) |
| Python | 366 → 367 (+1) | 10012 → 10032 (+20) | 5186 → 5197 (+11) | 109044 → 109227 (+183) |
| SIMION | 11 → 11 (0) | 35 → 35 (0) | 83 → 83 (0) | 256 → 256 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 114 → 114 (0) |
| SUM | 1128 → 1129 (+1) | 11804 → 11823 (+19) | 8332 → 8343 (+11) | 205786 → 205937 (+151) |

</details>

<details>
<summary>tests：按语言 files、blank、comment、code</summary>

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 4 → 4 (0) | 0 → 0 (0) | 0 → 0 (0) | 110 → 110 (0) |
| Lua | 13 → 13 (0) | 96 → 96 (0) | 62 → 62 (0) | 1462 → 1462 (0) |
| MATLAB | 38 → 38 (0) | 438 → 438 (0) | 518 → 518 (0) | 3498 → 3498 (0) |
| PowerShell | 8 → 8 (0) | 51 → 51 (0) | 6 → 6 (0) | 940 → 940 (0) |
| Python | 304 → 305 (+1) | 5790 → 5807 (+17) | 1294 → 1297 (+3) | 73146 → 73227 (+81) |
| SUM | 367 → 368 (+1) | 6375 → 6392 (+17) | 1880 → 1883 (+3) | 79156 → 79237 (+81) |

</details>

unclassified 为0；没有将 tests 目录整体视为纯测试。完整过滤口径及分类器身份如下：

```text
CLOC_VERSION=2.10
CLASSIFIER_SHA256=db9ed262601aa58092558467e9652fcc82c3787383e283c356973142e535809a
LANGUAGE_DEFINITION_SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6
INPUT_IDENTITY SNAPSHOT=baseline FILES=1495 SHA256=36a5e7e2da41fda2dff29ba26c8a445c25673c888a58c2e56d0e40f4bebe298b
INPUT_IDENTITY SNAPSHOT=result FILES=1497 SHA256=e4b837e2881079b6b10bfc3c344f97b5c1e36cedcaa7ad161b00a3cc03b1ba2c
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```

## 逐文件处置清单

下表包含起点229份与新增14份；旧history只核对完整性、位置与引用范围，未逐字改写或重新证明科学内容。
“修改”指相对起点字节不同；“保留”指原字节相同。最终值为本次测量快照，活跃科学任务后续编辑不属于此记录。

<details>
<summary>展开243份文档处置（路径为仓库相对位置）</summary>

| 文档 | 处置 | 行数：前→后 |
|---|---|---:|
| `.agents/skills/grill-me/SKILL.md` | 审查保留：职责／格式／消费者有效 | 43 → 43 |
| `AGENTS.md` | 规范／操作／归档职责与引用整治 | 165 → 163 |
| `CLAUDE.md` | 审查保留：职责／格式／消费者有效 | 5 → 5 |
| `common/comsol/README.md` | 入口或公共实现导航整治 | 60 → 61 |
| `common/contracts/README.md` | 入口或公共实现导航整治 | 206 → 212 |
| `common/integration/README.md` | 入口或公共实现导航整治 | 32 → 38 |
| `common/multipole/README.md` | 入口或公共实现导航整治 | 173 → 173 |
| `common/simion/assets/iob_instance_seeds/README.md` | 入口或公共实现导航整治 | 21 → 16 |
| `common/simion/PRODUCTION_FLY_AUDIT.md` | 规范／操作／归档职责与引用整治 | 27 → 9 |
| `common/simion/README.md` | 入口或公共实现导航整治 | 155 → 207 |
| `common/solidworks/README.md` | 入口或公共实现导航整治 | 11 → 11 |
| `docs/AUDITS.md` | 规范／操作／归档职责与引用整治 | 57 → 38 |
| `docs/COMPONENT_CONNECTION_ARCHITECTURE.md` | 规范／操作／归档职责与引用整治 | 123 → 116 |
| `docs/COMSOL_API.md` | 规范／操作／归档职责与引用整治 | 320 → 322 |
| `docs/COMSOL_DEBUGGING.md` | 规范／操作／归档职责与引用整治 | 190 → 192 |
| `docs/DEVELOPMENT_STANDARDS.md` | 规范／操作／归档职责与引用整治 | 407 → 411 |
| `docs/history/20260727__code-retention-audit.md` | 只读历史：原字节保留 | 103 → 103 |
| `docs/history/20260730__production-maintenance-boundary-disposition.md` | 只读历史：原字节保留 | 130 → 130 |
| `docs/history/20260730__production-maintenance-surface-baseline.md` | 只读历史：原字节保留 | 210 → 210 |
| `docs/history/20260730__repository-size-and-architecture-audit.md` | 只读历史：原字节保留 | 99 → 99 |
| `docs/history/20260801__active-compatibility-retirement.md` | 只读历史：原字节保留 | 48 → 48 |
| `docs/history/20260801__artifact-top-level-layout-closure.md` | 只读历史：原字节保留 | 75 → 75 |
| `docs/history/20260801__multipole-legacy-artifact-migration-audit.md` | 只读历史：原字节保留 | 173 → 173 |
| `docs/history/20260802__documentation-authority-content-audit.md` | 只读历史：原字节保留 | 43 → 43 |
| `docs/history/20260802__electron-source-wehnelt-artifact-migration.md` | 只读历史：原字节保留 | 24 → 24 |
| `docs/history/20260802__gate-system-audit.md` | 只读历史：原字节保留 | 50 → 50 |
| `docs/history/20260802__run-campaign-evidence-audit.md` | 只读历史：原字节保留 | 52 → 52 |
| `docs/history/20260814__artifact-authorized-disposition-audit.md` | 只读历史：原字节保留 | 76 → 76 |
| `docs/history/20260815__multipole-common-simion-rf-drive-kernel.md` | 只读历史：原字节保留 | 122 → 122 |
| `docs/history/20260815__multipole-single-flight-common-rod-gem-authority.md` | 只读历史：原字节保留 | 68 → 68 |
| `docs/history/20260820__repository-deep-architecture-contract-audit.md` | 只读历史：原字节保留 | 17 → 17 |
| `docs/history/20260825__history-placeholder-recovery-audit.md` | 只读历史：原字节保留 | 29 → 29 |
| `docs/history/20260827__repository-hygiene-disposition-audit.md` | 只读历史：原字节保留 | 84 → 84 |
| `docs/history/20260828__compact-artifact-hygiene-audit.md` | 只读历史：原字节保留 | 88 → 88 |
| `docs/history/20260911__documentation-system-reform.md` | 新增具名归档 | — → 本报告 |
| `docs/history/20260911__reference-documentation-consolidation.md` | 新增具名归档 | — → 80 |
| `docs/LIFECYCLE.md` | 新增独立职责正文 | — → 293 |
| `docs/multipoles/collisions.md` | 理论导航、符号／适用域与排版整治 | 336 → 340 |
| `docs/multipoles/exit_phase_space_control.md` | 理论导航、符号／适用域与排版整治 | 248 → 250 |
| `docs/multipoles/foundations.md` | 理论导航、符号／适用域与排版整治 | 366 → 369 |
| `docs/multipoles/higher_multipoles.md` | 理论导航、符号／适用域与排版整治 | 279 → 280 |
| `docs/multipoles/index.md` | 理论导航、符号／适用域与排版整治 | 80 → 78 |
| `docs/multipoles/quadrupole.md` | 理论导航、符号／适用域与排版整治 | 498 → 496 |
| `docs/OPERATIONS.md` | 新增独立职责正文 | — → 156 |
| `docs/PLOTTING_STANDARDS.md` | 规范／操作／归档职责与引用整治 | 324 → 324 |
| `docs/REPOSITORY_ARCHITECTURE.md` | 新增独立职责正文 | — → 207 |
| `docs/ROADMAP.md` | 规范／操作／归档职责与引用整治 | 277 → 156 |
| `docs/SIMION_REFERENCE.md` | 规范／操作／归档职责与引用整治 | 73 → 76 |
| `docs/VALIDATION_METHODS.md` | 规范／操作／归档职责与引用整治 | 373 → 382 |
| `docs/VISION.md` | 规范／操作／归档职责与引用整治 | 94 → 94 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/ARCHITECTURE.md` | 规范／操作／归档职责与引用整治 | 70 → 77 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/HARD_LIMIT_AUDIT.md` | 规范／操作／归档职责与引用整治 | 23 → 27 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md` | 只读历史：原字节保留 | 62 → 62 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260805__octupole-10ev-single-flight.md` | 只读历史：原字节保留 | 90 → 90 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260805__octupole-15mm-sleeve-accelerator-energy.md` | 只读历史：原字节保留 | 37 → 37 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260805__octupole-terminal-10ev-single-flight.md` | 只读历史：原字节保留 | 79 → 79 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260805__octupole-terminal-15mm-sleeve-single-flight-n1000.md` | 只读历史：原字节保留 | 51 → 51 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260810__oatof-frontend-grid-and-ideal-field.md` | 只读历史：原字节保留 | 42 → 42 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260810__oatof-source-z22-auto-rebuild.md` | 只读历史：原字节保留 | 56 → 56 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260811__oatof-resolution-formal-field-attribution.md` | 只读历史：原字节保留 | 64 → 64 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260812__oatof-finite-interval-focus-diagnostics.md` | 只读历史：原字节保留 | 39 → 39 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-2p2mm-higher-order-preregistration.md` | 只读历史：原字节保留 | 210 → 210 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-canonical-matrix-high-order-continuation.md` | 只读历史：原字节保留 | 969 → 969 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-long-affine-arm8-five-cell-official-restart-preregistration.md` | 只读历史：原字节保留 | 75 → 75 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-long-affine-arm8-five-cell-simion-preregistration.md` | 只读历史：原字节保留 | 162 → 162 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-native-grid-field-source-focus-investigation.md` | 只读历史：原字节保留 | 268 → 268 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-pulse-resolution-screening-closure.md` | 只读历史：原字节保留 | 104 → 104 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-rr-trajectory-quality-paired-check.md` | 只读历史：原字节保留 | 83 → 83 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__oatof-source-field-configuration-registry-and-results-matrix.md` | 只读历史：原字节保留 | 203 → 203 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260814__rf-oatof-schema-v3-resolved-pulse-population-authority.md` | 只读历史：原字节保留 | 109 → 109 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__oatof-finite-interval-compiler-ownership.md` | 只读历史：原字节保留 | 75 → 75 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__pulse-resolution-candidate-r01-failure-r02-successor.md` | 只读历史：原字节保留 | 18 → 18 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__pulse-resolution-candidate-r02-promotion-receipt-fix.md` | 只读历史：原字节保留 | 16 → 16 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__pulse-resolution-r09-baseline-and-candidate-preregistration.md` | 只读历史：原字节保留 | 34 → 34 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__rf-oatof-handoff-adapter-integration-ownership.md` | 只读历史：原字节保留 | 59 → 59 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__rf-oatof-single-flight-integration-run-ownership.md` | 只读历史：原字节保留 | 55 → 55 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260815__rf-oatof-staged-grid2-restart-functional-migration.md` | 只读历史：原字节保留 | 733 → 733 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260816__oatof-2p2mm-high-order-third-order-theory-handoff.md` | 只读历史：原字节保留 | 500 → 500 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260819__oatof-gap51p2-dt160-dt40-dt10-convergence.md` | 只读历史：原字节保留 | 70 → 70 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260819__oatof-zvz-residual-removal-handoff.md` | 只读历史：原字节保留 | 39 → 39 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260820__oatof-connector-gap-phase-space-trend.md` | 只读历史：原字节保留 | 40 → 40 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260820__resolution-matrix-gap-field-source-population.md` | 只读历史：原字节保留 | 30 → 30 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260821__compact-auto-gap-field-replay.md` | 只读历史：原字节保留 | 37 → 37 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260821__gap102p4_manifest-bound-handoff-n116.md` | 只读历史：原字节保留 | 30 → 30 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260822__post-pulse-no-rf-per-gap-theory-field-matrix.md` | 只读历史：原字节保留 | 42 → 42 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260831__five-ring-prepulse-and-field-diagnostics.md` | 只读历史：原字节保留 | 31 → 31 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__campaign-readonly-authority-gate.md` | 只读历史：原字节保留 | 56 → 56 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__compact-prepulse-terminal-publication.md` | 只读历史：原字节保留 | 206 → 206 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__current-square-h100-handoff-flight.md` | 只读历史：原字节保留 | 74 → 74 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__eligible-pulse-concentration.md` | 只读历史：原字节保留 | 162 → 162 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__exit-field-export-regression.md` | 只读历史：原字节保留 | 63 → 63 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__frozen-handoff-n50-reuse.md` | 只读历史：原字节保留 | 83 → 83 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__handoff-comparator-diagnostic-coverage.md` | 只读历史：原字节保留 | 56 → 56 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__pa-plus-boundary-mask-recovery.md` | 只读历史：原字节保留 | 103 → 103 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__post-pulse-duration-n1.md` | 只读历史：原字节保留 | 90 → 90 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__restart-velocity-n50-validation.md` | 只读历史：原字节保留 | 151 → 151 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__restore-upstream-terminal-extension.md` | 只读历史：原字节保留 | 138 → 138 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__return-detector-marker-validation.md` | 只读历史：原字节保留 | 166 → 166 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__square-four-aperture-flight-audit.md` | 只读历史：原字节保留 | 158 → 158 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__square-h150-capture-and-terminal-clock.md` | 只读历史：原字节保留 | 163 → 163 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__square-h150-handoff-comparison.md` | 只读历史：原字节保留 | 78 → 78 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__square-h150-postpulse.md` | 只读历史：原字节保留 | 161 → 161 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260904__zero-field-collision-grounding.md` | 只读历史：原字节保留 | 200 → 200 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20260911__single-flight-documentation-and-invalidated-comparisons.md` | 新增具名归档 | — → 761 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/retired_campaigns/root_campaigns/INDEX.md` | 只读历史：原字节保留 | 26 → 26 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/retired_campaigns.md` | 只读历史：原字节保留 | 17 → 17 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/HISTORY.md` | 规范／操作／归档职责与引用整治 | 59 → 69 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md` | 当前状态收缩与资格／开放任务裁决 | 746 → 70 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/RUNNING.md` | 新增独立职责正文 | — → 185 |
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md` | 入口或公共实现导航整治 | 39 → 39 |
| `official_docs/README.md` | 入口或公共实现导航整治 | 17 → 22 |
| `projects/apertured_tube_electron_impact_ion_source/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 49 → 53 |
| `projects/apertured_tube_electron_impact_ion_source/README.md` | 入口或公共实现导航整治 | 23 → 22 |
| `projects/dual_cone_tandem_quadrupole_ion_interface/docs/COMSOL.md` | 规范／操作／归档职责与引用整治 | 98 → 102 |
| `projects/dual_cone_tandem_quadrupole_ion_interface/docs/history/20260908__superseded-python-pressure-drag-screening.md` | 只读历史：原字节保留 | 18 → 18 |
| `projects/dual_cone_tandem_quadrupole_ion_interface/docs/history/20260911__empty-enclosure-gas-transport-prototype.md` | 新增具名归档 | — → 23 |
| `projects/dual_cone_tandem_quadrupole_ion_interface/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 98 → 101 |
| `projects/dual_cone_tandem_quadrupole_ion_interface/docs/SIMION.md` | 规范／操作／归档职责与引用整治 | 87 → 91 |
| `projects/dual_cone_tandem_quadrupole_ion_interface/README.md` | 入口或公共实现导航整治 | 79 → 71 |
| `projects/orthogonal_accelerator/docs/history/20260903__legacy-accelerator-diagnostic.md` | 只读历史：原字节保留 | 33 → 33 |
| `projects/orthogonal_accelerator/docs/history/20260911__component-migration-evidence.md` | 新增具名归档 | — → 71 |
| `projects/orthogonal_accelerator/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 79 → 49 |
| `projects/orthogonal_accelerator/docs/theory/affine_phase_space_time_focus.md` | 理论导航、符号／适用域与排版整治 | 187 → 196 |
| `projects/orthogonal_accelerator/docs/theory/oaaccelerator_time_focus.md` | 理论导航、符号／适用域与排版整治 | 585 → 587 |
| `projects/orthogonal_accelerator/docs/theory/README.md` | 审查保留：职责／格式／消费者有效 | 33 → 33 |
| `projects/orthogonal_accelerator/docs/theory/three_zone_accelerator_ideal_theory.md` | 审查保留：职责／格式／消费者有效 | 228 → 228 |
| `projects/orthogonal_accelerator/README.md` | 入口或公共实现导航整治 | 34 → 42 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/CAD.md` | 规范／操作／归档职责与引用整治 | 30 → 34 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/CAD_AUDIT_20260902.md` | 规范／操作／归档职责与引用整治 | 410 → 8 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20260802__mrtof-project-identity-consolidation.md` | 只读历史：原字节保留 | 47 → 47 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20260911__cad-audit-context-freeze.md` | 新增具名归档 | — → 424 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20260911__project-and-simion-status-freeze.md` | 新增具名归档 | — → 2032 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 1385 → 190 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/adiabatic_drift_and_original_ion_foil.md` | 理论导航、符号／适用域与排版整治 | 772 → 774 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/dual_stripe_non_tilt_design.md` | 理论导航、符号／适用域与排版整治 | 1003 → 1010 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/implementation_and_validation.md` | 理论导航、符号／适用域与排版整治 | 718 → 608 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/index.md` | 理论导航、符号／适用域与排版整治 | 201 → 196 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/injection_prism_source_and_calibration.md` | 理论导航、符号／适用域与排版整治 | 454 → 438 |
| `projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/isochronous_mirror_design.md` | 理论导航、符号／适用域与排版整治 | 615 → 618 |
| `projects/parallel_mirror_dual_stripe_mr_tof/README.md` | 入口或公共实现导航整治 | 37 → 39 |
| `projects/parallel_mirror_dual_stripe_mr_tof/simion/README.md` | 入口或公共实现导航整治 | 623 → 288 |
| `projects/rf_hexapole_ion_optics/docs/history/20260723__pre-n100-multipole-functional-evidence.md` | 只读历史：原字节保留 | 38 → 38 |
| `projects/rf_hexapole_ion_optics/docs/history/20260729__closed-hybrid-mesh-campaigns.md` | 只读历史：原字节保留 | 21 → 21 |
| `projects/rf_hexapole_ion_optics/docs/history/20260729__multipole-three-mode-posthoc-n100.md` | 只读历史：原字节保留 | 81 → 81 |
| `projects/rf_hexapole_ion_optics/docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md` | 只读历史：原字节保留 | 83 → 83 |
| `projects/rf_hexapole_ion_optics/docs/history/20260731__multipole-noacc-vs-segmented-h15-n100.md` | 只读历史：原字节保留 | 71 → 71 |
| `projects/rf_hexapole_ion_optics/docs/history/20260731__multipole-three-mode-h15-n100.md` | 只读历史：原字节保留 | 53 → 53 |
| `projects/rf_hexapole_ion_optics/docs/history/20260731__no-acceleration-multipole-discretization-followup.md` | 只读历史：原字节保留 | 76 → 76 |
| `projects/rf_hexapole_ion_optics/docs/history/20260802__retired-comsol-qualification-campaigns.md` | 只读历史：原字节保留 | 25 → 25 |
| `projects/rf_hexapole_ion_optics/docs/history/20260803__hex-rf-drive-phase-matched-h15-n100.md` | 只读历史：原字节保留 | 56 → 56 |
| `projects/rf_hexapole_ion_optics/docs/history/20260803__hex-rf-drive-phase-matched-h15-n1000.md` | 只读历史：原字节保留 | 59 → 59 |
| `projects/rf_hexapole_ion_optics/docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md` | 只读历史：原字节保留 | 56 → 56 |
| `projects/rf_hexapole_ion_optics/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 70 → 60 |
| `projects/rf_hexapole_ion_optics/README.md` | 入口或公共实现导航整治 | 69 → 49 |
| `projects/rf_octupole_ion_optics/docs/history/20260723__pre-n100-multipole-functional-evidence.md` | 只读历史：原字节保留 | 34 → 34 |
| `projects/rf_octupole_ion_optics/docs/history/20260911__source-model-comparison.md` | 新增具名归档 | — → 17 |
| `projects/rf_octupole_ion_optics/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 110 → 91 |
| `projects/rf_octupole_ion_optics/README.md` | 入口或公共实现导航整治 | 45 → 45 |
| `projects/rf_quadrupole_ion_optics/docs/COMSOL.md` | 规范／操作／归档职责与引用整治 | 92 → 72 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260722__rf-oatof-s2-s3-functional-closure.md` | 只读历史：原字节保留 | 141 → 141 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260722_rf-mesh-strategy-screen.md` | 只读历史：原字节保留 | 15 → 15 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260722_rf-validation-and-s1-integration.md` | 只读历史：原字节保留 | 598 → 598 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260723__pre-n100-multipole-functional-evidence.md` | 只读历史：原字节保留 | 42 → 42 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-comsol.md` | 只读历史：原字节保留 | 11 → 11 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-project.md` | 只读历史：原字节保留 | 12 → 12 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-readme.md` | 只读历史：原字节保留 | 12 → 12 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-simion.md` | 只读历史：原字节保留 | 12 → 12 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260729__superseded-rf-oatof-s2-s3-active-contracts.md` | 只读历史：原字节保留 | 37 → 37 |
| `projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md` | 新增具名归档 | — → 51 |
| `projects/rf_quadrupole_ion_optics/docs/PROJECT.md` | 审查保留：职责／格式／消费者有效 | 103 → 103 |
| `projects/rf_quadrupole_ion_optics/docs/SIMION.md` | 规范／操作／归档职责与引用整治 | 72 → 63 |
| `projects/rf_quadrupole_ion_optics/README.md` | 入口或公共实现导航整治 | 112 → 85 |
| `projects/single_reflection_oa_tof_mass_analyzer/analysis/README.md` | 入口或公共实现导航整治 | 220 → 235 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/CAD.md` | 规范／操作／归档职责与引用整治 | 66 → 65 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/COMSOL.md` | 规范／操作／归档职责与引用整治 | 54 → 55 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260716__simion-gui-recording-and-program-audit.md` | 只读历史：原字节保留 | 56 → 56 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260719__analysis-scaling-and-field-diagnostics.md` | 只读历史：原字节保留 | 72 → 72 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260720__midgrid-candidate-runtime-coverage.md` | 只读历史：原字节保留 | 44 → 44 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260720__oatof-theory-refactor-review.md` | 只读历史：原字节保留 | 57 → 57 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260721__superseded-theory-docx.md` | 只读历史：原字节保留 | 21 → 21 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260727__superseded-rf-handoff-diagnostics.md` | 只读历史：原字节保留 | 75 → 75 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260728__pre-document-consolidation-comsol.md` | 只读历史：原字节保留 | 11 → 11 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260728__pre-document-consolidation-project.md` | 只读历史：原字节保留 | 11 → 11 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260728__pre-document-consolidation-readme.md` | 只读历史：原字节保留 | 11 → 11 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260728__pre-document-consolidation-simion.md` | 只读历史：原字节保留 | 12 → 12 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260729__formal-vnext-zero-change-requests.md` | 只读历史：原字节保留 | 22 → 22 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260801__oatof-legacy-artifact-migration-audit.md` | 只读历史：原字节保留 | 54 → 54 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260802__formal-simion-integrity-recovery.md` | 只读历史：原字节保留 | 39 → 39 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260802__reflectron-midgrid-campaign-authorization.md` | 只读历史：原字节保留 | 55 → 55 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260817__three-zone-accelerator-external-document-review.md` | 只读历史：原字节保留 | 110 → 110 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260817__three-zone-observed-transverse-sensitivity.md` | 只读历史：原字节保留 | 71 → 71 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md` | 只读历史：原字节保留 | 189 → 189 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260823__three-zone-completed-results-snapshot.md` | 只读历史：原字节保留 | 52 → 52 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260827__200mm-ideal-acceptance-scan.md` | 只读历史：原字节保留 | 47 → 47 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260827__300mm-ideal-acceptance-scan.md` | 只读历史：原字节保留 | 33 → 33 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260827__ideal-source-residual-and-width-comparison.md` | 只读历史：原字节保留 | 151 → 151 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260827__synthetic-affine-slope-scan.md` | 只读历史：原字节保留 | 46 → 46 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260911__publication-status-consolidation.md` | 新增具名归档 | — → 400 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/CANDIDATE_WORKFLOW_VALIDATION_20260720.md` | 只读历史：原字节保留 | 53 → 53 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/COMSOL_EXTREME_N_CRASH_20260718_19.md` | 只读历史：原字节保留 | 46 → 46 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md` | 只读历史：原字节保留 | 65 → 65 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/NUMERICAL_VALIDATION_20260716_18.md` | 只读历史：原字节保留 | 81 → 81 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/PROJECT_HISTORY.md` | 只读历史：原字节保留 | 1017 → 1017 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/SIMION_VALIDATION.md` | 只读历史：原字节保留 | 484 → 484 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/history/SUPERSEDED_RESULTS.md` | 只读历史：原字节保留 | 65 → 65 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 221 → 203 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/overlap_and_claim_firewall.md` | 审查保留：职责／格式／消费者有效 | 124 → 124 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/connector_gap_paired_source_contract.md` | 研究／合同／证据职责与冻结边界整治 | 119 → 63 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/connector_gap_working_point_mechanism_20260827.md` | 研究／合同／证据职责与冻结边界整治 | 99 → 102 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/evidence_matrix.md` | 研究／合同／证据职责与冻结边界整治 | 88 → 48 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/j2_real_3d_pilot_contract.md` | 审查保留：职责／格式／消费者有效 | 84 → 84 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/scope_claims_and_outline.md` | 研究／合同／证据职责与冻结边界整治 | 166 → 4 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/stage_c0_theory_closure.md` | 审查保留：职责／格式／消费者有效 | 25 → 25 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/stage_c1_connector_gap_triplet_contract.md` | 研究／合同／证据职责与冻结边界整治 | 118 → 114 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/stage_c1_source_contract.md` | 研究／合同／证据职责与冻结边界整治 | 193 → 29 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/stage_c3_j3_real_field_contract.md` | 研究／合同／证据职责与冻结边界整治 | 51 → 44 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/stage_c4_j3_locked_prediction_contract.md` | 审查保留：职责／格式／消费者有效 | 23 → 23 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_1_jasms/validation_and_evidence_plan.md` | 研究／合同／证据职责与冻结边界整治 | 221 → 284 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_2_analytical_chemistry/scope_claims_and_new_work.md` | 研究／合同／证据职责与冻结边界整治 | 179 → 4 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/paper_2_analytical_chemistry/validation_and_evidence_plan.md` | 研究／合同／证据职责与冻结边界整治 | 115 → 266 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/prior_art_claim_registry.md` | 审查保留：职责／格式／消费者有效 | 171 → 171 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/prior_art_equation_claim_chart_20260825.md` | 研究／合同／证据职责与冻结边界整治 | 401 → 433 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/prior_art_search_audit_20260825.md` | 研究／合同／证据职责与冻结边界整治 | 203 → 206 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/publication/README.md` | 研究／合同／证据职责与冻结边界整治 | 67 → 49 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/SIMION.md` | 规范／操作／归档职责与引用整治 | 135 → 132 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/SIMION_REPRODUCTION_PARAMETERS.md` | 规范／操作／归档职责与引用整治 | 65 → 72 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/conditional_phase_space_focusability.md` | 理论导航、符号／适用域与排版整治 | 436 → 457 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/dual_stage_reflectron.md` | 理论导航、符号／适用域与排版整治 | 599 → 620 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oaaccelerator_time_focus.md` | 审查保留：职责／格式／消费者有效 | 8 → 8 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oatof_oaaccelerator_coupling.md` | 理论导航、符号／适用域与排版整治 | 602 → 625 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/README.md` | 理论导航、符号／适用域与排版整治 | 64 → 67 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/source_to_detector_phase_space_framework.md` | 理论导航、符号／适用域与排版整治 | 456 → 476 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/three_zone_accelerator_ideal_theory.md` | 理论导航、符号／适用域与排版整治 | 334 → 339 |
| `projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md` | 审查保留：职责／格式／消费者有效 | 58 → 58 |
| `projects/single_reflection_oa_tof_mass_analyzer/README.md` | 入口或公共实现导航整治 | 147 → 129 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/docs/COMSOL.md` | 规范／操作／归档职责与引用整治 | 54 → 55 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/docs/history/20260713__pre-transverse-wehnelt-lineages.md` | 只读历史：原字节保留 | 45 → 45 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/docs/history/20260728__pre-document-consolidation-project.md` | 只读历史：原字节保留 | 11 → 11 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/docs/history/PROJECT_HISTORY.md` | 只读历史：原字节保留 | 106 → 106 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/docs/PROJECT.md` | 当前状态收缩与资格／开放任务裁决 | 60 → 57 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/legacy/README.md` | 审查保留：职责／格式／消费者有效 | 10 → 10 |
| `projects/transverse_helical_filament_wehnelt_electron_gun/README.md` | 入口或公共实现导航整治 | 80 → 37 |
| `README.md` | 入口或公共实现导航整治 | 665 → 64 |

</details>
