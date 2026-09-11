# Paper 1：当前证据矩阵

本页是论文证据资格的汇总入口；精确结果留在来源报告，预注册门槛留在阶段合同。
`SUPPORTED` 表示满足相应主张的完整投稿要求；目前没有主 claim 达到该状态。
新颖性及允许措辞只查 [claim 注册表](../prior_art_claim_registry.md)，研究步骤见
[研究与证据计划](validation_and_evidence_plan.md)。

## 基础与阶段

| 对象 | 当前资格 | 依据与下一道门槛 |
|---|---|---|
| 双区、三区、反射器与一维整机模型 | `PROJECT_ORACLE`；三区部分为 `PROVISIONAL` | [理论入口](../../theory/README.md)；经典基础不作为创新 |
| 524 Da 双求解器冻结设计 | `FORMAL_REFERENCE` | [PROJECT](../../PROJECT.md)；不是 RF 真实源的论文闭环 |
| C0 理论与接口 | `PASS_CONTINUE / THEORY_ONLY` | [C0 记录](stage_c0_theory_closure.md)；不含源或粒子性能 |
| C1 两种源的历史识别 | `DEVELOPMENT_ONLY` | [源合同](stage_c1_source_contract.md)；新阶段须两份独立母群 assessment 均为 `PROSPECTIVE` |
| Connector-gap 三臂源侧比较 | `DEVELOPMENT_ONLY / SOURCE_ONLY` | [三臂合同](stage_c1_connector_gap_triplet_contract.md)与[机制证据](connector_gap_working_point_mechanism_20260827.md)；不能复用为新锁定测试 |
| J2-0 当前工作点复现 | `CURRENT_FUNCTIONAL_REPRODUCTION / DEVELOPMENT_ONLY` | [公平 pilot 的前置证据](j2_real_3d_pilot_contract.md)；不是两种预测器的公平比较 |
| C2 轴向总目标 | J2 为 `INCONCLUSIVE_REVISE`；J3 为 `IDEAL_AXIAL_ONLY` | [状态沿革及原来源](../../history/20260911__publication-status-consolidation.md#evidence_matrix)；不得将 J3 的局部闭合升级为 J2 |
| C3_J3 真实 PA | `INCONCLUSIVE_REVISE` | [C3 合同](stage_c3_j3_real_field_contract.md)：N=1 与 N=100 五点平台已完成；独立同段轴场参考待闭合 |
| C4_J3 锁定预测 | `BLOCKED_BY_C3_J3` | [C4 合同](stage_c4_j3_locked_prediction_contract.md)；先核验 C3 五件套，再读取锁定探测器结果 |

## 候选主张与缺口

| Claim | 可用证据边界 | 尚缺什么 |
|---|---|---|
| J1 条件均值与厚度分离 | 历史 observed-source 归因；只作框架 | 非独立新颖性，不承担主方法 claim |
| J2 受约束源加权预测 | 历史轴向总目标不确定；J2-0 仅复现已知机制 | 新前瞻源、同候选池／预算的加权与未加权真实场比较、锁定预测及独立验证 |
| J3 新增控制方向的增量价值 | 冻结一维理论与真实 PA 局部平台 | 独立轴场参考、锁定三维预测、完整六维损失／峰形、多质量与公平结构比较 |
| J4 源加权优于未加权目标 | 当前只能作为 J2/J3 的次级问题 | 同预算重优化及 blind test |
| J5 改分析器还是改源 | 工况条件化假设 | 至少两源的事前决策及独立验证 |

## 结果入口与使用边界

- [三区完成快照](../../history/20260823__three-zone-completed-results-snapshot.md)：一维理论、真实 PA 功能与固定源敏感性。
- [横向敏感性](../../history/20260817__three-zone-observed-transverse-sensitivity.md)：同一小样本下的横向增量，不能外推横向普遍不重要。
- [轴向残差归因](../../history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md)：固定设计中的主导退化，不能证明残差绝对不可补偿。
- [Connector-gap 工作点机制及钟表勘误](connector_gap_working_point_mechanism_20260827.md)：脉冲相对时钟下的模型特定重调收益。
  两个相邻 gap 的共同锁定 ID 群体不同，不能拼成同一三点残差曲线；低传输边界不能承担精密主结论。
- [先行工作审计](../prior_art_search_audit_20260825.md)与[逐式 claim chart](../prior_art_equation_claim_chart_20260825.md)：
  已核对部分主文本；剩余 SI、closest-work 全文、引文链和具体 IP 审查未关闭。

## 当前可写内容

可撰写收窄后的问题、相关工作及 Theory／Methods 草案，设计前瞻验证。
现有证据不支持定量 focusability 投稿结论、架构极限、三区一般优越性、source-weighted 优越性或 `first/novel`。

新增证据必须能追溯 claim、源及有序 ID、场／几何／数值／时钟身份、样本与质量、指标及分母、
run／manifest、独立验证和限制。更新本表时只调整资格与引用，不再次抄录结果数字。
