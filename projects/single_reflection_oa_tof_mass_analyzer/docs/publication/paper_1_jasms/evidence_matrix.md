# Paper 1：JASMS当前证据矩阵

> `STATUS: LIVE_INDEX / NO_RESULT_COPY`
>
> `LAST_REVIEW: 2026-08-26`

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
| C0理论与声明闭合 | [`stage_c0_theory_closure.md`](stage_c0_theory_closure.md) | `PASS_CONTINUE / THEORY_ONLY` | 不含source cohort、直接粒子或性能证据 |

## 2. 主claim证据

| Claim | 已有直接证据 | 当前等级 | 主要缺口 |
|---|---|---|---|
| J1：切向closure与条件厚度分离 | [`20260817 observed-source归因`](../../history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md) | `PRIOR_ART_OVERLAP / DIAGNOSTIC_FRAMEWORK` | N=100、单设计、post-hoc移植；且非线性相关与finite spread已有先例，不能独立承担新颖性 |
| J2：focusability projector预测残差floor | [`C2 total-variance revision`](../../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/paper1_stage_evidence/C2/20260825_144300__total_variance_j2_j3_revision/stage_conclusion.md) | `AXIAL_TOTAL_OBJECTIVE_INCONCLUSIVE_REVISE` | 已纳入条件均值方差和条件厚度；两源的source-weighted相对未加权增益符号相反，未得到跨源J2优势。完整6D covariance-only、真实场和峰形/传输检验仍缺 |
| J3：第三区的独立高阶控制方向及其有限束宽价值 | [`T5 2.2 mm理想模型验收`](../../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260817_122700__analysis__python__three-zone-t5/stage_receipt.json)显示：在两区已闭合`D1/D2`后，三区保留的`Γ3`方向可把冻结1D、2.2 mm轴向束宽的`σ_t`从0.816 ns降至0.182 ns；[`C2_J3 v2 revision`](../../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/paper1_stage_evidence/C2_J3/20260826_015500__ideal_axial_direction_v2/stage_conclusion.md)以当前哈希冻结的理论合同，在两种冻结源条件下通过导数、步长、零空间及 locked improve/zero/worsen 排序门槛；C3真实PA的五点N=1路径均已贯通 | `IDEAL_AXIAL_PASS_CONTINUE / C3_N1_FUNCTIONAL_ONLY / HIGH_OBVIOUSNESS_RISK` | N=1不支持导数或性能。仍须完成N=100五点中心差分、事件拓扑稳定性、独立轴场积分器、完整6D传输/峰形、多质量与公平结构比较 |
| J4：source-weighted优于未加权closure | solver-free two/three比较与`Γ3` | `PRIOR_ART_OVERLAP / LOCAL_SCALAR_ONLY` | 相同预算A–D公平重优化和blind test全部缺；只能作为J2/J3次级结果 |
| J5：诊断决定改分析器还是改源 | 历史结论提出下一阶段问题 | `PRIOR_ART_OVERLAP / HYPOTHESIS_ONLY` | 至少两源工况的事前决策和独立验证缺失；一般source/analyzer权衡已知 |

## 3. 先行工作门禁

| 门禁 | 当前证据 | 状态 | 仍需关闭 |
|---|---|---|---|
| 定向论文与引用链预审 | [`2026-08-25审计`](../prior_art_search_audit_20260825.md)及[`逐式claim chart`](../prior_art_equation_claim_chart_20260825.md) | `FOUR_LOCAL_MAIN_TEXTS_REVIEWED` | 2015/2026 SI、其他closest-work全文、扩展引用链与独立专家复核 |
| 专利族预审 | 同上，覆盖SVCF、RF guide/conditioner、OA guide mode、spatial-temporal correlation和upstream conditioner代表族 | `PRELIMINARY_LANDSCAPE_COMPLETE` | 具体conditioner逐权利要求、continuation/法域状态和专业FTO |
| J2/J3同构先例 | 定向检索及四份本地主文本均未发现完整同构组合；Yefchak 1989进一步加重J3明显性风险 | `NO_DIRECT_HIT / NOT_CLEARANCE` | 剩余正文/SI、引文扩展与领域专家独立复核 |

## 4. 当前真实源相关证据

| 证据 | 已证明 | 未证明 |
|---|---|---|
| [`三区完成结果快照`](../../history/20260823__three-zone-completed-results-snapshot.md) | 一维三区理论、N=100真实PA和固定设计源敏感性已完成 | N≥1000、条件模型、可补偿性、COMSOL/CAD和工程资格 |
| [`observed横向敏感性`](../../history/20260817__three-zone-observed-transverse-sensitivity.md) | 同一N=100 ID下横向恢复是较小但可测增量 | 横向普遍不重要、连续真实handoff或统计稳定性 |
| [`observed z-vz归因`](../../history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md) | 固定设计中observed-affine残差主导首尾顺序退化 | 该残差不可补偿、是光滑高阶曲线或可推广到其他工况 |
| RF→OA integration observed authority | S1的N=1000母cohort/900 handoff同步真实PA筛查提供875个所选时刻状态；S2的N=1000母cohort/914 handoff筛查提供828个所选时刻状态。两源均由冻结脉冲计划和detector-blind selector选择，且母分母与损失账本保留 | [`C1 source contract`](stage_c1_source_contract.md)为`PASS_CONTINUE`：只证明两源各自可稳定识别；它不比较模型相等性，也不升级为J2/J3或性能结论 |
| S1 connector-gap fixed integration pulse | 同一N=1000母 cohort / 900 handoff ID下，0 mm 在其 integration 脉冲时有875个适格状态、873个检测器命中；51.2 mm 在其 integration 脉冲时为0个适格、0个检测器命中，所有损失保留 | [`connector-gap paired-source contract`](connector_gap_paired_source_contract.md)为`FAIL_STOP`：排除51.2 mm gap作为当前固定脉冲的配对残差/性能候选；不支持“gap降低残差”或J2/J3，不可用历史时间窗结果替代 |
| C2 ideal axial total-objective revision | 两源的解析/有限差分`g`、`G`步长平台、两区零控制、三区改善/零效/恶化的锁定排序均闭合；目标同时含条件均值方差和条件厚度 | 对J2：`INCONCLUSIVE_REVISE / STOP`，不得进入三维。对预注册拆分的J3：`PASS_CONTINUE / IDEAL_AXIAL_ONLY`，只允许冻结一份C3_J3真实场局部导数合同；不允许借此恢复J2、FWHM、传输或普适结构优越性主张 |

## 5. 证据资格结论

当前仓库足以支持以下写作动作：

- 按收窄后的J2/J3中心问题写核心全文骨架、Introduction和claim-safe相关工作；
- 写Theory和Methods草案，但结果数字、摘要结论和新颖性措辞必须留空；
- 设计并预注册Paper 1 campaign；
- 把现有N=100结果作为hypothesis-generating历史证据。

当前仓库不足以支持：

- JASMS摘要中的定量focusability claim；
- 条件残差构成架构极限的结论；
- 三区对真实源优于二区的投稿结论；
- source-weighted设计优越性；
- “必须改源而不能改分析器”的普遍判断；
- 任何`first/novel`措辞。

## 6. 更新规则

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
