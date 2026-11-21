# 匹配场对照与边界输入隔离里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

本页为只读历史入口，不是当前执行规则。当前模型、资格和下一项决策见[PROJECT](../PROJECT.md)。

## 冻结范围

冻结已完成的匹配FEM两档／三档、同入口单镜、实际消费场分层、25点边界输入检查，
以及该阶段的源码发布、批次恢复规划和旧载荷退役记录。它们不能合并成全域或整程收敛声明。
新薄体积donor的表示检查形成另一个具名运行；没有重求场、Refine或飞行。

| 原文 | 来源与身份 |
|---|---|
| [PROJECT.before.txt](20261015__boundary-input-isolation/PROJECT.before.txt) | Git e18114fb 的项目正文；blob 674c9c33e53c8552d6377e6f199bc5ac32bd7695 |

上述UTF-8 LF载荷的SHA-256为 F83AE04BD04DE928F9CF03C464A06CF66450367ECC5E9377E67493897EA0DF44。
创建后与来源Git blob逐字节一致；历史正文中的“当前”和“下一项”仅指该冻结时点。

## 补充机器证据

- [边界donor表示检查](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_194413__analysis__cross__fem4-boundary-donor-representation/summary.json)：原生potential_vc对已有25点的表示差，不授予全边界或轨迹资格。
- [真实中断资产恢复规划](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_193228__analysis__python__native-static-batch-continuation-acceptance/summary.json)：completed2／replay11，未续飞剩余粒子。
- [mesh3导出退役收据](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_132400__analysis__comsol__mesh3-rhob-beam-tube-export/solver_review_retirement_receipt.json)：只退役八张PA，原MPH和小证据保留；旧IOB须重导出、重装配。

运行输入、summary及manifest保留各自权威；本入口不复制完整运行清单或反写历史结果。
