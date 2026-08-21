# 仓库规模与架构评审核验（2026-07-30）

DOC_STATUS: ARCHIVED_READ_ONLY

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文记录一次性外部评审核验和本次处置边界，不作为项目
> 当前状态、持续规范或开放任务权威。稳定审计索引见[`../AUDITS.md`](../AUDITS.md)；项目状态仍以
> 各项目`README.md → docs/PROJECT.md`和对应integration文档为准。

## 范围与权威

本次审计核验用户提供的`2026-07-29_REPOSITORY_CLOC_ARCHITECTURE_REVIEW.md`，但不把外部评审直接
纳入仓库规范。判断顺序固定为根`README.md`的目录职责与生命周期、`AGENTS.md`执行约束、
`docs/DEVELOPMENT_STANDARDS.md`、项目README/PROJECT、机器合同和现有测试，最后才用外部评审提出的
问题作为待核验证据。

审计基线为提交`1a2b87155387f083497401c2eb329bcffac34ca9`，规范计数工具为CLOC 2.10。审计期间
工作树已有未跟踪`.tmp/`；它不属于本次任务，未被修改或清理。

## CLOC复核

外部评审记录的total `115,197`没有绑定提交、CLOC版本或原始报告，且其四个分类相加为`115,198`，
不能作为当前可复现基线。修复前的旧入口曾对当前HEAD报告：

|分类|code|
|---|---:|
|total|135,552|
|production|96,010|
|tests|37,919|
|unclassified|1,623|

该旧口径会分次启动CLOC、受默认唯一性过滤影响、漏计GEM/FLY2，并把部分MATLAB误识别为
Mathematica。本次修复后，以同一HEAD重建的新基线为：

|分类|code|
|---|---:|
|total|135,764|
|production|96,278|
|tests|37,871|
|unclassified|1,615|

修复后的最终受管HEAD为136,637 code，相对新基线增加873，其中production增加672、tests增加201、
unclassified不变。包含任务开始前既有`.tmp/`的WORKTREE为145,864 code；关闭唯一性去重后，这14个
未跟踪JSON实际贡献9,227 code。旧口径报告的9,167少计了其中60行重复内容，不能把`.tmp/`与本次
受管架构增长合并解释。

按修复前统一口径，从CLOC治理提交`75709a3`到当前HEAD，total增加28,707，其中JSON机器合同、
资格/预注册记录和生成文本增加11,877，tests增加8,300，非测试可执行文本净增8,530。该历史分解
仍能说明增长来源，但不能与修复后补计语言的新绝对值直接混算。`production`只能解释为仓库生产责任/
非测试分类，不能等同“活跃可执行代码”。

当前报告已经排除任意`docs/history/**`、根`scratch/**`、artifacts、generated、vendor及run目录，
也已经报告提交身份、CLOC版本和过滤口径；外部评审关于这些能力全部缺失的判断已经过时。仍需修复的
真实缺陷是分类分次计数受CLOC默认唯一性过滤影响、`.gem/.fly2`漏计、部分`.m`被误判为Mathematica，
以及ignored execution profile理论上可以影响WORKTREE分类。

## 架构判断

|外部主张|核验结论|处置|
|---|---|---|
|RF→oaTOF仍为`equivalence_pending`|过时；零物理变化功能迁移已PASS，2026-07-30又通过integration入口复验|修正current README、机器入口和连接架构文档；历史与oracle不改写|
|六/八极杆profile尚未开始|过时；三种多极杆×两种source共六分支均已成功运行|只表述为`FUNCTIONAL_SCREEN/INCONCLUSIVE`，不晋升Candidate|
|PowerShell需要全仓统一runner|证据不足；多极杆已有共享launcher，integration runtime也委托公共生命周期|不建设万能runner；只盘点确切零引用候选|
|changed-scope靠手工同步且可能漏测|成立；`common/simion`、`common/comsol`、`common/multipole`和部分contracts依赖未完整传播|建立一份窄路由权威和`-FullScope`，不建设全仓DAG|
|`common/contracts`应整体拆分|部分成立；存在具名项目/集成Schema和一次性工具，但通用生命周期与canonical合同有真实多项目消费者|本次只做消费者盘点，不做Schema全量迁移|
|history污染规范CLOC|过时；当前过滤和测试已排除任意history|保持现行排除，不把history重新计入|
|应设整数CLOC上限并机械减行|拒绝；行数是职责审查信号，不是资格或质量目标|修复计量后按语义、消费者和生命周期逐项判断|

## 本次实施边界

本次只实施四项非破坏性收口：

1. 修复CLOC加法一致性、语言识别、输入集合和来源身份，同时保持现有命令兼容。
2. 用单一路由表统一changed-scope路径、原因和gate，并让CI fallback调用`-FullScope`。
3. 修复RF→oaTOF current authority的悬空入口和陈旧状态，增加current入口存在性静态门禁。
4. 保留本文作为一次性评审结论，不增加长期架构审计平台。

下列事项不在本次授权内：删除文件；移动qualification/config、分析源码或Schema；修改`AGENTS.md`、
根README或开发规范；legacy artifact relocation；退役`verify_lightweight.ps1`；六极杆Candidate晋升；
增加商业求解器CI。

## 持续负担约束

- CLOC由每分类重复启动改为每快照一次按文件聚合，不能为更细报告增加第二CLI或常驻生成物。
- 普通项目变更不得新增无关gate；共享路径只运行能由真实消费依赖解释的额外gate。
- `-FullScope`只用于显式全范围验证和CI fallback，不替代日常changed-scope。
- current入口检查保持为无商业软件静态测试；本次不增加求解器、GUI或CAD日常负担。
- 所有权迁移、终态资格记录收缩和入口退役必须先形成精确清单、消费者证明、回归门禁和用户批准。

## 实施验收

本次WORKTREE已通过CLOC专项与加法不变量、changed-scope/开发规范合同、RF→oaTOF current入口合同、
文档门禁、Ruff、PowerShell/JSON解析、L1 changed-scope及L2 repository integration。L1实测
244.2秒，L2实测356.6秒；二者均为无商业求解器门禁。

CLOC的HEAD→HEAD实测由约32.8秒降至20.8秒，原因是每快照从四次CLOC调用收敛为一次。普通EI
代表路径由4.09秒变为4.24秒；`common/simion`代表路径由原先约2.99秒但漏测消费者，变为137.21秒并
完整覆盖multipole、三个RF项目及RF→oaTOF integration。全范围脚本去重后的预计运行时间约265.6秒。
用户据此批准把GitHub L1整job超时由5分钟调整为8分钟，为checkout、Python环境和锁定依赖安装保留
余量；该上限调整不改变普通push的changed-scope运行集合。
