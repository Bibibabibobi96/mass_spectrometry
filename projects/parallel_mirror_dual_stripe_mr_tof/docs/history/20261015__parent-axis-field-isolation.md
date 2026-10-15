# 父场组合、停止与单轴离散隔离

DOC_STATUS: ARCHIVED_READ_ONLY

本里程碑关闭父层固定25点的组合、停止及y/z拆轴矩阵；
不关闭整程轨迹或跨来源精度调查。当前动作见[PROJECT](../PROJECT.md)。

## 固定输入与问题

会聚倾斜双镜、接地线性Stripe、低压五次Stripe、C0完整装配及完整工作电压不变。
父层半域为[0,−242,−425]至[162.5,558,425] mm，x=0对称、其余五面0 V。
采用fractional表面；原父层间距0.50/1.00/1.00 mm、Refine convergence=1e−5 V。
25点来自已完成边界诊断，包含x=2面四组中心及差商邻点和其余边界点，不代表完整轨迹包络。

问题是父场是否已含慢向跨源差，以及组合、停止、y/z离散能否解释这些差异。
不改变电压来补偿数值变化，不按更接近COMSOL或命中更多选择真值。

## 已完成矩阵

各项来源均有冻结输入、原生日志、summary与manifest；表中时间为该次实测，不是后续保证。

| 对照与来源 | 唯一改动／结果 | 原生Refine／总耗时 |
|---|---|---:|
| [父层查询][query] | 当前组合父PA只读查询；四中心父−FEM慢向电势差商1.407–6.020 V/m，中央−父1.216–1.274 V/m | 无Refine／13.78 s |
| [同U直接父场][direct] | 当前完整电压直接编译；直接−组合最大电势差1.6982e−11 V，y/z差商差≤2.2737e−9／2.2737e−8 V/m | 843.10／886.708 s |
| [停止复核][stop] | 同网格独立副本1e−5→1e−6 V；最大电势增量8.4153e−11 V，四中心慢向差商增量≤2.2737e−9 V/m | 1397.75／1426.782 s |
| [z单轴][z] | z1.00→0.50 mm，x/y不变；四中心慢向差商增量+3.487–3.519 V/m | 1835.04／1892.045 s |
| [y单轴][y] | y1.00→0.50 mm，x/z不变；四中心慢向差商增量+0.03366–0.04721 V/m | 2331.42／2389.232 s |
| [实际API][api] | 三张父PA，经正常adapter的raw_sample串行查询；无局窗、Refine或飞行 | 无Refine／23.999 s |

直接父场4150次、停止复核6080次、z档4520次、y档5530次；各自终止Delta分别为1e−5、1e−6、1e−5、1e−5 V。
停止复核原生耗时比直接基线增加约65.8%，但所查点变化远不足以解释慢向跨源差。
日志Delta和输入停止参数都不是电势或轨迹误差上界。

组合父场采用同几何、同网格、同1e−5基场及四列10000 V归一化响应，G=1.002032603。
同U直接对照不支持将当前所查差异归因于场线性组合；不能推广到其他响应库。

## 电势接近不等于梯度改善

x=2面20点的原父−FEM平均电势为+1.334991 V，中央−FEM为−0.488858 V，中央−父为−1.823849 V。
z细化后父−FEM平均电势变为−0.128621 V，但四中心慢向差商跨FEM差增至4.926–9.507 V/m。
y细化后最大电势增量仅0.00272442 V，四中心跨FEM慢向差商仍为1.441–6.067 V/m。
因此不能用平均电势接近宣布梯度准确，也不能将父层与中央层差简单解释成同一常数偏移。

实际API采用已校准的field_vc逐轴除网格间距得到V/mm，再乘1000转V/m；
历史单位与支撑模板校准身份保存在[API运行输入][api]，不把电势小跨度差商假定为实际受力。

| 四中心实际场增量 | z细化 | y细化 |
|---|---:|---:|
| ΔEy范围，V/m | +3.485–3.517 | +0.0341–0.0467 |
| ΔEy与对应差商最大差，V/m | 0.00399342 | 0.00209398 |

z细化ΔEz的API与差商仍相差2.09–3.80 V/m，不能概括成全梯度一致。
全25点最大实际|ΔEy|分别9.87316／0.346551 V/m，与四中心范围不是同一统计口径。
原查询、直接父场及两单轴档25点均有限、所查邻近支撑无物理节点。

## 结论、保留与关闭边界

已测父层慢向差对z离散显著比y敏感，这不是仅由小跨度差商定义造成。
组合误差和已测点停止增量不足以解释跨源差，但不唯一证明父场或FEM谁正确。
API运行是无局窗的父层诊断投影，不是整机实际路由；本矩阵没有重建中央层／镜层或飞行，
不提供峰宽、R、收集率或全轨迹收敛资格。矩阵结束，不自动补yz组合或更细档。

停止试验的PA／surface完成公共退役，释放1,802,340,060 B；全部小证据及14份冻结输入保留，
可从直接父场基线重建。基线、z/y新场与API证据保留用于后续受控传递。
临时作者已沿公共机制清理，冻结run输入保留；不因归档删除仍有消费者的场。

[query]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_211107__analysis__simion__parent-boundary-fixed25-query/summary.json
[direct]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_212434__build__simion__direct-parent-fixed-grid/summary.json
[stop]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_215310__build__simion__parent-stopping-increment/summary.json
[z]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_222113__build__simion__parent-z050-fixed-u/summary.json
[y]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_225850__build__simion__parent-y050-fixed-u/summary.json
[api]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_234023__analysis__simion__parent-api-field-comparison/summary.json
