# RF→oaTOF single-flight run所有权迁移（2026-08-15）

## 结论

新的RF→oaTOF joint single-flight run package及终态manifest统一归
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`。四/六/八极杆项目只提供冻结输入
lineage，不再是joint output owner。历史已发布在upstream项目目录中的single-flight run不移动、
不改写，只允许显式legacy reader兼容。本次不改变PA、场、轨迹积分、缓存物理或Formal状态，也未启动
SIMION。

## 单权威实现

- `runtime/run_single_flight.ps1`以单一`runProjectId`同时决定run package、manifest和PA cache项目；
  `run_config.project`写integration ID，并显式记录`upstream_project_id`。
- `family_source_closure/adapter.ps1`在发布parent receipt前核验child manifest确实位于integration runs
  root，且project、run ID、role与single-flight mode完全匹配。
- `publish_run.py`的stage owner由execution strategy穷尽决定：`simion_single_flight`归integration，
  `staged_three_stage`归upstream，未知值失败关闭。
- full-domain assessment reader不根据文件路径判断新旧。当前child必须以integration project身份并显式
  指向expected upstream；legacy child必须以manifest/config的upstream project身份并由
  `upstream_source_identity.project_id`显式闭合。混合身份失败关闭，输出记录
  `ownership_lineage`。

历史artifact例证仍保持只读：既有single-flight child的manifest与run_config project均为
`rf_octupole_ion_optics`，run_config中的`upstream_source_identity.project_id`也明确为同一项目；它因此
命中legacy read-only分支，而不是成为新writer默认。

## Publication与入口审计

两份schema-v3 successor campaign共29行：long full-domain 5行、source/architecture/field matrix
24行。审计时29个integration parent run ID均不存在`run_manifest.json`与`execution_receipt.json`，两份
campaign source binding均为PASS，因此没有发布碰撞，也不需要制造v4 successor。旧schema-v1/v2
single-flight入口继续只读，`SolverAuthorized`仍要求schema-v3。

官方repository binding refresher只更新预期7份runtime publication文件：
`family_runtime_implementation.json`、五份family runtime binding与
`execution_adapter_profiles.json`；随后`--check`为PASS。

## 验证

- ownership、publisher、adapter与legacy reader focused tests：34/34 PASS。
- 两份活动schema-v3 successor逐行`ValidateOnly`：5/5与24/24，共29/29 PASS；只执行准备与合同核验，
  未启动求解器。
- current integration ownership、explicit legacy ownership与mixed/implicit identity失败关闭均有单测。
- integration full suite：345/345 PASS；`common/verify_changed.ps1` L1 PASS，其中integration gate同为
  345/345 PASS。
- CLOC 2.10（base `26a0e9d990d46b87f4f8fa6473a1f84122d11eed`→WORKTREE）PASS：total code
  `172421→175945`（+3524），production `126479→129928`（+3449），tests
  `45912→45987`（+75）。production增量含官方refresher重冻结的JSON publication内容；过滤口径为
  `common/report_cloc_delta.ps1`记录的仓库标准扩展名、artifact/generated/vendor/run排除和
  production/test分类规则。

本记录只证明run ownership、lineage和执行合同闭合，不新增分辨率或物理性能结论。
