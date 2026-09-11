# 2026-09-11 根参考文档整治快照

DOC_STATUS: ARCHIVED_READ_ONLY

本记录冻结文档整治前的规划台账与日期化 Fly 审计，保留当时的判断及尚未裁决事项。
它不证明这些状态在归档日仍成立，也不授予实现或物理资格。源码基线为 `45a67415`；
并行任务中的未提交改动不属于本记录的核验结论。原运行及 manifest 未移动或改写。

当前规划见[路线图](../ROADMAP.md)，公共 SIMION 能力见[实现入口](../../common/simion/README.md)。

## 原 ROADMAP 台账

### 当前复杂度整顿台账（2026-08-25）

本表是当前、可关闭的简化候选的唯一计数位置；日期化审计只保留当时证据。`E`表示尚未形成
可安全修改方案，不计入可直接实施项。每项关闭前必须有对应的行为测试和 L1/L2 证据。

|分类|数量|状态|已验证事实与下一步|
|---|---:|---|---|
|A 必须保留|3|保留|原始 artifact/manifest 身份闭合；独立 SIMION batch/case 的 CPU、内存与已观测画像调度；oaTOF Candidate 的跨 COMSOL/SIMION/SolidWorks 阶段串行。|
|B 可简化|0|无待办|三域 runtime ID 投影与嵌套 changed-gate 路由测试已分别在 `34bc315`、`a40a599` 关闭；RF 四极杆 SIMION 入口已改为接受任意正数的步数/trajectory quality，并将偏离资格基线的实际值冻结且标记为未资格探索。|
|C 建议删除|0|无待办|尚无同时具备零消费者、低风险和行为等价证据的项。|
|D 防御不足|0|无待办|当前直接 SIMION 路径均是共享 PA/IOB、混合物种单次飞行或 Formal 单次证据；没有证据表明可无损并发。|
|E 需证据|3|审查中|①集成运行时剩余实现形状测试：先补行为等价后再删；②`prepare.py`/`adapter.ps1` 的大函数：先建立数据流与职责切分证据；③仍串行的 SIMION 路径：已盘点的活动独立 case/batch 均经共享调度器；`mass_spectrum_candidate` 仍是单份混合物种 fly/CSV，RF 四极杆 `Invoke-RfSimionCoreRun` 仍在一个 candidate 目录顺序改写 `quad_monolithic.pa#/.iob`，因此只有建立独立分片、输出合并及缓存隔离合同后才迁入。已关闭：④MATLAB 旧 1001 点 direct-KDE 与 Python 同网格设置在 2026-08-25 对同一 90 粒子 COMSOL CSV 逐值一致；MATLAB 仅保留非权威可视化，Python 4001 点 canonical 指标是唯一资格/发布 authority。|

商业 Candidate 串行结论已在 2026-08-25 以真实 COMSOL R2025b N=100 对照验证：并行
`20260825_160301__test__comsol__oatof-candidate-parallel-a__n100` 在 `SolverSequence.runAll` 报
COMSOL Java `NullPointerException`，并行
`20260825_160302__test__comsol__oatof-candidate-parallel-b__n100` 未在 120 s 内写出首份报告而被入口
清理；两者均保留 failed manifest。相同冻结合同的单实例
`20260825_160401__test__comsol__oatof-candidate-serial-control__n100` 成功，100/100 命中、10/5 环、
6 个时间窗 token，平均飞行时间 71.3528086363 µs，manifest PASS，且未修改 Formal。两实例可以同时
取得许可证和启动 server，但这不足以证明真实求解可靠；当前不增加新的商业并发调度器，也不放松
campaign 的串行限制。`run_n100_candidate_functional.ps1` 同时修复其冻结输入父目录、候选 run-config
绑定与真实 artifact MPH 输出路径，属于测试入口恢复既有公共合同，不改变物理或数值定义。

因此当前**已确认但未关闭的候选为 3 项，均为 E**；没有已证实而未处理的 B/C/D 项。此计数不等同
“全仓审计完成”：每完成一个审查域，新增的已证实候选必须先登记到本表，不能用推测补数。

`prepare.py` 与 `adapter.ps1` 的职责盘点已完成：前者按一个冻结状态依次完成 campaign 选择、authority/
source 解析、layout/profile、pulse/source materialization、resolved 产物和 execution-plan 发布；后者只
完成 plan→frozen inputs→runtime→receipt 的生命周期闭合，未实现物理公式或统计指标。它们之间不存在
不依赖前序冻结状态的可安全抽取块；当前拆分会把同一状态转发给多个薄 helper，增加而非减少依赖边。
`0790f90` 已收拢前者的重复 JSON 写入边界（不改变字节格式），但大型职责拆分仍保留为 E，直到能以独立
输入/输出合同和行为回归证明净收益。剩余 runtime 形状测试同样不能只按字符串数量删除：抽样确认其中
仍覆盖 Python fixture 未模拟的 PowerShell adapter→runner 接线、产物归属和失败关闭顺序。

启动未来平台任务的触发条件包括：相同运行协议已在至少两个项目稳定复用、一次合同修改需要同步三个
以上入口、轻量门禁时间显著妨碍普通提交，或artifact清单扫描成为日常等待的主要部分。完成判据不是
“增加框架”，而是减少重复真值、缩小变更影响范围，并保持现有正式资产和失败证据可追溯。

## 原生产 Fly 审计

## 生产 SIMION Fly 入口审计

审计日期：2026-08-31。范围为当前可由工作流启动的生产或候选 Fly；测试、历史回放和只读分析编排不计入。
公共调度职责由 [resource_scheduler.py](../../common/simion/resource_scheduler.py) 唯一承担：并发、分批、内存风险和 45 s 首批观测。
项目侧只能提供冻结的粒子总数、独立性、数值资源身份和启动规格。

| 入口 / 消费者 | 公共 scheduler | 项目侧批处理与合并 | 预算、租约、清理 / 记录 | 处置 |
|---|---|---|---|---|
| `common/multipole/run_simion_finite_3d_transport.ps1`（quad/hex/oct 传输） | 是 | 公共 plan；Python 按 offset 合并 state、trajectory、summary | 工程预算、host lease、retention、manifest/failure 均有 | 当前参考实现 |
| `rf_quadrupole_ion_optics/workflows/interface_readiness/run_simion.ps1` | 是，但有私有执行层 | 私有 batch Fly2/state/Lua/log 与 merge | 无公共 lease、冻结 resolved budget、retention | 迁移到公共执行适配层后删除私有投影/合并 |
| `rf_quadrupole_ion_optics/workflows/mass_filter_reference/run_simion.ps1` | 是，但有私有执行层 | 同上 | 同上 | 同上 |
| `integrations/.../runtime/run_single_flight.ps1` | 是 | 项目特有 handoff/trace continuation；不可退化为通用 CSV 合并 | 有 stage budget、lease、capacity cleanup、retention、manifest | 保留 handoff 语义；以后只抽取重复的 formal-first/batch 编排 |
| `single_reflection_oa_tof_mass_analyzer/workflows/formal_reference/run_formal_validation.ps1` | 否 | 单直接 Fly | 有 run/manifest；无 scheduler、预算、lease、retention | 迁移为共享 single-batch adapter |
| `single_reflection_oa_tof_mass_analyzer/workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1` | 否 | 单直接混合物种 Fly | 有 manifest；无 scheduler、预算、lease、retention | 迁移为共享 single-batch adapter |
| `single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py` → `run_n100_transport.ps1` | 否 | 直接 Fly | 无共享运行治理 | 与候选链一并迁移或明确退役 |
| `integrations/.../stages/cross_solver/run_analyzer_transport.ps1` | 否 | 单直接 Fly | 有 stage manifest/retention；无 scheduler、lease | 接入共享 single-batch adapter；若不再公开执行则退役 |

`common/multipole/run_simion_transport_campaign.ps1` 只做 campaign 分析编排，不是 Fly 入口。

### 最小迁移顺序

1. 在 `common/simion` 建立单/多批执行适配层，接收冻结 dispatch request 和项目回调，统一调用 scheduler、host lease、retention 与 manifest 记录。
2. 以同一冻结 N=1 输入对照后迁移 RF 四极杆两个私有入口，删除重复 batch 投影和合并。
3. 迁移 OA-TOF Formal、mass-spectrum 和 design-candidate 的直接 Fly 旁路；single-batch 仍必须经过共享层。
4. 迁移或退役 cross-solver 下游入口。不得在同一运行中同时保留两套并发、内存或批大小决策。

迁移的验收是同一冻结输入的 N=1 逐粒子终态一致，随后以小样本核对命中/损失分类和聚合指标；不以历史兼容为目的，也不改变物理合同。
