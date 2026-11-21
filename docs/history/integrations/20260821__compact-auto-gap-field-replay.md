# 单合同自动调度 gap×场复现

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY

## 范围

`connector_gap_field_matrix_compact_auto_replay_v2` 在一个扁平化实验合同中顺序执行了
2026-08-22 的 23 个最终成功 gap×场行。它是 Functional replay 和调度器回归，不构成
Formal、优化或数值收敛声明。

## 调度与执行

- 外层商业 SIMION 始终串行；每次只启动一个 experiment。
- 合同冻结 0.1 GiB 可用内存预留、5% 内存安全系数、每批 2 CPU cores 与 2 cores 预留。
- 批数由冻结资源 receipt、运行时可用内存和 CPU 容量共同决定；23 个实际求解均选择 3 个独立粒子批。
- 所有 23 个逻辑实验均有成功 parent manifest。第 15、21 行在 PA cache 元数据兼容边界处于轨迹求解前
  失败；原失败证据保留，分别由 `__r05` 和 `__r01` 不可覆盖恢复运行成功完成。

## 基线比较

对每行以去除 `_compact_auto_replay_v2` 后的历史 experiment identity 查找已冻结的成功基线，并比较
SIMION child summary 的 `census.detector_crossing` 与
`pulse_effective_peak.mass_resolution`：23/23 完全一致（质量分辨率绝对差 < `1e-9`）。
这证明合同压缩和自动批处理没有改变该矩阵的这两个终端结果。

## 证据

- 合同：[`connector_gap_field_matrix_compact_auto_replay_v2.json`](retired_campaigns/connector_gap_field_matrix_compact_auto_replay_v2.json)
- 新运行：`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260822_210000__sim__cross__gap-field-replay-01__n482` 至 `...210022__sim__cross__gap-field-replay-23__n116`
- 首行资源 receipt：`.../20260822_210000__sim__simion__rf-oatof-single-flight-gap12p8__n482/logs/resource_usage.json`

## 限制

该验证没有重新赋予历史矩阵 Formal、Candidate 或跨求解器资格。PA 缓存兼容处理仅保证合同冻结的
schema-v3 generation 被实际使用；它不将缓存本身视作来源 run 或物理证据。
