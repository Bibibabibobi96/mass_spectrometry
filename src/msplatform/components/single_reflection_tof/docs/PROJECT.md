# Single-reflection TOF status

The provider is a downstream-only physical projection. It preserves the old frozen
`rf_oatof_functional_v1` geometry and electrode values; its containment envelope does
not establish collision-free geometry, field accuracy or native flight qualification.
OA and TOF ground groups remain distinct component identities; their explicit common
potential or electrical connection must be supplied by the Assembly/drive authority.

In the frozen representative design, detector and OA shield overlap: the existing
shape query reports `interior` for both legacy members `accelerator/grounded_shield`
and `detector` at `[58, 0, -0.5]` mm. The OA shield has axis x = -14.013621843807044 mm,
outer/inner width 148/140 mm and z = [-31.929186803411028, 278.07081319658903] mm;
the detector has center x = 69.01362184380704 mm, radius 40 mm and z = [-1, 0] mm.
Both belonged to legacy `common_ground`; matching voltage does not establish mechanical
legality. This migration preserves that geometry and does not silently move either body.
Native acceptance and any physical change require separate evidence and decision.


## 分体原生消费进展（2026-11-27）

SIMION分体编译/模型/求场计划/连续原birth追踪软件入口已消费本provider；
精确代码入口、负例与实际验证范围见[架构迁移记录](../../../../../docs/development/architecture-migration.md)。
两组件与原RF上游三组件的原冻结网格可编译；尚无本分体SIMION Refine/Fly资格。
旧OA–TOF跨组件重新释放已在公共track和planner按真实scope拒绝；其他C链保持原边界。
已知detector与OA shield重叠仍保留，不因同地而推导无碰撞。
