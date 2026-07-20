# 电子轰击离子源项目

开始任务先读仓库根[`README.md`](../../README.md)，再读本项目当前状态
[`docs/PROJECT.md`](docs/PROJECT.md)。只有实际修改模型时才进入`comsol/`；本项目目前没有独立
软件实施文档，已确认的软件事实暂记在PROJECT，达到足够规模后再拆分`docs/COMSOL.md`。

当前实现入口是[`comsol/ms_stage1_ei_source.m`](comsol/ms_stage1_ei_source.m)，路径解析器为
[`ei_source_paths.m`](ei_source_paths.m)。大型模型与结果位于
`artifacts/projects/electron_impact_ion_source/`，不进入Git。当前正式/候选资格、已知限制和下一步
只以PROJECT为准，本入口不复制具体参数或运行结论。

机器身份、能力边界和当前`prototype`成熟度由[`config/project.json`](config/project.json)声明；
它用于项目发现，不把现有脚本自动提升为候选或正式资产。
