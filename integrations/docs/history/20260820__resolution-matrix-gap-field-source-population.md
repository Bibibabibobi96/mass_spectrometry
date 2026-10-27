# 分辨率矩阵、间隙场与来源群体记录

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

RECONSTRUCTION_STATUS: FACTS_RECOVERED; ORIGINAL_NARRATIVE_NOT_RECOVERABLE

## 归档内容

Git 对象中没有本文件的原始叙述或结论；它在 `e91652b` 时为空。本次恢复以两个仍存在的结构化矩阵为唯一
来源：`resolution_matrix_20260820`（50 行）与 `resolution_matrix_20260822`（按 gap 汇总的无 RF 功能矩阵）。
二者都保存 field condition、source population、粒子数、峰宽、模式、来源 run 与 summary SHA-256。

`20260820` 矩阵的比较轴为 `gap_mm × {real,partial_ideal,full_ideal}_field ×
{full_domain,ideal_source_region}`，但自身标记 `comparison_contract_id_differs`。`20260822` 矩阵的行统一标为
`functional_screen_diagnostic_only`，使用按 gap 重建的 post-pulse restart 人口，比较合同为
`post_pulse_no_rf_per_gap_source_zvz_theory_dt40_v1`。

因此两个矩阵适合回答“哪些历史 run 和哪些场反事实存在”，不适合回答某个场或来源群体是否在公平条件下
提升分辨率。特别是 `ideal_source_region` 是条件子集，不能代替完整母 cohort 的命中/损失分母。

## 证据与重建限制

- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/resolution_matrix_20260820/{inventory,matrix}.json`
- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/resolution_matrix_20260822/{inventory,matrix}.json`
- 原始 campaign 的版本化字节与 SHA-256：[`retired_campaigns/`](retired_campaigns.md)。

存档中未找到原先的筛选规则、统计置信区间、共同 ID 配对表或最终推荐工作点。本文件不恢复这些不存在的
信息；新的 gap×field 结论必须重新冻结同一母 cohort、完整损失分类及预注册统计口径。
