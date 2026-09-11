# 横置螺旋灯丝 Wehnelt 电子枪

本项目研究面向 EI 离子源的横置螺旋灯丝热电子发射与收集。当前状态、资格和开放任务以
[PROJECT](docs/PROJECT.md) 为准。

## 按任务阅读

| 任务 | 入口 |
|---|---|
| 开始项目工作 | [仓库 README](../../README.md) → [PROJECT](docs/PROJECT.md) |
| 构建、模型树与 GUI 验收 | [COMSOL 实施说明](docs/COMSOL.md) |
| 物理输入与数值模式 | [baseline](config/baseline.json)、[numerical_modes](config/numerical_modes.json) |
| 生成唯一 MATLAB 输入 | [resolve_contract.py](analysis/resolve_contract.py) → [resolved_model.json](config/resolved_model.json) |
| 项目发现与可执行能力 | [project.json](config/project.json)、[execution_profiles.json](config/execution_profiles.json) |
| 静态检查 | [verify_project.ps1](verify_project.ps1) |
| 选型及旧谱系 | 下方历史索引；[旧脚本目录说明](legacy/README.md) |

## 执行与产物

从本项目目录运行 `./run_build_only_smoke.ps1 -RunId <run_id>`，使用显式且符合仓库合同的新运行身份。
该入口只执行已注册的构建检查；参数、失败收尾、三阶段职责及输出判据见 COMSOL 实施说明。
当前构建能力不代表粒子求解、收集效率或 Candidate/Formal 资格。

新产物进入 `artifacts/projects/transverse_helical_filament_wehnelt_electron_gun/runs/<run_id>/`。
旧谱系与改名前资产按 [PROJECT](docs/PROJECT.md#产物边界) 及 descriptor 只读定位。
旧轴向灯丝的 phase5 扫描不能作为横置灯丝的参数结论。

## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260713__pre-transverse-wehnelt-lineages](docs/history/20260713__pre-transverse-wehnelt-lineages.md)
- [20260728__pre-document-consolidation-project](docs/history/20260728__pre-document-consolidation-project.md)
- [PROJECT_HISTORY](docs/history/PROJECT_HISTORY.md)

</details>
