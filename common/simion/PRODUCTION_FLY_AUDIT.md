# 生产 SIMION Fly 入口审计

审计日期：2026-08-31。范围为当前可由工作流启动的生产或候选 Fly；测试、历史回放和只读分析编排不计入。
公共调度职责由 [resource_scheduler.py](resource_scheduler.py) 唯一承担：并发、分批、内存风险和 45 s 首批观测。
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

## 最小迁移顺序

1. 在 `common/simion` 建立单/多批执行适配层，接收冻结 dispatch request 和项目回调，统一调用 scheduler、host lease、retention 与 manifest 记录。
2. 以同一冻结 N=1 输入对照后迁移 RF 四极杆两个私有入口，删除重复 batch 投影和合并。
3. 迁移 OA-TOF Formal、mass-spectrum 和 design-candidate 的直接 Fly 旁路；single-batch 仍必须经过共享层。
4. 迁移或退役 cross-solver 下游入口。不得在同一运行中同时保留两套并发、内存或批大小决策。

迁移的验收是同一冻结输入的 N=1 逐粒子终态一致，随后以小样本核对命中/损失分类和聚合指标；不以历史兼容为目的，也不改变物理合同。
