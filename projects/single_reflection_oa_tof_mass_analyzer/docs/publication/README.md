# OA-TOF 两论文发表计划

> `PROGRAM_STATUS: ACTIVE_PLANNING / NOT_SUBMISSION_READY`
>
> `SEQUENCE: PAPER_1_JASMS_TARGET -> PAPER_2_ANALYTICAL_CHEMISTRY`

本目录按独立科学问题组织两篇论文，不按“理论、模拟、实验”机械拆稿。当前任何论文均未达到投稿
go/no-go；本目录记录候选主张、所需证据和禁止重叠内容，不改变项目Formal资格。

## 1. 两篇论文的中心问题

| 论文 | 中心科学问题 | 必须新增的核心证据 | 不承担的内容 |
|---|---|---|---|
| Paper 1，JASMS目标 | 给定真实有限条件厚度的RF多极杆源，局部高阶closure能消除哪些展宽，受约束分析器控制子空间还可控制多少残差？ | 条件源、focusability、残差模态、公平重优化、三维多工况验证 | 最终conditioner、样机Pareto、真实样品 |
| Paper 2，Analytical Chemistry | 主动相空间匹配能否在实机中移动分辨率—传输—接受度—占空比—灵敏度前沿并改善分析终点？ | conditioner、稳健联合设计、as-built与实测波形、样机A/B、真实分析数据 | 把Paper 1理论重新称为新理论 |

Paper 1以JASMS为明确目标；如果只完成一维理论和有限模拟，或结论仍过度依赖单一私有几何，则不满足
当前JASMS计划，应补证或转向更匹配的期刊，而不是降低证据口径。

## 2. 权威入口

- 共享物理：[`theory/README.md`](../theory/README.md)
- Paper 1范围：[`paper_1_jasms/scope_claims_and_outline.md`](paper_1_jasms/scope_claims_and_outline.md)
- Paper 1验证：[`paper_1_jasms/validation_and_evidence_plan.md`](paper_1_jasms/validation_and_evidence_plan.md)
- Paper 1当前证据：[`paper_1_jasms/evidence_matrix.md`](paper_1_jasms/evidence_matrix.md)
- Paper 2范围：
  [`paper_2_analytical_chemistry/scope_claims_and_new_work.md`](paper_2_analytical_chemistry/scope_claims_and_new_work.md)
- Paper 2验证：
  [`paper_2_analytical_chemistry/validation_and_evidence_plan.md`](paper_2_analytical_chemistry/validation_and_evidence_plan.md)
- 跨论文防火墙：[`overlap_and_claim_firewall.md`](overlap_and_claim_firewall.md)
- 先行工作与候选claim：[`prior_art_claim_registry.md`](prior_art_claim_registry.md)
- 2026-08-25论文/引用链/专利族预审：
  [`prior_art_search_audit_20260825.md`](prior_art_search_audit_20260825.md)

## 3. 共同规则

- 理论文档只维护一套公式；论文计划只说明使用范围和证据。
- history、run和artifact不按论文复制；evidence matrix只链接冻结证据。
- 所有`first/novel/unprecedented`措辞在系统全文、引用链和专利族审查前禁用。
- Paper 1冻结给定source distribution；Paper 2主动改变source distribution。
- 任何性能比较都使用充分重优化的baseline、相同母cohort、相同约束和独立locked test。
- 公开conditioner、电压、波形、自动调谐或制造补偿前先完成公司IP审查。

2026-08-25定向查重已否决J1、J4、J5和Paper 2 A1的宽泛新颖性表述；Paper 1当前只保留J2/J3作为
候选主贡献。该预审没有关闭关键全文逐式claim chart或法律FTO，也没有使任何claim升级为`GREEN`。

## 4. RSI不在当前计划内

当前不建立第三篇RSI论文。只有未来产生可脱离最终分析性能故事、可被其他实验室独立复用的pulser、
电极端波形计量、as-built数字孪生、源相空间诊断或detector/readout创新时，才重新执行独立go/no-go。
仅“做出三区OA样机”不构成拆分RSI的理由。

## 5. 状态转换

```text
candidate claim
-> prior-art cleared
-> evidence planned
-> implementation validated
-> locked evidence complete
-> manuscript claim allowed
```

没有完成上一状态时，不得在摘要、标题或PROJECT中把后续状态写成当前事实。
