# 开孔长管电子轰击离子源项目

本项目维护开孔电离管内电子轰击电离的可行性模型。装配用途、离子出生状态与可交接范围须先查
[当前状态](docs/PROJECT.md#当前物理边界)，不能仅凭“离子源”名称假定已有完整上游源。

## 按任务阅读

| 任务 | 入口 |
|---|---|
| 开始项目工作 | [仓库README](../../README.md) → [PROJECT](docs/PROJECT.md) |
| 理解物理范围与缺口 | [物理边界](docs/PROJECT.md#当前物理边界)、[开放任务](docs/PROJECT.md#开放任务) |
| 修改或构建COMSOL模型 | 下方源码与合同入口；已确认实施事实暂由PROJECT维护 |
| 查资格与证据 | [当前状态](docs/PROJECT.md#当前状态) |

## 合同与执行入口

当前实现入口是[`comsol/ms_stage1_ei_source.m`](comsol/ms_stage1_ei_source.m)，路径解析器为
[`ei_source_paths.m`](ei_source_paths.m)。新模型与结果写入
`artifacts/projects/apertured_tube_electron_impact_ion_source/`，不进入Git。重命名前的旧运行和归档
已按原manifest身份迁入该根的具名migration archive；不得在新身份下改写或晋升。当前正式/候选资格、
已知限制和下一步只以PROJECT为准，本入口不复制具体参数或运行结论。

机器身份、能力边界和当前`prototype`成熟度由[`config/project.json`](config/project.json)声明；
它用于项目发现，不把现有脚本自动提升为候选或正式资产。

物理输入只在[`config/baseline.json`](config/baseline.json)维护，数值/证据模式只在
[`config/numerical_modes.json`](config/numerical_modes.json)维护；解析器
[`analysis/resolve_contract.py`](analysis/resolve_contract.py)生成MATLAB唯一允许读取的
[`config/resolved_model.json`](config/resolved_model.json)。resolved 对应的证据范围见 PROJECT。项目静态门禁为
`.\verify_project.ps1`；仓库统一执行入口只在
[`config/execution_profiles.json`](config/execution_profiles.json)注册，不把内部数值模式表
冒充执行profile合同。
