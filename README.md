# 质谱仪设计与仿真平台

Mass Spectrometer Design and Simulation Platform

本仓库持续积累可复用的质谱部件与仿真能力，支持部件独立研究和仪器组合模拟。离子轨道、
电磁场、气压、分子流及所需耦合物理按实际需求与证据逐步扩展。部件设计由项目维护，
结构变体分别验证，实例与跨项目组装由配方表达，求解器承担各自适用的计算。
这是[建设定位](docs/VISION.md)，不表示任意组合或物理域已经可用；当前能力与资格查相应状态页。

## 开始任务

1. Agent先读[执行规则](AGENTS.md)，再从下表选择项目或[组装入口](integrations/README.md)。
2. 项目任务读目标README和`docs/PROJECT.md`；组装任务读`docs/INTEGRATION.md`，确认能力、资格、限制和开放动作。
   公共工具任务从[公共机制](common/README.md)进入最近的实现说明，不创建占位PROJECT。
3. 按[文档任务目录](docs/README.md)选择本次需要的理论、操作或规范；修改或审查代码先读
   [开发标准阅读导航](docs/DEVELOPMENT_STANDARDS.md#阅读导航)。
4. 创建文件、运行或归档前查[生命周期](docs/LIFECYCLE.md)，执行与提交前查[操作指南](docs/OPERATIONS.md)。

项目入口和状态页提供最少阅读路径，不要求通读全部理论、软件手册或历史。
涉及已有结果的物理解释时，仍须读取相关模型的假设与适用域。

## 项目导航

项目身份和能力发现的机器权威是[生成注册表](config/project_registry.json)，来源为各项目`config/project.json`。
下表提供稳定导航；同一项目中的结构变体分别保存配置、能力和资格，不能相互继承验证结论。

| 设计项目 | 入口与可见变体 |
|---|---|
| RF多极杆离子光学 | [项目](projects/rf_multipole_ion_optics/README.md)；[四极杆](projects/rf_multipole_ion_optics/variants/quadrupole/README.md)、[六极杆](projects/rf_multipole_ion_optics/variants/hexapole/README.md)、[八极杆](projects/rf_multipole_ion_optics/variants/octupole/README.md) |
| 正交脉冲加速器 | [二区／三区加速器](projects/orthogonal_accelerator/README.md) |
| 单次反射正交加速飞行时间质量分析器 | [oa-TOF](projects/single_reflection_oa_tof_mass_analyzer/README.md) |
| 开放路径平行镜双条带多次反射飞行时间质量分析器 | [MR-TOF](projects/parallel_mirror_dual_stripe_mr_tof/README.md) |
| 双压力区矩形射频离子处理器 | [Ion Processor](projects/dual_pressure_rectilinear_ion_processor/README.md) |
| 双锥串联四极杆离子传输接口 | [双锥接口](projects/dual_cone_tandem_quadrupole_ion_interface/README.md) |
| 开孔长管电子轰击离子源 | [EI离子源](projects/apertured_tube_electron_impact_ion_source/README.md) |
| 横置螺旋灯丝Wehnelt电子枪 | [电子枪](projects/transverse_helical_filament_wehnelt_electron_gun/README.md) |

## 按问题查阅

模拟入口分为[分段接续模拟](integrations/README.md#分段接续模拟)和
[联合连续模拟](integrations/README.md#联合连续模拟)。选择表、完整命令及实际场范围只在组装入口维护。

| 要解决的问题 | 入口 |
|---|---|
| 选择部件、配置实例、组装和联合研究 | [组装入口](integrations/README.md)、[当前集成状态](integrations/docs/INTEGRATION.md) |
| 文件放哪里、项目怎样划分、谁拥有知识 | [仓库架构](docs/REPOSITORY_ARCHITECTURE.md) |
| 查理论、验证方法、软件操作、规范或参考资料 | [文档任务目录](docs/README.md) |
| 查公共API、运行机制和机器合同 | [公共机制导航](common/README.md) |
| 查长期目标和建设顺序 | [愿景](docs/VISION.md)、[路线图](docs/ROADMAP.md) |
| 追溯已完成全仓审计 | [审计索引](docs/AUDITS.md)；项目历史从所属README进入 |

## 工具链与执行入口

版本、启动方式、连接生命周期及验证层级只在[操作指南](docs/OPERATIONS.md#工具链与执行入口)维护。
本页保留此路由，便于从既有入口进入唯一权威。

## 维护文档

更新事实时修改它的唯一正文；入口只负责导航。理论随其模型所有者保存，公共方法、工具经验和
外部资料由文档任务目录统一发现。[文档维护规则](docs/REPOSITORY_ARCHITECTURE.md#文档维护与阅读体验)
定义归属与阅读体验，[历史规则](docs/LIFECYCLE.md#history-冻结条件)区分可维护索引、冻结证据和普通Git编辑历史。
验证和完成条件见[操作指南](docs/OPERATIONS.md#任务完成定义)。
