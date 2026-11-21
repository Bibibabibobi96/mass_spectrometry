# 脉冲后无 RF 间隙理论场矩阵

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

RECONSTRUCTION_STATUS: FACTS_RECOVERED; ORIGINAL_NARRATIVE_NOT_RECOVERABLE

## 可恢复矩阵与范围

原说明在 Git 中不可恢复；`resolution_matrix_20260822/matrix.json` 仍保存了按 gap 的 post-pulse restart
功能矩阵。它冻结了 no-RF 的单飞设定、`source_zvz_theory`工作点和 `dt40` 数值身份。每一行都标记
`functional_screen_diagnostic_only`，不是实测 RF 导引、数值收敛或候选性能证据。

对 real-field / full-domain 行，矩阵中保存的结果如下：

| gap (mm) | detector N | direct FWHM (ns) | R | modes |
|---:|---:|---:|---:|---:|
| 0.0 | 819 | 2.0325 | 7710 | 2 |
| 3.2 | 751 | 1.9166 | 8177 | 1 |
| 6.4 | 697 | 1.7715 | 8847 | 1 |
| 12.8 | 481 | 1.4793 | 10594 | 1 |
| 25.6 | 199 | 1.2849 | 12190 | 1 |
| 51.2 | 77 | 1.1087 | 14182 | 1 |
| 102.4 | 96 | 0.6005 | 26083 | 1 |

该表记录的是历史观察，而不是“长 gap 一定更好”的结论：每个 gap 的 post-pulse 人口独立重建，探测人数从
819 变为 96；因此无法排除传输选择、源状态变化和有限样本的影响。要验证 gap 是否降低不可校正残差，
应在 OA 脉冲前对同一完整母 cohort 的 `z-vz` 条件模型及残差协方差进行 detector-blind 配对分析。

## 场反事实

矩阵还包含 accelerator-ideal、reflectron-ideal 和 full-ideal 行。以 51.2 mm full-domain 为例，real、
accelerator-ideal、reflectron-ideal、full-ideal 的 FWHM 分别为 1.10869、0.75998、1.10869、0.75998 ns；
102.4 mm 相应为 0.60047、0.52471、0.60047、0.52471 ns。这是冻结的 no-RF 功能反事实，不能外推为真实场
部件归因。

## 可核查来源

- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/resolution_matrix_20260822/{inventory,matrix}.json`
- 逐行 source、geometry、grid identity 和 summary SHA-256 在上述 `inventory.json`。
- 退役合同清单：[`retired_campaigns/connector_gap_post_pulse_field_matrix_n1000_v1.json`](retired_campaigns/connector_gap_post_pulse_field_matrix_n1000_v1.json)。
