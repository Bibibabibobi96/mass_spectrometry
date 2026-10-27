# oaTOF 连接间隙相空间趋势记录

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

RECONSTRUCTION_STATUS: FACTS_RECOVERED; ORIGINAL_NARRATIVE_NOT_RECOVERABLE

## 可恢复的矩阵

原正文不在 Git 可达或不可达对象中：该路径于 `e91652b` 作为空文件建立，`dfa1c1e` 只恢复了占位标题。
不过 `resolution_matrix_20260820/matrix.json` 保留了 0--102.4 mm 连接器扫描的结构化摘录。下表摘录其中
真实场、full-domain 诊断行；数字是 detector cohort 的 direct KDE FWHM，不是共同 ID 的相空间方差比较。

| gap (mm) | detector N | FWHM (ns) | R | KDE modes |
|---:|---:|---:|---:|---:|
| 0.0 | 819 | 2.0754 | 7548 | 1 |
| 3.2 | 751 | 2.2219 | 7051 | 1 |
| 6.4 | 696 | 2.3553 | 6651 | 1 |
| 12.8 | 481 | 2.5049 | 6254 | 2 |
| 25.6 | 199 | 3.0480 | 5140 | 1 |
| 51.2 | 72 | 3.0670 | 5108 | 2 |
| 102.4 | 95 | 3.2202 | 4865 | 2 |

## 正确解释

该早期矩阵的 `comparison_warnings` 明确为 `comparison_contract_id_differs`，且 gap 增大时 detector N 从
819 变为 95。因而它没有保持同一预脉冲母群、相同传输率或共同 ID；不能证明“gap 增大使随机
`z-vz`残差降低”，也不能用于 gap 优化。它只保存了一个值得重新审计的观察：连接器长度同时改变了传输、
末端相空间和峰形。

后续无 RF 的按-gap功能矩阵见
[`20260822__post-pulse-no-rf-per-gap-theory-field-matrix.md`](20260822__post-pulse-no-rf-per-gap-theory-field-matrix.md)。
它的 FWHM 趋势不同，同样不能与本表合并为优化结论。

## 可核查来源

- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/resolution_matrix_20260820/{inventory,matrix}.json`
- 各行冻结 `summary.json` 路径及 SHA-256 已包含在上述 `inventory.json`。
- 关联退役 campaign 位于 [`retired_campaigns/`](retired_campaigns.md)。
