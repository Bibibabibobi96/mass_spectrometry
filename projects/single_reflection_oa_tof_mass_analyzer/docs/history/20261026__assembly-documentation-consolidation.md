# oa-TOF组装接口与当前状态文档收敛

DOC_STATUS: ARCHIVED_READ_ONLY

2026-10-26。本记录冻结本轮文档收敛前的PROJECT原始字节，保留提供者迁移、回归、具名原生验证、
失败前驱和当时开放任务。整治只改变知识组织，不新增物理结果、不改变Formal、run身份或原始证据。
原文中的“当前”“本次”“下一步”仅按冻结时点解释；现行项目资格见[PROJECT](../PROJECT.md)，
跨项目链路状态见[统一集成状态](../../../../integrations/docs/INTEGRATION.md)。

## 原始载荷与身份

- [原PROJECT原始字节](20261026__assembly-documentation-consolidation/PROJECT.txt)，SHA-256：
  `423F3F921F4494401F012CB3D5C0A0A6F714697F2C618EB8C111D38FDAEBDEC9`。
- [SHA256SUMS清单](20261026__assembly-documentation-consolidation/SHA256SUMS.txt)。

载荷只读，不作为活动执行入口。其中已退役integration链接和先行阶段的未完成状态保留原样，
不得将它们当作新的运行指令或用后继成功覆盖历史失败。

## 收敛范围与保留结论

原PROJECT前半包含已完成的几何／电压提供者、Candidate源码冻结、主机调度、共同场比较与CAD投影
迁移明细，以及静态回归数量和运行时间；当前页收缩为接口、资格与限制，操作仍由软件文档负责。

本快照保留以下独有证据及适用边界，查阅时可在原载荷内按标识定位：

| 标识／主题 | 冻结内容 |
|---|---|
| accelerator_side_shield、derive_simion_geometry、linear_ring_electrode_voltages | 提供者物理身份、显式孔径、几何及电压收敛；纯回归不代表新整机资格 |
| exit17、半cell、point_id | 冻结编译错误保真、网格舍入及完整场配对回归 |
| [组件几何保存／重开／STEP](../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261026_075441__test__comsol__geo/summary.json) | 组件几何保存、重开及STEP证据；不含上游多极杆、GUI、SolidWorks或Formal |
| [反射器API隔离](../../../../../artifacts/projects/instrument_assembly/runs/20261026_045007__test__simion__reflectron-api-isolation/summary.json) | CLI访问冲突保留failed；PA API调压／保存／重开成功，不能改写整个诊断终态 |
| `20261024_163000__test__comsol__finite-pulse-superposition-timecap1ns` | 有限脉冲微例程与四个失败前驱；只支持具名解析夹具 |
| [早期共同场容量拒绝](../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261024_210625__sim__comsol__192618-oatof-local-static-on-field/summary.json) | 早期matching源模型的容量拒绝与准备回归；不是求解器或物理FAIL |
| CPU复测、原Formal及理想源实验 | 历史性能与科学结论的原参数、身份和声明边界，不转授新配方资格 |

本次未删除原始run或二进制资产，也未改写旧history。理论与发表材料保持独立职责，不因收缩状态页合并。
