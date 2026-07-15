# RF 四极杆碰撞冷却项目

正式源脚本位于`comsol/`，通过[`rf_quadrupole_paths.m`](rf_quadrupole_paths.m)把新生成的
试验 MPH 写入项目 artifact 的`scratch/comsol/`，结果写入`results/comsol/`。历史
`test3`模型保存在`models/comsol/archive/`，尚未提升为正式基线。

本项目目前只有一个软件实现，因此当前参数、状态和项目专属错误直接维护在本 README；COMSOL
调用事实和跨项目方法按仓库根 README 路由。引入第二个求解器或 CAD 后，再建立
`docs/PROJECT.md`与对应软件文档，不创建空占位文件。
