# 开孔长管电子轰击离子源

本组件维护开孔电离管内电子轰击电离的可行性模型。装配用途、离子出生状态与可交接范围须先查
[当前状态](docs/PROJECT.md#当前物理边界)，不能仅凭“离子源”名称假定已有完整上游源。

## 固定阅读顺序

1. 先读仓库根 [README](../../../../README.md)。
2. 再读 [PROJECT](docs/PROJECT.md)。
3. 修改代码时按[开发标准阅读导航](../../../../docs/DEVELOPMENT_STANDARDS.md#阅读导航)读取通用章节及任务触发专题。

## 合同与执行入口

规范 COMSOL 构建器是 [`ms_stage1_ei_source.m`](../../backends/comsol/matlab/ms_stage1_ei_source.m)，配套解析合同加载器位于同一后端资源目录。构建器要求 `resolvedContractPath` 和显式 owner `runDirectory`，可选第三个参数为标签；不检索项目根或环境回退。新模型和结果只进入
`artifacts/projects/apertured_tube_electron_impact_ion_source/`，不进入 Git。

机器身份、能力边界和 `prototype` 成熟度由 [`config/project.json`](config/project.json)声明；物理输入只在 [`config/baseline.json`](config/baseline.json)维护，数值与证据模式只在 [`config/numerical_modes.json`](config/numerical_modes.json)维护。安装包解析器 `msplatform.components.apertured_tube_electron_impact_ion_source.resolve_contract` 生成 MATLAB 唯一允许读取的 [`config/resolved_model.json`](config/resolved_model.json)。当前 `build_only_smoke` fixture 不具 Candidate 证据资格。

静态验收入口为 `src/msplatform/workflows/resources/ei_verify.ps1`；公共 Python 入口是
`msplatform.backends.comsol.build_ei_model(baseline, modes, mode_id='build_only_smoke', context=environment)`。调用方传入上述两份可编辑文档及由 `execution.load_environment` 加载的环境；工程 profile 必须声明 `build_ei_model`，工具必须显式给出 `comsol_launcher` 和 `matlab_root`。该操作通过规范 LiveLink 启动器保存未求解模型，并在独立进程冷重开验证；能力查询只验证同一请求，不启动 COMSOL。

## 目录职责

```text
src/msplatform/components/apertured_tube_electron_impact_ion_source/
├─ config/                 # 唯一科学、数值、身份和执行定义
├─ resolve_contract.py     # 单向合同解析与失败关闭
└─ docs/PROJECT.md         # 当前物理、资格、证据和开放任务
src/msplatform/backends/comsol/
                            # 唯一公开操作与 MATLAB/COMSOL 实现
src/msplatform/workflows/resources/ei_verify.ps1
                            # 组件静态验收入口
tests/components/apertured_tube_electron_impact_ion_source/
                            # Python 与 MATLAB 长期验证及 fixtures
```

旧 `projects/apertured_tube_electron_impact_ion_source/` 已退出活动树。历史运行、原 ID、clock、6D 状态及失败/恢复语义不因源码迁移改写；历史证据按原 manifest 和 Git 来源追溯。当前资格和未闭合边界只以 [PROJECT](docs/PROJECT.md) 为准。
