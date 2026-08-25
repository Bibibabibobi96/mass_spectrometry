# 历史占位文档恢复审计（2026-08-25）

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

## 审计方法

本审计扫描全仓库 `docs/history/**/*.md` 的空文件、8 行及以下文件和仅含归档占位语句的文件；再对每个
候选依次检查 Git 路径历史、所有可达 ref、`git fsck --no-reflogs --unreachable` 的提交/树/blob，以及本机
artifacts、版本化 campaign 和 SHA-256 清单。只在存档能唯一支持的范围内重建事实；没有来源的原叙述一律
标为不可恢复。

## 结果

扫描到 100 个历史 Markdown，其中 7 个为实际占位条目，另有 1 个长文因开头使用常见归档措辞而被误报。

| 路径范围 | 项目数 | 结果 |
|---|---:|---|
| `integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/` | 6 | 5 份事实已由运行 manifest、矩阵与退役合同重建；1 份退役合同索引补全为可导航索引。 |
| `docs/history/20260820__repository-deep-architecture-contract-audit.md` | 1 | 原始叙述、冻结输入和唯一结果均未找到；保留不可恢复说明，不编造审计结论。 |

其余项目的历史 Markdown 在本次扫描中没有空文件或仅占位文件。

## 结论边界

所有恢复条目均是 `ARCHIVED_READ_ONLY` 和 `DEVELOPMENT_ONLY` 的历史索引。它们不恢复活动 campaign
资格、数值收敛、优化结论或 Paper 1 锁定证据。历史 run 未保持共同母 cohort 或 ID 配对时，恢复文本明确
禁止将其解释为因果性能比较。
