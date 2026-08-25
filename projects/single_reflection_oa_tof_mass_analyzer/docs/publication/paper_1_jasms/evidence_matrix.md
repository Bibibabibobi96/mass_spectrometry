# Paper 1：JASMS当前证据矩阵

> `STATUS: LIVE_INDEX / NO_RESULT_COPY`
>
> `LAST_REVIEW: 2026-08-25`

本表只索引当前证据和缺口，不复制run数字、manifest清单或history叙事。`SUPPORTED`表示证据满足该
claim的完整投稿要求；目前没有主claim达到`SUPPORTED`。

## 1. 基础能力

| 能力 | 当前证据 | 状态 | 投稿用途与限制 |
|---|---|---|---|
| N=2双区精确时间和焦面 | [`oaaccelerator_time_focus.md`](../../theory/oaaccelerator_time_focus.md)及测试 | `PROJECT_ORACLE` | 经典基础，不是创新 |
| affine `z-v_z`耦合 | [`z_vz_linear_phase_space_coupling.md`](../../theory/z_vz_linear_phase_space_coupling.md)及测试 | `PROJECT_ORACLE` | 已知相关聚焦特例 |
| 二级reflectron精确时间 | [`dual_stage_reflectron.md`](../../theory/dual_stage_reflectron.md)及测试 | `PROJECT_ORACLE` | 经典基础，不是创新 |
| 一维整机耦合 | [`oatof_oaaccelerator_coupling.md`](../../theory/oatof_oaaccelerator_coupling.md)及测试 | `PROJECT_ORACLE` | 参考面和低阶闭合基础 |
| N=3、`A1–A4`、`Γ3` | [`three_zone_accelerator_ideal_theory.md`](../../theory/three_zone_accelerator_ideal_theory.md)及测试 | `PROJECT_ORACLE / PROVISIONAL` | 三区不是创新；100 Th理论身份 |
| 524 Da N=1000双求解器Formal | [`PROJECT.md`](../../PROJECT.md)与机器合同 | `FORMAL_REFERENCE` | 理想项目基线；不是RF observed source的Paper 1闭环 |

## 2. 主claim证据

| Claim | 已有直接证据 | 当前等级 | 主要缺口 |
|---|---|---|---|
| J1：切向closure与条件厚度分离 | [`20260817 observed-source归因`](../../history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md) | `DIAGNOSTIC / HYPOTHESIS_GENERATING` | N=100、单设计、post-hoc移植；无条件模型、两工况、重新优化或独立求解器 |
| J2：focusability projector预测残差floor | 无 | `NOT_IMPLEMENTED` | 条件协方差、`g`、`G_N`、约束、QP、locked test均缺 |
| J3：残差模态归因 | observed-affine残差与多项式捕获诊断 | `PARTIAL_SOURCE_DIAGNOSTIC` | 没有无量纲条件模态、bootstrap、逐模态消融或预测验证 |
| J4：新增场区的source-weighted收益 | solver-free two/three比较与`Γ3` | `LOCAL_SCALAR_ONLY` | 没有`a_perp/DeltaJ`、observed-source公平重优化或blind test |
| J5：source-weighted优于未加权closure | 无 | `NOT_IMPLEMENTED` | 相同预算A–D架构比较全部缺 |
| J6：诊断决定改分析器还是改源 | 历史结论提出下一阶段问题 | `HYPOTHESIS_ONLY` | 至少两源工况的事前决策和独立验证缺失 |

## 3. 当前真实源相关证据

| 证据 | 已证明 | 未证明 |
|---|---|---|
| [`三区完成结果快照`](../../history/20260823__three-zone-completed-results-snapshot.md) | 一维三区理论、N=100真实PA和固定设计源敏感性已完成 | N≥1000、条件模型、可补偿性、COMSOL/CAD和工程资格 |
| [`observed横向敏感性`](../../history/20260817__three-zone-observed-transverse-sensitivity.md) | 同一N=100 ID下横向恢复是较小但可测增量 | 横向普遍不重要、连续真实handoff或统计稳定性 |
| [`observed z-vz归因`](../../history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md) | 固定设计中observed-affine残差主导首尾顺序退化 | 该残差不可补偿、是光滑高阶曲线或可推广到其他工况 |
| RF→OA integration历史observed authority | 有冻结pre-pulse状态和有序ID基础 | 当前活动Paper 1 source campaign、两工况和locked split |

## 4. 证据资格结论

当前仓库足以支持以下写作动作：

- 写Introduction中的问题动机；
- 写Theory和Methods草案；
- 设计并预注册Paper 1 campaign；
- 把现有N=100结果作为hypothesis-generating历史证据。

当前仓库不足以支持：

- JASMS摘要中的定量focusability claim；
- 条件残差构成架构极限的结论；
- 三区对真实源优于二区的投稿结论；
- source-weighted设计优越性；
- “必须改源而不能改分析器”的普遍判断；
- 任何`first/novel`措辞。

## 5. 更新规则

新证据只有在以下字段齐全时加入本表：

```text
claim_id
source cohort and ordered-ID hash
field/geometry/numerics identity
particle count and mass/source condition
metric and denominator definition
run/history/manifest reference
independent validation
evidence level
known limitation
```

结果数字留在summary/history，本文只更新资格和引用。
