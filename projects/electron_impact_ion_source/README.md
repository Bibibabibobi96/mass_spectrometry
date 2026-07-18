# 电子轰击离子源项目

正式源脚本位于`comsol/`，通过[`ei_source_paths.m`](ei_source_paths.m)把新生成的试验 MPH
写入项目 artifact 的`scratch/comsol/`，结果写入`results/comsol/`。迁移前位于通用模型
目录的三个`MS_Stage1_EISource_*`模型已归入本项目`models/comsol/archive/`。

本项目目前只有一个软件实现，因此当前参数、状态和项目专属错误直接维护在本 README；COMSOL
调用事实和跨项目方法按仓库根 README 路由。引入第二个求解器或 CAD 后，再建立
`docs/PROJECT.md`与对应软件文档，不创建空占位文件。
