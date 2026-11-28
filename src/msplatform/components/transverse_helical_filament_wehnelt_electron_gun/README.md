# 横置螺旋灯丝 Wehnelt 电子枪

本组件研究面向 EI 离子源的横置螺旋灯丝热电子发射与收集。当前状态、资格和开放任务以
[PROJECT](docs/PROJECT.md) 为准。

## 按任务阅读

| 任务 | 入口 |
|---|---|
| 开始组件工作 | [仓库 README](../../../../README.md) → [PROJECT](docs/PROJECT.md) |
| 构建、模型树与 GUI 验收 | [COMSOL 实施说明](docs/COMSOL.md) |
| 物理输入与数值模式 | [baseline](config/baseline.json)、[numerical_modes](config/numerical_modes.json) |
| 生成唯一 MATLAB 输入 | [resolve_contract.py](resolve_contract.py) → [resolved_model.json](config/resolved_model.json) |
| 组件发现与可执行能力 | [project.json](config/project.json)、[execution_profiles.json](config/execution_profiles.json) |
| 静态检查 | [wehnelt_verify.ps1](../../workflows/resources/wehnelt_verify.ps1) |
| 选型及旧谱系 | [历史索引](../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/README.md) |

## 执行与产物

注册 profile 直接调用现有公共 CLI：`python -m msplatform.cli wehnelt-build-only`。它消费编译后的
`--compiled-inputs`，并要求显式 `--execution-environment`、`--environment-profile`、`--workspace` 和
`--artifact-root`；实际编译命令由 `execution_profiles.json` 生成，不保留第二套 PowerShell owner。
CLI 加载真实 `ExecutionContext` 和 `ArtifactStore`，再调用公共 Python operation；run 身份由 Store
后端生成，不能把规划 run ID 当作原生生产 run ID。

The three stage implementations and contract helpers have one canonical owner in
[`msplatform.backends.comsol/matlab`](../../backends/comsol/matlab). The MATLAB
`build_wehnelt_model(resolvedContractPath, runDirectory)` wrapper retains the original intermediate MPH
chain. The Python `msplatform.backends.comsol.build_wehnelt_model(baseline, modes, mode_id=...,
evidence_particle_count=..., context=..., artifact_store=...)` operation freezes and protects its actual
inputs through the existing managed owner, builds all three stages and independently cold-reopens the final
model. The inlet count configures the unsolved model and does not create a particle realization. Parameters,
failure handling and stage/output criteria remain in the COMSOL implementation guide.
当前构建能力不代表粒子求解、收集效率或 Candidate/Formal 资格。

新产物只进入调用者显式选择的 ArtifactStore；旧组件 run 根、旧谱系与改名前资产按
[PROJECT](docs/PROJECT.md#产物边界) 及 descriptor 只读定位，不被新 Store 接管。
旧轴向灯丝的 phase5 扫描不能作为横置灯丝的参数结论。

## 目录职责与 History 索引

科学配置、解析器和当前文档由本组件唯一维护；原生构建阶段与公开 Python operation 位于
`src/msplatform/backends/comsol/`，注册组合入口位于 `src/msplatform/cli.py`，长期测试位于
`tests/components/transverse_helical_filament_wehnelt_electron_gun/`。
旧 `projects/transverse_helical_filament_wehnelt_electron_gun/` 已退出活动树，来源提交为
`7c272feb442945b2a415e1673a760e66ae098243`。

[历史索引](../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/README.md)集中列出已冻结实验、迁移和旧方案；需要追溯证据时按需进入。
