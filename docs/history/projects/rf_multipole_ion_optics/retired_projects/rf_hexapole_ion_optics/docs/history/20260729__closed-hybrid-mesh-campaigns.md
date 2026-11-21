# 六极杆已关闭 hybrid mesh campaign 归档

DOC_STATUS: ARCHIVED_READ_ONLY

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

## 归档结论

同名载荷目录冻结已经终止的 P1–P4 hybrid mesh pilot 与 D1 build-only diagnostic
预登记。P1 在场求解前触发拓扑门禁；D1 在`mesh.run`前因诊断实现错误结束，并耗尽零重试授权。
两项 campaign 均不再属于活动 qualification、runtime profile 或 solver numerics。

| 原仓库路径 | 历史载荷 | SHA-256 |
|---|---|---|
|`config/qualification/comsol_hybrid_mesh_pilot_preregistration.json`|[`comsol_hybrid_mesh_pilot_preregistration.json`](20260729__closed-hybrid-mesh-campaigns/comsol_hybrid_mesh_pilot_preregistration.json)|`9C86407EB507E1828D59606D64D60383CF72EB377A85DBA07D76E2F84F662FD0`|
|`config/qualification/comsol_hybrid_mesh_build_diagnostic_preregistration.json`|[`comsol_hybrid_mesh_build_diagnostic_preregistration.json`](20260729__closed-hybrid-mesh-campaigns/comsol_hybrid_mesh_build_diagnostic_preregistration.json)|`4ADFC47FCAADF7EBF846E6599DB07B42AEA2D2EA6456D416B877C9CD06982C6F`|

统一校验入口为
[`SHA256SUMS.txt`](20260729__closed-hybrid-mesh-campaigns/SHA256SUMS.txt)。
公共 hybrid mesh 与`mesh_build`实现继续作为已修复但未获商业运行授权的能力保留；归档载荷
不得直接执行，也不得恢复已关闭 profile。新的商业诊断必须另立预登记、runtime profile 和预算。
