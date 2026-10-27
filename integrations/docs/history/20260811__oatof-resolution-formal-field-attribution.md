# oaTOF分辨率Formal场归因（2026-08-11）

DOC_STATUS: ARCHIVED_READ_ONLY

本文冻结八极杆连续单飞分辨率与Formal `R=47662.02`差距的受控归因里程碑。当前结论只由
integration的[`INTEGRATION.md`](../INTEGRATION.md)
维护；本文不作为活动参数权威。

## 问题与共同合同

Formal SIMION已由新CPU同资产run
`20260810_121500__benchmark__cross__cpu-formal-n1000`精确复现1000/1000、`R=47662.02`。连续八极杆
共同队列取绝对RF稳态源中同时具有`pre_pulse_state`和基准探测事件的996个粒子；所有反事实均使用
同一粒子身份、同一脉冲时刻、同一峰算法、trajectory quality 8、每RF周期160步和5批受管并行。
PA只从验证过的Formal发布或内容寻址cache复制到run-local目录，不重建或修改Formal资产。

## 受控矩阵

最终成功run为
`20260811_003000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000`：

|臂|源/场唯一变化|命中|直接FWHM (ns)|R|峰模态|
|---|---|---:|---:|---:|---:|
|当前重启控制|当前pre-pulse状态；当前frontend与反射器|996/996|1.9828|19349.02|1|
|只匹配Formal z形状|z σ由0.4899降至0.2884 mm|996/996|1.4093|27223.97|1|
|当前布局理想源|`1×1×2.2 mm`、当前10 eV、纯+x|996/996|3.4132|11240.50|3|
|Formal聚焦桥接|Formal 1 mm形状、当前10 eV、纯+x、Formal反射器；当前frontend|996/996|3.1933|12014.18|2|
|严格Formal场桥接|上一行只把槽3改为Formal accelerator|996/996|0.3322|115493.38|2|
|z-vz完全压缩上界|当前状态只令z、vz各自为共同均值|996/996|0.3065|125159.97|2|

严格桥接与Formal release不完全同源：它仍为100 Da、约`10.0257±0.0472 eV`并把加速器平移到当前
轴位置，因此其双模`R=115493.38`不是Formal复现值、候选值或可优化目标。其用途是配对消融：与
`R=12014.18`行相比，源、反射器、脉冲、样本和分析均相同，唯一改变是槽3三维PA；9.61倍差异证明
combined frontend加速器场/离散是目前阻挡整体链复现高分辨率的最大因素。

## 已排除的误读

- Formal 5 eV源不能直接平移到当前布局。加速器轴相对Formal向上游移动约20.2 mm，而检测器仍由布局
  对称关系放置；该臂虽996/996离开加速器，只有301/996到达检测器，695个在返回近端罩面终止。
- 在当前frontend场内，z收窄能把R提高40.70%，但纯+x零角度理想源反而降低R；因此不能把总差距
  简化为“角度太散”，当前有利的z-vz相关性也不能直接删除。
- 当前2.2 mm反射器重构不是唯一原因：切回Formal反射器而保留当前frontend仍只有`R=12014.18`。
- 0.20/0.15/0.125 mm各向同性frontend序列此前得到`R=19176.67/18528.85/17685.52`且未收敛；
  它不能排除Formal accelerator的`z=0.05 mm`加速方向离散差异。

## 失败关闭与实现边界

严格桥接的两个前置run保留为失败证据：

- `20260811_000000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000`：combined Program向Formal
  1–9电极PA写10–19电极，启动前失败；
- `20260811_001000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000`：Formal Program正确拒绝
  combined-only的`single_flight_rf_steps` CLI变量。

`20260811_002000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000`完整成功但严格臂0命中；根因是
把ION的绝对TOB又加到脉冲时钟，脉冲延后到约91.1 µs。最终run恢复SIMION原生TOB语义后闭合。
这些run不提供物理负结论，也没有用于最终峰值。

## 下一步

保持“多极杆+加速器为一个整体PA”拓扑，先建立以Formal局部加速器场为oracle的数值profile。首选比较
横向约0.20–0.25 mm、加速方向0.05 mm的各向异性整体PA与当前各向同性PA；同时冻结同一理想桥接源，
比较repeller–grid1、grid1–grid2轴场、边缘场、加速器出口相空间和R。只有场与峰宽同时向Formal桥接
收敛后，再把真实八极杆稳态源接回并优化z-zv接受；不能先继续调源宽、脉冲相位或反射器来补偿错误场。
