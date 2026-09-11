# 质谱仿真仓库

本仓库维护质谱仪器及离子／电子光学部件的参数化建模、跨求解器验证与可重建交付。
项目按物理问题组织；COMSOL、SIMION、MATLAB、Python和SolidWorks是实现工具。
本页是人类研究人员和Agent共用的导航入口，当前事实进入各项目状态页查询。

## 开始任务

1. Agent先读[执行规则](AGENTS.md)；所有使用者按下表选择项目或集成。
2. 读目标README和`docs/PROJECT.md`（集成为`docs/INTEGRATION.md`），确认能力、资格、限制和下一步。
3. 修改代码前完整读[开发标准](docs/DEVELOPMENT_STANDARDS.md)；建图前读[绘图标准](docs/PLOTTING_STANDARDS.md)。
4. 按任务读取对应软件操作或理论文档；只有追溯旧结论时进入history。
5. 创建文件、运行或归档前查[生命周期](docs/LIFECYCLE.md)，执行与提交前查[操作指南](docs/OPERATIONS.md)。

判断目录和知识归属时查[仓库架构](docs/REPOSITORY_ARCHITECTURE.md)。日常项目任务无需通读愿景、
路线图及全部软件文档；它们也不能替代机器输入与冻结证据。

## 项目导航

项目身份和能力发现的机器权威是[生成注册表](config/project_registry.json)，来源为各项目`config/project.json`。
下表只提供稳定导航，不复制成熟度、物理参数、当前结果或开放任务。

| 项目 | 入口 |
|---|---|
| 单次反射正交加速飞行时间质量分析器 | [oa-TOF](projects/single_reflection_oa_tof_mass_analyzer/README.md) |
| 正交脉冲加速器（二区／三区） | [加速器](projects/orthogonal_accelerator/README.md) |
| 开放路径平行镜双条带多次反射飞行时间质量分析器 | [MR-TOF](projects/parallel_mirror_dual_stripe_mr_tof/README.md) |
| RF四极杆离子光学 | [四极杆](projects/rf_quadrupole_ion_optics/README.md) |
| RF六极杆离子光学 | [六极杆](projects/rf_hexapole_ion_optics/README.md) |
| RF八极杆离子光学 | [八极杆](projects/rf_octupole_ion_optics/README.md) |
| 双锥串联四极杆离子传输接口 | [双锥接口](projects/dual_cone_tandem_quadrupole_ion_interface/README.md) |
| 开孔长管电子轰击离子源 | [EI离子源](projects/apertured_tube_electron_impact_ion_source/README.md) |
| 横置螺旋灯丝Wehnelt电子枪 | [电子枪](projects/transverse_helical_filament_wehnelt_electron_gun/README.md) |
| RF多极杆到oa-TOF的集成 | [连接与单飞工作流](integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md) |

## 按问题查阅

| 要解决的问题 | 权威入口 |
|---|---|
| 文件放哪里、谁拥有结论、何时提炼公共知识 | [架构与知识权威](docs/REPOSITORY_ARCHITECTURE.md) |
| baseline/resolved、软件职责、正式几何验收 | [参数派生](docs/REPOSITORY_ARCHITECTURE.md#参数权威与单向派生)、[GUI/CAD](docs/REPOSITORY_ARCHITECTURE.md#gui-与-cad-门禁) |
| run、artifact、缓存、归档、保留 | [生命周期](docs/LIFECYCLE.md) |
| 准备环境、启动工具、执行验证、提交 | [操作指南](docs/OPERATIONS.md) |
| 编码、配置分层、合同、进程和测试 | [开发标准](docs/DEVELOPMENT_STANDARDS.md) |
| 粒子样本、收敛、统计和跨求解器比较 | [验证方法](docs/VALIDATION_METHODS.md) |
| 科学绘图与图形证据 | [绘图标准](docs/PLOTTING_STANDARDS.md) |
| COMSOL API与故障定位 | [API参考](docs/COMSOL_API.md)、[排错](docs/COMSOL_DEBUGGING.md)、[官方资料](official_docs/README.md) |
| SIMION及长PA输入 | [SIMION参考](docs/SIMION_REFERENCE.md)、[公共实现](common/simion/README.md) |
| 多极杆解析理论 | [理论入口](docs/multipoles/index.md) |
| 端口、连接器与联合模拟 | [连接架构](docs/COMPONENT_CONNECTION_ARCHITECTURE.md) |
| 长期目标与跨项目阶段 | [愿景](docs/VISION.md)、[路线图](docs/ROADMAP.md) |
| 已完成全仓审计 | [历史索引](docs/AUDITS.md) |

## 工具链与执行入口

版本、启动方式、连接生命周期及验证层级只在[操作指南](docs/OPERATIONS.md#工具链与执行入口)维护。
本页保留此路由，便于从既有入口进入新权威。

## 维护文档

更新事实时修改它的唯一正文；不要在README、PROJECT和软件说明各追加同一进展。
[文档维护规则](docs/REPOSITORY_ARCHITECTURE.md#文档维护与阅读体验)说明内容、导航和排版职责，
[归档条件](docs/LIFECYCLE.md#history-冻结条件)说明何时收缩当前视图。
验证和完成条件见[操作指南](docs/OPERATIONS.md#任务完成定义)。
