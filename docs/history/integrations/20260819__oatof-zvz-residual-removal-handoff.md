# oaTOF ZVZ 残差移除交接记录

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

RECONSTRUCTION_STATUS: FACTS_RECOVERED; ORIGINAL_NARRATIVE_NOT_RECOVERABLE

## 可恢复的事实

Git 历史表明本文件在归档提交 `e91652b` 时即为空文件；`dfa1c1e` 只补回标题和归档标记。对所有可达与
不可达 Git 对象的审计均未找到原始正文。下列内容是从仍存在的、manifest 绑定的运行重新建立的事实索引，
不是原文复写。

在 51.2 mm 连接器上，历史 campaign
`connector_gap_51p2_post_pulse_restart_zvz_affine_residual_removed_dt40_n77_v1` 将预脉冲重启源中的仿射
`z-vz`残差置零；相同人口的全理想场后继 campaign 是
`connector_gap_51p2_post_pulse_restart_full_ideal_zvz_affine_residual_removed_dt40_n77_v1`。对应的 cross-run
分别为 `20260820_020000__sim__cross__gap51p2-post-pulse-restart-zvz-affine-residual-removed-dt40__n77` 与
`20260820_030000__sim__cross__gap51p2-ideal-zvz-resid0-dt40__n77`。二者均记录 `launched=77`、
`pre_pulse_state=77`、`detector_crossing=77`，状态为 `success`，但 `claim_status=FUNCTIONAL_SCREEN_ONLY`，且
`paired_analysis_status=NOT_RUN`。

102.4 mm 的同类全理想场试验为
`20260821_063000__sim__cross__gap102p4-post-pulse-full-ideal-zvz-residual-removed__n116`：116 个预脉冲状态进入，
97 个到达探测器。其同样仅标为 `FUNCTIONAL_SCREEN_ONLY`，没有配对统计分析。

## 可核查来源

- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260820_020000__sim__cross__gap51p2-post-pulse-restart-zvz-affine-residual-removed-dt40__n77/{run_config,summary,run_manifest}.json`
- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260820_030000__sim__cross__gap51p2-ideal-zvz-resid0-dt40__n77/{run_config,summary,run_manifest}.json`
- `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260821_063000__sim__cross__gap102p4-post-pulse-full-ideal-zvz-residual-removed__n116/{run_config,summary,run_manifest}.json`
- 已退役合同：[`retired_campaigns/connector_gap_51p2_post_pulse_restart_zvz_affine_residual_removed_dt40_n77_v1.json`](retired_campaigns/connector_gap_51p2_post_pulse_restart_zvz_affine_residual_removed_dt40_n77_v1.json) 与 [`retired_campaigns/connector_gap_102p4_post_pulse_full_ideal_zvz_residual_removed_n116_v1.json`](retired_campaigns/connector_gap_102p4_post_pulse_full_ideal_zvz_residual_removed_n116_v1.json)

## 不能由存档恢复的内容与边界

存档没有留下当日的残差定义、拟合阶数、残差量值、对照组计算或原作者的因果解释。因此本记录**不能**说明
“移除残差改善了多少”，也不能将该干预与连接器长度或三区控制方向建立定量因果关系。它只证明这些具名的
功能性反事实曾被运行并保留了完整人口分类。任何新的残差结论必须重新以冻结母 cohort 和配对统计生成。
