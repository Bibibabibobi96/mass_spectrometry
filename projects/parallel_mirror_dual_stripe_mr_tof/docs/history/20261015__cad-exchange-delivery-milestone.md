# CAD交换与倾镜STEP交付里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

冻结日期：2026-10-15（Asia/Shanghai）。本页冻结CAD实施文档收缩前的完整WORKTREE原文，包含已有未提交事实。
来源身份为WORKTREE@`9e54679485c9b448a6b062a47ea289cfe22a39d2`；该提交只是捕获时HEAD，不能冒称原文已提交。
原文中的“当前／须／下一步”仅按冻结时点解释，当前操作见[CAD](../CAD.md)，状态见[PROJECT](../PROJECT.md)。

## 原文与身份

| 来源 | 只读载荷 | 字节数 | SHA-256 |
|---|---|---:|---|
| docs/CAD.md | [CAD.before.txt](20261015__cad-exchange-delivery-milestone/CAD.before.txt) | 24113 | `95d5ccf31cdfcf65e2801ac25c5bf5267727f2dc9a7f23bfe7211164696ea65f` |

原文为UTF-8、LF，共240行，逐字节保存，未重写历史相对链接。
此归档不修改CAD二进制、场、电压、原始用户档案或运行证据，不授新的几何或数值资格。

## 已关闭过程与检索映射

| 原文定位 | 保留内容 | 当前解释 |
|---|---|---|
| 当前冻结几何的工程外发，53独立STEP | 平行镜53件、7装配及同电位分组到独立件的演进 | 旧交付，不是当前倾镜40电极 |
| 3.770 mm³、1.2794 μm、5 μm | STEP转换、实际trim曲线比较、用户交换精度授权 | 仅交换边界，不是场或制造精度 |
| 39008／49089字符、seal-stopped-payload | 长参数和终态发布失败及零商业恢复 | 保留失败身份，不补授新商业验收 |
| BEM、Operations2、connected_contact_repair_details | 外部报告7组接触、同电势连接与COM绑定修复 | 不把体积无干涉等同没有共面接触 |
| FrozenMirrorPose、14镜 | 从平行镜原生件到冻结会聚位姿的受控交付 | 新镜重新冷读，旧曲线原件不变 |
| OmitMountingHoles、Parasolid、53/7 | 原生准确曲线、圆孔抑制、单位及冷读经验 | 原文可查，不作为当前批量操作步骤 |
| PublishCadRunPath、40个电极分组 | STEP-only字节再发布与Word分支边界 | 当前操作收缩到CAD实施说明 |

## 当前交付的证据边界

[163154发布记录][publication]为当前可引用交付身份：40电极、6参考面、1装配总览，ZIP共51成员。
它是零商业逐字节再发布；来源155743的摘要仍为failed，记录同时明确源manifest success与发布失败，
不能把原failed摘要改写为成功，或将恢复描述为一次新的商业冷读。
同电位局部连通组的合并不表示任意同电位或空间分离部件均合并。
第三方BEM实际消费、新倾镜英文Word与制造／仿真Formal资格仍未由这次发布授予。

[publication]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/delivery_publication.json
