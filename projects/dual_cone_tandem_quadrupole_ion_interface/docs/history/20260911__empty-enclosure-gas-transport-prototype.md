# 双锥空包络气流与气体辅助传输原型记录

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> 2026-09-11 只读归档；当前资格见 [PROJECT](../PROJECT.md)。

来源基线 `45a6741550aae5cbb009615896d16ef6d20618a2` 的 COMSOL/SIMION 实施文档。
此处保留当时的已完成尝试和结果；本次整治未重新运行或复核原始场／粒子输出。

## 气流求解过程

本机已确认 COMSOL 6.4 Build 293 与 LiveLink 可以启动。默认全耦合 Newton 及瞬态压力缓降均在大压比下失败，因此当前实现采用 High Mach Number Flow 对稳态问题默认支持的伪时间/CFL continuation，并对出口压力作参数 continuation；只有最终 `400 Pa` 解完成并通过质量守恒检查才产生合格场。失败报告保留在工作区 artifacts，入口严格保持 `STATUS=FAIL`。

2026-09-08 的真实 COMSOL 6.4 运行已校正轴对称速度映射（径向 `u`、轴向 `w`），并依次验证阻塞入口、亚声速定压出口、压力 continuation、阻尼 segregated、CFL 伪时间和常数氮气输运。`20260908_axisymmetric_gas_flow_pseudotime6` 在强制全后端亚声速的出口附近产生速度残差 `NaN`，因此没有导出 CSV、没有 canonical 场，也没有下游 SIMION 轨迹声明。该失败只否定了不一致的全亚声速出口设置，不否定用户确认的理想 `400 Pa` 恒压储槽代理。

2026-09-10 又以同一全后端 `400 Pa` 边界真实运行 Hybrid outlet；API 与模型构建通过，但求解仍在后端附近产生 `u/w` 残差 `NaN`。该历史 run 保持失败关闭；`uniform_rear_gas_field.json` 规定的均匀后端场只作快速对照，不得称为 CFD 结果。

同日加入 `z=110.22..110.72 mm` 孔板的 CFD 解虽完成 continuation，但进出口质量流量差 `3.82%`，被 `1%` 门禁拒绝。按最简模型边界，随后只从 CFD 中排除孔板阻塞、仍将孔板保留在 SIMION；`20260910_z120_empty_cfd_comsol` 对纯氮气完成至 `z=120 mm / 400 Pa`，质量流量差 `0.848%`、最大马赫数 `4.52`，通过并导出带哈希的场。该结果只支持空包络 Prototype，不支持孔板气动效应声明。


## 原型粒子结果

真实 COMSOL 场 Prototype `20260910_z120_empty_cfd_simion_n100` 使用冻结 N=100 圆柱源完成：80 个离子到达 `z=119.75 mm`，到达束斑半径中位数 `0.240 mm`、95% 分位 `0.527 mm`。这些数值依赖暂定的 `100 V`、`1 MHz` 两段 RF 和空包络气流，只是筛选结果，不是仪器绝对传输率。
