# COMSOL 官方文档索引

本目录存放COMSOL官方PDF手册，作为离线原始参考。它们不是本项目的经验文档，不建议在每次任务开始时全文阅读；只有当`../docs/COMSOL_API.md`、`../docs/COMSOL_DEBUGGING.md`或项目文档没有覆盖某个问题时，再按问题类型查对应PDF。

| 官方PDF | 页数 | 作用 | 什么时候查 |
|---|---:|---|---|
| `LiveLinkForMATLABUsersGuide.pdf` | 约400 | LiveLink for MATLAB用户指南：MATLAB连接COMSOL Server、`mph*`函数、几何/网格/物理场/求解/结果/批处理等MATLAB侧工作流。 | MATLAB脚本怎样加载/保存模型、运行求解、导出数据、循环扫描、读取结果、连接服务端不清楚时优先查。 |
| `COMSOL_ProgrammingReferenceManual.pdf` | 约1234 | COMSOL Multiphysics编程参考手册：最完整的Model API对象、属性、feature/tag、geometry/mesh/physics/result/solver命令参考。 | 需要确认某个`model.xxx()`、feature类型、属性名、合法取值、选择集/几何/结果节点API时查；这是底层权威索引。 |
| `ApplicationProgrammingGuide.pdf` | 约326 | COMSOL Application Builder/Method编程指南：Model Object入门、Java语法、方法、应用对象、调试/GUI/文件等应用编程工具。 | 主要查Model Object基本概念、`set/get/setIndex`用法、录制代码、方法编辑器、Application Builder相关问题；日常MATLAB脚本优先级低于LiveLink手册和Programming Reference。 |
| `ACDCModuleUsersGuide.pdf` | 约540 | AC/DC Module用户指南：静电场、电流、磁场、线圈、边界条件、研究类型和AC/DC物理理论。 | 做电子枪、静电透镜、反射镜电场、磁场/线圈、Wien filter、磁扇形场等AC/DC物理设置或理论判断时查。 |
| `ParticleTracingModuleUsersGuide.pdf` | 约414 | Particle Tracing Module用户指南：Charged Particle Tracing、粒子释放、力、碰撞、空间电荷、计数器、累积器、轨迹图和相关理论。 | 做CPT粒子追踪、热发射/初速度分布、碰撞、粒子计数、探测器统计、轨迹显示和质量谱后处理时查。 |

## 维护规则

- 新增官方COMSOL PDF时，先放进本目录，再在上表新增一行，写清楚“解决什么问题”和“什么时候查”。
- 不要把官方手册全文或大段摘录复制进项目经验文档；经验文档只记录本项目已经验证过的API写法、调试策略和项目结论。
- 如果从官方文档中确认了一个本项目常用的具体调用或陷阱，应把提炼后的结论写入`../docs/COMSOL_API.md`或`../docs/COMSOL_DEBUGGING.md`，并保留简短来源说明。
