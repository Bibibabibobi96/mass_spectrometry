# 102.4 mm 间隙的 manifest 绑定交接（N=116）

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

RECONSTRUCTION_STATUS: FACTS_RECOVERED; ORIGINAL_NARRATIVE_NOT_RECOVERABLE

## 冻结身份

此路径的原始正文未进入 Git；可恢复事实来自下列 manifest 绑定的历史 run。`N=116` 指重启到 oaTOF
单飞的预脉冲人口，而非初始 RF 源母群。它来源于上游
`20260820_215000__sim__simion__oct-terminal-10ev-h15-finalize-recovery-downstream__n5000`，并保留其 manifest、
事件、粒子表和元数据 SHA-256 于 cross-run `run_config.json` 中。

| cross-run | campaign | launched / detector | claim status |
|---|---|---:|---|
| `20260821_063000__sim__cross__gap102p4-post-pulse-full-ideal-zvz-residual-removed__n116` | `connector_gap_102p4_post_pulse_full_ideal_zvz_residual_removed_n116_v1` | 116 / 97 | `FUNCTIONAL_SCREEN_ONLY` |
| `20260821_070000__sim__cross__gap102p4-post-pulse-full-ideal-theory-working-point__n116` | `connector_gap_102p4_post_pulse_full_ideal_theory_working_point_n116_v1` | 116 / 97 | historical functional run |

前一行的完整事件 census 为 116 个预脉冲状态、107 个加速器 intermediate2 forward、97 个 local exit、
97 个 detector crossing。它保留了损失，未以共同命中子集替换分母。

## 可核查来源与限制

- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260821_063000__sim__cross__gap102p4-post-pulse-full-ideal-zvz-residual-removed__n116/{run_config,summary,run_manifest}.json`
- 退役合同：[`retired_campaigns/connector_gap_102p4_post_pulse_full_ideal_zvz_residual_removed_n116_v1.json`](retired_campaigns/connector_gap_102p4_post_pulse_full_ideal_zvz_residual_removed_n116_v1.json)

没有留存该交接的原始比较报告、时间峰统计或数值收敛材料，故不得把 97/116 的功能贯通误写为 gap=102.4 mm
的传输率、分辨率或工作点资格。
