# 匹配求场与轨迹对照里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

冻结日期：2026-10-15（Asia/Shanghai）。完整原文来自Git提交
`1f8613fd62b7cb11a748db534273d9ed6b52e402`的PROJECT，不混入其后两行152030“运行中”工作区标记。
原文“当前／下一步”只按该提交时点解释。当前状态见[PROJECT](../PROJECT.md)，导航见[项目README](../../README.md)。
本阶段完成匹配求场、导出及同源轨迹比较，不表示数值调查或整个物理目标完成。

## 原文身份

| 来源 | 只读载荷 | 字节数 | SHA-256 |
|---|---|---:|---|
| 上述Git提交的docs/PROJECT.md | [PROJECT.before.txt](20261015__matched-solve-and-trajectory-comparison/PROJECT.before.txt) | 24561 | `2d39dc02a66158a617e8be023638d4f68969339047cc6cc2969b91eb06531ed3` |

载荷按Git blob的UTF-8/LF字节逐字冻结；保留当时模型、参数、源、数值、失败链、证据链接与开放任务。
不修改任何旧history、run或重载荷。前阶段完整过程见[固定场与求解状态里程碑](20261015__fixed-field-reproduction-and-solve-state.md)。

## 本阶段证据与结论

| 运行 | 完成范围 |
|---|---|
| [150021匹配mesh2](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_150021__analysis__comsol__mesh2-from-stable-source/summary.json) | 复用成功模型、重绑既有mesh2；Q2/CG-AMG/rhob40000，32次CG、runAll819.263 s；无新网格 |
| [152030导出](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_152030__analysis__comsol__matched-mesh2-beam-tube-export/summary.json) | 同四窗，总1608.874 s、查询1546.783 s；success/full20与公共ready；未求场或飞行 |
| [154824受控N13](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_154824__sim__simion__matched-mesh2-fixed-u-controlled-n13/summary.json) | 原trial/调度器、1 worker、波次480.594 s；success/full24；0命中、10物理碰撞＋3拓扑拒绝 |
| [155820配对](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_155820__analysis__python__matched-fem-controlled-n13-pairing/summary.json) | 纯分析0.445 s；FEM间15项及native对照9项登记控制全部相等；不推断缺失的检测器结果 |

匹配两档FEM在首次P2后相对中心计时差为0、y差约2×10⁻¹⁰ mm；到target49为0.601675 ns／1.878743 mm。
旧混控比较为2.055357 ns／3.928290 mm，因此此前差异不能全部归因网格；
剩余差值也不是总误差界、额外峰宽或收敛证明。两档都0/13并不等价：六颗粒子更换碰撞部件。
细档native→匹配mesh2的target49差为7.687358 ns／14.634182 mm，native为13/13命中；
不按更高收集率或更高R选真值，不在各网格分别调压后声称固定输入收敛。

| target49诊断 | Ey斜率 ns/eV | 局部x偶响应 ns | 全幅x偶响应 ns |
|---|---:|---:|---:|
| 匹配mesh2 | +16.44406 | −0.180612 | +1.958104 |
| mesh3重求 | +17.44775 | +0.079818 | +2.559779 |

均为受控队列目标事件的响应，不是检测器FWHM、R或高斯宽平台资格。
原生高斯σEy=0.15／0.2 eV细档性能仍为有限工程参考，完整源表和限制保留在PROJECT；
COMSOL没有新的高斯束团性能。固定源、低压电极、几何和观察定义不变。

## 检索与未关闭边界

冻结原文“电场表示与数值资格”保存317 V/m、对称性改变、131251组装断言、
143250可重复性、40点分层查询、150021与旧mesh2／mesh3点差等完整上下文。
这些尝试分别回答求解状态、场表示及传播敏感性，不以一个控制标签代替精度证明。
实际消费仍为COMSOL标量电势规则采样→SIMION求导／插值／选窗，基础窗未知节点保持无效。

下一决策是从既有入口选择一次相同入口状态的单段传输对照，比较同出口状态；
归档时尚未启动，不新建网格、改压、另建追迹框架或开展高斯N100。
后续结论只更新PROJECT，不追加本只读里程碑。
