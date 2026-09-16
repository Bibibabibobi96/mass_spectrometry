# 代码规模、重复与复杂度深审

DOC_STATUS: ARCHIVED_READ_ONLY

本次按用户要求审查代码量是否过多，冻结基线为`6b2445a4d8e89bafe57aa7d3b390def47216e75a`。
这是审查与候选决策，不是删减实施记录；不修改科学源码，不打断另一Agent的MR工作。
当前开发规则仍以[开发标准](../DEVELOPMENT_STANDARDS.md)为准，本页不新增代码量硬门禁。

## 结论与证据强度

代码膨胀的怀疑有依据：增长快、规模集中，且已确认重复执行机制、参数双份运输、失去消费者的测试辅助链、
诊断入口长期化和大量源码形状断言。问题不能通过压缩JSON、压行、拆更多文件或把代码搬进common解决。
目前证据也不支持“32万行中一半都能删除”：科学分析、边界验证、生成配置和求解器适配占据真实需求。

最优先对象是集成编排和测试结构，其次是MR执行包装与公共生命周期重复。六/八极小包装及独立科学公式
已经有合理复用，不应为统一外观继续抽象。下文的影响范围不是可删量，候选之间也不能直接相加。

## 同口径规模与增长

工具为CLOC 2.10；调用仓库`common/report_cloc_delta.ps1`，固定提交快照，开启skip-uniqueness，
复用其文件过滤、production/tests分类和MATLAB/Lua/GEM语言定义。排除artifacts、generated、vendor、
run、任意docs/history载荷及根scratch；按入口用途分类，不把tests目录一律算测试。未提交MR文件不计入基线。

| 基线 | 文件 | production code | tests code | unclassified code | total code |
|---|---:|---:|---:|---:|---:|
| 7月31日 `b9fd71b5` | 913 | 105,425 | 43,025 | 318 | 148,768 |
| 8月30日 `b2f4bb4b` | 1,208 | 164,292 | 64,130 | 0 | 228,422 |
| 9月16日 `6b2445a4` | 1,615 | 230,406 | 94,203 | 0 | 324,609 |

相对8月末增加96,187 code（42.1%）：production增加66,114，tests增加30,073，文件增加407。
相对7月末增加175,841（118.2%）。历史快照都用本次同一个分类器重算；旧版历史报告不混用。
按路径职责分类，8月末以来分析增加31,392、运行编排增加16,375、合同配置增加9,557、
求解器模型增加4,290、其他工具增加4,500、测试增加30,073；职责分类是定位线索，不等于人工判断算法价值。

| 当前语言 | 文件 | code | 其中production | 其中tests |
|---|---:|---:|---:|---:|
| Python | 755 | 213,075 | 125,223 | 87,852 |
| JSON | 488 | 48,572 | 48,462 | 110 |
| PowerShell | 150 | 40,426 | 39,364 | 1,062 |
| MATLAB | 110 | 12,934 | 9,436 | 3,498 |
| Lua（含Fly2） | 98 | 9,208 | 7,527 | 1,681 |
| GEM/TOML/YAML | 14 | 394 | 394 | 0 |

因此32.46万不是32.46万行业务算法；扣除测试及production JSON/YAML/TOML后，运行/分析/模型等代码为181,806。
但测试和配置同样需要维护，不能因为不属于业务算法就忽略。JSON中68份Schema为9,796 code，
9份以resolved命名的文件为2,929，其余411份为35,847；该命名分组不意味着其余全为手写，亦不授权删生成视图。

| 当前区域 | 文件 | production | tests | 合计 |
|---|---:|---:|---:|---:|
| RF→OA integration | 367 | 73,512 | 29,686 | 103,198 |
| common | 392 | 50,197 | 26,859 | 77,056 |
| MR-TOF | 217 | 38,283 | 14,260 | 52,543 |
| OA-TOF | 268 | 36,701 | 10,607 | 47,308 |
| 四极杆 | 175 | 16,341 | 8,104 | 24,445 |
| 双锥 | 38 | 3,281 | 811 | 4,092 |
| 八极杆 | 53 | 3,147 | 897 | 4,044 |
| Wehnelt | 21 | 2,371 | 1,231 | 3,602 |
| 加速器 | 24 | 2,161 | 804 | 2,965 |
| 六极杆 | 37 | 2,112 | 638 | 2,750 |
| EI源 | 17 | 1,074 | 306 | 1,380 |
| 根配置及其他 | 6 | 1,226 | 0 | 1,226 |

前四块占86.3%。production中78文件超过600 code、30文件超过1,000 code；最大的20个production文件合计39,819。
大文件不自动等于坏设计，但已经足以优先审查职责与修改波及面。

## 高优先级发现

### F1：集成已形成巨型编排核心

[单飞runner](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runtime/run_single_flight.ps1)
为6,145 code；2774、3208、约3510行的fine/local/overlay重复维护资源请求、规划、首项观察、
重新规划、进程specification、完成回调与wave执行。外围机制可共用，几何、边界条件、cache key及恢复资格必须分开。

[prepare](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/workflows/family_source_closure/prepare.py)
为5,142 code；`prepare_family_source_closure`单函数跨3276–5365行，含211个if/loop/try等AST控制节点，
该数不是圈复杂度。`build_successor_program`跨1,890物理行，`analyze`跨1,098物理行也属于重点。
先消除重复协议与分清阶段，再决定模块分割；仅拆文件不会降低总维护量。

### F2：同一执行参数被复制运输，再写代码证明两份一致

prepare的5332行起从`execution_steps[0].arguments`的name=value列表再构造
`resolved_execution_plan.json`。相邻`adapter.ps1:474–543`重新解析两者，逐字段比较，再选择其中一份。
这是真实双运输机制，adapter自身为1,962 code；并非两份独立科学真值的必要校验。

建议新活动计划只引用一个冻结执行参数文件及其身份；campaign/row/source身份检查保留。
同步composition plan、编译器、adapter和测试，历史计划保持只读；不为迁移再造长期双入口。

### F3：测试绑定源码写法，阻碍等价提炼并提供有限行为保证

`test_runtime_run_local_contract.py`与`test_domain_split_runner_contract.py`合计包含592个assertIn、
110个assertNotIn，部分绑定局部变量名、完整表达式与fine/local分支排列，实际由integration门禁执行。
全仓175个Python测试文件同时存在read_text与包含/正则断言，这是筛查信号，不表示175个文件都无用。

代表位置：公共`test_artifact_retention.py:334–357`、`common/multipole/test_family_contract.py:177`、
`test_resource_budget.py:229`、四极`test_comsol_workflow_architecture_contract.py:285`。
已有真实PowerShell函数/假进程行为测试，应把重复的形状断言改为冻结输入→阶段/输出/错误的参数化回归。
继续保留关键架构禁令；不要削掉NaN、粒子身份、时钟、结果一致性与失败证据测试来换行数。

上一轮新增的[路径测试](../../common/paths/test_common_artifact_paths_contract.py)也有问题：17行硬锁16个消费者，
22–36行锁定源码条件，48行锁定nargin写法。它只能证明指定代码文字存在，不能证明路径运行行为。
应取消固定数量，保留入口迁移检查，并用无需COMSOL的MATLAB路径回归覆盖实际边界。

### F4：已有明确无消费者的历史测试辅助链

[family workflow测试](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/tests/test_family_source_closure_workflow.py)
的`migrate_v3_campaign:318–427`仅由`write_current_policy_campaign:430–435`调用，后者没有调用者；
活动全仓搜索仅命中两定义与内部调用，模块没有globals/getattr/eval/exec式动态分发，这些名字也不被unittest自动发现。
这是约118物理行的高置信删除候选，尚未实施CLOC减量。相邻`use_current_time_grid_profile`仍有调用，不能整区删除。

### F5：公共文件治理又复制了安全执行器

[容量处置](../../common/contracts/reconcile_artifact_capacity.py)、[retention](../../common/contracts/artifact_retention.py)
及[退休](../../common/contracts/solver_review_retirement.py)分别维护SHA清单、pending、删除和完成状态；
包括上一轮新代码。准入条件与receipt科学语义确实不同，但按冻结清单执行删除的底层机制可共用。
容量模块还混合TTL、扫描、计划、执行和CLI；三个消费者导入其私有保护函数，compact通过局部导入避循环。

先收敛已有多消费者的保护租约和精确删除职责，保留身份重验、清单外新文件保护和部分失败证据。
不要把“提炼”做成增加万能回调/插件框架。其他直接候选包括退休的`_sha:43`与公共`file_sha256`重复。

### F6：公共PA缓存提炼未完全替代原实现

`common/simion/pa_family_cache.py:184,395`与`cache_generation.py:116,146`仍分别计算具名库存和
8MiB复制/flush/fsync，前者已导入后者其他公共原语。可复用已有字节操作，保留排序、只读属性和异常协议。
两个generation身份协议不能只因相似就合并，否则影响冻结cache身份与历史消费者。

### F7：MR基础包装和私有并发仍多份并存

MR的34个非测试PowerShell文件中有23个项目Python启动包装、9个别名路径映射定义。
`run_analyzer_local_workbench.ps1:29`和`run_local_operating_pa_prewarm.ps1:27`各自管理进程循环；
`run_two_prism_trial.ps1:932`已经使用公共执行器。相应测试还要求私有函数名存在。

复用公共环境恢复/验证复制和进程执行协议，保留MR任务生成。PA库存/合成与粒子flight不是同一负载，
不能照搬flight观测窗口。Python另有8组、23份至少5行的相同AST实现候选；finite组对bool策略不同，
只在相同语义组内合并。这些数量有重叠，不能加为“可删脚本数”。

### F8：专项诊断的退出条件没有落实到代码生命周期

MR的`r27_source_return_correlation.py:31,189–250`及其PS入口绑定r27和N=100，主要由自身runner与测试引用，
current入口文档未发现导航。决策应是通用cohort相关分析或关闭后退役两生产文件；相关分析算法本身仍有价值。
四极的`ReleaseConstructionGate`分支散布在runner与MATLAB构建中，COMSOL文档仍登记活动诊断，
不能据旧桥接退役就删整个gate；需明确保留场景并隔离诊断，或在其任务关闭后一起退役入口和专属测试。

### F9：已有实现没有被另一条同语义路径复用

`common/multipole/runtime_profile.py:43`内联源/数值解析，同文件303、359、384行已有campaign消费的函数，
普通profile路径可直接复用；四极interface/mass-filter两个SIMION runner又复制首批观察和重规划流程，
应收敛到已有`runtime/simion_execution.ps1`。两项估计80–120及60–120物理行净减，仅作实施前粗估。

公共与四极MATLAB的首次正向穿越插值也相似（`solve_finite_3d_transport.m:1333`与
`solve_deterministic_rf_quadrupole_particles.m:489`）；合并前核对NaN间隙、反向、单位、时间与canonical附加列。

### F10：策略既在配置声明，又被实现和测试锁死

`common/multipole/resource_budget_support.ps1:580,726,760`要求45秒及固定1GiB/512MiB余量，
测试又匹配这些文字。调整一个策略会扩散到配置、代码、测试三处。应由冻结策略传入，代码检查合法范围和
确有依据的不变量，测试验证压力行为；不能把资源保护整体删除。

## 不支持直接删除或强制合并的范围

- 主机调度解决跨任务准入，SIMION批次规划解决本次任务内部并发，两者不是重复系统。
- OA的两种并行工作流可以共用粒子分批身份，但case并发与同源cohort分批不同，不能合成同一科学workflow。
- 加速器`accelerator_time_focus.py:930`的同义字段/default适配是活动CLI，属于收敛作者格式候选，不是死代码；理论核心保留。
- 六/八极生产wrapper约12–19物理行，已调用公共实现；双锥两小入口也已复用气体场原型，不再造包装器生成器。
- EI与Wehnelt几何/电离/发射物理不同；把它们合成通用模型DSL可能增加维护负担。
- 488份JSON只有一组完整语义重复：octupole publication普通/diagnostics两路径；普通路径有多份绑定消费。
  需查历史外部引用后处理诊断副本，不能借此声称配置大面积可删。61份exploration也不是因为未列active campaign就失效。
- 原生组件参考、独立理论/数值对照与已注册生成resolved视图不能按文件名删。压缩JSON只改变行数外观。

## 建议实施顺序与验收

| 顺序 | 边界 | 完成判据 |
|---|---|---|
| 1 | 无消费者测试辅助链、重复SHA/库存、已有profile解析复用 | 实际调用链保持、负例保留；CLOC production/tests/total分别记录，新增机制不抵消主要收益 |
| 2 | 精确删除执行、MR/四极重复编排、单飞refine外围 | 同输入结果、取消/失败收尾、首批不重复、缓存与manifest身份一致；入口脚本总数不膨胀 |
| 3 | 单份冻结执行参数及巨型prepare阶段边界 | 单权威、历史只读、干净checkout可运行；逐个现有workflow闭合后迁移 |
| 4 | 源码形状测试去重、诊断生命周期逐项决策 | 保留可说明具体故障的行为回归，退役时连入口/测试/注册一起减少 |

不预先承诺减到20万或减半。小型精确重复只解释少量行数，大幅收缩必须解除双合同、重复执行和长期诊断等
职责负担。第一批需要用实测减量证明路线有效；仅搬目录、拆模块、压行或把重复改成复杂配置框架都不算瘦身。
合并存在共用缺陷扩大影响面的风险，因此先从低风险机制开始，科学公式与真实求解等价另行验收。

## 覆盖、复现与限制

Agent 0做固定提交全量CLOC、增长、AST/JSON/PowerShell扫描与交叉核实；Agent 1审公共机制与测试，
Agent 2审integration/OA/加速器，Agent 3审MR，Agent 4审其余项目及公共科学代码。共盘点1,615文件；
755份Python解析成功、7,523函数，150份PowerShell解析成功，488份JSON可解析。MATLAB/Lua/GEM以
规模盘点和代表性科学/调用链审查覆盖，不宣称逐行读完32万行或完成供应商语义验收。

Python严格相同body+参数、忽略函数名/docstring、至少12物理行的扫描仅得5组（production 3组），
这说明“大块机械复制”不足以解释规模；缩短门槛会发现更多小helper，但上下文/全局变量仍需人工核对。
8份PowerShell含超过500字符的行，最极端4,011字符；49行runner也可隐藏复杂流程，物理行不是可读性证明。

可复现机器记录位于工作区`artifacts/common/capacity_disposal_receipts/`：
`code-size-by-file-20260916.json`、`code-structure-audit-20260916.json`、`code-powershell-audit-20260916.json`、
`code-growth-july_end-20260916.json`、`code-growth-august_end-20260916.json`。
增长报告包含全部language的files/blank/comment/code及delta；分类器与过滤口径跟随固定源码。
临时提交快照只用于分析，任务完成时清理。审查不运行科学求解或重复全仓L2；报告只做文档门禁。
本次生产/测试实现均未改，`CLOC_DELTA=N/A (docs-only)`；上述增长是历史测量，不是本任务造成的增量。
